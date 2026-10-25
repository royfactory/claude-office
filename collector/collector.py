#!/usr/bin/env python3
"""claude-office 수집기: 이 컴퓨터의 Claude Code 세션들을 읽어 허브로 보낸다(macOS·Windows, 리눅스는 시험 전).

읽는 곳(읽기만 한다):
  <설정 폴더>/sessions/<pid>.json                     세션 목록·이름·idle/busy
    (설정 폴더 = ~/.claude 와 Orca 프로필 ~/Library/Application Support/orca/claude-profiles/*/home)
  ~/.claude/projects/<cwd>/<sessionId>.jsonl          대화 기록 → 지금 쓰는 도구
  ~/.claude/projects/<cwd>/<sessionId>/subagents/     서브에이전트 기록
  ~/.claude-office/events/<sessionId>.json            (선택) 훅이 남긴 마지막 이벤트 → 승인 대기

보내는 것: 세션 이름·제목(ai-title), 프로젝트 폴더 이름, 상태, 도구 이름과 짧은 대상(파일 이름,
Bash 의 description, 검색어 앞부분 등), 도구 호출 횟수, 그리고 말풍선용으로 Claude 마지막 답변의 앞 80자.
명령 원문·파일 내용·사용자 메시지는 보내지 않는다. 말풍선은 허브 관리 화면의 '말풍선' 설정을 끄면
수집기가 30초 안에 알아채고 보내지 않는다. --detail none 이면 대상·말풍선·설명을 모두 뺀다.

설정은 환경변수 → --env 로 준 파일 → ~/.claude-office/.env → 저장소 루트 .env 순서로 읽는다
(앞에 있는 값이 이긴다). 키는 저장소의 .env.example 을 본다.

표준 라이브러리만 쓴다(/usr/bin/python3 3.9 에서 돈다).
  python3 collector.py                                   계속 보내기(허브 주소는 CLAUDE_OFFICE_HUB)
  python3 collector.py --hub http://127.0.0.1:3006       허브 주소를 직접 주기
  python3 collector.py --dump                            한 번 모아 출력만(보내지 않음)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import signal
import socket
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

WINDOWS = os.name == "nt"


def pid_alive(pid):
    """세션 프로세스가 살아 있는지 조회만 한다. 프로세스에는 아무 신호도 보내지 않는다.

    Windows 에서는 os.kill(pid, 0) 이 '확인'이 아니라 TerminateProcess 라서 절대 쓰지 않는다
    — 그대로 쓰면 Claude 세션이 꺼진다. 대신 OpenProcess + GetExitCodeProcess 로 묻는다."""
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION — 조회 권한만
        if not h:
            return ctypes.get_last_error() == 5   # ACCESS_DENIED = 있긴 한데 못 여는 프로세스
        try:
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)   # POSIX 에서 신호 0 은 보내지 않고 존재만 확인한다
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def load_env(path):
    """KEY=VALUE 파일을 읽어 아직 없는 환경변수만 채운다."""
    if not path or not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as f:   # 메모장이 붙이는 BOM 도 견딘다
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_env_arg = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--env"), None)
for _p in (_env_arg, os.path.expanduser("~/.claude-office/.env"),
           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
    load_env(_p)
TOKEN = os.environ.get("OFFICE_TOKEN", "").strip()
# 대시보드에서 세션으로 메시지 보내기. 이 컴퓨터에서 켜야만(on) 받는다 — 허브가 켜 있어도 여기서 꺼 두면 전달하지 않는다
MESSAGES = os.environ.get("CLAUDE_OFFICE_MESSAGES", "").strip().lower() in ("on", "1", "true", "yes")
APPROVE = os.environ.get("CLAUDE_OFFICE_APPROVE", "").strip().lower() in ("on", "1", "true", "yes")
MESSAGE_PREFIX = "[claude-office 대시보드에서 이 컴퓨터의 사용자가 보낸 메시지]\n"
MAX_MESSAGE = 4000

# Claude Code 설정 폴더들. 기본 ~/.claude 말고도 Orca 가 띄운 세션은 프로필마다 CLAUDE_CONFIG_DIR 이 따로 있다.
# 더 있으면 CLAUDE_OFFICE_ROOTS 에 콜론(:)으로 이어 적는다.
ROOT_GLOBS = [
    os.path.expanduser("~/.claude"),
    os.path.expanduser("~/Library/Application Support/orca/claude-profiles/*/home"),
] + [p for p in os.environ.get("CLAUDE_OFFICE_ROOTS", "").split(":") if p]


# 선택 기능: hooks/claude_office_hook.py 를 Claude Code 훅으로 넣으면 세션별 마지막 훅 이벤트가 여기 쌓인다.
# 없으면 지금처럼 기록 파일만 보고 판단한다.
EVENTS_DIR = os.environ.get("CLAUDE_OFFICE_EVENTS") or os.path.join(os.path.expanduser("~"), ".claude-office", "events")
_SID_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def hook_event(sid, started_at):
    """그 세션의 마지막 훅 이벤트 {event, kind, ts, tool_name?}. 파일이 없거나 세션 시작 전 것이면 None."""
    if not sid or not _SID_FILE.match(sid):
        return None
    try:
        with open(os.path.join(EVENTS_DIR, sid + ".json"), encoding="utf-8") as f:
            ev = json.load(f)
        ts = float(ev.get("ts", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if ts < started_at - 5:   # 같은 세션 ID 를 이어 연(--resume) 예전 프로세스의 것
        return None
    return dict(ev, ts=ts)


# 선택 기능: hooks/claude_office_statusline.py 를 상태 표시줄로 걸면 세션별 사용 한도·컨텍스트가 여기 쌓인다.
STATUS_DIR = os.environ.get("CLAUDE_OFFICE_STATUS") or os.path.join(os.path.expanduser("~"), ".claude-office", "status")
STATUS_FRESH_SEC = 8 * 24 * 3600   # 주간 한도 창(7일)보다 오래된 파일은 버린다


def status_line(sid, now):
    """그 세션의 상태 표시줄 요약 {ts, model, limits, ctx}. 없거나 너무 오래됐으면 None."""
    if not sid or not _SID_FILE.match(sid):
        return None
    try:
        with open(os.path.join(STATUS_DIR, sid + ".json"), encoding="utf-8") as f:
            st = json.load(f)
        ts = float(st.get("ts", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if now - ts > STATUS_FRESH_SEC:
        return None
    out = {"ts": ts}
    lim = st.get("limits")
    if isinstance(lim, dict):
        clean = {}
        for k in ("five_hour", "seven_day"):
            w = lim.get(k)
            if isinstance(w, dict) and isinstance(w.get("pct"), (int, float)):
                resets = w.get("resets") if isinstance(w.get("resets"), (int, float)) else None
                if resets and resets < now:   # 이미 초기화된 창의 값은 0 으로 본다
                    clean[k] = {"pct": 0, "resets": None}
                else:
                    clean[k] = {"pct": round(float(w["pct"]), 1), "resets": resets}
        if clean:
            out["limits"] = clean
    ctx = st.get("ctx")
    if isinstance(ctx, dict) and isinstance(ctx.get("size"), (int, float)) and ctx["size"] > 0:
        out["ctxSize"] = int(ctx["size"])
    return out


def profile_of(root):
    """설정 폴더의 짧은 이름: ~/.claude → 기본, Orca 프로필 → 'Orca f23251ba', 그 밖은 폴더 이름(계정 구별용)."""
    r = root.replace("\\", "/").rstrip("/")
    if os.path.abspath(root) == os.path.abspath(os.path.expanduser("~/.claude")):
        return "기본"
    m = re.search(r"claude-profiles/([^/]+)/home$", r)
    return "Orca " + m.group(1)[:8] if m else os.path.basename(r)[:24]


def claude_roots():
    roots = []
    for g in ROOT_GLOBS:
        for r in sorted(glob.glob(g)):
            if os.path.isdir(os.path.join(r, "sessions")) and r not in roots:
                roots.append(r)
    return roots
FIRST_READ_BYTES = 32 * 1024 * 1024  # 처음 열 때 이보다 크면 끝부분만 읽는다(도구 횟수는 그만큼 근사)
SAY_CHARS = 80
CONFIG_POLL_SEC = 30
# 도구 결과가 '백그라운드로 돌기 시작했다'는 뜻인지(Bash run_in_background·시간 초과로 넘어감·비동기 서브에이전트·Monitor)
BG_STARTED = re.compile(r"(Command running in background|Command did not complete within .{0,40}moved to the background|Async agent launched|Monitor started)", re.I)
BG_MAX_SEC = 6 * 3600   # 완료 알림을 놓쳐도 6시간 지나면 기다림에서 뺀다
SUBAGENT_ACTIVE_SEC = 45     # 서브에이전트 기록이 이 시간 안에 바뀌었으면 출근 중으로 본다
SUBAGENT_SCAN_SEC = 600      # 이보다 오래된 서브에이전트 파일은 아예 열지 않는다
STALL_SEC = 90               # 생각만 하는데 기록이 이만큼 조용하면 '막힘'
RECENT_N = 8
TIMELINE_SEC = 30 * 60   # 타임라인: 최근 30분의 도구 사용 구간과 사람이 말을 건 시각
TIMELINE_N = 60          # 그중 최근 것만(세션 하나에 보내는 구간 수 상한)
# 컨텍스트 창 크기(토큰). 모델 이름에 [1m] 이 붙었거나 이미 20만을 넘겨 쓴 기록이 있으면 100만으로 본다.
# 기본이 100만인 모델은 이름 앞부분으로 적는다(opus-5 는 96만 토큰에서 자동 압축된 기록으로 확인).
# 맞지 않으면 CLAUDE_OFFICE_CONTEXT_WINDOW 로 한 값을 정한다.
CONTEXT_DEFAULT = 200_000
CONTEXT_1M_PREFIXES = ("opus-5",)   # 'claude-' 를 뗀 이름 기준
CONTEXT_OVERRIDE = int(os.environ.get("CLAUDE_OFFICE_CONTEXT_WINDOW") or 0)
HEARTBEAT_SEC = 10
WAIT_SEC = 25           # 메시지 롱폴링(/api/outbox/wait) 한 번에 기다리는 시간(허브 최대 25초)


_project_cache = {}


def project_of(cwd):
    """세션 폴더 → (층 이름, worktree 이름). 층 = git 저장소 이름.

    git worktree(.git 이 'gitdir: <주 저장소>/.git/worktrees/<이름>' 파일)는 주 저장소 이름으로 묶어 같은 층에 둔다
    (예: Orca 가 만든 ~/orca/workspaces/DailyGoal/dg-en-c0 → DailyGoal 층, worktree dg-en-c0).
    저장소 안의 하위 폴더에서 연 세션도 저장소 이름으로 본다. 홈 폴더 위로는 올라가지 않는다(홈이 저장소여도 무시).
    git 이 아니면 폴더 이름 그대로."""
    cwd = (cwd or "").rstrip("/\\")
    if cwd in _project_cache:
        return _project_cache[cwd]
    out = (os.path.basename(cwd), "")
    home = os.path.abspath(os.path.expanduser("~"))
    d = cwd
    for _ in range(12):
        if not d or (os.path.abspath(d) == home and d != cwd):
            break
        g = os.path.join(d, ".git")
        try:
            if os.path.isdir(g):
                out = (os.path.basename(d), "")
                break
            if os.path.isfile(g):
                with open(g, encoding="utf-8", errors="replace") as f:
                    line = f.read(4096).strip()
                gitdir = line[7:].strip() if line.startswith("gitdir:") else ""
                if gitdir and not os.path.isabs(gitdir):
                    gitdir = os.path.normpath(os.path.join(d, gitdir))
                parts = gitdir.replace("\\", "/").rstrip("/").split("/")
                if len(parts) >= 3 and parts[-2] == "worktrees":   # <주 저장소>/.git/worktrees/<이름>
                    common = "/".join(parts[:-2])                   # <주 저장소>/.git
                    main = os.path.basename(os.path.dirname(common)) if os.path.basename(common) == ".git" else os.path.basename(common)
                    out = (main or os.path.basename(d), os.path.basename(d))
                else:   # 서브모듈 등: 그 폴더가 저장소 뿌리
                    out = (os.path.basename(d), "")
                break
        except OSError:
            break
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    if len(_project_cache) > 500:
        _project_cache.clear()
    _project_cache[cwd] = out
    return out


def short(s, n=48):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def target_of(name, inp, detail):
    """도구 입력에서 화면에 보일 짧은 대상만 뽑는다. 원문(명령·본문)은 넘기지 않는다."""
    if detail == "none" or not isinstance(inp, dict):
        return ""
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return os.path.basename(p)
    if name == "Bash":
        d = inp.get("description")
        if d:
            return short(d)
        cmd = (inp.get("command") or "").strip().split()
        return os.path.basename(cmd[0]) if cmd else ""
    if name in ("Grep", "Glob"):
        return short(inp.get("pattern", ""), 32)
    if name == "WebFetch":
        return urllib.parse.urlparse(inp.get("url", "")).hostname or ""
    if name == "WebSearch":
        return short(inp.get("query", ""), 32)
    if name in ("Agent", "Task"):
        return short(inp.get("description", ""), 40)
    if name == "Skill":
        return short(inp.get("skill", ""), 32)
    if name == "SendMessage":
        return short(inp.get("to", ""), 24)
    return ""


def context_window(model, seen):
    """그 세션의 컨텍스트 창 크기. seen = 이 세션에서 본 가장 큰 컨텍스트 사용량."""
    if CONTEXT_OVERRIDE > 0:
        return CONTEXT_OVERRIDE
    if "[1m]" in model or model.startswith(CONTEXT_1M_PREFIXES) or seen > CONTEXT_DEFAULT:
        return 1_000_000
    return CONTEXT_DEFAULT


def patch_lines(res):
    """Edit/Write 결과(toolUseResult)에서 더한 줄·뺀 줄 수. 새 파일은 내용 줄 수를 더한 것으로 센다."""
    if not isinstance(res, dict):
        return 0, 0
    if res.get("type") == "create" and isinstance(res.get("content"), str):
        return res["content"].count("\n") + (0 if res["content"].endswith("\n") or not res["content"] else 1), 0
    add = rem = 0
    for h in res.get("structuredPatch") or []:
        for ln in (h.get("lines") or []) if isinstance(h, dict) else []:
            if isinstance(ln, str) and ln[:1] == "+":
                add += 1
            elif isinstance(ln, str) and ln[:1] == "-":
                rem += 1
    return add, rem


def iso_ts(s):
    # "2026-10-20T13:46:45.950Z" → epoch. 3.9 의 fromisoformat 은 Z 를 못 읽는다.
    try:
        from datetime import datetime, timezone
        base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None
    m = re.match(r"\.(\d{1,6})", s[19:])   # 소수점 아래(밀리초)까지 — 타임라인의 짧은 도구 길이
    return base + (float("0." + m.group(1)) if m else 0.0)


def say_of(text):
    # 마크다운 장식을 걷어내고 한 줄로 줄인다
    t = text.replace("```", " ").replace("**", "").replace("`", "")
    t = " ".join(w for w in t.split() if not set(w) <= set("#>-*|"))
    return short(t, SAY_CHARS)


class Transcript:
    """jsonl 을 새로 붙은 만큼만 읽어 지금 걸린 도구·최근 도구·도구 횟수·제목·마지막 말을 유지한다."""

    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.rest = b""
        self.pending = {}
        self.recent = []
        self.tools = 0
        self.title = ""
        self.say = ""
        self.mode = ""
        self.bg = {}            # 아직 끝나지 않은 백그라운드 작업: tool_use_id -> {tool, target, ts}
        self.tools_by_id = {}   # tool_use_id -> {tool, target, ts} (결과가 올 때 백그라운드인지 판단용, 최근 것만)
        self.tasks = {}         # 할 일 목록: 번호 -> {s: 제목, st: pending|in_progress|completed}
        self.task_create = {}   # TaskCreate 의 tool_use_id -> 제목(결과의 'Task #N' 으로 번호를 받는다)
        self.model = ""         # 마지막 답변의 모델(claude- 뗀 이름)
        self.branch = ""        # 마지막 기록의 git 브랜치
        self.ctx = 0            # 지금 컨텍스트 사용량 = 마지막 답변의 입력 + 캐시 읽기 + 캐시 쓰기 토큰
        self.ctx_seen = 0       # 이 세션에서 본 가장 큰 사용량(창 크기 짐작용)
        self.out_tokens = 0     # 이 세션이 만든 출력 토큰 합(같은 답변이 여러 줄로 나뉘어도 한 번만)
        self.usage_ids = set()
        self.compacts = 0       # 자동·수동 압축 횟수와 마지막 시각
        self.compact_at = None
        self.lines = [0, 0]     # Edit/Write 로 더한 줄·뺀 줄
        self.spans = []         # 타임라인: [도구, 시작, 끝(None=아직), 대상, 실패 여부]
        self.span_by_id = {}    # tool_use_id -> spans 의 항목(결과가 오면 끝을 채운다)
        self.prompts = []       # 사람이 말을 건 시각(내용은 보내지 않는다)
        self.last = None
        self.ino = None

    def read(self, detail):
        try:
            st = os.stat(self.path)
        except OSError:
            return self
        if self.ino != st.st_ino or st.st_size < self.offset:  # 처음이거나 파일이 바뀜
            self.__init__(self.path)
            self.ino = st.st_ino
            if st.st_size > FIRST_READ_BYTES:
                self.offset = st.st_size - FIRST_READ_BYTES
        if st.st_size == self.offset:
            if self.last is None:
                self.last = st.st_mtime
            return self
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read(st.st_size - self.offset)
        self.offset = st.st_size
        lines = (self.rest + data).split(b"\n")
        self.rest = lines.pop()  # 아직 덜 쓴 마지막 줄
        for raw in lines:
            if raw:
                self._feed(raw, detail)
        if self.last is None:
            self.last = st.st_mtime
        return self

    def _feed(self, raw, detail):
        try:
            rec = json.loads(raw)
        except ValueError:
            return
        t = rec.get("type")
        if t == "queue-operation" and "<task-notification>" in str(rec.get("content") or ""):
            self._notification(str(rec.get("content")))
            return
        if t == "attachment":
            att = rec.get("attachment") or {}
            if isinstance(att, dict) and att.get("type") == "queued_command":
                self._notification(str(att.get("prompt") or ""))
            return
        if t == "permission-mode":
            self.mode = str(rec.get("permissionMode") or "")[:32]
            return
        if t in ("ai-title", "custom-title"):
            self.title = short(rec.get("customTitle") or rec.get("aiTitle") or rec.get("title") or "", 40)
            return
        ts = iso_ts(rec["timestamp"]) if rec.get("timestamp") else None
        if ts:
            self.last = ts
        if rec.get("gitBranch") and not rec.get("isSidechain"):
            self.branch = short(rec["gitBranch"], 40) if detail != "none" else ""
        if t == "system" and rec.get("subtype") == "compact_boundary":
            cm = rec.get("compactMetadata") if isinstance(rec.get("compactMetadata"), dict) else {}
            self.compacts += 1
            self.compact_at = ts or time.time()
            self.ctx_seen = max(self.ctx_seen, int(cm.get("preTokens") or 0))
            self.ctx = int(cm.get("postTokens") or 0)
            return
        msg = rec.get("message")
        if t == "user" and ts and self._is_prompt(rec, msg):
            self.prompts = (self.prompts + [ts])[-20:]
        if t == "assistant" and isinstance(msg, dict) and not rec.get("isSidechain"):
            self._usage(msg)   # 예전 버전이 같은 파일에 적던 서브에이전트(사이드체인) 답변은 이 세션의 컨텍스트가 아니다
        if t == "user" and rec.get("toolUseResult"):
            add, rem = patch_lines(rec.get("toolUseResult"))
            self.lines[0] += add
            self.lines[1] += rem
        if isinstance(msg, dict) and isinstance(msg.get("content"), str) and "<task-notification>" in msg["content"]:
            self._notification(msg["content"])   # 백그라운드 완료 알림은 문자열 사용자 메시지로도 온다
            return
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            return
        for c in msg["content"]:
            if not isinstance(c, dict):
                continue
            ct = c.get("type")
            if ct == "tool_use":
                name = c.get("name", "?")
                inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                item = {"tool": name, "target": target_of(name, inp, detail), "ts": ts}
                self.pending[c.get("id")] = item
                self.tools_by_id[c.get("id")] = dict(item, bg=bool(inp.get("run_in_background")))
                if len(self.tools_by_id) > 400:
                    for k in list(self.tools_by_id)[:200]:
                        del self.tools_by_id[k]
                self.recent = (self.recent + [item])[-RECENT_N:]
                span = [name, ts or time.time(), None, item["target"][:24], False]
                self.spans = (self.spans + [span])[-TIMELINE_N * 2:]
                self.span_by_id[c.get("id")] = span
                if len(self.span_by_id) > 200:
                    for k in list(self.span_by_id)[:100]:
                        del self.span_by_id[k]
                self.tools += 1
                self._task_tool(name, inp, c.get("id"), detail)
            elif ct == "tool_result":
                tid = c.get("tool_use_id")
                self.pending.pop(tid, None)
                span = self.span_by_id.pop(tid, None)
                if span:
                    span[2] = ts or time.time()
                    span[4] = bool(c.get("is_error"))
                text = c.get("content")
                if not isinstance(text, str):
                    text = " ".join(x.get("text", "") for x in text if isinstance(x, dict)) if isinstance(text, list) else ""
                info = self.tools_by_id.get(tid)
                # 결과가 '백그라운드로 시작했다'로 시작할 때만(명령 출력에 그 문구가 섞여 있어도 오판하지 않게)
                if info and (info.get("bg") or BG_STARTED.match(text.lstrip())):
                    self.bg[tid] = {"tool": info["tool"], "target": info["target"], "ts": ts or time.time()}
                if tid in self.task_create:
                    m = re.search(r"Task #(\d+)", text)
                    if m:
                        self.tasks[m.group(1)] = {"s": self.task_create.pop(tid), "st": "pending"}
            elif ct == "text" and msg.get("role") == "user" and "<task-notification>" in c.get("text", ""):
                self._notification(c.get("text", ""))
            elif ct == "text" and msg.get("role") == "assistant" and detail != "none":
                txt = say_of(c.get("text", ""))
                if txt:
                    self.say = txt

    @staticmethod
    def _is_prompt(rec, msg):
        """사람이 입력한 말인지. 요즘 기록은 origin.kind 가 human, 예전 기록은 isMeta·태그로 걸러 짐작한다."""
        origin = rec.get("origin")
        if isinstance(origin, dict):
            return origin.get("kind") == "human"
        if rec.get("isMeta") or rec.get("isSidechain") or not isinstance(msg, dict):
            return False
        ct = msg.get("content")
        if isinstance(ct, list):
            if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in ct):
                return False
            ct = next((x.get("text", "") for x in ct if isinstance(x, dict) and x.get("type") == "text"), "")
        return isinstance(ct, str) and bool(ct.strip()) and not ct.lstrip().startswith("<")

    def timeline(self, now):
        """최근 TIMELINE_SEC 안에 걸친 도구 구간과 사람이 말을 건 시각. 시각은 0.1초 단위로 줄인다."""
        since = now - TIMELINE_SEC
        spans = [[s[0], round(s[1], 1), None if s[2] is None else round(s[2], 1), s[3], 1 if s[4] else 0]
                 for s in self.spans if (s[2] is None and s[1] >= since - 6 * 3600) or (s[2] or 0) >= since][-TIMELINE_N:]
        return {"spans": spans, "prompts": [round(p, 1) for p in self.prompts if p >= since]}

    def _usage(self, msg):
        """답변의 토큰 사용량으로 지금 컨텍스트 크기와 출력 토큰 합을 갱신한다."""
        model = str(msg.get("model") or "")
        u = msg.get("usage")
        if not model or model.startswith("<") or not isinstance(u, dict):
            return   # <synthetic> = Claude Code 가 만든 안내 줄(실제 호출 아님)
        self.model = short(model[7:] if model.startswith("claude-") else model, 32)
        try:
            ctx = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) \
                + int(u.get("cache_creation_input_tokens") or 0)
            out = int(u.get("output_tokens") or 0)
        except (TypeError, ValueError):
            return
        if ctx:
            self.ctx = ctx
            self.ctx_seen = max(self.ctx_seen, ctx)
        mid = msg.get("id")
        if mid and mid not in self.usage_ids:
            self.usage_ids.add(mid)
            if len(self.usage_ids) > 2000:
                self.usage_ids = set(list(self.usage_ids)[-1000:])
            self.out_tokens += out

    def usage(self):
        """화면에 보낼 모델·컨텍스트·토큰·바꾼 줄 요약."""
        win = context_window(self.model, self.ctx_seen) if self.model else 0
        return {
            "model": self.model,
            "ctx": {"used": self.ctx, "max": win} if self.model else None,
            "outTokens": self.out_tokens,
            "compacts": self.compacts,
            "compactAt": self.compact_at,
            "lines": list(self.lines),
        }

    def _notification(self, text):
        """백그라운드 작업 완료 알림(<task-notification>)이 오면 그 작업을 기다림 목록에서 뺀다."""
        for block in re.findall(r"<task-notification>(.*?)</task-notification>", text, re.S):
            tid = re.search(r"<tool-use-id>([^<]+)</tool-use-id>", block)
            st = re.search(r"<status>([^<]+)</status>", block)
            if tid and (not st or st.group(1).strip() != "running"):
                self.bg.pop(tid.group(1).strip(), None)

    def _task_tool(self, name, inp, use_id, detail):
        """Claude Code 의 할 일 목록 도구를 따라가 체크리스트를 유지한다(TaskCreate/TaskUpdate, 예전 TodoWrite)."""
        if name == "TaskCreate":
            if self.tasks and all(t["st"] == "completed" for t in self.tasks.values()):
                self.tasks = {}   # 다 끝난 목록 뒤에 새로 만들면 새 묶음으로 본다
            self.task_create[use_id] = short(inp.get("subject") or inp.get("activeForm") or "", 80) if detail != "none" else "할 일"
        elif name == "TaskUpdate":
            t = self.tasks.get(str(inp.get("taskId", "")))
            if t:
                st = inp.get("status")
                if st == "deleted":
                    self.tasks.pop(str(inp.get("taskId")), None)
                elif st in ("pending", "in_progress", "completed"):
                    t["st"] = st
                if inp.get("subject") and detail != "none":
                    t["s"] = short(inp["subject"], 80)
        elif name == "TodoWrite" and isinstance(inp.get("todos"), list):
            self.tasks = {str(i + 1): {"s": short(x.get("content", ""), 80) if detail != "none" else "할 일",
                                       "st": x.get("status", "pending")}
                          for i, x in enumerate(inp["todos"]) if isinstance(x, dict)}

    def background(self, now):
        """아직 끝나지 않은 백그라운드 작업(너무 오래된 것은 끝난 것으로 본다)."""
        for k in [k for k, v in self.bg.items() if now - (v.get("ts") or now) > BG_MAX_SEC]:
            del self.bg[k]
        return list(self.bg.values())

    def current(self):
        if not self.pending:
            return None
        return max(self.pending.values(), key=lambda v: v["ts"] or 0)


class Collector:
    def __init__(self, detail):
        self.detail = detail
        self.speech = True      # 허브 설정 'speech' 를 따른다
        self.transcripts = {}   # path -> Transcript
        self.paths = {}         # sessionId -> jsonl path
        self.metas = {}         # meta path -> dict
        self.used = set()
        self.sockets = {}       # sessionId -> 그 세션의 수신함 소켓 경로(sessions/<pid>.json 의 messagingSocketPath)

    def transcript(self, path):
        self.used.add(path)
        t = self.transcripts.get(path)
        if t is None:
            t = self.transcripts[path] = Transcript(path)
        return t.read(self.detail)

    def find_jsonl(self, sid, cwd, root):
        p = self.paths.get(sid)
        if p and os.path.exists(p):
            return p
        enc = "".join(ch if ch.isalnum() else "-" for ch in cwd)
        p = os.path.join(root, "projects", enc, sid + ".jsonl")
        if not os.path.exists(p):
            hits = glob.glob(os.path.join(glob.escape(root), "projects", "*", sid + ".jsonl"))
            p = hits[0] if hits else None
        if p:
            self.paths[sid] = p
        return p

    def meta(self, path):
        m = self.metas.get(path)
        if m is None:
            try:
                with open(path, encoding="utf-8") as f:
                    m = json.load(f)
            except (OSError, ValueError):
                m = {}
            self.metas[path] = m
        return m

    def said(self, tr):
        return tr.say if self.speech else ""

    def subagents(self, jsonl, parent, now):
        d = os.path.join(jsonl[: -len(".jsonl")], "subagents")
        if not os.path.isdir(d):
            return []
        out = []
        for p in glob.glob(os.path.join(d, "agent-*.jsonl")):
            try:
                mtime = os.path.getmtime(p)
            except OSError:
                continue
            if now - mtime > SUBAGENT_SCAN_SEC:
                continue
            meta = self.meta(p[: -len(".jsonl")] + ".meta.json")
            # 부모가 아직 결과를 기다리는 Agent 호출(포그라운드)이거나, 기록이 방금 바뀌었으면(백그라운드) 출근 중
            active = meta.get("toolUseId") in parent.pending or now - mtime < SUBAGENT_ACTIVE_SEC
            if not active:
                continue
            tr = self.transcript(p)
            cur = tr.current()
            out.append({
                "id": os.path.basename(p)[6:-6],
                "type": short(meta.get("agentType", "subagent"), 32),
                "description": short(meta.get("description", ""), 40) if self.detail != "none" else "",
                "tool": cur["tool"] if cur else "",
                "target": cur["target"] if cur else "",
                "since": (cur or {}).get("ts") or tr.last,
                "tools": tr.tools,
                "say": self.said(tr),
                "model": tr.model,
            })
        return sorted(out, key=lambda s: s["id"])

    def collect(self):
        now = time.time()
        self.used = set()
        socks = {}   # 다 모은 뒤 한 번에 바꾼다 — 메시지 스레드가 반쯤 찬 사전을 읽지 않게
        agents = []
        seen = set()
        files = [(r, f) for r in claude_roots() for f in glob.glob(os.path.join(glob.escape(r), "sessions", "*.json"))]
        for root, f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    s = json.load(fh)
                if not pid_alive(int(s["pid"])):  # 죽은 프로세스의 파일이 남아 있을 수 있다
                    continue
            except (OSError, ValueError, KeyError):
                continue
            sid, cwd = s.get("sessionId", ""), s.get("cwd", "")
            if sid in seen:  # 같은 세션이 두 설정 폴더에 잡히면 한 번만
                continue
            seen.add(sid)
            status = s.get("status", "idle")
            jsonl = self.find_jsonl(sid, cwd, root) if sid else None
            tr = self.transcript(jsonl) if jsonl else Transcript("")
            last = tr.last or (s.get("updatedAt", 0) / 1000)
            cur = tr.current() if status == "busy" else None
            bg = tr.background(now)
            if status == "busy":
                kind = "working" if cur else "thinking"
            elif status == "shell":
                kind = "shell"
            elif bg or status == "waiting":
                kind = "waiting"   # 턴은 끝났지만 백그라운드 작업(명령·서브에이전트)을 기다리는 중
            else:
                kind = "idle"
            ev = hook_event(sid, s.get("startedAt", 0) / 1000) if status == "busy" else None
            approval = bool(ev) and ev.get("kind") == "permission"
            if approval:
                kind = "approval"   # 권한 창을 띄우고 사용자의 승인을 기다리는 중(훅을 넣은 경우만 안다)
            since = (ev["ts"] if approval else None) or (cur or {}).get("ts") or (s.get("statusUpdatedAt", 0) / 1000) or last
            subs = self.subagents(jsonl, tr, now) if jsonl else []
            project, worktree = project_of(cwd)
            sl = status_line(sid, now)
            usage = tr.usage()
            if sl and sl.get("ctxSize") and usage.get("ctx"):   # 상태 표시줄이 알려 준 창 크기가 짐작보다 정확하다
                usage["ctx"] = dict(usage["ctx"], max=sl["ctxSize"])
            sock = s.get("messagingSocketPath") or ""
            if sock:
                socks[sid] = sock
            agents.append({
                "id": sid,
                "pid": s.get("pid"),
                "name": s.get("name") or os.path.basename(cwd),
                "title": tr.title,
                "project": project,
                "worktree": worktree,
                "profile": profile_of(root),
                "status": status,
                "kind": kind,
                "tool": cur["tool"] if cur else (str(ev.get("tool_name") or "") if approval else ""),
                "target": cur["target"] if cur else "",
                "since": since,
                "lastActivity": last,
                # 도구도 서브에이전트도 없이 생각만 하는데 기록이 오래 조용하면 '막힘'. 긴 Bash 는 막힘이 아니다.
                "stalled": kind == "thinking" and not subs and now - last > STALL_SEC,
                "startedAt": s.get("startedAt", 0) / 1000,
                "tools": tr.tools,
                "say": self.said(tr),
                "mode": tr.mode,
                "branch": tr.branch,
                **usage,
                "limits": dict(sl["limits"], ts=sl["ts"]) if sl and sl.get("limits") else None,
                "timeline": tr.timeline(now),
                "bg": [{"tool": b["tool"], "target": b["target"], "ts": b.get("ts")} for b in bg][:5],
                "todos": list(tr.tasks.values())[:30],
                "canMessage": MESSAGES and not WINDOWS and socket_ok(sock),
                "recent": [{"tool": r["tool"], "target": r["target"], "ts": r["ts"]} for r in tr.recent[::-1]],
                "subagents": subs,
            })
        for p in list(self.transcripts):  # 끝난 세션·서브에이전트는 잊는다
            if p not in self.used:
                del self.transcripts[p]
        agents.sort(key=lambda a: a["startedAt"])
        self.sockets = socks
        return agents


# 이 컴퓨터의 Claude 전역 지침에 '할 일 체크리스트' 규칙이 있는지. 없으면 화면이 넣을 문장을 안내한다
_rule_cache = {"at": 0.0, "ok": False}


# ---------- 이 컴퓨터의 자원(CPU·GPU·메모리·디스크) ----------
# 화면 왼쪽 아래 게이지용. 따로 도는 스레드가 SYS_SEC 마다 재고, 보낼 때는 마지막 값을 붙인다(수집 고리를 막지 않게).
# 표준 라이브러리와 기본 명령만 쓴다. 잴 수 없는 값(예: GPU 를 읽을 길이 없는 컴퓨터)은 None.
SYS_SEC = 5
_sys = {"val": None, "started": False}


def _run(cmd, timeout=4):
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if WINDOWS else 0)   # Windows: 콘솔 창을 띄우지 않는다
        return r.stdout if r.returncode == 0 else ""
    except (OSError, ValueError, Exception):
        return ""


def _pct(x):
    return None if x is None else max(0, min(100, int(round(x))))


class _CpuDelta:
    """누적 (바쁜 시간, 전체 시간)의 차로 사용률을 낸다(리눅스 /proc/stat, Windows GetSystemTimes)."""

    def __init__(self):
        self.prev = None

    def __call__(self, busy, total):
        prev, self.prev = self.prev, (busy, total)
        if not prev or total <= prev[1]:
            return None
        return 100.0 * (busy - prev[0]) / (total - prev[1])


_cpu_delta = _CpuDelta()


def _cpu():
    if sys.platform == "darwin":
        # top 의 두 번째 표본이 최근 1초 사용률이다(첫 표본은 부팅 뒤 평균)
        out = _run(["top", "-l", "2", "-n", "0", "-s", "1"], timeout=8)   # 바쁠 때는 2초를 넘기기도 한다
        m = re.findall(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys", out)
        return float(m[-1][0]) + float(m[-1][1]) if m else None
    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None
        v = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime   # noqa: E731
        total = v(kern) + v(user)   # 커널 시간에 유휴 시간이 들어 있다
        return _cpu_delta(total - v(idle), total)
    try:
        with open("/proc/stat") as f:
            nums = [int(x) for x in f.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return _cpu_delta(sum(nums) - idle, sum(nums))


def _mem():
    if sys.platform == "darwin":
        total = _run(["sysctl", "-n", "hw.memsize"]).strip()
        vm = _run(["vm_stat"])
        page = re.search(r"page size of (\d+)", vm)
        got = {k: int(v) for k, v in re.findall(r'^"?([^":]+)"?:\s+(\d+)\.', vm, re.M)}
        if not (total.isdigit() and page):
            return None, None
        # 활성 상태 보기의 '사용된 메모리'에 가깝게: 앱(익명) + 고정 + 압축
        used = got.get("Anonymous pages", got.get("Pages active", 0)) - got.get("Pages purgeable", 0) \
            + got.get("Pages wired down", 0) + got.get("Pages occupied by compressor", 0)
        return 100.0 * used * int(page.group(1)) / int(total), int(total)
    if WINDOWS:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                        ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
        m = MS(); m.len = ctypes.sizeof(MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None, None
        return float(m.load), int(m.total)
    try:
        with open("/proc/meminfo") as f:
            kv = {ln.split(":")[0]: int(ln.split()[1]) * 1024 for ln in f if ln.split()[1:2] and ln.split()[1].isdigit()}
        return 100.0 * (kv["MemTotal"] - kv["MemAvailable"]) / kv["MemTotal"], kv["MemTotal"]
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None, None


def _gpu():
    if sys.platform == "darwin":
        # Apple 실리콘(그리고 일부 인텔 맥)의 GPU 드라이버가 사용률을 알려 준다. 권한 없이 읽힌다
        m = re.findall(r'"Device Utilization %"\s*=\s*(\d+)', _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"]))
        return max(int(x) for x in m) if m else None
    import shutil
    if shutil.which("nvidia-smi"):
        vals = [int(x) for x in re.findall(r"\d+", _run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"]))]
        return max(vals) if vals else None
    return None


def _disk():
    import shutil
    try:
        # 맥은 / 가 읽기 전용 시스템 볼륨이라 사용자 데이터가 있는 홈 쪽 볼륨을 잰다
        u = shutil.disk_usage(os.path.expanduser("~"))
        return 100.0 * u.used / u.total, u.total
    except OSError:
        return None, None


def sample_system():
    """한 번 재서 {cpu, gpu, mem, memTotal, disk, diskTotal, ts} 를 돌려준다(백분율은 0~100 정수)."""
    out = {"ts": int(time.time())}
    for name, fn in (("cpu", _cpu), ("gpu", _gpu)):
        try:
            out[name] = _pct(fn())
        except Exception:
            out[name] = None
    for name, fn in (("mem", _mem), ("disk", _disk)):
        try:
            pct, total = fn()
        except Exception:
            pct, total = None, None
        out[name], out[name + "Total"] = _pct(pct), total
    return out


def system_stats():
    """마지막으로 잰 값. 처음 부를 때 재는 스레드를 띄운다(그 전에는 None)."""
    if not _sys["started"]:
        _sys["started"] = True

        def loop():
            while True:
                _sys["val"] = sample_system()
                time.sleep(SYS_SEC)
        threading.Thread(target=loop, name="system-stats", daemon=True).start()
    return _sys["val"]


def checklist_rule_installed():
    if time.time() - _rule_cache["at"] < 60:
        return _rule_cache["ok"]
    ok = False
    for root in claude_roots():
        for path in [os.path.join(root, "CLAUDE.md")]:
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            # '@~/.claude/CLAUDE.md' 처럼 다른 파일을 끌어오는 줄은 한 단계만 따라간다(Orca 프로필이 이렇게 한다)
            for inc in re.findall(r"(?m)^@(\S+)", text):
                try:
                    with open(os.path.expanduser(inc), encoding="utf-8") as f:
                        text += "\n" + f.read()
                except OSError:
                    pass
            if "TaskCreate" in text or "TodoWrite" in text:
                ok = True
    _rule_cache.update(at=time.time(), ok=ok)
    return ok


# 이 컴퓨터의 선택 기능 설치 상태. 대시보드 「안내」 탭의 설정 점검표가 이걸로 어디까지 했는지 보여 준다.
# 설정 폴더(~/.claude, Orca 프로필…)마다 settings.json 을 읽어 claude-office 훅·승인 훅·상태 표시줄이 걸렸는지 센다.
# 경로·내용은 보내지 않고 개수만 보낸다.
_setup_cache = {"at": 0.0, "val": None}


def setup_status():
    if _setup_cache["val"] is not None and time.time() - _setup_cache["at"] < 60:
        return _setup_cache["val"]
    roots = claude_roots()
    hooks = approve = status = todo = 0
    home = os.path.expanduser("~")
    detail = []
    for root in roots:
        # 화면에 그 폴더용 명령을 보이려고 홈 아래 경로만 '~/…' 로 보낸다(사용자 이름 없이)
        label = "~" + root[len(home):].replace("\\", "/") if root.startswith(home) else os.path.basename(root)
        row = {"label": label[:160], "hooks": False, "approveHook": False, "statusline": False, "todoTools": False}
        detail.append(row)
        try:
            with open(os.path.join(root, "settings.json"), encoding="utf-8-sig") as f:
                st = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(st, dict):
            continue
        text = json.dumps(st.get("hooks") or {})
        sl = st.get("statusLine")
        env = st.get("env") if isinstance(st.get("env"), dict) else {}
        row.update(hooks="claude_office_hook.py" in text, approveHook="claude_office_approve.py" in text,
                   statusline=isinstance(sl, dict) and "claude_office_statusline.py" in str(sl.get("command") or ""),
                   # 새 모델(Opus 4.7·Sonnet 4.6·Haiku 4.5 보다 뒤)은 할 일 도구가 기본으로 빠진다. 이 값이 있어야 켜진다
                   todoTools=str(env.get("CLAUDE_CODE_ENABLE_TODO_TOOLS", "")).strip().lower() in ("1", "true", "yes", "on"))
        hooks += row["hooks"]
        approve += row["approveHook"]
        status += row["statusline"]
        todo += row["todoTools"]
    repo = ""
    try:   # 수집기 설치가 적어 둔 저장소 위치(대시보드가 명령 앞에 cd 를 붙인다)
        with open(os.path.join(home, ".claude-office", "repo"), encoding="utf-8-sig") as f:
            r = f.read().strip()
        repo = ("~" + r[len(home):].replace("\\", "/")) if r.startswith(home) else r.replace("\\", "/")
    except OSError:
        pass
    # 이 수집기를 돌리는 파이썬(창 없는 pythonw 대신 같은 폴더의 python). 점검표가 이걸로 명령을 만든다 —
    # Windows 는 py 실행기가 없거나(Anaconda 등) 다른 파이썬일 수 있다
    exe = sys.executable or ""
    if WINDOWS and os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        exe = alt if os.path.exists(alt) else exe
    py = ("~" + exe[len(home):]) if exe.startswith(home) else exe
    val = {"repo": repo[:200], "python": py.replace("\\", "/")[:200], "os": "windows" if WINDOWS else ("mac" if sys.platform == "darwin" else "linux"),
           "roots": len(roots), "hooks": hooks, "approveHook": approve, "statusline": status, "todoTools": todo, "rootsDetail": detail[:10],
           "messagesEnv": MESSAGES, "approveEnv": APPROVE}
    _setup_cache.update(at=time.time(), val=val)
    return val


def post(hub, payload, timeout=5):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Office-Token"] = TOKEN
    req = urllib.request.Request(hub.rstrip("/") + "/api/ingest", data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def api(hub, path, payload, timeout=5):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Office-Token"] = TOKEN
    req = urllib.request.Request(hub.rstrip("/") + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# Claude Code 가 수신함 소켓을 만드는 곳만 받는다(허브가 엉뚱한 경로를 시키지 못하게)
_SOCK_DIRS = re.compile(r"^(/private)?/tmp/cc-socks(-\d+)?/[^/]+$|^/run/user/\d+/cc-socks/[^/]+$")


def socket_ok(path):
    if WINDOWS or not path or not _SOCK_DIRS.match(path):
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def deliver(sock_path, text):
    """세션 수신함 소켓에 한 줄짜리 메시지를 쓴다(Claude Code 의 교차 세션 메시지 형식).

    인증 줄은 보내지 않는다 — 받는 세션은 이 메시지를 '다른 세션이 보낸 것'으로 다루고, 그 세션의
    수신 규칙(crossSessionInbound, 권한 모드)에 따라 바로 전달하거나 터미널에서 승인을 기다린다."""
    line = json.dumps({"type": "user", "message": {"role": "user", "content": MESSAGE_PREFIX + text}}, ensure_ascii=False)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(sock_path)
        s.sendall((line + "\n").encode("utf-8"))
    finally:
        s.close()


def handle_outbox(hub, host, col, items):
    """허브에서 받은 '이 컴퓨터 세션에 보낼 메시지'를 전달하고 결과를 알린다."""
    sockets = col.sockets   # 수집 루프가 통째로 바꿔 끼우는 사전 — 이 순간의 것을 잡아 둔다
    for m in items:
        ok, err = False, ""
        text = str(m.get("text", ""))[:MAX_MESSAGE]
        sock = sockets.get(m.get("session"))
        if not MESSAGES:
            err = "이 컴퓨터의 수집기에서 메시지 받기가 꺼져 있다(CLAUDE_OFFICE_MESSAGES)"
        elif WINDOWS:
            err = "Windows 수집기는 아직 메시지 보내기를 지원하지 않는다"
        elif not text.strip():
            err = "빈 메시지"
        elif not sock or not socket_ok(sock):
            err = "그 세션의 수신함을 찾지 못했다(끝났거나 메시지를 받지 않는 세션)"
        else:
            try:
                deliver(sock, text)
                ok = True
            except Exception as e:   # OSError 말고도(UnicodeEncodeError 등) 이 메시지만 실패로 보고 다음으로
                err = f"전달 실패: {e}"
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "메시지", "전달" if ok else "실패", str(m.get("session", ""))[:8], err, flush=True)
        try:   # 보고가 실패해도 남은 메시지는 계속 전달한다(허브는 그 메시지를 60초 뒤 만료로 본다)
            api(hub, "/api/outbox/result", {"host": host, "id": m.get("id"), "ok": ok, "error": err})
        except Exception as e:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "메시지 결과 보고 실패:", repr(e), flush=True)


def outbox_loop(hub, host, col):
    """메시지 스레드: 허브에 롱폴링(/api/outbox/wait)을 계속 걸어 두고, 받으면 바로 전달한다.

    끊기거나 오류면 1초부터 두 배씩 최대 30초 쉬었다 다시 건다. 허브가 메시지를 끄거나(403)
    토큰이 다르면(401) 30초 쉰다. 허브가 예전 판이라 wait 가 없으면(404) 5분 동안 1초마다 pull 로 가져간다."""
    delay, legacy_until, failing = 1.0, 0.0, False
    while True:
        try:
            if time.time() < legacy_until:
                items = api(hub, "/api/outbox/pull", {"host": host}).get("messages", [])
                pause = 1.0
            else:
                started = time.monotonic()
                items = api(hub, "/api/outbox/wait", {"host": host, "timeout": WAIT_SEC},
                            timeout=WAIT_SEC + 10).get("messages", [])
                # 롱폴링인데 곧바로 빈 응답이면(이상한 허브·프록시) 쉬지 않고 두드리지 않게 1초 쉰다
                pause = 1.0 if not items and time.monotonic() - started < 1.0 else 0.0
            if items:
                handle_outbox(hub, host, col, items)
            delay, failing = 1.0, False
            time.sleep(pause)
        except urllib.error.HTTPError as e:
            if e.code == 404 and time.time() >= legacy_until:
                legacy_until = time.time() + 300
                continue
            time.sleep(30 if e.code in (401, 403, 404) else delay)
            delay = min(delay * 2, 30.0)
        except Exception as e:   # 연결 끊김·시간 초과 등. 스레드는 죽지 않는다
            if not failing:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "메시지 대기 연결 실패:", repr(e), flush=True)
                failing = True
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


def say_bye(hub, host):
    """정상 종료할 때 허브에 '떠남'을 알린다 — 허브가 30초를 기다리지 않고 바로 끊김으로 본다."""
    try:
        api(hub, "/api/hosts/bye", {"host": host}, timeout=2)
    except Exception:   # 허브가 꺼졌거나 예전 판이면 그냥 30초 기준에 맡긴다
        pass


def _exit_on_signal(signum, _frame):
    raise SystemExit(128 + signum)


def hub_speech(hub):
    with urllib.request.urlopen(hub.rstrip("/") + "/api/config", timeout=5) as r:
        return bool(json.load(r).get("speech", True))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hub", default=os.environ.get("CLAUDE_OFFICE_HUB") or "http://127.0.0.1:3006")
    ap.add_argument("--host", default=os.environ.get("CLAUDE_OFFICE_HOST") or socket.gethostname().split(".")[0])
    ap.add_argument("--env", help="설정 파일(KEY=VALUE) 경로")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--detail", choices=["basic", "none"], default=os.environ.get("CLAUDE_OFFICE_DETAIL") or "basic")
    ap.add_argument("--dump", action="store_true", help="한 번 모아 출력만 하고 끝낸다")
    ap.add_argument("--log", help="출력을 이 파일에 이어 쓴다(1MB 넘으면 시작할 때 비움). Windows 작업 스케줄러용")
    args = ap.parse_args()
    if args.log:
        try:
            if os.path.getsize(args.log) > 1024 * 1024:
                open(args.log, "w").close()
        except OSError:
            pass
        sys.stdout = sys.stderr = open(args.log, "a", encoding="utf-8", buffering=1)
    elif sys.stdout is None:   # 창 없는 pythonw 로 떴는데 --log 가 없으면 출력은 버린다
        sys.stdout = sys.stderr = open(os.devnull, "w")

    col = Collector(args.detail)
    if args.dump:
        json.dump(col.collect(), sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    # launchd·systemd 가 멈출 때 보내는 SIGTERM 도 Ctrl+C 처럼 '떠남'을 알리고 끝나게 한다.
    # Windows 작업 스케줄러는 신호 없이 프로세스를 끝내므로 거기서는 허브의 30초 기준으로 끊김이 된다.
    try:
        signal.signal(signal.SIGTERM, _exit_on_signal)
    except (ValueError, OSError, AttributeError):
        pass
    try:
        if MESSAGES and not WINDOWS:
            # 소켓 표를 먼저 채운다 — 비어 있으면 재시작 직후 허브에 쌓여 있던 메시지가 '수신함을 찾지 못했다' 로 실패한다
            try:
                col.collect()
            except Exception as e:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "수집 오류:", repr(e), flush=True)
            threading.Thread(target=outbox_loop, args=(args.hub, args.host, col), name="outbox", daemon=True).start()
        run(args, col)
    except (KeyboardInterrupt, SystemExit):
        say_bye(args.hub, args.host)
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "수집기 종료", flush=True)


class Sender:
    """허브로 보낸다. 처음과 다시 맞출 때는 전체(/api/ingest), 그다음은 바뀐 세션만(/api/ingest/patch).

    세션마다 lastActivity 를 뺀 내용을 비교해 바뀐 것만 set 에 담는다. lastActivity 만 바뀐 세션은
    HEARTBEAT_SEC 마다 한 번 함께 보낸다. 허브가 patch 를 모르면(예전 허브, 404) 전체 보내기로 돌아간다."""

    def __init__(self, hub, host):
        self.hub, self.host = hub, host
        self.seq = 0
        self.synced = False       # 허브가 우리 seq 를 알고 있다
        self.patch_ok = True      # 허브가 patch 를 받는다
        self.sigs, self.full, self.order, self.meta = {}, {}, [], None
        self.last_at = 0.0

    @staticmethod
    def _sig(a, with_activity=False):
        return json.dumps(a if with_activity else {k: v for k, v in a.items() if k != "lastActivity"}, sort_keys=True)

    def reset(self):
        self.synced = False

    def send(self, agents, meta, now=None):
        """보낼 게 있으면 보내고 무엇을 했는지 돌려준다('full'·'patch'·None). 네트워크 오류는 그대로 올린다."""
        now = time.time() if now is None else now
        sigs = {a["id"]: self._sig(a) for a in agents}
        order = [a["id"] for a in agents]
        beat = now - self.last_at > HEARTBEAT_SEC
        changed = [a for a in agents if self.sigs.get(a["id"]) != sigs[a["id"]]]
        if beat:   # 심장 박동 때는 lastActivity 만 바뀐 세션도 보낸다
            ids = {a["id"] for a in changed}
            changed += [a for a in agents if a["id"] not in ids and self.full.get(a["id"]) != self._sig(a, True)]
        removed = [i for i in self.sigs if i not in sigs]
        if not (changed or removed or order != self.order or meta != self.meta or beat):
            return None
        kind = None
        if self.synced and self.patch_ok:
            try:
                r = api(self.hub, "/api/ingest/patch", {"host": self.host, "base": self.seq, "seq": self.seq + 1,
                                                         "set": changed, "del": removed, "order": order, "meta": meta})
                if r.get("ok"):
                    self.seq += 1
                    kind = "patch"
                else:
                    self.synced = False   # 허브가 다시 떴거나 전송을 놓쳤다 → 아래에서 전체
            except urllib.error.HTTPError as e:
                if e.code not in (404, 405):
                    raise
                self.patch_ok = False     # 예전 허브: 앞으로는 전체만
        if kind is None:
            post(self.hub, {"host": self.host, "agents": agents, "meta": meta, "seq": self.seq + 1})
            self.seq += 1
            self.synced = True
            kind = "full"
        self.sigs, self.order, self.meta, self.last_at = sigs, order, meta, now
        self.full = {a["id"]: self._sig(a, True) for a in agents}
        return kind


def run(args, col):
    failing, cfg_at = False, 0.0
    sender = Sender(args.hub, args.host)
    while True:
        try:
            if time.time() - cfg_at > CONFIG_POLL_SEC:
                cfg_at = time.time()
                # 설정을 못 읽으면 말풍선을 보내지 않는다(꺼 둔 설정을 놓치지 않게)
                try:
                    col.speech = hub_speech(args.hub)
                except Exception:
                    col.speech = False
            agents = col.collect()
            meta = {"checklistRule": checklist_rule_installed(), "setup": setup_status()}
            if sys_val := system_stats():
                meta["sys"] = sys_val
            if sender.send(agents, meta):
                if failing:
                    print(time.strftime("%Y-%m-%d %H:%M:%S"), "허브 연결 복구", flush=True)
                    failing = False
                    cfg_at = 0.0
        except (urllib.error.URLError, OSError) as e:
            if not failing:  # 끊길 때 한 번만 남긴다(로그가 쌓이지 않게)
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "허브에 보내지 못함:", e, flush=True)
                failing = True
            sender.reset()   # 다시 붙으면 전체부터
        except Exception as e:  # 한 세션 파일이 이상해도 수집기는 죽지 않는다
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "수집 오류:", repr(e), flush=True)
        time.sleep(args.interval if not failing else 5)


if __name__ == "__main__":
    main()
