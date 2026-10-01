import os

os.environ["MANALI_ENV"] = "test"
os.environ["MANALI_API_KEY"] = "test-key-test-key-test-key-test-key"
os.environ["MANALI_ADMIN_KEY"] = "admin-key-admin-key-admin-key-admin"
os.environ["MANALI_TOKEN_SECRET"] = "test-secret-test-secret-test-secret-test"
os.environ["MANALI_SITE_URL"] = "https://example.test"
os.environ["MANALI_NOTIFY_EMAIL"] = "owner@example.test"

from fastapi.testclient import TestClient  # noqa: E402

from manali_api import comments, mail, reactions, replies, store  # noqa: E402
from manali_api.app import app  # noqa: E402

H = {"x-api-key": os.environ["MANALI_API_KEY"]}
A = {**H, "x-admin-key": os.environ["MANALI_ADMIN_KEY"]}


def setup_function() -> None:
    store._store = store.MemoryStore()
    mail._mailer = mail.MemoryMailer()
    reactions._store = reactions.MemoryReactions()
    replies._store = replies.MemoryReplies()
    comments._store = comments.MemoryComments()


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
    assert c.post("/unsubscribe", json={"token": "nope.nope"}, headers=H).json()["ok"] is True
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
    r = c.post("/reactions/hello", json={"client": me, "kind": "idea"}, headers=H).json()
    assert r["counts"]["idea"] == 1 and r["mine"] == ["idea"]
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
    to_follower = [m for m in mailer.sent if m[0] == ["f@example.com"] and m[1] == "Part two"]
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


def test_follows_are_capped_without_dropping_old_ones() -> None:
    c = TestClient(app)
    c.post("/subscribe", json={"email": "many@example.com"}, headers=H)
    c.post("/confirm", json={"token": store.get_store().get("many@example.com").confirm_token}, headers=H)
    long = "s" * 110
    for i in range(60):
        r = c.post("/subscribe", json={"email": "many@example.com", "series": f"{long}-{i}", "seriesTitle": "S"}, headers=H)
        assert r.status_code == 202
    follows = store.get_store().get("many@example.com").follows()
    assert len(follows) == store.MAX_FOLLOWS
    assert follows[0] == f"{long}-0" and follows[-1] == f"{long}-{store.MAX_FOLLOWS - 1}"
    assert len(",".join(follows)) < 32_000  # well inside one Table Storage property



def test_comments_moderation_threads_loves_and_privacy() -> None:
    c = TestClient(app)
    mailer = mail.get_mailer()
    a, b = "client-aaaaaaaaaaaaaaaa", "client-bbbbbbbbbbbbbbbb"
    first = {"client": a, "text": "  First!  ", "email": "A@Example.com", "notify": True, "title": "Hello"}
    r = c.post("/comments/hello", json=first, headers=H).json()
    assert r["state"] == "pending"
    assert mailer.sent[-1][0] == ["owner@example.test"] and mailer.sent[-1][1].startswith("Waiting")
    # held: only its author sees it, and nobody ever sees the email or the raw client id
    assert c.get("/comments/hello", headers=H).json()["comments"] == []
    mine = c.get("/comments/hello", headers={**H, "x-client": a}).json()
    assert mine["comments"][0]["state"] == "pending" and mine["comments"][0]["mine"] is True
    assert "email" not in str(mine) and a not in str(mine) and mine["you"]["trusted"] is False
    # approving trusts the browser: its next comment is live at once
    assert c.post(f"/admin/comments/hello/{r['id']}/approve", headers=H).status_code == 401
    assert c.post(f"/admin/comments/hello/{r['id']}/approve", headers=A).json()["state"] == "live"
    second = c.post("/comments/hello", json={"client": a, "text": "Second"}, headers=H).json()
    assert second["state"] == "live"
    # a trusted reader replies to a reply: it joins the top-level thread and emails the parent's author
    c.post(f"/admin/comments/hello/{r['id']}/approve", headers=A)
    reply = c.post("/admin/comments/hello", json={"text": "Thanks", "parent": r["id"], "title": "Hello"}, headers=A).json()
    assert mailer.sent[-1][0] == ["a@example.com"] and "replied to your comment" in mailer.sent[-1][2]
    stop_url = [x for x in mailer.sent[-1][2].split('"') if "/comments/stop/" in x][0]
    b_first = c.post("/comments/hello", json={"client": b, "text": "Me too", "parent": reply["id"]}, headers=H).json()
    c.post(f"/admin/comments/hello/{b_first['id']}/approve", headers=A)
    thread = c.get("/comments/hello", headers=H).json()["comments"]
    assert {x["parent"] for x in thread if x["id"] in (reply["id"], b_first["id"])} == {r["id"]}
    owner = next(x for x in thread if x["id"] == reply["id"])
    assert owner["owner"] is True and owner["seed"] == ""
    # the stop link turns the author's reply emails off
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(stop_url.replace("&amp;", "&")).query).items()}
    assert c.post("/comment-emails/stop", json={"post": q["post"], "id": q["id"], "token": "wrong" * 5}, headers=H).json() == {"ok": True}
    assert c.post("/comment-emails/stop", json={**q, "token": "é" * 32}, headers=H).json() == {"ok": True}  # no 500
    assert c.post("/comment-emails/stop", json=q, headers=H).json() == {"ok": True}
    assert c.get("/comments/hello", headers={**H, "x-client": a}).json()["comments"][0]["notify"] is False
    # only the author can switch reply emails; a comment without an email can't turn them on
    assert c.post(f"/comments/hello/{r['id']}/notify", json={"client": b, "notify": True}, headers=H).status_code == 404
    assert c.post(f"/comments/hello/{second['id']}/notify", json={"client": a, "notify": True}, headers=H).status_code == 400
    # loves toggle per browser
    assert c.post(f"/comments/hello/{second['id']}/love", json={"client": b}, headers=H).json() == {"loves": 1, "loved": True}
    assert c.post(f"/comments/hello/{second['id']}/love", json={"client": b}, headers=H).json() == {"loves": 0, "loved": False}
    # removed comments keep a placeholder without the text
    c.post(f"/admin/comments/hello/{second['id']}/remove", headers=A)
    gone = next(x for x in c.get("/comments/hello", headers=H).json()["comments"] if x["id"] == second["id"])
    assert gone == {"id": second["id"], "parent": "", "state": "removed", "created": gone["created"]}
    # names that would pass as the owner are refused; admin listing needs the admin key
    assert c.post("/comments/hello", json={"client": b, "text": "hi", "name": "Ayush (real)"}, headers=H).status_code == 400
    assert c.get("/admin/comments", headers=H).status_code == 401
    assert any(x.get("email") == "a@example.com" for x in c.get("/admin/comments", headers=A).json()["comments"])


def test_comments_share_the_reply_rate_limit() -> None:
    c = TestClient(app)
    me = "client-cccccccccccccccc"
    codes = [c.post("/comments/hello", json={"client": me, "text": f"n{i}"}, headers=H).status_code for i in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429
    assert c.post("/comments/hello", json={"client": me, "text": "x", "parent": "nope"}, headers=H).status_code == 400


def test_announcements_list_who_got_it() -> None:
    c = TestClient(app)
    s = store.get_store()
    for e in ("a@example.com", "b@example.com"):
        s.put(store.Subscriber(email=e, confirmed=True, created=store.now()))
    s.log_email("Old one", 9, slug="old")  # from before recipient lists were kept
    post = {"slug": "hello", "title": "Hello", "summary": "First.", "url": "https://example.test/blog/hello/", "author": "Ayush"}
    n = len(mail.get_mailer().sent)
    preview = c.post("/admin/announce/preview", json=post, headers=A).json()
    assert preview["subject"] == "Hello" and "Read it" in preview["html"]
    assert len(mail.get_mailer().sent) == n  # a preview sends nothing
    assert c.post("/admin/announce", json=post, headers=A).json() == {"recipients": 2, "subscribers": 2}
    got = c.get("/admin/announcements", headers=A).json()["announcements"]
    assert [a["slug"] for a in got] == ["hello", "old"]
    assert [(t["email"], t["ok"]) for t in got[0]["to"]] == [("a@example.com", True), ("b@example.com", True)]
    assert got[1]["to"] is None and got[1]["recipients"] == 9
    c.post("/unsubscribe", json={"token": store.unsubscribe_token("b@example.com")}, headers=H)
    to = c.get("/admin/announcements", headers=A).json()["announcements"][0]["to"]
    assert [(t["email"], t["ok"]) for t in to] == [("a@example.com", True), (None, True)]  # the address is gone
    assert c.get("/admin/announcements", headers=H).status_code == 401


def test_letter_email_and_series_stop() -> None:
    c = TestClient(app)
    s = store.get_store()
    s.put(store.Subscriber(email="all@example.com", confirmed=True, created=store.now()))
    fan = store.Subscriber(email="fan@example.com", confirmed=True, created=store.now(), everything=False)
    fan.follow("building-yapp", "Building Yapp")
    fan.follow("other")
    s.put(fan)
    post = {"slug": "p2", "title": "Undo", "summary": "Why undo.", "url": "https://example.test/blog/p2/", "series": "building-yapp",
            "seriesTitle": "Building Yapp", "seriesPart": 2, "seriesTotal": 3, "seriesUrl": "https://example.test/series/building-yapp/",
            "authorKind": "agent", "authorName": "Claude", "authorOwner": "Ayush Manish Agrawal", "project": "yapp", "note": "Claude wrote this one.\n\nI kept it."}
    assert c.post("/admin/announce/preview", json={**post, "seriesPart": 5}, headers=A).status_code == 422  # part 5 of 3
    pv = c.post("/admin/announce/preview?theme=dark", json=post, headers=A).json()
    assert pv["subject"] == "Building Yapp, part 2: Undo" and pv["preheader"] == "Claude wrote this one."
    assert pv["from"].startswith("Ayush at manali apps") and pv["audience"] == 2 and pv["followers"] == 1
    assert 'class="ma-email ma-dark"' in pv["html"] and "Part 2 of 3" in pv["html"] and "/email/agent-yapp@2x.png" in pv["html"]
    assert c.post("/admin/announce", json=post, headers=A).json() == {"recipients": 2, "subscribers": 2}
    sent = {to[0]: html for to, _, html in mail.get_mailer().sent[-2:]}
    assert "Stop following this series" in sent["fan@example.com"] and "Stop following" not in sent["all@example.com"]
    to = c.get("/admin/announcements", headers=A).json()["announcements"][0]["to"]
    assert {t["email"]: t["follower"] for t in to} == {"all@example.com": False, "fan@example.com": True}
    # stopping one series keeps the other follow; stopping the last one removes the address
    tok = store.unsubscribe_token("fan@example.com")
    assert c.post("/unsubscribe", json={"token": tok, "series": "building-yapp"}, headers=H).json()["scope"] == "series"
    assert s.get("fan@example.com").follows() == ["other"]
    assert c.post("/unsubscribe", json={"token": tok, "series": "other"}, headers=H).json()["scope"] == "all"
    assert s.get("fan@example.com") is None


def test_failed_batches_are_recorded() -> None:
    class Flaky(mail.MemoryMailer):
        def send_many(self, messages, idempotency="", accepted=None, failures=None):  # noqa: ANN001, ANN201
            failures.update((m["to"][0], "rejected by Resend (422)") for m in messages)
            return 0

    mail._mailer = Flaky()
    c = TestClient(app)
    store.get_store().put(store.Subscriber(email="a@example.com", confirmed=True, created=store.now()))
    post = {"slug": "hello", "title": "Hello", "url": "https://example.test/blog/hello/"}
    assert c.post("/admin/announce", json=post, headers=A).json() == {"recipients": 0, "subscribers": 1}
    got = c.get("/admin/announcements", headers=A).json()["announcements"][0]
    assert got["to"] == [{"email": "a@example.com", "ok": False, "follower": False, "reason": "rejected by Resend (422)"}]


def test_admin_data_masks_client_ids() -> None:
    from manali_api import data

    t = data.MemoryTables()
    t.data = {
        "reactions": [{"PartitionKey": "hello", "RowKey": "client-abcdef|love", "Timestamp": "2026-09-30T10:00:00Z"}],
        "replies": [{"PartitionKey": "reply", "RowKey": "1", "client": "client-abcdef", "text": "hi", "Timestamp": "2026-09-30T09:00:00Z"},
                    {"PartitionKey": "reply", "RowKey": "2", "client": "client-xyz", "text": "newer", "Timestamp": "2026-09-30T11:00:00Z"}],
        "subscribers": [{"PartitionKey": "sub", "RowKey": "k", "email": "a@example.com", "confirm_token": "secret-token"}],
    }
    data._tables = t
    c = TestClient(app)
    assert c.get("/admin/data", headers=H).status_code == 401
    tables = {x["name"]: x for x in c.get("/admin/data", headers=A).json()["tables"]}
    assert set(tables) == set(data.TABLES)
    assert tables["replies"]["count"] == 2 and tables["comments"]["count"] == 0
    assert tables["replies"]["updated"] == "2026-09-30T11:00:00Z"
    r = c.get("/admin/data/reactions", headers=A).json()
    assert r["rows"][0]["RowKey"] == "clie…|love"
    rep = c.get("/admin/data/replies?limit=1", headers=A).json()
    assert rep["total"] == 2 and [x["text"] for x in rep["rows"]] == ["newer"]  # newest first
    assert rep["rows"][0]["client"] == "clie…"
    assert rep["columns"][:2] == ["PartitionKey", "RowKey"] and rep["columns"][-1] == "Timestamp"
    sub = c.get("/admin/data/subscribers", headers=A).json()["rows"][0]
    assert sub["email"] == "a@example.com" and sub["confirm_token"] == "secr…"
    assert c.get("/admin/data/nope", headers=A).status_code == 404


def test_admin_telemetry() -> None:
    from manali_api import telemetry

    class Fake:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def query(self, kql: str) -> list[dict]:
            self.seen.append(kql)
            if "summarize people = dcount(user_Id)\n" in kql or kql.rstrip().endswith("summarize people = dcount(user_Id)"):
                return [{"people": 3}]
            if kql.startswith("union (pageViews") and "make-series" not in kql:
                return [{"pageviews": 10, "people": 4, "sessions": 5, "seconds": None, "depth": 40.0, "errors": 0, "calls": 7, "failed": 1}]
            return []

    c = TestClient(app)
    telemetry._reader = None
    assert c.get("/admin/telemetry", headers=A).json() == {"configured": False}
    fake = Fake()
    telemetry._reader = fake
    telemetry._cache.clear()
    out = c.get("/admin/telemetry?range=7d", headers=A).json()
    assert out["configured"] and out["range"] == "7d" and out["step"] == "6h"
    assert out["now"]["people"] == 3 and out["totals"]["pageviews"] == 10 and out["totals"]["seconds"] == 0
    assert all('cloud_RoleName' in q for q in fake.seen)  # never another site's traffic
    n = len(fake.seen)
    c.get("/admin/telemetry?range=7d", headers=A)
    assert len(fake.seen) == n  # cached
    assert c.get("/admin/telemetry?range=1y", headers=A).status_code == 422
    assert c.get("/admin/telemetry/now", headers=A).json() == {"configured": True, "people": 3, "pages": [], "window": "5m"}

    class Broken:
        def query(self, kql: str) -> list[dict]:
            raise RuntimeError("Application Insights answered 403")

    telemetry._reader = Broken()
    telemetry._cache.clear()
    r = c.get("/admin/telemetry", headers=A)
    assert r.status_code == 502 and "403" in r.json()["detail"]
    telemetry._reader = None
