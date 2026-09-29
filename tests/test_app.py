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


def test_reply_quota_holds_under_concurrency() -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = replies.MemoryReplies()
    with ThreadPoolExecutor(16) as ex:
        granted = list(ex.map(lambda _: store.take_quota("client-dddddddddddddddd"), range(40)))
    assert granted.count(True) == replies.PER_CLIENT_PER_HOUR
    assert store.take_quota("client-eeeeeeeeeeeeeeee")  # another browser has its own budget


def test_series_followers_get_only_their_series() -> None:
    c = TestClient(app)
    mailer = mail.get_mailer()
    follow = {"email": "f@example.com", "series": "evening-builds", "seriesTitle": "Evening builds"}
    assert c.post("/subscribe", json=follow, headers=H).status_code == 202
    assert mailer.sent[-1][1] == "Confirm: follow Evening builds"
    token = store.get_store().get("f@example.com").confirm_token
    assert c.post("/confirm", json={"token": token}, headers=H).json() == {"ok": True}
    assert mailer.sent[-1][1] == "You're following Evening builds"
    assert "/series/evening-builds/" in mailer.sent[-1][2]
    # an everything subscriber, the way every existing row loads
    c.post("/subscribe", json={"email": "all@example.com"}, headers=H)
    c.post("/confirm", json={"token": store.get_store().get("all@example.com").confirm_token}, headers=H)

    post = {"slug": "solo", "title": "Solo", "url": "https://example.test/blog/solo/"}
    assert c.post("/admin/announce", json=post, headers=A).json()["recipients"] == 1  # not the follower
    part = {"slug": "part-2", "title": "Part two", "url": "https://example.test/blog/part-2/", "series": "evening-builds", "seriesTitle": "Evening builds"}
    assert c.post("/admin/announce", json=part, headers=A).json()["recipients"] == 2
    to_follower = [m for m in mailer.sent if m[0] == ["f@example.com"] and m[1] == "New post: Part two"]
    assert to_follower and "because you follow Evening builds" in to_follower[0][2]
    other = {**part, "slug": "else", "series": "another-one", "seriesTitle": "Another"}
    assert c.post("/admin/announce", json=other, headers=A).json()["recipients"] == 1

    # a confirmed follower following another series: no new opt-in, a note instead
    n = len(mailer.sent)
    c.post("/subscribe", json={**follow, "series": "another-one", "seriesTitle": "Another"}, headers=H)
    assert mailer.sent[-1][1] == "You're following Another" and len(mailer.sent) == n + 1
    assert store.get_store().get("f@example.com").follows() == ["evening-builds", "another-one"]
    # and later asking for every post turns that on without mailing again
    c.post("/subscribe", json={"email": "f@example.com"}, headers=H)
    assert store.get_store().get("f@example.com").everything is True
    assert c.post("/subscribe", json={**follow, "series": "Bad Slug"}, headers=H).status_code == 422


def test_follow_notes_are_capped_per_day() -> None:
    c = TestClient(app)
    mailer = mail.get_mailer()
    c.post("/subscribe", json={"email": "cap@example.com"}, headers=H)
    c.post("/confirm", json={"token": store.get_store().get("cap@example.com").confirm_token}, headers=H)
    for i in range(10):
        c.post("/subscribe", json={"email": "cap@example.com", "series": f"s-{i}", "seriesTitle": f"S{i}"}, headers=H)
    notes = [m for m in mailer.sent if m[0] == ["cap@example.com"] and m[1].startswith("You're following")]
    assert 1 <= len(notes) <= 3
    assert len(store.get_store().get("cap@example.com").follows()) == 10  # every follow still counts
