"""hub/app.py 테스트(FastAPI TestClient). 허브 의존성(hub/requirements.txt)과 httpx 가 있어야 돈다."""
import asyncio
import json
import signal
import socket
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from conftest import HUB_PY, load_module  # noqa: E402

TOKEN = "test-token"
AUTH = {"X-Office-Token": TOKEN}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF87 = b"GIF87a" + b"\x00" * 32
GIF89 = b"GIF89a" + b"\x01" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


@pytest.fixture
def make_hub(home, tmp_path, monkeypatch):
    """OFFICE_DATA·OFFICE_TOKEN 을 정한 뒤 app.py 를 새로 읽고 TestClient 를 연다(lifespan 포함)."""
    opened = []

    def make(token=""):
        monkeypatch.setenv("OFFICE_DATA", str(tmp_path / "data"))
        monkeypatch.setenv("OFFICE_TOKEN", token)
        mod = load_module("office_hub_app", HUB_PY)
        client = TestClient(mod.app)
        client.__enter__()
        opened.append(client)
        return mod, client

    yield make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def hub(make_hub):
    return make_hub()


@pytest.fixture
def authed(make_hub):
    return make_hub(TOKEN)


def agent(sid="s1", **kw):
    return {"id": sid, "name": "n", "kind": "idle", **kw}


# ---------- 기본 ----------

def test_health(hub):
    _, c = hub
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "hosts": 0, "version": 0, "auth": False}


def test_health_reports_auth(authed):
    _, c = authed
    assert c.get("/health").json()["auth"] is True


def test_ingest_and_state_snapshot(hub):
    _, c = hub
    r = c.post("/api/ingest", json={"host": "mac-1", "agents": [agent()], "meta": {"checklistRule": 1, "x": 2}})
    assert r.status_code == 200 and r.json() == {"ok": True}
    s = c.get("/api/state").json()
    assert s["version"] == 1
    (h,) = s["hosts"]
    assert h["host"] == "mac-1" and h["online"] is True and h["count"] == 1
    assert h["checklistRule"] is True and "x" not in h
    assert s["agents"] == [{**agent(), "host": "mac-1"}]
    assert s["messaging"] == {"ready": False, "auth": False}
    assert s["config"]["rooms"] and s["messages"] == []


def test_ingest_without_meta_has_no_checklist_key(hub):
    _, c = hub
    c.post("/api/ingest", json={"host": "pc", "agents": []})
    assert "checklistRule" not in c.get("/api/state").json()["hosts"][0]


def test_ingest_same_payload_does_not_bump(hub):
    _, c = hub
    body = {"host": "pc", "agents": [agent()]}
    c.post("/api/ingest", json=body)
    c.post("/api/ingest", json=body)
    assert c.get("/health").json()["version"] == 1


@pytest.mark.parametrize("body", [
    {"host": "bad host!", "agents": []},
    {"host": "", "agents": []},
    {"host": "a/b", "agents": []},
    {"host": "pc", "agents": {"not": "list"}},
    {"host": "pc"},
    {"host": "pc", "agents": [{}] * 201},
])
def test_ingest_rejects_bad_shape(hub, body):
    _, c = hub
    assert c.post("/api/ingest", json=body).status_code == 400


# ---------- 토큰 ----------

def test_write_needs_token(authed):
    _, c = authed
    body = {"host": "pc", "agents": []}
    assert c.post("/api/ingest", json=body).status_code == 401
    assert c.post("/api/ingest", json=body, headers={"X-Office-Token": "wrong"}).status_code == 401
    assert c.post("/api/ingest", json=body, headers=AUTH).status_code == 200
    assert c.post("/api/ingest", json=body, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert c.post("/api/config/reset").status_code == 401
    assert c.post("/api/assets", content=PNG).status_code == 401


def test_read_is_open_with_token(authed):
    _, c = authed
    assert c.get("/api/state").status_code == 200
    assert c.get("/api/config").status_code == 200
    assert c.get("/api/assets").status_code == 200


def test_no_token_means_open_writes(hub):
    _, c = hub
    assert c.post("/api/ingest", json={"host": "pc", "agents": []}).status_code == 200
    assert c.post("/api/config/reset").status_code == 200


# ---------- 설정 ----------

def test_put_config_saves_and_persists(make_hub, tmp_path):
    mod, c = make_hub()
    cfg = c.get("/api/config").json()
    cfg["meName"] = "로이"
    cfg["assignments"] = [{"match": "project", "value": "claude-office", "character": "fox"}]
    r = c.put("/api/config", json=cfg)
    assert r.status_code == 200 and r.json()["meName"] == "로이"
    saved = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert saved["meName"] == "로이"
    _, c2 = make_hub()                       # 다시 띄워도 설정이 남는다
    assert c2.get("/api/config").json()["assignments"][0]["character"] == "fox"


def _put(c, change):
    cfg = c.get("/api/config").json()
    change(cfg)
    return c.put("/api/config", json=cfg)


def test_put_config_rejects_missing_room(hub):
    _, c = hub
    r = _put(c, lambda cfg: cfg["rooms"].pop())
    assert r.status_code == 400 and "방" in r.json()["detail"]


def test_put_config_rejects_unknown_character_in_assignment(hub):
    _, c = hub
    r = _put(c, lambda cfg: cfg.update(assignments=[{"match": "host", "value": "pc", "character": "ghost"}]))
    assert r.status_code == 400 and "ghost" in r.json()["detail"]


@pytest.mark.parametrize("key", ["subagentCharacter", "meCharacter"])
def test_put_config_rejects_unknown_special_character(hub, key):
    _, c = hub
    assert _put(c, lambda cfg: cfg.update({key: "ghost"})).status_code == 400


def test_put_config_rejects_duplicate_ids_and_missing_image(hub):
    _, c = hub
    assert _put(c, lambda cfg: cfg["characters"].append(dict(cfg["characters"][0]))).status_code == 400
    assert _put(c, lambda cfg: cfg["characters"][0].update(image="0123456789abcdef.png")).status_code == 400


def test_put_config_schema_errors_are_422(hub):
    _, c = hub
    assert _put(c, lambda cfg: cfg["characters"][0].update(color="red")).status_code == 422
    assert _put(c, lambda cfg: cfg.update(defaultRoom="lounge")).status_code == 422


def test_reset_config(hub):
    mod, c = hub
    _put(c, lambda cfg: cfg.update(meName="바뀜"))
    r = c.post("/api/config/reset")
    assert r.status_code == 200 and {k: v for k, v in r.json().items() if k != "rev"} == {k: v for k, v in mod.default_config().items() if k != "rev"}
    assert c.get("/api/config").json()["meName"] == "나"


# ---------- 메시지 ----------

MSG = {"host": "mac", "session": "s1", "text": "안녕하세요 확인 부탁"}


def _messaging_on(c):
    cfg = c.get("/api/config").json()
    cfg["messaging"] = True
    assert c.put("/api/config", json=cfg, headers=AUTH).status_code == 200


def test_message_needs_hub_token(hub):
    _, c = hub
    _put(c, lambda cfg: cfg.update(messaging=True))
    r = c.post("/api/sessions/message", json=MSG)
    assert r.status_code == 403 and "OFFICE_TOKEN" in r.json()["detail"]
    assert c.post("/api/outbox/pull", json={"host": "mac"}).status_code == 403


def test_message_needs_messaging_on(authed):
    _, c = authed
    assert c.post("/api/sessions/message", json=MSG, headers=AUTH).status_code == 403
    assert c.get("/api/state").json()["messaging"] == {"ready": False, "auth": True}


def test_message_unknown_session_404_and_no_inbox_409(authed):
    _, c = authed
    _messaging_on(c)
    assert c.post("/api/sessions/message", json=MSG, headers=AUTH).status_code == 404
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1")]}, headers=AUTH)
    assert c.post("/api/sessions/message", json=MSG, headers=AUTH).status_code == 409


def test_message_queue_pull_result_flow(authed):
    mod, c = authed
    _messaging_on(c)
    assert c.get("/api/state").json()["messaging"]["ready"] is True
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", canMessage=True)]}, headers=AUTH)
    assert c.post("/api/sessions/message", json=MSG).status_code == 401      # 쓰기라 토큰 필요

    r = c.post("/api/sessions/message", json=MSG, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "queued"
    mid = r.json()["id"]
    (m,) = c.get("/api/state").json()["messages"]
    assert m["id"] == mid and m["status"] == "queued" and m["preview"] == MSG["text"] and "text" not in m

    assert c.post("/api/outbox/pull", json={"host": "mac"}).status_code == 401
    assert c.post("/api/outbox/pull", json={"host": "other"}, headers=AUTH).json() == {"messages": []}
    pulled = c.post("/api/outbox/pull", json={"host": "mac"}, headers=AUTH).json()["messages"]
    assert pulled == [{"id": mid, "session": "s1", "text": MSG["text"]}]
    assert c.get("/api/state").json()["messages"][0]["status"] == "sending"
    assert c.post("/api/outbox/pull", json={"host": "mac"}, headers=AUTH).json() == {"messages": []}

    r = c.post("/api/outbox/result", json={"host": "mac", "id": mid, "ok": True}, headers=AUTH)
    assert r.status_code == 200
    assert c.get("/api/state").json()["messages"][0]["status"] == "sent"
    assert mod.hub.outbox[0]["text"] == ""        # 전달이 끝난 본문은 허브에 남기지 않는다


def test_message_failed_result_keeps_error(authed):
    mod, c = authed
    _messaging_on(c)
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", canMessage=True)]}, headers=AUTH)
    mid = c.post("/api/sessions/message", json=MSG, headers=AUTH).json()["id"]
    c.post("/api/outbox/pull", json={"host": "mac"}, headers=AUTH)
    c.post("/api/outbox/result", json={"host": "mac", "id": mid, "ok": False, "error": "x" * 500}, headers=AUTH)
    (m,) = c.get("/api/state").json()["messages"]
    assert m["status"] == "failed" and m["error"] == "x" * 200
    assert mod.hub.outbox[0]["text"] == ""


def test_message_result_from_other_host_is_ignored(authed):
    _, c = authed
    _messaging_on(c)
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", canMessage=True)]}, headers=AUTH)
    mid = c.post("/api/sessions/message", json=MSG, headers=AUTH).json()["id"]
    c.post("/api/outbox/result", json={"host": "evil", "id": mid, "ok": True}, headers=AUTH)
    assert c.get("/api/state").json()["messages"][0]["status"] == "queued"


def test_message_text_limits(authed):
    _, c = authed
    _messaging_on(c)
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", canMessage=True)]}, headers=AUTH)
    assert c.post("/api/sessions/message", json={**MSG, "text": ""}, headers=AUTH).status_code == 422
    assert c.post("/api/sessions/message", json={**MSG, "text": "x" * 4001}, headers=AUTH).status_code == 422


# ---------- 이미지 ----------

@pytest.mark.parametrize("data,ext,ctype", [
    (PNG, "png", "image/png"), (JPG, "jpg", "image/jpeg"), (GIF87, "gif", "image/gif"),
    (GIF89, "gif", "image/gif"), (WEBP, "webp", "image/webp"),
])
def test_upload_image_by_bytes(hub, data, ext, ctype):
    _, c = hub
    r = c.post("/api/assets", content=data, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    name = r.json()["name"]
    assert name.endswith("." + ext) and r.json()["url"] == f"/assets/{name}"
    g = c.get(f"/assets/{name}")
    assert g.status_code == 200 and g.content == data
    assert g.headers["content-type"] == ctype and g.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("data", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b'<?xml version="1.0"?><svg/>',
    b"<html><body>png</body></html>",
    b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 16,      # RIFF 지만 WEBP 가 아님
    b"xx\x89PNG\r\n\x1a\n",                              # 서명이 맨 앞이 아님
    b"",
])
def test_upload_rejects_non_images(hub, data):
    _, c = hub
    assert c.post("/api/assets", content=data, headers={"Content-Type": "image/png"}).status_code == 400


def test_upload_rejects_over_2mb(hub):
    mod, c = hub
    big = PNG + b"\x00" * (mod.MAX_ASSET_BYTES - len(PNG) + 1)
    assert c.post("/api/assets", content=big).status_code == 400
    ok = PNG + b"\x00" * (mod.MAX_ASSET_BYTES - len(PNG))
    assert c.post("/api/assets", content=ok).status_code == 200


def test_used_image_cannot_be_deleted(hub):
    _, c = hub
    name = c.post("/api/assets", content=PNG).json()["name"]
    assert _put(c, lambda cfg: cfg["characters"][0].update(image=name)).status_code == 200
    assert [a["used"] for a in c.get("/api/assets").json()] == [True]
    assert c.delete(f"/api/assets/{name}").status_code == 409
    _put(c, lambda cfg: cfg["characters"][0].update(image=""))
    assert c.delete(f"/api/assets/{name}").status_code == 200
    assert c.get(f"/assets/{name}").status_code == 404
    assert c.get("/api/assets").json() == []


def test_state_image_counts_as_used(hub):
    _, c = hub
    name = c.post("/api/assets", content=GIF89).json()["name"]
    _put(c, lambda cfg: cfg["characters"][1].update(states={"working": {"emoji": "", "image": name}}))
    assert c.delete(f"/api/assets/{name}").status_code == 409


def test_walk_images_count_as_used_and_must_exist(hub):
    _, c = hub
    name = c.post("/api/assets", content=GIF89).json()["name"]
    walk = {"front": [name, name], "back": [name]}
    r = _put(c, lambda cfg: cfg["characters"][2].update(walk=walk))
    assert r.status_code == 200 and r.json()["characters"][2]["walk"] == walk
    assert c.delete(f"/api/assets/{name}").status_code == 409
    assert _put(c, lambda cfg: cfg["characters"][2].update(walk={"front": ["0123456789abcdef.png"]})).status_code == 400
    assert _put(c, lambda cfg: cfg["characters"][2].update(walk={"side": [name]})).status_code == 422
    assert _put(c, lambda cfg: cfg["characters"][2].update(walk={"front": [name] * 5})).status_code == 422


def test_default_characters_use_bundled_images(hub):
    mod, c = hub
    cfg = c.get("/api/config").json()
    chars = {ch["id"]: ch for ch in cfg["characters"]}
    assert cfg["meCharacter"] == "me" and chars["me"]["inPool"] is False
    names = [n for ch in cfg["characters"] for n in [ch["image"], *(f for fr in ch["walk"].values() for f in fr)]]
    assert len(names) == 14 * 5 and all(names)
    states = [s["image"] for ch in cfg["characters"] for s in ch["states"].values()]
    assert len(states) == 14 * 3 and all(c.get("/assets/" + n).status_code == 200 for n in states)
    r = c.get(f"/assets/{names[0]}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert c.get("/api/assets").json() == []                     # 기본 이미지는 올린 이미지 목록에 없다
    assert _put(c, lambda cfg: cfg.update(meName="로이")).status_code == 200   # 기본 이미지로 설정 검사를 통과한다


def test_language_setting(hub):
    _, c = hub
    assert c.get("/api/config").json()["language"] == "auto"
    assert _put(c, lambda cfg: cfg.update(language="en")).json()["language"] == "en"
    assert _put(c, lambda cfg: cfg.update(language="fr")).status_code == 422


def test_ingest_keeps_clean_system_stats(hub):
    _, c = hub
    meta = {"sys": {"cpu": 37.6, "gpu": None, "mem": 140, "disk": "x", "memTotal": 1024, "diskTotal": -5, "ts": 1, "junk": 1}}
    assert c.post("/api/ingest", json={"host": "mac", "agents": [agent()], "meta": meta}, headers=AUTH).status_code == 200
    h = c.get("/api/state").json()["hosts"][0]
    assert h["sys"] == {"cpu": 37, "gpu": None, "mem": 100, "disk": None, "memTotal": 1024, "ts": 1}


def test_pages_and_code_ask_for_fresh_copy(hub):
    _, c = hub
    for u in ("/", "/admin", "/static/office3d.js", "/static/i18n.js"):
        assert c.get(u).headers["cache-control"] == "no-cache", u


def test_favicon(hub):
    _, c = hub
    r = c.get("/favicon.ico")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get("/static/favicon.svg").status_code == 200
    assert 'href="/static/favicon.svg"' in c.get("/").text and 'href="/static/favicon.svg"' in c.get("/admin").text


def test_old_config_gets_default_looks_once(make_hub, tmp_path):
    """기본 캐릭터 그림이 생기기 전에 저장된 설정(이모지만)에 한 번만 그림을 채운다."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    old = {"characters": [
        {"id": "fox", "name": "여우", "emoji": "🦊", "color": "#d95926", "inPool": True, "states": {}},
        {"id": "cat", "name": "고양이", "emoji": "🐱", "color": "#fbbf24", "inPool": True, "states": {}, "image": "0123456789abcdef.png"},
        {"id": "mine", "name": "내 캐릭터", "emoji": "🙂", "color": "#94a3b8", "inPool": True, "states": {}}],
        "meCharacter": "", "meName": "로이"}
    (data / "config.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    mod, c = make_hub()
    cfg = c.get("/api/config").json()
    chars = {ch["id"]: ch for ch in cfg["characters"]}
    assert chars["fox"]["image"] and len(chars["fox"]["walk"]["front"]) == 2      # 그림 없던 기본 캐릭터는 채움
    assert set(chars["fox"]["states"]) == {"thinking", "stalled", "idle"}          # 상태별 모습도
    assert chars["cat"]["image"] == "0123456789abcdef.png"                       # 사용자가 고른 이미지는 그대로
    assert not chars["mine"].get("image")                                         # 기본이 아닌 캐릭터는 그대로
    assert "me" in chars and cfg["meCharacter"] == "me" and cfg["meName"] == "로이"
    assert chars["cat"]["states"]["idle"]["image"]                                 # 상태별 모습이 비었던 캐릭터는 그것만 채움
    saved = json.loads((data / "config.json").read_text(encoding="utf-8"))
    assert saved["lookVersion"] == mod.LOOK_VERSION
    # 그 뒤 사용자가 여우 그림을 빼면 다시 띄워도 채우지 않는다
    saved["characters"][0].update(image="", walk={})
    (data / "config.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    _, c2 = make_hub()
    assert not {ch["id"]: ch for ch in c2.get("/api/config").json()["characters"]}["fox"]["image"]


def test_stats_accumulate_deltas_and_active_time(hub):
    mod, c = hub
    st = mod.stats
    a = lambda **kw: {"id": "s1", "project": "web", "kind": "working", "tools": 10, "lines": [5, 1], "outTokens": 1000, **kw}   # noqa: E731
    st.observe("mac", [a()], now=1000.0)                                    # 처음 본 세션: 차 없음
    st.observe("mac", [a(tools=13, lines=[9, 2], outTokens=1600)], now=1010.0)
    st.observe("mac", [a(tools=14, kind="idle")], now=1020.0)               # 쉬는 동안은 활동 시간 아님
    st.observe("mac", [a(tools=15)], now=1200.0)                            # 30초 넘게 끊겼다 이어짐: 사이는 안 셈
    st.observe("mac", [a(tools=16, subagents=[{"id": "x", "tools": 4, "tool": "Read"}])], now=1205.0)
    day = st.summary(1, now=1205.0)["days"][-1]["projects"]["web"]
    assert day == {"active": 15.0, "tools": 6, "add": 4, "del": 1, "out": 600, "sessions": 1}
    # 같은 프로젝트에서 두 세션이 함께 일해도 활동 시간은 한 번만(겹친 구간), 백그라운드 대기는 활동이 아니다
    st2 = mod.Stats()
    st2.days, st2.prev = {}, {}
    two = lambda k: [{"id": "x", "project": "p", "kind": "working"}, {"id": "y", "project": "p", "kind": k}]   # noqa: E731
    st2.observe("mac", two("working"), now=2000.0)
    st2.observe("mac", two("working"), now=2010.0)
    st2.observe("mac", [{"id": "x", "project": "p", "kind": "waiting"}], now=2020.0)
    st2.observe("mac", [{"id": "x", "project": "p", "kind": "waiting"}], now=2030.0)
    assert st2.summary(1, now=2030.0)["days"][-1]["projects"]["p"]["active"] == 10.0
    st.flush(now=1205.0)
    assert mod.Stats().days == st.days                                      # 파일에서 다시 읽어 이어 센다
    r = c.get("/api/stats?days=3").json()
    assert len(r["days"]) == 3 and r["today"] == r["days"][-1]["date"]


def test_config_rev_rejects_stale_save(hub):
    _, c = hub
    cfg = c.get("/api/config").json()
    assert _put(c, lambda x: x.update(meName="가")).status_code == 200          # 판 하나 올라감
    stale = dict(cfg, meName="나중")                                             # 예전 판으로 저장 시도
    r = c.put("/api/config", json=stale)
    assert r.status_code == 409
    assert c.put("/api/config?force=true", json=stale).status_code == 200      # 일부러 덮어쓰기
    assert c.get("/api/config").json()["meName"] == "나중"


def test_broken_config_is_kept_aside(make_hub, tmp_path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "config.json").write_text("{ broken", encoding="utf-8")
    _, c = make_hub()
    assert c.get("/api/config").json()["meName"] == "나"                        # 기본값으로 뜬다
    assert not (data / "config.json").exists()                                    # 덮어쓰지 않았다
    assert [p.name for p in data.glob("config.json.broken-*")]                   # 옆에 보관


def test_same_host_name_from_two_machines_is_rejected(hub):
    _, c = hub
    a = {"host": "mac", "machine": "a" * 16, "agents": [agent()]}
    assert c.post("/api/ingest", json=a, headers=AUTH).status_code == 200
    b = dict(a, machine="b" * 16)
    assert c.post("/api/ingest", json=b, headers=AUTH).status_code == 409
    h = c.get("/api/state").json()["hosts"][0]
    assert h["conflict"] is True and "machine" not in h
    assert c.post("/api/ingest", json=a, headers=AUTH).status_code == 200      # 원래 컴퓨터는 그대로


def test_account_names_setting(hub):
    _, c = hub
    assert _put(c, lambda x: x.update(accountNames={"abcdef1234": "회사"})).status_code == 200
    assert _put(c, lambda x: x.update(accountNames={"not-hex": "x"})).status_code == 422


def test_asset_names_are_strict(hub):
    _, c = hub
    assert c.delete("/api/assets/..%2Fconfig.json").status_code == 404
    assert c.delete("/api/assets/abc.png").status_code == 404
    assert c.get("/assets/0123456789abcdef.svg").status_code == 404


# ---------- 롱폴링 /api/outbox/wait ----------
# 기다리는 요청과 넣는 요청이 한 이벤트 루프에서 동시에 돌아야 해서, 동시성 시험은 httpx.AsyncClient(ASGI)로
# asyncio.run 안에서 한다. TestClient(별도 루프)와 섞으면 hub.queued 가 두 루프에 걸리므로 넣기·기다리기는 한쪽만 쓴다.

def _ready(c, host="mac", sids=("s1",)):
    """메시지 켜기 + 그 컴퓨터 세션을 받을 수 있게 올려 둔다."""
    _messaging_on(c)
    agents = [agent(s, canMessage=True) for s in sids]
    assert c.post("/api/ingest", json={"host": host, "agents": agents}, headers=AUTH).status_code == 200


def _aclient(mod):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=mod.app), base_url="http://hub", headers=AUTH)


class FakeRequest:
    """outbox_wait 를 직접 부를 때 쓰는 가짜 요청. limit 번 넘게 물으면 '안 끝나는 고리'로 보고 멈춘다."""

    def __init__(self, disconnected=False, limit=200):
        self.disconnected, self.limit, self.calls = disconnected, limit, 0

    async def is_disconnected(self):
        self.calls += 1
        if self.calls > self.limit:
            raise RuntimeError("outbox_wait 가 끝나지 않고 계속 돈다")
        await asyncio.sleep(0)
        return self.disconnected


def test_wait_default_and_cap_are_25s(authed):
    mod, _ = authed
    assert mod.WAIT_MAX_SEC == 25 and mod.Wait(host="h").timeout == 25


def test_wait_returns_already_queued_message_at_once(authed):
    mod, c = authed
    _ready(c)
    mid = c.post("/api/sessions/message", json=MSG, headers=AUTH).json()["id"]
    t0 = time.monotonic()
    r = c.post("/api/outbox/wait", json={"host": "mac", "timeout": 25}, headers=AUTH)
    assert time.monotonic() - t0 < 2
    assert r.status_code == 200 and r.json() == {"messages": [{"id": mid, "session": "s1", "text": MSG["text"]}]}
    assert c.get("/api/state").json()["messages"][0]["status"] == "sending"
    # 한 번 가져간 것은 다시 오지 않는다
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0}, headers=AUTH).json() == {"messages": []}


def test_wait_wakes_as_soon_as_message_is_queued(authed):
    mod, c = authed
    _ready(c)

    async def go():
        async with _aclient(mod) as ac:
            waiter = asyncio.create_task(ac.post("/api/outbox/wait", json={"host": "mac", "timeout": 10}))
            await asyncio.sleep(0.2)
            assert not waiter.done()                       # 큐가 비어 있으면 기다린다
            t0 = time.monotonic()
            mid = (await ac.post("/api/sessions/message", json=MSG)).json()["id"]
            r = await asyncio.wait_for(waiter, 3)
            return mid, r, time.monotonic() - t0

    mid, r, took = asyncio.run(go())
    assert took < 1.0                                       # 5초 주기 확인을 기다리지 않고 바로 깨어난다
    assert r.status_code == 200 and [m["id"] for m in r.json()["messages"]] == [mid]
    assert mod.hub.outbox[0]["status"] == "sending"


def test_wait_ignores_messages_for_other_hosts(authed):
    mod, c = authed
    _ready(c)

    async def go():
        async with _aclient(mod) as ac:
            other = asyncio.create_task(ac.post("/api/outbox/wait", json={"host": "pc", "timeout": 0.6}))
            await asyncio.sleep(0.1)
            await ac.post("/api/sessions/message", json=MSG)
            return await asyncio.wait_for(other, 3)

    assert asyncio.run(go()).json() == {"messages": []}
    assert mod.hub.outbox[0]["status"] == "queued"        # mac 앞 메시지는 그대로 남는다


def test_two_waiters_same_host_get_message_once(authed):
    mod, c = authed
    _ready(c)

    async def go():
        async with _aclient(mod) as ac:
            ws = [asyncio.create_task(ac.post("/api/outbox/wait", json={"host": "mac", "timeout": 0.8}))
                  for _ in range(2)]
            await asyncio.sleep(0.1)
            await ac.post("/api/sessions/message", json=MSG)
            return [r.json()["messages"] for r in await asyncio.wait_for(asyncio.gather(*ws), 3)]

    got = asyncio.run(go())
    assert sorted(len(m) for m in got) == [0, 1]


def test_wait_times_out_empty(authed):
    _, c = authed
    _ready(c)
    t0 = time.monotonic()
    r = c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0.3}, headers=AUTH)
    took = time.monotonic() - t0
    assert r.status_code == 200 and r.json() == {"messages": []}
    assert 0.25 <= took < 2


@pytest.mark.parametrize("timeout", [0, -5])
def test_wait_zero_or_negative_timeout_returns_at_once(authed, timeout):
    _, c = authed
    _ready(c)
    t0 = time.monotonic()
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": timeout}, headers=AUTH).json() == {"messages": []}
    assert time.monotonic() - t0 < 1


def test_wait_timeout_is_capped(authed, monkeypatch):
    mod, c = authed
    _ready(c)
    monkeypatch.setattr(mod, "WAIT_MAX_SEC", 0.3)         # 상한(실제 25초)을 줄여 '999초를 달라 해도 상한에서 끊김'을 본다
    t0 = time.monotonic()
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": 999}, headers=AUTH).json() == {"messages": []}
    assert time.monotonic() - t0 < 2


def test_wait_needs_token(authed):
    _, c = authed
    _ready(c)
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0}).status_code == 401
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0},
                  headers={"X-Office-Token": "wrong"}).status_code == 401


def test_wait_messaging_off_is_403(authed):
    _, c = authed
    r = c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0}, headers=AUTH)
    assert r.status_code == 403 and "꺼져" in r.json()["detail"]


def test_wait_without_hub_token_is_403(hub):
    _, c = hub
    _put(c, lambda cfg: cfg.update(messaging=True))
    r = c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0})
    assert r.status_code == 403 and "OFFICE_TOKEN" in r.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"host": ""}, {"host": "x" * 41}, {"host": "mac", "timeout": "soon"}])
def test_wait_rejects_bad_body(authed, body):
    _, c = authed
    _ready(c)
    assert c.post("/api/outbox/wait", json=body, headers=AUTH).status_code == 422


def test_wait_disconnected_client_does_not_take_message(authed):
    mod, c = authed
    _ready(c)
    c.post("/api/sessions/message", json=MSG, headers=AUTH)
    out = asyncio.run(mod.outbox_wait(mod.Wait(host="mac", timeout=1), FakeRequest(disconnected=True)))
    assert out == {"messages": []}
    assert mod.hub.outbox[0]["status"] == "queued"        # 다음 연결이 받도록 남긴다
    assert len(c.post("/api/outbox/wait", json={"host": "mac", "timeout": 0}, headers=AUTH).json()["messages"]) == 1


def test_wait_releases_condition_after_timeout(authed):
    """시간이 다 된 대기자가 Condition 에 남지 않는다(누수 없음)."""
    mod, c = authed
    _ready(c)

    async def go():
        async with _aclient(mod) as ac:
            await asyncio.gather(*[ac.post("/api/outbox/wait", json={"host": f"h{i}", "timeout": 0.2}) for i in range(5)])
        return len(mod.hub.queued._waiters), mod.hub.queued.locked()

    assert asyncio.run(go()) == (0, False)


@pytest.mark.parametrize("raw,ok", [(b'{"host":"mac","timeout":NaN}', True), (b'{"host":"mac","timeout":-Infinity}', True),
                                    (b'{"host":"mac","timeout":"nan"}', False), (b'{"host":"mac","timeout":"5"}', False),
                                    (b'{"host":"mac","timeout":true}', False)])
def test_wait_non_finite_returns_at_once_and_non_number_is_422(authed, raw, ok):
    """NaN 이면 deadline 비교가 늘 거짓이라 끝없이 돌았다(T4 검토). NaN·-무한은 0 으로 바꿔 바로 빈 응답, 숫자가 아니면 422."""
    _, c = authed
    _ready(c)
    t0 = time.monotonic()
    r = c.post("/api/outbox/wait", content=raw, headers={**AUTH, "Content-Type": "application/json"})
    assert time.monotonic() - t0 < 2
    if ok:
        assert r.status_code == 200 and r.json() == {"messages": []}
    else:
        assert r.status_code == 422


def test_wait_infinity_is_capped(authed, monkeypatch):
    mod, c = authed
    _ready(c)
    assert mod.Wait(host="h", timeout=float("inf")).timeout == 25
    monkeypatch.setattr(mod, "WAIT_MAX_SEC", 0.2)
    t0 = time.monotonic()
    r = c.post("/api/outbox/wait", content=b'{"host":"mac","timeout":Infinity}',
               headers={**AUTH, "Content-Type": "application/json"})
    assert r.json() == {"messages": []} and time.monotonic() - t0 < 2


def test_wait_nan_timeout_returns_even_past_validation(authed):
    """검증을 거치지 않고 NaN 이 들어와도(직접 호출) 돌지 않고 바로 끝난다."""
    mod, c = authed
    _ready(c)
    p = mod.Wait.model_construct(host="mac", timeout=float("nan"))
    req = FakeRequest()
    assert asyncio.run(mod.outbox_wait(p, req)) == {"messages": []}
    assert req.calls == 1


def test_wait_huge_timeout_is_capped(authed, monkeypatch):
    mod, c = authed
    _ready(c)
    monkeypatch.setattr(mod, "WAIT_MAX_SEC", 0.2)
    t0 = time.monotonic()
    assert c.post("/api/outbox/wait", json={"host": "mac", "timeout": 1e308}, headers=AUTH).json() == {"messages": []}
    assert time.monotonic() - t0 < 2


# 실제 소켓으로 '끊긴 연결'을 만들려면 진짜 서버가 있어야 한다(ASGITransport 는 연결을 끊지 못한다).

@pytest.fixture
def live_hub(authed):
    import uvicorn

    mod, c = authed
    _ready(c)
    server = uvicorn.Server(uvicorn.Config(mod.app, host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started
    port = server.servers[0].sockets[0].getsockname()[1]
    yield mod, f"http://127.0.0.1:{port}", port
    server.should_exit = True
    th.join(5)


def test_wait_client_gone_before_message_leaves_it_queued(live_hub):
    mod, base, port = live_hub
    body = json.dumps({"host": "mac", "timeout": 3}).encode()
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(b"POST /api/outbox/wait HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
              + f"X-Office-Token: {TOKEN}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
    time.sleep(0.3)
    s.close()                                               # 수집기가 기다리다 끊음
    time.sleep(0.2)
    with httpx.Client(base_url=base, headers=AUTH, timeout=5) as hc:
        assert hc.post("/api/sessions/message", json=MSG).status_code == 200
        time.sleep(0.4)                                     # 끊긴 대기자가 깨어나 끊김을 확인할 시간
        assert hc.get("/api/state").json()["messages"][0]["status"] == "queued"
        got = hc.post("/api/outbox/wait", json={"host": "mac", "timeout": 2}).json()["messages"]
    assert len(got) == 1                                    # 다음 연결이 받는다


# ---------- 떠남 /api/hosts/bye ----------

def test_bye_marks_host_offline_at_once(authed):
    mod, c = authed
    c.post("/api/ingest", json={"host": "mac", "agents": [agent()]}, headers=AUTH)
    v = c.get("/health").json()["version"]
    assert c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH).json() == {"ok": True}
    s = c.get("/api/state").json()
    assert s["hosts"][0]["online"] is False and s["hosts"][0]["age"] < 5
    assert s["agents"] == [] and s["version"] == v + 1


def test_bye_again_or_unknown_host_does_not_bump(authed):
    _, c = authed
    c.post("/api/ingest", json={"host": "mac", "agents": [agent()]}, headers=AUTH)
    c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH)
    v = c.get("/health").json()["version"]
    assert c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH).status_code == 200
    assert c.post("/api/hosts/bye", json={"host": "nobody"}, headers=AUTH).status_code == 200
    assert c.get("/health").json()["version"] == v
    assert [h["host"] for h in c.get("/api/state").json()["hosts"]] == ["mac"]


def test_ingest_after_bye_recovers(authed):
    _, c = authed
    body = {"host": "mac", "agents": [agent()]}
    c.post("/api/ingest", json=body, headers=AUTH)
    c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH)
    v = c.get("/health").json()["version"]
    c.post("/api/ingest", json=body, headers=AUTH)          # 같은 내용이어도 떠났다 돌아온 것은 알린다
    s = c.get("/api/state").json()
    assert s["hosts"][0]["online"] is True and len(s["agents"]) == 1 and s["version"] == v + 1


def test_bye_needs_token(authed):
    _, c = authed
    c.post("/api/ingest", json={"host": "mac", "agents": [agent()]}, headers=AUTH)
    assert c.post("/api/hosts/bye", json={"host": "mac"}).status_code == 401
    assert c.post("/api/hosts/bye", json={"host": "mac"}, headers={"X-Office-Token": "no"}).status_code == 401
    assert c.get("/api/state").json()["hosts"][0]["online"] is True


@pytest.mark.parametrize("body", [{}, {"host": ""}, {"host": "x" * 41}])
def test_bye_rejects_bad_body(authed, body):
    _, c = authed
    assert c.post("/api/hosts/bye", json=body, headers=AUTH).status_code == 422


def test_bye_blocks_new_messages_until_back(authed):
    _, c = authed
    _ready(c)
    c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH)
    assert c.post("/api/sessions/message", json=MSG, headers=AUTH).status_code == 404
    _ready(c)
    assert c.post("/api/sessions/message", json=MSG, headers=AUTH).status_code == 200


def test_expire_loop_keeps_bye_host_offline(authed):
    """5초 주기 점검도 '떠남' 표시를 존중한다(30초 안이라도 다시 온라인으로 바꾸지 않는다)."""
    mod, c = authed
    c.post("/api/ingest", json={"host": "mac", "agents": [agent()]}, headers=AUTH)
    c.post("/api/hosts/bye", json={"host": "mac"}, headers=AUTH)
    h = mod.hub.hosts["mac"]
    assert mod.Hub.online(h, time.time()) is False
    assert mod.Hub.online({"receivedAt": time.time()}, time.time()) is True
    assert mod.Hub.online({"receivedAt": time.time() - mod.HOST_STALE_SEC - 1}, time.time()) is False


# ---------- 정상 종료: 열린 SSE·롱폴링이 종료를 막지 않는다 ----------
# uvicorn 은 열린 연결이 다 끝난 뒤에야 lifespan 종료를 부른다. 그래서 종료 신호 단계에서 hub.close() 로 깨운다.

def test_close_ends_open_sse_stream(hub):
    mod, _ = hub

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mod.app), base_url="http://hub") as ac:
            stream = asyncio.create_task(ac.get("/api/stream"))   # ASGITransport 는 응답이 끝나야 돌려준다
            await asyncio.sleep(0.2)
            assert not stream.done()
            await mod.hub.close()
            return await asyncio.wait_for(stream, 2)

    r = asyncio.run(go())
    assert r.status_code == 200 and r.text.startswith("data: ")


def test_close_ends_pending_wait_and_new_waits(authed):
    mod, c = authed
    _ready(c)

    async def go():
        async with _aclient(mod) as ac:
            w = asyncio.create_task(ac.post("/api/outbox/wait", json={"host": "mac", "timeout": 20}))
            await asyncio.sleep(0.2)
            t0 = time.monotonic()
            await mod.hub.close()
            r = await asyncio.wait_for(w, 2)
            again = await ac.post("/api/outbox/wait", json={"host": "mac", "timeout": 20})
            return r, again, time.monotonic() - t0

    r, again, took = asyncio.run(go())
    assert r.json() == {"messages": []} and again.json() == {"messages": []} and took < 1


def test_close_still_hands_over_queued_message(authed):
    """끝나는 중이라도 이미 쌓인 메시지는 그대로 가져가게 한다(응답 형식 유지)."""
    mod, c = authed
    _ready(c)
    c.post("/api/sessions/message", json=MSG, headers=AUTH)

    async def go():
        await mod.hub.close()
        async with _aclient(mod) as ac:
            return (await ac.post("/api/outbox/wait", json={"host": "mac", "timeout": 20})).json()

    assert len(asyncio.run(go())["messages"]) == 1


def test_lifespan_exit_marks_closing(make_hub):
    mod, c = make_hub()
    assert mod.hub.closing is False
    c.__exit__(None, None, None)
    assert mod.hub.closing is True


def test_exit_signal_hook_wakes_hub_and_calls_previous_handler(hub):
    mod, _ = hub
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    called = []
    try:
        for s in saved:
            signal.signal(s, lambda signum, frame: called.append(signum))   # uvicorn 의 handle_exit 자리

        async def go():
            hooked = mod._hook_exit_signals(asyncio.get_running_loop())
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)       # 신호가 온 것처럼 처리기를 부른다
            await asyncio.sleep(0.05)
            return hooked

        hooked = asyncio.run(go())
    finally:
        for s, h in saved.items():
            signal.signal(s, h)
    assert {"SIGTERM", "SIGINT"} <= set(hooked)
    assert called == [signal.SIGTERM] and mod.hub.closing is True


def test_exit_signal_hook_skips_off_main_thread(hub):
    mod, _ = hub
    out = []
    th = threading.Thread(target=lambda: out.append(mod._hook_exit_signals(asyncio.new_event_loop())))
    th.start()
    th.join(5)
    assert out == [[]]


# ---------- 바뀐 것만 받기·보내기 ----------

def test_patch_applies_set_del_order(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [agent("a"), agent("b"), agent("c")], "seq": 1})
    v = mod.hub.version
    r = c.post("/api/ingest/patch", json={"host": "m", "base": 1, "seq": 2, "set": [agent("b", kind="working"), agent("d")],
                                          "del": ["c"], "order": ["d", "a", "b"]})
    assert r.json() == {"ok": True}
    agents = c.get("/api/state").json()["agents"]
    assert [a["id"] for a in agents] == ["d", "a", "b"]
    assert agents[2]["kind"] == "working"
    assert mod.hub.version > v and mod.hub.hosts["m"]["seq"] == 2


def test_patch_with_nothing_changed_keeps_host_alive_without_bump(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [agent("a")], "seq": 5})
    v, t = mod.hub.version, mod.hub.hosts["m"]["receivedAt"]
    time.sleep(0.01)
    assert c.post("/api/ingest/patch", json={"host": "m", "base": 5, "seq": 6, "set": [], "del": [], "order": ["a"]}).json()["ok"]
    assert mod.hub.version == v and mod.hub.hosts["m"]["receivedAt"] > t


@pytest.mark.parametrize("first", [None, {"seq": None}, {"seq": 3}])
def test_patch_needs_matching_base_else_resync(hub, first):
    mod, c = hub
    if first is not None:
        body = {"host": "m", "agents": [agent("a")]}
        if first["seq"] is not None:
            body["seq"] = first["seq"]
        c.post("/api/ingest", json=body)
    r = c.post("/api/ingest/patch", json={"host": "m", "base": 1, "seq": 2, "set": [], "del": [], "order": ["a"]})
    assert r.json() == {"ok": False, "resync": True}


def test_patch_after_bye_asks_resync(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [agent("a")], "seq": 1})
    c.post("/api/hosts/bye", json={"host": "m"})
    assert c.post("/api/ingest/patch", json={"host": "m", "base": 1, "seq": 2, "set": [], "del": [], "order": ["a"]}).json()["resync"]


@pytest.mark.parametrize("bad", [{"set": "x"}, {"set": [{"no": "id"}]}, {"order": None}, {"del": {"x": 1}}])
def test_patch_rejects_bad_shape(hub, bad):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [agent("a")], "seq": 1})
    body = {"host": "m", "base": 1, "seq": 2, "set": [], "del": [], "order": ["a"], **bad}
    assert c.post("/api/ingest/patch", json=body).status_code == 400


def test_patch_needs_token(authed):
    mod, c = authed
    assert c.post("/api/ingest/patch", json={"host": "m"}).status_code == 401


def test_sse_patch_only_carries_changes(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [agent("a"), agent("b")], "seq": 1})
    s1 = mod.hub.snapshot()
    sent = mod._sent_view(s1)
    c.post("/api/ingest/patch", json={"host": "m", "base": 1, "seq": 2, "set": [agent("b", kind="working"), agent("c")],
                                      "del": ["a"], "order": ["b", "c"]})
    p = mod._patch(sent, mod.hub.snapshot())
    assert [a["id"] for a in p["set"]] == ["b", "c"]
    assert p["del"] == ["m/a"] and p["order"] == ["m/b", "m/c"]
    assert "config" not in p and "messages" not in p and p["hosts"][0]["host"] == "m"
    # 아무것도 안 바뀌면 set·del 이 비고 order 도 없다
    snap = mod.hub.snapshot()
    p2 = mod._patch(mod._sent_view(snap), snap)
    assert p2["set"] == [] and p2["del"] == [] and "order" not in p2


# ---------- 대시보드에서 승인 ----------

APPR = {"host": "mac", "session": "s1", "toolUseId": "tu1", "tool": "Bash", "preview": "rm -rf build"}


def _approvals_on(c):
    cfg = c.get("/api/config").json()
    cfg["approvals"] = True
    assert c.put("/api/config", json=cfg, headers=AUTH).status_code == 200


def test_approval_needs_token_and_toggle(hub, authed):
    _, c0 = hub
    assert c0.post("/api/approvals", json=APPR).status_code == 403          # 허브 토큰 없음
    _, c = authed
    assert c.post("/api/approvals", json=APPR).status_code == 401           # 쓰기 토큰
    assert c.post("/api/approvals", json=APPR, headers=AUTH).status_code == 403   # 관리 화면 꺼짐
    assert c.get("/api/state").json()["approvalsReady"] is False


def test_approval_flow_allow(authed):
    mod, c = authed
    _approvals_on(c)
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", kind="approval")]}, headers=AUTH)
    aid = c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"]
    assert c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"] == aid      # 같은 도구 호출은 한 요청
    st = c.get("/api/state").json()
    assert st["approvalsReady"] is True
    assert st["approvals"] == [{"id": aid, "host": "mac", "session": "s1", "tool": "Bash",
                                "createdAt": st["approvals"][0]["createdAt"], "status": "pending"}]   # 미리보기는 안 보인다
    assert c.get(f"/api/approvals/{aid}").status_code == 401
    assert c.get(f"/api/approvals/{aid}", headers=AUTH).json()["preview"] == "rm -rf build"
    assert c.post("/api/approvals/wait", json={"id": aid, "timeout": 0}, headers=AUTH).json() == {"status": "pending"}
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "allow"}).status_code == 401
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "allow"}, headers=AUTH).json()["status"] == "allow"
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "deny"}, headers=AUTH).status_code == 409
    assert c.post("/api/approvals/wait", json={"id": aid, "timeout": 5}, headers=AUTH).json() == {"status": "allow"}
    assert c.get("/api/state").json()["approvals"] == []


def test_approval_bad_decision_and_unknown(authed):
    mod, c = authed
    _approvals_on(c)
    assert c.post("/api/approvals/zzz/decide", json={"decision": "allow"}, headers=AUTH).status_code == 404
    aid = c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"]
    assert c.post(f"/api/approvals/{aid}/decide", json={"decision": "maybe"}, headers=AUTH).status_code == 422
    assert c.post("/api/approvals/wait", json={"id": "nope", "timeout": 0}, headers=AUTH).json() == {"status": "gone"}


def test_approval_wait_wakes_on_decision(authed):
    mod, c = authed
    _approvals_on(c)
    aid = c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"]
    out = {}
    t = threading.Thread(target=lambda: out.update(c.post("/api/approvals/wait", json={"id": aid, "timeout": 20}, headers=AUTH).json()))
    t.start()
    time.sleep(0.3)
    started = time.time()
    c.post(f"/api/approvals/{aid}/decide", json={"decision": "deny"}, headers=AUTH)
    t.join(10)
    assert out == {"status": "deny"} and time.time() - started < 5


def test_settle_marks_gone_when_session_no_longer_waits(authed):
    mod, c = authed
    _approvals_on(c)
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", kind="approval")]}, headers=AUTH)
    aid = c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"]
    x = mod.hub.approvals[aid]
    now = x["createdAt"] + 20
    assert mod._settle_approvals(now) is False                       # 아직 승인 대기 중
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", kind="working")]}, headers=AUTH)   # 터미널에서 답함
    assert mod._settle_approvals(now) is False                       # 바로 거두지 않고 잠깐 본다
    assert mod._settle_approvals(now + mod.APPROVAL_GONE_SEC) is True
    assert x["status"] == "gone"


def test_settle_grace_and_ttl(authed):
    mod, c = authed
    _approvals_on(c)
    aid = c.post("/api/approvals", json=APPR, headers=AUTH).json()["id"]   # 수집기가 아직 못 봄(세션 없음)
    x = mod.hub.approvals[aid]
    assert mod._settle_approvals(x["createdAt"] + 1) is False and x["status"] == "pending"
    c.post("/api/ingest", json={"host": "mac", "agents": [agent("s1", kind="approval")]}, headers=AUTH)
    assert mod._settle_approvals(x["createdAt"] + mod.APPROVAL_TTL_SEC + 1) is True and x["status"] == "gone"


def test_patch_carries_approvals(authed):
    mod, c = authed
    _approvals_on(c)
    snap = mod.hub.snapshot()
    sent = mod._sent_view(snap)
    c.post("/api/approvals", json=APPR, headers=AUTH)
    p = mod._patch(sent, mod.hub.snapshot())
    assert len(p["approvals"]) == 1 and "preview" not in p["approvals"][0]


def test_meta_setup_is_sanitized(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "m", "agents": [], "meta": {"checklistRule": True, "setup": {
        "os": "mac", "roots": 3, "hooks": True, "approveHook": 999, "statusline": "2", "todoTools": 1,
        "messagesEnv": 1, "approveEnv": False, "path": "/Users/x", "evil": {"a": 1}}}})
    h = c.get("/api/state").json()["hosts"][0]
    assert h["setup"] == {"os": "mac", "roots": 3, "approveHook": 99, "todoTools": 1, "messagesEnv": True, "approveEnv": False}
    c.post("/api/ingest", json={"host": "w", "agents": [], "meta": {"setup": {"os": "solaris"}}})
    assert "os" not in [x for x in c.get("/api/state").json()["hosts"] if x["host"] == "w"][0]["setup"]


def test_meta_roots_detail_is_sanitized(hub):
    mod, c = hub
    rows = [{"label": "~/.claude", "hooks": 1, "approveHook": False, "statusline": True, "todoTools": None, "secret": "x"}, "bad"] + \
        [{"label": f"~/p{i}"} for i in range(20)]
    c.post("/api/ingest", json={"host": "m", "agents": [], "meta": {"setup": {"rootsDetail": rows}}})
    rd = c.get("/api/state").json()["hosts"][0]["setup"]["rootsDetail"]
    assert rd[0] == {"label": "~/.claude", "hooks": True, "approveHook": False, "statusline": True, "todoTools": False, "rule": False}
    assert len(rd) == 19   # 앞 20개 중 dict 만


def test_meta_setup_keeps_repo_and_python(hub):
    mod, c = hub
    c.post("/api/ingest", json={"host": "w", "agents": [], "meta": {"setup": {
        "os": "windows", "repo": "D:/01_Developer/claude-office", "python": "~/AppData/Local/anaconda3/python.exe", "junk": "x"}}})
    su = c.get("/api/state").json()["hosts"][0]["setup"]
    assert su["repo"] == "D:/01_Developer/claude-office" and su["python"] == "~/AppData/Local/anaconda3/python.exe" and "junk" not in su
