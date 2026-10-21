"""hooks/(승인 대기 감지 훅·설치 스크립트)와 수집기의 훅 이벤트 읽기 테스트. 표준 라이브러리 + pytest(Python 3.9 에서도 돈다).

훅 입력 예시는 https://code.claude.com/docs/en/hooks.md 의 형식을 그대로 따른다.
사용자의 실제 ~/.claude/settings.json·~/.claude-office 는 건드리지 않는다 — 모두 tmp_path 안에서 한다."""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import REPO, load_module

HOOK_PY = REPO / "hooks" / "claude_office_hook.py"
INSTALL_PY = REPO / "hooks" / "install_hooks.py"
SID = "00893aaf-19fa-41d2-8238-13269b9b3ca0"

# ---------- 공식 문서 형식의 훅 입력 ----------

COMMON = {"session_id": SID, "transcript_path": "/Users/x/.claude/projects/p/" + SID + ".jsonl",
          "cwd": "/Users/x/proj", "permission_mode": "default"}
PERMISSION_REQUEST = dict(COMMON, hook_event_name="PermissionRequest", tool_name="Bash",
                          tool_input={"command": "rm -rf node_modules", "description": "Remove node_modules directory"},
                          permission_suggestions=[{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm -rf node_modules"}],
                                                   "behavior": "allow", "destination": "localSettings"}])
NOTIFICATION = dict(COMMON, hook_event_name="Notification", message="Claude needs your permission",
                    title="Permission needed", notification_type="permission_prompt")
PRE_TOOL = dict(COMMON, hook_event_name="PreToolUse", tool_name="Bash",
                tool_input={"command": "npm test", "description": "Run test suite"}, tool_use_id="toolu_01ABC123")
POST_TOOL = dict(COMMON, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "npm test"},
                 tool_use_id="toolu_01ABC123", tool_response={"stdout": "All tests passed"})
POST_FAIL = dict(COMMON, hook_event_name="PostToolUseFailure", tool_name="Bash", tool_input={"command": "npm test"},
                 tool_use_id="toolu_01ABC123", error="Command failed with exit code 1")
PROMPT = dict(COMMON, hook_event_name="UserPromptSubmit", prompt="Write a function to calculate the factorial")
STOP = dict(COMMON, hook_event_name="Stop", stop_hook_active=False,
            last_assistant_message="I've completed the refactoring.")


def run_hook(events, payload, timeout=10):
    """훅 스크립트를 Claude Code 처럼 별도 프로세스로 돌린다(stdin 에 JSON)."""
    data = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    env = dict(os.environ, CLAUDE_OFFICE_EVENTS=str(events))
    t = time.time()
    p = subprocess.run([sys.executable, str(HOOK_PY)], input=data.encode() if isinstance(data, str) else data,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
    return p, time.time() - t


def event_file(events, sid=SID):
    return events / (sid + ".json")


def read_event(events, sid=SID):
    return json.loads(event_file(events, sid).read_text(encoding="utf-8"))


@pytest.fixture
def events(tmp_path):
    return tmp_path / "events"


@pytest.fixture
def hook(monkeypatch, events):
    monkeypatch.setenv("CLAUDE_OFFICE_EVENTS", str(events))
    mod = load_module("office_hook", HOOK_PY)
    yield mod
    sys.modules.pop("office_hook", None)


# ---------- 훅 스크립트 ----------

def test_hook_permission_request_writes_event(events):
    p, _ = run_hook(events, PERMISSION_REQUEST)
    assert p.returncode == 0 and p.stdout == b"" and p.stderr == b""   # 결정을 내리지 않는다(출력 없음)
    ev = read_event(events)
    assert ev["event"] == "PermissionRequest" and ev["kind"] == "permission" and ev["tool_name"] == "Bash"
    assert abs(ev["ts"] - time.time()) < 30
    raw = event_file(events).read_text(encoding="utf-8")
    assert "rm -rf" not in raw and "node_modules" not in raw and "/Users/x" not in raw   # 명령 원문·경로는 남기지 않는다


def test_hook_notification_permission_prompt_is_permission(events):
    run_hook(events, NOTIFICATION)
    ev = read_event(events)
    assert ev["kind"] == "permission" and "tool_name" not in ev
    assert "permission" in ev["kind"] and "Claude needs" not in event_file(events).read_text(encoding="utf-8")


@pytest.mark.parametrize("payload,kind", [(PRE_TOOL, "tool_start"), (POST_TOOL, "tool_end"), (POST_FAIL, "tool_end"),
                                          (PROMPT, "prompt"), (STOP, "stop")])
def test_hook_kinds_and_no_content(events, payload, kind):
    p, _ = run_hook(events, payload)
    assert p.returncode == 0
    assert read_event(events)["kind"] == kind
    raw = event_file(events).read_text(encoding="utf-8")
    for secret in ("npm test", "All tests passed", "factorial", "refactoring", "exit code 1"):
        assert secret not in raw


@pytest.mark.parametrize("payload", [
    dict(NOTIFICATION, notification_type="idle_prompt"),                 # 권한과 무관한 알림
    dict(COMMON, hook_event_name="SessionStart", source="startup"),      # 다루지 않는 이벤트
])
def test_hook_ignores_other_events(events, payload):
    p, _ = run_hook(events, payload)
    assert p.returncode == 0 and not event_file(events).exists()


def test_hook_other_notification_does_not_clear_permission(events):
    run_hook(events, PERMISSION_REQUEST)
    run_hook(events, dict(NOTIFICATION, notification_type="idle_prompt"))
    assert read_event(events)["kind"] == "permission"


@pytest.mark.parametrize("payload", [b"", b"not json", b"\xff\xfe\x00garbage", b"[1,2,3]", b"null",
                                     json.dumps(dict(STOP, session_id=None)),
                                     json.dumps(dict(STOP, session_id="../../etc/passwd")),
                                     json.dumps(dict(STOP, session_id="")),
                                     json.dumps(dict(STOP, hook_event_name=7))])
def test_hook_broken_input_exits_zero(events, payload):
    p, _ = run_hook(events, payload)
    assert p.returncode == 0 and p.stdout == b"" and p.stderr == b""
    assert not events.exists() or list(events.iterdir()) == []


def test_hook_write_failure_exits_zero(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")                       # 폴더 자리에 파일이 있어 만들 수 없다
    p, _ = run_hook(blocker / "events", PERMISSION_REQUEST)
    assert p.returncode == 0 and p.stderr == b""


def test_hook_corrupt_existing_file_is_replaced(events):
    events.mkdir()
    event_file(events).write_text("{broken", encoding="utf-8")
    run_hook(events, PRE_TOOL)
    assert read_event(events)["kind"] == "tool_start"


def test_hook_is_fast(events):
    _, took = run_hook(events, PERMISSION_REQUEST)   # 첫 실행(바이트코드 캐시 등) 제외
    took = min(run_hook(events, PRE_TOOL)[1] for _ in range(3))
    assert took < 1.0   # 프로세스 띄우기까지 포함. 스크립트 자체는 아래 시험처럼 수 ms
    assert read_event(events)["kind"] == "tool_start"


def test_hook_record_and_write_in_process_under_100ms(hook, events):
    t = time.perf_counter()
    for _ in range(20):
        hook.write(*hook.record(PERMISSION_REQUEST, time.time()))
    assert (time.perf_counter() - t) / 20 < 0.1
    assert read_event(events)["kind"] == "permission"
    assert [p.name for p in events.iterdir()] == [SID + ".json"]   # 임시 파일이 남지 않는다


def test_hook_older_event_does_not_overwrite_newer(hook, events):
    now = time.time()
    hook.write(*hook.record(PERMISSION_REQUEST, now))
    hook.write(*hook.record(POST_TOOL, now - 1))   # 늦게 끝난 앞선 훅
    assert read_event(events)["kind"] == "permission"


def test_hook_record_mapping(hook):
    assert hook.record(dict(COMMON, hook_event_name="PermissionDenied", tool_name="Bash", reason="x"), 1.0)[1]["kind"] == "denied"
    assert hook.record(dict(COMMON, hook_event_name="StopFailure", error="rate_limit"), 1.0)[1]["kind"] == "stop"
    assert hook.record({"hook_event_name": "Stop"}, 1.0) is None
    assert hook.record("Stop", 1.0) is None


# ---------- 수집기: 승인 대기 판정 ----------

def make_session(home, recs=(), sid=SID, cwd="/work/myproj", status="busy", started=None):
    root = home / ".claude"
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    s = {"pid": os.getpid(), "sessionId": sid, "cwd": cwd, "status": status,
         "startedAt": int((started if started is not None else time.time() - 600) * 1000),
         "updatedAt": int(time.time() * 1000), "name": ""}
    (root / "sessions" / ("%d.json" % s["pid"])).write_text(json.dumps(s), encoding="utf-8")
    d = root / "projects" / "".join(ch if ch.isalnum() else "-" for ch in cwd)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / (sid + ".jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def bash_use(tid="t1"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": "rm -rf x", "description": "지우기"}}]}}


@pytest.fixture
def col(collector, events, monkeypatch):
    monkeypatch.setattr(collector, "EVENTS_DIR", str(events))
    return collector


def collect_one(col):
    agents = col.Collector("basic").collect()
    assert len(agents) == 1
    return agents[0]


def test_collector_without_event_file_is_unchanged(col, home):
    make_session(home, [bash_use()])
    a = collect_one(col)
    assert a["kind"] == "working" and a["tool"] == "Bash"


def test_collector_default_events_dir_is_under_home(collector, home):
    assert collector.EVENTS_DIR == os.path.join(str(home), ".claude-office", "events")


def test_collector_permission_then_tool_end_then_stop(col, home, events):
    make_session(home, [bash_use()])
    run_hook(events, PRE_TOOL)
    assert collect_one(col)["kind"] == "working"

    run_hook(events, PERMISSION_REQUEST)
    a = collect_one(col)
    assert a["kind"] == "approval" and a["tool"] == "Bash" and a["target"] == "지우기"
    assert a["since"] == pytest.approx(read_event(events)["ts"])
    assert a["stalled"] is False

    run_hook(events, NOTIFICATION)                 # 6초 뒤 오는 알림도 그대로 승인 대기
    assert collect_one(col)["kind"] == "approval"

    run_hook(events, POST_TOOL)                    # 승인되어 도구가 끝남 → 해제
    assert collect_one(col)["kind"] == "working"   # (기록에는 아직 결과가 없으니 작업 중)

    run_hook(events, PERMISSION_REQUEST)
    assert collect_one(col)["kind"] == "approval"
    run_hook(events, STOP)
    assert collect_one(col)["kind"] == "working"


@pytest.mark.parametrize("after", [PRE_TOOL, POST_FAIL, PROMPT,
                                   dict(COMMON, hook_event_name="PermissionDenied", tool_name="Bash", reason="[x]")])
def test_collector_permission_cleared_by_later_events(col, home, events, after):
    make_session(home, [bash_use()])
    run_hook(events, PERMISSION_REQUEST)
    run_hook(events, after)
    assert collect_one(col)["kind"] != "approval"


@pytest.mark.parametrize("status,kind", [("idle", "idle"), ("waiting", "waiting"), ("shell", "shell")])
def test_collector_permission_only_while_busy(col, home, events, status, kind):
    make_session(home, [bash_use()], status=status)
    run_hook(events, PERMISSION_REQUEST)
    assert collect_one(col)["kind"] == kind


def test_collector_ignores_event_from_before_session_start(col, home, events):
    run_hook(events, PERMISSION_REQUEST)
    make_session(home, [bash_use()], started=time.time() + 60)   # 이 프로세스는 이벤트 뒤에 시작했다
    assert collect_one(col)["kind"] == "working"


def test_collector_approval_without_transcript_tool_uses_event_tool(col, home, events):
    make_session(home, [])
    run_hook(events, PERMISSION_REQUEST)
    a = collect_one(col)
    assert a["kind"] == "approval" and a["tool"] == "Bash" and a["target"] == ""


@pytest.mark.parametrize("content", ["{broken", "[]", '{"kind": "permission", "ts": "x"}', ""])
def test_collector_broken_event_file_is_ignored(col, home, events, content):
    make_session(home, [bash_use()])
    events.mkdir()
    event_file(events).write_text(content, encoding="utf-8")
    assert collect_one(col)["kind"] == "working"


def test_collector_rejects_unsafe_session_id(col):
    assert col.hook_event("../../x", 0) is None and col.hook_event("", 0) is None


# ---------- 설치 스크립트 ----------

EXISTING = {
    "model": "opus",
    "permissions": {"allow": ["Bash(git status)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/local/bin/guard.sh"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
    },
}


@pytest.fixture
def inst():
    mod = load_module("office_install_hooks", INSTALL_PY)
    yield mod
    sys.modules.pop("office_install_hooks", None)


@pytest.fixture
def settings(tmp_path):
    p = tmp_path / "claude" / "settings.json"
    p.parent.mkdir()
    p.write_text(json.dumps(EXISTING, indent=2), encoding="utf-8")
    return p


def ours(data):
    return [(ev, g.get("matcher"), h) for ev, groups in data.get("hooks", {}).items()
            for g in groups for h in g["hooks"] if "claude_office_hook.py" in json.dumps(h)]


def backups(p):
    return sorted(x for x in p.parent.iterdir() if ".bak-" in x.name)


def test_install_dry_run_is_default_and_changes_nothing(inst, settings, capsys):
    before = settings.read_bytes()
    assert inst.main(["--settings", str(settings)]) == 0
    out = capsys.readouterr().out
    assert settings.read_bytes() == before and backups(settings) == []
    for name in ("PermissionRequest", "PreToolUse", "PostToolUse", "Stop", "permission_prompt", "claude_office_hook.py", "--apply"):
        assert name in out
    assert inst.main(["--settings", str(settings), "--dry-run"]) == 0
    assert settings.read_bytes() == before


def test_install_dry_run_shows_exec_form(inst):
    groups = inst.groups_to_add("/usr/bin/python3", "/x/hooks/claude_office_hook.py")
    h = groups["PermissionRequest"][0]["hooks"][0]
    assert h["type"] == "command" and h["command"] == "/usr/bin/python3" and h["timeout"] == 5
    assert h["args"][0] == "-c" and "'/x/hooks/claude_office_hook.py'" in h["args"][1] and len(h["args"]) == 2
    assert groups["Notification"][0]["matcher"] == "permission_prompt"
    assert "matcher" not in groups["Stop"][0]


def test_install_apply_merges_and_keeps_existing(inst, settings):
    before = settings.read_text(encoding="utf-8")
    assert inst.main(["--settings", str(settings), "--apply"]) == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus" and data["permissions"] == EXISTING["permissions"]
    assert data["hooks"]["PreToolUse"][0] == EXISTING["hooks"]["PreToolUse"][0]   # 기존 훅이 먼저, 그대로
    assert data["hooks"]["Stop"][0] == EXISTING["hooks"]["Stop"][0]
    events = sorted(ev for ev, _, _ in ours(data))
    assert events == sorted(ev for ev, _ in inst.EVENTS)
    for _, _, h in ours(data):
        assert h["command"] == sys.executable and h["args"] == ["-c", inst.launcher(inst.HOOK_SCRIPT)]
    (b,) = backups(settings)
    assert b.read_text(encoding="utf-8") == before

    assert inst.main(["--settings", str(settings), "--apply"]) == 0   # 다시 넣어도 겹치지 않는다
    again = json.loads(settings.read_text(encoding="utf-8"))
    assert len(ours(again)) == len(inst.EVENTS) and again["hooks"]["PreToolUse"][0] == EXISTING["hooks"]["PreToolUse"][0]


def test_install_remove_restores_original(inst, settings):
    inst.main(["--settings", str(settings), "--apply"])
    time.sleep(1.1)   # 백업 이름이 초 단위라 겹치지 않게
    assert inst.main(["--settings", str(settings), "--remove"]) == 0
    assert json.loads(settings.read_text(encoding="utf-8")) == EXISTING
    assert len(backups(settings)) == 2


def test_install_remove_keeps_other_hooks_in_same_group(inst, settings):
    data = inst.merged(EXISTING)
    data["hooks"]["Stop"][-1]["hooks"].append({"type": "command", "command": "echo mine"})
    inst.strip_ours(data)
    assert data["hooks"]["Stop"][-1]["hooks"] == [{"type": "command", "command": "echo mine"}]
    assert "PermissionRequest" not in data["hooks"]


def test_install_remove_without_ours_changes_nothing(inst, settings, capsys):
    before = settings.read_bytes()
    assert inst.main(["--settings", str(settings), "--remove"]) == 0
    assert settings.read_bytes() == before and backups(settings) == []


def test_install_apply_then_remove_on_new_file(inst, tmp_path):
    p = tmp_path / "new" / "settings.json"
    assert inst.main(["--settings", str(p), "--apply"]) == 0
    assert len(ours(json.loads(p.read_text(encoding="utf-8")))) == len(inst.EVENTS)
    assert inst.main(["--settings", str(p), "--remove"]) == 0
    assert json.loads(p.read_text(encoding="utf-8")) == {}


def test_install_refuses_broken_settings(inst, settings):
    settings.write_text("{ not json", encoding="utf-8")
    assert inst.main(["--settings", str(settings), "--apply"]) == 1
    assert settings.read_text(encoding="utf-8") == "{ not json" and backups(settings) == []


def test_installed_hook_runs_like_claude_code(inst, tmp_path, events):
    """설치된 항목(command + args)을 그대로 exec 해서 훅이 이벤트를 남기는지."""
    p = tmp_path / "settings.json"
    inst.main(["--settings", str(p), "--apply"])
    h = json.loads(p.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"][0]["hooks"][0]
    r = subprocess.run([h["command"]] + h["args"], input=json.dumps(PERMISSION_REQUEST).encode(),
                       env=dict(os.environ, CLAUDE_OFFICE_EVENTS=str(events)), timeout=h["timeout"])
    assert r.returncode == 0 and read_event(events)["kind"] == "permission"


def test_installed_hook_exits_zero_when_script_is_gone(inst, tmp_path, events):
    """저장소를 옮겨 훅 스크립트가 없어져도 exit 0 — `python 없는파일.py` 의 exit 2 는 PreToolUse 를 막는다."""
    h = inst.hook_entry(script=str(tmp_path / "moved" / "claude_office_hook.py"))
    r = subprocess.run([h["command"]] + h["args"], input=json.dumps(PRE_TOOL).encode(), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=dict(os.environ, CLAUDE_OFFICE_EVENTS=str(events)), timeout=10)
    assert r.returncode == 0 and r.stdout == b"" and not events.exists()


def test_installed_hook_handles_quotes_in_path(inst, tmp_path, events):
    d = tmp_path / ("it's odd dir" if os.name == "nt" else "it's \"odd\" dir")   # Windows 파일 이름에는 " 를 못 쓴다
    d.mkdir()
    (d / "claude_office_hook.py").write_bytes(HOOK_PY.read_bytes())
    h = inst.hook_entry(script=str(d / "claude_office_hook.py"))
    r = subprocess.run([h["command"]] + h["args"], input=json.dumps(PERMISSION_REQUEST).encode(),
                       env=dict(os.environ, CLAUDE_OFFICE_EVENTS=str(events)), timeout=10)
    assert r.returncode == 0 and read_event(events)["kind"] == "permission"
