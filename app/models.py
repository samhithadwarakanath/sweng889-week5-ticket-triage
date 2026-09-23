"""Request and response shapes. Everything crossing the API boundary is declared here."""

from __future__ import annotations

from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")

Kind = Literal["central", "branch", "bookmobile", "research"]


class Library(BaseModel):
    """One facility. This is the record type the whole app is built around."""

    id: int
    name: str
    city: str
    state: str = Field(min_length=2, max_length=2)
    kind: Kind
    year_founded: int
    annual_visits: int
    has_makerspace: bool


class LibraryCreate(BaseModel):
    """The write path. Note that ``id`` is assigned by the server, never by the caller."""

    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=2, max_length=2)
    kind: Kind
    year_founded: int = Field(ge=1700, le=2100)
    annual_visits: int = Field(ge=0)
    has_makerspace: bool = False


class Page(BaseModel, Generic[T]):
    """Every list endpoint returns this shape. Copy it for new list endpoints."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ModelPayload(BaseModel):
    """How a model-backed endpoint reports what the model said.

    Every model-backed response embeds this, so a caller can always see the
    confidence and which model version produced the answer.
    """

    value: object
    confidence: float
    model_version: str
    latency_ms: int


class DescribeResponse(BaseModel):
    library_id: int
    description: str
    model: ModelPayload


class ErrorBody(BaseModel):
    """The one error shape. Every 4xx and 5xx this app raises looks like this."""

    detail: str
    code: str


class SummaryResponse(BaseModel):
    """`GET /libraries/summary` — see specs/filtered-summary.md §5."""

    count: int
    filters: dict
    summary: Optional[str]
    word_count: int
    truncated: bool
    cached: bool
    model: Optional[ModelPayload]
    model_error: Optional[str]


TicketStatus = Literal["pending_review", "approved", "rejected"]


class TicketCreate(BaseModel):
    """`POST /tickets` — see specs/spec-v2.md §5. At least one field must carry text."""

    subject: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def _not_both_empty(self) -> "TicketCreate":
        if not self.subject.strip() and not self.body.strip():
            raise ValueError("a ticket needs a subject or a body")
        return self


class TicketTriage(BaseModel):
    """What the classifier suggested. ``model.confidence`` is passed through unrounded."""

    category: str
    priority: str
    team: str
    model: ModelPayload


class Ticket(BaseModel):
    """A support ticket queued for a human decision."""

    id: int
    status: TicketStatus
    subject: str
    body: str
    draft_reply: Optional[str]
    triage: Optional[TicketTriage]
    needs_human_attention: bool
    model_error: Optional[str]


class TicketReview(BaseModel):
    """`POST /tickets/{id}/review` — a human's one decision on a queued ticket."""

    decision: Literal["approve", "edit", "reject"]
    draft_reply: Optional[str] = Field(default=None, min_length=1)
    reviewer: Optional[str] = None

    @model_validator(mode="after")
    def _draft_reply_only_on_edit(self) -> "TicketReview":
        if self.decision == "edit" and self.draft_reply is None:
            raise ValueError("decision 'edit' needs a draft_reply")
        if self.decision != "edit" and self.draft_reply is not None:
            raise ValueError(f"draft_reply is only accepted with decision 'edit', not {self.decision!r}")
        return self
