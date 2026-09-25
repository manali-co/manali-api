"""Email through Resend. The HTML mirrors the EmailShell / EmailTemplates components in the
Claude Design project: 600px table frame, paper ground, one white card, avatar mark + wordmark
header, grey footer, dark mode through prefers-color-scheme. Reply notifications for comments
are GitHub's own, since comments live in Discussions; the template is here for completeness."""
from __future__ import annotations

import html
import logging
from typing import Protocol

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
LABELS = {"yapp": "Yapp", "what-should-we-watch": "What Should We Watch", "manali": "manali apps"}
DOTS = {"yapp": "#E8B79A", "what-should-we-watch": "#EE8079", "manali": "#5B63C7"}
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
            + button("Yes, that was me", confirm_url)
            + p("If it wasn't you, ignore this and nothing happens.", muted=True, small=True, margin="20px 0 0"))
    return "Confirm your subscription", shell("Confirm your subscription", "One click and you're in.", body, "If you didn't ask for this, ignore it and nothing happens.")


def welcome_email(unsub_url: str) -> tuple[str, str]:
    body = (h1("You're in.")
            + p("Thanks. Here's the deal: we email when something ships or breaks. No schedule, no digest, no \"top picks\". Some posts are written by the coding agents doing the work; we always say which.")
            + p("Two projects so far: Yapp, a macOS voice assistant that acts while you're still talking, and What Should We Watch, a mood-driven film picker.")
            + button("Read what's there", settings.site_url + "/blog/"))
    return "You're in", shell("You're in", "You're in. Here's what to expect.", body, default_footer(unsub_url))


def post_email(post: dict, unsub_url: str) -> tuple[str, str]:
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


def reply_email(post_title: str, replier: str, reply: str, url: str, off_url: str) -> tuple[str, str]:
    body = (h1(f"Someone replied to your comment on {post_title}")
            + p(f"{replier} wrote:", muted=True, small=True)
            + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px"><tr><td class="ma-quote ma-text" style="background:{E["paper"]};border-left:3px solid {E["gold"]};border-radius:0 12px 12px 0;padding:16px 20px;font-size:16px;line-height:1.6;color:{E["ink"]}">{esc(reply)}</td></tr></table>'
            + button("View on GitHub", url))
    footer = f'<a href="{esc(off_url)}" style="color:{E["ink3"]}">Turn off reply emails</a>. You get these because you commented via GitHub.'
    return f"Someone replied to your comment on {post_title}", shell("Reply", f"{replier} replied on {post_title}", body, footer)


def unsubscribed_email() -> tuple[str, str]:
    body = (h1("You're unsubscribed.")
            + p(f'Done. No more email from us. The posts stay on the site if you ever want them, and you can <a href="{esc(settings.site_url)}/subscribe/">subscribe again</a> any time. We won\'t mention this.', raw=True))
    return "You're unsubscribed", shell("You're unsubscribed", "Done. No more email from us.", body, "This is the last one.")


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
                batch = [{"from": settings.mail_from, "to": [addr], "subject": subject, "html": html_body} for addr in to[i : i + 100]]
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
