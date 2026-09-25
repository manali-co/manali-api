import os

os.environ.setdefault("MANALI_API_KEY", "test-key")
os.environ.setdefault("MANALI_TOKEN_SECRET", "test-secret")
os.environ.setdefault("MANALI_SITE_URL", "https://example.test")

from fastapi.testclient import TestClient  # noqa: E402

from manali_api import mail, reactions, store  # noqa: E402
from manali_api.app import app  # noqa: E402

H = {"x-api-key": "test-key"}


def setup_function() -> None:
    store._store = store.MemoryStore()
    mail._mailer = mail.MemoryMailer()
    reactions._store = reactions.MemoryReactions()


def test_subscribe_confirm_announce_unsubscribe() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "A@Example.com"}, headers=H).status_code == 202
    mailer = mail.get_mailer()
    assert mailer.sent[-1][1].startswith("Confirm")
    token = store.get_store().get("a@example.com").confirm_token
    r = c.get(f"/confirm?token={token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("confirmed=1")
    assert mailer.sent[-1][1] == "You're in"
    assert c.get("/admin/stats", headers=H).json()["subscribers"] == 1
    assert c.post("/subscribe", json={"email": "a@example.com"}, headers=H).status_code == 409
    post = {"slug": "hello", "title": "Hello", "summary": "First.", "url": "https://example.test/blog/hello/", "author": "Ayush"}
    assert c.post("/admin/announce", json=post, headers=H).json() == {"recipients": 1}
    assert "Unsubscribe" in mailer.sent[-1][2]
    unsub = store.unsubscribe_token("a@example.com")
    assert c.post("/unsubscribe", json={"token": unsub}, headers=H).status_code == 200
    assert c.get("/admin/stats", headers=H).json()["subscribers"] == 0
    assert c.get("/admin/stats", headers=H).json()["lastEmail"]["subject"] == "Hello"
    assert "manali" in mailer.sent[-2][2] and "Read it" in mailer.sent[-2][2]


def test_rejects_bad_key_and_bad_email() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "a@example.com"}).status_code == 401
    assert c.post("/subscribe", json={"email": "nope"}, headers=H).status_code == 400
    assert c.get("/confirm?token=nope", follow_redirects=False).headers["location"].endswith("confirmed=0")


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
    assert c.get(f"/reactions/hello?client={you}", headers=H).json()["mine"] == ["sun"]
    assert c.post("/reactions/hello", json={"client": me, "kind": "nope"}, headers=H).status_code == 400
    assert c.post("/reactions/Bad Slug", json={"client": me, "kind": "sun"}, headers=H).status_code == 400
