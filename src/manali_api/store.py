"""Subscribers and a tiny event log, in Azure Table Storage.

Two tables: `subscribers` (PartitionKey "sub", RowKey = sha256 of the lowercased address, the
address itself is a property) and `events` (PartitionKey "email", RowKey = reverse-timestamp so
the newest sorts first). An in-memory store stands in for tests and local runs without a
storage account.

Unsubscribe deletes the row. The only thing an ex-subscriber leaves behind is nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .settings import settings


def key(email: str) -> str:
    """Row key: a hash, so any valid address fits Table Storage's key rules."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


MAX_FOLLOWS = 50  # 50 slugs of up to 120 characters stay far below one property's 64 KiB


@dataclass
class Subscriber:
    email: str
    created: str
    confirmed: bool = False
    source: str = "site"
    confirm_token: str = ""
    sends: int = 0  # confirmation emails sent for this address
    last_sent: str = ""
    everything: bool = True  # every new post; False for someone who only follows series
    series: str = ""  # comma-separated slugs of the series this address follows
    series_title: str = ""  # display name of the series most recently followed, for the emails

    def follows(self) -> list[str]:
        """Followed series slugs, oldest first."""
        return [x for x in self.series.split(",") if x]

    def follow(self, slug: str, title: str = "") -> bool:
        """Add a followed series. Returns False, changing nothing, once the address already follows
        MAX_FOLLOWS others: the list is one Table Storage string, capped at 64 KiB, and existing
        follows are never dropped to make room."""
        current = self.follows()
        if slug not in current and len(current) >= MAX_FOLLOWS:
            return False
        self.series = ",".join([x for x in current if x != slug] + [slug])
        if title:
            self.series_title = title
        return True

    def wants(self, series: str | None) -> bool:
        """Should a new post in `series` (None for a standalone post) reach this address?"""
        return self.everything or (series is not None and series in self.follows())

    def unfollow(self, slug: str) -> bool:
        """Drop one followed series. Returns whether it was followed."""
        current = self.follows()
        self.series = ",".join(x for x in current if x != slug)
        return slug in current

    def to_row(self) -> dict[str, Any]:
        return {"PartitionKey": "sub", "RowKey": key(self.email), **asdict(self)}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Subscriber:
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row})


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp) if stamp else datetime.fromtimestamp(0, UTC)


def unsubscribe_token(email: str) -> str:
    """`<row key>.<mac>`: stable per address so links never expire, and the row key part makes
    the lookup O(1) instead of a scan over every subscriber."""
    k = key(email)
    mac = hmac.new(settings.token_secret.encode(), k.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{k}.{mac}"


def split_unsub_token(token: str) -> str | None:
    """The row key inside a valid token, or None if the MAC does not check out."""
    k, _, mac = token.partition(".")
    if len(k) != 32 or len(mac) != 32:
        return None
    want = hmac.new(settings.token_secret.encode(), k.encode(), hashlib.sha256).hexdigest()[:32]
    return k if hmac.compare_digest(mac, want) else None


class Store(Protocol):
    def get(self, email: str) -> Subscriber | None: ...
    def get_by_key(self, k: str) -> Subscriber | None: ...
    def put(self, sub: Subscriber) -> None: ...
    def delete(self, sub: Subscriber) -> None: ...
    def all(self) -> list[Subscriber]: ...
    def by_confirm_token(self, token: str) -> Subscriber | None: ...
    def log_email(
        self, subject: str, recipients: int, slug: str = "", audience: list[str] | None = None, accepted: list[str] | None = None,
        failures: dict[str, str] | None = None, followers: list[str] | None = None,
    ) -> None: ...
    def last_email(self) -> dict[str, Any] | None: ...
    def announced(self, slug: str) -> bool: ...
    def announcements(self) -> list[dict[str, Any]]: ...


def send_log(
    audience: list[str], accepted: list[str], failures: dict[str, str] | None = None, followers: list[str] | None = None
) -> list[dict[str, Any]]:
    """Who a send was meant for and whether Resend took it. Only the hashed row key is kept, never
    the address: the admin view matches keys back to current subscribers, so an address that
    unsubscribes later is gone from here too (the privacy page promises unsubscribing deletes it)."""
    ok, fol, why = {key(e) for e in accepted}, {key(e) for e in followers or []}, {key(e): r for e, r in (failures or {}).items()}
    keys = [key(e) for e in audience]
    return [{"key": k, "ok": k in ok, "follower": k in fol, "reason": "" if k in ok else why.get(k, "not sent")} for k in keys]


def by_unsub_token(store: Store, token: str) -> Subscriber | None:
    k = split_unsub_token(token)
    return store.get_by_key(k) if k else None


def purge_pending(store: Store, days: int = 7) -> int:
    """Addresses that never confirmed are not ours to keep."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stale = [s for s in store.all() if not s.confirmed and parse(s.created) < cutoff]
    for s in stale:
        store.delete(s)
    return len(stale)


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, Subscriber] = {}
        self.events: list[dict[str, Any]] = []

    def get(self, email: str) -> Subscriber | None:
        return self.rows.get(key(email))

    def get_by_key(self, k: str) -> Subscriber | None:
        return self.rows.get(k)

    def put(self, sub: Subscriber) -> None:
        self.rows[key(sub.email)] = sub

    def delete(self, sub: Subscriber) -> None:
        self.rows.pop(key(sub.email), None)

    def all(self) -> list[Subscriber]:
        return list(self.rows.values())

    def by_confirm_token(self, token: str) -> Subscriber | None:
        return next((s for s in self.rows.values() if s.confirm_token and hmac.compare_digest(s.confirm_token, token)), None)

    def log_email(
        self, subject: str, recipients: int, slug: str = "", audience: list[str] | None = None, accepted: list[str] | None = None,
        failures: dict[str, str] | None = None, followers: list[str] | None = None,
    ) -> None:
        row: dict[str, Any] = {"id": f"{len(self.events):013d}", "subject": subject, "sent": now(), "recipients": recipients}
        row["slug"] = slug
        if audience is not None:
            row.update(subscribers=len(audience), to=send_log(audience, accepted or [], failures, followers))
        self.events.insert(0, row)

    def last_email(self) -> dict[str, Any] | None:
        return self.events[0] if self.events else None

    def announced(self, slug: str) -> bool:
        return any(e.get("slug") == slug for e in self.events)

    def announcements(self) -> list[dict[str, Any]]:
        fields = ("id", "slug", "subject", "sent", "recipients", "subscribers", "to")
        return [{k: e.get(k) for k in fields} for e in self.events if e.get("slug")]


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
        return self.get_by_key(key(email))

    def get_by_key(self, k: str) -> Subscriber | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return Subscriber.from_row(self.subs.get_entity("sub", k))
        except ResourceNotFoundError:
            return None  # anything else (throttle, auth) raises: never mistake an outage for "new"

    def put(self, sub: Subscriber) -> None:
        self.subs.upsert_entity(sub.to_row())

    def delete(self, sub: Subscriber) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.subs.delete_entity("sub", key(sub.email))
        except ResourceNotFoundError:
            pass

    def all(self) -> list[Subscriber]:
        return [Subscriber.from_row(r) for r in self.subs.query_entities("PartitionKey eq 'sub'")]

    def by_confirm_token(self, token: str) -> Subscriber | None:
        rows = list(self.subs.query_entities("PartitionKey eq 'sub' and confirm_token eq @t", parameters={"t": token}))
        return Subscriber.from_row(rows[0]) if rows else None

    def log_email(
        self, subject: str, recipients: int, slug: str = "", audience: list[str] | None = None, accepted: list[str] | None = None,
        failures: dict[str, str] | None = None, followers: list[str] | None = None,
    ) -> None:
        # newest sorts first; the suffix keeps two sends in the same millisecond apart
        stamp = f"{10**13 - int(datetime.now(UTC).timestamp() * 1000):013d}-{secrets.token_hex(4)}"
        row: dict[str, Any] = {"PartitionKey": "email", "RowKey": stamp, "subject": subject, "sent": now(), "recipients": recipients}
        row["slug"] = slug
        if audience is not None:
            row["subscribers"] = len(audience)
            # one row per recipient in the send's own partition, written 100 at a time (a table transaction's limit)
            log = send_log(audience, accepted or [], failures, followers)
            rows = [{"PartitionKey": f"to-{stamp}", "RowKey": r["key"], "ok": r["ok"], "follower": r["follower"], "reason": r["reason"]}
                    for r in log]
            for i in range(0, len(rows), 100):
                self.events.submit_transaction([("upsert", r) for r in rows[i : i + 100]])
        self.events.upsert_entity(row)  # last, so a listed send always has its recipients

    def last_email(self) -> dict[str, Any] | None:
        for r in self.events.query_entities("PartitionKey eq 'email'", results_per_page=1):
            return {"subject": r["subject"], "sent": r["sent"], "recipients": int(r["recipients"])}
        return None

    def announced(self, slug: str) -> bool:
        rows = self.events.query_entities("PartitionKey eq 'email' and slug eq @s", parameters={"s": slug}, select=["RowKey"])
        return any(True for _ in rows)

    def announcements(self) -> list[dict[str, Any]]:
        out = []
        for r in self.events.query_entities("PartitionKey eq 'email' and slug ne ''"):
            e: dict[str, Any] = {"id": r["RowKey"], "slug": r["slug"], "subject": r["subject"], "sent": r["sent"]}
            e.update(recipients=int(r["recipients"]), subscribers=None, to=None)
            if "subscribers" in r:  # sends from before recipient lists were kept have only the count
                e["subscribers"] = int(r["subscribers"])
                sent_to = self.events.query_entities("PartitionKey eq @p", parameters={"p": f"to-{r['RowKey']}"})
                e["to"] = [{"key": t["RowKey"], "ok": bool(t["ok"]), "follower": bool(t.get("follower")), "reason": t.get("reason", "")}
                           for t in sent_to]
            out.append(e)
        return out


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        if settings.tables_endpoint or settings.tables_connection:
            _store = TableStore()
        elif settings.fake_allowed:
            _store = MemoryStore()
        else:
            raise RuntimeError("no storage configured; set MANALI_TABLES_ENDPOINT")
    return _store


def new_confirm_token() -> str:
    return secrets.token_urlsafe(24)
