"""Email through Resend. The HTML mirrors the EmailShell / EmailTemplates components in the
Claude Design project: 600px table frame, paper ground, one white card, avatar mark + wordmark
header, grey footer, dark mode through prefers-color-scheme. Reply notifications for comments
are GitHub's own, since comments live in Discussions; the template is here for completeness."""
from __future__ import annotations

import html
import logging
import re
from email.utils import formataddr, parseaddr
from typing import Any, Protocol

import httpx

from .settings import settings

log = logging.getLogger("manali.mail")

E = {
    "paper": "#F7F5EE", "white": "#FFFFFF", "ink": "#23224A", "ink2": "#55547A", "ink3": "#84839E", "line": "#E3DFD2", "sunken": "#EFEBDF",
    "night": "#0C0C12", "nightRaised": "#16161F", "nightSunken": "#08080C", "paper2dark": "#B9B8D3", "ink3dark": "#8785AA", "linedark": "#2A2A36",
    "indigo": "#5B63C7", "indigoSoft": "#9AA0EA", "gold": "#F2B84B", "goldText": "#8A5A00", "halo": "#FBE7B8", "haloDark": "#3A2F17",
    "todo": "#C9C4B4", "todoDark": "#55546E",
    "font": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "display": "Comfortaa, 'Varela Round', 'Arial Rounded MT Bold', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
    "mono": "'JetBrains Mono', SFMono-Regular, Menlo, Consolas, 'Courier New', monospace",
}
LABELS = {"yapp": "Yapp", "what-should-we-watch": "What Should We Watch", "spark": "Spark", "portfolio": "Personal Portfolio", "manali": "manali apps"}
DOTS = {"yapp": "#E8B79A", "what-should-we-watch": "#EE8079", "spark": "#E03C7A", "portfolio": "#D2491F", "manali": "#5B63C7"}
AVATAR = "https://raw.githubusercontent.com/manali-co/.github/main/brand/png/github-avatar-500.png"
OWNER_AVATAR = "https://github.com/ayushm-agrawal.png?size=96"


def _dark(p: str) -> str:
    return f"""
{p} .ma-bg{{background:{E['night']} !important}}
{p} .ma-card{{background:{E['nightRaised']} !important;border-color:{E['linedark']} !important}}
{p} .ma-sunk{{background:{E['nightSunken']} !important;border-color:{E['linedark']} !important}}
{p} .ma-text{{color:{E['paper']} !important}}
{p} .ma-muted{{color:{E['paper2dark']} !important}}
{p} .ma-faint{{color:{E['ink3dark']} !important}}
{p} .ma-rule{{border-color:{E['linedark']} !important}}
{p} .ma-quote{{background:{E['night']} !important;border-color:{E['gold']} !important}}
{p} .ma-apps,{p} .ma-sun{{color:{E['gold']} !important}}
{p} .ma-dot-read{{background:{E['indigoSoft']} !important;border-color:{E['indigoSoft']} !important}}
{p} .ma-dot-now{{background:{E['gold']} !important;border-color:{E['haloDark']} !important}}
{p} .ma-dot-todo{{background:{E['nightRaised']} !important;border-color:{E['todoDark']} !important}}
{p} .ma-line-read{{border-color:{E['indigoSoft']} !important}}
{p} .ma-line-todo{{border-color:{E['todoDark']} !important}}
{p} a{{color:{E['indigoSoft']}}}
{p} .ma-btn td{{background:{E['indigoSoft']} !important}}
{p} .ma-btn a{{color:{E['night']} !important}}
{p} .ma-link{{color:{E['indigoSoft']} !important}}"""


def _narrow(p: str) -> str:
    return f"""
{p} .ma-wrap{{width:100% !important}}
{p} .ma-outer{{padding:20px 12px !important}}
{p} .ma-pad{{padding-left:20px !important;padding-right:20px !important}}
{p} .ma-padv{{padding-top:24px !important;padding-bottom:24px !important}}
{p} .ma-h2{{font-size:21px !important}}
{p} .ma-img{{width:100% !important;height:auto !important}}"""


# Dark mode three ways, as in the design system's EmailShell: prefers-color-scheme (Apple Mail, iOS,
# Outlook for Mac), [data-ogsc] (Outlook.com and the Outlook apps), and .ma-dark (forced, previews only).
# Gmail ignores all three and inverts on its own; the palette survives it.
CSS = (
    "@import url('https://fonts.googleapis.com/css2?family=Comfortaa:wght@500;600&family=Inter:wght@400;500;600&display=swap');\n"
    f".ma-email a{{color:{E['indigo']}}}\n"
    f"@media (prefers-color-scheme: dark){{{_dark('.ma-email:not(.ma-light)')}}}\n"
    f"{_dark('[data-ogsc] .ma-email')}\n{_dark('.ma-email.ma-dark')}\n"
    f"@media (max-width: 620px){{{_narrow('.ma-email')}}}\n"
)


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def shell(title: str, preheader: str, body: str, footer: str, theme: str | None = None) -> str:
    """600px table frame: paper ground, avatar mark + wordmark, one white card, footer. `theme`
    ("dark" or "light") forces a look for the admin preview; sent mail leaves it None."""
    cls = "ma-email" + {"dark": " ma-dark", "light": " ma-light"}.get(theme or "", "")
    pad = "&nbsp;&zwnj;" * 40  # keeps the inbox preview from pulling in body text
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"><title>{esc(title)}</title><style>{CSS}</style></head>
<body class="{cls}" style="margin:0;background:{E['paper']};font-family:{E['font']}">
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:transparent;opacity:0">{esc(preheader)}{pad}</div>
<table role="presentation" class="ma-bg" width="100%" cellpadding="0" cellspacing="0" style="background:{E['paper']}"><tr><td class="ma-outer" align="center" style="padding:32px 16px">
<table role="presentation" class="ma-wrap" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%">
<tr><td style="padding:0 0 20px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="vertical-align:middle"><img src="{AVATAR}" width="32" height="32" alt="" style="display:block;border-radius:8px"></td>
<td class="ma-text" style="vertical-align:middle;padding-left:10px;font-family:{E['display']};font-size:18px;color:{E['ink']}"><span style="font-weight:600">manali</span> <span class="ma-apps" style="color:{E['indigo']}">apps</span></td>
</tr></table></td></tr>
<tr><td class="ma-card ma-pad ma-padv" style="background:{E['white']};border:1px solid {E['line']};border-radius:16px;padding:36px 40px">{body}</td></tr>
<tr><td class="ma-faint ma-pad" style="padding:24px 8px 0;font-size:13px;line-height:1.6;color:{E['ink3']}">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def button(label: str, url: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" class="ma-btn"><tr><td style="border-radius:999px;background:{E["indigo"]}">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:14px 26px;font-family:{E["font"]};font-size:16px;font-weight:600;line-height:20px;color:{E["white"]};text-decoration:none;border-radius:999px">{esc(label)}</a></td></tr></table>')


def h1(text: str) -> str:
    return f'<h1 class="ma-text" style="margin:0 0 12px;font-family:{E["display"]};font-weight:500;font-size:26px;line-height:1.2;color:{E["ink"]}">{esc(text)}</h1>'


def p(text: str, muted: bool = False, small: bool = False, margin: str = "0 0 16px", raw: bool = False) -> str:
    cls = "ma-muted" if muted else "ma-text"
    color = E["ink2"] if muted else E["ink"]
    return f'<p class="{cls}" style="margin:{margin};font-size:{14 if small else 16}px;line-height:1.6;color:{color}">{text if raw else esc(text)}</p>'


def default_footer(unsub_url: str, reason: str = "You got this because you subscribed at manali apps.") -> str:
    addr = f" manali apps · {esc(settings.mail_address)}." if settings.mail_address else ""
    return f'{esc(reason)} <a href="{esc(unsub_url)}" style="color:{E["ink3"]}">Unsubscribe</a> in one click.{addr}'


def confirm_email(confirm_url: str, series_title: str = "") -> tuple[str, str]:
    if series_title:
        body = (h1(f"Follow {series_title}?")
                + p(f"Someone, probably you, asked for an email when the next part of {series_title} goes up on manali apps. One click and it's set. Nothing else gets sent.")
                + button("Yes, that was me", confirm_url))
        return f"Confirm: follow {series_title}", shell("Confirm your follow", "One click and the next part comes to you.", body, "If you didn't ask for this, ignore it and nothing happens.")
    body = (h1("Confirm your subscription")
            + p("Someone, probably you, asked for new posts from manali apps by email. One click and you're in.")
            + button("Yes, that was me", confirm_url))
    return "Confirm your subscription", shell("Confirm your subscription", "One click and you're in.", body, "If you didn't ask for this, ignore it and nothing happens.")


def follow_email(series_title: str, series_url: str, everything: bool, unsub_url: str) -> tuple[str, str]:
    """For an address that is already confirmed: following one more series needs no new opt-in,
    but the inbox still hears about it, so the site's "check your inbox" is always true."""
    line = ("You already get every new post, so nothing changes. This just notes that you asked."
            if everything else "The next part comes to your inbox the day it goes up. Nothing else.")
    body = h1(f"You're following {series_title}.") + p(line) + button("See every part", series_url)
    return f"You're following {series_title}", shell("You're following a series", line, body, default_footer(unsub_url))


def welcome_email(unsub_url: str, series_title: str = "", series_url: str = "") -> tuple[str, str]:
    if series_title:
        body = (h1(f"You're following {series_title}.")
                + p("The next part comes to your inbox the day it goes up. Nothing else, and one click to stop.")
                + button("See every part", series_url or settings.site_url + "/blog/"))
        reason = f"You got this because you followed {series_title} at manali apps."
        return f"You're following {series_title}", shell("You're following a series", "The next part comes to you.", body, default_footer(unsub_url, reason))
    body = (h1("You're in.")
            + p("Thanks. Here's the deal: you get an email when there's a post, and there's a post only when there's something worth reading. Findings, thoughts, the odd evening. No schedule, no digest, no \"top picks\". Some posts are written by the coding agents doing the work; we always say which.")
            + p("Three things so far: Yapp, a macOS voice assistant that acts while you're still talking; What Should We Watch, a mood-driven film picker; and Spark, a personality test that writes its own questions.")
            + button("Read what's there", settings.site_url + "/blog/"))
    return "You're in", shell("You're in", "You're in. Here's what to expect.", body, default_footer(unsub_url))


def _notes(note: str) -> list[str]:
    return [n.strip() for n in re.split(r"\n\s*\n", note or "") if n.strip()]


def _first_sentence(text: str) -> str:
    m = re.match(r"^.*?[.!?](\s|$)", text, re.S)
    return (m.group(0) if m else text).strip()


def _clip(text: str, n: int = 120) -> str:
    return text if len(text) <= n else re.sub(r"\s+\S*$", "", text[: n - 1]) + "…"


def post_meta(post: dict[str, Any], note: str = "") -> dict[str, str]:
    """Sender name, subject and preheader for the letter design (Claude Design: EmailNewPostMeta).
    The admin preview and the send use the same values."""
    title = post.get("title") or "A new post"
    series_title, part = post.get("seriesTitle") or "", post.get("seriesPart")
    subject = f"{series_title}, part {part}: {title}" if series_title and part else title
    notes, summary = _notes(note), post.get("summary") or ""
    if notes:
        pre = _first_sentence(notes[0])
    elif post.get("authorKind") == "agent":
        pre = f"{post.get('authorName') or 'Claude'} wrote this one for {LABELS.get(post.get('project') or 'manali', 'manali apps')}. {summary}"
    elif series_title and part:
        pre = f"Part {part} of {post.get('seriesTotal') or part}. {summary}"
    else:
        pre = summary
    return {"fromName": "Ayush at manali apps", "subject": subject, "preheader": _clip(pre)}


def sender(name: str) -> str:
    """The configured From address under another display name."""
    return formataddr((name, parseaddr(settings.mail_from)[1]))


_kick = f"margin:0 0 12px;font-family:{E['mono']};font-size:12px;line-height:18px;letter-spacing:0.08em;text-transform:uppercase;color:{E['ink3']}"


def _kicker(post: dict[str, Any]) -> str:
    project = post.get("project") or "manali"
    if post.get("seriesTitle") and post.get("seriesPart"):
        inner = (f'<span class="ma-sun" style="color:{E["goldText"]}">Part {post["seriesPart"]} of {post.get("seriesTotal") or post["seriesPart"]}</span>'
                 f' · {esc(post["seriesTitle"])}')
    else:
        dot = f'<span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:{DOTS.get(project, E["indigo"])};margin-right:8px;vertical-align:1px"></span>'
        inner = dot + esc(LABELS.get(project, "manali apps")) + (f" · {esc(post['readTime'])}" if post.get("readTime") else "")
    return f'<p class="ma-faint" style="{_kick}">{inner}</p>'


def _track(part: int, total: int) -> str:
    """The series line as table cells, no SVG: published parts indigo, this part the sun with its
    halo, parts not written yet dashed. Outlook squares the dots; the line still reads."""
    cells = []
    for n in range(1, total + 1):
        state = "read" if n < part else "now" if n == part else "todo"
        if n > 1:
            lit = state != "todo"
            cells.append(f'<td style="padding:0 3px;vertical-align:middle"><div class="{"ma-line-read" if lit else "ma-line-todo"}" '
                         f'style="width:22px;height:0;border-top:2px {"solid" if lit else "dashed"} {E["indigo"] if lit else E["todo"]};font-size:0;line-height:0">&nbsp;</div></td>')
        size = 14 if state == "now" else 10
        look = {"now": f"background:{E['gold']};border:3px solid {E['halo']}", "todo": f"background:{E['white']};border:2px dashed {E['ink3']}",
                "read": f"background:{E['indigo']};border:2px solid {E['indigo']}"}[state]
        cells.append(f'<td style="vertical-align:middle"><div class="ma-dot-{state}" style="width:{size}px;height:{size}px;border-radius:50%;font-size:0;line-height:0;{look}">&nbsp;</div></td>')
    return f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px"><tr>{"".join(cells)}</tr></table>'


def _byline(post: dict[str, Any], size: int = 28) -> str:
    project = post.get("project") or "manali"
    if post.get("authorKind") == "agent":
        img = f'<img src="{esc(settings.site_url)}/email/agent-{esc(project)}@2x.png" width="{size}" height="{size}" alt="" style="display:block;border-radius:{round(size * 0.26)}px">'
        line1 = f"{post.get('authorName') or 'Claude'} for {LABELS.get(project, 'manali apps')}"
        line2 = " · ".join(x for x in (f"by {post.get('authorOwner')}" if post.get("authorOwner") else "", post.get("date") or "") if x)
    else:
        img = f'<img src="{OWNER_AVATAR}" width="{size}" height="{size}" alt="" style="display:block;border-radius:50%">'
        line1, line2 = post.get("authorName") or post.get("author") or "Ayush", post.get("date") or ""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 24px"><tr>'
            f'<td style="vertical-align:middle;width:{size}px">{img}</td>'
            f'<td style="vertical-align:middle;padding-left:10px;font-size:14px;line-height:20px">'
            f'<span class="ma-text" style="display:block;color:{E["ink"]};font-weight:600">{esc(line1)}</span>'
            + (f'<span class="ma-faint" style="display:block;color:{E["ink3"]}">{esc(line2)}</span>' if line2 else "")
            + "</td></tr></table>")


def _cover(post: dict[str, Any]) -> str:
    project = post.get("project") or "manali"
    if post.get("cover"):
        return (f'<img class="ma-img" src="{esc(post["cover"])}" width="516" alt="" '
                f'style="display:block;width:100%;max-width:516px;height:auto;border-radius:13px 13px 0 0">')
    inner = esc(post["coverText"]) if post.get("coverText") else f'<span style="display:inline-block;width:14px;height:14px;border-radius:7px;background:{DOTS.get(project, E["indigo"])}"></span>'
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td class="ma-sunk ma-text" height="180" '
            f'style="height:180px;background:{E["sunken"]};border-radius:13px 13px 0 0;text-align:center;vertical-align:middle;font-family:{E["display"]};font-size:44px;color:{E["ink"]}">{inner}</td></tr></table>')


def post_email(post: dict[str, Any], unsub_url: str, reason: str = "", note: str = "", stop_series_url: str = "", theme: str | None = None) -> tuple[str, str]:
    """The new-post email, "letter" design from Claude Design (EmailNewPost design="letter"): an
    optional note from Ayush opens it, signed with his photo; the post sits below as a card with
    cover, kicker (or the series part and its timeline), title, summary, byline and Read it.
    `stop_series_url` is for series followers: their footer offers stopping just that series."""
    meta = post_meta(post, note)
    para = f"margin:0 0 18px;font-size:17px;line-height:1.65;color:{E['ink']}"
    opening = ""
    if notes := _notes(note):
        opening = ("".join(f'<p class="ma-text" style="{para}">{esc(n)}</p>' for n in notes)
                   + f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="vertical-align:middle;width:40px">'
                   f'<img src="{OWNER_AVATAR}" width="40" height="40" alt="" style="display:block;border-radius:50%"></td>'
                   f'<td style="vertical-align:middle;padding-left:12px"><span class="ma-text" style="display:block;font-family:{E["display"]};font-size:17px;font-weight:600;line-height:22px;color:{E["ink"]}">Ayush</span>'
                   f'<span class="ma-faint" style="display:block;font-size:13px;line-height:18px;color:{E["ink3"]}">manali apps</span></td></tr></table>'
                   '<div style="height:28px;line-height:28px;font-size:0">&nbsp;</div>')
    part = int(post.get("seriesPart") or 0)
    track = _track(part, int(post.get("seriesTotal") or part)) if post.get("seriesTitle") and part else ""
    summary = f'<p class="ma-muted" style="margin:0 0 18px;font-size:15px;line-height:1.6;color:{E["ink2"]}">{esc(post["summary"])}</p>' if post.get("summary") else ""
    card = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="ma-sunk" style="background:{E["paper"]};border:1px solid {E["line"]};border-radius:14px;border-collapse:separate">'
            f'<tr><td style="padding:0"><a href="{esc(post["url"])}" style="display:block;text-decoration:none">{_cover(post)}</a></td></tr>'
            f'<tr><td class="ma-pad" style="padding:22px 24px 24px">{_kicker(post)}{track}'
            f'<h2 class="ma-text ma-h2" style="margin:0 0 10px;font-family:{E["display"]};font-weight:500;font-size:23px;line-height:1.25;color:{E["ink"]}">{esc(post["title"])}</h2>'
            f'{summary}{_byline(post)}{button("Read it", post["url"])}</td></tr></table>')
    missed = ""
    if track and part > 1 and post.get("seriesUrl"):
        earlier = "Part 1 is" if part == 2 else f"Parts 1 to {part - 1} are"
        missed = (f'<div style="height:16px;font-size:0;line-height:16px">&nbsp;</div><p class="ma-faint" style="margin:0;font-size:13px;line-height:18px;color:{E["ink3"]}">'
                  f'{earlier} up if you missed {"it" if part == 2 else "them"}. <a href="{esc(post["seriesUrl"])}" class="ma-link" style="color:{E["indigo"]}">See the series</a></p>')
    if stop_series_url:
        footer = (f'You got this because you follow {esc(post.get("seriesTitle") or "this series")} on manali apps. '
                  f'<a href="{esc(stop_series_url)}" style="color:{E["ink3"]}">Stop following this series</a> or '
                  f'<a href="{esc(unsub_url)}" style="color:{E["ink3"]}">unsubscribe from everything</a>, one click each.')
        if settings.mail_address:
            footer += f" manali apps · {esc(settings.mail_address)}."
    else:
        footer = default_footer(unsub_url, reason) if reason else default_footer(unsub_url)
    return meta["subject"], shell(post["title"], meta["preheader"], opening + card + missed, footer, theme)


def reply_notice(post_title: str, post_url: str, text: str, name: str, email: str, admin_url: str) -> tuple[str, str]:
    """To the owner: someone replied to a post. Plain, with the reply quoted."""
    who = name or "Someone"
    contact = f" · {esc(email)}" if email else " · no email left"
    quote = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px"><tr>'
             f'<td class="ma-quote ma-text" style="background:{E["paper"]};border-left:3px solid {E["gold"]};border-radius:0 12px 12px 0;padding:16px 20px;font-size:16px;line-height:1.6;color:{E["ink"]};white-space:pre-wrap">{esc(text)}</td></tr></table>')
    body = (h1(f"{who} replied to “{post_title}”") + p(f"{esc(who)}{contact}", muted=True, small=True, raw=True) + quote
            + button("Open the post", post_url))
    footer = f'All replies are on <a href="{esc(admin_url)}" style="color:{E["ink3"]}">your admin page</a>. Reply to this email to answer them directly, if they left an address.'
    return f"Reply on “{post_title}”", shell("New reply", f"{who}: {text[:80]}", body, footer)


def _quote(text: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px"><tr>'
            f'<td class="ma-quote ma-text" style="background:{E["paper"]};border-left:3px solid {E["gold"]};border-radius:0 12px 12px 0;padding:16px 20px;font-size:16px;line-height:1.6;color:{E["ink"]};white-space:pre-wrap">{esc(text)}</td></tr></table>')


def comment_notice(post_title: str, post_url: str, text: str, who: str, held: bool, admin_url: str) -> tuple[str, str]:
    """To the owner: a new public comment. Held ones say so and point at the admin page."""
    head = f"{who} commented on “{post_title}”"
    line = ("It's waiting for you: first comments from a new browser need your approval before anyone else sees them."
            if held else "It's live on the post.")
    body = h1(head) + p(line, muted=True, small=True) + _quote(text) + button("Approve or remove" if held else "Open the post", admin_url if held else post_url)
    footer = f'Every comment is on <a href="{esc(admin_url)}" style="color:{E["ink3"]}">your admin page</a>.'
    return (f"Waiting: comment on “{post_title}”" if held else f"Comment on “{post_title}”"), shell("New comment", f"{who}: {text[:80]}", body, footer)


def comment_reply_email(post_title: str, post_url: str, who: str, text: str, stop_url: str) -> tuple[str, str]:
    """To a commenter who asked for it: someone replied to their comment."""
    body = h1(f"{who} replied to your comment") + p(f"On “{post_title}”.", muted=True, small=True) + _quote(text) + button("Read the thread", post_url)
    footer = (f'You got this because you asked for replies to your comment by email. '
              f'<a href="{esc(stop_url)}" style="color:{E["ink3"]}">Stop these emails</a> in one click.')
    return f"New reply on “{post_title}”", shell("New reply", f"{who}: {text[:80]}", body, footer)


def unsubscribed_email() -> tuple[str, str]:
    body = (h1("You're unsubscribed.")
            + p(f'Done. No more email from us. The posts stay on the site if you ever want them, and you can <a href="{esc(settings.site_url)}/subscribe/">subscribe again</a> any time. We won\'t mention this.', raw=True))
    return "You're unsubscribed", shell("You're unsubscribed", "Done. No more email from us.", body, "This is the last one.")


class Mailer(Protocol):
    def send(self, to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> int: ...
    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "", accepted: list[str] | None = None, failures: dict[str, str] | None = None) -> int: ...


def message(to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None, from_: str = "") -> dict[str, Any]:
    m: dict[str, Any] = {"from": from_ or settings.mail_from, "to": [to], "subject": subject.replace("\r", " ").replace("\n", " "), "html": html_body}
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

    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "", accepted: list[str] | None = None, failures: dict[str, str] | None = None) -> int:
        """`accepted` collects the addresses of every batch Resend took; `failures` maps the rest to why."""
        def fail(batch: list[dict[str, Any]], why: str) -> None:
            if failures is not None:
                failures.update((m["to"][0], why) for m in batch)

        if not settings.resend_api_key:
            log.error("RESEND_API_KEY missing; %d message(s) NOT sent", len(messages))
            fail(messages, "email not configured")
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
                        if accepted is not None:
                            accepted.extend(m["to"][0] for m in batch)
                        break
                    if r.status_code == 429 or r.status_code >= 500:
                        wait = float(r.headers.get("retry-after") or 1.5 * (attempt + 1))
                        log.warning("resend batch %d: %s, retrying in %.1fs", i // self.BATCH, r.status_code, wait)
                        time.sleep(min(wait, 20))
                        continue
                    log.error("resend batch %d failed: %s %s", i // self.BATCH, r.status_code, r.text[:200])
                    fail(batch, f"rejected by Resend ({r.status_code})")
                    break
                else:
                    log.error("resend batch %d gave up after %d attempts", i // self.BATCH, self.RETRIES)
                    fail(batch, "Resend didn't answer")
        return sent


class MemoryMailer:
    """Only for MANALI_ENV=local or test. Never a stand-in for a missing key in prod."""

    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str]] = []

    def send(self, to: str, subject: str, html_body: str, headers: dict[str, Any] | None = None) -> int:
        self.sent.append(([to], subject, html_body))
        return 1

    def send_many(self, messages: list[dict[str, Any]], idempotency: str = "", accepted: list[str] | None = None, failures: dict[str, str] | None = None) -> int:
        for m in messages:
            self.sent.append((m["to"], m["subject"], m["html"]))
            if accepted is not None:
                accepted.append(m["to"][0])
        return len(messages)


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = MemoryMailer() if (settings.fake_allowed and not settings.resend_api_key) else ResendMailer()
    return _mailer
