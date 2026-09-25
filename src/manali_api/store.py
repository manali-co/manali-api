"""Subscribers and a tiny event log, in Azure Table Storage.

Two tables: `subscribers` (PartitionKey "sub", RowKey = lowercased email) and `events`
(PartitionKey "email", RowKey = reverse-timestamp so the newest sorts first). An in-memory
store stands in for tests and local runs without a storage account.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from .settings import settings


@dataclass
class Subscriber:
    email: str
    created: str
    confirmed: bool = False
    unsubscribed: bool = False
    source: str = "site"
    confirm_token: str = ""

    def to_row(self) -> dict:
        return {"PartitionKey": "sub", "RowKey": self.email, **asdict(self)}

    @classmethod
    def from_row(cls, row: dict) -> Subscriber:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row})


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def unsubscribe_token(email: str) -> str:
    """Stable, unguessable per-address token so unsubscribe links never expire."""
    return hmac.new(settings.token_secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]


class Store(Protocol):
    def get(self, email: str) -> Subscriber | None: ...
    def put(self, sub: Subscriber) -> None: ...
    def all(self) -> list[Subscriber]: ...
    def by_confirm_token(self, token: str) -> Subscriber | None: ...
    def by_unsub_token(self, token: str) -> Subscriber | None: ...
    def log_email(self, subject: str, recipients: int) -> None: ...
    def last_email(self) -> dict | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, Subscriber] = {}
        self.events: list[dict] = []

    def get(self, email: str) -> Subscriber | None:
        return self.rows.get(email.lower())

    def put(self, sub: Subscriber) -> None:
        self.rows[sub.email.lower()] = sub

    def all(self) -> list[Subscriber]:
        return list(self.rows.values())

    def by_confirm_token(self, token: str) -> Subscriber | None:
        return next((s for s in self.rows.values() if s.confirm_token and s.confirm_token == token), None)

    def by_unsub_token(self, token: str) -> Subscriber | None:
        return next((s for s in self.rows.values() if unsubscribe_token(s.email) == token), None)

    def log_email(self, subject: str, recipients: int) -> None:
        self.events.insert(0, {"subject": subject, "sent": now(), "recipients": recipients})

    def last_email(self) -> dict | None:
        return self.events[0] if self.events else None


class TableStore:
    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())
        self.subs = svc.create_table_if_not_exists("subscribers")
        self.events = svc.create_table_if_not_exists("events")

    def get(self, email: str) -> Subscriber | None:
        try:
            return Subscriber.from_row(self.subs.get_entity("sub", email.lower()))
        except Exception:
            return None

    def put(self, sub: Subscriber) -> None:
        self.subs.upsert_entity(sub.to_row())

    def all(self) -> list[Subscriber]:
        return [Subscriber.from_row(r) for r in self.subs.query_entities("PartitionKey eq 'sub'")]

    def by_confirm_token(self, token: str) -> Subscriber | None:
        rows = list(self.subs.query_entities("PartitionKey eq 'sub' and confirm_token eq @t", parameters={"t": token}))
        return Subscriber.from_row(rows[0]) if rows else None

    def by_unsub_token(self, token: str) -> Subscriber | None:
        return next((s for s in self.all() if unsubscribe_token(s.email) == token), None)

    def log_email(self, subject: str, recipients: int) -> None:
        stamp = f"{10**13 - int(datetime.now(UTC).timestamp() * 1000):013d}"
        self.events.upsert_entity({"PartitionKey": "email", "RowKey": stamp, "subject": subject, "sent": now(), "recipients": recipients})

    def last_email(self) -> dict | None:
        for r in self.events.query_entities("PartitionKey eq 'email'", results_per_page=1):
            return {"subject": r["subject"], "sent": r["sent"], "recipients": int(r["recipients"])}
        return None


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = TableStore() if (settings.tables_endpoint or settings.tables_connection) else MemoryStore()
    return _store


def new_confirm_token() -> str:
    return secrets.token_urlsafe(24)
