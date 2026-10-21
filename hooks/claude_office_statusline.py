#!/usr/bin/env python3
"""claude-office 상태 표시줄(선택 기능): Claude Code 가 상태 표시줄에 넘기는 JSON 에서 사용 한도·컨텍스트만 파일로 남긴다.

Claude Code 는 사용 한도(5시간·7일)를 상태 표시줄 명령에만 알려 준다(https://code.claude.com/docs/en/statusline).
이 스크립트를 상태 표시줄로 걸면 세션마다 ~/.claude-office/status/<session_id>.json 에
  {"v": 1, "ts": …, "model": "…", "limits": {"five_hour": {"pct": 42, "resets": 1792…}, "seven_day": {…}},
   "ctx": {"pct": 19, "size": 1000000}}
만 적고(대화·명령·경로는 쓰지 않음), 원래 쓰던 상태 표시줄 명령이 있으면(--next 파일) 같은 입력으로 돌려 그 출력을
그대로 보여 준다. 없으면 '모델 · ctx 19% · 5h 42%' 한 줄을 보여 준다. 수집기가 이 파일을 읽어 화면에 보낸다.
네트워크로 아무것도 보내지 않는다. 어떤 오류에도 상태 표시줄을 비우지 않도록 원래 명령은 꼭 돌린다.
표준 라이브러리만 쓴다(Python 3.9, macOS·리눅스·Windows).
"""
import json
import os
import re
import subprocess
import sys
import time

SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def status_dir():
    return os.environ.get("CLAUDE_OFFICE_STATUS") or os.path.join(os.path.expanduser("~"), ".claude-office", "status")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def summary(data, now):
    """상태 표시줄 입력 → (session_id, 남길 사전). 남길 게 없으면 None."""
    if not isinstance(data, dict):
        return None
    sid = data.get("session_id")
    if not isinstance(sid, str) or not SID.match(sid):
        return None
    rec = {"v": 1, "ts": round(now, 1)}
    model = data.get("model")
    if isinstance(model, dict) and isinstance(model.get("id"), str):
        rec["model"] = model["id"][:64]
    limits = {}
    rl = data.get("rate_limits")
    if isinstance(rl, dict):
        for k in ("five_hour", "seven_day"):
            w = rl.get(k)
            if isinstance(w, dict) and _num(w.get("used_percentage")) is not None:
                limits[k] = {"pct": round(float(w["used_percentage"]), 1), "resets": _num(w.get("resets_at"))}
    if limits:
        rec["limits"] = limits
    cw = data.get("context_window")
    if isinstance(cw, dict):
        ctx = {"pct": _num(cw.get("used_percentage")), "size": _num(cw.get("context_window_size"))}
        if any(v is not None for v in ctx.values()):
            rec["ctx"] = ctx
    return sid, rec


def write(sid, rec):
    d = status_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".json")
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fallback_line(rec):
    bits = []
    if rec.get("model"):
        bits.append(rec["model"].replace("claude-", ""))
    c = rec.get("ctx") or {}
    if c.get("pct") is not None:
        bits.append("ctx %d%%" % round(c["pct"]))
    lim = rec.get("limits") or {}
    for k, label in (("five_hour", "5h"), ("seven_day", "7d")):
        if k in lim:
            bits.append("%s %d%%" % (label, round(lim[k]["pct"])))
    return " · ".join(bits)


def next_command(path):
    """설치 때 남겨 둔 원래 상태 표시줄 설정({"statusLine": {...}})에서 명령을 꺼낸다."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            sl = json.load(f).get("statusLine")
        cmd = sl.get("command") if isinstance(sl, dict) else None
        return cmd if isinstance(cmd, str) and cmd.strip() else None
    except (OSError, ValueError, AttributeError):
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    nxt = argv[argv.index("--next") + 1] if "--next" in argv and argv.index("--next") + 1 < len(argv) else None
    raw = b""
    rec = None
    try:
        raw = sys.stdin.buffer.read()
        hit = summary(json.loads(raw.decode("utf-8", "replace")), time.time())
        if hit:
            write(*hit)
            rec = hit[1]
    except BaseException:
        pass
    cmd = next_command(nxt)
    if cmd:   # 원래 상태 표시줄을 같은 입력으로 돌려 그대로 보여 준다
        try:
            p = subprocess.run(cmd, shell=True, input=raw, stdout=subprocess.PIPE, timeout=10)
            sys.stdout.buffer.write(p.stdout)
            sys.stdout.flush()
            return 0
        except BaseException:
            pass
    if rec:
        # Windows 기본 인코딩(cp949 등)이 아니라 UTF-8 바이트로 쓴다 — Claude Code 는 UTF-8 로 읽는다
        sys.stdout.buffer.write((fallback_line(rec) + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)
