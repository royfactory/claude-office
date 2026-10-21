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
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent   # 저장소 루트(도커 안에서는 / 이라 data 가 /data 가 된다)


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
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
            saved = json.loads(CONFIG_PATH.read_text())
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
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    tmp.replace(CONFIG_PATH)


# ---------- 실시간 상태 ----------

class Hub:
    def __init__(self) -> None:
        self.hosts: dict[str, dict] = {}  # host -> {"receivedAt", "agents"}
        self.config = load_config()
        self.version = 0
        self.changed = asyncio.Condition()

    def snapshot(self) -> dict:
        now = time.time()
        hosts, agents = [], []
        for name, h in sorted(self.hosts.items()):
            age = now - h["receivedAt"]
            hosts.append({"host": name, "age": round(age, 1), "online": age < HOST_STALE_SEC,
                          "count": len(h["agents"])})
            if age < HOST_STALE_SEC:
                agents.extend({**a, "host": name} for a in h["agents"])
        return {"version": self.version, "now": now, "hosts": hosts, "agents": agents,
                "config": self.config}

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
        cur = {h: now - v["receivedAt"] < HOST_STALE_SEC for h, v in hub.hosts.items()}
        if cur != online:
            online = cur
            await hub.bump()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_expire_loop())
    yield
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


@app.post("/api/ingest", dependencies=[Depends(require_write)])
async def ingest(request: Request) -> dict:
    body = await request.json()
    host = str(body.get("host", ""))[:40]
    agents = body.get("agents")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", host) or not isinstance(agents, list) or len(agents) > 200:
        raise HTTPException(400, "host·agents 형식이 맞지 않다")
    prev = hub.hosts.get(host)
    hub.hosts[host] = {"receivedAt": time.time(), "agents": agents}
    if prev is None or prev["agents"] != agents:
        await hub.bump()
    return {"ok": True}


@app.get("/api/state")
async def state() -> dict:
    return hub.snapshot()


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    async def gen():
        seen = -1
        while not await request.is_disconnected():
            if hub.version != seen:
                seen = hub.version
                yield f"data: {json.dumps(hub.snapshot(), ensure_ascii=False)}\n\n"
                continue
            try:
                async with hub.changed:
                    await asyncio.wait_for(hub.changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
