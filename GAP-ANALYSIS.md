# Gap Analysis — Ticket Triage

## What the agent assumed during reconnaissance

I gave a fresh agent just one line: "Add a support ticket triage feature: incoming tickets get a category, priority, and suggested team, plus a draft reply, and queue up for a human to review." No hints about edge cases, confidence, or anything else. Here's what it quietly decided on its own.

It picked a 503/504 style failure for a down or timed out classifier, the same pattern `describe_library` uses, meaning a failed model call would have failed the whole request and the ticket would never get saved. It never questioned whether losing an incoming support ticket because the model happened to be down was actually the right tradeoff.

It never applied any confidence threshold at all. Every ticket just got whatever the model returned, shown as certain, with nothing in the response distinguishing a confident classification from a shaky one.

It didn't attempt any duplicate detection, even though four of the sample tickets in `data/tickets.json` are obvious near duplicates of earlier ones (T-001/T-011, T-002/T-012, T-003/T-013, T-004/T-014).

Its validation rule only rejected a ticket when subject and body were *both* empty. That means T-020 (empty subject, real body) and T-021 (real subject, empty body), both deliberately planted fixtures, would have sailed through untouched, and nothing would have flagged that as worth deciding on purpose rather than by accident.

It made replies single shot and one directional: `pending_review` to `approved`/`rejected`, no path back, no re-triage on edit. Reasonable, but entirely its own call, not something I'd asked for.

It picked server assigned integer ids instead of the `T-001` style strings from the fixture file, again without flagging it as a decision.

## Which acceptance criteria passed and which didn't (round 1)

All twelve acceptance criteria technically passed in round 1: 69 out of 69 tests were green, including all 16 tests in `tests/test_tickets.py`, and I reran `make test` myself rather than trusting the agent's own report. So on paper, round 1 looks like a clean win.

But "the tests I wrote all passed" isn't the same as "the spec communicated cleanly." Two things showed up in round 1 that no test caught, because I hadn't thought to test for them; they only showed up in the agent's own list of assumptions it had to make.

## What was missing or ambiguous in spec v1

**AC6 versus AC7, a real contradiction.** AC6 in v1 said:

> "Given a ticket has `triage` `null` (AC5) or has not yet been reviewed, when `POST /tickets/{id}/review` is called with `decision: "approve"`, then the response is HTTP 409..."

That "or has not yet been reviewed" clause quietly makes the rule apply to every single pending ticket, not just ones with a failed classification, which directly contradicts AC7 saying a normal pending ticket with real triage should be approvable. The agent picked the reading that made the feature actually usable (only block approval when `triage` is null), which was the right call, but it had to guess, and a different agent could easily have gone the other way and made approval broken for every ticket. I rewrote it in v2 as:

> "Given a ticket has `triage` `null` (its classification failed), when `POST /tickets/{id}/review` is called with `decision: "approve"`, then the response is HTTP 409... A ticket that has triage and has simply not been reviewed yet is not covered by this criterion, see AC7."

**Editing a ticket with no triage had nowhere to go.** v1's AC7 let a human edit a ticket even when `triage` was null, since AC6 only blocked approve, not edit. But `draft_reply` lived only inside `triage` in v1's response shape, so an edited reply on a null triage ticket would be saved with genuinely nowhere for the API to show it back. I hadn't noticed this interaction until the agent pointed it out. Fixed in v2 by moving `draft_reply` to a top level field on the ticket, present whether or not `triage` is null.

**The repo's own model convention wasn't followed.** `api-conventions` says every model backed response should embed a full `ModelPayload` (value, confidence, model_version, latency_ms), the way `describe_library` does. v1's example response just put flat `confidence` and `model_version` fields directly on `triage`, no `latency_ms`, no raw `value`. The agent followed my spec instead of the repo convention, which was the correct thing for it to do, since the spec is supposed to be the source of truth, but it meant v1 quietly broke a stated convention without anyone deciding that on purpose. Fixed in v2 by nesting a proper `ModelPayload` under `triage.model`.

**Unknown filter values were never addressed.** v1 never said what `GET /tickets?category=bogus` should do: 422 for an unrecognized value, or 200 with an empty result like any other filter that matches nothing. This wasn't caught by any test in round 1 because I hadn't written one, so it slipped through as a silent gap rather than a documented decision. v2 makes it explicit: unknown values behave like any other non matching filter and return 200 with an empty page.

## What round 2 still got wrong, and what a v3 would change

Round 2 passed cleanly too (76 out of 76 once I added tests for the new behavior), but a few things came out of round 2's own assumption list that are still genuinely unresolved.

There's no database migration story. The new columns for `model_value` and `latency_ms` use `CREATE TABLE IF NOT EXISTS`, so an existing local `app.db` from round 1 wouldn't pick up the new columns and ticket creation would just start failing. The tests are unaffected because they run on a throwaway database, but nothing in either spec addresses schema evolution at all. A v3 would need to either specify a migration path or explicitly say this app has no upgrade story and a fresh database is expected between spec versions.

The confidence threshold (0.5) is still borrowed from an existing constant in `libraries.py` rather than being its own named value in this feature. It works, but it means the ticket feature's behavior is quietly tied to a constant defined for a completely different feature. A v3 should give ticket triage its own explicitly named threshold, even if it happens to equal 0.5 today.

Queue ordering for tickets with equal `needs_human_attention` still just falls back to `id` order, since there's no timestamp column at all. That's a reasonable stand in for "oldest first," but it was never actually specified as intentional versus incidental, and it would break the moment ids stopped being sequential (say, if tickets ever got imported from somewhere else).

Filter matching is exact and case sensitive, still never explicitly decided in either spec version. `category=Access` versus `category=access` would behave differently and nothing says whether that's correct.

An open question that's now been open through two full rounds: whether `triage.model.value`, the full raw classifier output, should ever be treated as a second source of truth if it somehow disagreed with the typed `category`/`priority`/`team` fields sitting next to it. Neither version answers this, and it's the same ambiguity `api-conventions` already has for `describe_library`.

## Where the spec went too far

A couple of places in v2 arguably specify more than they need to.

The exact model_error string prefixes ("model unavailable: " and "model timed out: ") are probably over specified. What actually matters to a caller is that `model_error` is a non-empty, human readable string when the classifier fails, and maybe that the two failure modes are distinguishable somehow if a caller cares. Locking the literal string prefix ties the implementation to wording that has no real reason to be part of the contract, and it's the kind of detail the "how to write a spec" skill file specifically warns against, since it edges toward specifying implementation rather than observable behavior.

The subject and body length caps (200 and 500 characters) are also arguably too specific for a first spec. They're reasonable numbers, but I only kept them because the earlier, discarded reconnaissance code happened to have them, not because anything about the feature's intent actually requires those exact limits. A looser first version might have just said "a maximum length applies to prevent unbounded input" and left the exact numbers as an open question for whoever owns validation limits elsewhere in the app, rather than baking in numbers that came from code I told the assignment to throw away.
