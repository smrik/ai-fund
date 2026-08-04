from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from config import PEER_SIMILARITY_MODEL
from db.loader import (
    insert_evidence_packet,
    insert_treatment_decision,
    insert_valuation_policy_version,
    upsert_peer_similarity_cache,
)
from db.schema import create_tables
from src.contracts.assumption_registry import DriverFamily
from src.contracts.ticker_runs import (
    EligibilityStatus,
    ReplayInputFingerprints,
    SourceFingerprint,
    TerminalStatus,
    TickerIdentity,
    TickerRunContext,
)
from src.contracts.valuation_readiness import (
    LTMStatus,
    ReconciliationGateStatus,
    ValuationReadinessEvidence,
)
from src.stage_04_pipeline.ticker_terminal_store import (
    list_ticker_terminal_outcomes,
)
from src.stage_04_pipeline.ticker_valuation_execution import PreparedTickerRun
from src.stage_04_pipeline.valuation_workup_service import (
    PersistedValuationMaterials,
    load_persisted_valuation_materials,
    run_persisted_valuation_workups,
)


def _connection_factory(db_path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def _insert_live_observation_packet(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    profile_name: str,
    generated_at: str = "2026-07-25T10:00:00+00:00",
    model_name: str = "openrouter/provider-model",
    accepted_observation_count: object = 1,
    evidence_anchor_id: str | None = None,
) -> None:
    observation_id = f"observation:{profile_name}:1"
    insert_evidence_packet(
        conn,
        {
            "created_at": generated_at,
            "updated_at": generated_at,
            "ticker": ticker,
            "profile_name": profile_name,
            "packet_kind": profile_name,
            "bundle_id": None,
            "generated_at": generated_at,
            "source_refs": [
                {
                    "source_ref_id": f"source:{profile_name}:1",
                    "source_type": "sec_filing",
                    "source_name": "10-K",
                }
            ],
            "facts": [
                {
                    "fact_id": f"fact:{profile_name}:1",
                    "fact_name": "revenue",
                    "value": 100,
                }
            ],
            "snippets": [
                {
                    "snippet_id": f"snippet:{profile_name}:1",
                    "source_ref_id": f"source:{profile_name}:1",
                    "text": f"Grounded {profile_name} evidence.",
                }
            ],
            "observations": [
                {
                    "observation_id": observation_id,
                    "observation_kind": "qualitative",
                    "observation_type": "driver",
                    "claim": f"Grounded {profile_name} observation.",
                    "evidence_anchor_ids": [
                        evidence_anchor_id or f"fact:{profile_name}:1"
                    ],
                    "text_snippet_ids": [f"snippet:{profile_name}:1"],
                }
            ],
            "run_metadata": {
                "source_quality": "real",
                "handoff_run_status": "completed_with_items",
                "agent_observation_artifact": {
                    "model_used": model_name,
                    "structured_model_used": model_name,
                    "accepted_observation_count": accepted_observation_count,
                    "accepted_observation_ids": [observation_id],
                },
            },
        },
    )


def _provisional_prepared(ticker: str) -> PreparedTickerRun:
    readiness = ValuationReadinessEvidence(
        statement_reconciliation=ReconciliationGateStatus.reconciled,
        source_reconciliation=ReconciliationGateStatus.reconciled,
        claim_ledger_reconciliation=ReconciliationGateStatus.reconciled,
        operating_reconciliation=ReconciliationGateStatus.reconciled,
        annual_period_count=5,
        ltm_status=LTMStatus.compatible,
        approved_family_hashes={},
        statement_reconciliation_hash="statement",
        source_reconciliation_hash="source",
        claim_ledger_hash="claim",
        operating_reconciliation_hash="operating",
        peer_set_fingerprint="peers",
        treatment_set_fingerprint="treatments",
        prompt_contract_fingerprint="prompt",
        dcf_engine_fingerprint="dcf",
        comps_engine_fingerprint="comps",
        bridge_engine_fingerprint="bridge",
    )
    context = TickerRunContext(
        identity=TickerIdentity(ticker=ticker),
        analysis_as_of=date(2026, 7, 26),
        eligibility=EligibilityStatus.supported_v1,
        valuation_model="industrial_fcff_dcf_comps_v1",
        replay_inputs=ReplayInputFingerprints(
            analysis_snapshot_hash=f"snapshot:{ticker}",
            approved_case_replay_fingerprint="approval:pending",
            peer_universe_fingerprint="peers",
            treatment_register_fingerprint="treatments",
            judgment_contract_fingerprint="prompt",
            valuation_engine_fingerprint="engines",
        ),
        readiness=readiness,
        source_fingerprints=(
            SourceFingerprint(
                source_id=f"source:{ticker}",
                fingerprint=f"fingerprint:{ticker}",
            ),
        ),
    )
    return PreparedTickerRun(
        context=context,
        snapshot=SimpleNamespace(snapshot_hash=f"snapshot:{ticker}"),
    )


def test_preparation_exceptions_are_isolated_and_every_name_is_checkpointed(
    tmp_path: Path,
) -> None:
    connect = _connection_factory(tmp_path / "valuation-workups.sqlite")
    with connect() as conn:
        create_tables(conn)

    requests = (
        TickerIdentity(
            ticker="FAIL",
            exchange="NASDAQ",
            share_class="A",
            cik="1234",
        ),
        TickerIdentity(ticker="SAFE", exchange="NYSE"),
        TickerIdentity(ticker="MATERIAL", exchange="NYSE"),
        TickerIdentity(ticker="CROSS", exchange="NYSE"),
    )

    def prepare_run(conn, ticker, **kwargs) -> PreparedTickerRun | None:
        if ticker == "SAFE":
            return None
        if ticker == "CROSS":
            return _provisional_prepared("OTHER")
        raise RuntimeError(f"cannot prepare {ticker}")

    def material_loader(conn, identity, **kwargs):
        if identity.ticker == "MATERIAL":
            return None
        return PersistedValuationMaterials()

    manifest = run_persisted_valuation_workups(
        requests,
        execution_run_id="execution:no-drop",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T12:00:00+00:00",
        bindings={},
        connection_factory=connect,
        material_loader=material_loader,
        prepare_run=prepare_run,
        max_workers=2,
    )

    assert manifest.requested_count == 4
    assert manifest.unique_count == 4
    assert {record.context.identity for record in manifest.records} == set(requests)
    assert all(record.status == TerminalStatus.blocked for record in manifest.records)
    details = {
        record.context.identity.ticker: record.reason_detail or ""
        for record in manifest.records
    }
    assert "preparation.exception.RuntimeError" in details["FAIL"]
    assert "preparation.prepare_result_invalid" in details["SAFE"]
    assert "preparation.material_loader_invalid" in details["MATERIAL"]
    assert "preparation.prepare_identity_mismatch" in details["CROSS"]

    with connect() as conn:
        persisted = list_ticker_terminal_outcomes(
            conn,
            execution_run_id="execution:no-drop",
        )
    assert len(persisted) == 4
    assert {outcome.record.context.identity for outcome in persisted} == set(requests)


def test_material_loader_builds_one_as_of_bundle_from_persisted_sources(
    tmp_path: Path,
) -> None:
    connect = _connection_factory(tmp_path / "materials.sqlite")
    with connect() as conn:
        create_tables(conn)
        _insert_live_observation_packet(
            conn,
            ticker="MSFT",
            profile_name="company_analysis",
        )
        _insert_live_observation_packet(
            conn,
            ticker="MSFT",
            profile_name="industry_analysis",
        )
        insert_valuation_policy_version(
            conn,
            {
                "created_at": "2026-07-24T09:00:00+00:00",
                "actor": "pm",
                "global_defaults_json": json.dumps(
                    {
                        "risk_free_rate": 0.04,
                        "equity_risk_premium": 0.05,
                    }
                ),
                "sector_defaults_json": json.dumps(
                    {"Technology": {"terminal_growth": 0.025}}
                ),
                "source_ref": "pm:policy:1",
                "notes": "approved",
            },
        )
        insert_treatment_decision(
            conn,
            {
                "ticker": "MSFT",
                "topic": "restructuring",
                "focus_key": "operating_margin",
                "treatment": "normalize",
                "valuation_treatment": "exclude one-time cost",
                "driver_field": "ebit_margin_start",
                "model_change_request": None,
                "evidence_anchor_ids": ["fact:company_analysis:1"],
                "rationale": "Non-recurring charge.",
                "decided_at": "2026-07-25T11:00:00+00:00",
                "approved_by": "pm",
                "evidence_corpus_hash": "corpus:1",
            },
        )
        insert_treatment_decision(
            conn,
            {
                "ticker": "MSFT",
                "topic": "restructuring",
                "focus_key": "operating_margin",
                "treatment": "retain",
                "valuation_treatment": "include recurring cost",
                "driver_field": "ebit_margin_start",
                "model_change_request": None,
                "evidence_anchor_ids": ["fact:company_analysis:1"],
                "rationale": "Later PM decision.",
                "decided_at": "2026-07-27T11:00:00+00:00",
                "approved_by": "pm",
                "evidence_corpus_hash": "corpus:2",
            },
        )
        upsert_peer_similarity_cache(
            conn,
            {
                "target_ticker": "MSFT",
                "peer_ticker": "ORCL",
                "text_hash_target": "target-text",
                "text_hash_peer": "peer-text",
                "embedding_model": PEER_SIMILARITY_MODEL,
                "similarity_score": 0.84,
                "computed_at": "2026-07-25T08:00:00+00:00",
            },
        )

        materials = load_persisted_valuation_materials(
            conn,
            TickerIdentity(
                ticker="MSFT",
                exchange="NASDAQ",
                cik="789019",
            ),
            analysis_as_of=date(2026, 7, 26),
            comps_loader=lambda ticker, as_of_date: {
                "target": {
                    "ticker": ticker,
                    "as_of_date": as_of_date,
                },
                "peers": [
                    {
                        "ticker": "ORCL",
                        "as_of_date": as_of_date,
                    }
                ],
                "medians": {"tev_ebitda_ltm": 20.0},
                "source_lineage": {
                    "as_of_date": as_of_date,
                    "run_id": "ciq:run:1",
                    "source_file": "ciq.xlsx",
                },
            },
        )

    assert materials.blocker_reason_codes == ()
    assert set(materials.upstream_context) == {"business", "industry"}
    assert (
        materials.upstream_context["business"]["profile_name"]
        == "company_analysis"
    )
    assert {
        "source:company_analysis:1",
        "fact:company_analysis:1",
        "snippet:company_analysis:1",
        "observation:company_analysis:1",
        "source:industry_analysis:1",
        "fact:industry_analysis:1",
        "snippet:industry_analysis:1",
        "observation:industry_analysis:1",
    }.issubset(materials.evidence)
    assert materials.comps_inputs["similarity_scores"] == {"ORCL": 0.84}
    assert materials.valuation_policy["policy_id"] == 1
    assert materials.valuation_policy["actor"] == "pm"
    assert len(materials.approved_treatments) == 1
    assert materials.approved_treatments[0]["topic"] == "restructuring"
    assert materials.approved_treatments[0]["treatment"] == "normalize"
    assert materials.approved_treatments[0]["active"] is True
    assert materials.approved_treatments[0]["superseded_by"] is None


def test_material_loader_blocks_stale_heuristic_and_missing_components(
    tmp_path: Path,
) -> None:
    connect = _connection_factory(tmp_path / "blocked-materials.sqlite")
    with connect() as conn:
        create_tables(conn)
        _insert_live_observation_packet(
            conn,
            ticker="MSFT",
            profile_name="company_analysis",
            generated_at="2026-06-01T10:00:00+00:00",
        )
        _insert_live_observation_packet(
            conn,
            ticker="MSFT",
            profile_name="industry_analysis",
            generated_at="2026-06-01T10:00:00+00:00",
        )
        _insert_live_observation_packet(
            conn,
            ticker="MSFT",
            profile_name="industry_analysis",
            generated_at="2026-07-25T10:00:00+00:00",
            model_name="local_heuristic_v1",
            accepted_observation_count="invalid",
            evidence_anchor_id="fact:not-in-packet",
        )
        insert_valuation_policy_version(
            conn,
            {
                "created_at": "2026-07-24T09:00:00+00:00",
                "actor": "pm",
                "global_defaults_json": "{}",
                "sector_defaults_json": "{}",
                "source_ref": "pm:invalid-policy",
                "notes": None,
            },
        )

        materials = load_persisted_valuation_materials(
            conn,
            TickerIdentity(ticker="MSFT"),
            analysis_as_of=date(2026, 7, 26),
            comps_loader=lambda ticker, as_of_date: {
                "target": {"ticker": ticker},
                "peers": [{"ticker": "ORCL"}],
                "source_lineage": {
                    "as_of_date": as_of_date,
                    "run_id": "ciq:run:1",
                    "source_file": "ciq.xlsx",
                },
            },
            freshness_policy=lambda packet, cutoff: (
                packet["profile_name"] != "company_analysis"
            ),
        )

    assert set(materials.blocker_reason_codes) >= {
        "materials.company_analysis.stale",
        "materials.industry_analysis.heuristic_observations",
        "materials.industry_analysis.evidence_anchors_invalid",
        "materials.comps.similarity_scores_missing",
        "materials.valuation_policy.invalid",
    }
    assert materials.upstream_context == {}
    assert materials.comps_inputs == {}
    assert materials.valuation_policy == {}


def test_source_blocked_name_is_checkpointed_without_requiring_a_provider(
    tmp_path: Path,
) -> None:
    connect = _connection_factory(tmp_path / "source-blocked.sqlite")
    with connect() as conn:
        create_tables(conn)
    provider_calls: list[dict] = []
    lane_calls: list[str] = []
    rate_limit_calls: list[str] = []

    def provider_lane(context: TickerRunContext) -> str:
        lane_calls.append(context.identity.ticker)
        raise AssertionError("source-blocked names do not need provider routing")

    manifest = run_persisted_valuation_workups(
        ["MISS"],
        execution_run_id="execution:source-blocked",
        analysis_as_of=date(2026, 7, 26),
        captured_at="2026-07-26T12:00:00+00:00",
        bindings={},
        connection_factory=connect,
        material_loader=lambda *args, **kwargs: PersistedValuationMaterials(
            blocker_reason_codes=("materials.company_analysis.missing",),
        ),
        judgment_runner=lambda **kwargs: provider_calls.append(kwargs),
        provider_lane=provider_lane,
        rate_limiter=lambda lane, context: rate_limit_calls.append(lane),
    )

    assert provider_calls == []
    assert lane_calls == []
    assert rate_limit_calls == []
    assert manifest.executed_count == 1
    assert manifest.records[0].status == TerminalStatus.blocked
    assert "materials.company_analysis.missing" in (
        manifest.records[0].reason_detail or ""
    )
    with connect() as conn:
        persisted = list_ticker_terminal_outcomes(
            conn,
            execution_run_id="execution:source-blocked",
        )
    assert len(persisted) == 1


def test_second_identical_execution_resumes_the_checkpointed_first_pass(
    tmp_path: Path,
) -> None:
    connect = _connection_factory(tmp_path / "resume.sqlite")
    with connect() as conn:
        create_tables(conn)
    provider_calls: list[float] = []

    def prepare_run(conn, ticker, **kwargs) -> PreparedTickerRun:
        return _provisional_prepared(ticker)

    def queued_judgment(**kwargs):
        provider_calls.append(kwargs["transport_timeout_seconds"])
        return SimpleNamespace(
            status="queued",
            snapshot_hash=kwargs["snapshot"].snapshot_hash,
            queue_item_ids={
                family: index
                for index, family in enumerate(DriverFamily, start=1)
            },
            blocker_reasons={},
            model_change_request_ids={},
        )

    run_options = {
        "requests": [
            TickerIdentity(
                ticker="MSFT",
                exchange="NASDAQ",
                cik="789019",
            )
        ],
        "execution_run_id": "execution:resume",
        "analysis_as_of": date(2026, 7, 26),
        "captured_at": "2026-07-26T12:00:00+00:00",
        "bindings": {},
        "connection_factory": connect,
        "material_loader": lambda *args, **kwargs: (
            PersistedValuationMaterials()
        ),
        "prepare_run": prepare_run,
        "judgment_runner": queued_judgment,
        "transport_timeout_seconds": 7.0,
        "batch_timeout_seconds": 30.0,
    }

    first = run_persisted_valuation_workups(**run_options)
    second = run_persisted_valuation_workups(**run_options)

    assert first.executed_count == 1
    assert first.records[0].status == TerminalStatus.provisional
    assert second.executed_count == 0
    assert second.resumed_count == 1
    assert second.records == first.records
    assert provider_calls == [7.0]
    with connect() as conn:
        persisted = list_ticker_terminal_outcomes(
            conn,
            execution_run_id="execution:resume",
        )
    assert len(persisted) == 1
