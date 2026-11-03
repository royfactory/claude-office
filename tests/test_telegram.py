"""텔레그램 다리(hub/tgbridge.py)와 허브 연결 시험. 텔레그램 API 는 가짜(FakeTg)로 바꾼다."""
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from conftest import HUB_PY, load_module  # noqa: E402

TOKEN = "test-token"
AUTH = {"X-Office-Token": TOKEN}
CHAT = 777001


class FakeTg:
    def __init__(self):
        self.calls, self.n = [], 100

    def __call__(self, method, params):
        self.calls.append((method, params))
        if method == "sendMessage":
            self.n += 1
            return {"message_id": self.n}
        if method == "getMe":
            return {"username": "office_bot"}
        return True

    def sent(self, chat=CHAT):
        return [p["text"] for m, p in self.calls if m == "sendMessage" and p["chat_id"] == chat]

    def last(self, method):
        return next(p for m, p in reversed(self.calls) if m == method)


@pytest.fixture
def tgh(home, tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OFFICE_TOKEN", TOKEN)
    monkeypatch.setenv("OFFICE_TELEGRAM_TOKEN", "")   # 폴링 스레드는 띄우지 않는다(빈 값이라야 .env 가 채우지 않는다)
    mod = load_module("office_hub_app_tg", HUB_PY)
    c = TestClient(mod.app)
    c.__enter__()
    fake = FakeTg()
    mod.tg.token, mod.tg.call, mod.tg.inline, mod.tg.bot = "123:abc", fake, True, "office_bot"
    mod.hub.config["messaging"] = True
    yield mod, c, fake
    c.__exit__(None, None, None)


def msg(text, chat=CHAT, kind="private", reply_to=None, mid=1):
    m = {"message_id": mid, "chat": {"id": chat, "type": kind}, "from": {"first_name": "로이"}, "text": text}
    if reply_to:
        m["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": mid, "message": m}


def handle(mod, c, update):
    c.portal.call(mod.tg.handle, update)


def link(mod, c):
    code = c.post("/api/telegram/pair", headers=AUTH).json()["code"]
    handle(mod, c, msg(f"/start {code}"))
    return mod.tg.data["links"][0]


def agent(sid="s1", **kw):
    return {"id": sid, "name": "n", "project": "proj", "title": "제목", "kind": "idle", "canMessage": True, **kw}


def ingest(c, *agents, host="mac"):
    return c.post("/api/ingest", json={"host": host, "agents": list(agents)}, headers=AUTH).json()


# ---------- 연결 ----------

def test_pair_code_links_private_chat_and_state_hides_chat_id(tgh):
    mod, c, fake = tgh
    assert c.post("/api/telegram/pair").status_code == 401            # 쓰기 토큰 필요
    lk = link(mod, c)
    assert lk["name"] == "로이" and lk["chat"] == CHAT and "연결했습니다" in fake.sent()[-1]
    st = c.get("/api/state").json()["telegram"]
    assert st["enabled"] and st["bot"] == "office_bot" and st["links"][0]["name"] == "로이"
    assert str(CHAT) not in json.dumps(st)                             # 채팅 id 원문은 공개 상태에 없다
    saved = json.loads((mod.DATA / "telegram.json").read_text())
    assert saved["links"][0]["chat"] == CHAT


def test_wrong_or_used_code_and_group_chat_are_refused(tgh):
    mod, c, fake = tgh
    code = c.post("/api/telegram/pair", headers=AUTH).json()["code"]
    handle(mod, c, msg(code, chat=5, kind="group"))
    assert not mod.tg.data["links"] and "개인 채팅" in fake.sent(5)[-1]
    handle(mod, c, msg("000000" if code != "000000" else "111111", chat=6))
    handle(mod, c, msg("hello", chat=6))
    assert not mod.tg.data["links"] and len(fake.sent(6)) == 1         # 모르는 채팅 안내는 가끔만


def test_disabled_without_token(make_hub_free):
    mod, c = make_hub_free
    assert c.get("/api/state").json()["telegram"] == {"enabled": False}
    assert c.post("/api/telegram/pair", headers=AUTH).status_code == 404


@pytest.fixture
def make_hub_free(home, tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("OFFICE_TOKEN", TOKEN)
    monkeypatch.setenv("OFFICE_TELEGRAM_TOKEN", "")
    mod = load_module("office_hub_app_tg0", HUB_PY)
    c = TestClient(mod.app)
    c.__enter__()
    yield mod, c
    c.__exit__(None, None, None)


# ---------- 세션 하나를 텔레그램으로 ----------

def test_status_use_and_text_goes_to_bound_session(tgh):
    mod, c, fake = tgh
    link(mod, c)
    ingest(c, agent("s1", kind="working", title="일하는 세션"), agent("s2"))
    handle(mod, c, msg("/status", mid=2))
    assert "1. proj · 일하는 세션 · 근무" in fake.sent()[-1]
    handle(mod, c, msg("/use 1", mid=3))
    assert mod.tg.data["links"][0]["bind"]["session"] == "s1" and "일하는 세션" in fake.sent()[-1]
    handle(mod, c, msg("테스트 돌려줘", mid=4))
    m = mod.hub.outbox[-1]
    assert m["session"] == "s1" and m["via"] == "telegram" and m["text"] == "테스트 돌려줘"
    pulled = c.post("/api/outbox/pull", json={"host": "mac"}, headers=AUTH).json()["messages"]
    assert pulled[0]["via"] == "telegram"                               # 수집기가 머리말을 고른다
    c.post("/api/outbox/result", json={"host": "mac", "id": m["id"], "ok": True}, headers=AUTH)
    assert fake.last("setMessageReaction")["reaction"][0]["emoji"] == "👌"


def test_text_without_bound_session_or_messaging_off_explains(tgh):
    mod, c, fake = tgh
    link(mod, c)
    ingest(c, agent("s1"))
    handle(mod, c, msg("안녕", mid=2))
    assert "붙인 세션이 없습니다" in fake.sent()[-1]
    handle(mod, c, msg("/use 1", mid=3))
    mod.hub.config["messaging"] = False
    handle(mod, c, msg("안녕", mid=4))
    assert "보내지 못했습니다" in fake.sent()[-1] and not mod.hub.outbox


def test_reply_to_notification_goes_to_that_session(tgh):
    mod, c, fake = tgh
    link(mod, c)
    mod.hub.config["telegram"]["doneSec"] = 0
    ingest(c, agent("s1"), agent("s2"))
    ingest(c, agent("s1"), agent("s2", kind="working"))
    ingest(c, agent("s1"), agent("s2", say="다 했어요"))               # s2 완료 알림
    note = fake.calls[-1][1]
    assert "작업 완료" in note["text"] and "다 했어요" in note["text"]
    handle(mod, c, msg("이어서 커밋해", mid=9, reply_to=fake.n))
    assert mod.hub.outbox[-1]["session"] == "s2"


def test_ingest_reply_carries_relay_and_relay_sends_only_new_replies(tgh):
    mod, c, fake = tgh
    lk = link(mod, c)
    assert "relay" not in ingest(c, agent("s1"))
    c.post("/api/telegram/bind", json={"link": lk["id"], "host": "mac", "session": "s1"}, headers=AUTH)
    r = ingest(c, agent("s1"))
    at = r["relay"]["s1"]
    assert abs(at - time.time()) < 5
    body = {"host": "mac", "session": "s1", "items": [
        {"id": "old", "ts": at - 600, "text": "붙이기 전 답"},
        {"id": "u1", "ts": at + 1, "text": "결과는 이렇습니다\n" + "가" * 5000}]}
    assert c.post("/api/telegram/relay", json=body, headers=AUTH).json()["sent"] == 1
    out = fake.sent()
    assert out[-2].startswith("💬 제목\n결과는") and len(out[-2]) <= 4000 and out[-1].startswith("가")   # 길면 나눈다
    assert c.post("/api/telegram/relay", json=body, headers=AUTH).json()["sent"] == 0    # 같은 답은 한 번만
    assert all("붙이기 전" not in t for t in out)
    st = c.get("/api/state").json()["telegram"]
    assert st["log"][-1]["kind"] == "reply" and len(st["log"][-1]["text"]) <= 80


def test_bind_endpoint_unbind_and_unknown_session(tgh):
    mod, c, fake = tgh
    lk = link(mod, c)
    ingest(c, agent("s1"))
    assert c.post("/api/telegram/bind", json={"link": lk["id"], "host": "mac", "session": "zz"}, headers=AUTH).status_code == 404
    assert c.post("/api/telegram/bind", json={"link": "nope", "host": "mac", "session": "s1"}, headers=AUTH).status_code == 404
    assert c.post("/api/telegram/bind", json={"link": lk["id"], "host": "mac", "session": "s1"}, headers=AUTH).status_code == 200
    assert c.get("/api/state").json()["telegram"]["links"][0]["bind"]["session"] == "s1"
    c.post("/api/telegram/bind", json={"link": lk["id"]}, headers=AUTH)
    assert c.get("/api/state").json()["telegram"]["links"][0]["bind"] is None


# ---------- 알림 ----------

def test_notifications_approval_done_and_first_sight_is_quiet(tgh):
    mod, c, fake = tgh
    link(mod, c)
    n0 = len(fake.sent())
    ingest(c, agent("s1", kind="approval", tool="Bash"))                 # 처음 보는 컴퓨터: 기준만
    assert len(fake.sent()) == n0
    ingest(c, agent("s1", kind="working"))
    ingest(c, agent("s1", kind="approval", tool="Bash", target="npm test"))
    assert "승인 대기 · proj" in fake.sent()[-1] and "Bash · npm test" in fake.sent()[-1]
    ingest(c, agent("s1"))                                               # 방금 시작한 턴 — doneSec(60) 안이라 조용
    assert "작업 완료" not in fake.sent()[-1]
    ingest(c, agent("s1", kind="working"))
    mod.tg.prev["mac/s1"]["activeSince"] -= 120
    ingest(c, agent("s1"))
    assert "작업 완료 · proj (2분)" in fake.sent()[-1]


def test_muted_filtered_and_minimal_detail(tgh):
    mod, c, fake = tgh
    lk = link(mod, c)
    mod.hub.config["telegram"].update(doneSec=0, detail="minimal", notify=["done", "stalled"])
    ingest(c, agent("s1"), host="mac")
    ingest(c, agent("s1", kind="working"), host="mac")
    ingest(c, agent("s1"), host="mac")
    assert fake.sent()[-1].startswith("✅") and "제목" not in fake.sent()[-1]      # minimal: 제목 빼고
    c.put(f"/api/telegram/links/{lk['id']}", json={"hosts": ["pc"]}, headers=AUTH)
    n = len(fake.sent())
    ingest(c, agent("s1", kind="working"), host="mac")
    ingest(c, agent("s1"), host="mac")
    assert len(fake.sent()) == n                                         # 다른 컴퓨터만 받기로
    c.put(f"/api/telegram/links/{lk['id']}", json={"hosts": [], "muted": True}, headers=AUTH)
    ingest(c, agent("s1", kind="thinking", stalled=True), host="mac")
    assert len(fake.sent()) == n


def test_approval_buttons_decide_only_when_enabled(tgh):
    mod, c, fake = tgh
    link(mod, c)
    mod.hub.config["approvals"] = True
    ingest(c, agent("s1", kind="working"))
    aid = c.post("/api/approvals", json={"host": "mac", "session": "s1", "tool": "Bash", "preview": "rm -rf build"}, headers=AUTH).json()["id"]
    ingest(c, agent("s1", kind="approval", tool="Bash"))
    note = fake.last("sendMessage")
    assert "reply_markup" not in note                                    # 텔레그램 승인은 기본 꺼짐
    cb = {"update_id": 50, "callback_query": {"id": "q1", "data": f"ap:{aid}:allow", "message": {"message_id": fake.n, "chat": {"id": CHAT}, "text": note["text"]}}}
    handle(mod, c, cb)
    assert mod.hub.approvals[aid]["status"] == "pending" and "꺼져" in fake.last("answerCallbackQuery")["text"]
    mod.hub.config["telegram"]["approvals"] = True
    ingest(c, agent("s1", kind="working"))
    ingest(c, agent("s1", kind="approval", tool="Bash"))
    note = fake.last("sendMessage")
    btns = note["reply_markup"]["inline_keyboard"][0]
    assert btns[0]["callback_data"] == f"ap:{aid}:allow" and "rm -rf build" in note["text"]
    handle(mod, c, cb)
    assert mod.hub.approvals[aid]["status"] == "allow" and "허용했습니다" in fake.last("editMessageText")["text"]
    other = {"update_id": 51, "callback_query": {"id": "q2", "data": f"ap:{aid}:deny", "message": {"message_id": 1, "chat": {"id": 999}}}}
    handle(mod, c, other)                                                # 연결 안 된 채팅의 단추는 무시
    assert mod.hub.approvals[aid]["status"] == "allow"


def test_commands_mute_stop_unlink(tgh):
    mod, c, fake = tgh
    link(mod, c)
    handle(mod, c, msg("/mute", mid=2))
    assert mod.tg.data["links"][0]["muted"] is True
    handle(mod, c, msg("/unmute", mid=3))
    assert mod.tg.data["links"][0]["muted"] is False
    handle(mod, c, msg("/unlink", mid=4))
    assert mod.tg.data["links"] == []


def test_split_text_prefers_newlines(tgh):
    mod, _, _ = tgh
    parts = mod.tgbridge.split_text("a" * 30 + "\n" + "b" * 30, 40)
    assert parts == ["a" * 30, "b" * 30]


def test_status_puts_ready_sessions_first_and_warns_bypass(tgh):
    mod, c, fake = tgh
    link(mod, c)
    ingest(c, agent("by", kind="working", title="건너뛰기", mode="bypassPermissions"), agent("ok", title="바로 받음", mode="auto"),
           agent("no", title="못 받음", canMessage=False), *[agent(f"x{i}", title=f"쉼{i}", mode="auto") for i in range(15)])
    handle(mod, c, msg("/status", mid=2))
    out = fake.sent()[-1].split("\n")
    assert "바로 받음" in out[1] and "쉼" not in out[1] or "바로 받음" in out[1]
    assert not any("⚠" in l or "🚫" in l for l in out[1:13] if "쉼" in l or "바로 받음" in l)
    assert "… 외 6개" in fake.sent()[-1] and "건너뛰기" not in fake.sent()[-1]     # 12개만, 바로 받는 세션부터
    handle(mod, c, msg("/status all", mid=3))
    full = fake.sent()[-1]
    assert "건너뛰기 · 근무 ⚠" in full and "못 받음" in full and "🚫" in full and "권한 건너뛰기 모드" in full
    n = [l for l in full.split("\n") if "건너뛰기 · 근무" in l][0].split(".")[0]
    handle(mod, c, msg(f"/use {n}", mid=4))
    assert mod.tg.data["links"][0]["bind"]["session"] == "by" and "crossSessionInbound" in fake.sent()[-1]


def test_use_number_only_from_shown_list(tgh):
    mod, c, fake = tgh
    link(mod, c)
    ingest(c, *[agent(f"x{i:02d}", title=f"쉼{i:02d}", mode="auto", lastActivity=1000 - i) for i in range(15)])
    handle(mod, c, msg("/status", mid=2))
    assert "쉼00 · 휴식 · " in fake.sent()[-1]
    handle(mod, c, msg("/use 14", mid=3))                             # 12개만 보였으니 14번은 없다
    assert mod.tg.data["links"][0]["bind"] is None and "/status all" in fake.sent()[-1]
    handle(mod, c, msg("/status all", mid=4))
    handle(mod, c, msg("/use 14", mid=5))
    assert mod.tg.data["links"][0]["bind"]["session"] == "x13"
