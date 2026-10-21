#!/usr/bin/env python3
"""claude-office 훅(선택 기능): Claude Code 훅 입력을 받아 세션별 '마지막 이벤트'만 이 컴퓨터 파일에 적는다.

Claude Code 가 훅마다 stdin 으로 넘기는 JSON(https://code.claude.com/docs/en/hooks.md)에서
hook_event_name·session_id·tool_name·notification_type 만 본다. 대화 본문, 명령 원문(tool_input),
도구 결과, 사용자 프롬프트는 읽어도 쓰지 않는다. 네트워크로 아무것도 보내지 않는다.

  쓰는 곳: ~/.claude-office/events/<session_id>.json   (CLAUDE_OFFICE_EVENTS 로 폴더를 바꿀 수 있다)
  내용:    {"v": 1, "event": "PermissionRequest", "kind": "permission", "ts": 1792580499.123, "tool_name": "Bash"}

수집기는 이 파일을 읽어, 마지막 이벤트가 권한 요청이고 세션이 busy 면 '승인 대기'로 보낸다.
어떤 오류가 나도 출력 없이 exit 0 으로 끝난다 — 훅이 Claude Code 를 막거나 결정을 내리면 안 된다.
표준 라이브러리만 쓴다(Python 3.9, macOS·리눅스·Windows).
"""
import json
import os
import re
import sys
import time

# 훅 이벤트 → 수집기가 보는 종류. 여기 없는 이벤트는 파일을 건드리지 않는다.
KINDS = {
    "PreToolUse": "tool_start",
    "PermissionRequest": "permission",       # 권한 창을 띄우기 직전(바로 온다)
    "PostToolUse": "tool_end",
    "PostToolUseFailure": "tool_end",
    "PermissionDenied": "denied",            # 자동 모드가 거절함 — 기다리지 않는다
    "UserPromptSubmit": "prompt",
    "Stop": "stop",
    "StopFailure": "stop",
}
# Notification 은 이 종류일 때만 권한 요청으로 본다(권한 창이 약 6초 기다린 뒤 온다, 샌드박스 네트워크 요청 포함)
PERMISSION_NOTIFICATIONS = ("permission_prompt",)
SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")   # 파일 이름으로 써도 안전한 세션 ID 만


def events_dir():
    return os.environ.get("CLAUDE_OFFICE_EVENTS") or os.path.join(os.path.expanduser("~"), ".claude-office", "events")


def record(data, now):
    """훅 입력 → (session_id, 기록할 사전). 기록할 것이 없으면 None."""
    if not isinstance(data, dict):
        return None
    event = data.get("hook_event_name")
    if event == "Notification":
        kind = "permission" if data.get("notification_type") in PERMISSION_NOTIFICATIONS else None
    else:
        kind = KINDS.get(event)
    sid = data.get("session_id")
    if not kind or not isinstance(sid, str) or not SID.match(sid):
        return None
    rec = {"v": 1, "event": event, "kind": kind, "ts": round(now, 3)}
    tool = data.get("tool_name")
    if isinstance(tool, str) and tool:
        rec["tool_name"] = tool[:64]
    return sid, rec


def write(sid, rec):
    d = events_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".json")
    try:   # 늦게 끝난 훅이 더 새 이벤트를 덮지 않게
        with open(path, encoding="utf-8") as f:
            if float(json.load(f).get("ts", 0)) > rec["ts"]:
                return
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, path)   # 수집기가 반쯤 쓴 파일을 읽지 않게 통째로 바꿔 끼운다
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    try:
        now = time.time()
        raw = sys.stdin.buffer.read()
        hit = record(json.loads(raw.decode("utf-8", "replace")), now)
        if hit:
            write(*hit)
    except BaseException:   # 깨진 입력·쓰기 실패·Ctrl+C 무엇이든 조용히 넘긴다
        pass
    return 0


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)   # 어떤 경우에도 0 — Claude Code 는 0 이 아니면 훅 오류로 다룬다
