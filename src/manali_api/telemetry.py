"""Read-only view of what Application Insights holds, for the admin page.

The function's managed identity reads the component (Bicep grants it Monitoring Reader) through
the Application Insights query API; no key is stored. The component is shared with the owner's
other sites, so every query is limited to the site's browser role (`manali-web`) or this API's
role. The owner's own pages (/admin, /sign-in) are left out of the visitor numbers.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal, Protocol

from .settings import settings

Range = Literal["24h", "7d"]
# window and chart bucket per range: 24 hourly bars, 28 six-hour bars
WINDOWS: dict[str, tuple[str, str]] = {"24h": ("24h", "1h"), "7d": ("7d", "6h")}
NOW_WINDOW = "5m"

WEB = 'cloud_RoleName == "manali-web"'
API = 'cloud_RoleName startswith "manali-" and cloud_RoleName endswith "-api"'
# parse_url reads the home page's path as empty, so it is put back as "/"
VISITOR = f'{WEB} | extend page = tostring(parse_url(url).Path) | extend page = iff(isempty(page), "/", page) | where not(page startswith "/admin" or page startswith "/sign-in")'


def queries(r: Range) -> dict[str, str]:
    ago, step = WINDOWS[r]
    since = f"timestamp > ago({ago})"
    return {
        "now": f"""pageViews | where timestamp > ago({NOW_WINDOW}) | where {VISITOR}
            | summarize people = dcount(user_Id), pageviews = count() by page | order by people desc, pageviews desc | take 8""",
        "nowPeople": f"""pageViews | where timestamp > ago({NOW_WINDOW}) | where {VISITOR} | summarize people = dcount(user_Id)""",
        "totals": f"""union (pageViews | where {since} | where {VISITOR} | extend k = "v"),
                (customEvents | where {since} and {WEB} and name == "page_engaged" | extend page = tostring(customDimensions.page)
                    | where not(page startswith "/admin" or page startswith "/sign-in") | extend k = "g"),
                (exceptions | where {since} and {WEB} | extend k = "e"),
                (requests | where {since} and {API} | extend k = "r")
            | summarize pageviews = countif(k == "v"), people = dcountif(user_Id, k == "v"), sessions = dcountif(session_Id, k == "v"),
                seconds = sumif(todouble(customMeasurements.seconds), k == "g"), depth = avgif(todouble(customMeasurements.depth), k == "g"),
                errors = countif(k == "e"), calls = countif(k == "r"), failed = countif(k == "r" and success == false)""",
        "series": f"""union (pageViews | where {since} | where {VISITOR} | extend k = "v"),
                (exceptions | where {since} and {WEB} | extend k = "e"),
                (requests | where {since} and {API} and success == false | extend k = "f")
            | make-series pageviews = countif(k == "v"), people = dcountif(user_Id, k == "v"), errors = countif(k != "v") default = 0
                on timestamp from bin(ago({ago}), {step}) to now() step {step}
            | mv-expand timestamp to typeof(datetime), pageviews to typeof(long), people to typeof(long), errors to typeof(long)
            | project t = timestamp, pageviews, people, errors""",
        "pages": f"""let eng = customEvents | where {since} and {WEB} and name == "page_engaged"
                | summarize seconds = sum(todouble(customMeasurements.seconds)), depth = avg(todouble(customMeasurements.depth))
                    by page = tostring(customDimensions.page);
            pageViews | where {since} | where {VISITOR} | summarize pageviews = count(), people = dcount(user_Id) by page
            | join kind = leftouter eng on page
            | project page, pageviews, people, seconds = round(coalesce(seconds, 0.0) / pageviews, 1), depth = round(coalesce(depth, 0.0))
            | order by pageviews desc | take 15""",
        "referrers": f"""pageViews | where {since} | where {VISITOR}
            | extend host = tostring(parse_url(tostring(customDimensions.refUri)).Host)
            | where isnotempty(host) and host != "manali.page"
            | summarize pageviews = count(), people = dcount(user_Id) by host | order by pageviews desc | take 10""",
        "events": f"""customEvents | where {since} and {WEB} and name !in ("page_engaged", "click")
            | summarize count = count(), people = dcount(user_Id) by name | order by count desc""",
        "outbound": f"""customEvents | where {since} and {WEB} and name == "outbound_click"
            | summarize count = count() by host = tostring(customDimensions.host) | order by count desc | take 10""",
        "devices": f"""customEvents | where {since} and {WEB} and name == "page_engaged"
            | summarize pageviews = count() by device = tostring(customDimensions.device) | order by pageviews desc""",
        "browsers": f"""pageViews | where {since} | where {VISITOR}
            | summarize people = dcount(user_Id) by browser = trim(" ", extract(@"^([^0-9]+)", 1, client_Browser)) | order by people desc | take 6""",
        "countries": f"""pageViews | where {since} | where {VISITOR}
            | summarize people = dcount(user_Id) by country = client_CountryOrRegion | order by people desc | take 10""",
        "errors": f"""exceptions | where {since} and {WEB}
            | summarize count = count(), people = dcount(user_Id), latest = max(timestamp), message = take_any(outerMessage) by problemId
            | order by count desc | take 10""",
        "api": f"""requests | where {since} and {API}
            | extend parts = split(tostring(parse_url(url).Path), "/")
            | extend route = iff(tostring(parts[2]) == "admin", strcat("/admin/", tostring(parts[3])), strcat("/", tostring(parts[2])))
            | summarize calls = count(), failed = countif(success == false), p95 = round(percentile(duration, 95)) by route
            | order by calls desc | take 12""",
    }


class Reader(Protocol):
    def query(self, kql: str) -> list[dict[str, Any]]: ...


class AppInsightsReader:
    """The Application Insights query API, signed in as the function's managed identity."""

    SCOPE = "https://api.applicationinsights.io/.default"

    def __init__(self, app_id: str) -> None:
        import httpx
        from azure.identity import DefaultAzureCredential

        self.url = f"https://api.applicationinsights.io/v1/apps/{app_id}/query"
        self.cred = DefaultAzureCredential()
        self.http = httpx.Client(timeout=25)

    def query(self, kql: str) -> list[dict[str, Any]]:
        token = self.cred.get_token(self.SCOPE).token
        res = self.http.post(self.url, json={"query": kql, "timespan": "P8D"}, headers={"authorization": f"Bearer {token}"})
        if res.status_code != 200:
            raise RuntimeError(f"Application Insights answered {res.status_code}: {res.text[:200]}")
        table = res.json()["tables"][0]
        names = [c["name"] for c in table["columns"]]
        return [dict(zip(names, row, strict=True)) for row in table["rows"]]


_reader: Reader | None = None
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
# one report run per range at a time: a second tab or a reload waits for it instead of querying again
_running: dict[str, threading.Lock] = {r: threading.Lock() for r in WINDOWS}
CACHE_SECONDS = 20  # a second tab or a reload within 20s costs nothing


def get_reader() -> Reader | None:
    global _reader
    if _reader is None and settings.appinsights_app_id:
        _reader = AppInsightsReader(settings.appinsights_app_id)
    return _reader


def _run(reader: Reader, qs: dict[str, str]) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=len(qs)) as pool:
        futures = {name: pool.submit(reader.query, kql) for name, kql in qs.items()}
        return {name: f.result() for name, f in futures.items()}


def _now(out: dict[str, Any]) -> dict[str, Any]:
    people = out.pop("nowPeople")
    return {"people": people[0]["people"] if people else 0, "pages": out.pop("now"), "window": NOW_WINDOW}


def live() -> dict[str, Any]:
    """Just who is on the site in the last few minutes: two small queries, for frequent polling."""
    reader = get_reader()
    if reader is None:
        return {"configured": False}
    qs = queries("24h")
    return {"configured": True, **_now(_run(reader, {k: qs[k] for k in ("now", "nowPeople")}))}


def report(r: Range) -> dict[str, Any]:
    """Every section in one answer. Sections run in parallel; one failure fails the whole report,
    so the page never shows numbers that disagree with each other."""
    reader = get_reader()
    if reader is None:
        return {"configured": False}
    with _running[r]:
        with _lock:
            hit = _cache.get(r)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
        out = _run(reader, queries(r))
        totals = out["totals"][0] if out["totals"] else {}
        out["totals"] = {k: (v or 0) for k, v in totals.items()}
        out["now"] = _now(out)
        out.update(configured=True, range=r, step=WINDOWS[r][1])
        with _lock:
            _cache[r] = (time.monotonic(), out)
        return out
