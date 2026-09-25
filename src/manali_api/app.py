"""manali apps backend: subscribers and email. Small on purpose.

Auth: every route except /confirm and /healthz needs `x-api-key` (the site's server holds it;
browsers never see it). Tokens in links are per-address HMACs, so unsubscribe never expires.
"""
from __future__ import annotations

import re

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import mail
from .settings import settings
from .store import Subscriber, get_store, new_confirm_token, now, unsubscribe_token

app = FastAPI(title="manali apps api", docs_url=None, redoc_url=None)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_key(x_api_key: str = Header(default="")) -> None:
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(401, "missing or wrong api key")


class SubscribeIn(BaseModel):
    email: str = Field(max_length=254)
    source: str = "site"


class TokenIn(BaseModel):
    token: str = Field(max_length=64)


class PostIn(BaseModel):
    slug: str
    title: str
    summary: str = ""
    url: str
    cover: str | None = None
    coverText: str | None = None
    project: str = "manali"
    date: str = ""
    author: str = "Manali"


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "configured": settings.configured}


@app.post("/subscribe", status_code=202, dependencies=[Depends(require_key)])
def subscribe(body: SubscribeIn) -> dict:
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "invalid email")
    store = get_store()
    sub = store.get(email)
    if sub and sub.confirmed and not sub.unsubscribed:
        raise HTTPException(409, "already subscribed")
    sub = Subscriber(email=email, created=now(), source=body.source[:32], confirm_token=new_confirm_token())
    store.put(sub)
    subject, html_body = mail.confirm_email(f"{settings.site_url}/api/confirm?token={sub.confirm_token}")
    mail.get_mailer().send([email], subject, html_body)
    return {"ok": True}


@app.get("/confirm")
def confirm(token: str) -> RedirectResponse:
    """Linked from the confirmation email; the site proxies /api/confirm here."""
    store = get_store()
    sub = store.by_confirm_token(token) if token else None
    if not sub:
        return RedirectResponse(f"{settings.site_url}/subscribe/?confirmed=0", status_code=302)
    sub.confirmed, sub.unsubscribed, sub.confirm_token = True, False, ""
    store.put(sub)
    subject, html_body = mail.welcome_email(f"{settings.site_url}/unsubscribe/?token={unsubscribe_token(sub.email)}")
    mail.get_mailer().send([sub.email], subject, html_body)
    return RedirectResponse(f"{settings.site_url}/subscribe/?confirmed=1", status_code=302)


@app.post("/unsubscribe", dependencies=[Depends(require_key)])
def unsubscribe(body: TokenIn) -> dict:
    store = get_store()
    sub = store.by_unsub_token(body.token)
    if not sub:
        raise HTTPException(404, "unknown token")
    sub.unsubscribed = True
    store.put(sub)
    subject, html_body = mail.unsubscribed_email()
    mail.get_mailer().send([sub.email], subject, html_body)
    return {"ok": True}


@app.get("/admin/stats", dependencies=[Depends(require_key)])
def stats() -> dict:
    store = get_store()
    subs = store.all()
    live = [s for s in subs if s.confirmed and not s.unsubscribed]
    recent = sorted(subs, key=lambda s: s.created, reverse=True)[:10]
    return {
        "subscribers": len(live),
        "recent": [{"email": s.email, "created": s.created, "confirmed": s.confirmed and not s.unsubscribed} for s in recent],
        "lastEmail": store.last_email(),
    }


@app.post("/admin/announce", dependencies=[Depends(require_key)])
def announce(post: PostIn) -> dict:
    store = get_store()
    live = [s for s in store.all() if s.confirmed and not s.unsubscribed]
    sent = 0
    mailer = mail.get_mailer()
    for s in live:  # one message per address so each unsubscribe link is its own
        subject, html_body = mail.post_email(post.model_dump(), f"{settings.site_url}/unsubscribe/?token={unsubscribe_token(s.email)}")
        sent += mailer.send([s.email], subject, html_body)
    store.log_email(post.title, sent)
    return {"recipients": sent}
