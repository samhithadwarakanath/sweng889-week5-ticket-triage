"""Endpoints for the library records.

Read this file before adding an endpoint of your own — it is the pattern the rest of
the app expects: query parameters go through :mod:`app.filters`, list responses use
:class:`app.models.Page`, and anything that calls the model wraps the call the way
:func:`describe_library` does.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import filters
from app.db import get_db, rows_to_dicts
from app.model_client import ModelError, ModelTimeout, ModelUnavailable, get_client
from app.models import DescribeResponse, Library, LibraryCreate, ModelPayload, Page

router = APIRouter(prefix="/libraries", tags=["libraries"])

# Below this, a model answer is not trustworthy enough to show without saying so.
# The existing endpoint surfaces the score rather than hiding it; what *your*
# feature does about a low score is a decision for your specification.
LOW_CONFIDENCE = 0.5


def _query_params(
    state: Optional[str] = Query(None, min_length=2, max_length=2),
    city: Optional[str] = None,
    kind: Optional[str] = None,
    min_visits: Optional[int] = Query(None, ge=0),
    max_visits: Optional[int] = Query(None, ge=0),
    founded_after: Optional[int] = None,
    founded_before: Optional[int] = None,
    has_makerspace: Optional[bool] = None,
    q: Optional[str] = None,
) -> dict:
    """The shared filter set. Add a filter here and in :data:`app.filters.FILTERS`."""
    return {
        "state": state.upper() if state else None,
        "city": city,
        "kind": kind,
        "min_visits": min_visits,
        "max_visits": max_visits,
        "founded_after": founded_after,
        "founded_before": founded_before,
        "has_makerspace": has_makerspace,
        "q": q,
    }


@router.get("", response_model=Page[Library])
def list_libraries(
    params: dict = Depends(_query_params),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
) -> Page[Library]:
    """List facilities, filtered. This is the endpoint the summary feature sits beside."""
    where, args = filters.build_where(params)
    total = db.execute(f"SELECT COUNT(*) AS n FROM libraries WHERE {where}", args).fetchone()["n"]
    rows = db.execute(
        f"SELECT * FROM libraries WHERE {where} ORDER BY name LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return Page[Library](items=[Library(**r) for r in rows_to_dicts(rows)],
                total=total, limit=limit, offset=offset)


@router.post("", response_model=Library, status_code=201)
def create_library(body: LibraryCreate, db: sqlite3.Connection = Depends(get_db)) -> Library:
    """The write path. Rejects a duplicate (name, city) pair rather than creating one."""
    clash = db.execute(
        "SELECT id FROM libraries WHERE LOWER(name) = LOWER(?) AND LOWER(city) = LOWER(?)",
        (body.name, body.city),
    ).fetchone()
    if clash:
        raise HTTPException(status_code=409,
                            detail=f"a facility named {body.name!r} already exists in {body.city}")
    cur = db.execute(
        "INSERT INTO libraries (name, city, state, kind, year_founded, annual_visits,"
        " has_makerspace) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.name, body.city, body.state.upper(), body.kind, body.year_founded,
         body.annual_visits, int(body.has_makerspace)),
    )
    db.commit()
    row = db.execute("SELECT * FROM libraries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return Library(**rows_to_dicts([row])[0])


@router.get("/{library_id}", response_model=Library)
def get_library(library_id: int, db: sqlite3.Connection = Depends(get_db)) -> Library:
    row = db.execute("SELECT * FROM libraries WHERE id = ?", (library_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no facility with id {library_id}")
    return Library(**rows_to_dicts([row])[0])


@router.get("/{library_id}/describe", response_model=DescribeResponse)
def describe_library(
    library_id: int,
    db: sqlite3.Connection = Depends(get_db),
) -> DescribeResponse:
    """A one-line, model-written description of a single facility.

    **This is the worked example of a model-backed endpoint.** Copy its shape:

    1. Fetch your own data first; never hand the model something you have not checked.
    2. Call the model inside try/except for :class:`ModelUnavailable` and
       :class:`ModelTimeout`. They are different failures and may deserve different
       handling — this endpoint treats both as 503, which is a decision, not a law.
    3. Return the confidence and model version to the caller instead of swallowing them.
    """
    row = db.execute("SELECT * FROM libraries WHERE id = ?", (library_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no facility with id {library_id}")
    record = rows_to_dicts([row])[0]

    try:
        result = get_client().complete("describe_record", record)
    except ModelTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return DescribeResponse(
        library_id=library_id,
        description=str(result.value),
        model=ModelPayload(**result.as_dict()),
    )
