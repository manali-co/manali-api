"""Public comments on posts, no account needed.

A reader posts as their browser. The browser's random client id (the same one reactions use)
never leaves the server: comments carry `seed`, a one-way hash of it that the browser can also
compute, so the site can draw the reader's friendly name and avatar without the id ever being
public. A display name is optional; names that would pass as the owner are refused.

Moderation: the first comment from a browser is held (`pending`) until the owner approves it,
which marks that browser trusted; after that its comments go straight up (`live`). Removing a
comment keeps a placeholder so replies keep their context (`removed`).

Storage layout: see TableComments.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import Any, Protocol

from .settings import settings

MAX_TEXT = 2000
RESERVED = re.compile(r"ayush|manali|author|admin|moderator", re.I)


def seed_of(client: str) -> str:
    """Public stand-in for a client id: sha256 hex, first 24 chars. The browser computes the same."""
    return hashlib.sha256(client.encode()).hexdigest()[:24]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    """Sortable oldest-first within a post, unique across requests."""
    return f"{int(datetime.now(UTC).timestamp() * 1000):013d}-{secrets.token_hex(3)}"


@dataclass
class Comment:
    slug: str
    text: str
    created: str
    seed: str  # hash of the author's client id; empty for the owner
    state: str = "live"  # pending | live | removed
    parent: str = ""  # id of the top-level comment this replies to
    name: str = ""  # chosen display name, else empty (the site derives a friendly one from seed)
    owner: bool = False
    email: str = ""  # only for reply notifications; never returned publicly
    notify: bool = False
    loves: int = 0
    title: str = ""  # the post's title when this was written, for emails sent later
    id: str = ""


class CommentStore(Protocol):
    def add(self, c: Comment) -> Comment: ...
    def get(self, slug: str, cid: str) -> Comment | None: ...
    def put(self, c: Comment) -> None: ...
    def update(self, slug: str, cid: str, **changes: Any) -> None: ...
    def for_post(self, slug: str) -> list[Comment]: ...
    def recent(self, limit: int = 100) -> list[Comment]: ...
    def trusted(self, seed: str) -> bool: ...
    def trust(self, seed: str) -> None: ...
    def toggle_love(self, cid: str, seed: str) -> bool: ...
    def loved_by(self, seed: str, ids: list[str]) -> set[str]: ...
    def bump_loves(self, slug: str, cid: str, delta: int) -> int: ...


class MemoryComments:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Comment] = {}
        self.trusted_seeds: set[str] = set()
        self.love: set[tuple[str, str]] = set()

    def add(self, c: Comment) -> Comment:
        c.id = new_id()
        self.rows[(c.slug, c.id)] = c
        return c

    def get(self, slug: str, cid: str) -> Comment | None:
        return self.rows.get((slug, cid))

    def put(self, c: Comment) -> None:
        self.rows[(c.slug, c.id)] = c

    def update(self, slug: str, cid: str, **changes: Any) -> None:
        c = self.rows.get((slug, cid))
        if c:
            for k, v in changes.items():
                setattr(c, k, v)

    def for_post(self, slug: str) -> list[Comment]:
        return sorted((c for (s, _), c in self.rows.items() if s == slug), key=lambda c: c.id)

    def recent(self, limit: int = 100) -> list[Comment]:
        return sorted(self.rows.values(), key=lambda c: c.id, reverse=True)[:limit]

    def trusted(self, seed: str) -> bool:
        return seed in self.trusted_seeds

    def trust(self, seed: str) -> None:
        self.trusted_seeds.add(seed)

    def toggle_love(self, cid: str, seed: str) -> bool:
        k = (cid, seed)
        if k in self.love:
            self.love.discard(k)
            return False
        self.love.add(k)
        return True

    def loved_by(self, seed: str, ids: list[str]) -> set[str]:
        return {i for i in ids if (i, seed) in self.love}

    def bump_loves(self, slug: str, cid: str, delta: int) -> int:
        c = self.rows[(slug, cid)]
        c.loves = max(0, c.loves + delta)
        return c.loves


class TableComments:
    """Three tables, each read by key or by one partition:
    - comments: PartitionKey = post slug, RowKey = sortable id (oldest first), so one query reads
      a post's whole thread.
    - commenters: PartitionKey "seed", RowKey = seed, present once the owner has approved one of
      that browser's comments.
    - commentloves: PartitionKey = seed, RowKey = comment id, one row per love, so a browser's
      loves on a post come back in one partition query."""

    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())
        self.t = svc.create_table_if_not_exists("comments")
        self.who = svc.create_table_if_not_exists("commenters")
        self.lv = svc.create_table_if_not_exists("commentloves")

    @staticmethod
    def _from(row: dict[str, Any]) -> Comment:
        known = {f.name for f in fields(Comment)}
        c = Comment(**{k: row[k] for k in known if k in row and k not in ("slug", "id")}, slug=row["PartitionKey"], id=row["RowKey"])
        c.loves, c.owner, c.notify = int(c.loves or 0), bool(c.owner), bool(c.notify)
        return c

    def add(self, c: Comment) -> Comment:
        c.id = new_id()
        self.put(c)
        return c

    def get(self, slug: str, cid: str) -> Comment | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._from(self.t.get_entity(slug, cid))
        except ResourceNotFoundError:
            return None

    def put(self, c: Comment) -> None:
        """Whole-entity write: only for a new comment. Changes to an existing one go through
        update, which writes just the named fields, so it can't undo a concurrent love or
        moderation change."""
        row = {"PartitionKey": c.slug, "RowKey": c.id, **{k: v for k, v in asdict(c).items() if k not in ("slug", "id")}}
        self.t.upsert_entity(row)

    def update(self, slug: str, cid: str, **changes: Any) -> None:
        from azure.data.tables import UpdateMode

        self.t.update_entity({"PartitionKey": slug, "RowKey": cid, **changes}, mode=UpdateMode.MERGE)

    def for_post(self, slug: str) -> list[Comment]:
        return [self._from(r) for r in self.t.query_entities("PartitionKey eq @s", parameters={"s": slug})]

    def recent(self, limit: int = 100) -> list[Comment]:
        # Small site: a full scan is fine at this size; newest first.
        rows = [self._from(r) for r in self.t.list_entities()]
        return sorted(rows, key=lambda c: c.id, reverse=True)[:limit]

    def trusted(self, seed: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.who.get_entity("seed", seed)
            return True
        except ResourceNotFoundError:
            return False

    def trust(self, seed: str) -> None:
        self.who.upsert_entity({"PartitionKey": "seed", "RowKey": seed, "since": now_iso()})

    def toggle_love(self, cid: str, seed: str) -> bool:
        from azure.core.exceptions import ResourceExistsError

        try:
            self.lv.create_entity({"PartitionKey": seed, "RowKey": cid})
            return True
        except ResourceExistsError:
            self.lv.delete_entity(seed, cid)
            return False

    def bump_loves(self, slug: str, cid: str, delta: int) -> int:
        """Counter updated with an ETag match, so two loves at once can't overwrite each other."""
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError
        from azure.data.tables import UpdateMode

        for _ in range(5):
            row = self.t.get_entity(slug, cid)
            loves = max(0, int(row.get("loves", 0)) + delta)
            try:
                self.t.update_entity({"PartitionKey": slug, "RowKey": cid, "loves": loves}, mode=UpdateMode.MERGE,
                                     etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
                return loves
            except HttpResponseError as e:
                if getattr(e, "status_code", None) == 412:
                    continue
                raise
        return int(row.get("loves", 0))

    def loved_by(self, seed: str, ids: list[str]) -> set[str]:
        want = set(ids)
        return {r["RowKey"] for r in self.lv.query_entities("PartitionKey eq @s", parameters={"s": seed}) if r["RowKey"] in want}


_store: CommentStore | None = None


def get_comments() -> CommentStore:
    global _store
    if _store is None:
        if settings.tables_endpoint or settings.tables_connection:
            _store = TableComments()
        elif settings.fake_allowed:
            _store = MemoryComments()
        else:
            raise RuntimeError("no storage configured; set MANALI_TABLES_ENDPOINT")
    return _store
