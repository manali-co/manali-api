import os

os.environ["MANALI_ENV"] = "test"
os.environ["MANALI_API_KEY"] = "test-key-test-key-test-key-test-key"
os.environ["MANALI_ADMIN_KEY"] = "admin-key-admin-key-admin-key-admin"
os.environ["MANALI_TOKEN_SECRET"] = "test-secret-test-secret-test-secret-test"
os.environ["MANALI_SITE_URL"] = "https://example.test"
os.environ["MANALI_NOTIFY_EMAIL"] = "owner@example.test"

from fastapi.testclient import TestClient  # noqa: E402

from manali_api import mail, reactions, replies, store  # noqa: E402
from manali_api.app import app  # noqa: E402

H = {"x-api-key": os.environ["MANALI_API_KEY"]}
A = {**H, "x-admin-key": os.environ["MANALI_ADMIN_KEY"]}


def setup_function() -> None:
    store._store = store.MemoryStore()
    mail._mailer = mail.MemoryMailer()
    reactions._store = reactions.MemoryReactions()
    replies._store = replies.MemoryReplies()


def test_subscribe_confirm_announce_unsubscribe() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "A@Example.com"}, headers=H).status_code == 202
    mailer = mail.get_mailer()
    assert mailer.sent[-1][1].startswith("Confirm")
    assert "/confirm/?token=" in mailer.sent[-1][2]
    token = store.get_store().get("a@example.com").confirm_token
    # a scanner's GET does nothing; only the site's POST confirms
    assert c.get(f"/confirm?token={token}", headers=H).status_code == 405
    assert c.post("/confirm", json={"token": token}, headers=H).json() == {"ok": True}
    assert mailer.sent[-1][1] == "You're in"
    assert c.post("/confirm", json={"token": token}, headers=H).json() == {"ok": False}  # token is single-use
    assert c.get("/admin/stats", headers=A).json()["subscribers"] == 1
    # subscribing again is a quiet 202, not a membership oracle
    assert c.post("/subscribe", json={"email": "a@example.com"}, headers=H).status_code == 202
    assert mailer.sent[-1][1] == "You're in"  # nothing new was sent
    post = {"slug": "hello", "title": "Hello", "summary": "First.", "url": "https://example.test/blog/hello/", "author": "Ayush"}
    assert c.post("/admin/announce", json=post, headers=A).json() == {"recipients": 1, "subscribers": 1}
    assert "Unsubscribe" in mailer.sent[-1][2]
    assert c.post("/admin/announce", json=post, headers=A).status_code == 409  # already announced
    assert c.post("/admin/announce", json={**post, "force": True}, headers=A).json()["recipients"] == 1
    unsub = store.unsubscribe_token("a@example.com")
    assert c.post("/unsubscribe", json={"token": unsub}, headers=H).status_code == 200
    assert mailer.sent[-1][1] == "You're unsubscribed"
    assert c.get("/admin/stats", headers=A).json()["subscribers"] == 0
    assert store.get_store().get("a@example.com") is None  # the row is gone, not flagged
    n = len(mailer.sent)
    assert c.post("/unsubscribe", json={"token": unsub}, headers=H).status_code == 200
    assert len(mailer.sent) == n  # replay sends nothing
    assert c.get("/admin/stats", headers=A).json()["lastEmail"]["subject"] == "Hello"


def test_confirm_email_is_throttled() -> None:
    c = TestClient(app)
    mailer = mail.get_mailer()
    for _ in range(5):
        assert c.post("/subscribe", json={"email": "b@example.com"}, headers=H).status_code == 202
    assert len(mailer.sent) == 1  # one confirmation, token reused
    sub = store.get_store().get("b@example.com")
    assert sub.sends == 1 and sub.confirm_token


def test_keys_and_validation() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "a@example.com"}).status_code == 401
    assert c.post("/subscribe", json={"email": "nope"}, headers=H).status_code == 400
    assert c.post("/subscribe", json={"email": "a/b@example.com"}, headers=H).status_code == 400
    assert c.get("/admin/stats", headers=H).status_code == 401  # site key alone is not enough
    assert c.post("/confirm", json={"token": "nope"}, headers=H).json() == {"ok": False}
    assert c.post("/unsubscribe", json={"token": "nope.nope"}, headers=H).json() == {"ok": True}
    bad = {"slug": "x", "title": "T", "url": "javascript:alert(1)"}
    assert c.post("/admin/announce", json=bad, headers=A).status_code == 422
    assert c.get("/healthz").json()["configured"] is True


def test_reactions_toggle_per_browser() -> None:
    c = TestClient(app)
    me, you = "client-aaaaaaaaaaaaaaaa", "client-bbbbbbbbbbbbbbbb"
    assert c.get("/reactions/hello", headers=H).json() == {"counts": {k: 0 for k in reactions.KINDS}, "mine": []}
    r = c.post("/reactions/hello", json={"client": me, "kind": "sun"}, headers=H).json()
    assert r["counts"]["sun"] == 1 and r["mine"] == ["sun"]
    r = c.post("/reactions/hello", json={"client": you, "kind": "sun"}, headers=H).json()
    assert r["counts"]["sun"] == 2 and r["mine"] == ["sun"]
    r = c.post("/reactions/hello", json={"client": me, "kind": "sun"}, headers=H).json()  # second tap removes
    assert r["counts"]["sun"] == 1 and r["mine"] == []
    assert c.get("/reactions/hello", headers={**H, "x-client": you}).json()["mine"] == ["sun"]
    assert c.get("/reactions/hello", headers=H).json()["mine"] == []  # no id in the URL, ever
    assert c.post("/reactions/hello", json={"client": me, "kind": "nope"}, headers=H).status_code == 400
    assert c.post("/reactions/Bad Slug", json={"client": me, "kind": "sun"}, headers=H).status_code == 400


def test_replies_store_notify_limit_and_admin() -> None:
    c = TestClient(app)
    me = "client-cccccccccccccccc"
    body = {"client": me, "text": "  I would want it to ask about failures.  ", "name": "Mira", "email": "Mira@Example.com", "title": "Screening"}
    assert c.post("/replies/hello", json=body, headers=H).json() == {"ok": True}
    sent = mail.get_mailer().sent[-1]
    assert sent[0] == ["owner@example.test"] and "Mira" in sent[2] and "ask about failures" in sent[2]
    got = c.get("/admin/replies", headers=A).json()["replies"]
    assert got[0]["text"] == "I would want it to ask about failures." and got[0]["email"] == "mira@example.com"
    assert c.get("/admin/replies", headers=H).status_code == 401  # admin key required
    for _ in range(4):
        c.post("/replies/hello", json={"client": me, "text": "more"}, headers=H)
    assert c.post("/replies/hello", json={"client": me, "text": "too many"}, headers=H).status_code == 429
    assert c.post("/replies/hello", json={"client": me, "text": "x", "email": "nope"}, headers=H).status_code == 400
    assert c.post("/replies/Bad Slug", json={"client": me, "text": "x"}, headers=H).status_code == 400
    assert c.post("/replies/hello", json={"client": me, "text": ""}, headers=H).status_code == 422
    rid = got[0]["id"]
    assert c.delete(f"/admin/replies/hello/{rid}", headers=A).json() == {"ok": True}
