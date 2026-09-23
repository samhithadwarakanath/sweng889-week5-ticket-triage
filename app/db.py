"""SQLite access.

One connection per request, created by :func:`get_db`. The schema is created and
seeded from ``data/libraries.csv`` on first use, so a fresh clone needs no migration
step — ``make test`` works immediately.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    city            TEXT    NOT NULL,
    state           TEXT    NOT NULL,
    kind            TEXT    NOT NULL,
    year_founded    INTEGER NOT NULL,
    annual_visits   INTEGER NOT NULL,
    has_makerspace  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_libraries_state ON libraries(state);
CREATE INDEX IF NOT EXISTS idx_libraries_kind  ON libraries(kind);

CREATE TABLE IF NOT EXISTS tickets (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    subject                TEXT    NOT NULL,
    body                   TEXT    NOT NULL,
    status                 TEXT    NOT NULL,
    category               TEXT,
    priority               TEXT,
    team                   TEXT,
    draft_reply            TEXT,
    confidence             REAL,
    model_version          TEXT,
    model_value            TEXT,
    latency_ms             INTEGER,
    model_error            TEXT,
    needs_human_attention  INTEGER NOT NULL,
    reviewer               TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection.

    ``path`` is resolved when this is *called*, not when the module is imported, so a
    test can point :data:`DB_PATH` somewhere temporary and actually be obeyed.
    """
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection, seed_csv: Path | None = None) -> int:
    """Create the schema and seed it if empty. Returns the row count."""
    conn.executescript(SCHEMA)
    count = conn.execute("SELECT COUNT(*) AS n FROM libraries").fetchone()["n"]
    if count:
        return count
    source = seed_csv or (DATA_DIR / "libraries.csv")
    with source.open(newline="", encoding="utf-8") as fh:
        rows = [
            (
                int(r["id"]), r["name"], r["city"], r["state"], r["kind"],
                int(r["year_founded"]), int(r["annual_visits"]),
                1 if r["has_makerspace"].strip().lower() in ("1", "true", "yes") else 0,
            )
            for r in csv.DictReader(fh)
        ]
    conn.executemany(
        "INSERT INTO libraries (id, name, city, state, kind, year_founded, annual_visits,"
        " has_makerspace) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


_conn: sqlite3.Connection | None = None


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency. Use it as ``db: sqlite3.Connection = Depends(get_db)``."""
    global _conn
    if _conn is None:
        _conn = connect(DB_PATH)
        init(_conn)
    yield _conn


def reset(path: Path | str | None = None) -> None:
    """Drop the cached connection and the file. Tests use this for isolation."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    p = Path(path or DB_PATH)
    if p.exists():
        p.unlink()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        d = dict(r)
        d["has_makerspace"] = bool(d["has_makerspace"])
        out.append(d)
    return out
