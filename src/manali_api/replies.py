"""Replies to posts, no account needed: a line of text, an optional name and email.

Storage layout: see TableReplies.
The browser's random client id is kept only to rate-limit, never shown. Emails are optional,
visible only to the owner (admin), and used only to answer the person who left them.
"""
from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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


def hour_bucket(t: datetime | None = None) -> str:
    return (t or datetime.now(UTC)).strftime("%Y%m%d%H")


class ReplyStore(Protocol):
    def take_quota(self, client: str) -> bool: ...
    def add(self, r: Reply) -> Reply: ...
    def latest(self, limit: int = 50) -> list[Reply]: ...
    def delete(self, slug: str, reply_id: str) -> bool: ...


class MemoryReplies:
    def __init__(self) -> None:
        import threading

        self.rows: list[Reply] = []
        self.quota: dict[tuple[str, str], int] = {}
        self.lock = threading.Lock()

    def take_quota(self, client: str) -> bool:
        with self.lock:
            k = (client, hour_bucket())
            if self.quota.get(k, 0) >= PER_CLIENT_PER_HOUR:
                return False
            self.quota[k] = self.quota.get(k, 0) + 1
            return True

    def add(self, r: Reply) -> Reply:
        r.id = new_id()
        self.rows.insert(0, r)
        return r

    def latest(self, limit: int = 50) -> list[Reply]:
        return sorted(self.rows, key=lambda r: r.id)[:limit]

    def delete(self, slug: str, reply_id: str) -> bool:
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r.slug == slug and r.id == reply_id)]
        return len(self.rows) < before


class TableReplies:
    """Two tables, each read by key only:
    - replies: PartitionKey "reply", RowKey = reverse timestamp, so the first N rows of the one
      partition are the N newest across every post.
    - replyquota: PartitionKey = client, RowKey = hour; a counter updated with an ETag match, so
      concurrent requests from one browser can't all slip under the limit."""

    PK = "reply"

    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())
        self.t = svc.create_table_if_not_exists("replies")
        self.q = svc.create_table_if_not_exists("replyquota")

    def take_quota(self, client: str) -> bool:
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError

        hour = hour_bucket()
        for _ in range(5):  # optimistic concurrency: retry on a lost race
            try:
                row = self.q.get_entity(client, hour)
            except ResourceNotFoundError:
                try:
                    self.q.create_entity({"PartitionKey": client, "RowKey": hour, "n": 1})
                    return True
                except ResourceExistsError:
                    continue
            n = int(row.get("n", 0))
            if n >= PER_CLIENT_PER_HOUR:
                return False
            row["n"] = n + 1
            try:
                self.q.update_entity(row, etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
                return True
            except HttpResponseError as e:
                if getattr(e, "status_code", None) == 412:
                    continue
                raise
        return False

    def add(self, r: Reply) -> Reply:
        r.id = new_id()
        row: dict[str, Any] = {"PartitionKey": self.PK, "RowKey": r.id, **{k: v for k, v in asdict(r).items() if k != "id"}}
        self.t.create_entity(row)
        return r

    def latest(self, limit: int = 50) -> list[Reply]:
        out: list[Reply] = []
        for row in self.t.query_entities(f"PartitionKey eq '{self.PK}'", results_per_page=limit):
            out.append(Reply(slug=row.get("slug", ""), id=row["RowKey"], text=row.get("text", ""), created=row.get("created", ""),
                             client=row.get("client", ""), name=row.get("name", ""), email=row.get("email", "")))
            if len(out) >= limit:
                break
        return out

    def delete(self, slug: str, reply_id: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            row = self.t.get_entity(self.PK, reply_id)
        except ResourceNotFoundError:
            return False
        if row.get("slug") != slug:
            return False
        self.t.delete_entity(self.PK, reply_id)
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

