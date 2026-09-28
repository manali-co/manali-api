"""Email through Resend. The HTML mirrors the EmailShell / EmailTemplates components in the
Claude Design project: 600px table frame, paper ground, one white card, avatar mark + wordmark
header, grey footer, dark mode through prefers-color-scheme. Reply notifications for comments
are GitHub's own, since comments live in Discussions; the template is here for completeness."""
from __future__ import annotations

import html
import logging
from typing import Any, Protocol

import httpx

from .settings import settings

log = logging.getLogger("manali.mail")

E = {
    "paper": "#F7F5EE", "white": "#FFFFFF", "ink": "#23224A", "ink2": "#55547A", "ink3": "#84839E", "line": "#E3DFD2",
    "night": "#16152E", "paper2dark": "#B9B8D3", "linedark": "rgba(247,245,238,0.14)",
    "indigo": "#5B63C7", "indigoSoft": "#9AA0EA", "gold": "#F2B84B",
    "font": "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "display": "Comfortaa, Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
}
LABELS = {"yapp": "Yapp", "what-should-we-watch": "What Should We Watch", "spark": "Spark", "manali": "manali apps"}
DOTS = {"yapp": "#E8B79A", "what-should-we-watch": "#EE8079", "spark": "#E03C7A", "manali": "#5B63C7"}
AVATAR = "https://raw.githubusercontent.com/manali-co/.github/main/brand/png/github-avatar-500.png"

CSS = f"""
.ma-email a{{color:{E['indigo']}}}
@media (prefers-color-scheme: dark){{
  .ma-email .ma-bg{{background:{E['night']} !important}}
  .ma-email .ma-card{{background:{E['ink']} !important;border-color:{E['linedark']} !important}}
  .ma-email .ma-text{{color:{E['paper']} !important}}
  .ma-email .ma-muted{{color:{E['paper2dark']} !important}}
  .ma-email .ma-faint{{color:#8785AA !important}}
  .ma-email .ma-quote{{background:{E['night']} !important;border-color:{E['gold']} !important}}
  .ma-email .ma-apps{{color:{E['gold']} !important}}
  .ma-email a{{color:{E['indigoSoft']}}}
  .ma-email .ma-btn a{{color:{E['night']} !important;background:{E['indigoSoft']} !important}}
}}
@media (max-width: 620px){{ .ma-email .ma-wrap{{width:100% !important}} .ma-email .ma-pad{{padding-left:20px !important;padding-right:20px !important}} }}
"""


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def shell(title: str, preheader: str, body: str, footer: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"><title>{esc(title)}</title><style>{CSS}</style></head>
<body class="ma-email" style="margin:0;background:{E['paper']};font-family:{E['font']}">
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:transparent">{esc(preheader)}</div>
<table role="presentation" class="ma-bg" width="100%" cellpadding="0" cellspacing="0" style="background:{E['paper']}"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" class="ma-wrap" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%">
<tr><td style="padding:0 0 20px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="vertical-align:middle"><img src="{AVATAR}" width="32" height="32" alt="" style="display:block;border-radius:8px"></td>
<td class="ma-text" style="vertical-align:middle;padding-left:10px;font-family:{E['display']};font-size:18px;color:{E['ink']}"><span style="font-weight:600">manali</span> <span class="ma-apps" style="color:{E['indigo']}">apps</span></td>
</tr></table></td></tr>
<tr><td class="ma-card ma-pad" style="background:{E['white']};border:1px solid {E['line']};border-radius:16px;padding:36px 40px">{body}</td></tr>
<tr><td class="ma-faint ma-pad" style="padding:24px 8px 0;font-size:13px;line-height:1.6;color:{E['ink3']}">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def button(label: str, url: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" class="ma-btn"><tr><td style="border-radius:999px;background:{E["indigo"]}">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:14px 24px;font-family:{E["font"]};font-size:16px;font-weight:500;color:{E["white"]};text-decoration:none;border-radius:999px">{esc(label)}</a></td></tr></table>')


def h1(text: str) -> str:
    return f'<h1 class="ma-text" style="margin:0 0 12px;font-family:{E["display"]};font-weight:500;font-size:26px;line-height:1.2;color:{E["ink"]}">{esc(text)}</h1>'


def p(text: str, muted: bool = False, small: bool = False, margin: str = "0 0 16px", raw: bool = False) -> str:
    cls = "ma-muted" if muted else "ma-text"
    color = E["ink2"] if muted else E["ink"]
    return f'<p class="{cls}" style="margin:{margin};font-size:{14 if small else 16}px;line-height:1.6;color:{color}">{text if raw else esc(text)}</p>'


def default_footer(unsub_url: str, reason: str = "You got this because you subscribed at manali apps.") -> str:
    addr = f" manali apps · {esc(settings.mail_address)}." if settings.mail_address else ""
    return f'{esc(reason)} <a href="{esc(unsub_url)}" style="color:{E["ink3"]}">Unsubscribe</a> in one click.{addr}'


def confirm_email(confirm_url: str) -> tuple[str, str]:
    body = (h1("Confirm your subscription")
            + p("Someone, probably you, asked for new posts from manali apps by email. One click and you're in.")
            + button("Yes, that was me", confirm_url))
    return "Confirm your subscription", shell("Confirm your subscription", "One click and you're in.", body, "If you didn't ask for this, ignore it and nothing happens.")


def welcome_email(unsub_url: str) -> tuple[str, str]:
    body = (h1("You're in.")
            + p("Thanks. Here's the deal: we email when something ships or breaks. No schedule, no digest, no \"top picks\". Some posts are written by the coding agents doing the work; we always say which.")
            + p("Three things so far: Yapp, a macOS voice assistant that acts while you're still talking; What Should We Watch, a mood-driven film picker; and Spark, a personality test that writes its own questions.")
            + button("Read what's there", settings.site_url + "/blog/"))
    return "You're in", shell("You're in", "You're in. Here's what to expect.", body, default_footer(unsub_url))


def post_email(post: dict[str, Any], unsub_url: str) -> tuple[str, str]:
    project = post.get("project") or "manali"
    dot = DOTS.get(project, E["indigo"])
    if post.get("cover"):
        hero = f'<img src="{esc(post["cover"])}" width="518" alt="" style="display:block;width:100%;border-radius:12px;margin-bottom:24px;border:1px solid {E["line"]}">'
    else:
        inner = esc(post["coverText"]) if post.get("coverText") else f'<span style="display:inline-block;width:14px;height:14px;border-radius:7px;background:{dot}"></span>'
        hero = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px"><tr>'
                f'<td class="ma-quote" style="background:{E["paper"]};border:1px solid {E["line"]};border-radius:12px;height:180px;text-align:center;font-family:{E["display"]};font-size:44px;color:{E["ink"]};vertical-align:middle">{inner}</td></tr></table>')
    kicker = (f'<p class="ma-faint" style="margin:0 0 10px;font-size:13px;color:{E["ink3"]};letter-spacing:0.04em;text-transform:uppercase">'
              f'<span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:{dot};margin-right:8px;vertical-align:middle"></span>{esc(LABELS.get(project, "manali apps"))}</p>')
    byline = post.get("author", "Manali")
    if post.get("date"):
        byline += " · " + post["date"]
    body = (hero + kicker + h1(post["title"]) + p(post.get("summary", ""), muted=True)
            + p(byline, muted=True, small=True, margin="0 0 24px") + button("Read it", post["url"]))
    return f"New post: {post['title']}", shell(post["title"], post.get("summary", ""), body, default_footer(unsub_url))


def unsubscribed_email() -> tuple[str, str]:
    body = (h1("You're unsubscribed.")
            + p(f'Done. No more email from us. The posts stay on the site if you ever want them, and you can <a href="{esc(settings.site_url)}/subscribe/">subscribe again</a> any time. We won\'t mention this.', raw=True))
    return "You're unsubscribed", shell("You're unsubscribed", "Done. No more email from us.", body, "This is the last one.")


class Mailer(Protocol):
    def send(self, to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> int: ...
    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "") -> int: ...


def message(to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> dict[str, Any]:
    m: dict[str, Any] = {"from": settings.mail_from, "to": [to], "subject": subject.replace("\r", " ").replace("\n", " "), "html": html_body}
    if headers:
        m["headers"] = headers
    return m


def unsubscribe_headers(unsub_url: str) -> dict[str, Any]:
    """RFC 8058 one-click unsubscribe; Gmail and Yahoo expect it on list mail."""
    return {"List-Unsubscribe": f"<{unsub_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


class ResendMailer:
    """Batches of 100 (Resend's limit), retried on 429/5xx with backoff, idempotent per batch so a
    retried announce never double-sends. Returns how many messages Resend accepted."""

    BATCH = 100
    RETRIES = 4

    def send(self, to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> int:
        return self.send_many([message(to, subject, html_body, headers)])

    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "") -> int:
        if not settings.resend_api_key:
            log.error("RESEND_API_KEY missing; %d message(s) NOT sent", len(messages))
            return 0
        import time

        sent = 0
        with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {settings.resend_api_key}"}) as c:
            for i in range(0, len(messages), self.BATCH):
                batch = messages[i : i + self.BATCH]
                headers = {"Idempotency-Key": f"{idempotency}/{i // self.BATCH}"[:256]} if idempotency else {}
                for attempt in range(self.RETRIES):
                    try:
                        r = c.post("https://api.resend.com/emails/batch", json=batch, headers=headers)
                    except httpx.HTTPError as e:
                        log.warning("resend batch %d attempt %d: %s", i // self.BATCH, attempt, e)
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if r.status_code < 300:
                        sent += len(batch)
                        break
                    if r.status_code == 429 or r.status_code >= 500:
                        wait = float(r.headers.get("retry-after") or 1.5 * (attempt + 1))
                        log.warning("resend batch %d: %s, retrying in %.1fs", i // self.BATCH, r.status_code, wait)
                        time.sleep(min(wait, 20))
                        continue
                    log.error("resend batch %d failed: %s %s", i // self.BATCH, r.status_code, r.text[:200])
                    break
                else:
                    log.error("resend batch %d gave up after %d attempts", i // self.BATCH, self.RETRIES)
        return sent


class MemoryMailer:
    """Only for MANALI_ENV=local or test. Never a stand-in for a missing key in prod."""

    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str]] = []

    def send(self, to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> int:
        self.sent.append(([to], subject, html_body))
        return 1

    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "") -> int:
        for m in messages:
            self.sent.append((m["to"], m["subject"], m["html"]))
        return len(messages)


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = MemoryMailer() if (settings.fake_allowed and not settings.resend_api_key) else ResendMailer()
    return _mailer
