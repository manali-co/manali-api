"""Post reactions: the Discussions set plus the sun, anonymous, one per browser per kind.

Each browser gets a random client id (the site stores it in localStorage). We store one row
per (post, client, kind) so a second tap removes it, and keep a per-post counter row for
fast reads. No accounts, no IPs, nothing personal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .settings import settings

KINDS = ("thumbs-up", "heart", "rocket", "eyes", "laugh", "sun")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")
CLIENT = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclass
class Counts:
    counts: dict[str, int]
    mine: list[str]


class ReactionStore(Protocol):
    def get(self, slug: str, client: str) -> Counts: ...
    def toggle(self, slug: str, client: str, kind: str) -> Counts: ...


class MemoryReactions:
    def __init__(self) -> None:
        self.rows: set[tuple[str, str, str]] = set()

    def get(self, slug: str, client: str) -> Counts:
        counts = {k: 0 for k in KINDS}
        mine = []
        for s, c, k in self.rows:
            if s == slug:
                counts[k] += 1
                if c == client:
                    mine.append(k)
        return Counts(counts, sorted(mine))

    def toggle(self, slug: str, client: str, kind: str) -> Counts:
        key = (slug, client, kind)
        if key in self.rows:
            self.rows.remove(key)
        else:
            self.rows.add(key)
        return self.get(slug, client)


class TableReactions:
    """Rows: PartitionKey = slug, RowKey = f"{client}|{kind}". Counts are computed by a
    partition query, which is cheap at blog scale and never drifts."""

    def __init__(self) -> None:
        from azure.data.tables import TableServiceClient

        if settings.tables_connection:
            svc = TableServiceClient.from_connection_string(settings.tables_connection)
        else:
            from azure.identity import DefaultAzureCredential

            svc = TableServiceClient(endpoint=settings.tables_endpoint, credential=DefaultAzureCredential())
        self.t = svc.create_table_if_not_exists("reactions")

    def get(self, slug: str, client: str) -> Counts:
        counts = {k: 0 for k in KINDS}
        mine = []
        for r in self.t.query_entities("PartitionKey eq @s", parameters={"s": slug}, select=["RowKey"]):
            c, _, k = r["RowKey"].partition("|")
            if k in counts:
                counts[k] += 1
                if c == client:
                    mine.append(k)
        return Counts(counts, sorted(mine))

    def toggle(self, slug: str, client: str, kind: str) -> Counts:
        row_key = f"{client}|{kind}"
        try:
            self.t.get_entity(slug, row_key)
            self.t.delete_entity(slug, row_key)
        except Exception:
            self.t.upsert_entity({"PartitionKey": slug, "RowKey": row_key})
        return self.get(slug, client)


_store: ReactionStore | None = None


def get_reactions() -> ReactionStore:
    global _store
    if _store is None:
        _store = TableReactions() if (settings.tables_endpoint or settings.tables_connection) else MemoryReactions()
    return _store
