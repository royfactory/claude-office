#!/usr/bin/env python3
"""claude-office 수집기: 이 컴퓨터의 Claude Code 세션들을 읽어 허브로 보낸다(macOS, 리눅스는 시험 전).

읽는 곳(읽기만 한다):
  <설정 폴더>/sessions/<pid>.json                     세션 목록·이름·idle/busy
    (설정 폴더 = ~/.claude 와 Orca 프로필 ~/Library/Application Support/orca/claude-profiles/*/home)
  ~/.claude/projects/<cwd>/<sessionId>.jsonl          대화 기록 → 지금 쓰는 도구
  ~/.claude/projects/<cwd>/<sessionId>/subagents/     서브에이전트 기록

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
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if os.name == "nt":
    # Windows 에서는 os.kill(pid, 0) 이 '살아 있는지 확인'이 아니라 그 프로세스를 끝낸다 — Claude 세션이 꺼진다
    sys.exit("claude-office 수집기는 Windows 를 지원하지 않습니다(세션 생존 확인 방식이 다릅니다).")


def load_env(path):
    """KEY=VALUE 파일을 읽어 아직 없는 환경변수만 채운다."""
    if not path or not os.path.isfile(path):
        return
    with open(path) as f:
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

# Claude Code 설정 폴더들. 기본 ~/.claude 말고도 Orca 가 띄운 세션은 프로필마다 CLAUDE_CONFIG_DIR 이 따로 있다.
# 더 있으면 CLAUDE_OFFICE_ROOTS 에 콜론(:)으로 이어 적는다.
ROOT_GLOBS = [
    os.path.expanduser("~/.claude"),
    os.path.expanduser("~/Library/Application Support/orca/claude-profiles/*/home"),
] + [p for p in os.environ.get("CLAUDE_OFFICE_ROOTS", "").split(":") if p]


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
SUBAGENT_ACTIVE_SEC = 45     # 서브에이전트 기록이 이 시간 안에 바뀌었으면 출근 중으로 본다
SUBAGENT_SCAN_SEC = 600      # 이보다 오래된 서브에이전트 파일은 아예 열지 않는다
STALL_SEC = 90               # 생각만 하는데 기록이 이만큼 조용하면 '막힘'
RECENT_N = 8
HEARTBEAT_SEC = 10


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


def iso_ts(s):
    # "2026-10-20T13:46:45.950Z" → epoch. 3.9 의 fromisoformat 은 Z 를 못 읽는다.
    try:
        from datetime import datetime, timezone
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


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
        if t in ("ai-title", "custom-title"):
            self.title = short(rec.get("customTitle") or rec.get("aiTitle") or rec.get("title") or "", 40)
            return
        ts = iso_ts(rec["timestamp"]) if rec.get("timestamp") else None
        if ts:
            self.last = ts
        msg = rec.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            return
        for c in msg["content"]:
            if not isinstance(c, dict):
                continue
            ct = c.get("type")
            if ct == "tool_use":
                name = c.get("name", "?")
                item = {"tool": name, "target": target_of(name, c.get("input"), detail), "ts": ts}
                self.pending[c.get("id")] = item
                self.recent = (self.recent + [item])[-RECENT_N:]
                self.tools += 1
            elif ct == "tool_result":
                self.pending.pop(c.get("tool_use_id"), None)
            elif ct == "text" and msg.get("role") == "assistant" and detail != "none":
                txt = say_of(c.get("text", ""))
                if txt:
                    self.say = txt

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
                with open(path) as f:
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
            })
        return sorted(out, key=lambda s: s["id"])

    def collect(self):
        now = time.time()
        self.used = set()
        agents = []
        seen = set()
        files = [(r, f) for r in claude_roots() for f in glob.glob(os.path.join(glob.escape(r), "sessions", "*.json"))]
        for root, f in files:
            try:
                with open(f) as fh:
                    s = json.load(fh)
                os.kill(int(s["pid"]), 0)  # 죽은 프로세스의 파일이 남아 있을 수 있다
            except (OSError, ValueError, KeyError, ProcessLookupError, PermissionError):
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
            if status == "busy":
                kind = "working" if cur else "thinking"
            elif status == "shell":
                kind = "shell"
            else:
                kind = "idle"
            since = (cur or {}).get("ts") or (s.get("statusUpdatedAt", 0) / 1000) or last
            subs = self.subagents(jsonl, tr, now) if jsonl else []
            agents.append({
                "id": sid,
                "pid": s.get("pid"),
                "name": s.get("name") or os.path.basename(cwd),
                "title": tr.title,
                "project": os.path.basename(cwd.rstrip("/")),
                "status": status,
                "kind": kind,
                "tool": cur["tool"] if cur else "",
                "target": cur["target"] if cur else "",
                "since": since,
                "lastActivity": last,
                # 도구도 서브에이전트도 없이 생각만 하는데 기록이 오래 조용하면 '막힘'. 긴 Bash 는 막힘이 아니다.
                "stalled": kind == "thinking" and not subs and now - last > STALL_SEC,
                "startedAt": s.get("startedAt", 0) / 1000,
                "tools": tr.tools,
                "say": self.said(tr),
                "recent": [{"tool": r["tool"], "target": r["target"], "ts": r["ts"]} for r in tr.recent[::-1]],
                "subagents": subs,
            })
        for p in list(self.transcripts):  # 끝난 세션·서브에이전트는 잊는다
            if p not in self.used:
                del self.transcripts[p]
        agents.sort(key=lambda a: a["startedAt"])
        return agents


def post(hub, payload, timeout=5):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Office-Token"] = TOKEN
    req = urllib.request.Request(hub.rstrip("/") + "/api/ingest", data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


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
    args = ap.parse_args()

    col = Collector(args.detail)
    if args.dump:
        json.dump(col.collect(), sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    last_sent, last_at, failing, cfg_at = None, 0.0, False, 0.0
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
            # lastActivity 만 바뀐 경우까지 매초 보내지 않도록 비교에서 뺀다
            sig = json.dumps([{k: v for k, v in a.items() if k != "lastActivity"} for a in agents], sort_keys=True)
            if sig != last_sent or time.time() - last_at > HEARTBEAT_SEC:
                post(args.hub, {"host": args.host, "agents": agents})
                last_sent, last_at = sig, time.time()
                if failing:
                    print(time.strftime("%F %T"), "허브 연결 복구", flush=True)
                    failing = False
                    cfg_at = 0.0
        except (urllib.error.URLError, OSError) as e:
            if not failing:  # 끊길 때 한 번만 남긴다(로그가 쌓이지 않게)
                print(time.strftime("%F %T"), "허브에 보내지 못함:", e, flush=True)
                failing = True
            last_sent = None
        except Exception as e:  # 한 세션 파일이 이상해도 수집기는 죽지 않는다
            print(time.strftime("%F %T"), "수집 오류:", repr(e), flush=True)
        time.sleep(args.interval if not failing else 5)


if __name__ == "__main__":
    main()
