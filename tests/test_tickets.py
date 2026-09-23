"""Ticket triage — one test per acceptance criterion in specs/spec-v1.md.

Test names carry the criterion number. When one of these goes red it points at a line
in the specification, not just at a broken function.
"""

from __future__ import annotations

from app import model_client as mc


def test_ac1_valid_ticket_returns_triage(client):
    body = client.post(
        "/tickets",
        json={
            "subject": "Cannot log in",
            "body": "My password stopped working this morning. I am locked out.",
        },
    ).json()
    assert isinstance(body["id"], int)
    assert body["status"] == "pending_review"
    triage = body["triage"]
    assert triage["category"]
    assert triage["priority"]
    assert triage["team"]
    assert body["draft_reply"]
    assert 0.0 <= triage["model"]["confidence"] <= 1.0
    assert triage["model"]["model_version"] in ("v1", "v2")


def test_ac2_no_category_match_is_general_with_unmodified_confidence(client):
    body = client.post(
        "/tickets",
        json={
            "subject": "Feature request: dark mode",
            "body": "Would be nice to have a dark theme in the catalogue.",
        },
    ).json()
    assert body["triage"]["category"] == "general"
    # the stub returns 0.44 for zero keyword hits; the endpoint must not round it up
    assert body["triage"]["model"]["confidence"] < 0.5


def test_ac3_low_confidence_sets_needs_human_attention(client, monkeypatch):
    monkeypatch.setenv("STUB_WRONGNESS", "1.0")
    mc.reset_client()
    body = client.post(
        "/tickets",
        json={"subject": "Something is wrong", "body": "It is just broken."},
    ).json()
    assert body["triage"]["model"]["confidence"] < 0.5
    assert body["needs_human_attention"] is True


def test_ac3_high_confidence_does_not_set_needs_human_attention(client):
    body = client.post(
        "/tickets",
        json={
            "subject": "Refund for duplicate charge",
            "body": "I was billed twice for my September membership. Please refund one.",
        },
    ).json()
    assert body["triage"]["model"]["confidence"] >= 0.5
    assert body["needs_human_attention"] is False


def test_ac4_missing_subject_or_body_is_still_created(client):
    no_subject = client.post(
        "/tickets", json={"subject": "", "body": "Body with no subject at all."}
    )
    assert no_subject.status_code == 201
    assert no_subject.json()["triage"] is not None

    no_body = client.post(
        "/tickets", json={"subject": "Subject with no body", "body": ""}
    )
    assert no_body.status_code == 201
    assert no_body.json()["triage"] is not None


def test_ac4_both_missing_is_rejected(client):
    r = client.post("/tickets", json={"subject": "", "body": ""})
    assert r.status_code == 422


def test_ac5_model_failure_does_not_fail_the_request(client, monkeypatch):
    monkeypatch.setenv("STUB_FAILURE_RATE", "1.0")
    mc.reset_client()
    r = client.post(
        "/tickets", json={"subject": "Site is down", "body": "Everything is broken."}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending_review"
    assert body["triage"] is None
    assert body["model_error"]


def test_ac5_model_timeout_does_not_fail_the_request(client, monkeypatch):
    monkeypatch.setenv("STUB_LATENCY_MS", "900")
    monkeypatch.setenv("STUB_TIMEOUT_MS", "100")
    monkeypatch.setenv("STUB_SLEEP", "0")
    mc.reset_client()
    r = client.post(
        "/tickets", json={"subject": "Site is down", "body": "Everything is broken."}
    )
    assert r.status_code == 201
    assert r.json()["model_error"]


def test_ac6_cannot_approve_a_ticket_with_no_triage(client, monkeypatch):
    monkeypatch.setenv("STUB_FAILURE_RATE", "1.0")
    mc.reset_client()
    created = client.post(
        "/tickets", json={"subject": "Site is down", "body": "Everything is broken."}
    ).json()
    r = client.post(f"/tickets/{created['id']}/review", json={"decision": "approve"})
    assert r.status_code == 409


def test_ac7_approve_keeps_the_models_draft_reply(client):
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    original_reply = created["draft_reply"]
    r = client.post(
        f"/tickets/{created['id']}/review", json={"decision": "approve"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["draft_reply"] == original_reply


def test_ac7_edit_replaces_the_draft_reply(client):
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    r = client.post(
        f"/tickets/{created['id']}/review",
        json={"decision": "edit", "draft_reply": "A human-written reply."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["draft_reply"] == "A human-written reply."


def test_ac8_reject_clears_the_draft_reply(client):
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    r = client.post(f"/tickets/{created['id']}/review", json={"decision": "reject"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["draft_reply"] is None

    fetched = client.get(f"/tickets/{created['id']}").json()
    assert fetched["status"] == "rejected"


def test_ac9_reviewing_twice_is_a_conflict(client):
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    first = client.post(f"/tickets/{created['id']}/review", json={"decision": "approve"})
    assert first.status_code == 200

    second = client.post(f"/tickets/{created['id']}/review", json={"decision": "reject"})
    assert second.status_code == 409

    unchanged = client.get(f"/tickets/{created['id']}").json()
    assert unchanged["status"] == "approved"


def test_ac10_near_duplicate_tickets_are_triaged_independently(client):
    first = client.post(
        "/tickets",
        json={
            "subject": "Refund for duplicate charge",
            "body": "I was billed twice for my September membership. Please refund one.",
        },
    ).json()
    second = client.post(
        "/tickets",
        json={
            "subject": "Charged twice",
            "body": "My card was charged two times for the same membership renewal.",
        },
    ).json()
    assert first["id"] != second["id"]
    assert "duplicate_of" not in first
    assert "duplicate_of" not in second


def test_ac11_filter_by_category_returns_only_matching_tickets(client):
    client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    )
    client.post(
        "/tickets",
        json={
            "subject": "Refund for duplicate charge",
            "body": "I was billed twice for my September membership.",
        },
    )
    body = client.get("/tickets", params={"category": "access"}).json()
    assert body["total"] >= 1
    assert all(item["triage"]["category"] == "access" for item in body["items"])


def test_ac12_filter_matching_nothing_returns_empty_page(client):
    body = client.get("/tickets", params={"category": "outage"}).json()
    assert body["items"] == []
    assert body["total"] == 0

def test_ac3_needs_attention_tickets_are_sorted_first(client, monkeypatch):
    # a clean, high-confidence ticket first
    client.post(
        "/tickets",
        json={
            "subject": "Refund for duplicate charge",
            "body": "I was billed twice for my September membership.",
        },
    )
    # then a low-confidence one
    monkeypatch.setenv("STUB_WRONGNESS", "1.0")
    mc.reset_client()
    client.post(
        "/tickets",
        json={"subject": "Something is wrong", "body": "It is just broken."},
    )
    monkeypatch.delenv("STUB_WRONGNESS", raising=False)
    mc.reset_client()

    body = client.get("/tickets").json()
    assert body["items"][0]["needs_human_attention"] is True


def test_ac4_both_missing_or_whitespace_is_rejected(client):
    whitespace = client.post("/tickets", json={"subject": "   ", "body": "\n\t"})
    assert whitespace.status_code == 422


def test_ac4_over_length_subject_is_rejected(client):
    r = client.post(
        "/tickets", json={"subject": "x" * 201, "body": "A normal body."}
    )
    assert r.status_code == 422


def test_ac6_normal_pending_ticket_can_still_be_approved(client):
    """Regression guard: v1's AC6 wording accidentally 409'd every unreviewed ticket."""
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    r = client.post(f"/tickets/{created['id']}/review", json={"decision": "approve"})
    assert r.status_code == 200


def test_ac7_edit_works_even_with_no_triage(client, monkeypatch):
    monkeypatch.setenv("STUB_FAILURE_RATE", "1.0")
    mc.reset_client()
    created = client.post(
        "/tickets", json={"subject": "Site is down", "body": "Everything is broken."}
    ).json()
    assert created["triage"] is None

    r = client.post(
        f"/tickets/{created['id']}/review",
        json={"decision": "edit", "draft_reply": "Manually written since triage failed."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["draft_reply"] == "Manually written since triage failed."

    fetched = client.get(f"/tickets/{created['id']}").json()
    assert fetched["draft_reply"] == "Manually written since triage failed."


def test_ac7_edit_with_empty_reply_is_rejected(client):
    created = client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    ).json()
    r = client.post(
        f"/tickets/{created['id']}/review",
        json={"decision": "edit", "draft_reply": ""},
    )
    assert r.status_code == 422


def test_ac11_unknown_filter_value_returns_empty_page_not_an_error(client):
    client.post(
        "/tickets",
        json={"subject": "Cannot log in", "body": "My password stopped working."},
    )
    r = client.get("/tickets", params={"category": "not-a-real-category"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0