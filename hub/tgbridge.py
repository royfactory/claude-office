"""텔레그램 다리: 휴대폰 텔레그램으로 세션 알림을 받고, 세션 하나를 붙여 텔레그램에서 대화한다.

- 봇 토큰은 .env 의 OFFICE_TELEGRAM_TOKEN 에만 둔다(화면 설정은 누구나 읽으므로 거기에 두지 않는다).
- 허브가 텔레그램에 먼저 묻는 롱 폴링(getUpdates)이라 허브를 인터넷에 열지 않아도 된다(tailnet 안 그대로).
- 연결은 관리 화면에서 받은 6자리 코드를 봇에게 보낸 개인 채팅만. 연결된 채팅 목록은 data/telegram.json(공개되지 않음).
- 연결된 채팅마다: 알림(승인 대기·오래 걸린 일의 완료·막힘), 세션 하나를 '붙여' 보낸 글을 그 세션에 전달하고
  그 세션의 매 턴 마지막 답을 받는다(수집기가 붙인 세션의 답만 /api/telegram/relay 로 따로 보낸다).
- 폴링과 보내기는 각자 데몬 스레드에서 돈다 — 허브를 끌 때 25초짜리 롱 폴링을 기다리지 않고, 화면 갱신도 막지 않는다.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import os
import queue
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.telegram.org"
PAIR_SEC = 600          # 연결 코드가 유효한 시간
POLL_SEC = 25           # getUpdates 롱 폴링
TEXT_MAX = 4000         # 텔레그램 한 메시지 상한(4096)보다 조금 작게
NUDGE_SEC = 300         # 연결 안 된 채팅에 안내를 다시 보내기까지
APPROVAL_DELAY_SEC = 3  # 승인 대기를 보고 알림을 보내기까지 — 그사이 승인 훅 요청이 오면 단추를 붙인다
ACTIVE = {"working", "thinking", "shell", "approval", "waiting"}
NOTIFY_KINDS = ("approval", "done", "stalled")
STATUS_N = 12           # /status 가 보여 줄 세션 수(/status all 은 전부)

# 텔레그램으로 보내는 글. 관리 화면 언어가 en 이면 영어, 아니면 한국어
STR = {
    "ko": {
        "help": "claude-office 봇입니다.\n/status 세션 목록(번호, 바로 받는 세션이 위) · /status all 전부\n/use 번호  그 세션을 이 채팅에 붙이기 — 이후 보내는 글이 그 세션으로 가고, 답이 여기로 옵니다\n/stop 붙인 세션 떼기\n/mute · /unmute 알림 끄기·켜기\n/unlink 이 채팅 연결 끊기\n알림에 답장하면 그 세션으로 보냅니다.",
        "linked": "연결했습니다: {name}\n",
        "need_code": "연결되지 않은 채팅입니다. claude-office 관리 화면의 「텔레그램」에서 연결 코드를 받아 이 채팅에 보내세요.",
        "private_only": "개인 채팅에서만 연결할 수 있습니다.",
        "no_sessions": "지금 보이는 세션이 없습니다.",
        "list_head": "세션 목록 — /use 번호 로 붙입니다(바로 받는 세션이 위)",
        "list_more": "… 외 {n}개 — /status all 로 전부",
        "legend_bypass": "⚠ 권한 건너뛰기 모드 — 보낸 글이 그 컴퓨터 터미널의 승인을 기다립니다",
        "legend_nomsg": "🚫 메시지를 받지 않는 컴퓨터(수집기 CLAUDE_OFFICE_MESSAGES)",
        "bound_bypass": "\n⚠ 이 세션은 권한 건너뛰기 모드라, 여기서 보낸 글이 그 컴퓨터 터미널에서 승인을 기다립니다(5분 안에 안 하면 버려짐). 밖에서 쓰려면 바로 받는 세션을 고르거나, 그 설정 폴더의 Claude Code 설정에 crossSessionInbound: \"accept\" 를 둡니다.",
        "ago_m": "{n}분 전", "ago_h": "{n}시간 전", "ago_d": "{n}일 전", "now": "방금",
        "bad_number": "번호가 맞지 않습니다. /status 로 목록을 다시 보세요.",
        "bad_more": "목록에 없는 세션은 /status all 로 전부 본 뒤 고릅니다.",
        "bound": "이제 이 채팅의 글은 「{title}」({host})로 갑니다. 그 세션의 답이 여기로 옵니다.",
        "bound_no_msg": "\n(주의: 그 컴퓨터가 메시지를 받지 않습니다 — 수집기 .env 의 CLAUDE_OFFICE_MESSAGES=on 과 관리 화면 '메시지 보내기'를 켜세요)",
        "unbound": "세션을 뗐습니다. 알림은 계속 옵니다.",
        "no_target": "붙인 세션이 없습니다. /status 로 목록을 보고 /use 번호 로 붙이거나, 알림에 답장하세요.",
        "send_fail": "보내지 못했습니다: {err}",
        "text_only": "글만 보낼 수 있습니다.",
        "muted": "알림을 껐습니다(붙인 세션의 답은 계속 옵니다).",
        "unmuted": "알림을 켰습니다.",
        "unlinked": "연결을 끊었습니다.",
        "approval": "✋ 승인 대기 · {project}",
        "done": "✅ {project}",
        "stalled": "⏳ 막힘 · {project}",
        "open_web": "🔎 웹에서 보기",
        "allow": "✅ 이번만 허용", "deny": "❌ 거절",
        "decided_allow": "→ 허용했습니다", "decided_deny": "→ 거절했습니다",
        "decide_fail": "처리하지 못했습니다: {err}",
        "approvals_off": "텔레그램 승인이 꺼져 있습니다(관리 화면)",
        "gone": "세션이 보이지 않습니다",
        "kind": {"working": "근무", "thinking": "고민", "shell": "셸", "approval": "승인", "waiting": "대기", "idle": "휴식"},
        "min": "{n}분", "sec": "{n}초", "hour": "{h}시간 {m}분",
    },
    "en": {
        "help": "claude-office bot.\n/status list sessions (numbered, ready-to-receive first) · /status all for all\n/use N  attach that session to this chat — what you send goes to it, and its replies come here\n/stop detach\n/mute · /unmute notifications\n/unlink disconnect this chat\nReply to a notification to message that session.",
        "linked": "Linked: {name}\n",
        "need_code": "This chat isn't linked. Get a link code from 「Telegram」 on the claude-office admin page and send it here.",
        "private_only": "Only private chats can be linked.",
        "no_sessions": "No sessions right now.",
        "list_head": "Sessions — attach with /use N (ready-to-receive first)",
        "list_more": "… {n} more — /status all for all",
        "legend_bypass": "⚠ bypass-permissions mode — messages wait for approval in that computer's terminal",
        "legend_nomsg": "🚫 that computer doesn't accept messages (collector CLAUDE_OFFICE_MESSAGES)",
        "bound_bypass": "\n⚠ This session runs in bypass-permissions mode, so messages from here wait for approval in its terminal (dropped after 5 minutes). To use it remotely, pick a ready-to-receive session or set crossSessionInbound: \"accept\" in that config folder's Claude Code settings.",
        "ago_m": "{n}m ago", "ago_h": "{n}h ago", "ago_d": "{n}d ago", "now": "now",
        "bad_number": "No such number. Send /status to see the list again.",
        "bad_more": "For sessions not listed, send /status all first.",
        "bound": "This chat now talks to “{title}” ({host}). Its replies will come here.",
        "bound_no_msg": "\n(Note: that computer doesn't accept messages — set CLAUDE_OFFICE_MESSAGES=on in its collector .env and enable messaging on the admin page)",
        "unbound": "Detached. Notifications continue.",
        "no_target": "No session attached. Send /status and /use N, or reply to a notification.",
        "send_fail": "Couldn't send: {err}",
        "text_only": "Only text can be sent.",
        "muted": "Notifications off (replies from the attached session still come).",
        "unmuted": "Notifications on.",
        "unlinked": "Disconnected.",
        "approval": "✋ Approval · {project}",
        "done": "✅ {project}",
        "stalled": "⏳ Stuck · {project}",
        "open_web": "🔎 Open in browser",
        "allow": "✅ Allow once", "deny": "❌ Deny",
        "decided_allow": "→ Allowed", "decided_deny": "→ Denied",
        "decide_fail": "Couldn't do that: {err}",
        "approvals_off": "Telegram approvals are off (admin page)",
        "gone": "Session not found",
        "kind": {"working": "working", "thinking": "thinking", "shell": "shell", "approval": "approval", "waiting": "waiting", "idle": "idle"},
        "min": "{n}m", "sec": "{n}s", "hour": "{h}h {m}m",
    },
}

_CODE = re.compile(r"^(?:/start\s+)?(\d{6})$")
_CMD = re.compile(r"^/([a-z]+)(?:@\w+)?(?:\s+(.*))?$", re.S)


def chat_key(chat) -> str:
    """화면·설정에 보일 채팅 표시(채팅 id 원문은 공개 상태에 싣지 않는다)."""
    return hashlib.sha256(f"tg:{chat}".encode()).hexdigest()[:10]


def split_text(text: str, n: int = TEXT_MAX) -> list[str]:
    """긴 답을 텔레그램 한 메시지 크기로 나눈다. 되도록 줄바꿈에서 자른다."""
    out, text = [], text.strip()
    while len(text) > n:
        cut = text.rfind("\n", n // 2, n)
        cut = cut if cut > 0 else n
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    if text:
        out.append(text)
    return out


class Bridge:
    """ops: 허브 쪽 동작을 모은 객체(app.py 의 _TgOps). agents()·config()·send()·decide()·pending()·bump()."""

    def __init__(self, token: str, path: Path, ops, call=None):
        self.token = (token or "").strip()
        self.path = path
        self.ops = ops
        self.call = call or self._http
        self.inline = False      # 시험용: 보내기를 스레드 큐 대신 바로
        self.data = self._load()
        self.pair: dict | None = None
        self.bot = ""
        self.error = ""
        self.ok_at = 0.0
        self.prev: dict[str, dict] = {}      # "host/세션" -> {kind, activeSince, stalled}
        self.seen_hosts: set[str] = set()
        self.lists: dict[int, list] = {}     # 채팅 -> 마지막 /status 목록 [(host, 세션)]
        self.reply_to: dict[tuple, tuple] = {}   # (채팅, 알림 메시지 id) -> (host, 세션)
        self.outbox: dict[str, tuple] = {}   # 허브 메시지 id -> (채팅, 텔레그램 메시지 id)
        self.relayed: collections.deque = collections.deque(maxlen=400)
        self.nudged: dict[int, float] = {}
        self.log: collections.deque = collections.deque(maxlen=30)
        self._q: queue.Queue = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()

    # ---------- 저장 ----------
    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("links"), list):
                d.setdefault("offset", 0)
                return d
        except (OSError, ValueError):
            pass
        return {"offset": 0, "links": []}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as e:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램 연결 목록을 저장하지 못함:", repr(e), flush=True)

    # ---------- 바깥에 보이는 것 ----------
    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def link(self, chat) -> dict | None:
        return next((x for x in self.data["links"] if x["chat"] == chat), None)

    def link_by_id(self, lid: str) -> dict | None:
        return next((x for x in self.data["links"] if x["id"] == lid), None)

    def snapshot(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        return {"enabled": True, "bot": self.bot, "error": self.error, "ok": bool(self.ok_at) and not self.error,
                "pairing": bool(self.pair and self.pair["until"] > time.time()),
                "links": [{"id": x["id"], "name": x["name"], "muted": bool(x.get("muted")), "bind": x.get("bind"),
                           "filter": x.get("filter") or {}} for x in self.data["links"]],
                "log": list(self.log)[-20:]}

    def relay_for(self, host: str) -> dict:
        """수집기에게: 이 컴퓨터에서 답을 텔레그램으로 보낼 세션 → 붙인 시각."""
        if not self.enabled or not self.ops.config().get("telegram", {}).get("replies", True):
            return {}
        out = {}
        for x in self.data["links"]:
            b = x.get("bind")
            if b and b.get("host") == host:
                out[b["session"]] = min(out.get(b["session"], b["at"]), b["at"])
        return out

    def new_code(self) -> dict:
        self.pair = {"code": f"{secrets.randbelow(10 ** 6):06d}", "until": time.time() + PAIR_SEC}
        return {"code": self.pair["code"], "until": self.pair["until"], "bot": self.bot}

    def _s(self) -> dict:
        return STR["en"] if self.ops.config().get("language") == "en" else STR["ko"]

    def _note(self, dir_: str, who: str, kind: str, text: str = "", session: str = "") -> None:
        self.log.append({"ts": time.time(), "dir": dir_, "who": who[:24], "kind": kind, "text": text[:80], "session": session})

    # ---------- 텔레그램 API ----------
    def _http(self, method: str, params: dict):
        timeout = POLL_SEC + 10 if method == "getUpdates" else 15
        req = urllib.request.Request(f"{API}/bot{self.token}/{method}", data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:   # 텔레그램은 오류도 JSON 으로 준다(429 의 retry_after 등)
            try:
                body = json.load(e)
            except ValueError:
                raise e from None
        if not body.get("ok"):
            raise TgError(body.get("error_code") or 0, body.get("description") or "", (body.get("parameters") or {}).get("retry_after"))
        return body.get("result")

    def send(self, chat, text: str, after=None, **extra) -> None:
        """보내기를 큐에 넣는다. after(result) 는 보낸 뒤 보내기 스레드에서 불린다(메시지 id 를 기억하려고)."""
        self.enqueue("sendMessage", {"chat_id": chat, "text": text[:4096], "disable_web_page_preview": True, **extra}, after)

    def enqueue(self, method: str, params: dict, after=None) -> None:
        if self.inline:
            self._do(method, params, after)
        else:
            self._q.put((method, params, after))

    def _do(self, method, params, after) -> None:
        for _ in range(3):
            try:
                res = self.call(method, params)
                if after:
                    after(res)
                return
            except TgError as e:
                if e.code == 429 and e.retry_after:
                    time.sleep(min(float(e.retry_after), 30))
                    continue
                rm = params.get("reply_markup") or {}
                if e.code == 400 and any("url" in b for row in rm.get("inline_keyboard", []) for b in row):
                    # 텔레그램이 웹 주소 단추를 받지 않으면(점 없는 호스트 이름 등) 단추만 빼고 다시
                    rows = [r for r in ([b for b in row if "url" not in b] for row in rm["inline_keyboard"]) if r]
                    params = {**params, "reply_markup": {"inline_keyboard": rows}} if rows else {k: v for k, v in params.items() if k != "reply_markup"}
                    print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램이 웹 주소 단추를 받지 않음(관리 화면 웹 주소 확인):", e, flush=True)
                    continue
                if method not in ("setMessageReaction",):   # 반응 표시는 실패해도 조용히
                    print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램", method, "실패:", e, flush=True)
                return
            except Exception as e:   # 네트워크 끊김 등 — 잠깐 쉬고 다시
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램", method, "실패:", repr(e), flush=True)
                time.sleep(2)

    def _sender(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1)
            except queue.Empty:
                continue
            self._do(*item)
            time.sleep(0.05)

    def _poller(self) -> None:
        back = 5.0
        while not self._stop.is_set():
            try:
                if not self.bot:
                    me = self.call("getMe", {}) or {}
                    self.bot = me.get("username") or ""
                ups = self.call("getUpdates", {"offset": self.data.get("offset", 0), "timeout": POLL_SEC,
                                               "allowed_updates": ["message", "callback_query"]})
                self.error, self.ok_at, back = "", time.time(), 5.0
                for u in ups or []:
                    self.data["offset"] = max(self.data.get("offset", 0), int(u.get("update_id", 0)) + 1)
                    if self._loop:
                        fut = asyncio.run_coroutine_threadsafe(self.handle(u), self._loop)
                        try:
                            fut.result(timeout=30)
                        except Exception as e:
                            print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램 처리 오류:", repr(e), flush=True)
                if ups:
                    self.save()
            except TgError as e:
                self.error = f"{e.code} {e.desc}"[:120]
                if e.code == 409:   # 웹훅이 걸려 있으면 롱 폴링이 막힌다 — 한 번 지운다
                    try:
                        self.call("deleteWebhook", {})
                    except Exception:
                        pass
                wait = 600 if e.code == 401 else back   # 토큰이 틀렸으면 10분마다만
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "텔레그램 연결 실패:", self.error, flush=True)
                self._stop.wait(wait)
                back = min(back * 2, 60)
            except Exception as e:
                self.error = repr(e)[:120]
                self._stop.wait(back)
                back = min(back * 2, 60)

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self.enabled:
            return
        self._loop = loop
        threading.Thread(target=self._poller, name="telegram-poll", daemon=True).start()
        threading.Thread(target=self._sender, name="telegram-send", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ---------- 받은 것 처리 ----------
    async def handle(self, u: dict) -> None:
        if u.get("callback_query"):
            await self._callback(u["callback_query"])
            return
        m = u.get("message")
        if not isinstance(m, dict):
            return
        chat = (m.get("chat") or {}).get("id")
        if chat is None:
            return
        s = self._s()
        text = (m.get("text") or "").strip()
        link = self.link(chat)
        if link is None:
            await self._unlinked(m, chat, text, s)
            return
        if not text:
            self.send(chat, s["text_only"])
            return
        cm = _CMD.match(text)
        if cm:
            await self._command(link, chat, cm.group(1), (cm.group(2) or "").strip(), s)
            return
        target = None
        rt = m.get("reply_to_message")
        if isinstance(rt, dict):
            target = self.reply_to.get((chat, rt.get("message_id")))
        if not target and link.get("bind"):
            target = (link["bind"]["host"], link["bind"]["session"])
        if not target:
            self.send(chat, s["no_target"])
            return
        mid, err = await self.ops.send(target[0], target[1], text)
        self._note("in", link["name"], "msg", text, target[1])
        if err:
            self.send(chat, s["send_fail"].format(err=err), reply_to_message_id=m.get("message_id"))
        else:
            self.outbox[mid] = (chat, m.get("message_id"))
            if len(self.outbox) > 200:
                for k in list(self.outbox)[:100]:
                    del self.outbox[k]
            self.enqueue("setMessageReaction", {"chat_id": chat, "message_id": m.get("message_id"),
                                                "reaction": [{"type": "emoji", "emoji": "👀"}]})
        await self.ops.bump()

    async def _unlinked(self, m: dict, chat, text: str, s: dict) -> None:
        cm = _CODE.match(text)
        if cm and self.pair and self.pair["until"] > time.time() and secrets.compare_digest(cm.group(1), self.pair["code"]):
            if (m.get("chat") or {}).get("type") != "private":
                self.send(chat, s["private_only"])
                return
            fr = m.get("from") or {}
            name = (fr.get("first_name") or fr.get("username") or "Telegram")[:24]
            self.data["links"].append({"id": chat_key(chat), "chat": chat, "name": name, "since": time.time(),
                                       "muted": False, "filter": {}, "bind": None})
            self.pair = None
            self.save()
            self._note("in", name, "link")
            self.send(chat, s["linked"].format(name=name) + s["help"])
            await self.ops.bump()
            return
        if time.time() - self.nudged.get(chat, 0) > NUDGE_SEC:   # 모르는 채팅에는 안내를 가끔만
            self.nudged[chat] = time.time()
            self.send(chat, s["need_code"])

    @staticmethod
    def ready(a: dict) -> bool:
        """텔레그램에서 보낸 글을 바로 받는 세션: 메시지를 받는 컴퓨터이고, 권한 건너뛰기 모드가 아니다
        (그 모드는 Claude Code 규칙상 다른 곳에서 온 메시지를 터미널 승인 뒤에만 넣는다)."""
        return bool(a.get("canMessage")) and a.get("mode") != "bypassPermissions"

    def _sessions(self, limit: int = 40) -> list[dict]:
        """붙일 후보: 바로 받는 세션 → 일하는 세션 → 최근에 움직인 세션 순."""
        ag = self.ops.agents()
        return sorted(ag, key=lambda a: (not self.ready(a), a.get("kind") == "idle", -(a.get("lastActivity") or 0)))[:limit]

    def _ago(self, ts, s: dict) -> str:
        sec = time.time() - (ts or time.time())
        if sec < 60:
            return s["now"]
        if sec < 3600:
            return s["ago_m"].format(n=int(sec // 60))
        if sec < 86400:
            return s["ago_h"].format(n=int(sec // 3600))
        return s["ago_d"].format(n=int(sec // 86400))

    async def _command(self, link: dict, chat, cmd: str, arg: str, s: dict) -> None:
        if cmd in ("start", "help"):
            self.send(chat, s["help"])
        elif cmd in ("status", "list", "sessions"):
            every = self._sessions()
            ag = every if arg == "all" else every[:STATUS_N]
            self.lists[chat] = [(a["host"], a["id"]) for a in ag]   # /use 번호는 방금 보여 준 목록에서만(안 보인 번호에 붙지 않게)
            if not ag:
                self.send(chat, s["no_sessions"])
                return
            b = link.get("bind") or {}
            hosts = {a["host"] for a in every}
            lines = [s["list_head"]]
            for i, a in enumerate(ag, 1):
                mark = "📎 " if b.get("session") == a["id"] and b.get("host") == a["host"] else ""
                warn = "" if self.ready(a) else (" ⚠" if a.get("canMessage") else " 🚫")
                kind = s["kind"].get(a.get("kind"), a.get("kind", ""))
                when = kind if a.get("kind") != "idle" else f"{kind} · {self._ago(a.get('lastActivity'), s)}"
                where = f" @{a['host']}" if len(hosts) > 1 else ""
                lines.append(f"{i}. {mark}{a.get('project', '')} · {(a.get('title') or a.get('name') or '')[:36]} · {when}{where}{warn}")
            if len(ag) < len(every):
                lines.append(s["list_more"].format(n=len(every) - len(ag)))
            if any(not self.ready(a) and a.get("canMessage") for a in ag):
                lines.append(s["legend_bypass"])
            if any(not a.get("canMessage") for a in ag):
                lines.append(s["legend_nomsg"])
            self.send(chat, "\n".join(lines))
        elif cmd == "use":
            lst = self.lists.get(chat) or [(a["host"], a["id"]) for a in self._sessions()[:STATUS_N]]
            try:
                n = int(arg)
                if n < 1:
                    raise IndexError
                host, sid = lst[n - 1]
            except (ValueError, IndexError):
                self.send(chat, s["bad_number"] + (" " + s["bad_more"] if len(lst) < len(self._sessions()) else ""))
                return
            await self.bind(link, host, sid)
        elif cmd == "stop":
            link["bind"] = None
            self.save()
            self.send(chat, s["unbound"])
        elif cmd in ("mute", "unmute"):
            link["muted"] = cmd == "mute"
            self.save()
            self.send(chat, s["muted" if link["muted"] else "unmuted"])
        elif cmd == "unlink":
            self.data["links"] = [x for x in self.data["links"] if x is not link]
            self.save()
            self.send(chat, s["unlinked"])
        else:
            self.send(chat, s["help"])
        await self.ops.bump()

    async def bind(self, link: dict, host: str, sid: str) -> None:
        """그 채팅에 세션을 붙인다(텔레그램 /use 와 화면의 '텔레그램에 붙이기')."""
        a = next((x for x in self.ops.agents() if x["host"] == host and x["id"] == sid), None)
        link["bind"] = {"host": host, "session": sid, "at": time.time()}
        self.save()
        s = self._s()
        title = (a or {}).get("title") or (a or {}).get("name") or sid[:8]
        self._note("out", link["name"], "bind", title, sid)
        extra = s["bound_no_msg"] if not (a or {}).get("canMessage") else s["bound_bypass"] if (a or {}).get("mode") == "bypassPermissions" else ""
        self.send(link["chat"], s["bound"].format(title=title, host=host) + extra)
        await self.ops.bump()

    async def _callback(self, q: dict) -> None:
        chat = ((q.get("message") or {}).get("chat") or {}).get("id")
        link = self.link(chat)
        data = q.get("data") or ""
        s = self._s()
        m = re.match(r"^ap:([0-9a-f]{1,32}):(allow|deny)$", data)
        answer = ""
        if link and m:
            if not self.ops.config().get("telegram", {}).get("approvals"):
                answer = s["approvals_off"]
            else:
                err = await self.ops.decide(m.group(1), m.group(2))
                if err:
                    answer = s["decide_fail"].format(err=err)
                else:
                    answer = s["decided_" + m.group(2)]
                    msg = q.get("message") or {}
                    self.enqueue("editMessageText", {"chat_id": chat, "message_id": msg.get("message_id"),
                                                     "text": (msg.get("text") or "") + "\n\n" + answer})
                    self._note("in", link["name"], m.group(2))
        self.enqueue("answerCallbackQuery", {"callback_query_id": q.get("id"), "text": answer[:190]})

    def on_result(self, mid: str, ok: bool, err: str) -> None:
        """허브 메시지가 세션에 전달됐는지(수집기 보고) — 텔레그램에서 보낸 것이면 반응·오류로 알린다."""
        t = self.outbox.pop(mid, None)
        if not t:
            return
        chat, tmid = t
        if ok:
            self.enqueue("setMessageReaction", {"chat_id": chat, "message_id": tmid, "reaction": [{"type": "emoji", "emoji": "👌"}]})
        else:
            self.send(chat, self._s()["send_fail"].format(err=err or "?"), reply_to_message_id=tmid)

    # ---------- 알림 ----------
    def observe(self, host: str, agents: list) -> None:
        """수집기가 보낸 세션 목록을 앞 것과 견줘 알릴 일(승인 대기·완료·막힘)을 찾는다. 처음 보는 컴퓨터는 기준만 잡는다."""
        if not self.enabled or not self.data["links"]:
            self.seen_hosts.discard(host)
            return
        now = time.time()
        first = host not in self.seen_hosts
        self.seen_hosts.add(host)
        cfg = self.ops.config().get("telegram", {})
        kinds = set(cfg.get("notify", ["approval", "done"]))
        done_sec = cfg.get("doneSec", 60)
        alive = set()
        for a in agents:
            if not isinstance(a, dict) or not a.get("id"):
                continue
            k = f"{host}/{a['id']}"
            alive.add(k)
            kind, stalled = a.get("kind", "idle"), bool(a.get("stalled"))
            p = self.prev.get(k)
            if p is None:
                self.prev[k] = {"kind": kind, "activeSince": now if kind in ACTIVE else None, "stalled": stalled}
                continue
            if not first:
                if kind == "approval" and p["kind"] != "approval" and "approval" in kinds:
                    self._later(APPROVAL_DELAY_SEC, self._notify_approval, host, a["id"])
                if kind == "idle" and p["kind"] in ACTIVE and p["activeSince"] and "done" in kinds \
                        and now - p["activeSince"] >= done_sec:
                    self.notify("done", host, a, now - p["activeSince"])
                if stalled and not p["stalled"] and "stalled" in kinds:
                    self.notify("stalled", host, a)
            if kind in ACTIVE and p["kind"] not in ACTIVE:
                p["activeSince"] = now
            elif kind not in ACTIVE:
                p["activeSince"] = None
            p["kind"], p["stalled"] = kind, stalled
        for k in [k for k in self.prev if k.startswith(host + "/") and k not in alive]:
            del self.prev[k]

    def _later(self, sec, fn, *args) -> None:
        if self._loop and self._loop.is_running() and not self.inline:
            self._loop.call_later(sec, fn, *args)
        else:
            fn(*args)

    def _notify_approval(self, host: str, sid: str) -> None:
        a = next((x for x in self.ops.agents() if x["host"] == host and x["id"] == sid), None)
        if a and a.get("kind") == "approval":
            self.notify("approval", host, a)

    def _dur(self, sec: float, s: dict) -> str:
        sec = int(sec)
        if sec < 60:
            return s["sec"].format(n=sec)
        if sec < 3600:
            return s["min"].format(n=sec // 60)
        return s["hour"].format(h=sec // 3600, m=sec % 3600 // 60)

    def _wants(self, link: dict, host: str, a: dict) -> bool:
        f = link.get("filter") or {}
        if f.get("hosts") and host not in f["hosts"]:
            return False
        acc = (a.get("account") or {}).get("id")
        return not (f.get("accounts") and acc not in f["accounts"])

    def notify(self, kind: str, host: str, a: dict, dur: float = 0) -> None:
        cfg = self.ops.config()
        tg = cfg.get("telegram", {})
        s = self._s()
        # 한 줄로: 무슨 일 · 층 · 세션 제목(basic) · 도구(승인)·걸린 시간(완료). 자세한 것은 '웹에서 보기'로
        project = a.get("project") or "?"
        parts = [s[kind].format(project=project)]
        if tg.get("detail", "basic") == "basic":
            title = a.get("title") or a.get("name") or ""
            if title:
                parts.append(title[:40])
            if kind == "approval" and a.get("tool"):
                parts.append(a["tool"][:32])
        if kind == "done":
            parts.append(self._dur(dur, s))
        lines = [" · ".join(parts)]
        rows = []
        if kind == "approval" and tg.get("approvals") and cfg.get("approvals"):
            x = self.ops.pending(host, a["id"])
            if x:   # 텔레그램에서 결정하려면 명령을 봐야 한다 — 승인 단추를 켠 경우만 미리보기를 붙인다
                if x.get("preview"):
                    lines.append(x["preview"][:600])
                rows.append([{"text": s["allow"], "callback_data": f"ap:{x['id']}:allow"},
                             {"text": s["deny"], "callback_data": f"ap:{x['id']}:deny"}])
        url = self.web_url(project, a["id"])
        if url:
            rows.append([{"text": s["open_web"], "url": url}])
        markup = {"inline_keyboard": rows} if rows else None
        text = "\n".join(lines)
        sent = False
        for link in self.data["links"]:
            b = link.get("bind") or {}
            mine = b.get("host") == host and b.get("session") == a["id"]
            if (link.get("muted") and not mine) or not self._wants(link, host, a):
                continue
            if kind == "done" and mine and tg.get("replies", True):
                continue   # 붙인 세션의 완료는 답이 곧 온다
            chat = link["chat"]
            self.send(chat, text, after=lambda r, c=chat, h=host, sid=a["id"]: self._remember(c, r, h, sid),
                      **({"reply_markup": markup} if markup else {}))
            sent = True
        if sent:
            self._note("out", "bot", kind, a.get("title") or project, a["id"])

    def web_url(self, project: str, sid: str) -> str:
        """대시보드에서 그 세션을 고른 채로 여는 주소(관리 화면 '웹 주소'가 있을 때만)."""
        base = (self.ops.config().get("telegram", {}).get("webUrl") or "").strip().rstrip("/")
        if not re.match(r"^https?://[^\s/]+", base):
            return ""
        q = urllib.parse.quote
        return f"{base}/#p={q(project, safe='')}&s={q(sid, safe='')}"

    def _remember(self, chat, res, host, sid) -> None:
        if isinstance(res, dict) and res.get("message_id"):
            self.reply_to[(chat, res["message_id"])] = (host, sid)
            if len(self.reply_to) > 300:
                for k in list(self.reply_to)[:150]:
                    del self.reply_to[k]

    # ---------- 붙인 세션의 답 ----------
    def relay(self, host: str, session: str, items: list) -> int:
        """수집기가 보낸 그 세션의 답을 붙인 채팅들로. 붙이기 전의 답·이미 보낸 답은 건너뛴다. 보낸 수."""
        if not self.enabled or not self.ops.config().get("telegram", {}).get("replies", True):
            return 0
        links = [x for x in self.data["links"] if (x.get("bind") or {}).get("host") == host and x["bind"].get("session") == session]
        if not links:
            return 0
        a = next((x for x in self.ops.agents() if x["host"] == host and x["id"] == session), None) or {}
        head = f"💬 {(a.get('title') or a.get('name') or a.get('project') or session[:8])[:60]}\n"
        n = 0
        for it in items:
            rid, text, ts = str(it.get("id", "")), str(it.get("text", "")), float(it.get("ts") or 0)
            if not rid or not text.strip() or rid in self.relayed:
                continue
            self.relayed.append(rid)
            for link in links:
                if ts and ts < link["bind"]["at"] - 5:
                    continue
                parts = split_text(text, TEXT_MAX - len(head))
                for i, part in enumerate(parts):
                    self.send(link["chat"], (head if i == 0 else "") + part,
                              after=lambda r, c=link["chat"]: self._remember(c, r, host, session))
                n += 1
            self._note("out", "bot", "reply", text, session)
        return n


class TgError(Exception):
    def __init__(self, code: int, desc: str, retry_after=None):
        super().__init__(f"{code} {desc}")
        self.code, self.desc, self.retry_after = code, desc, retry_after
