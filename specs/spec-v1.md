# Feature Specification — Ticket triage

**Status:** draft
**Author:** Samhitha Dwarakanath
**Reviewers:** —
**Date:** 2026-09-23

---

## 1. Intent

Support tickets arrive as free text with no category, priority, or owning team attached,
so a human has to read every ticket before deciding who should handle it. This feature
runs each incoming ticket through the existing classification model to suggest a
category, a priority, a team, and a draft reply, and places the ticket in a queue for a
human to approve, edit, or reject before anything is acted on. The goal is to remove the
triage-reading step for clear tickets while making sure a human, not the model, is
always the one who decides what actually happens to a ticket.

## 2. User stories

- As a support agent, I want an incoming ticket to already show a suggested category,
  priority, and team, so that I can act on it without reading it cold.
- As a support agent, I want a draft reply I can approve or edit, so that I do not have
  to write a first response from nothing.
- As a support lead, I want every model suggestion to require a human decision before
  it takes effect, so that a wrong suggestion cannot reach a customer unreviewed.
- As a support agent, I want tickets the model is unsure about to be visibly marked as
  uncertain, so that I do not trust a low-confidence suggestion as if it were certain.

## 3. Acceptance criteria

1. Given a valid ticket with a subject and a body, when `POST /tickets` is called, then
   the response is HTTP 201 with a server-assigned integer `id`, `status` of
   `"pending_review"`, and a `triage` object containing `category`, `priority`, `team`,
   `draft_reply`, `confidence`, and `model_version`.
2. Given a ticket whose text produces zero keyword matches in any category (the
   `classify_ticket` stub's "general" case), when `POST /tickets` is called, then the
   response is still HTTP 201, `triage.category` is `"general"`, and
   `triage.confidence` is returned as-is (not hidden, not rounded up).
3. Given a ticket whose `triage.confidence` is below `0.5`, when the ticket is created,
   then `needs_human_attention` is `true` in the response and in `GET /tickets`. A
   confidence at or above `0.5` sets it `false`. **This flag changes nothing about what
   the human can do with the ticket — every ticket requires review regardless of
   confidence (see AC7) — it only changes how the queue is sorted and labelled.**
4. Given a ticket with an empty `subject` and a non-empty `body` (or the reverse), when
   `POST /tickets` is called, then the ticket is still created and classified using
   whichever field is present. Given both `subject` and `body` are empty or missing,
   when `POST /tickets` is called, then the response is HTTP 422 and no ticket is
   created.
5. Given the classifier raises `ModelUnavailable` or `ModelTimeout`, when
   `POST /tickets` is called, then the response is still HTTP 201, the ticket is
   created with `status` `"pending_review"`, `triage` is `null`, and `model_error` is
   set to a short reason. **The endpoint never returns 5xx because the model failed —
   an incoming ticket is never dropped for that reason.**
6. Given a ticket has `triage` `null` (AC5) or has not yet been reviewed, when
   `POST /tickets/{id}/review` is called with `decision: "approve"`, then the response
   is HTTP 409 with `code` `"conflict"`: **a ticket with no triage cannot be approved
   as-is; it may only be edited or rejected.**
7. Given a ticket with `status` `"pending_review"`, when
   `POST /tickets/{id}/review` is called with `decision: "approve"`, then `status`
   becomes `"approved"`, and the stored `draft_reply` is exactly the model's original
   text. Given the same call with `decision: "edit"` and a `draft_reply` field, then
   `status` becomes `"approved"` and the stored `draft_reply` is the human-supplied
   text, not the model's. **No draft reply is ever sent by this API; approval only
   marks the ticket ready for a reply to be sent by whatever process does that
   outside this feature.**
8. Given a ticket with `status` `"pending_review"`, when
   `POST /tickets/{id}/review` is called with `decision: "reject"`, then `status`
   becomes `"rejected"` and `draft_reply` is cleared to `null`. A rejected ticket
   still exists and is retrievable by `GET /tickets/{id}`.
9. Given a ticket that has already been reviewed (`status` is `"approved"` or
   `"rejected"`), when `POST /tickets/{id}/review` is called again, then the response
   is HTTP 409 and the ticket's stored state does not change.
10. Given two tickets whose text is a near-duplicate of each other (same problem,
    different wording — see §4), when both are submitted via `POST /tickets`, then
    both are triaged and queued independently. **This feature does not detect,
    merge, or link near-duplicate tickets in this increment** (see §4 and §8).
11. Given a filter on `GET /tickets` for `category`, `priority`, `team`, or `status`,
    when the endpoint is called, then only matching tickets are returned in a `Page`,
    following the same filter and pagination conventions as `GET /libraries`.
12. Given no tickets match a filter, when `GET /tickets` is called, then the response
    is HTTP 200 with `items` an empty list and `total` `0` — not 404.

## 4. Scope and non-goals

**In scope:** classifying one ticket at a time on creation; a single human review step
per ticket (approve, edit, or reject); a queryable, filterable, paginated queue of
tickets; surfacing model confidence and errors to the caller without hiding or
suppressing them.

**Explicitly out of scope:**

- **Duplicate detection.** Four of the sample tickets are near-duplicates of earlier
  ones (same problem, different wording). This feature does not identify, flag, or
  merge them. A future increment may add this; until then, an agent should not build
  ad hoc similarity matching into this feature.
- **Sending the draft reply.** Approving a ticket marks it ready; no email, webhook,
  or notification is sent by this feature.
- **Re-triage after edit.** Editing a `draft_reply` does not re-run the classifier or
  change `category`/`priority`/`team`.
- **Authenticated reviewer identity.** `reviewer` is a free-text field on the review
  request; there is no login system in this app to attach it to.
- **Escalation workflows.** All-caps or urgent-language tickets (e.g. sample ticket
  T-022) are not treated specially beyond the ordinary `priority: "high"` the
  classifier already assigns when urgency keywords are present. There is no separate
  escalation path, paging, or SLA timer in this increment.
- **Bulk operations.** No bulk import, bulk review, or bulk re-classification endpoint.

## 5. Interfaces and contracts

```
POST /tickets
{
  "subject": "Cannot log in",
  "body": "My password stopped working this morning. I am locked out."
}

201
{
  "id": 1,
  "status": "pending_review",
  "subject": "Cannot log in",
  "body": "My password stopped working this morning. I am locked out.",
  "triage": {
    "category": "access",
    "priority": "normal",
    "team": "identity",
    "draft_reply": "Thanks for writing in. I have started a reset on your account.",
    "confidence": 0.86,
    "model_version": "v1"
  },
  "needs_human_attention": false,
  "model_error": null
}
```

```
GET /tickets?category=access&status=pending_review&limit=50&offset=0

200
{
  "items": [ { ...ticket shape above... } ],
  "total": 3,
  "limit": 50,
  "offset": 0
}
```

```
GET /tickets/{id}

200  -> the same ticket shape as POST /tickets returns
404  -> ErrorBody, code "not_found"
```

```
POST /tickets/{id}/review
{ "decision": "approve" }
  | { "decision": "edit", "draft_reply": "<human-edited text>" }
  | { "decision": "reject" }
  , "reviewer": "<free text, optional>"

200 -> the updated ticket, same shape as above, with `status` changed
409 -> ErrorBody, code "conflict"  (already reviewed, or approving with no triage)
422 -> ErrorBody's FastAPI validation shape (missing draft_reply on an "edit" decision)
```

`triage` is `null` only when `model_error` is set (AC5). `needs_human_attention` is
always a boolean, even when `triage` is `null` (treat a failed classification as
needing attention: `true`).

## 6. Constraints

- **Design system / UI:** n/a — this is a backend-only API feature; no UI is built or
  changed here.
- **Security:** n/a beyond what already exists — this app has no authentication
  system, so `reviewer` is unauthenticated free text, named explicitly in §4.
- **Performance:** a single `POST /tickets` call makes exactly one call to the model
  client. `GET /tickets` makes zero. Pagination follows the existing `limit`
  (default 50, max 200) and `offset` (default 0) conventions from `api-conventions`.
- **Compatibility:** does not change any existing endpoint or model. `Page` is reused
  as-is for `GET /tickets`, following the same shape as `GET /libraries`.
- **Other:** two-letter fields do not apply here; no localization or accessibility
  surface exists for a JSON API.
- **Model access:** exclusively through `app.model_client.get_client()`, calling the
  `classify_ticket` task, per `api-conventions`.
- **Error shapes:** validation failures use FastAPI's standard 422 body. All other
  errors use `ErrorBody` (`detail`, `code`), with `code` values `"not_found"` and
  `"conflict"` for this feature. **This feature does not use `503`/`504` for a model
  failure** — that is a deliberate departure from `describe_library`'s pattern,
  because losing an incoming support ticket is worse than storing it without a
  suggestion (see AC5).
- **Confidence is never hidden or thresholded away.** It is always present in the
  response when `triage` is not `null`. The `< 0.5` boundary only sets
  `needs_human_attention`; it does not change what actions are available.

## 7. Test plan

One test per criterion in `tests/test_tickets.py`, named `test_ac<N>_...`, following
the `testing` skill's conventions (the `client` fixture on a throwaway database; the
`stub` fixture or direct `StubModelClient(...)` construction to force degraded,
failing, or timed-out behaviour; `sleep=False` whenever latency is simulated).

| AC | Covered by |
|---|---|
| 1 | happy path: real ticket text that matches a category cleanly (e.g. the T-002 login text) |
| 2 | ticket text with no category keywords; assert `category == "general"` and confidence is returned unmodified |
| 3 | `StubModelClient(wrongness=1.0)` (confidence capped at 0.41) asserts `needs_human_attention: true`; a clean high-confidence call asserts `false` |
| 4 | one ticket with empty `subject`, one with empty `body` — both created; one with both empty — 422 |
| 5 | `StubModelClient(failure_rate=1.0)` and a forced timeout — both assert 201, `triage: null`, `model_error` set |
| 6 | create a ticket with a forced model failure, then attempt `decision: "approve"` — assert 409 |
| 7 | approve a normal ticket — assert stored `draft_reply` equals the model's text; edit a ticket — assert stored `draft_reply` equals the supplied text, not the model's |
| 8 | reject a ticket — assert `status == "rejected"` and `draft_reply is None` |
| 9 | review a ticket twice — second call asserts 409 and the ticket's `status` is unchanged from the first review |
| 10 | submit two near-duplicate ticket texts (from the fixture) — assert both are created as independent tickets with no linkage field |
| 11 | create tickets across at least two categories; filter `GET /tickets` by one — assert only matching tickets returned |
| 12 | filter `GET /tickets` on a value matching nothing — assert 200, `items: []`, `total: 0` |

## 8. Open questions

- Should `needs_human_attention` ever be settable by a human directly (e.g. flagging
  a high-confidence ticket for a second look), or is it purely model-derived? Ask
  product before building any manual-override path.
- Should an edited `draft_reply` be validated for length or content in any way, or is
  free text acceptable without limit? Unanswered — no length cap is specified here.
- If duplicate detection is added in a future increment, should it run at creation
  time or as a background pass? Out of scope here, but the answer will decide whether
  `POST /tickets` needs to change shape later.
