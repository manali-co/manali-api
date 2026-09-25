import os

os.environ.setdefault("MANALI_API_KEY", "test-key")
os.environ.setdefault("MANALI_TOKEN_SECRET", "test-secret")
os.environ.setdefault("MANALI_SITE_URL", "https://example.test")

from fastapi.testclient import TestClient  # noqa: E402

from manali_api import mail, store  # noqa: E402
from manali_api.app import app  # noqa: E402

H = {"x-api-key": "test-key"}


def setup_function() -> None:
    store._store = store.MemoryStore()
    mail._mailer = mail.MemoryMailer()


def test_subscribe_confirm_announce_unsubscribe() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "A@Example.com"}, headers=H).status_code == 202
    mailer = mail.get_mailer()
    assert mailer.sent[-1][1].startswith("Confirm")
    token = store.get_store().get("a@example.com").confirm_token
    r = c.get(f"/confirm?token={token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("confirmed=1")
    assert mailer.sent[-1][1] == "Welcome to manali apps"
    assert c.get("/admin/stats", headers=H).json()["subscribers"] == 1
    assert c.post("/subscribe", json={"email": "a@example.com"}, headers=H).status_code == 409
    post = {"slug": "hello", "title": "Hello", "summary": "First.", "url": "https://example.test/blog/hello/", "author": "Ayush"}
    assert c.post("/admin/announce", json=post, headers=H).json() == {"recipients": 1}
    assert "Unsubscribe" in mailer.sent[-1][2]
    unsub = store.unsubscribe_token("a@example.com")
    assert c.post("/unsubscribe", json={"token": unsub}, headers=H).status_code == 200
    assert c.get("/admin/stats", headers=H).json()["subscribers"] == 0
    assert c.get("/admin/stats", headers=H).json()["lastEmail"]["subject"] == "Hello"


def test_rejects_bad_key_and_bad_email() -> None:
    c = TestClient(app)
    assert c.post("/subscribe", json={"email": "a@example.com"}).status_code == 401
    assert c.post("/subscribe", json={"email": "nope"}, headers=H).status_code == 400
    assert c.get("/confirm?token=nope", follow_redirects=False).headers["location"].endswith("confirmed=0")
