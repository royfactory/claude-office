#!/usr/bin/env python3
"""claude-office 승인 훅(선택 기능): 권한 요청을 허브에 올리고, 대시보드에서 누른 허용·거절을 Claude Code 에 돌려준다.

Claude Code 의 PermissionRequest 훅으로 돈다(https://code.claude.com/docs/en/hooks.md). 터미널의 권한 창은
그동안에도 떠 있고, 사람이 터미널에서 먼저 답하면 그 답이 이긴다(훅의 늦은 결정은 버려진다).
결정이 없으면(시간 초과·허브 끊김·꺼져 있음·터미널에서 이미 답함) 아무것도 출력하지 않고 exit 0 —
그러면 Claude Code 는 평소처럼 터미널에서 묻는다. 어떤 경우에도 허용을 스스로 만들지 않는다.

켜는 조건(모두): 이 컴퓨터 .env 의 CLAUDE_OFFICE_APPROVE=on, OFFICE_TOKEN, 허브 관리 화면 '대시보드에서 승인'.
설정은 환경변수 → ~/.claude-office/.env(수집기 설치가 복사한 것) → 저장소 루트 .env 순서로 읽는다.

허브로 보내는 것: 컴퓨터 이름, 세션 id, 도구 이름, 승인 판단용 미리보기(Bash 명령 앞 400자, 파일 도구는
파일 경로, 웹 도구는 주소, 그 밖은 입력 JSON 앞 300자). 미리보기는 허브 메모리에만 두고 토큰이 있어야 보인다.
표준 라이브러리만 쓴다(Python 3.9, macOS·리눅스·Windows).
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOTAL_SEC = 570      # 훅 시간 제한(설치 때 600초)보다 짧게 끝낸다
WAIT_SEC = 25        # 허브 롱폴링 한 번


def load_env():
    """KEY=VALUE 파일들을 읽어 아직 없는 값만 채운 사전(환경변수가 이긴다)."""
    env = {}
    for path in (os.path.join(os.path.expanduser("~"), ".claude-office", ".env"), os.path.join(os.path.dirname(HERE), ".env")):
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass
    for k in ("CLAUDE_OFFICE_HUB", "CLAUDE_OFFICE_HOST", "CLAUDE_OFFICE_APPROVE", "OFFICE_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def preview_of(tool, inp):
    """사람이 허용할지 판단할 만큼의 짧은 미리보기."""
    if not isinstance(inp, dict):
        return ""
    if tool == "Bash":
        d = inp.get("description")
        cmd = str(inp.get("command") or "")
        return ((d + "\n") if d else "") + cmd[:400]
    for k in ("file_path", "notebook_path", "path"):
        if inp.get(k):
            return str(inp[k])[:300]
    if inp.get("url"):
        return str(inp["url"])[:300]
    try:
        return json.dumps(inp, ensure_ascii=False)[:300]
    except (TypeError, ValueError):
        return ""


def call(hub, path, payload, token, timeout):
    req = urllib.request.Request(hub.rstrip("/") + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "X-Office-Token": token}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def decide(data, env, call=call, now=time.monotonic, sleep=time.sleep):
    """훅 입력 → Claude Code 에 돌려줄 출력 사전, 결정이 없으면 None."""
    if str(env.get("CLAUDE_OFFICE_APPROVE", "")).lower() not in ("on", "1", "true", "yes"):
        return None
    hub, token = env.get("CLAUDE_OFFICE_HUB") or "http://127.0.0.1:3006", env.get("OFFICE_TOKEN") or ""
    if not token or not isinstance(data, dict) or data.get("hook_event_name") != "PermissionRequest":
        return None
    sid, tool = data.get("session_id"), data.get("tool_name")
    if not isinstance(sid, str) or not sid or not isinstance(tool, str) or not tool:
        return None
    host = env.get("CLAUDE_OFFICE_HOST") or socket.gethostname().split(".")[0]
    start = now()
    try:
        aid = call(hub, "/api/approvals", {"host": host[:40], "session": sid[:80], "toolUseId": str(data.get("tool_use_id") or "")[:120],
                                           "tool": tool[:64], "preview": preview_of(tool, data.get("tool_input"))}, token, 10)["id"]
    except Exception:
        return None
    while now() - start < TOTAL_SEC:
        try:
            st = call(hub, "/api/approvals/wait", {"id": aid, "timeout": WAIT_SEC}, token, WAIT_SEC + 10).get("status")
        except Exception:
            sleep(3)   # 허브가 잠깐 끊겨도 시간 안에서는 다시 묻는다
            continue
        if st == "allow":
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        if st == "deny":
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                           "decision": {"behavior": "deny", "message": "claude-office 대시보드에서 거절했습니다."}}}
        if st != "pending":   # gone: 터미널에서 이미 답했거나 세션이 끝났다
            return None
    return None


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        out = decide(data, load_env())
        if out:
            sys.stdout.write(json.dumps(out))
            sys.stdout.flush()
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)   # 어떤 경우에도 0 — 결정이 없으면 터미널이 평소처럼 묻는다
