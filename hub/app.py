"""claude-office 허브: 수집기가 보낸 Claude 세션 상태를 모아 사무실 화면과 관리 화면에 실시간으로 뿌린다.

- 상태(세션 목록)는 메모리에만 둔다. 수집기가 1~10초마다 통째로 다시 보낸다.
- 설정(캐릭터·배정 규칙·방·도구 매핑)과 캐릭터 이미지는 OFFICE_DATA(도커는 /data 볼륨, 직접 실행은 저장소의 data/)에 둔다.
- OFFICE_TOKEN 을 정하면 쓰기(수집기 전송·설정 저장·이미지 올리기/지우기)에 그 토큰이 필요하다.
  보기(사무실 화면·상태·설정 읽기)는 열려 있다. 비우면 인증 없이 동작한다 — 믿을 수 있는 네트워크에서만 쓴다.
- 설정은 환경변수로 받고, 직접 실행하면 저장소 루트의 .env 도 읽는다(이미 있는 환경변수는 덮지 않는다).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal


def _early_log() -> None:
    """--log 가 있으면 다른 모듈을 읽기 전에 출력을 그 파일로 돌린다.

    창 없는 pythonw(Windows 작업 스케줄러)로 뜨면 시작 중 오류가 어디에도 남지 않아서,
    import·설정 읽기에서 죽어도 원인이 로그에 남도록 맨 먼저 한다."""
    if "--log" not in sys.argv[:-1]:
        if sys.stdout is None:
            sys.stdout = sys.stderr = open(os.devnull, "w")
        return
    path = sys.argv[sys.argv.index("--log") + 1]
    try:
        if os.path.getsize(path) > 1024 * 1024:   # 1MB 넘으면 비우고 시작
            open(path, "w").close()
    except OSError:
        pass
    sys.stdout = sys.stderr = open(path, "a", encoding="utf-8", buffering=1)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "허브 시작", sys.executable, flush=True)


if __name__ == "__main__":
    _early_log()

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent   # 저장소 루트(도커 안에서는 / 이라 data 가 /data 가 된다)


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    # Windows 기본 인코딩(cp949)으로 읽으면 한글 주석에서 죽는다 — 늘 UTF-8(메모장 BOM 포함)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")
DATA = Path(os.environ.get("OFFICE_DATA") or ROOT / "data")
TOKEN = os.environ.get("OFFICE_TOKEN", "").strip()
ASSETS = DATA / "assets"
CONFIG_PATH = DATA / "config.json"
STATIC = Path(__file__).parent / "static"
HOST_STALE_SEC = 30  # 이 시간 동안 소식이 없는 수집기의 세션은 화면에서 뺀다
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_MESSAGE = 4000
OUTBOX_TTL_SEC = 60
WAIT_MAX_SEC = 25   # /api/outbox/wait 롱폴링 최대 대기
GRACEFUL_SEC = 3    # 종료 때 열린 연결(SSE·롱폴링)을 기다리는 최대 시간

ROOM_IDS = ("library", "dev", "server", "search", "meeting", "mydesk", "lounge")

DEFAULT_CONFIG: dict = {
    "characters": [
        {"id": c, "name": n, "emoji": e, "color": col, "inPool": True, "states": {}}
        for c, n, e, col in [
            ("fox", "여우", "🦊", "#d95926"),
            ("cat", "고양이", "🐱", "#fbbf24"),
            ("bear", "곰", "🐻", "#a16207"),
            ("panda", "판다", "🐼", "#94a3b8"),
            ("penguin", "펭귄", "🐧", "#38bdf8"),
            ("owl", "부엉이", "🦉", "#a78bfa"),
            ("frog", "개구리", "🐸", "#34d399"),
            ("tiger", "호랑이", "🐯", "#f59e0b"),
            ("rabbit", "토끼", "🐰", "#f9a8d4"),
            ("robot", "로봇", "🤖", "#2a78d6"),
            ("koala", "코알라", "🐨", "#64748b"),
            ("monkey", "원숭이", "🐵", "#b45309"),
        ]
    ]
    + [{"id": "chick", "name": "병아리", "emoji": "🐥", "color": "#fde047", "inPool": False, "states": {}}],
    "subagentCharacter": "chick",
    "assignments": [],
    "rooms": [
        {"id": "library", "name": "자료실", "emoji": "📚", "desc": "파일 읽기 · 검색"},
        {"id": "dev", "name": "개발실", "emoji": "💻", "desc": "코드 작성 · 수정"},
        {"id": "server", "name": "서버실", "emoji": "🗄️", "desc": "명령 실행 · git"},
        {"id": "search", "name": "정보검색실", "emoji": "🌐", "desc": "웹 · 외부 도구"},
        {"id": "meeting", "name": "회의실", "emoji": "🗣️", "desc": "계획 · 할 일 · 스킬"},
        {"id": "mydesk", "name": "내 자리", "emoji": "🙋", "desc": "질문 · 에이전트 호출"},
        {"id": "lounge", "name": "라운지", "emoji": "☕", "desc": "쉬는 중"},
    ],
    "toolRooms": [
        {"pattern": p, "room": r}
        for r, ps in [
            ("library", ["Read", "Grep", "Glob", "LS", "NotebookRead", "ToolSearch"]),
            ("dev", ["Edit", "Write", "MultiEdit", "NotebookEdit"]),
            ("server", ["Bash", "BashOutput", "KillShell", "Monitor", "TaskStop"]),
            ("search", ["WebFetch", "WebSearch", "Artifact*", "mcp__*"]),
            ("meeting", ["TodoWrite", "Task*", "Skill", "EnterPlanMode", "ExitPlanMode", "Workflow", "Cron*"]),
            ("mydesk", ["AskUserQuestion", "Agent", "SendMessage", "ListAgents"]),
        ]
        for p in ps
    ],
    "defaultRoom": "dev",
    "speech": True,      # 말풍선에 Claude 마지막 답변 앞 80자. 끄면 수집기가 30초 안에 보내지 않는다
    "messaging": False,  # 대시보드에서 세션으로 메시지 보내기. OFFICE_TOKEN 이 있어야 켜진다
    "approvals": False,  # 대시보드에서 권한 요청 허용·거절. OFFICE_TOKEN + 그 컴퓨터의 승인 훅이 있어야 동작
    "meName": "나",
    "meCharacter": "",   # 내 자리에 앉은 '나'의 캐릭터. 비면 🧑‍💻
}


# ---------- 설정 ----------

class StateLook(BaseModel):
    emoji: str = Field("", max_length=16)
    image: str = Field("", max_length=64)


class Character(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    name: str = Field(min_length=1, max_length=24)
    emoji: str = Field("", max_length=16)
    image: str = Field("", max_length=64)
    color: str = Field("#94a3b8", pattern=r"^#[0-9a-fA-F]{6}$")
    inPool: bool = True
    pixel: bool = False  # 픽셀아트 이미지면 확대할 때 뭉개지지 않게 그린다
    # 상태별 모습(working·thinking·stalled·idle). 비면 기본 모습을 쓴다.
    states: dict[Literal["working", "thinking", "stalled", "idle"], StateLook] = {}


class Assignment(BaseModel):
    match: Literal["project", "session", "agentType", "host"]
    value: str = Field(min_length=1, max_length=80)
    character: str


RoomId = Literal["library", "dev", "server", "search", "meeting", "mydesk", "lounge"]
WorkRoomId = Literal["library", "dev", "server", "search", "meeting", "mydesk"]


class Room(BaseModel):
    id: RoomId
    name: str = Field(min_length=1, max_length=12)
    emoji: str = Field("", max_length=16)
    desc: str = Field("", max_length=40)


class ToolRoom(BaseModel):
    pattern: str = Field(min_length=1, max_length=64)
    room: WorkRoomId


class Config(BaseModel):
    characters: list[Character] = Field(min_length=1, max_length=200)
    subagentCharacter: str = ""
    assignments: list[Assignment] = Field(default=[], max_length=500)
    rooms: list[Room]
    toolRooms: list[ToolRoom] = Field(default=[], max_length=300)
    defaultRoom: WorkRoomId = "dev"
    speech: bool = True
    messaging: bool = False
    approvals: bool = False
    meName: str = Field("나", min_length=1, max_length=12)
    meCharacter: str = ""

    def check(self) -> None:
        ids = [c.id for c in self.characters]
        if len(ids) != len(set(ids)):
            raise ValueError("캐릭터 id가 겹친다")
        known = set(ids)
        for label, cid in (("서브에이전트", self.subagentCharacter), ("내 자리", self.meCharacter)):
            if cid and cid not in known:
                raise ValueError(f"{label} 캐릭터 {cid} 가 없다")
        for a in self.assignments:
            if a.character not in known:
                raise ValueError(f"배정 규칙의 캐릭터 {a.character} 가 없다")
        if sorted(r.id for r in self.rooms) != sorted(ROOM_IDS):
            raise ValueError("방 7개(" + "·".join(ROOM_IDS) + ")가 모두 있어야 한다")
        for c in self.characters:
            for img in [c.image, *(s.image for s in c.states.values())]:
                if img and not (ASSETS / img).is_file():
                    raise ValueError(f"이미지 {img} 가 없다")


def default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_PATH.is_file():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            saved = {}
        # 방 구성이 바뀐 옛 설정이면 방·도구 매핑만 기본값으로 바꾸고 캐릭터·규칙은 살린다
        if sorted(r.get("id") for r in saved.get("rooms", [])) != sorted(ROOM_IDS):
            for k in ("rooms", "toolRooms", "defaultRoom"):
                saved.pop(k, None)
        cfg.update(saved)
    return cfg


def save_config(cfg: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


# ---------- 실시간 상태 ----------

class Hub:
    def __init__(self) -> None:
        self.hosts: dict[str, dict] = {}  # host -> {"receivedAt", "agents"}
        self.config = load_config()
        self.version = 0
        self.changed = asyncio.Condition()
        self.outbox: list[dict] = []   # 대시보드 → 세션 메시지(최근 것만, 메모리에만)
        self.queued = asyncio.Condition()   # 새 메시지가 큐에 들어오면 롱폴링 중인 수집기를 깨운다
        self.approvals: dict[str, dict] = {}   # 승인 요청 id -> 요청(메모리에만)
        self.decided = asyncio.Condition()       # 결정이 나면 기다리는 승인 훅을 깨운다
        self.closing = False   # 종료 신호를 받았다 — 열린 SSE·롱폴링을 바로 끝낸다

    @staticmethod
    def online(h: dict, now: float) -> bool:
        # 수집기가 '떠남'을 알렸으면(정상 종료) 바로 끊김, 아니면 마지막 소식 뒤 HOST_STALE_SEC 기준
        return not h.get("offline") and now - h["receivedAt"] < HOST_STALE_SEC

    def messaging_ready(self) -> bool:
        return bool(TOKEN) and bool(self.config.get("messaging"))

    def snapshot(self) -> dict:
        now = time.time()
        hosts, agents = [], []
        for name, h in sorted(self.hosts.items()):
            age = now - h["receivedAt"]
            on = self.online(h, now)
            hosts.append({"host": name, "age": round(age, 1), "online": on,
                          "count": len(h["agents"]), **h.get("meta", {})})
            if on:
                agents.extend({**a, "host": name} for a in h["agents"])
        msgs = [{k: m[k] for k in ("id", "host", "session", "status", "error", "createdAt", "preview")}
                for m in self.outbox[-20:]]
        # 기다리는 승인 요청. 명령 미리보기는 토큰이 있어야 따로 받는다(읽기는 누구나 하므로)
        appr = [{k: x[k] for k in ("id", "host", "session", "tool", "createdAt", "status")}
                for x in self.approvals.values() if x["status"] == "pending"]
        return {"version": self.version, "now": now, "hosts": hosts, "agents": agents,
                "config": self.config, "messaging": {"ready": self.messaging_ready(), "auth": bool(TOKEN)},
                "messages": msgs, "approvals": appr,
                "approvalsReady": bool(TOKEN) and bool(self.config.get("approvals"))}

    async def close(self) -> None:
        """종료가 시작되면 기다리는 SSE·롱폴링을 모두 깨워 바로 끝나게 한다."""
        self.closing = True
        for cond in (self.changed, self.queued, self.decided):
            async with cond:
                cond.notify_all()

    async def bump(self) -> None:
        async with self.changed:
            self.version += 1
            self.changed.notify_all()


hub = Hub()


def require_write(request: Request) -> None:
    """OFFICE_TOKEN 이 있으면 쓰기 요청에 같은 토큰을 요구한다(Authorization: Bearer 또는 X-Office-Token)."""
    if not TOKEN:
        return
    got = request.headers.get("x-office-token") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got.encode(), TOKEN.encode()):
        raise HTTPException(401, "토큰이 필요하다(OFFICE_TOKEN)")



async def _expire_loop() -> None:
    # 수집기가 끊기면 그 세션들이 화면에서 빠지도록 주기적으로 알린다.
    online: dict[str, bool] = {}
    while True:
        await asyncio.sleep(5)
        now = time.time()
        cur = {h: hub.online(v, now) for h, v in hub.hosts.items()}
        expired = False
        for m in hub.outbox:   # 수집기가 1분 안에 가져가지 않으면(꺼짐·메시지 받기 꺼짐) 만료
            if m["status"] in ("queued", "sending") and now - m["createdAt"] > OUTBOX_TTL_SEC:
                m.update(status="expired", error="그 컴퓨터의 수집기가 가져가지 않았다(꺼져 있거나 메시지 받기가 꺼짐)")
                expired = True
        if _settle_approvals(now):   # 거둔 요청이 있으면 기다리는 승인 훅을 깨워 끝나게 한다
            expired = True
            async with hub.decided:
                hub.decided.notify_all()
        if cur != online or expired:
            online = cur
            await hub.bump()


def _hook_exit_signals(loop: asyncio.AbstractEventLoop) -> list:
    """uvicorn 이 SIGTERM·SIGINT 로 종료를 시작할 때 hub.close() 도 부르게 처리기를 이어 단다.

    uvicorn 은 열린 연결이 다 끝난 뒤에야 lifespan 종료를 부르므로, 그때 깨우면 늦다(대시보드 SSE 가 열려 있으면
    끝나지 않는다). 그래서 신호 처리기 단계에서 깨운다. 앞선 처리기(uvicorn 의 handle_exit)는 그대로 부른다.
    main 스레드가 아니거나(테스트) 앞선 처리기가 없으면 건드리지 않는다. 걸어 둔 신호 목록을 돌려준다."""
    hooked = []
    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):   # SIGBREAK 는 Windows
        sig = getattr(signal, name, None)
        prev = signal.getsignal(sig) if sig is not None else None
        if not callable(prev):
            continue

        def handler(signum, frame, prev=prev):
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(hub.close()))
            prev(signum, frame)
        try:
            signal.signal(sig, handler)
        except ValueError:   # main 스레드가 아니면 신호 처리기를 바꿀 수 없다
            continue
        hooked.append(name)
    return hooked


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_expire_loop())
    _hook_exit_signals(asyncio.get_running_loop())   # uvicorn 은 serve 를 마치면 자기 처리기 이전 것으로 되돌린다
    yield
    await hub.close()
    task.cancel()


app = FastAPI(title="claude-office", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
async def admin() -> FileResponse:
    return FileResponse(STATIC / "admin.html")


@app.get("/admin/")
async def admin_slash() -> RedirectResponse:
    return RedirectResponse("/admin")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "hosts": len(hub.hosts), "version": hub.version, "auth": bool(TOKEN)}


def _host_of(body: dict) -> str:
    host = str(body.get("host", ""))[:40]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", host):
        raise HTTPException(400, "host 형식이 맞지 않다")
    return host


def _meta_of(body: dict) -> dict:
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    return {"checklistRule": bool(meta.get("checklistRule"))} if "checklistRule" in meta else {}


def _seq_of(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


@app.post("/api/ingest", dependencies=[Depends(require_write)])
async def ingest(request: Request) -> dict:
    """수집기가 그 컴퓨터의 세션 전체를 보낸다(처음·다시 맞출 때). seq 를 주면 이어서 바뀐 것만 받을 수 있다."""
    body = await request.json()
    host = _host_of(body)
    agents = body.get("agents")
    if not isinstance(agents, list) or len(agents) > 200:
        raise HTTPException(400, "host·agents 형식이 맞지 않다")
    meta = _meta_of(body)
    prev = hub.hosts.get(host)
    hub.hosts[host] = {"receivedAt": time.time(), "agents": agents, "meta": meta, "seq": _seq_of(body.get("seq"))}
    if prev is None or prev["agents"] != agents or prev.get("meta") != meta or prev.get("offline"):
        await hub.bump()
    return {"ok": True}


@app.post("/api/ingest/patch", dependencies=[Depends(require_write)])
async def ingest_patch(request: Request) -> dict:
    """바뀐 세션만 받는다: set(바뀌거나 새로 생긴 세션 전체) · del(사라진 id) · order(id 순서).
    허브가 아는 마지막 seq 가 base 와 다르면(허브 재시작·놓친 전송) resync 를 돌려줘 수집기가 전체를 다시 보낸다."""
    body = await request.json()
    host = _host_of(body)
    h = hub.hosts.get(host)
    base, seq = _seq_of(body.get("base")), _seq_of(body.get("seq"))
    if not h or h.get("offline") or h.get("seq") is None or base != h["seq"] or seq is None:
        return {"ok": False, "resync": True}
    set_, dels, order = body.get("set") or [], body.get("del") or [], body.get("order")
    if not (isinstance(set_, list) and isinstance(dels, list) and isinstance(order, list)) \
            or len(set_) > 200 or len(dels) > 400 or len(order) > 200 \
            or not all(isinstance(a, dict) and isinstance(a.get("id"), str) for a in set_):
        raise HTTPException(400, "set·del·order 형식이 맞지 않다")
    by = {a.get("id"): a for a in h["agents"]}
    for i in dels:
        by.pop(i, None)
    for a in set_:
        by[a["id"]] = a
    agents = [by[i] for i in order if isinstance(i, str) and i in by]
    meta = _meta_of(body)
    changed = bool(set_ or dels) or [a.get("id") for a in h["agents"]] != [a.get("id") for a in agents] or h.get("meta") != meta
    hub.hosts[host] = {"receivedAt": time.time(), "agents": agents, "meta": meta, "seq": seq}
    if changed:
        await hub.bump()
    return {"ok": True}


class Bye(BaseModel):
    host: str = Field(min_length=1, max_length=40)


@app.post("/api/hosts/bye", dependencies=[Depends(require_write)])
async def host_bye(b: Bye) -> dict:
    """수집기가 정상 종료(SIGTERM·Ctrl+C)하며 알린다. 30초를 기다리지 않고 바로 끊김으로 본다."""
    h = hub.hosts.get(b.host)
    if h and not h.get("offline"):
        h["offline"] = True
        await hub.bump()
    return {"ok": True}


@app.get("/api/state")
async def state() -> dict:
    return hub.snapshot()


PATCH_KEYS = ("config", "messaging", "messages", "approvals", "approvalsReady")


def _agent_key(a: dict) -> str:
    return f"{a.get('host')}/{a.get('id')}"


def _sent_view(snap: dict) -> dict:
    """연결마다 마지막으로 보낸 상태를 비교하기 쉬운 문자열로 기억한다."""
    return {"agents": {_agent_key(a): json.dumps(a, sort_keys=True, ensure_ascii=False) for a in snap["agents"]},
            "order": [_agent_key(a) for a in snap["agents"]],
            **{k: json.dumps(snap[k], sort_keys=True, ensure_ascii=False) for k in PATCH_KEYS}}


def _patch(prev: dict, snap: dict) -> dict:
    """화면에 보낼 차분: 바뀐 세션 전체(set), 사라진 키(del), 순서가 바뀌었으면 order, 바뀐 설정·메시지."""
    out = {"version": snap["version"], "now": snap["now"], "hosts": snap["hosts"], "set": [], "del": []}
    keys = []
    for a in snap["agents"]:
        k = _agent_key(a)
        keys.append(k)
        if prev["agents"].get(k) != json.dumps(a, sort_keys=True, ensure_ascii=False):
            out["set"].append(a)
    now_keys = set(keys)
    out["del"] = [k for k in prev["agents"] if k not in now_keys]
    if keys != prev["order"]:
        out["order"] = keys
    for k in PATCH_KEYS:
        if json.dumps(snap[k], sort_keys=True, ensure_ascii=False) != prev[k]:
            out[k] = snap[k]
    return out


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    async def gen():
        seen, sent = -1, None
        while not hub.closing and not await request.is_disconnected():
            if hub.version != seen:
                seen = hub.version
                snap = hub.snapshot()
                if sent is None:   # 이 연결의 첫 소식은 전체, 그다음부터는 바뀐 것만(event: patch)
                    yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                else:
                    yield f"event: patch\ndata: {json.dumps(_patch(sent, snap), ensure_ascii=False)}\n\n"
                sent = _sent_view(snap)
                continue
            try:
                async with hub.changed:
                    await asyncio.wait_for(hub.changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 대시보드 → 세션 메시지 ----------
# 흐름: 화면이 /api/sessions/message 로 맡김 → 그 컴퓨터의 수집기가 /api/outbox/wait(롱폴링)로 바로 받아
#       세션 수신함 소켓에 쓰고 → /api/outbox/result 로 결과를 알린다. 허브는 세션에 직접 닿지 않는다.
# 켜는 조건: 허브 OFFICE_TOKEN + 관리 화면 '메시지 보내기' + 그 컴퓨터 수집기 CLAUDE_OFFICE_MESSAGES=on


class OutMessage(BaseModel):
    host: str = Field(min_length=1, max_length=40)
    session: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=MAX_MESSAGE)


def _require_messaging() -> None:
    if not TOKEN:
        raise HTTPException(403, "메시지 보내기는 허브에 OFFICE_TOKEN 을 정해야 쓸 수 있다")
    if not hub.config.get("messaging"):
        raise HTTPException(403, "관리 화면에서 '대시보드에서 메시지 보내기'가 꺼져 있다")


@app.post("/api/sessions/message", dependencies=[Depends(require_write)])
async def send_message(m: OutMessage) -> dict:
    _require_messaging()
    h = hub.hosts.get(m.host)
    agent = next((a for a in (h or {}).get("agents", []) if a.get("id") == m.session), None)
    if not agent or h.get("offline"):
        raise HTTPException(404, "그 세션이 지금 보이지 않는다")
    if not agent.get("canMessage"):
        raise HTTPException(409, "그 컴퓨터의 수집기가 메시지를 받지 않는다(CLAUDE_OFFICE_MESSAGES 꺼짐·Windows·수신함 없음)")
    now = time.time()
    item = {"id": hashlib.sha256(f"{now}{m.session}{m.text}".encode()).hexdigest()[:12], "host": m.host,
            "session": m.session, "text": m.text, "preview": m.text[:60], "status": "queued", "error": "",
            "createdAt": now}
    hub.outbox = (hub.outbox + [item])[-50:]
    async with hub.queued:
        hub.queued.notify_all()
    await hub.bump()
    return {"id": item["id"], "status": "queued"}


class Pull(BaseModel):
    host: str = Field(min_length=1, max_length=40)


def _has_queued(host: str) -> bool:
    return any(m["host"] == host and m["status"] == "queued" for m in hub.outbox)


async def _claim(host: str) -> dict:
    out = []
    for m in hub.outbox:
        if m["host"] == host and m["status"] == "queued":
            m["status"] = "sending"
            out.append({"id": m["id"], "session": m["session"], "text": m["text"]})
    if out:
        await hub.bump()
    return {"messages": out}


@app.post("/api/outbox/pull", dependencies=[Depends(require_write)])
async def outbox_pull(p: Pull) -> dict:
    """예전 수집기용(1초마다 가져가기). 새 수집기는 /api/outbox/wait 를 쓴다."""
    _require_messaging()
    return await _claim(p.host)


class Wait(BaseModel):
    host: str = Field(min_length=1, max_length=40)
    timeout: float = Field(WAIT_MAX_SEC, strict=True)   # 숫자만 — 문자열("nan"·"5")·참거짓은 422

    @field_validator("timeout", mode="before")
    @classmethod
    def _finite(cls, v):
        # NaN 이면 deadline 비교가 늘 거짓이라 끝없이 돈다. 422 로 돌려주면 응답에 NaN 이 실려 직렬화가 깨지므로
        # 유한한 값으로 바꾼다: NaN·-무한 → 0(바로 빈 응답), +무한 → 상한
        if isinstance(v, float) and not math.isfinite(v):
            return WAIT_MAX_SEC if v > 0 else 0.0
        return v


@app.post("/api/outbox/wait", dependencies=[Depends(require_write)])
async def outbox_wait(p: Wait, request: Request) -> dict:
    """롱폴링: 그 컴퓨터 앞으로 쌓인 메시지가 있으면 바로, 없으면 생길 때까지(최대 25초) 기다렸다 돌려준다."""
    _require_messaging()
    wait = p.timeout if math.isfinite(p.timeout) else 0.0
    deadline = time.monotonic() + min(max(wait, 0.0), WAIT_MAX_SEC)
    while True:
        async with hub.queued:
            left = deadline - time.monotonic()
            if not _has_queued(p.host) and left > 0 and not hub.closing:
                try:   # 5초마다 깨어 수집기가 끊었는지 본다
                    await asyncio.wait_for(hub.queued.wait(), timeout=min(left, 5))
                except asyncio.TimeoutError:
                    pass
        # 기다리는 사이 수집기가 끊었으면 메시지를 가져가지 않는다(다음 연결이 받게)
        if await request.is_disconnected():
            return {"messages": []}
        if _has_queued(p.host):
            return await _claim(p.host)
        if deadline - time.monotonic() <= 0 or hub.closing:   # 허브가 끝나는 중이면 빈 응답으로 바로 돌려보낸다
            return {"messages": []}


class Result(BaseModel):
    host: str
    id: str
    ok: bool
    error: str = ""


@app.post("/api/outbox/result", dependencies=[Depends(require_write)])
async def outbox_result(r: Result) -> dict:
    for m in hub.outbox:
        if m["id"] == r.id and m["host"] == r.host:
            m.update(status="sent" if r.ok else "failed", error=r.error[:200])
            m["text"] = ""   # 전달이 끝난 본문은 허브 메모리에 남기지 않는다(미리보기만)
            await hub.bump()
            break
    return {"ok": True}


# ---------- 대시보드에서 권한 승인 ----------
# 흐름: 그 컴퓨터의 승인 훅(hooks/claude_office_approve.py, PermissionRequest)이 /api/approvals 로 요청을 올리고
#       /api/approvals/wait 로 결정을 기다린다 → 화면에서 허용·거절(/api/approvals/{id}/decide) → 훅이 결정을
#       Claude Code 에 돌려준다. 터미널 권한 창은 그동안에도 떠 있고, 사람이 먼저 답하면 그쪽이 이긴다.
#       그 세션이 더는 '승인 대기'가 아니게 되면(터미널에서 답함·끝남) 요청은 gone 이 되어 훅이 조용히 끝난다.
# 켜는 조건: 허브 OFFICE_TOKEN + 관리 화면 '대시보드에서 승인' + 그 컴퓨터 .env CLAUDE_OFFICE_APPROVE=on + 승인 훅 설치
APPROVAL_TTL_SEC = 590      # 훅 시간 제한(600초)보다 조금 짧게
APPROVAL_GRACE_SEC = 8      # 요청 직후에는 수집기가 아직 '승인 대기'를 못 봤을 수 있다
APPROVAL_GONE_SEC = 4       # 세션이 승인 대기가 아닌 채로 이만큼 지나면 요청을 거둔다


def _require_approvals() -> None:
    if not TOKEN:
        raise HTTPException(403, "대시보드 승인은 허브에 OFFICE_TOKEN 을 정해야 쓸 수 있다")
    if not hub.config.get("approvals"):
        raise HTTPException(403, "관리 화면에서 '대시보드에서 승인'이 꺼져 있다")


def _settle_approvals(now: float) -> bool:
    """끝난 요청을 정리한다: 시간 초과·컴퓨터 끊김·세션이 더는 승인 대기가 아님 → gone. 바뀌었으면 True."""
    changed = False
    for x in list(hub.approvals.values()):
        if x["status"] != "pending":
            if now - (x.get("decidedAt") or x["createdAt"]) > 120:
                del hub.approvals[x["id"]]
            continue
        h = hub.hosts.get(x["host"])
        agent = next((a for a in (h or {}).get("agents", []) if a.get("id") == x["session"]), None)
        waiting = bool(agent) and agent.get("kind") == "approval" and bool(h) and hub.online(h, now)
        if waiting:
            x["notSince"] = None
        elif now - x["createdAt"] > APPROVAL_GRACE_SEC:
            x["notSince"] = x.get("notSince") or now
            if now - x["notSince"] >= APPROVAL_GONE_SEC:
                x.update(status="gone", decidedAt=now)
                changed = True
        if x["status"] == "pending" and now - x["createdAt"] > APPROVAL_TTL_SEC:
            x.update(status="gone", decidedAt=now)
            changed = True
    return changed


class ApprovalIn(BaseModel):
    host: str = Field(pattern=r"^[A-Za-z0-9._-]{1,40}$")
    session: str = Field(min_length=1, max_length=80)
    toolUseId: str = Field("", max_length=120)
    tool: str = Field(min_length=1, max_length=64)
    preview: str = Field("", max_length=600)


@app.post("/api/approvals", dependencies=[Depends(require_write)])
async def approval_request(a: ApprovalIn) -> dict:
    _require_approvals()
    now = time.time()
    for x in hub.approvals.values():   # 같은 도구 호출로 다시 오면(훅 재시도) 그 요청을 그대로
        if a.toolUseId and x["toolUseId"] == a.toolUseId and x["host"] == a.host and x["status"] == "pending":
            return {"id": x["id"]}
    aid = hashlib.sha256(f"{now}{a.host}{a.session}{a.toolUseId}".encode()).hexdigest()[:16]
    hub.approvals[aid] = {"id": aid, "host": a.host, "session": a.session, "toolUseId": a.toolUseId, "tool": a.tool,
                          "preview": a.preview, "createdAt": now, "status": "pending", "notSince": None}
    if len(hub.approvals) > 100:   # 넘치면 오래된 끝난 것부터
        for k in sorted(hub.approvals, key=lambda k: hub.approvals[k]["createdAt"])[:20]:
            if hub.approvals[k]["status"] != "pending":
                del hub.approvals[k]
    await hub.bump()
    return {"id": aid}


class ApprovalWait(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    timeout: float = 25

    @field_validator("timeout")
    @classmethod
    def _finite_wait(cls, v):
        return v if math.isfinite(v) else 0


@app.post("/api/approvals/wait", dependencies=[Depends(require_write)])
async def approval_wait(w: ApprovalWait, request: Request) -> dict:
    """결정이 나거나(allow·deny), 요청이 거둬지거나(gone), timeout 이 지나면(pending) 답한다."""
    deadline = time.monotonic() + max(0.0, min(w.timeout, WAIT_MAX_SEC))
    while True:
        x = hub.approvals.get(w.id)
        if not x:
            return {"status": "gone"}
        if x["status"] != "pending" or hub.closing:
            return {"status": x["status"]}
        left = deadline - time.monotonic()
        if left <= 0 or await request.is_disconnected():
            return {"status": "pending"}
        try:
            async with hub.decided:
                await asyncio.wait_for(hub.decided.wait(), timeout=min(left, 5))
        except asyncio.TimeoutError:
            pass


@app.get("/api/approvals/{aid}", dependencies=[Depends(require_write)])
async def approval_detail(aid: str) -> dict:
    """명령 미리보기까지. 쓰기 토큰이 있어야 본다."""
    x = hub.approvals.get(aid)
    if not x:
        raise HTTPException(404, "그 요청이 없다")
    return {k: x[k] for k in ("id", "host", "session", "tool", "preview", "createdAt", "status")}


class Decision(BaseModel):
    decision: Literal["allow", "deny"]


@app.post("/api/approvals/{aid}/decide", dependencies=[Depends(require_write)])
async def approval_decide(aid: str, d: Decision) -> dict:
    _require_approvals()
    x = hub.approvals.get(aid)
    if not x:
        raise HTTPException(404, "그 요청이 없다")
    if x["status"] != "pending":
        raise HTTPException(409, f"이미 끝난 요청이다({x['status']})")
    x.update(status=d.decision, decidedAt=time.time())
    async with hub.decided:
        hub.decided.notify_all()
    await hub.bump()
    return {"ok": True, "status": x["status"]}


@app.get("/api/config")
async def get_config() -> dict:
    return hub.config


@app.put("/api/config", dependencies=[Depends(require_write)])
async def put_config(cfg: Config) -> dict:
    try:
        cfg.check()
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.config = cfg.model_dump()
    save_config(hub.config)
    await hub.bump()
    return hub.config


@app.post("/api/config/reset", dependencies=[Depends(require_write)])
async def reset_config() -> dict:
    hub.config = default_config()
    save_config(hub.config)
    await hub.bump()
    return hub.config


# ---------- 캐릭터 이미지 ----------

_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
]
_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _sniff(data: bytes) -> str | None:
    # 확장자·Content-Type 을 믿지 않고 바이트로 판정한다. SVG 는 스크립트가 들어갈 수 있어 받지 않는다.
    for sig, ext, _ in _MAGIC:
        if data.startswith(sig):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@app.post("/api/assets", dependencies=[Depends(require_write)])
async def upload_asset(request: Request) -> dict:
    data = await request.body()
    if not data or len(data) > MAX_ASSET_BYTES:
        raise HTTPException(400, "이미지는 2MB 이하여야 한다")
    ext = _sniff(data)
    if not ext:
        raise HTTPException(400, "PNG·JPG·GIF·WEBP 만 받는다")
    ASSETS.mkdir(parents=True, exist_ok=True)
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    path = ASSETS / name
    if not path.exists():
        path.write_bytes(data)
    return {"name": name, "url": f"/assets/{name}"}


@app.get("/api/assets")
async def list_assets() -> list[dict]:
    if not ASSETS.is_dir():
        return []
    used = _used_assets()
    return [{"name": p.name, "url": f"/assets/{p.name}", "bytes": p.stat().st_size, "used": p.name in used}
            for p in sorted(ASSETS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if p.suffix[1:] in _TYPES]


def _used_assets() -> set[str]:
    used = set()
    for c in hub.config.get("characters", []):
        used.add(c.get("image", ""))
        used.update(s.get("image", "") for s in c.get("states", {}).values())
    return used - {""}


@app.delete("/api/assets/{name}", dependencies=[Depends(require_write)])
async def delete_asset(name: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|gif|webp)", name):
        raise HTTPException(404)
    if name in _used_assets():
        raise HTTPException(409, "캐릭터가 쓰고 있는 이미지다")
    (ASSETS / name).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/assets/{name}")
async def get_asset(name: str):
    if not re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|gif|webp)", name) or not (ASSETS / name).is_file():
        return JSONResponse({"detail": "없음"}, status_code=404)
    return FileResponse(ASSETS / name, media_type=_TYPES[name.rsplit(".", 1)[1]],
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Cache-Control": "public, max-age=31536000, immutable"})


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("OFFICE_BIND") or "127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("OFFICE_PORT") or 3006))
    ap.add_argument("--log", help="출력을 이 파일에 이어 쓴다(1MB 넘으면 시작할 때 비움, 맨 위 _early_log 가 처리)")
    args = ap.parse_args()
    # 열린 SSE·롱폴링 연결을 GRACEFUL_SEC 만 기다리고 끝낸다(Dockerfile CMD 의 --timeout-graceful-shutdown 과 같은 값)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", timeout_graceful_shutdown=GRACEFUL_SEC)
