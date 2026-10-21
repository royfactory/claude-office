"""collector/collector.py 테스트. 표준 라이브러리 + pytest 만 쓴다(Python 3.9 에서도 돈다)."""
import json
import os
import re
import socket
import sys
import tempfile
import time
from unittest import mock

import pytest

from conftest import COLLECTOR_PY, load_module, posix_only

TS = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())   # 백그라운드 6시간 만료에 걸리지 않게 지금 시각


# ---------- 기록(jsonl) 만들기 ----------

def use(tid, name, ts=TS, **inp):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, text="ok", ts=TS):
    return {"type": "user", "timestamp": ts,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def said(text, ts=TS):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def notification(tid, status="completed"):
    return (f"<task-notification><task-id>x</task-id><tool-use-id>{tid}</tool-use-id>"
            f"<status>{status}</status><summary>done</summary></task-notification>")


def write(path, *recs, mode="a"):
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")


@pytest.fixture
def tr_file(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("")
    return p


def read(collector, path, *recs, detail="basic"):
    """기록에 줄을 붙이고 새 Transcript 로 읽는다."""
    write(path, *recs)
    return collector.Transcript(str(path)).read(detail)


# ---------- load_env ----------

def test_load_env_bom_crlf_quotes_and_keeps_existing(collector, tmp_path):
    p = tmp_path / "x.env"
    p.write_bytes(b"\xef\xbb\xbfT1_A=1\r\n# comment=no\r\nT1_B=\"two\"\r\nT1_C='three'\r\n\r\nnoequals\r\nT1_KEEP=file\r\n")
    with mock.patch.dict(os.environ, {"T1_KEEP": "env"}):
        collector.load_env(str(p))
        assert os.environ["T1_A"] == "1"            # BOM 이 키에 붙지 않는다
        assert os.environ["T1_B"] == "two"
        assert os.environ["T1_C"] == "three"
        assert os.environ["T1_KEEP"] == "env"       # 이미 있는 값은 덮지 않는다
        assert "# comment" not in os.environ and "noequals" not in os.environ


def test_load_env_missing_file_is_noop(collector, tmp_path):
    collector.load_env(str(tmp_path / "none.env"))
    collector.load_env(None)


# ---------- target_of / say_of ----------

def test_target_of_file_tools_give_basename_only(collector):
    assert collector.target_of("Read", {"file_path": "/secret/dir/app.py"}, "basic") == "app.py"
    assert collector.target_of("NotebookEdit", {"notebook_path": "/a/b/n.ipynb"}, "basic") == "n.ipynb"


def test_target_of_bash_uses_description_not_command(collector):
    assert collector.target_of("Bash", {"command": "rm -rf /x", "description": "Clean build"}, "basic") == "Clean build"
    assert collector.target_of("Bash", {"command": "/usr/bin/git status --short"}, "basic") == "git"
    long = collector.target_of("Bash", {"description": "x" * 100}, "basic")
    assert len(long) == 48 and long.endswith("…")


def test_target_of_search_terms_are_cut(collector):
    g = collector.target_of("Grep", {"pattern": "a" * 50}, "basic")
    assert len(g) == 32 and g.endswith("…")
    assert collector.target_of("WebSearch", {"query": "  many   spaces  "}, "basic") == "many spaces"
    assert collector.target_of("WebFetch", {"url": "https://example.com/p?q=1"}, "basic") == "example.com"


def test_target_of_detail_none_and_bad_input(collector):
    assert collector.target_of("Read", {"file_path": "/a/b.py"}, "none") == ""
    assert collector.target_of("Read", "not a dict", "basic") == ""
    assert collector.target_of("UnknownTool", {"x": 1}, "basic") == ""


def test_say_of_strips_markdown(collector):
    assert collector.say_of("## Title\n\n- **bold** item `code`\n> quote") == "Title bold item code quote"
    assert collector.say_of("```py\nx = 1\n```") == "py x = 1"
    s = collector.say_of("word " * 40)
    assert len(s) == 80 and s.endswith("…")


# ---------- Transcript ----------

def test_transcript_pending_tool_is_current_until_result(collector, tr_file):
    tr = read(collector, tr_file, use("t1", "Read", file_path="/a/b/c.py"))
    cur = tr.current()
    assert cur["tool"] == "Read" and cur["target"] == "c.py"
    write(tr_file, result("t1"))
    assert tr.read("basic").current() is None


def test_transcript_reads_incrementally_and_waits_for_whole_line(collector, tr_file):
    tr = read(collector, tr_file, use("t1", "Grep", pattern="foo"))
    assert tr.tools == 1
    line = json.dumps(use("t2", "Glob", pattern="*.py"))
    with open(tr_file, "a", encoding="utf-8") as f:
        f.write(line[:20])                 # 아직 덜 쓴 줄
    tr.read("basic")
    assert tr.tools == 1
    with open(tr_file, "a", encoding="utf-8") as f:
        f.write(line[20:] + "\n")
    tr.read("basic")
    assert tr.tools == 2 and sorted(v["tool"] for v in tr.pending.values()) == ["Glob", "Grep"]


def test_transcript_resets_when_file_shrinks(collector, tr_file):
    tr = read(collector, tr_file, use("t1", "Read", file_path="/a"), use("t2", "Read", file_path="/b"))
    assert tr.tools == 2
    write(tr_file, use("t3", "Edit", file_path="/c"), mode="w")
    tr.read("basic")
    assert tr.tools == 1 and tr.current()["tool"] == "Edit"


def test_transcript_recent_and_tool_count(collector, tr_file):
    recs = []
    for i in range(10):
        recs += [use(f"t{i}", "Read", file_path=f"/f{i}.py"), result(f"t{i}")]
    tr = read(collector, tr_file, *recs)
    assert tr.tools == 10
    assert [r["target"] for r in tr.recent] == [f"f{i}.py" for i in range(2, 10)]


def test_transcript_title_mode_and_last_words(collector, tr_file):
    tr = read(collector, tr_file,
              {"type": "ai-title", "aiTitle": "테스트 작성"},
              {"type": "permission-mode", "permissionMode": "plan"},
              said("첫 말"), said("**마지막** 말"))
    assert tr.title == "테스트 작성"
    assert tr.mode == "plan"
    assert tr.say == "마지막 말"
    write(tr_file, {"type": "custom-title", "customTitle": "내 제목"})
    assert tr.read("basic").title == "내 제목"


def test_transcript_detail_none_hides_words(collector, tr_file):
    tr = read(collector, tr_file, said("비밀 이야기"), use("t1", "Read", file_path="/a/b.py"), detail="none")
    assert tr.say == "" and tr.current()["target"] == ""


def test_transcript_ignores_broken_lines(collector, tr_file):
    tr = read(collector, tr_file, "{not json", use("t1", "Read", file_path="/a"))
    assert tr.tools == 1


def test_transcript_last_activity_from_timestamp(collector, tr_file):
    tr = read(collector, tr_file, use("t1", "Read", file_path="/a"))
    assert tr.last == collector.iso_ts(TS)


# ---------- 백그라운드 ----------

def test_bg_run_in_background_bash(collector, tr_file):
    tr = read(collector, tr_file, use("b1", "Bash", command="sleep 100", run_in_background=True))
    assert tr.background(time.time()) == []         # 결과 전에는 아직 '지금 도구'
    write(tr_file, result("b1", "Command running in background with ID: abc"))
    bg = tr.read("basic").background(time.time())
    assert [b["tool"] for b in bg] == ["Bash"]


@pytest.mark.parametrize("text", [
    "Command running in background with ID: x1",
    "  Async agent launched successfully. agentId: a1",
    "Monitor started",
])
def test_bg_detected_when_result_starts_with_phrase(collector, tr_file, text):
    tr = read(collector, tr_file, use("a1", "Agent", description="look"), result("a1", text))
    assert len(tr.background(time.time())) == 1


def test_bg_not_detected_when_phrase_is_in_middle_of_output(collector, tr_file):
    # 회귀: 명령 출력(예: 이 소스를 grep)에 그 문구가 섞여 있어도 백그라운드가 아니다
    out = "collector.py:117: BG_STARTED = re.compile(r\"(Command running in background|Async agent launched)\")"
    tr = read(collector, tr_file, use("g1", "Bash", command="grep -n BG collector.py"), result("g1", out))
    assert tr.background(time.time()) == []


def test_bg_result_as_text_blocks(collector, tr_file):
    rec = result("a1")
    rec["message"]["content"][0]["content"] = [{"type": "text", "text": "Async agent launched successfully."}]
    tr = read(collector, tr_file, use("a1", "Agent", description="x"), rec)
    assert len(tr.bg) == 1


def _bg_started(collector, tr_file):
    return read(collector, tr_file, use("b1", "Bash", command="x", run_in_background=True),
                result("b1", "Command running in background with ID: b"))


def test_bg_cleared_by_string_user_message(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    write(tr_file, {"type": "user", "timestamp": TS, "message": {"role": "user", "content": notification("b1")}})
    assert tr.read("basic").bg == {}


def test_bg_cleared_by_user_text_block(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    write(tr_file, {"type": "user", "timestamp": TS,
                    "message": {"role": "user", "content": [{"type": "text", "text": notification("b1")}]}})
    assert tr.read("basic").bg == {}


def test_bg_cleared_by_queue_operation(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    write(tr_file, {"type": "queue-operation", "operation": "enqueue", "content": notification("b1")})
    assert tr.read("basic").bg == {}


def test_bg_cleared_by_attachment_queued_command(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    write(tr_file, {"type": "attachment", "attachment": {"type": "queued_command", "prompt": notification("b1")}})
    assert tr.read("basic").bg == {}


def test_bg_kept_while_status_running_or_other_id(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    write(tr_file, {"type": "queue-operation", "content": notification("b1", status="running")},
          {"type": "queue-operation", "content": notification("other")})
    assert list(tr.read("basic").bg) == ["b1"]


def test_bg_expires_after_six_hours(collector, tr_file):
    tr = _bg_started(collector, tr_file)
    ts = tr.bg["b1"]["ts"]
    assert len(tr.background(ts + collector.BG_MAX_SEC - 1)) == 1
    assert tr.background(ts + collector.BG_MAX_SEC + 1) == []


# ---------- 할 일 ----------

def _create(tid, n, subject):
    return [use(tid, "TaskCreate", subject=subject), result(tid, f"Task #{n} created successfully: {subject}")]


def test_tasks_create_update_delete(collector, tr_file):
    tr = read(collector, tr_file, *_create("c1", 1, "읽기"), *_create("c2", 2, "쓰기"), *_create("c3", 3, "지우기"))
    assert tr.tasks == {"1": {"s": "읽기", "st": "pending"}, "2": {"s": "쓰기", "st": "pending"},
                        "3": {"s": "지우기", "st": "pending"}}
    write(tr_file, use("u1", "TaskUpdate", taskId="1", status="in_progress"),
          use("u2", "TaskUpdate", taskId="2", status="completed", subject="다 쓰기"),
          use("u3", "TaskUpdate", taskId="3", status="deleted"),
          use("u4", "TaskUpdate", taskId="9", status="completed"))
    tr.read("basic")
    assert tr.tasks == {"1": {"s": "읽기", "st": "in_progress"}, "2": {"s": "다 쓰기", "st": "completed"}}


def test_tasks_new_batch_after_all_completed(collector, tr_file):
    tr = read(collector, tr_file, *_create("c1", 1, "하나"), use("u1", "TaskUpdate", taskId="1", status="completed"),
              *_create("c2", 2, "새 일"))
    assert tr.tasks == {"2": {"s": "새 일", "st": "pending"}}


def test_tasks_not_reset_while_some_open(collector, tr_file):
    tr = read(collector, tr_file, *_create("c1", 1, "하나"), *_create("c2", 2, "둘"),
              use("u1", "TaskUpdate", taskId="1", status="completed"), *_create("c3", 3, "셋"))
    assert list(tr.tasks) == ["1", "2", "3"]


def test_tasks_todowrite_replaces_list(collector, tr_file):
    tr = read(collector, tr_file, *_create("c1", 1, "옛 일"),
              use("w1", "TodoWrite", todos=[{"content": "가", "status": "completed"},
                                            {"content": "나", "status": "in_progress"}]))
    assert tr.tasks == {"1": {"s": "가", "st": "completed"}, "2": {"s": "나", "st": "in_progress"}}


def test_tasks_detail_none_hides_subjects(collector, tr_file):
    tr = read(collector, tr_file, *_create("c1", 1, "비밀 일"),
              use("u1", "TaskUpdate", taskId="1", subject="또 비밀"), detail="none")
    assert tr.tasks == {"1": {"s": "할 일", "st": "pending"}}
    write(tr_file, use("w1", "TodoWrite", todos=[{"content": "비밀", "status": "pending"}]))
    assert tr.read("none").tasks == {"1": {"s": "할 일", "st": "pending"}}


# ---------- socket_ok / pid_alive ----------

@pytest.mark.parametrize("path", ["/tmp/cc-socks/abc", "/tmp/cc-socks-501/abc.sock",
                                  "/private/tmp/cc-socks/abc", "/run/user/1000/cc-socks/abc"])
def test_socket_dirs_allowed(collector, path):
    assert collector._SOCK_DIRS.match(path)


@pytest.mark.parametrize("path", ["", "/etc/passwd", "/tmp/cc-socks/a/b", "/tmp/cc-socksx/a", "/tmp/evil/cc-socks/a",
                                  "/home/u/tmp/cc-socks/a", "/run/user/x/cc-socks/a", "relative/cc-socks/a"])
def test_socket_ok_rejects_other_paths(collector, path):
    assert not collector._SOCK_DIRS.match(path)
    assert collector.socket_ok(path) is False


def test_socket_ok_allowed_but_missing(collector):
    assert collector.socket_ok("/tmp/cc-socks-0/t1-does-not-exist-%d" % os.getpid()) is False


@pytest.fixture
def fake_socket(collector, monkeypatch):
    """짧은 임시 폴더에 진짜 유닉스 소켓을 만들고, 그 폴더를 허용 경로로 바꾼다(실제 /tmp/cc-socks 는 건드리지 않는다)."""
    d = tempfile.mkdtemp(prefix="cot1-", dir="/tmp" if os.path.isdir("/tmp") else None)
    monkeypatch.setattr(collector, "_SOCK_DIRS", re.compile("^" + re.escape(os.path.realpath(d)) + "/[^/]+$"))
    path = os.path.join(os.path.realpath(d), "s")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    yield path
    srv.close()
    for p in os.listdir(d):
        os.unlink(os.path.join(d, p))
    os.rmdir(d)


@posix_only
def test_socket_ok_real_socket_and_regular_file(collector, fake_socket):
    assert collector.socket_ok(fake_socket) is True
    plain = os.path.join(os.path.dirname(fake_socket), "plain")
    open(plain, "w").close()
    assert collector.socket_ok(plain) is False       # 소켓이 아닌 파일


def test_pid_alive(collector):
    assert collector.pid_alive(os.getpid()) is True
    assert collector.pid_alive(2147483644) is False
    assert collector.pid_alive(0) is False and collector.pid_alive(-1) is False


# ---------- Collector.collect ----------

SID = "11111111-2222-3333-4444-555555555555"


def make_session(home, recs=(), sid=SID, cwd="/work/myproj", status="busy", pid=None, root=".claude", **extra):
    root = home / root
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    s = {"pid": pid or os.getpid(), "sessionId": sid, "cwd": cwd, "status": status,
         "startedAt": 1_700_000_000_000, "updatedAt": 1_700_000_000_000, "name": "", **extra}
    (root / "sessions" / f"{s['pid']}-{sid[:4]}.json").write_text(json.dumps(s), encoding="utf-8")
    enc = "".join(ch if ch.isalnum() else "-" for ch in cwd)
    d = root / "projects" / enc
    d.mkdir(parents=True, exist_ok=True)
    jsonl = d / f"{sid}.jsonl"
    write(jsonl, *recs, mode="w")
    return jsonl


def collect_one(collector, detail="basic"):
    agents = collector.Collector(detail).collect()
    assert len(agents) == 1
    return agents[0]


def test_collect_working(collector, home):
    make_session(home, [{"type": "ai-title", "aiTitle": "제목"}, use("t1", "Edit", file_path="/w/app.py")])
    a = collect_one(collector)
    assert a["id"] == SID and a["pid"] == os.getpid()
    assert a["kind"] == "working" and a["tool"] == "Edit" and a["target"] == "app.py"
    assert a["project"] == "myproj" and a["name"] == "myproj" and a["title"] == "제목"
    assert a["tools"] == 1 and a["canMessage"] is False and a["bg"] == [] and a["todos"] == []


def test_collect_thinking(collector, home):
    make_session(home, [use("t1", "Read", file_path="/a"), result("t1")])
    assert collect_one(collector)["kind"] == "thinking"


def test_collect_idle(collector, home):
    make_session(home, [use("t1", "Read", file_path="/a")], status="idle")
    a = collect_one(collector)
    assert a["kind"] == "idle" and a["tool"] == ""     # 쉬는 중이면 남은 도구를 보이지 않는다


def test_collect_waiting_with_background_and_todos(collector, home):
    make_session(home, [use("b1", "Bash", command="x", description="긴 빌드", run_in_background=True),
                        result("b1", "Command running in background with ID: z"),
                        *_create("c1", 1, "빌드 기다리기")], status="idle")
    a = collect_one(collector)
    assert a["kind"] == "waiting"
    assert a["bg"][0]["tool"] == "Bash" and a["bg"][0]["target"] == "긴 빌드"
    assert a["todos"] == [{"s": "빌드 기다리기", "st": "pending"}]


def test_collect_waiting_status(collector, home):
    make_session(home, [], status="waiting")
    assert collect_one(collector)["kind"] == "waiting"


def test_collect_detail_none(collector, home):
    make_session(home, [said("비밀"), use("t1", "Read", file_path="/secret.py"), *_create("c1", 1, "비밀 일")])
    a = collect_one(collector, detail="none")
    assert a["say"] == "" and a["todos"] == [{"s": "할 일", "st": "pending"}]


def test_collect_speech_off_hides_say(collector, home):
    make_session(home, [said("안녕")])
    col = collector.Collector("basic")
    assert col.collect()[0]["say"] == "안녕"
    col.speech = False
    assert col.collect()[0]["say"] == ""


def test_collect_skips_dead_pid_and_dedups_roots(collector, home, monkeypatch):
    make_session(home, [], pid=2147483644, sid="dead-session")
    make_session(home, [])
    make_session(home, [], root="orca/home")      # 같은 세션이 다른 설정 폴더에도
    monkeypatch.setattr(collector, "ROOT_GLOBS", collector.ROOT_GLOBS + [str(home / "orca" / "home")])
    agents = collector.Collector("basic").collect()
    assert [a["id"] for a in agents] == [SID]


def test_collect_finds_jsonl_in_other_project_folder(collector, home):
    jsonl = make_session(home, [use("t1", "Read", file_path="/x/y.md")])
    other = home / ".claude" / "projects" / "-renamed"
    other.mkdir()
    os.replace(str(jsonl), str(other / jsonl.name))
    assert collect_one(collector)["target"] == "y.md"


def test_collect_can_message_off_by_default(collector, home):
    make_session(home, [], messagingSocketPath="/tmp/cc-socks/whatever")
    assert collect_one(collector)["canMessage"] is False


@posix_only
def test_collect_can_message_with_socket(collector, home, fake_socket, monkeypatch):
    monkeypatch.setattr(collector, "MESSAGES", True)
    make_session(home, [], messagingSocketPath=fake_socket)
    col = collector.Collector("basic")
    a = col.collect()[0]
    assert a["canMessage"] is True and col.sockets[SID] == fake_socket


# ---------- checklist_rule_installed ----------

def test_checklist_rule_present(collector, home):
    (home / ".claude" / "CLAUDE.md").write_text("단계가 많으면 TaskCreate 로 목록을 만든다", encoding="utf-8")
    assert collector.checklist_rule_installed() is True


def test_checklist_rule_absent(collector, home):
    (home / ".claude" / "CLAUDE.md").write_text("# 규칙\n아무것도 없음\n", encoding="utf-8")
    assert collector.checklist_rule_installed() is False


def test_checklist_rule_no_file(collector):
    assert collector.checklist_rule_installed() is False


def test_checklist_rule_follows_one_include(collector, home):
    (home / "rules.md").write_text("TodoWrite 를 쓴다\n", encoding="utf-8")
    (home / ".claude" / "CLAUDE.md").write_text("@~/rules.md\n", encoding="utf-8")
    assert collector.checklist_rule_installed() is True


def test_checklist_rule_include_only_one_level(collector, home):
    (home / "deep.md").write_text("TaskCreate\n", encoding="utf-8")
    (home / "mid.md").write_text("@~/deep.md\n", encoding="utf-8")
    (home / ".claude" / "CLAUDE.md").write_text("@~/mid.md\n", encoding="utf-8")
    assert collector.checklist_rule_installed() is False


# ---------- 메시지 스레드(outbox_loop)·떠남(say_bye)·종료 신호 ----------

class StopLoop(BaseException):
    """outbox_loop 의 while True 를 끝내려고 던진다(except Exception 에 잡히지 않게 BaseException)."""


class Clock:
    """collector 모듈의 time 을 바꿔 끼워 sleep 을 기록하고, n 번째 sleep 에서 고리를 끝낸다."""

    def __init__(self, stop_after, start=1000.0):
        self.now, self.sleeps, self.stop_after = start, [], stop_after
        self.strftime = time.strftime

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, sec):
        self.sleeps.append(sec)
        self.now += sec
        if len(self.sleeps) >= self.stop_after:
            raise StopLoop


def http_error(code):
    import urllib.error
    return urllib.error.HTTPError("http://hub/x", code, "err", {}, None)


def run_loop(collector, monkeypatch, replies, stop_after, handled=None):
    """api 를 replies(차례대로 돌려줄 값 또는 던질 예외)로 바꾸고 outbox_loop 를 돌린다. (호출 기록, Clock) 을 돌려준다."""
    clock = Clock(stop_after)
    monkeypatch.setattr(collector, "time", clock)
    calls, replies = [], list(replies)

    def fake_api(hub, path, payload, timeout=5):
        calls.append((path, payload, timeout))
        r = replies.pop(0) if replies else {"messages": []}
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(collector, "api", fake_api)
    monkeypatch.setattr(collector, "handle_outbox",
                        lambda hub, host, col, items: (handled if handled is not None else []).append(items))
    with pytest.raises(StopLoop):
        collector.outbox_loop("http://hub", "mac", collector.Collector("basic"))
    return calls, clock


def test_outbox_loop_waits_and_hands_messages_over(collector, monkeypatch):
    msg = {"id": "m1", "session": "s1", "text": "hi"}
    handled = []
    calls, clock = run_loop(collector, monkeypatch, [{"messages": [msg]}, {"messages": []}], 2, handled)
    assert calls[0] == ("/api/outbox/wait", {"host": "mac", "timeout": 25}, 35)   # 허브 상한 25초 + 여유
    assert handled == [[msg]]                                # 빈 응답은 handle 로 넘기지 않는다
    assert clock.sleeps == [0.0, 1.0]                        # 받으면 바로 다시 걸고, 곧바로 온 빈 응답이면 1초 쉰다


@pytest.mark.parametrize("code", [401, 403])
def test_outbox_loop_auth_or_off_waits_30s(collector, monkeypatch, code):
    calls, clock = run_loop(collector, monkeypatch, [http_error(code)], 1)
    assert clock.sleeps == [30]
    assert [c[0] for c in calls] == ["/api/outbox/wait"]


def test_outbox_loop_backoff_doubles_to_30_and_resets(collector, monkeypatch):
    import urllib.error
    errs = [http_error(500)] + [urllib.error.URLError("down")] * 6 + [OSError("reset")]
    calls, clock = run_loop(collector, monkeypatch, errs + [{"messages": []}, http_error(502)], 10)
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 1.0, 1.0]   # 성공하면 1초로 돌아간다


def test_outbox_loop_logs_connection_failure_once(collector, monkeypatch, capsys):
    import urllib.error
    run_loop(collector, monkeypatch, [urllib.error.URLError("down")] * 3 + [{"messages": []},
                                      urllib.error.URLError("down")], 5)
    out = capsys.readouterr().out
    assert out.count("메시지 대기 연결 실패") == 2           # 끊길 때마다 한 번(이어지는 실패는 조용히)


def test_outbox_loop_old_hub_falls_back_to_pull(collector, monkeypatch):
    msg = {"id": "m1", "session": "s1", "text": "hi"}
    handled = []
    calls, clock = run_loop(collector, monkeypatch, [http_error(404), {"messages": [msg]}, {"messages": []}], 2, handled)
    assert [c[0] for c in calls] == ["/api/outbox/wait", "/api/outbox/pull", "/api/outbox/pull"]
    assert calls[1][1] == {"host": "mac"}
    assert clock.sleeps == [1.0, 1.0]                        # 404 로 바꿀 때는 쉬지 않고, pull 은 1초마다
    assert handled == [[msg]]


def test_outbox_loop_retries_wait_after_5_minutes_of_pull(collector, monkeypatch):
    calls, clock = run_loop(collector, monkeypatch, [http_error(404)], 305)
    paths = [c[0] for c in calls]
    back = paths.index("/api/outbox/wait", 1)               # pull 다음 처음 다시 건 wait
    assert paths[0] == "/api/outbox/wait" and set(paths[1:back]) == {"/api/outbox/pull"}
    assert 295 <= back - 1 <= 301                           # 1초 간격 pull 이 5분 동안


def test_outbox_loop_pull_404_waits_30s(collector, monkeypatch):
    calls, clock = run_loop(collector, monkeypatch, [http_error(404), http_error(404)], 1)
    assert [c[0] for c in calls] == ["/api/outbox/wait", "/api/outbox/pull"]
    assert clock.sleeps == [30]                              # pull 도 없는 허브면 다시 바꾸지 않고 30초 쉰다


def test_outbox_loop_survives_handle_errors(collector, monkeypatch):
    clock = Clock(3)
    monkeypatch.setattr(collector, "time", clock)
    monkeypatch.setattr(collector, "api", lambda *a, **k: {"messages": [{"id": "m"}]})

    def boom(*a):
        raise ValueError("이상한 메시지")
    monkeypatch.setattr(collector, "handle_outbox", boom)
    with pytest.raises(StopLoop):
        collector.outbox_loop("http://hub", "mac", collector.Collector("basic"))
    assert clock.sleeps == [1.0, 2.0, 4.0]                   # 스레드는 죽지 않고 물러섰다 다시 건다


# 진짜 HTTP 로 한 바퀴: 표준 라이브러리 http.server 로 가짜 허브를 루프백에 띄운다.

@pytest.fixture
def fake_hub():
    import http.server
    import threading

    state = {"requests": [], "replies": {}}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            state["requests"].append((self.path, body, self.headers.get("X-Office-Token")))
            queue = state["replies"].get(self.path) or [(200, {"ok": True})]
            code, data = queue.pop(0) if len(queue) > 1 else queue[0]
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    state["url"] = "http://127.0.0.1:%d" % srv.server_address[1]
    yield state
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def inbox(collector, monkeypatch):
    """listen 하는 가짜 수신함 소켓(짧은 /tmp 경로, 실제 /tmp/cc-socks 는 건드리지 않는다)."""
    d = tempfile.mkdtemp(prefix="cot4-", dir="/tmp")
    real = os.path.realpath(d)
    monkeypatch.setattr(collector, "_SOCK_DIRS", re.compile("^" + re.escape(real) + "/[^/]+$"))
    path = os.path.join(real, "in")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(4)
    srv.settimeout(3)
    yield path, srv
    srv.close()
    os.unlink(path)
    os.rmdir(d)


@posix_only
def test_outbox_loop_end_to_end_over_http(collector, monkeypatch, fake_hub, inbox):
    path, srv = inbox
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "TOKEN", "tt")
    fake_hub["replies"]["/api/outbox/wait"] = [(200, {"messages": [{"id": "m1", "session": "s1", "text": "안녕"}]}),
                                               (200, {"messages": []})]
    col = collector.Collector("basic")
    col.sockets = {"s1": path}
    clock = Clock(1)
    monkeypatch.setattr(collector, "time", clock)
    with pytest.raises(StopLoop):
        collector.outbox_loop(fake_hub["url"], "mac", col)
    conn, _ = srv.accept()
    line = conn.makefile("rb").readline()
    conn.close()
    sent = json.loads(line)
    assert sent["type"] == "user" and sent["message"]["content"] == collector.MESSAGE_PREFIX + "안녕"
    reqs = fake_hub["requests"]
    assert reqs[0] == ("/api/outbox/wait", {"host": "mac", "timeout": 25}, "tt")
    assert reqs[1] == ("/api/outbox/result", {"host": "mac", "id": "m1", "ok": True, "error": ""}, "tt")


def test_api_raises_http_error_codes(collector, fake_hub):
    import urllib.error
    fake_hub["replies"]["/api/outbox/wait"] = [(404, {"detail": "Not Found"})]
    with pytest.raises(urllib.error.HTTPError) as e:
        collector.api(fake_hub["url"], "/api/outbox/wait", {"host": "mac"})
    assert e.value.code == 404


# handle_outbox 는 시작할 때의 소켓 표를 잡아 둔다(수집 루프가 중간에 표를 바꿔 끼워도 섞이지 않게)

def test_handle_outbox_uses_socket_snapshot(collector, monkeypatch):
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)
    monkeypatch.setattr(collector, "socket_ok", lambda p: True)
    delivered, results = [], []
    monkeypatch.setattr(collector, "deliver", lambda sock, text: delivered.append((sock, text)))
    col = collector.Collector("basic")
    col.sockets = {"a": "/sock/a", "b": "/sock/b"}

    def fake_api(hub, path, payload, timeout=5):
        results.append(payload)
        col.sockets = {}                                    # 다른 스레드(수집 루프)가 표를 바꿔 끼움
        return {"ok": True}

    monkeypatch.setattr(collector, "api", fake_api)
    collector.handle_outbox("http://hub", "mac", col, [{"id": "1", "session": "a", "text": "x"},
                                                       {"id": "2", "session": "b", "text": "y"}])
    assert delivered == [("/sock/a", "x"), ("/sock/b", "y")]
    assert [r["ok"] for r in results] == [True, True]


@pytest.mark.parametrize("flags,err", [
    ({"MESSAGES": False}, "꺼져"),
    ({"MESSAGES": True, "WINDOWS": True}, "Windows"),
])
def test_handle_outbox_refuses_when_off_or_windows(collector, monkeypatch, flags, err):
    for k, v in flags.items():
        monkeypatch.setattr(collector, k, v)
    results = []
    monkeypatch.setattr(collector, "api", lambda hub, path, payload, timeout=5: results.append((path, payload)))
    collector.handle_outbox("http://hub", "mac", collector.Collector("basic"), [{"id": "1", "session": "a", "text": "x"}])
    ((path, payload),) = results
    assert path == "/api/outbox/result" and payload["ok"] is False and err in payload["error"]


def test_collect_swaps_socket_table_whole(collector, home, monkeypatch):
    monkeypatch.setattr(collector, "MESSAGES", True)
    make_session(home, [], messagingSocketPath="/tmp/cc-socks/whatever")
    col = collector.Collector("basic")
    before = col.sockets
    col.collect()
    assert before == {} and col.sockets is not before          # 옛 사전은 건드리지 않고 새 사전으로 바꾼다
    assert col.sockets == {SID: "/tmp/cc-socks/whatever"}


def test_handle_outbox_result_failure_does_not_drop_rest(collector, monkeypatch, capsys):
    import urllib.error
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)
    monkeypatch.setattr(collector, "socket_ok", lambda p: True)
    delivered, reported = [], []
    monkeypatch.setattr(collector, "deliver", lambda sock, text: delivered.append(text))

    def flaky_api(hub, path, payload, timeout=5):
        reported.append(payload["id"])
        if len(reported) == 1:
            raise urllib.error.URLError("hub blip")
        return {"ok": True}

    monkeypatch.setattr(collector, "api", flaky_api)
    col = collector.Collector("basic")
    col.sockets = {"a": "/sock/a", "b": "/sock/b"}
    collector.handle_outbox("http://hub", "mac", col, [{"id": "1", "session": "a", "text": "x"},
                                                       {"id": "2", "session": "b", "text": "y"}])
    assert delivered == ["x", "y"] and reported == ["1", "2"]
    assert capsys.readouterr().out.count("메시지 결과 보고 실패") == 1


def test_handle_outbox_deliver_error_fails_only_that_message(collector, monkeypatch):
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)
    monkeypatch.setattr(collector, "socket_ok", lambda p: True)
    delivered, results = [], []

    def deliver(sock, text):
        if text == "bad":
            "\ud800".encode("utf-8")                        # 짝 없는 서로게이트 → UnicodeEncodeError(OSError 아님)
        delivered.append(text)
    monkeypatch.setattr(collector, "deliver", deliver)
    monkeypatch.setattr(collector, "api", lambda hub, path, payload, timeout=5: results.append(payload))
    col = collector.Collector("basic")
    col.sockets = {"a": "/sock/a", "b": "/sock/b"}
    collector.handle_outbox("http://hub", "mac", col, [{"id": "1", "session": "a", "text": "bad"},
                                                       {"id": "2", "session": "b", "text": "good"}])
    assert delivered == ["good"]
    assert [(r["id"], r["ok"]) for r in results] == [("1", False), ("2", True)]
    assert "전달 실패" in results[0]["error"]


def test_outbox_loop_does_not_spin_on_instant_empty_replies(collector, monkeypatch):
    calls, clock = run_loop(collector, monkeypatch, [], 20)
    assert clock.sleeps == [1.0] * 20                        # 곧바로 온 빈 응답마다 1초 쉰다(바쁜 고리 없음)


def test_outbox_loop_no_pause_after_real_long_poll(collector, monkeypatch):
    clock = Clock(3)
    monkeypatch.setattr(collector, "time", clock)

    def slow_empty(hub, path, payload, timeout=5):
        clock.now += 25                                      # 허브가 25초 붙잡았다가 빈 응답
        return {"messages": []}
    monkeypatch.setattr(collector, "api", slow_empty)
    with pytest.raises(StopLoop):
        collector.outbox_loop("http://hub", "mac", collector.Collector("basic"))
    assert clock.sleeps == [0.0, 0.0, 0.0]


# 떠남·종료 신호

def test_say_bye_posts_host_with_short_timeout(collector, monkeypatch):
    calls = []
    monkeypatch.setattr(collector, "api", lambda hub, path, payload, timeout=5: calls.append((hub, path, payload, timeout)))
    collector.say_bye("http://hub", "mac")
    assert calls == [("http://hub", "/api/hosts/bye", {"host": "mac"}, 2)]


@pytest.mark.parametrize("exc", ["urlerror", "404", "timeout"])
def test_say_bye_swallows_errors(collector, monkeypatch, exc):
    import urllib.error
    err = {"urlerror": urllib.error.URLError("down"), "404": http_error(404), "timeout": socket.timeout("t")}[exc]

    def boom(*a, **k):
        raise err
    monkeypatch.setattr(collector, "api", boom)
    collector.say_bye("http://hub", "mac")                   # 예외 없이 끝난다


def test_say_bye_real_http(collector, fake_hub, monkeypatch):
    monkeypatch.setattr(collector, "TOKEN", "tt")
    collector.say_bye(fake_hub["url"], "mac")
    assert fake_hub["requests"] == [("/api/hosts/bye", {"host": "mac"}, "tt")]


def test_exit_on_signal_raises_system_exit(collector):
    import signal
    with pytest.raises(SystemExit) as e:
        collector._exit_on_signal(signal.SIGTERM, None)
    assert e.value.code == 128 + signal.SIGTERM


@pytest.fixture
def main_env(collector, monkeypatch):
    """main() 을 끝까지 돌리되, 수집 고리(run)·스레드·bye 를 가로챈다. SIGTERM 처리기는 끝나면 되돌린다."""
    import signal
    saved = signal.getsignal(signal.SIGTERM)
    rec = {"bye": [], "threads": [], "order": []}

    class FakeThread:
        def __init__(self, target=None, args=(), name=None, daemon=None):
            self.kw = dict(target=target, args=args, name=name, daemon=daemon)

        def start(self):
            rec["threads"].append(self.kw)
            rec["order"].append("thread")

    class FakeThreading:
        Thread = FakeThread

    monkeypatch.setattr(collector, "threading", FakeThreading)
    monkeypatch.setattr(collector, "say_bye", lambda hub, host: rec["bye"].append((hub, host)))
    monkeypatch.setattr(sys, "argv", ["collector.py", "--hub", "http://hub:1", "--host", "mac"])
    yield rec
    signal.signal(signal.SIGTERM, saved)



@pytest.mark.parametrize("exc", [SystemExit(143), KeyboardInterrupt()])
def test_main_says_bye_on_exit(collector, monkeypatch, main_env, capsys, exc):
    def run(args, col):
        raise exc
    monkeypatch.setattr(collector, "run", run)
    collector.main()
    assert main_env["bye"] == [("http://hub:1", "mac")]
    assert "수집기 종료" in capsys.readouterr().out


def test_main_installs_sigterm_handler(collector, monkeypatch, main_env):
    import signal
    seen = []
    monkeypatch.setattr(collector, "run", lambda args, col: seen.append(signal.getsignal(signal.SIGTERM)))
    collector.main()
    assert seen == [collector._exit_on_signal]


@posix_only
def test_main_real_sigterm_sends_bye(collector, monkeypatch, main_env):
    import signal

    def run(args, col):
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(100):          # 신호 처리기가 SystemExit 을 던질 때까지
            time.sleep(0.01)
        raise AssertionError("SIGTERM 이 SystemExit 으로 바뀌지 않았다")
    monkeypatch.setattr(collector, "run", run)
    collector.main()
    assert main_env["bye"] == [("http://hub:1", "mac")]


def test_main_starts_outbox_thread_when_messages_on(collector, monkeypatch, main_env):
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)
    monkeypatch.setattr(collector, "run", lambda args, col: None)
    collector.main()
    (t,) = main_env["threads"]
    assert t["target"] is collector.outbox_loop and t["daemon"] is True and t["name"] == "outbox"
    assert t["args"][:2] == ("http://hub:1", "mac")


@pytest.mark.parametrize("messages,windows", [(True, True), (False, False)])
def test_main_no_outbox_thread_on_windows_or_off(collector, monkeypatch, main_env, messages, windows):
    monkeypatch.setattr(collector, "MESSAGES", messages)
    monkeypatch.setattr(collector, "WINDOWS", windows)    # os.name == "nt" 일 때 import 시점에 정해지는 값
    monkeypatch.setattr(collector, "run", lambda args, col: None)
    collector.main()
    assert main_env["threads"] == [] and main_env["bye"] == []   # 정상 반환이면 bye 도 없다


def test_main_on_nt_does_not_start_outbox_thread(collector, monkeypatch, main_env):
    """os.name == "nt" 로 새로 읽은 모듈은 WINDOWS 가 켜지고, 메시지를 켜도 스레드를 띄우지 않는다."""
    monkeypatch.setenv("CLAUDE_OFFICE_MESSAGES", "on")
    monkeypatch.setattr(os, "name", "nt")
    try:
        nt = load_module("office_collector_nt", COLLECTOR_PY)
    finally:
        monkeypatch.setattr(os, "name", "posix" if sys.platform != "win32" else "nt")
        sys.modules.pop("office_collector_nt", None)
    assert nt.WINDOWS is True and nt.MESSAGES is True
    started = []
    monkeypatch.setattr(nt, "threading", type("T", (), {"Thread": lambda *a, **k: started.append(k)}))
    monkeypatch.setattr(nt, "run", lambda args, col: None)
    monkeypatch.setattr(nt.signal, "signal", lambda *a: None)   # 이 시험에서는 신호 처리기를 바꾸지 않는다
    nt.main()
    assert started == []


def test_main_collects_once_before_outbox_thread(collector, monkeypatch, main_env):
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)
    real_collect = collector.Collector.collect

    def collect(self):
        main_env["order"].append("collect")
        return real_collect(self)
    monkeypatch.setattr(collector.Collector, "collect", collect)
    monkeypatch.setattr(collector, "run", lambda args, col: None)
    collector.main()
    assert main_env["order"] == ["collect", "thread"]


def test_main_outbox_thread_starts_even_if_first_collect_fails(collector, monkeypatch, main_env, capsys):
    monkeypatch.setattr(collector, "MESSAGES", True)
    monkeypatch.setattr(collector, "WINDOWS", False)

    def boom(self):
        raise ValueError("이상한 세션 파일")
    monkeypatch.setattr(collector.Collector, "collect", boom)
    monkeypatch.setattr(collector, "run", lambda args, col: None)
    collector.main()
    assert main_env["order"] == ["thread"] and "수집 오류" in capsys.readouterr().out


# ---------- 모델·컨텍스트·토큰·바꾼 줄 ----------

def answer(mid, model="claude-opus-5-5", inp=10, read_=1000, write_=200, out=50, ts=TS, branch="main", sidechain=False):
    return {"type": "assistant", "timestamp": ts, "gitBranch": branch, "isSidechain": sidechain,
            "message": {"id": mid, "role": "assistant", "model": model, "content": [{"type": "text", "text": "hi"}],
                        "usage": {"input_tokens": inp, "cache_read_input_tokens": read_,
                                  "cache_creation_input_tokens": write_, "output_tokens": out}}}


def test_usage_context_is_last_answer_and_output_counted_once_per_message(collector, tr_file):
    # 한 답변이 여러 줄로 나뉘어 같은 usage 가 되풀이돼도 출력 토큰은 한 번만
    tr = read(collector, tr_file, answer("m1", out=50), answer("m1", out=50), answer("m2", inp=5, read_=3000, write_=0, out=7))
    u = tr.usage()
    assert u["model"] == "opus-5-5"
    assert u["ctx"] == {"used": 3005, "max": 1_000_000}
    assert u["outTokens"] == 57
    assert tr.branch == "main"


def test_usage_ignores_synthetic_and_window_grows_past_200k(collector, tr_file):
    tr = read(collector, tr_file, answer("m1", model="claude-sonnet-4-5", read_=150_000),
              answer("x", model="<synthetic>", read_=0, out=999))
    assert tr.usage()["ctx"] == {"used": 150_210, "max": 200_000}
    assert tr.usage()["outTokens"] == 50
    write(tr_file, answer("m2", model="claude-sonnet-4-5", read_=250_000))
    assert tr.read("basic").usage()["ctx"]["max"] == 1_000_000   # 20만을 넘겨 썼으면 100만 창


def test_usage_1m_suffix_and_override(collector, tr_file, monkeypatch):
    tr = read(collector, tr_file, answer("m1", model="claude-sonnet-4-5[1m]"))
    assert tr.usage()["ctx"]["max"] == 1_000_000
    monkeypatch.setattr(collector, "CONTEXT_OVERRIDE", 500_000)
    assert tr.usage()["ctx"]["max"] == 500_000


def test_no_model_means_no_gauge(collector, tr_file):
    tr = read(collector, tr_file, said("hello"))
    assert tr.usage()["ctx"] is None and tr.usage()["model"] == ""


def test_compact_boundary_counts_and_resets_context(collector, tr_file):
    tr = read(collector, tr_file, answer("m1", read_=900_000),
              {"type": "system", "subtype": "compact_boundary", "timestamp": TS,
               "compactMetadata": {"trigger": "auto", "preTokens": 967_332, "postTokens": 9_204}})
    u = tr.usage()
    assert u["compacts"] == 1 and u["compactAt"]
    assert u["ctx"]["used"] == 9_204


def test_branch_hidden_with_detail_none_and_sidechain_ignored(collector, tr_file):
    tr = read(collector, tr_file, answer("m1", branch="secret-feature"), detail="none")
    assert tr.branch == ""
    tr = read(collector, tr_file, answer("m2", branch="sub-branch", sidechain=True))
    assert tr.branch == "secret-feature"


def test_patch_lines_counts_edits_and_new_files(collector, tr_file):
    edit = {"type": "user", "timestamp": TS, "toolUseResult": {"filePath": "a.py", "structuredPatch": [
        {"lines": [" ctx", "-old", "+new", "+more"]}, {"lines": ["-gone"]}]},
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
    create = {"type": "user", "timestamp": TS, "toolUseResult": {"type": "create", "content": "a\nb\nc", "structuredPatch": []},
              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}}
    tr = read(collector, tr_file, edit, create, {"type": "user", "toolUseResult": "Error: x"})
    assert tr.usage()["lines"] == [5, 2]


def test_sidechain_answers_do_not_move_context(collector, tr_file):
    tr = read(collector, tr_file, answer("m1", read_=5000), answer("s1", read_=90_000, sidechain=True))
    assert tr.usage()["ctx"]["used"] == 5210


# ---------- 타임라인 ----------

def test_iso_ts_keeps_milliseconds(collector):
    assert collector.iso_ts("2026-10-20T13:46:45.950Z") - collector.iso_ts("2026-10-20T13:46:45Z") == pytest.approx(0.95)
    assert collector.iso_ts("nope") is None


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".500Z"


def test_timeline_spans_open_closed_and_errors(collector, tr_file):
    now = time.time()
    err = result("t2", "boom", ts=_iso(now - 50))
    err["message"]["content"][0]["is_error"] = True
    tr = read(collector, tr_file,
              use("t1", "Read", ts=_iso(now - 100), file_path="/x/a.py"), result("t1", ts=_iso(now - 98)),
              use("t2", "Bash", ts=_iso(now - 60), description="build it"), err,
              use("t3", "Grep", ts=_iso(now - 10), pattern="foo"))
    sp = tr.timeline(now)["spans"]
    assert [s[0] for s in sp] == ["Read", "Bash", "Grep"]
    assert sp[0][3] == "a.py" and sp[0][2] - sp[0][1] == pytest.approx(2, abs=0.11)
    assert sp[1][4] == 1 and sp[0][4] == 0
    assert sp[2][2] is None   # 아직 결과가 없는 도구


def test_timeline_drops_old_spans(collector, tr_file):
    now = time.time()
    tr = read(collector, tr_file, use("t1", "Read", ts=_iso(now - 3 * 3600)), result("t1", ts=_iso(now - 3 * 3600 + 1)),
              use("t2", "Read", ts=_iso(now - 5)), result("t2", ts=_iso(now - 4)))
    assert len(tr.timeline(now)["spans"]) == 1


def test_timeline_prompts_only_from_people(collector, tr_file):
    now = time.time()
    human = {"type": "user", "timestamp": _iso(now - 30), "origin": {"kind": "human"}, "message": {"role": "user", "content": "do it"}}
    notif = {"type": "user", "timestamp": _iso(now - 20), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": notification("x")}}
    old_style = {"type": "user", "timestamp": _iso(now - 10), "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}}
    meta = {"type": "user", "timestamp": _iso(now - 5), "isMeta": True, "message": {"role": "user", "content": "caveat"}}
    tagged = {"type": "user", "timestamp": _iso(now - 4), "message": {"role": "user", "content": "<local-command-stdout>x"}}
    tr = read(collector, tr_file, human, notif, old_style, meta, tagged, result("t9", ts=_iso(now - 3)))
    assert len(tr.timeline(now)["prompts"]) == 2


# ---------- 바뀐 것만 보내기(Sender) ----------

class FakeHub:
    def __init__(self, patch_status=None):
        self.calls = []
        self.patch_status = patch_status   # None=정상, 'resync', 404
        self.accept = True

    def api(self, hub, path, payload, timeout=5):
        import urllib.error
        self.calls.append(("patch", payload))
        if self.patch_status == 404:
            raise urllib.error.HTTPError(hub + path, 404, "nf", {}, None)
        if self.patch_status == "resync":
            return {"ok": False, "resync": True}
        return {"ok": True}

    def post(self, hub, payload, timeout=5):
        self.calls.append(("full", payload))


@pytest.fixture
def fake(collector, monkeypatch):
    f = FakeHub()
    monkeypatch.setattr(collector, "api", f.api)
    monkeypatch.setattr(collector, "post", f.post)
    return f


def test_sender_full_then_only_changes(collector, fake):
    s = collector.Sender("http://h", "m")
    a, b = agent_d("a"), agent_d("b")
    assert s.send([a, b], {}, now=100) == "full"
    assert fake.calls[-1][1]["seq"] == 1
    assert s.send([a, b], {}, now=101) is None                       # 그대로면 안 보낸다
    assert s.send([a, dict(b, lastActivity=101)], {}, now=102) is None   # lastActivity 만 바뀐 건 박동 때까지 미룬다
    assert s.send([a, dict(b, kind="working")], {}, now=103) == "patch"
    p = fake.calls[-1][1]
    assert [x["id"] for x in p["set"]] == ["b"] and p["del"] == [] and p["base"] == 1 and p["seq"] == 2
    assert s.send([dict(b, kind="working")], {}, now=104) == "patch"
    assert fake.calls[-1][1]["del"] == ["a"] and fake.calls[-1][1]["order"] == ["b"]


def test_sender_heartbeat_carries_activity_changes(collector, fake):
    s = collector.Sender("http://h", "m")
    a = agent_d("a")
    s.send([a], {}, now=100)
    s.send([dict(a, lastActivity=150)], {}, now=100 + collector.HEARTBEAT_SEC + 1)
    p = fake.calls[-1][1]
    assert fake.calls[-1][0] == "patch" and p["set"][0]["lastActivity"] == 150


def test_sender_resync_and_old_hub_fall_back_to_full(collector, fake):
    s = collector.Sender("http://h", "m")
    s.send([agent_d("a")], {}, now=100)
    fake.patch_status = "resync"
    assert s.send([agent_d("a", kind="working")], {}, now=101) == "full"
    fake.patch_status = 404
    assert s.send([agent_d("a", kind="idle")], {}, now=102) == "full"
    assert s.patch_ok is False
    fake.patch_status = None
    assert s.send([agent_d("a", kind="working")], {}, now=103) == "full"   # 예전 허브라고 본 뒤로는 계속 전체


def test_sender_reset_after_network_error_sends_full(collector, fake):
    s = collector.Sender("http://h", "m")
    s.send([agent_d("a")], {}, now=100)
    s.reset()
    assert s.send([agent_d("a")], {}, now=100 + collector.HEARTBEAT_SEC + 1) == "full"


def agent_d(i, **kw):
    return dict({"id": i, "kind": "idle", "lastActivity": 100}, **kw)


# ---------- 층 = git 저장소(worktree 는 주 저장소로) ----------

def test_project_of_plain_repo_subdir_and_worktree(collector, tmp_path):
    main = tmp_path / "repos" / "DailyGoal"
    (main / ".git" / "worktrees" / "dg-en-c0").mkdir(parents=True)
    (main / "src" / "deep").mkdir(parents=True)
    wt = tmp_path / "orca" / "DailyGoal" / "dg-en-c0"
    (wt / "app").mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'dg-en-c0'}\n")
    plain = tmp_path / "notes"
    plain.mkdir()
    collector._project_cache.clear()
    assert collector.project_of(str(main)) == ("DailyGoal", "")
    assert collector.project_of(str(main / "src" / "deep")) == ("DailyGoal", "")
    assert collector.project_of(str(wt)) == ("DailyGoal", "dg-en-c0")
    assert collector.project_of(str(wt / "app")) == ("DailyGoal", "dg-en-c0")
    assert collector.project_of(str(plain)) == ("notes", "")


def test_project_of_submodule_and_relative_gitdir(collector, tmp_path):
    sup = tmp_path / "super"
    (sup / ".git" / "modules" / "lib").mkdir(parents=True)
    (sup / "lib").mkdir()
    (sup / "lib" / ".git").write_text("gitdir: ../.git/modules/lib\n")
    collector._project_cache.clear()
    assert collector.project_of(str(sup / "lib")) == ("lib", "")


def test_project_of_does_not_climb_to_home_repo(collector, home):
    (home / ".git").mkdir()
    d = home / "scratch" / "x"
    d.mkdir(parents=True)
    collector._project_cache.clear()
    assert collector.project_of(str(d)) == ("x", "")


# ---------- 상태 표시줄 요약(사용 한도) ----------

def test_status_line_reads_limits_and_drops_passed_windows(collector, tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "STATUS_DIR", str(tmp_path))
    now = time.time()
    (tmp_path / "s1.json").write_text(json.dumps({"v": 1, "ts": now - 10, "limits": {
        "five_hour": {"pct": 42.2, "resets": now - 5}, "seven_day": {"pct": 18, "resets": now + 3600}},
        "ctx": {"pct": 19, "size": 1000000}}))
    st = collector.status_line("s1", now)
    assert st["limits"]["five_hour"] == {"pct": 0, "resets": None}       # 초기화가 지난 창
    assert st["limits"]["seven_day"] == {"pct": 18.0, "resets": now + 3600}
    assert st["ctxSize"] == 1000000
    assert collector.status_line("nope", now) is None and collector.status_line("../x", now) is None
    (tmp_path / "old.json").write_text(json.dumps({"ts": now - 9 * 24 * 3600, "limits": {}}))
    assert collector.status_line("old", now) is None


# ---------- 설정 점검(meta.setup) ----------

def test_setup_status_counts_per_settings_folder(collector, home, monkeypatch):
    root = home / ".claude"
    (root / "settings.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [{"hooks": [{"command": "py", "args": ["-c", "x/claude_office_hook.py"]}]}],
                  "PermissionRequest": [{"hooks": [{"command": "py", "args": ["-c", "x/claude_office_approve.py"]}]}]},
        "statusLine": {"type": "command", "command": '"py" "x/claude_office_statusline.py" --next "n"'},
        "env": {"CLAUDE_CODE_ENABLE_TODO_TOOLS": "1"}}))
    other = home / "profile"
    (other / "sessions").mkdir(parents=True)
    (other / "settings.json").write_text("{ broken")
    monkeypatch.setattr(collector, "ROOT_GLOBS", [str(root), str(other)])
    monkeypatch.setattr(collector, "APPROVE", True)
    collector._setup_cache["val"] = None
    su = collector.setup_status()
    assert su["roots"] == 2 and su["hooks"] == 1 and su["approveHook"] == 1 and su["statusline"] == 1 and su["todoTools"] == 1
    assert su["approveEnv"] is True and su["os"] in ("mac", "windows", "linux")
    assert [r["label"] for r in su["rootsDetail"]] == ["~/.claude", "~/profile"]   # 홈은 ~ 로 줄여 보낸다
    assert su["rootsDetail"][0]["approveHook"] is True and su["rootsDetail"][1]["hooks"] is False
    assert str(home) not in json.dumps(su)
