"""Support ticket triage — see specs/spec-v2.md.

A ticket is classified once, at creation, through the same model-calling pattern as
``describe_library`` in :mod:`app.routes.libraries` — except a failed classification
does not fail the request. An incoming ticket must survive a down model; it is stored
untriaged instead (see :func:`create_ticket`). A ticket is then reviewed by a human
exactly once through :func:`review_ticket`. Nothing here sends a reply anywhere.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import filters
from app.db import get_db
from app.model_client import ModelTimeout, ModelUnavailable, get_client
from app.models import ModelPayload, Page, Ticket, TicketCreate, TicketReview, TicketTriage
from app.routes.libraries import LOW_CONFIDENCE

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _query_params(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    team: Optional[str] = None,
) -> dict:
    """The ticket filter set. Each one is declared in :data:`app.filters.FILTERS`."""
    return {"status": status, "category": category, "priority": priority, "team": team}


def _row_to_ticket(row: sqlite3.Row) -> Ticket:
    triage = None
    if row["model_version"] is not None:
        triage = TicketTriage(
            category=row["category"],
            priority=row["priority"],
            team=row["team"],
            model=ModelPayload(
                value=json.loads(row["model_value"]),
                confidence=row["confidence"],
                model_version=row["model_version"],
                latency_ms=row["latency_ms"],
            ),
        )
    return Ticket(
        id=row["id"],
        status=row["status"],
        subject=row["subject"],
        body=row["body"],
        draft_reply=row["draft_reply"],
        triage=triage,
        needs_human_attention=bool(row["needs_human_attention"]),
        model_error=row["model_error"],
    )


def _fetch(db: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no ticket with id {ticket_id}")
    return row


@router.post("", response_model=Ticket, status_code=201)
def create_ticket(body: TicketCreate, db: sqlite3.Connection = Depends(get_db)) -> Ticket:
    """Classify a new ticket and queue it for review.

    A classifier failure does not fail this request (AC5) — the ticket is stored with
    ``triage`` null and ``model_error`` set, because losing an incoming ticket is worse
    than storing it without a suggestion. That is a deliberate departure from the
    503/504 that ``describe_library`` returns.
    """
    category = priority = team = draft_reply = confidence = model_version = None
    model_value = latency_ms = model_error = None
    try:
        result = get_client().complete(
            "classify_ticket", {"subject": body.subject, "body": body.body}
        )
    except ModelTimeout as exc:
        model_error = f"model timed out: {exc}"
    except ModelUnavailable as exc:
        model_error = f"model unavailable: {exc}"
    else:
        value = result.value
        category, priority, team, draft_reply = (
            value["category"], value["priority"], value["team"], value["draft_reply"],
        )
        # Not ModelResult.as_dict(): that rounds, and AC2 says confidence is returned as-is.
        confidence, model_version = result.confidence, result.model_version
        model_value, latency_ms = json.dumps(value), result.latency_ms

    # A failed classification needs attention too (spec §5).
    needs_attention = confidence is None or confidence < LOW_CONFIDENCE

    cur = db.execute(
        "INSERT INTO tickets (subject, body, status, category, priority, team, draft_reply,"
        " confidence, model_version, model_value, latency_ms, model_error, needs_human_attention)"
        " VALUES (?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (body.subject, body.body, category, priority, team, draft_reply,
         confidence, model_version, model_value, latency_ms, model_error, int(needs_attention)),
    )
    db.commit()
    return _row_to_ticket(_fetch(db, cur.lastrowid))


@router.get("", response_model=Page[Ticket])
def list_tickets(
    params: dict = Depends(_query_params),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
) -> Page[Ticket]:
    """The review queue: tickets needing attention first, then oldest first."""
    where, args = filters.build_where(params)
    total = db.execute(f"SELECT COUNT(*) AS n FROM tickets WHERE {where}", args).fetchone()["n"]
    rows = db.execute(
        f"SELECT * FROM tickets WHERE {where}"
        " ORDER BY needs_human_attention DESC, id LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return Page[Ticket](items=[_row_to_ticket(r) for r in rows],
                        total=total, limit=limit, offset=offset)


@router.get("/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: int, db: sqlite3.Connection = Depends(get_db)) -> Ticket:
    return _row_to_ticket(_fetch(db, ticket_id))


@router.post("/{ticket_id}/review", response_model=Ticket)
def review_ticket(
    ticket_id: int, body: TicketReview, db: sqlite3.Connection = Depends(get_db)
) -> Ticket:
    """Record a human's one decision on a queued ticket.

    ``approve`` keeps the model's draft reply exactly; ``edit`` replaces it and also
    approves; ``reject`` clears it. Category, priority and team are never changed here.
    """
    row = _fetch(db, ticket_id)
    if row["status"] != "pending_review":
        raise HTTPException(
            status_code=409, detail=f"ticket {ticket_id} was already reviewed ({row['status']})"
        )
    if body.decision == "approve" and row["model_version"] is None:
        raise HTTPException(
            status_code=409,
            detail=f"ticket {ticket_id} has no triage to approve; edit or reject it instead",
        )

    status, draft_reply = {
        "approve": ("approved", row["draft_reply"]),
        "edit": ("approved", body.draft_reply),
        "reject": ("rejected", None),
    }[body.decision]

    db.execute(
        "UPDATE tickets SET status = ?, draft_reply = ?, reviewer = ? WHERE id = ?",
        (status, draft_reply, body.reviewer, ticket_id),
    )
    db.commit()
    return _row_to_ticket(_fetch(db, ticket_id))
