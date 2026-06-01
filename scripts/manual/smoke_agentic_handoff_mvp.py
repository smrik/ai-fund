from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _project_imports() -> tuple[Any, Any]:
    import config
    import config.settings as config_settings

    return config, config_settings


def _copy_sqlite_snapshot(source_db: Path, target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source_db))
    try:
        target_conn = sqlite3.connect(str(target_db))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


@contextmanager
def isolated_db_snapshot() -> Any:
    config, config_settings = _project_imports()
    live_db = Path(config.DB_PATH)
    if not live_db.exists():
        raise FileNotFoundError(f"Live database not found: {live_db}")

    original_db_path = Path(config.DB_PATH)
    temp_dir = Path(tempfile.mkdtemp(prefix="agentic-handoff-mvp-"))
    temp_db_path = temp_dir / "alpha_pod_smoke.db"
    _copy_sqlite_snapshot(original_db_path, temp_db_path)

    patched_modules: list[tuple[Any, str, Any]] = []
    for module_name in list(sys.modules):
        module = sys.modules.get(module_name)
        if module is None or not hasattr(module, "DB_PATH"):
            continue
        current_value = getattr(module, "DB_PATH")
        if Path(str(current_value)) != original_db_path:
            continue
        patched_modules.append((module, "DB_PATH", current_value))
        setattr(module, "DB_PATH", temp_db_path)

    patched_modules.append((config, "DB_PATH", config.DB_PATH))
    config.DB_PATH = temp_db_path
    patched_modules.append((config_settings, "DB_PATH", config_settings.DB_PATH))
    config_settings.DB_PATH = temp_db_path

    try:
        yield temp_db_path
    finally:
        for module, attr_name, original_value in reversed(patched_modules):
            setattr(module, attr_name, original_value)


def _build_stub_observations(packet: Any, profile_name: str) -> list[Any]:
    from src.contracts.evidence_packet import (
        EvidenceConfidence,
        EvidenceImportance,
        EvidencePacketObservation,
        EvidencePacketObservationKind,
    )

    source_quality = str((packet.run_metadata or {}).get("source_quality") or "").strip().lower()
    if source_quality != "real":
        return []

    observation_type_by_profile = {
        "comps_analysis": "multiple_premium_supported",
        "earnings_update": "pricing_pressure_improved",
        "company_analysis": "pricing_pressure_improved",
        "industry_analysis": "demand_strength_broad",
        "risk_review": "execution_risk_increased",
        "valuation_review": "wacc_method_disagreement",
    }
    observation_type = observation_type_by_profile.get(profile_name)
    if observation_type is None:
        return []

    anchor_ids: list[str] = []
    snippet_ids: list[str] = []
    if packet.facts:
        anchor_ids.append(packet.facts[0].fact_id)
    if packet.snippets:
        snippet_ids.append(packet.snippets[0].snippet_id)
        anchor_ids.append(packet.snippets[0].snippet_id)
    if not anchor_ids and packet.source_refs:
        anchor_ids.append(packet.source_refs[0].source_ref_id)
    if not anchor_ids:
        return []

    observation_kind = (
        EvidencePacketObservationKind.qualitative
        if snippet_ids
        else EvidencePacketObservationKind.numeric
    )
    claim = {
        "earnings_update": "Stub smoke check: pricing pressure looks modestly better than baseline.",
        "company_analysis": "Stub smoke check: filing evidence supports a modest operating improvement.",
        "comps_analysis": "Stub smoke check: peer multiples support PM review of the exit multiple.",
        "industry_analysis": "Stub smoke check: industry demand appears firmer than the embedded base case.",
        "risk_review": "Stub smoke check: execution risk should stay on the PM review queue.",
        "valuation_review": "Stub smoke check: valuation method choice deserves PM attention before override approval.",
    }[profile_name]
    return [
        EvidencePacketObservation(
            observation_id=f"smoke:{profile_name}:1",
            observation_kind=observation_kind,
            observation_type=observation_type,
            claim=claim,
            evidence_anchor_ids=anchor_ids,
            text_snippet_ids=snippet_ids,
            qualitative_importance=EvidenceImportance.high,
            agent_confidence=EvidenceConfidence.high,
            metadata={},
        )
    ]


@contextmanager
def stub_agent_runs(enabled: bool) -> Any:
    if not enabled:
        yield
        return

    from src.stage_03_judgment.grounded_observation_agent import GroundedObservationAgent
    from src.stage_03_judgment.earnings_agent import EarningsAgent
    from src.stage_03_judgment.comps_agent import CompsAgent
    from src.stage_03_judgment.filings_agent import FilingsAgent
    from src.stage_03_judgment.industry_agent import IndustryAgent
    from src.stage_03_judgment.risk_agent import RiskAgent
    from src.stage_03_judgment.valuation_agent import ValuationAgent

    original_methods = {
        GroundedObservationAgent: GroundedObservationAgent.analyze_evidence_packet,
        CompsAgent: CompsAgent.analyze_evidence_packet,
        EarningsAgent: EarningsAgent.analyze_evidence_packet,
        FilingsAgent: FilingsAgent.analyze_evidence_packet,
        IndustryAgent: IndustryAgent.analyze_evidence_packet,
        RiskAgent: RiskAgent.analyze_evidence_packet,
        ValuationAgent: ValuationAgent.analyze_evidence_packet,
    }

    def _stub(self: Any, packet: Any, profile_name: str) -> list[Any]:
        return _build_stub_observations(packet, profile_name)

    try:
        for cls in original_methods:
            cls.analyze_evidence_packet = _stub  # type: ignore[method-assign]
        yield
    finally:
        for cls, original_method in original_methods.items():
            cls.analyze_evidence_packet = original_method  # type: ignore[method-assign]


@contextmanager
def stub_external_evidence_collectors(enabled: bool) -> Any:
    if not enabled:
        yield
        return

    import src.stage_04_pipeline.evidence_packets as evidence_packets
    import src.stage_02_valuation.input_assembler as input_assembler
    import src.stage_04_pipeline.pending_assumption_changes as pending_assumption_changes
    from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
    from src.stage_02_valuation.valuation_types import ForecastDrivers

    originals = {
        "get_agent_filing_context": evidence_packets.get_agent_filing_context,
        "get_sec_filing_metrics": evidence_packets.get_sec_filing_metrics,
        "get_8k_texts": evidence_packets.get_8k_texts,
        "get_market_data": evidence_packets.get_market_data,
        "build_valuation_inputs": evidence_packets.build_valuation_inputs,
        "build_comps_dashboard_view": evidence_packets.build_comps_dashboard_view,
        "default_scenario_specs": evidence_packets.default_scenario_specs,
        "run_dcf_professional": evidence_packets.run_dcf_professional,
        "input_assembler.build_valuation_inputs": input_assembler.build_valuation_inputs,
        "pending_assumption_changes.default_scenario_specs": pending_assumption_changes.default_scenario_specs,
        "pending_assumption_changes.run_dcf_professional": pending_assumption_changes.run_dcf_professional,
    }

    def _valuation_inputs_fixture(ticker: str) -> Any:
        drivers = ForecastDrivers(
            revenue_base=10_000.0,
            revenue_growth_near=0.07,
            revenue_growth_mid=0.05,
            revenue_growth_terminal=0.025,
            ebit_margin_start=0.16,
            ebit_margin_target=0.18,
            tax_rate_start=0.21,
            tax_rate_target=0.21,
            capex_pct_start=0.04,
            capex_pct_target=0.04,
            da_pct_start=0.03,
            da_pct_target=0.03,
            dso_start=45.0,
            dso_target=45.0,
            dio_start=35.0,
            dio_target=35.0,
            dpo_start=40.0,
            dpo_target=40.0,
            wacc=0.09,
            exit_multiple=12.0,
            exit_metric="ev_ebitda",
            net_debt=1_200.0,
            shares_outstanding=900.0,
            ronic_terminal=0.12,
        )
        return ValuationInputsWithLineage(
            ticker=ticker.upper(),
            company_name=f"{ticker.upper()} Smoke Fixture",
            sector="Technology",
            industry="Software",
            current_price=125.0,
            as_of_date="2026-05-15",
            model_applicability_status="supported",
            drivers=drivers,
            source_lineage={
                "revenue_growth_near": "smoke_fixture",
                "revenue_growth_mid": "smoke_fixture",
                "ebit_margin_start": "smoke_fixture",
                "ebit_margin_target": "smoke_fixture",
                "wacc": "smoke_fixture",
                "terminal_growth": "smoke_fixture",
                "ronic_terminal": "smoke_fixture",
            },
            ciq_lineage={},
            wacc_inputs={},
        )

    try:
        evidence_packets.get_agent_filing_context = lambda ticker, **kwargs: SimpleNamespace(
            sources=[
                {
                    "accession_no": "0001",
                    "form_type": "10-K",
                    "doc_name": f"{ticker.lower()}-10k.htm",
                    "filing_date": "2026-02-01",
                }
            ],
            selected_chunks=[
                SimpleNamespace(
                    accession_no="0001",
                    chunk_index=0,
                    text="Revenue growth remained resilient while financing costs eased.",
                    section_key="mda",
                    filing_date="2026-02-01",
                    score=0.91,
                )
            ],
            retrieval_summary={"selected_chunk_count": 1},
        )
        evidence_packets.get_sec_filing_metrics = lambda ticker: SimpleNamespace(
            source_form="10-K",
            source_filing_date="2026-02-01",
            metric_source="smoke_fixture",
            revenue_cagr_3y=0.08,
            ebit_margin_avg_3y=0.19,
            gross_margin_avg_3y=0.52,
            net_debt_to_ebitda=1.6,
            fcf_yield=0.04,
        )
        evidence_packets.get_8k_texts = lambda ticker, limit=3, max_chars_each=4_000: [
            {
                "accession_no": "8k-1",
                "filing_date": "2026-05-01",
                "text": "Management raised guidance and described improving demand trends.",
            }
        ]
        evidence_packets.get_market_data = lambda ticker, use_cache=True: {
            "current_price": 125.0,
            "analyst_target_mean": 140.0,
            "analyst_recommendation": "buy",
            "number_of_analysts": 18,
            "beta": 1.1,
            "short_ratio": 2.0,
        }
        evidence_packets.build_valuation_inputs = _valuation_inputs_fixture
        evidence_packets.build_comps_dashboard_view = lambda ticker: {
            "available": True,
            "peer_counts": {"raw": 8, "clean": 6},
            "primary_metric": "tev_ebitda_ltm",
            "target_vs_peers": {"peer_medians": {"tev_ebitda_ltm": 11.5, "pe_ltm": 18.2}},
            "source_lineage": {"source": "smoke_fixture"},
        }
        evidence_packets.default_scenario_specs = lambda: [SimpleNamespace(name="base"), SimpleNamespace(name="bull")]
        evidence_packets.run_dcf_professional = lambda drivers, spec: SimpleNamespace(
            intrinsic_value_per_share=150.0 if spec.name == "base" else 180.0
        )
        input_assembler.build_valuation_inputs = _valuation_inputs_fixture
        pending_assumption_changes.default_scenario_specs = lambda: [SimpleNamespace(name="base"), SimpleNamespace(name="bull")]
        pending_assumption_changes.run_dcf_professional = lambda drivers, spec: SimpleNamespace(
            intrinsic_value_per_share=150.0 if spec.name == "base" else 180.0
        )
        yield
    finally:
        for name, original in originals.items():
            if name.startswith("input_assembler."):
                setattr(input_assembler, name.split(".", 1)[1], original)
            elif name.startswith("pending_assumption_changes."):
                setattr(pending_assumption_changes, name.split(".", 1)[1], original)
            else:
                setattr(evidence_packets, name, original)


def _proposal_targets_from_preview(preview_payload: dict[str, Any]) -> dict[str, float]:
    preview = preview_payload.get("preview") or {}
    if hasattr(preview, "model_dump"):
        preview = preview.model_dump()
    resolved_values = preview.get("resolved_values") or {}
    resolved_map: dict[str, float] = {}
    for assumption_name, value_payload in resolved_values.items():
        if not isinstance(value_payload, dict):
            continue
        proposed_value = value_payload.get("proposed_value")
        if proposed_value is None:
            proposed_value = value_payload.get("value")
        if proposed_value is None:
            continue
        resolved_map[str(assumption_name)] = round(float(proposed_value), 12)
    return resolved_map


def _proposal_targets_from_approved(item_payload: dict[str, Any]) -> dict[str, float]:
    approved_pack = (item_payload.get("item") or {}).get("approved_proposal_pack") or {}
    resolved_map: dict[str, float] = {}
    for proposal in approved_pack.get("proposals") or []:
        assumption_name = proposal.get("assumption_name")
        target_value = proposal.get("proposed_target_value")
        if not assumption_name or target_value is None:
            continue
        resolved_map[str(assumption_name)] = round(float(target_value), 12)
    return resolved_map


def run_smoke_check(ticker: str, *, live_agents: bool) -> int:
    from api.main import (
        approve_pm_decision_queue_payload,
        apply_pm_decision_queue_payload,
        list_evidence_packets_payload,
        list_pm_decision_queue_payload,
        preview_pm_decision_queue_payload,
        run_agentic_handoff_profile_payload,
    )
    from src.stage_04_pipeline.agentic_handoff_profiles import list_agentic_handoff_profiles

    ticker = ticker.upper().strip()
    runnable_profiles = [profile for profile in list_agentic_handoff_profiles() if profile.runnable]
    unsupported_profiles = [profile for profile in list_agentic_handoff_profiles() if not profile.runnable]

    initial_packets = list_evidence_packets_payload(ticker)["evidence_packets"]
    initial_packet_ids = {int(packet["packet_id"]) for packet in initial_packets if packet.get("packet_id") is not None}
    initial_queue = list_pm_decision_queue_payload(ticker, status=None)["items"]
    initial_queue_item_ids = {int(item["item_id"]) for item in initial_queue if item.get("item_id") is not None}

    run_results: list[dict[str, Any]] = []
    for profile in runnable_profiles:
        run_results.append(run_agentic_handoff_profile_payload(ticker, profile.profile_name))

    packet_payload = list_evidence_packets_payload(ticker)["evidence_packets"]
    new_packets = [packet for packet in packet_payload if packet.get("packet_id") is not None and int(packet["packet_id"]) not in initial_packet_ids]
    packet_by_id = {str(packet["packet_id"]): packet for packet in packet_payload if packet.get("packet_id") is not None}

    queue_payload = list_pm_decision_queue_payload(ticker, status=None)["items"]
    new_queue_items = [item for item in queue_payload if item.get("item_id") is not None and int(item["item_id"]) not in initial_queue_item_ids]

    failures: list[str] = []
    notes: list[str] = []
    approval_checks: list[dict[str, Any]] = []

    for profile in unsupported_profiles:
        notes.append(f"unsupported profile: {profile.profile_name} ({profile.not_runnable_reason})")

    for result in run_results:
        status = str(result.get("status") or "unknown")
        if status in {"blocked", "not_runnable", "failed"}:
            notes.append(f"{result['profile_name']}: {status} ({result.get('reason') or 'no reason'})")

    for item in new_queue_items:
        linked_packets = [packet_by_id.get(str(packet_id)) for packet_id in item.get("evidence_packet_ids") or []]
        qualities = {
            str(((packet or {}).get("run_metadata") or {}).get("source_quality") or "").strip().lower()
            for packet in linked_packets
            if packet is not None
        }
        if "placeholder" in qualities:
            failures.append(
                f"queue item {item['item_id']} was created from placeholder evidence packet(s): {sorted(qualities)}"
            )

    for item in new_queue_items:
        if item.get("item_type") != "assumption_change_pack":
            continue
        item_id = int(item["item_id"])
        preview_payload = preview_pm_decision_queue_payload(ticker, item_id)
        approved_payload = approve_pm_decision_queue_payload(ticker, item_id, actor="smoke_script")
        applied_payload = apply_pm_decision_queue_payload(ticker, item_id, actor="smoke_script")
        preview_targets = _proposal_targets_from_preview(preview_payload)
        approved_targets = _proposal_targets_from_approved(approved_payload)
        skipped_fields = preview_payload.get("skipped_fields") or []
        approval_checks.append(
            {
                "item_id": item_id,
                "preview_targets": preview_targets,
                "approved_targets": approved_targets,
                "applied_change_ids": (applied_payload.get("item") or {}).get("adapter_links", {}).get("applied_assumption_change_ids") or [],
                "skipped_fields": skipped_fields,
            }
        )
        if preview_targets != approved_targets:
            failures.append(
                f"queue item {item_id} preview targets {preview_targets} did not match approved targets {approved_targets}"
            )
        if not approval_checks[-1]["applied_change_ids"]:
            failures.append(f"queue item {item_id} did not apply an approved deterministic change")
        if skipped_fields:
            notes.append(f"queue item {item_id}: skipped_fields={','.join(str(value) for value in skipped_fields)}")

    observation_count = sum(len(packet.get("observations") or []) for packet in new_packets)
    queue_item_count = len(new_queue_items)

    mode_label = "live" if live_agents else "stubbed-local"
    print(f"Agentic Handoff MVP smoke check ({mode_label}) for {ticker}")
    print(f"New packets: {len(new_packets)}")
    print(f"New observations: {observation_count}")
    print(f"New queue items: {queue_item_count}")

    for result in run_results:
        print(
            f"- {result['profile_name']}: status={result.get('status')} observations={result.get('observation_count', 0)} queue_items={result.get('queue_item_count', 0)}"
        )

    if approval_checks:
        print("Approval checks:")
        for check in approval_checks:
            print(
                f"- item {check['item_id']}: preview_targets={check['preview_targets']} approved_targets={check['approved_targets']} skipped_fields={check['skipped_fields']}"
            )
    else:
        print("Approval checks: no assumption_change_pack items were created in this run.")

    if notes:
        print("Notes:")
        for note in notes:
            print(f"- {note}")

    if failures:
        print("Result: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Result: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-check the agentic handoff MVP on an isolated DB snapshot.")
    parser.add_argument("--ticker", required=True, help="Ticker to exercise, for example IBM.")
    parser.add_argument(
        "--live-agents",
        action="store_true",
        help="Use live agents instead of local stub observations. This may require API credentials and network access.",
    )
    args = parser.parse_args()

    with isolated_db_snapshot():
        with stub_external_evidence_collectors(enabled=not args.live_agents):
            with stub_agent_runs(enabled=not args.live_agents):
                return run_smoke_check(args.ticker, live_agents=args.live_agents)


if __name__ == "__main__":
    raise SystemExit(main())
