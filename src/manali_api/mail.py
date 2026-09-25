"""Email through Resend. Templates are plain HTML strings built from the brand tokens; the
HTML mirrors the Email components in the Claude Design project (confirm, welcome, new post,
unsubscribed). Reply notifications for comments are GitHub's own, since comments live in
Discussions."""
from __future__ import annotations

import html
import logging
from typing import Protocol

import httpx

from .settings import settings

log = logging.getLogger("manali.mail")

INK, PAPER, INDIGO, GOLD, INK2 = "#23224A", "#F7F5EE", "#5B63C7", "#F2B84B", "#55547A"
FONT = "Inter, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"


def shell(title: str, body: str, footer: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light dark"><title>{html.escape(title)}</title></head>
<body style="margin:0;background:{PAPER};font-family:{FONT};color:{INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER}"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
<tr><td style="padding:0 0 24px"><img src="{settings.site_url}/brand/lockup-light.svg" width="150" alt="manali apps" style="display:block"></td></tr>
<tr><td style="background:#FFFFFF;border:1px solid #E3DFD2;border-radius:16px;padding:32px">{body}</td></tr>
<tr><td style="padding:24px 8px 0;font-size:13px;line-height:1.5;color:#84839E">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def button(label: str, url: str) -> str:
    return (f'<a href="{html.escape(url)}" style="display:inline-block;background:{INDIGO};color:#FFFFFF;text-decoration:none;'
            f'font-weight:600;font-size:16px;padding:13px 22px;border-radius:999px">{html.escape(label)}</a>')


def confirm_email(confirm_url: str) -> tuple[str, str]:
    body = (f'<h1 style="margin:0 0 12px;font-size:24px;line-height:1.3">One click and you\'re in.</h1>'
            f'<p style="margin:0 0 20px;font-size:16px;line-height:1.6;color:{INK2}">You asked for new posts from manali apps by email. Confirm it was you and we\'ll do the rest. If it wasn\'t you, ignore this and nothing happens.</p>'
            f'{button("Confirm subscription", confirm_url)}')
    return "Confirm your subscription to manali apps", shell("Confirm your subscription", body, "You got this because someone entered your address at manali apps. No confirmation, no emails.")


def welcome_email(unsub_url: str) -> tuple[str, str]:
    body = (f'<h1 style="margin:0 0 12px;font-size:24px;line-height:1.3">You\'re in.</h1>'
            f'<p style="margin:0 0 20px;font-size:16px;line-height:1.6;color:{INK2}">Every new post lands here, and nothing else does. No digests, no schedule. When there\'s something to say, you\'ll hear it.</p>'
            f'{button("Read the blog", settings.site_url + "/blog/")}')
    return "Welcome to manali apps", shell("Welcome", body, f'You subscribed at manali apps. <a href="{html.escape(unsub_url)}" style="color:#84839E">Unsubscribe</a> any time, one click.')


def post_email(post: dict, unsub_url: str) -> tuple[str, str]:
    cover = f'<img src="{html.escape(post["cover"])}" width="536" alt="" style="display:block;width:100%;border-radius:12px;margin:0 0 20px">' if post.get("cover") else ""
    body = (f'{cover}<h1 style="margin:0 0 12px;font-size:24px;line-height:1.3">{html.escape(post["title"])}</h1>'
            f'<p style="margin:0 0 8px;font-size:16px;line-height:1.6;color:{INK2}">{html.escape(post.get("summary", ""))}</p>'
            f'<p style="margin:0 0 20px;font-size:14px;color:#84839E">{html.escape(post.get("author", "Manali"))}</p>'
            f'{button("Read it", post["url"])}')
    return post["title"], shell(post["title"], body, f'You got this because you subscribed at manali apps. <a href="{html.escape(unsub_url)}" style="color:#84839E">Unsubscribe</a> in one click.')


def unsubscribed_email() -> tuple[str, str]:
    body = (f'<h1 style="margin:0 0 12px;font-size:24px;line-height:1.3">You\'re off the list.</h1>'
            f'<p style="margin:0;font-size:16px;line-height:1.6;color:{INK2}">No hard feelings. The posts are still there whenever you want them.</p>')
    return "Unsubscribed from manali apps", shell("Unsubscribed", body, "This is the last one.")


class Mailer(Protocol):
    def send(self, to: list[str], subject: str, html_body: str) -> int: ...


class ResendMailer:
    def send(self, to: list[str], subject: str, html_body: str) -> int:
        if not settings.resend_api_key:
            log.warning("RESEND_API_KEY missing; not sending %r to %d addresses", subject, len(to))
            return 0
        sent = 0
        with httpx.Client(timeout=20, headers={"Authorization": f"Bearer {settings.resend_api_key}"}) as c:
            for i in range(0, len(to), 100):  # Resend batch limit
                batch = [{"from": settings.mail_from, "to": [addr], "subject": subject, "html": html_body.replace("{{email}}", addr)} for addr in to[i : i + 100]]
                r = c.post("https://api.resend.com/emails/batch", json=batch)
                if r.status_code >= 300:
                    log.error("resend batch failed: %s %s", r.status_code, r.text[:200])
                    continue
                sent += len(batch)
        return sent


class MemoryMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str]] = []

    def send(self, to: list[str], subject: str, html_body: str) -> int:
        self.sent.append((to, subject, html_body))
        return len(to)


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = ResendMailer() if settings.resend_api_key else MemoryMailer()
    return _mailer
