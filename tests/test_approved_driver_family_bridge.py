import sqlite3

from db.loader import insert_pm_decision_queue_item
from db.schema import create_tables
from src.contracts.assumption_registry import judgment_owned_fields
from src.contracts.pm_decision_queue import AssumptionChangePack
from src.contracts.valuation_readiness import (
    JudgmentDriverSourceStrength,
    assess_judgment_driver_provenance,
)
from src.stage_02_valuation.batch_runner import (
    _run_probabilistic_valuation_with_scenario_drivers,
)
from src.stage_02_valuation.professional_dcf import (
    default_scenario_specs,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.approved_driver_family_bridge import (
    resolve_approved_driver_family_packs,
)


def _drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=1_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.20,
        ebit_margin_target=0.328,
        tax_rate_start=0.21,
        tax_rate_target=0.21,
        capex_pct_start=0.05,
        capex_pct_target=0.05,
        da_pct_start=0.03,
        da_pct_target=0.03,
        dso_start=45.0,
        dso_target=45.0,
        dio_start=40.0,
        dio_target=40.0,
        dpo_start=35.0,
        dpo_target=35.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=100.0,
        shares_outstanding=100.0,
        ronic_terminal=0.12,
        cogs_pct_of_revenue=0.60,
    )


def _pack(*, pack_id: str, ebit: tuple[float, float, float]) -> AssumptionChangePack:
    values = {
        "ebit_margin_target": ebit,
        "tax_rate_target": (0.21, 0.185, 0.16),
        "cogs_pct_of_revenue": (0.33, 0.312, 0.295),
    }
    return AssumptionChangePack.model_validate(
        {
            "pack_id": pack_id,
            "proposal_scope": "low_base_high",
            "family": "profitability_tax",
            "analysis_snapshot_hash": "snapshot-1",
            "primary_run_id": "primary-1",
            "critic_run_id": "critic-1",
            "critic_verdict": "accept",
            "notes": {
                "family_rationale": "Fixture profitability and tax cases.",
                "assumption_notes": {
                    name: {
                        "scenario_conditions": {
                            "low": "Low case.",
                            "base": "Base case.",
                            "high": "High case.",
                        },
                        "what_would_change_view": "New evidence.",
                    }
                    for name in values
                },
            },
            "proposals": [
                {
                    "assumption_name": name,
                    "proposal_mode": "scenarios",
                    "scenario_values": {
                        "low": scenario[0],
                        "base": scenario[1],
                        "high": scenario[2],
                    },
                    "unit": "decimal",
                    "horizon_years": 10,
                    "evidence_anchor_ids": [f"fact:{name}"],
                    "rationale": "Fixture approval.",
                }
                for name, scenario in values.items()
            ],
        }
    )


def _insert_queue_item(
    conn: sqlite3.Connection,
    *,
    pack: AssumptionChangePack,
    status: str,
    fingerprint: str,
    approved: bool,
) -> int:
    payload = pack.model_dump(mode="json")
    return insert_pm_decision_queue_item(
        conn,
        {
            "dedupe_key": f"fixture:{pack.pack_id}:{status}",
            "created_at": "2026-08-03T10:00:00Z",
            "updated_at": "2026-08-03T10:00:00Z",
            "ticker": "TEST",
            "profile_name": "driver_family_profitability_tax",
            "item_type": "assumption_change_pack",
            "status": status,
            "qualitative_importance": "high",
            "valuation_impact_bucket": "high",
            "title": "Fixture driver-family approval",
            "summary": "Fixture approval for bridge tests.",
            "evidence_anchor_ids": ["fact:ebit_margin_target"],
            "evidence_packet_ids": [],
            "proposal_pack": payload,
            "approved_proposal_pack": payload if approved else None,
            "agent_confidence": 1.0,
            "translator_confidence": 1.0,
            "pm_confidence": 1.0,
            "valuation_impact": {},
            "adapter_links": {"approval_fingerprint": fingerprint},
            "decision_history": [],
            "metadata": {},
        },
    )


def test_approved_pack_reaches_dcf_drivers_and_lineage() -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    pack = _pack(pack_id="pack:approved", ebit=(0.38, 0.44, 0.47))
    item_id = _insert_queue_item(
        conn,
        pack=pack,
        status="approved",
        fingerprint="approval-fingerprint-1",
        approved=True,
    )

    base = _drivers()
    resolution = resolve_approved_driver_family_packs(
        conn,
        "TEST",
        base,
        {"ebit_margin_target": "default", "tax_rate_target": "default"},
    )

    assert resolution.base_drivers.ebit_margin_target == 0.44
    assert resolution.base_drivers.tax_rate_target == 0.185
    assert resolution.base_drivers.cogs_pct_of_revenue == 0.312
    assert resolution.dcf_scenario_drivers["bear"].ebit_margin_target == 0.38
    assert resolution.dcf_scenario_drivers["base"].ebit_margin_target == 0.44
    assert resolution.dcf_scenario_drivers["bull"].ebit_margin_target == 0.47

    lineage = resolution.source_lineage
    assert "approved" in lineage["ebit_margin_target"]
    assert str(item_id) in lineage["ebit_margin_target"]
    assert "approval-fingerprint-1" in lineage["ebit_margin_target"]
    assert "default" not in lineage["ebit_margin_target"]
    assert "ciq" not in lineage["ebit_margin_target"]

    scenario_specs = default_scenario_specs()
    before = _run_probabilistic_valuation_with_scenario_drivers(
        {spec.name: base for spec in scenario_specs},
        scenario_specs,
    )
    after = _run_probabilistic_valuation_with_scenario_drivers(
        resolution.dcf_scenario_drivers,
        scenario_specs,
    )
    assert set(after.scenario_results) == {"bear", "base", "bull"}
    assert after.scenario_results["bear"].scenario == "bear"
    assert after.scenario_results["base"].scenario == "base"
    assert after.scenario_results["bull"].scenario == "bull"
    assert (
        after.scenario_results["base"].intrinsic_value_per_share
        != before.scenario_results["base"].intrinsic_value_per_share
    )
    assert (
        after.scenario_results["base"].intrinsic_value_per_share
        > before.scenario_results["base"].intrinsic_value_per_share
    )


def test_unapproved_pack_does_not_affect_drivers_or_dcf() -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    pack = _pack(pack_id="pack:pending", ebit=(0.38, 0.44, 0.47))
    _insert_queue_item(
        conn,
        pack=pack,
        status="pending",
        fingerprint="not-an-approval",
        approved=False,
    )

    base = _drivers()
    lineage = {"ebit_margin_target": "default"}
    resolution = resolve_approved_driver_family_packs(conn, "TEST", base, lineage)

    assert resolution.base_drivers == base
    assert resolution.dcf_scenario_drivers is None
    assert resolution.source_lineage == lineage


def test_superseded_approval_stops_applying() -> None:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    old_pack = _pack(pack_id="pack:old", ebit=(0.30, 0.31, 0.32))
    new_pack = _pack(pack_id="pack:new", ebit=(0.38, 0.44, 0.47))
    old_id = _insert_queue_item(
        conn,
        pack=old_pack,
        status="superseded",
        fingerprint="old-fingerprint",
        approved=True,
    )
    new_id = _insert_queue_item(
        conn,
        pack=new_pack,
        status="approved",
        fingerprint="new-fingerprint",
        approved=True,
    )

    resolution = resolve_approved_driver_family_packs(
        conn,
        "TEST",
        _drivers(),
        {"ebit_margin_target": "default"},
    )

    assert resolution.base_drivers.ebit_margin_target == 0.44
    assert str(new_id) in resolution.source_lineage["ebit_margin_target"]
    assert str(old_id) not in resolution.source_lineage["ebit_margin_target"]
    assert "old-fingerprint" not in resolution.source_lineage["ebit_margin_target"]


def test_bridge_lineage_is_recognised_as_approved_by_the_provenance_gate() -> None:
    """The lineage the bridge writes must classify as approved downstream.

    This is the producer-to-consumer contract: the bridge is the only writer of
    this lineage form, and the provenance gate is what the PM-facing markdown
    reads.  Building the lineage with the real resolver keeps the two from
    drifting apart if the source string is ever reworded.
    """

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    _insert_queue_item(
        conn,
        pack=_pack(pack_id="pack-provenance", ebit=(0.38, 0.44, 0.47)),
        status="approved",
        fingerprint="approval-fingerprint-1",
        approved=True,
    )

    resolution = resolve_approved_driver_family_packs(
        conn,
        "TEST",
        _drivers(),
        {field: "default" for field in judgment_owned_fields()},
    )

    verdicts = assess_judgment_driver_provenance(
        resolution.source_lineage,
        used_fields=judgment_owned_fields(),
    )
    ebit = next(row for row in verdicts if row.field == "ebit_margin_target")

    assert ebit.source_strength is JudgmentDriverSourceStrength.judgment_approved
    assert ebit.status == "approved"
    assert ebit.severity == "none"

    # A family the pack never covered must stay provisional.
    untouched = next(row for row in verdicts if row.field == "revenue_growth_mid")
    assert untouched.status == "provisional"
