"""Every table this API keeps, as the admin page shows it: what each one is for, how many rows it
holds, and the rows themselves, newest first.

Values that work as credentials are shortened before they leave: a browser's client id (it is
what lets that browser react, post and skip moderation) and pending confirmation tokens. Hashes
and everything else are shown as stored.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol

from .settings import settings

TABLES: dict[str, str] = {
    "subscribers": "Email addresses, confirmed or waiting, and the series each one follows.",
    "events": "Every email sent, and for each announcement one row per recipient: hashed address, delivered or not.",
    "comments": "Every comment, live, waiting or removed, with the email of anyone who asked for reply notices.",
    "commenters": "Browsers whose comments post straight away, because you approved one of theirs.",
    "commentloves": "One row per browser per loved comment.",
    "reactions": "One row per browser per reaction on a post.",
    "replies": "Private notes sent from a post.",
    "replyquota": "Per-browser hourly counter that limits private notes.",
}
MAX_ROWS = 5000  # every table is far below this today; past it the count says "5000+"
SECRET_FIELDS = {"client", "confirm_token"}
# tables whose keys are a raw client id: replyquota's PartitionKey, reactions' RowKey "client|kind"
SECRET_KEYS = {"replyquota": "PartitionKey", "reactions": "RowKey"}


def mask(v: str) -> str:
    return f"{v[:4]}…" if len(v) > 4 else ("…" if v else "")


def clean(table: str, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, bytes):
            v = f"<{len(v)} bytes>"
        elif not isinstance(v, str | int | float | bool) and v is not None:
            v = str(v)
        if isinstance(v, str) and k in SECRET_FIELDS:
            v = mask(v)
        out[k] = v
    key = SECRET_KEYS.get(table)
    if key and isinstance(out.get(key), str):
        client, sep, rest = out[key].partition("|")
        out[key] = mask(client) + sep + rest
    return out


class Tables(Protocol):
    def rows(self, table: str) -> list[dict[str, Any]]: ...


class AzureTables:
    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            self.svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            self.svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())

    def rows(self, table: str) -> list[dict[str, Any]]:
        from azure.core.exceptions import ResourceNotFoundError

        out = []
        try:
            for e in self.svc.get_table_client(table).list_entities(results_per_page=1000):
                stamp = e.metadata.get("timestamp")
                out.append({**e, "Timestamp": stamp})
                if len(out) > MAX_ROWS:
                    break
        except ResourceNotFoundError:
            return []  # created on first use; nothing written yet
        return out


class MemoryTables:
    def __init__(self) -> None:
        self.data: dict[str, list[dict[str, Any]]] = {}

    def rows(self, table: str) -> list[dict[str, Any]]:
        return list(self.data.get(table, []))


_tables: Tables | None = None


def get_tables() -> Tables:
    global _tables
    if _tables is None:
        _tables = AzureTables() if settings.tables_endpoint or settings.tables_connection else MemoryTables()
    return _tables


def _newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: str(r.get("Timestamp") or ""), reverse=True)


def overview() -> list[dict[str, Any]]:
    tables = get_tables()
    with ThreadPoolExecutor(max_workers=len(TABLES)) as pool:
        all_rows = dict(zip(TABLES, pool.map(tables.rows, TABLES), strict=True))
    out = []
    for name, purpose in TABLES.items():
        rows = all_rows[name]
        newest = _newest_first(rows)[:1]
        out.append({"name": name, "purpose": purpose, "count": min(len(rows), MAX_ROWS), "capped": len(rows) > MAX_ROWS,
                    "updated": clean(name, newest[0]).get("Timestamp") if newest else None})
    return out


def page(table: str, offset: int, limit: int) -> dict[str, Any]:
    rows = _newest_first(get_tables().rows(table))[:MAX_ROWS]
    shown = [clean(table, r) for r in rows[offset : offset + limit]]
    # keys first, then the columns in the order they first appear, Timestamp last
    cols: list[str] = ["PartitionKey", "RowKey"]
    for r in shown:
        cols += [k for k in r if k not in cols and k != "Timestamp"]
    cols.append("Timestamp")
    masked = [c for c in cols if c in SECRET_FIELDS or c == SECRET_KEYS.get(table)]
    return {"name": table, "purpose": TABLES[table], "columns": cols, "masked": masked, "rows": shown,
            "total": len(rows), "offset": offset, "limit": limit}
