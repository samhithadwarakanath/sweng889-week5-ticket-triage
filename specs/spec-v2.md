# Feature Specification — Ticket triage

**Status:** draft
**Author:** Samhitha Dwarakanath
**Reviewers:** —
**Date:** 2026-09-23

> Revision of `spec-v1.md`, after a blind handoff and independent test run against it.
> Every change below is driven by a specific finding from that round; see
> `GAP-ANALYSIS.md` for the evidence. Sections unchanged from v1 are marked as such.

---

## 1. Intent

*(unchanged from v1)*

Support tickets arrive as free text with no category, priority, or owning team attached,
so a human has to read every ticket before deciding who should handle it. This feature
runs each incoming ticket through the existing classification model to suggest a
category, a priority, a team, and a draft reply, and places the ticket in a queue for a
human to approve, edit, or reject before anything is acted on. The goal is to remove the
triage-reading step for clear tickets while making sure a human, not the model, is
always the one who decides what actually happens to a ticket.

## 2. User stories

*(unchanged from v1)*

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
   `"pending_review"`, a top-level `draft_reply`, and a `triage` object containing
   `category`, `priority`, `team`, and `model` (see §5). *(unchanged from v1)*

2. Given a ticket whose text produces zero keyword matches in any category (the
   `classify_ticket` stub's "general" case), when `POST /tickets` is called, then the
   response is still HTTP 201, `triage.category` is `"general"`, and
   `triage.model.confidence` is returned as-is, unrounded — not hidden, not rounded up.
   *(unchanged from v1, field path updated for §5's new shape)*

3. Given a ticket whose `triage.model.confidence` is below `0.5`, when the ticket is
   created, then `needs_human_attention` is `true` in the response and in
   `GET /tickets`. A confidence at or above `0.5` sets it `false`. This flag changes
   nothing about what the human can do with the ticket — every ticket requires review
   regardless of confidence (see AC7) — it changes two things: how the queue is
   sorted (§6) and this label. *(unchanged from v1, plus explicit sort-order pointer)*

4. Given a ticket with an empty or whitespace-only `subject` and a non-empty `body`
   (or the reverse), when `POST /tickets` is called, then the ticket is still created
   and classified using whichever field is present. Given both `subject` and `body`
   are empty, whitespace-only, or missing, when `POST /tickets` is called, then the
   response is HTTP 422 and no ticket is created. **`subject` is capped at 200
   characters and `body` at 5000 characters; a longer value is HTTP 422.**
   *(unchanged from v1, with the length caps now stated explicitly rather than
   inherited silently from earlier code)*

5. Given the classifier raises `ModelUnavailable` or `ModelTimeout`, when
   `POST /tickets` is called, then the response is still HTTP 201, the ticket is
   created with `status` `"pending_review"`, `triage` is `null`, `draft_reply` is
   `null`, and `model_error` is set to a short reason beginning with `"model
   unavailable: "` or `"model timed out: "`. The endpoint never returns 5xx because
   the model failed. *(unchanged from v1, error message format now specified)*

6. **[Revised — was ambiguous in v1.]** Given a ticket has `triage` `null` (its
   classification failed), when `POST /tickets/{id}/review` is called with
   `decision: "approve"`, then the response is HTTP 409 with `code` `"conflict"`. A
   ticket with no triage may only be edited or rejected, never approved as-is. **A
   ticket that has triage and has simply not been reviewed yet is not covered by this
   criterion — see AC7.**

   > v1 said: *"Given a ticket has `triage` `null` (AC5) **or has not yet been
   > reviewed**, when ... approve ... then 409."* The "or has not yet been reviewed"
   > clause made this criterion cover every ordinary pending ticket too, directly
   > contradicting AC7. Removed.

7. Given a ticket with `status` `"pending_review"` and a non-null `triage`, when
   `POST /tickets/{id}/review` is called with `decision: "approve"`, then `status`
   becomes `"approved"` and `draft_reply` is unchanged. Given the same call with
   `decision: "edit"` and a non-empty `draft_reply` field, then `status` becomes
   `"approved"` and the top-level `draft_reply` is replaced with the human-supplied
   text. **This applies whether or not `triage` is null** — a human may write a reply
   from scratch when classification failed. No draft reply is ever sent by this API;
   approval only marks the ticket ready for a reply to be sent by whatever process
   does that outside this feature.

   > v1 left the null-triage-edit case with nowhere in the response to show the
   > result, because `draft_reply` lived only inside `triage`. `draft_reply` is now a
   > top-level field on the ticket (§5) so this case has somewhere to go.

8. Given a ticket with `status` `"pending_review"`, when
   `POST /tickets/{id}/review` is called with `decision: "reject"`, then `status`
   becomes `"rejected"` and the top-level `draft_reply` is cleared to `null`. A
   rejected ticket still exists and is retrievable by `GET /tickets/{id}`.
   *(unchanged from v1, field path updated)*

9. Given a ticket that has already been reviewed (`status` is `"approved"` or
   `"rejected"`), when `POST /tickets/{id}/review` is called again, then the response
   is HTTP 409 and the ticket's stored state does not change. *(unchanged from v1)*

10. Given two tickets whose text is a near-duplicate of each other (same problem,
    different wording — see §4), when both are submitted via `POST /tickets`, then
    both are triaged and queued independently. This feature does not detect, merge,
    or link near-duplicate tickets in this increment. *(unchanged from v1)*

11. Given a filter on `GET /tickets` for `category`, `priority`, `team`, or `status`,
    when the endpoint is called, then only matching tickets are returned in a `Page`,
    following the same filter and pagination conventions as `GET /libraries`.
    **[New] A filter value that does not match any known category, priority, team, or
    status is not an error: it behaves like any other value that matches nothing (see
    AC12).** *(v1 did not say; this makes it explicit rather than leaving 200-vs-422
    to be guessed)*

12. Given no tickets match a filter — including a filter value that is not one of the
    known categories, priorities, teams, or statuses — when `GET /tickets` is called,
    then the response is HTTP 200 with `items` an empty list and `total` `0`, never
    404 or 422. *(unchanged from v1, scope widened to explicitly cover unknown
    filter values per AC11)*

## 4. Scope and non-goals

*(unchanged from v1)*

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
- **Re-triage after edit.** Editing `draft_reply` does not re-run the classifier or
  change `category`/`priority`/`team`.
- **Authenticated reviewer identity.** `reviewer` is a free-text field on the review
  request, stored but never returned in any response; there is no login system in
  this app to attach it to. *(the "never returned" clause is new in v2 — v1 implied
  it but did not say it, and the round-1 implementation had to guess)*
- **Escalation workflows.** All-caps or urgent-language tickets (e.g. sample ticket
  T-022) are not treated specially beyond the ordinary `priority: "high"` the
  classifier already assigns when urgency keywords are present. There is no separate
  escalation path, paging, or SLA timer in this increment.
- **Bulk operations.** No bulk import, bulk review, or bulk re-classification endpoint.

## 5. Interfaces and contracts

**[Revised — `draft_reply` is now top-level; `triage` embeds `ModelPayload` under
`model`, per `api-conventions`, instead of flattening `confidence`/`model_version`
directly onto `triage`.]**

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
  "draft_reply": "Thanks for writing in. I have started a reset on your account.",
  "triage": {
    "category": "access",
    "priority": "normal",
    "team": "identity",
    "model": {
      "value": {"category": "access", "priority": "normal", "team": "identity",
                "draft_reply": "Thanks for writing in. I have started a reset on your account."},
      "confidence": 0.86,
      "model_version": "v1",
      "latency_ms": 0
    }
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

Queue ordering (unfiltered or filtered): `needs_human_attention: true` tickets first,
then oldest-created first within each group.

```
GET /tickets/{id}

200  -> the same ticket shape as POST /tickets returns
404  -> ErrorBody, code "not_found"
```

```
POST /tickets/{id}/review
{ "decision": "approve" }
  | { "decision": "edit", "draft_reply": "<non-empty human-edited text>" }
  | { "decision": "reject" }
  , "reviewer": "<free text, optional, never echoed back>"

200 -> the updated ticket, same shape as above, with `status` and `draft_reply` changed
409 -> ErrorBody, code "conflict"  (already reviewed, or approving with no triage)
422 -> ErrorBody's FastAPI validation shape (empty draft_reply on "edit"; draft_reply
       supplied on "approve" or "reject")
```

`triage` is `null` only when `model_error` is set (AC5); when `triage` is `null`,
`draft_reply` starts `null` too but may still be set later via an edit (AC7).
`needs_human_attention` is always a boolean, even when `triage` is `null` (a failed
classification counts as needing attention: `true`).

## 6. Constraints

- **Design system / UI:** n/a — this is a backend-only API feature; no UI is built or
  changed here.
- **Security:** n/a beyond what already exists — this app has no authentication
  system, so `reviewer` is unauthenticated free text, named explicitly in §4.
- **Performance:** a single `POST /tickets` call makes exactly one call to the model
  client. `GET /tickets` makes zero. Pagination follows the existing `limit`
  (default 50, max 200) and `offset` (default 0) conventions from `api-conventions`.
- **Compatibility:** does not change any existing endpoint's behavior. `Page` is now
  generic (`Page[T]`) so `GET /tickets` and `GET /libraries` share one shape; this is
  a compatible widening, not a breaking change to `GET /libraries`.
- **Other:** two-letter fields do not apply here; no localization or accessibility
  surface exists for a JSON API.
- **Model access:** exclusively through `app.model_client.get_client()`, calling the
  `classify_ticket` task, per `api-conventions`. **The response embeds `ModelPayload`
  under `triage.model`, exactly as `describe_library` does — this was not followed in
  v1 and is corrected here.**
- **Error shapes:** validation failures use FastAPI's standard 422 body. All other
  errors use `ErrorBody` (`detail`, `code`), with `code` values `"not_found"` and
  `"conflict"` for this feature. This feature does not use `503`/`504` for a model
  failure — that is a deliberate departure from `describe_library`'s pattern, because
  losing an incoming support ticket is worse than storing it without a suggestion
  (see AC5).
- **Confidence is never hidden or thresholded away.** It is always present in
  `triage.model.confidence` when `triage` is not `null`. The `< 0.5` boundary only
  sets `needs_human_attention` and queue order (§5); it does not change what actions
  are available.
- **Length limits:** `subject` ≤ 200 characters, `body` ≤ 5000 characters (AC4).

## 7. Test plan

One test per criterion in `tests/test_tickets.py`, named `test_ac<N>_...`, following
the `testing` skill's conventions. **Tests from v1 that referenced `triage.confidence`
or `triage.draft_reply` directly must be updated to `triage.model.confidence` and the
new top-level `draft_reply`, per §5's revised shape.**

| AC | Covered by |
|---|---|
| 1 | happy path: real ticket text that matches a category cleanly; assert top-level `draft_reply` and `triage.model` both present |
| 2 | ticket text with no category keywords; assert `category == "general"` and `triage.model.confidence` returned unmodified |
| 3 | `StubModelClient(wrongness=1.0)` asserts `needs_human_attention: true`; a clean high-confidence call asserts `false`; assert ordering in `GET /tickets` places the low-confidence ticket first |
| 4 | one ticket with empty `subject`, one with empty `body` — both created; one with both empty (or whitespace-only) — 422; a 201-character subject — 422 |
| 5 | `StubModelClient(failure_rate=1.0)` and a forced timeout — both assert 201, `triage: null`, `draft_reply: null`, `model_error` matching the specified prefix |
| 6 | create a ticket with a forced model failure, then attempt `decision: "approve"` — assert 409; **and** create a normal ticket with real triage and confirm approve succeeds (guards against the v1 regression) |
| 7 | approve a normal ticket — assert `draft_reply` unchanged; edit a normal ticket — assert `draft_reply` replaced; **edit a null-triage ticket — assert the human's reply is now readable at the top level** |
| 8 | reject a ticket — assert `status == "rejected"` and top-level `draft_reply` is `None` |
| 9 | review a ticket twice — second call asserts 409 and the ticket's `status` is unchanged from the first review |
| 10 | submit two near-duplicate ticket texts (from the fixture) — assert both are created as independent tickets with no linkage field |
| 11 | filter by a known category — assert only matching tickets returned; filter by an unknown/bogus category value — assert 200 with an empty page, not 422 |
| 12 | filter matching nothing (known value, zero matches) — assert 200, `items: []`, `total: 0` |

## 8. Open questions

*(unchanged from v1, plus one new item)*

- Should `needs_human_attention` ever be settable by a human directly (e.g. flagging
  a high-confidence ticket for a second look), or is it purely model-derived? Ask
  product before building any manual-override path.
- If duplicate detection is added in a future increment, should it run at creation
  time or as a background pass? Out of scope here, but the answer will decide whether
  `POST /tickets` needs to change shape later.
- **[New]** Should the raw `triage.model.value` (the full classifier dict) be
  trusted as a second source of truth if it ever disagrees with `triage.category` /
  `triage.priority` / `triage.team`, or are the typed fields always authoritative?
  Unanswered — this repeats a question `api-conventions` raises generally
  (`describe_library` has the same duplication) and was not resolved for this
  feature either.
