from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from db.schema import create_tables
from src.contracts.analysis_snapshot import AnalysisSnapshot
from src.contracts.assumption_registry import (
    ASSUMPTION_REGISTRY,
    DriverFamily,
    ScenarioDirection,
    judgment_owned_fields,
)
from src.contracts.judgment_runs import ProviderRoute
from src.stage_03_judgment.judgment_gateway import JudgmentBackendResponse
from src.stage_04_pipeline.valuation_judgment_pipeline import (
    DriverFamilyExecutionBinding,
    run_valuation_judgment_pipeline,
)
from tests.valuation_provenance_fixtures import (
    authoritative_snapshot,
    persist_snapshot_provenance,
)


def _create_support_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS valuation_artifact_integrity (
            artifact_type TEXT NOT NULL,
            artifact_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_type, artifact_key)
        );
        CREATE TABLE IF NOT EXISTS judgment_invocation_reservations (
            invocation_hash TEXT PRIMARY KEY,
            owner_run_id TEXT NOT NULL,
            reserved_at_epoch REAL NOT NULL,
            lease_expires_at_epoch REAL NOT NULL
        );
        """
    )
    persist_snapshot_provenance(conn, _snapshot())


def _snapshot() -> AnalysisSnapshot:
    evidence = {
        f"fact:{name}": {"value": index}
        for index, name in enumerate(judgment_owned_fields(), start=1)
    }
    evidence["fact:wacc:peer-set"] = {"peers": ["AAA", "BBB"]}
    return authoritative_snapshot(
        {
            "ticker": "TEST",
            "as_of_date": "2026-07-26",
            "identity": {"cik": "0000000001"},
            "statements": {"annual_periods": 5, "ltm_status": "compatible"},
            "statement_reconciliation": {"status": "reconciled"},
            "claim_ledger": {"status": "reconciled"},
            "market_inputs": {
                "price": 10.0,
                "operating_reconciliation": {
                    "status": "reconciled",
                    "unresolved_clamp_count": 0,
                },
            },
            "wacc_inputs": {"wacc": 0.09},
            "comps_inputs": {"peer_count": 4},
            "evidence": evidence,
            "upstream_context": {
                "business": {"status": "complete"},
                "industry": {"status": "complete"},
            },
            "source_fingerprints": {"xbrl": "xbrl-hash", "ciq": "ciq-hash"},
            "component_versions": {
                "snapshot_builder": "v1",
                "valuation_model": "industrial_fcff_v1",
            },
            "captured_at": "2026-07-26T10:00:00Z",
        }
    )


def _route(family: DriverFamily, role: str) -> ProviderRoute:
    return ProviderRoute.model_validate(
        {
            "route_id": f"{family.value}-{role}",
            "provider": "fixture",
            "adapter_id": "fixture",
            "adapter_version": "v1",
            "requested_model": f"fixture-{role}",
            "endpoint_capability": "structured",
            "sampling": {"temperature": 0.0},
        }
    )


def _proposal(family: DriverFamily) -> dict[str, object]:
    assumptions = []
    for name in judgment_owned_fields(family):
        definition = ASSUMPTION_REGISTRY[name]
        if definition.scenario_direction == ScenarioDirection.descending:
            values = (0.03, 0.02, 0.01)
        elif definition.scenario_direction == ScenarioDirection.unordered:
            values = (0.02, 0.02, 0.02)
        else:
            values = (0.01, 0.02, 0.03)
        assumptions.append(
            {
                "assumption_name": name,
                "unit": definition.unit.value,
                "applicability": "applicable",
                "low": values[0],
                "base": values[1],
                "high": values[2],
                "conditions": {
                    "low": f"Low condition for {name}.",
                    "base": f"Base condition for {name}.",
                    "high": f"High condition for {name}.",
                },
                "rationale": f"Evidence-grounded rationale for {name}.",
                "evidence_anchor_ids": [f"fact:{name}"],
                "what_would_change_view": f"New evidence for {name}.",
            }
        )
    return {
        "family": family.value,
        "horizon_years": 10,
        "assumptions": assumptions,
        "family_rationale": f"Direct scenarios for {family.value}.",
    }


class _Backend:
    def __init__(self) -> None:
        self.call_count = 0
        self.requests = []

    def generate(self, request):
        self.call_count += 1
        self.requests.append(request)
        if request.task.role == "critic":
            output = {
                "family": request.task.family,
                "verdict": "accept",
                "issues": [],
                "summary": "The complete family is supported.",
            }
        else:
            output = _proposal(DriverFamily(request.task.family))
        return JudgmentBackendResponse(
            output=output,
            actual_model=request.route.requested_model,
            provider_request_id=f"{request.task.family}:{request.task.role}",
        )


class _ConcurrentBackend(_Backend):
    def __init__(self, barrier: threading.Barrier) -> None:
        super().__init__()
        self.barrier = barrier
        self._lock = threading.Lock()
        self.active_primary = 0
        self.max_active_primary = 0

    def generate(self, request):
        if request.task.role == "primary":
            with self._lock:
                self.active_primary += 1
                self.max_active_primary = max(
                    self.max_active_primary,
                    self.active_primary,
                )
            try:
                self.barrier.wait(timeout=1.0)
            finally:
                with self._lock:
                    self.active_primary -= 1
        return super().generate(request)


class _ConcurrentFailureBackend(_ConcurrentBackend):
    def generate(self, request):
        if request.task.family == DriverFamily.revenue.value:
            raise RuntimeError("fixture concurrent revenue failure")
        return super().generate(request)


class _PermanentFailingRevenueBackend(_Backend):
    def generate(self, request):
        if request.task.family == DriverFamily.revenue.value:
            raise RuntimeError("fixture permanent provider failure")
        return super().generate(request)


class _TimeoutRevenueBackend(_Backend):
    def generate(self, request):
        if request.task.family == DriverFamily.revenue.value:
            raise TimeoutError("fixture provider timeout")
        return super().generate(request)


class _MethodologyChallengeBackend(_Backend):
    def generate(self, request):
        if (
            request.task.role == "critic"
            and request.task.family
            == DriverFamily.terminal_capital_comps.value
        ):
            return JudgmentBackendResponse(
                output={
                    "family": request.task.family,
                    "verdict": "accept",
                    "issues": [],
                    "methodology_challenges": [
                        {
                            "code": "wacc_peer_method_not_representative",
                            "severity": "warning",
                            "category": "methodology",
                            "required_capability": (
                                "issuer_specific_wacc_methodology"
                            ),
                            "rationale": (
                                "The frozen peer set does not represent the "
                                "issuer's regulated capital structure."
                            ),
                            "evidence_anchor_ids": [
                                "fact:wacc:peer-set"
                            ],
                        }
                    ],
                    "summary": (
                        "The family is coherent; WACC methodology needs PM review."
                    ),
                },
                actual_model=request.route.requested_model,
                provider_request_id="methodology-challenge",
            )
        return super().generate(request)


def _bindings() -> dict[DriverFamily, DriverFamilyExecutionBinding]:
    return {
        family: DriverFamilyExecutionBinding(
            primary_route=_route(family, "primary"),
            primary_backend=_Backend(),
            critic_route=_route(family, "critic"),
            critic_backend=_Backend(),
        )
        for family in DriverFamily
    }


def test_pipeline_persists_one_snapshot_all_runs_and_four_atomic_queue_items() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()

    result = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
        transport_timeout_seconds=31.75,
    )

    assert result.status == "queued"
    assert set(result.family_results) == set(DriverFamily)
    assert len(result.queue_item_ids) == 4
    assert result.blocker_reasons == {}
    assert conn.execute("SELECT COUNT(*) FROM analysis_snapshots").fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM judgment_run_envelopes").fetchone()[0]
        == 8
    )
    rows = conn.execute(
        "SELECT proposal_pack_json FROM pm_decision_queue_items"
    ).fetchall()
    assert len(rows) == 4
    assert all('"proposal_scope":"low_base_high"' in row[0] for row in rows)
    assert {
        family_result.primary_envelope.task.frozen_snapshot_hash
        for family_result in result.family_results.values()
    } == {_snapshot().snapshot_hash}
    requests = [
        request
        for binding in bindings.values()
        for backend in (binding.primary_backend, binding.critic_backend)
        for request in backend.requests
    ]
    assert len(requests) == 8
    assert {request.transport_timeout_seconds for request in requests} == {31.75}


def test_pipeline_runs_families_concurrently_but_persists_deterministically() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    tracker = _ConcurrentBackend(threading.Barrier(4))
    bindings = {
        family: DriverFamilyExecutionBinding(
            primary_route=binding.primary_route,
            primary_backend=tracker,
            critic_route=binding.critic_route,
            critic_backend=tracker,
        )
        for family, binding in _bindings().items()
    }

    first = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
    )
    second = run_valuation_judgment_pipeline(
        snapshot=_snapshot().model_copy(
            update={"captured_at": "2026-07-26T11:00:00Z"}
        ),
        bindings=bindings,
        conn=conn,
    )

    assert first.status == "queued"
    assert tracker.max_active_primary == 4
    assert list(first.family_results) == list(DriverFamily)
    assert second.queue_item_ids == first.queue_item_ids
    assert tracker.call_count == 8
    queue_rows = conn.execute(
        "SELECT proposal_pack_json FROM pm_decision_queue_items ORDER BY id"
    ).fetchall()
    assert [json.loads(row[0])["family"] for row in queue_rows] == [
        family.value for family in DriverFamily
    ]


def test_concurrent_family_failure_does_not_cancel_other_families() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    tracker = _ConcurrentFailureBackend(threading.Barrier(3))
    bindings = {
        family: DriverFamilyExecutionBinding(
            primary_route=binding.primary_route,
            primary_backend=tracker,
            critic_route=binding.critic_route,
            critic_backend=tracker,
        )
        for family, binding in _bindings().items()
    }

    result = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
    )

    assert result.status == "partial"
    assert result.blocker_reasons == {
        DriverFamily.revenue: "primary_judgment_failed"
    }
    assert set(result.queue_item_ids) == set(DriverFamily) - {
        DriverFamily.revenue
    }
    assert tracker.max_active_primary == 3


def test_pipeline_is_queue_idempotent_for_the_same_semantic_snapshot() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()

    first = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
    )
    second = run_valuation_judgment_pipeline(
        snapshot=_snapshot().model_copy(
            update={"captured_at": "2026-07-26T11:00:00Z"}
        ),
        bindings=bindings,
        conn=conn,
    )

    assert second.snapshot_hash == first.snapshot_hash
    assert second.queue_item_ids == first.queue_item_ids
    assert conn.execute(
        "SELECT COUNT(*) FROM pm_decision_queue_items"
    ).fetchone()[0] == 4
    assert conn.execute(
        "SELECT COUNT(*) FROM judgment_run_envelopes"
    ).fetchone()[0] == 8
    assert sum(
        binding.primary_backend.call_count
        + binding.critic_backend.call_count
        for binding in bindings.values()
    ) == 8

    forced = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
        force_refresh=True,
    )

    assert forced.queue_item_ids == first.queue_item_ids
    assert conn.execute(
        "SELECT COUNT(*) FROM judgment_run_envelopes"
    ).fetchone()[0] == 16
    assert sum(
        binding.primary_backend.call_count
        + binding.critic_backend.call_count
        for binding in bindings.values()
    ) == 16


def test_pipeline_reports_partial_without_hiding_a_failed_family() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()
    revenue = bindings[DriverFamily.revenue]
    bindings[DriverFamily.revenue] = DriverFamilyExecutionBinding(
        primary_route=revenue.primary_route,
        primary_backend=_PermanentFailingRevenueBackend(),
        critic_route=revenue.critic_route,
        critic_backend=revenue.critic_backend,
    )

    result = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
    )

    assert result.status == "partial"
    assert result.blocker_reasons == {
        DriverFamily.revenue: "primary_judgment_failed"
    }
    assert set(result.queue_item_ids) == set(DriverFamily) - {
        DriverFamily.revenue
    }
    assert conn.execute(
        "SELECT COUNT(*) FROM judgment_run_envelopes"
    ).fetchone()[0] == 7


def test_pipeline_persists_timeout_envelope_before_error_bubbles() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()
    revenue = bindings[DriverFamily.revenue]
    bindings[DriverFamily.revenue] = DriverFamilyExecutionBinding(
        primary_route=revenue.primary_route,
        primary_backend=_TimeoutRevenueBackend(),
        critic_route=revenue.critic_route,
        critic_backend=revenue.critic_backend,
    )

    with pytest.raises(TimeoutError, match="fixture provider timeout"):
        run_valuation_judgment_pipeline(
            snapshot=_snapshot(),
            bindings=bindings,
            conn=conn,
            transport_timeout_seconds=6.25,
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM judgment_run_envelopes"
    ).fetchone()[0] == 7


def test_pipeline_rejects_missing_family_bindings_before_any_write() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()
    del bindings[DriverFamily.revenue]

    with pytest.raises(ValueError, match="bindings must be complete"):
        run_valuation_judgment_pipeline(
            snapshot=_snapshot(),
            bindings=bindings,
            conn=conn,
        )

    assert conn.execute("SELECT COUNT(*) FROM analysis_snapshots").fetchone()[0] == 0


@pytest.mark.parametrize(
    "transport_timeout_seconds",
    [0.0, -1.0, float("inf"), float("nan")],
)
def test_pipeline_rejects_non_positive_or_non_finite_transport_timeout(
    transport_timeout_seconds: float,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()

    with pytest.raises(
        ValueError,
        match="transport_timeout_seconds must be finite and positive",
    ):
        run_valuation_judgment_pipeline(
            snapshot=_snapshot(),
            bindings=bindings,
            conn=conn,
            transport_timeout_seconds=transport_timeout_seconds,
        )

    assert all(
        backend.call_count == 0
        for binding in bindings.values()
        for backend in (binding.primary_backend, binding.critic_backend)
    )


def test_pipeline_persists_snapshot_but_calls_no_provider_when_context_is_pending() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    snapshot = _snapshot().model_copy(
        update={
            "upstream_context": {
                "business": {"status": "complete"},
                "industry": {},
            }
        }
    )

    result = run_valuation_judgment_pipeline(
        snapshot=snapshot,
        bindings=_bindings(),
        conn=conn,
    )

    assert result.status == "blocked"
    assert set(result.blocker_reasons) == set(DriverFamily)
    assert all(
        "snapshot.industry_context_missing" in reason
        for reason in result.blocker_reasons.values()
    )
    assert conn.execute("SELECT COUNT(*) FROM analysis_snapshots").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM judgment_run_envelopes"
    ).fetchone()[0] == 0


def test_pipeline_persists_critic_methodology_challenge_without_numeric_proxy() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _create_support_tables(conn)
    bindings = _bindings()
    family = DriverFamily.terminal_capital_comps
    binding = bindings[family]
    bindings[family] = DriverFamilyExecutionBinding(
        primary_route=binding.primary_route,
        primary_backend=binding.primary_backend,
        critic_route=binding.critic_route,
        critic_backend=_MethodologyChallengeBackend(),
    )

    result = run_valuation_judgment_pipeline(
        snapshot=_snapshot(),
        bindings=bindings,
        conn=conn,
    )

    assert result.status == "queued"
    request_ids = result.model_change_request_ids[family]
    assert len(request_ids) == 1
    row = conn.execute(
        """
        SELECT status, payload_json
        FROM valuation_model_change_requests
        WHERE request_id = ?
        """,
        (request_ids[0],),
    ).fetchone()
    assert row["status"] == "pending"
    assert "numeric_proxy" not in row["payload_json"]
    assert "issuer_specific_wacc_methodology" in row["payload_json"]
