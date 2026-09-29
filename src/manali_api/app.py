"""manali apps backend: subscribers, email, reactions. Small on purpose.

Auth: every route except /healthz needs `x-api-key` (the site's server holds it; browsers never
see it). /admin/* needs `x-admin-key` on top, a separate secret the public routes never carry.
Links in email carry per-address HMAC tokens; the state change only happens on a POST from the
site, never on the GET a link scanner performs.
"""
from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import mail
from .reactions import CLIENT, KINDS, SLUG, get_reactions
from .replies import MAX_TEXT, Reply, get_replies
from .replies import now_iso as reply_now
from .settings import settings
from .store import Subscriber, by_unsub_token, get_store, new_confirm_token, now, parse, purge_pending, unsubscribe_token

app = FastAPI(title="manali apps api", docs_url=None, redoc_url=None, openapi_url=None)
# Local part: no control characters and none of the characters Table Storage rejects in keys
# (keys are hashed now, but keep addresses sane); one domain with a dot.
EMAIL = re.compile(r"^[A-Za-z0-9!$%&'*+=^_`{|}~.-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
RESEND_WINDOW = timedelta(minutes=10)
MAX_CONFIRM_SENDS_PER_DAY = 3


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def series_url(slug: str) -> str:
    return f"{settings.site_url}/series/{slug}/"


def unsubscribe_links(email: str) -> tuple[str, str]:
    """The page a person clicks (nothing happens until they press the button) and the endpoint a
    mail client POSTs to for RFC 8058 one-click unsubscribe."""
    token = unsubscribe_token(email)
    return f"{settings.site_url}/unsubscribe/?token={token}", f"{settings.site_url}/api/unsubscribe/?token={token}"


def ready() -> None:
    if settings.problems:
        raise HTTPException(503, "api not configured: " + "; ".join(settings.problems))


def require_key(x_api_key: str = Header(default=""), _: None = Depends(ready)) -> None:
    if not _same(x_api_key, settings.api_key):
        raise HTTPException(401, "missing or wrong api key")


def require_admin(x_admin_key: str = Header(default=""), _: None = Depends(require_key)) -> None:
    if not settings.admin_key:
        raise HTTPException(503, "MANALI_ADMIN_KEY not set")
    if not _same(x_admin_key, settings.admin_key):
        raise HTTPException(401, "missing or wrong admin key")


class SubscribeIn(BaseModel):
    email: str = Field(max_length=254)
    source: str = Field(default="site", max_length=32)
    # Set to follow one series instead of every post. The site sends the title from its own
    # content, never from the visitor, and only for a series slug it knows.
    series: str | None = Field(default=None, max_length=120)
    seriesTitle: str = Field(default="", max_length=120)

    @field_validator("series")
    @classmethod
    def _series(cls, v: str | None) -> str | None:
        if v is not None and not SLUG.match(v):
            raise ValueError("bad series")
        return v

    @field_validator("seriesTitle")
    @classmethod
    def _title(cls, v: str) -> str:
        return re.sub(r"[\r\n\t]+", " ", v).strip()


class TokenIn(BaseModel):
    token: str = Field(max_length=80)


class PostIn(BaseModel):
    slug: str = Field(max_length=120)
    title: str = Field(max_length=200)
    summary: str = Field(default="", max_length=600)
    url: str
    cover: str | None = None
    coverText: str | None = Field(default=None, max_length=40)
    project: str = "manali"
    date: str = Field(default="", max_length=40)
    author: str = Field(default="Manali", max_length=120)
    series: str | None = Field(default=None, max_length=120)  # followers of this series get it too
    seriesTitle: str = Field(default="", max_length=120)
    force: bool = False

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("bad slug")
        return v

    @field_validator("url", "cover")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("links in email must be https")
        return v

    @field_validator("series")
    @classmethod
    def _series(cls, v: str | None) -> str | None:
        if v is not None and not SLUG.match(v):
            raise ValueError("bad series")
        return v

    @field_validator("title", "summary", "author", "seriesTitle")
    @classmethod
    def _one_line(cls, v: str) -> str:
        return re.sub(r"[\r\n\t]+", " ", v).strip()


class ReplyIn(BaseModel):
    client: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    name: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=254)
    title: str = Field(default="", max_length=200)

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("name", "title")
    @classmethod
    def _one_line(cls, v: str) -> str:
        # both reach an email subject or header; never let a newline through
        return re.sub(r"[\r\n\t]+", " ", v).strip()


class ReactIn(BaseModel):
    client: str = Field(max_length=64)
    kind: str = Field(max_length=16)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "configured": settings.configured,
        "mail": settings.mail_ready,
        "site_url": settings.site_url,
        "problems": settings.problems,
    }


# --- reactions -------------------------------------------------------------------------------

@app.get("/reactions/{slug}", dependencies=[Depends(require_key)])
def reactions(slug: str, x_client: str = Header(default="")) -> dict[str, Any]:
    """Counts for a post. The browser's own reactions come back only when it sends its id in a
    header, so the id never lands in a request URL or a log."""
    if not SLUG.match(slug):
        raise HTTPException(400, "bad slug")
    c = get_reactions().get(slug, x_client if CLIENT.match(x_client) else "")
    return {"counts": c.counts, "mine": c.mine}


@app.post("/reactions/{slug}", dependencies=[Depends(require_key)])
def react(slug: str, body: ReactIn) -> dict[str, Any]:
    """Toggle one reaction for one browser. Anonymous by design; the client id is random."""
    if not SLUG.match(slug) or body.kind not in KINDS or not CLIENT.match(body.client):
        raise HTTPException(400, "bad request")
    c = get_reactions().toggle(slug, body.client, body.kind)
    return {"counts": c.counts, "mine": c.mine}


# --- replies ---------------------------------------------------------------------------------

@app.post("/replies/{slug}", status_code=202, dependencies=[Depends(require_key)])
def reply(slug: str, body: ReplyIn) -> dict[str, Any]:
    """A reply to a post, no account needed. Rate-limited per browser; the owner gets an email.
    The answer never echoes anything back."""
    if not SLUG.match(slug) or not CLIENT.match(body.client) or not body.text:
        raise HTTPException(400, "bad request")
    email = body.email.strip().lower()
    if email and not EMAIL.match(email):
        raise HTTPException(400, "invalid email")
    store = get_replies()
    if not store.take_quota(body.client):
        raise HTTPException(429, "slow down")
    r = store.add(Reply(slug=slug, text=body.text, created=reply_now(), client=body.client, name=body.name, email=email))
    if settings.notify_email:
        post_url, admin_url = f"{settings.site_url}/blog/{slug}/", f"{settings.site_url}/admin/"
        subject, html_body = mail.reply_notice(body.title or slug, post_url, r.text, r.name, r.email, admin_url)
        m = mail.message(settings.notify_email, subject, html_body)
        if r.email:
            m["reply_to"] = r.email
        mail.get_mailer().send_many([m])
    return {"ok": True}


@app.get("/admin/replies", dependencies=[Depends(require_admin)])
def replies_list() -> dict[str, Any]:
    rows = get_replies().latest(50)
    return {"replies": [{"slug": r.slug, "id": r.id, "text": r.text, "name": r.name, "email": r.email, "created": r.created} for r in rows]}


@app.delete("/admin/replies/{slug}/{reply_id}", dependencies=[Depends(require_admin)])
def replies_delete(slug: str, reply_id: str) -> dict[str, Any]:
    return {"ok": get_replies().delete(slug, reply_id)}


# --- subscribers -----------------------------------------------------------------------------

@app.post("/subscribe", status_code=202, dependencies=[Depends(require_key)])
def subscribe(body: SubscribeIn) -> dict[str, Any]:
    """Always 202: the response never says whether an address is on the list. An email goes out
    at most once per ten minutes and three times a day per address, and the confirm token is
    reused, so a flood of requests cannot bomb an inbox or kill the link in the first email.

    With `series`, the address follows that one series: it gets an email for a new part and
    nothing else. A confirmed address following another series needs no new opt-in; it gets a
    short note instead, so the site's "check your inbox" is always true."""
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "invalid email")
    store = get_store()
    sub = store.get(email)
    t = datetime.now(UTC)

    def may_send(s: Subscriber, window: bool = True) -> bool:
        # The ten-minute window protects a pending confirmation link; a follow note has none to
        # protect, so it only counts toward the daily cap.
        recent = parse(s.last_sent)
        day_ago = t - timedelta(days=1)
        if (window and t - recent < RESEND_WINDOW) or (recent > day_ago and s.sends >= MAX_CONFIRM_SENDS_PER_DAY):
            return False
        if recent <= day_ago:
            s.sends = 0
        return True

    def sent(s: Subscriber, ok: int) -> None:
        if ok:
            s.sends, s.last_sent = s.sends + 1, now()

    if sub and sub.confirmed:
        if body.series:
            if not sub.follow(body.series, body.seriesTitle):
                return {"ok": True}  # at the follow cap: nothing added, nothing sent, same answer
            if may_send(sub, window=False):
                page, one_click = unsubscribe_links(sub.email)
                subject, html_body = mail.follow_email(body.seriesTitle or "the series", series_url(body.series), sub.everything, page)
                sent(sub, mail.get_mailer().send(email, subject, html_body, mail.unsubscribe_headers(one_click)))
            store.put(sub)
        elif not sub.everything:
            sub.everything = True  # a series follower who now wants every post
            store.put(sub)
        return {"ok": True}

    if sub:
        if body.series:
            sub.follow(body.series, body.seriesTitle)
        else:
            sub.everything = True
        if not may_send(sub):
            store.put(sub)
            return {"ok": True}
        sub.confirm_token = sub.confirm_token or new_confirm_token()
    else:
        sub = Subscriber(email=email, created=now(), source=body.source, confirm_token=new_confirm_token(), everything=not body.series)
        if body.series:
            sub.follow(body.series, body.seriesTitle)
    title = "" if sub.everything else (sub.series_title or "the series")
    subject, html_body = mail.confirm_email(f"{settings.site_url}/confirm/?token={sub.confirm_token}", title)
    sent(sub, mail.get_mailer().send(email, subject, html_body))
    store.put(sub)
    return {"ok": True}


@app.post("/confirm", dependencies=[Depends(require_key)])
def confirm(body: TokenIn) -> dict[str, Any]:
    """The site's /confirm/ page posts here after the person clicks the button; a link scanner
    fetching the URL from the email changes nothing."""
    store = get_store()
    sub = store.by_confirm_token(body.token) if body.token else None
    if not sub:
        return {"ok": False}
    if sub.confirmed:
        return {"ok": True, "already": True}
    sub.confirmed, sub.confirm_token = True, ""
    store.put(sub)
    page, one_click = unsubscribe_links(sub.email)
    if sub.everything:
        subject, html_body = mail.welcome_email(page)
    else:
        latest = sub.follows()[-1] if sub.follows() else ""
        subject, html_body = mail.welcome_email(page, sub.series_title or "the series", series_url(latest) if latest else "")
    mail.get_mailer().send(sub.email, subject, html_body, mail.unsubscribe_headers(one_click))
    return {"ok": True}


@app.post("/unsubscribe", dependencies=[Depends(require_key)])
def unsubscribe(body: TokenIn) -> dict[str, Any]:
    """Deletes the row. Idempotent: a replayed token is a no-op and sends nothing. The answer
    does not reveal whether the token matched anyone."""
    store = get_store()
    sub = by_unsub_token(store, body.token)
    if sub:
        store.delete(sub)
        subject, html_body = mail.unsubscribed_email()
        mail.get_mailer().send(sub.email, subject, html_body)
    return {"ok": True}


# --- admin -----------------------------------------------------------------------------------

@app.get("/admin/stats", dependencies=[Depends(require_admin)])
def stats() -> dict[str, Any]:
    store = get_store()
    purge_pending(store)
    subs = store.all()
    live = sorted((s for s in subs if s.confirmed), key=lambda s: s.created, reverse=True)
    return {
        "subscribers": len(live),
        "pending": sum(1 for s in subs if not s.confirmed),
        "recent": [{"email": s.email, "created": s.created, "confirmed": True} for s in live[:10]],
        "lastEmail": store.last_email(),
    }


@app.post("/admin/announce", dependencies=[Depends(require_admin)])
def announce(post: PostIn) -> dict[str, Any]:
    """One message per confirmed address (each has its own unsubscribe link), sent in batches
    with an idempotency key per batch. A slug that was already announced is refused unless
    `force` is set, so a retried click cannot mail everyone twice."""
    store = get_store()
    if not post.force and store.announced(post.slug):
        raise HTTPException(409, "already announced; pass force to send again")
    live = [s for s in store.all() if s.confirmed and s.wants(post.series)]
    messages = []
    for s in live:
        page, one_click = unsubscribe_links(s.email)
        reason = f"You got this because you follow {post.seriesTitle or 'this series'} at manali apps." if not s.everything else ""
        subject, html_body = mail.post_email(post.model_dump(exclude={"force", "series", "seriesTitle"}), page, reason)
        messages.append(mail.message(s.email, subject, html_body, mail.unsubscribe_headers(one_click)))
    sent = mail.get_mailer().send_many(messages, idempotency=f"announce/{post.slug}") if messages else 0
    store.log_email(post.title, sent, slug=post.slug)
    return {"recipients": sent, "subscribers": len(live)}
