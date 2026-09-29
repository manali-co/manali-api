"""Replies to posts, no account needed: a line of text, an optional name and email.

Rows: PartitionKey = post slug, RowKey = reverse timestamp + random, so the newest sort first.
The browser's random client id is kept only to rate-limit, never shown. Emails are optional,
visible only to the owner (admin), and used only to answer the person who left them.
"""
from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .settings import settings

MAX_TEXT = 1000
PER_CLIENT_PER_HOUR = 5


@dataclass
class Reply:
    slug: str
    text: str
    created: str
    client: str
    name: str = ""
    email: str = ""
    id: str = ""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return f"{10**13 - int(datetime.now(UTC).timestamp() * 1000):013d}-{secrets.token_hex(3)}"


class ReplyStore(Protocol):
    def add(self, r: Reply) -> Reply: ...
    def recent_by_client(self, client: str, since: datetime) -> int: ...
    def latest(self, limit: int = 50) -> list[Reply]: ...
    def delete(self, slug: str, reply_id: str) -> bool: ...


class MemoryReplies:
    def __init__(self) -> None:
        self.rows: list[Reply] = []

    def add(self, r: Reply) -> Reply:
        r.id = new_id()
        self.rows.insert(0, r)
        return r

    def recent_by_client(self, client: str, since: datetime) -> int:
        return sum(1 for r in self.rows if r.client == client and datetime.fromisoformat(r.created) >= since)

    def latest(self, limit: int = 50) -> list[Reply]:
        return sorted(self.rows, key=lambda r: r.created, reverse=True)[:limit]

    def delete(self, slug: str, reply_id: str) -> bool:
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r.slug == slug and r.id == reply_id)]
        return len(self.rows) < before


class TableReplies:
    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())
        self.t = svc.create_table_if_not_exists("replies")

    def add(self, r: Reply) -> Reply:
        r.id = new_id()
        row: dict[str, Any] = {"PartitionKey": r.slug, "RowKey": r.id, **{k: v for k, v in asdict(r).items() if k not in ("slug", "id")}}
        self.t.create_entity(row)
        return r

    def recent_by_client(self, client: str, since: datetime) -> int:
        rows = self.t.query_entities("client eq @c and created ge @s", parameters={"c": client, "s": since.isoformat(timespec="seconds")}, select=["RowKey"])
        return sum(1 for _ in rows)

    def latest(self, limit: int = 50) -> list[Reply]:
        out = [Reply(slug=r["PartitionKey"], id=r["RowKey"], text=r.get("text", ""), created=r.get("created", ""), client=r.get("client", ""),
                     name=r.get("name", ""), email=r.get("email", "")) for r in self.t.query_entities("PartitionKey ne ''")]
        return sorted(out, key=lambda r: r.created, reverse=True)[:limit]

    def delete(self, slug: str, reply_id: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.t.get_entity(slug, reply_id)
        except ResourceNotFoundError:
            return False
        self.t.delete_entity(slug, reply_id)
        return True


_store: ReplyStore | None = None


def get_replies() -> ReplyStore:
    global _store
    if _store is None:
        if settings.tables_endpoint or settings.tables_connection:
            _store = TableReplies()
        elif settings.fake_allowed:
            _store = MemoryReplies()
        else:
            raise RuntimeError("no storage configured; set MANALI_TABLES_ENDPOINT")
    return _store


def over_limit(store: ReplyStore, client: str) -> bool:
    return store.recent_by_client(client, datetime.now(UTC) - timedelta(hours=1)) >= PER_CLIENT_PER_HOUR
