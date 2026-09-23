"""The filter layer.

Filters are declared once, here, and reused by every endpoint that lists records.
A new filter is a new entry in :data:`FILTERS` plus a query parameter — nothing else
in the app needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Filter:
    """One filter: how it reaches SQL, and how it is described to a human."""

    name: str
    sql: str
    describe: Callable[[Any], str]


FILTERS: tuple[Filter, ...] = (
    Filter("state", "state = ?", lambda v: f"state {v}"),
    Filter("city", "LOWER(city) = LOWER(?)", lambda v: f"city {v}"),
    Filter("kind", "kind = ?", lambda v: f"{v} facilities"),
    Filter("min_visits", "annual_visits >= ?", lambda v: f"at least {v:,} visits"),
    Filter("max_visits", "annual_visits <= ?", lambda v: f"at most {v:,} visits"),
    Filter("founded_after", "year_founded > ?", lambda v: f"founded after {v}"),
    Filter("founded_before", "year_founded < ?", lambda v: f"founded before {v}"),
    Filter("has_makerspace", "has_makerspace = ?", lambda v: "with a makerspace" if v else "without a makerspace"),
    Filter("q", "LOWER(name) LIKE LOWER(?)", lambda v: f"name containing {v!r}"),
    Filter("status", "status = ?", lambda v: f"status {v}"),
    Filter("category", "category = ?", lambda v: f"category {v}"),
    Filter("priority", "priority = ?", lambda v: f"priority {v}"),
    Filter("team", "team = ?", lambda v: f"team {v}"),
)

_BY_NAME = {f.name: f for f in FILTERS}


def build_where(params: dict[str, Any]) -> tuple[str, list[Any]]:
    """Turn a dict of filter values into a WHERE clause and its bound arguments.

    Values that are ``None`` are dropped, so callers can pass their whole query
    object without pre-filtering it.
    """
    clauses: list[str] = []
    args: list[Any] = []
    for name, value in params.items():
        if value is None or name not in _BY_NAME:
            continue
        f = _BY_NAME[name]
        clauses.append(f.sql)
        args.append(f"%{value}%" if name == "q" else (int(value) if isinstance(value, bool) else value))
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, args


def describe(params: dict[str, Any]) -> str:
    """A plain-English rendering of the active filters, for humans and for prompts."""
    parts = [_BY_NAME[n].describe(v) for n, v in params.items()
             if v is not None and n in _BY_NAME]
    if not parts:
        return "all facilities"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


_CASE_INSENSITIVE = {"city", "q"}   # compared with LOWER() in SQL, so normalise here too


def active(params: dict[str, Any]) -> dict[str, Any]:
    """Just the filters that are actually set, normalised. Safe to use as a cache key.

    Text filters that SQL matches case-insensitively are lowercased, so ``city=Boston``
    and ``city=boston`` — the same selection — produce the same key.
    """
    out = {}
    for n, v in sorted(params.items()):
        if v is None or n not in _BY_NAME:
            continue
        out[n] = v.lower() if n in _CASE_INSENSITIVE and isinstance(v, str) else v
    return out
