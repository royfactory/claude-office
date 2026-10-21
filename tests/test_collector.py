"""collector/collector.py 테스트. 표준 라이브러리 + pytest 만 쓴다(Python 3.9 에서도 돈다)."""
import json
import os
import re
import socket
import tempfile
import time
from unittest import mock

import pytest

from conftest import posix_only

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
