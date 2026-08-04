from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from db.schema import create_tables
from src.contracts.model_change_requests import (
    ModelChangeCategory,
    ModelChangeStatus,
    ValuationModelChangeRequest,
    build_model_change_request,
    decide_model_change_request,
)
from src.stage_04_pipeline import valuation_run_store
from src.stage_04_pipeline.valuation_run_store import (
    decide_persisted_model_change_request,
    load_model_change_request,
    persist_model_change_request,
)


def _request(
    *,
    created_at: str = "2026-07-26T10:00:00Z",
) -> ValuationModelChangeRequest:
    return build_model_change_request(
        ticker="bank",
        analysis_snapshot_hash="snapshot-bank",
        category="methodology",
        current_model="industrial_fcff_v1",
        required_capability="bank_excess_capital_valuation",
        rationale="Deposits and regulatory capital make industrial net debt invalid.",
        evidence_anchor_ids=("fact:deposits", "fact:cet1"),
        evidence_fingerprints=("statement-hash", "filing-hash"),
        created_at=created_at,
    )


def test_model_change_identity_is_deterministic_and_has_no_numeric_proxy() -> None:
    first = _request()
    second = _request()

    assert first == second
    assert first.ticker == "BANK"
    assert first.status == ModelChangeStatus.pending
    assert first.request_id.startswith("model-change:")
    with pytest.raises(ValidationError, match="Extra inputs"):
        ValuationModelChangeRequest.model_validate(
            {**first.model_dump(mode="json"), "numeric_proxy": 0.08}
        )


def test_acceptance_records_implementation_intent_but_cannot_fake_a_number() -> None:
    with pytest.raises(ValueError, match="implementation intent"):
        decide_model_change_request(
            _request(),
            status="accepted",
            actor="pm",
            decided_at="2026-07-26T11:00:00Z",
        )

    accepted = decide_model_change_request(
        _request(),
        status="accepted",
        actor="pm",
        decided_at="2026-07-26T11:00:00Z",
        implementation_intent=(
            "Implement and validate a bank excess-capital methodology."
        ),
    )

    assert accepted.status == ModelChangeStatus.accepted
    assert accepted.implementation_intent.startswith("Implement")
    assert accepted.request_id == _request().request_id


def test_model_change_request_and_decision_are_persisted_with_events() -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    request = _request()

    persist_model_change_request(conn, request, actor="pipeline")
    persist_model_change_request(conn, request, actor="pipeline")
    accepted = decide_persisted_model_change_request(
        conn,
        request_id=request.request_id,
        status="accepted",
        actor="pm",
        decided_at="2026-07-26T11:00:00Z",
        implementation_intent="Build the required methodology and regression suite.",
    )

    assert load_model_change_request(conn, request.request_id) == accepted
    events = conn.execute(
        """
        SELECT event_type, actor
        FROM valuation_model_change_events
        WHERE request_id = ?
        ORDER BY event_id
        """,
        (request.request_id,),
    ).fetchall()
    assert events == [("created", "pipeline"), ("accepted", "pm")]
    with pytest.raises(ValueError, match="already been decided"):
        decide_persisted_model_change_request(
            conn,
            request_id=request.request_id,
            status="rejected",
            actor="pm",
            decided_at="2026-07-26T12:00:00Z",
        )
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM valuation_model_change_events
        WHERE request_id = ?
        """,
        (request.request_id,),
    ).fetchone()[0] == 2


def test_model_change_repersist_with_new_created_at_is_first_write_wins() -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    first = _request()
    later = _request(created_at="2026-07-27T10:00:00Z")

    assert first.request_id == later.request_id
    persist_model_change_request(conn, first, actor="pipeline")
    assert persist_model_change_request(conn, later, actor="pipeline") == first.request_id

    stored = load_model_change_request(conn, first.request_id)
    assert stored == first
    assert conn.execute(
        """
        SELECT created_at, updated_at
        FROM valuation_model_change_requests
        WHERE request_id = ?
        """,
        (first.request_id,),
    ).fetchone() == (first.created_at, first.created_at)
    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM valuation_model_change_events
        WHERE request_id = ?
        """,
        (first.request_id,),
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("category", ModelChangeCategory.applicability),
        ("rationale", "A materially different model rationale."),
        ("required_capability", "different_capability"),
        ("evidence_anchor_ids", ("fact:deposits", "fact:capital")),
        ("evidence_fingerprints", ("statement-hash", "different-filing-hash")),
    ],
)
def test_model_change_repersist_rejects_identity_payload_divergence(
    field: str,
    value: object,
) -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    request = _request()
    divergent = request.model_copy(update={field: value})

    assert divergent.request_id == request.request_id
    persist_model_change_request(conn, request, actor="pipeline")
    with pytest.raises(
        ValueError,
        match="model-change request identity has divergent payloads",
    ):
        persist_model_change_request(conn, divergent, actor="pipeline")


def test_model_change_cas_loser_writes_no_decision_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    request = _request()
    persist_model_change_request(conn, request, actor="pipeline")
    original_decide = valuation_run_store.decide_model_change_request

    def _simulate_competing_decision(*args: object, **kwargs: object):
        conn.execute(
            """
            UPDATE valuation_model_change_requests
            SET status = 'rejected'
            WHERE request_id = ?
            """,
            (request.request_id,),
        )
        return original_decide(*args, **kwargs)

    monkeypatch.setattr(
        valuation_run_store,
        "decide_model_change_request",
        _simulate_competing_decision,
    )

    with pytest.raises(ValueError, match="decision conflict"):
        decide_persisted_model_change_request(
            conn,
            request_id=request.request_id,
            status="accepted",
            actor="pm",
            decided_at="2026-07-26T11:00:00Z",
            implementation_intent="Implement it.",
        )

    events = conn.execute(
        """
        SELECT event_type
        FROM valuation_model_change_events
        WHERE request_id = ?
        ORDER BY event_id
        """,
        (request.request_id,),
    ).fetchall()
    assert events == [("created",)]
