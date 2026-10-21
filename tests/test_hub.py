"""hub/app.py 테스트(FastAPI TestClient). 허브 의존성(hub/requirements.txt)과 httpx 가 있어야 돈다."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
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
    assert r.status_code == 200 and r.json() == mod.default_config()
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


def test_asset_names_are_strict(hub):
    _, c = hub
    assert c.delete("/api/assets/..%2Fconfig.json").status_code == 404
    assert c.delete("/api/assets/abc.png").status_code == 404
    assert c.get("/assets/0123456789abcdef.svg").status_code == 404
