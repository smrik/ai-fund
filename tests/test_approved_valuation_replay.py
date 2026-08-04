from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.contracts.driver_families import DriverFamilyProposal
from src.contracts.assumption_registry import judgment_owned_fields
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.valuation_readiness import (
    ValuationReadinessEvidence,
    assess_judgment_driver_provenance,
)
from src.stage_02_valuation.approved_case_replay import (
    compile_approved_valuation_case,
    replay_approved_valuation_case,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


def _driver(
    assumption_name: str,
    unit: str,
    low: float,
    base: float,
    high: float,
) -> dict[str, object]:
    return {
        "assumption_name": assumption_name,
        "unit": unit,
        "applicability": "applicable",
        "low": low,
        "base": base,
        "high": high,
        "conditions": {
            "low": f"Low case for {assumption_name}.",
            "base": f"Base case for {assumption_name}.",
            "high": f"High case for {assumption_name}.",
        },
        "rationale": f"Evidence-grounded rationale for {assumption_name}.",
        "evidence_anchor_ids": [f"fact:{assumption_name}"],
        "what_would_change_view": f"New evidence for {assumption_name}.",
    }


def _approved_packs() -> tuple[DriverFamilyProposal, ...]:
    return (
        DriverFamilyProposal.model_validate(
            {
                "family": "revenue",
                "horizon_years": 10,
                "assumptions": [
                    _driver("revenue_growth_near", "decimal", 0.04, 0.08, 0.12),
                    _driver("revenue_growth_mid", "decimal", 0.03, 0.05, 0.08),
                    _driver(
                        "revenue_growth_terminal",
                        "decimal",
                        0.02,
                        0.025,
                        0.03,
                    ),
                ],
                "family_rationale": "Revenue cases follow disclosed demand.",
            }
        ),
        DriverFamilyProposal.model_validate(
            {
                "family": "profitability_tax",
                "horizon_years": 10,
                "assumptions": [
                    _driver("cogs_pct_of_revenue", "decimal", 0.65, 0.60, 0.55),
                    _driver("ebit_margin_target", "decimal", 0.18, 0.22, 0.26),
                    _driver("tax_rate_target", "decimal", 0.25, 0.22, 0.19),
                ],
                "family_rationale": "Margin and tax cases follow operating evidence.",
            }
        ),
        DriverFamilyProposal.model_validate(
            {
                "family": "reinvestment_working_capital",
                "horizon_years": 10,
                "assumptions": [
                    _driver("capex_pct_target", "decimal", 0.07, 0.05, 0.04),
                    _driver("da_pct_target", "decimal", 0.03, 0.03, 0.03),
                    _driver("dso_target", "days", 55.0, 45.0, 35.0),
                    _driver("dio_target", "days", 50.0, 40.0, 30.0),
                    _driver("dpo_target", "days", 30.0, 40.0, 50.0),
                ],
                "family_rationale": "Reinvestment follows reconciled statements.",
            }
        ),
        DriverFamilyProposal.model_validate(
            {
                "family": "terminal_capital_comps",
                "horizon_years": 10,
                "assumptions": [
                    _driver("ronic_terminal", "decimal", 0.09, 0.12, 0.15),
                    _driver("annual_dilution_pct", "decimal", 0.02, 0.01, 0.00),
                    _driver("exit_multiple", "multiple", 9.0, 12.0, 15.0),
                ],
                "family_rationale": "Terminal cases triangulate reinvestment and peers.",
            }
        ),
    )


def _base_drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=1_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.20,
        ebit_margin_target=0.22,
        tax_rate_start=0.21,
        tax_rate_target=0.22,
        capex_pct_start=0.05,
        capex_pct_target=0.05,
        da_pct_start=0.03,
        da_pct_target=0.03,
        dso_start=45.0,
        dso_target=45.0,
        dio_start=40.0,
        dio_target=40.0,
        dpo_start=40.0,
        dpo_target=40.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=100.0,
        shares_outstanding=100.0,
        ronic_terminal=0.12,
        cogs_pct_of_revenue=0.60,
        annual_dilution_pct=0.01,
    )


def _comps_detail() -> dict[str, object]:
    return {
        "target": {
            "ticker": "TEST",
            "market_cap_mm": 900.0,
            "tev_mm": 1_000.0,
            "ebitda_ltm_mm": 150.0,
            "ebit_ltm_mm": 120.0,
            "eps_ltm": 1.5,
        },
        "peers": [
            {
                "ticker": ticker,
                "market_cap_mm": market_cap,
                "tev_ebitda_ltm": multiple,
                "tev_ebit_ltm": multiple + 2.0,
                "pe_ltm": multiple + 8.0,
            }
            for ticker, market_cap, multiple in (
                ("AAA", 700.0, 9.0),
                ("BBB", 900.0, 10.0),
                ("CCC", 1_100.0, 11.0),
                ("DDD", 1_300.0, 12.0),
            )
        ],
    }


def _engine_fingerprint() -> str:
    return canonical_semantic_hash(
        {"dcf": "dcf-test-v1", "comps": "comps-test-v1", "bridge": "bridge-test-v1"}
    )


def _approval_fingerprints() -> tuple[str, ...]:
    return (
        "approval:revenue:v1",
        "approval:profitability_tax:v1",
        "approval:reinvestment_working_capital:v1",
        "approval:terminal_capital_comps:v1",
    )


def _readiness(
    packs: tuple[DriverFamilyProposal, ...],
    *,
    comps_detail: dict[str, object] | None = None,
    treatments: tuple[str, ...] = ("treatment-1",),
) -> ValuationReadinessEvidence:
    resolved_comps = comps_detail or _comps_detail()
    return ValuationReadinessEvidence.model_validate(
        {
            "statement_reconciliation": "reconciled",
            "source_reconciliation": "reconciled",
            "claim_ledger_reconciliation": "reconciled",
            "operating_reconciliation": "reconciled",
            "annual_period_count": 5,
            "ltm_status": "compatible",
            "judgment_driver_verdicts": assess_judgment_driver_provenance(
                {
                    field: "approved_assumption_register"
                    for field in judgment_owned_fields()
                },
                used_fields=judgment_owned_fields(),
            ),
            "approved_family_hashes": {
                pack.family.value: canonical_semantic_hash(pack)
                for pack in packs
            },
            "statement_reconciliation_hash": "statement-hash",
            "source_reconciliation_hash": "source-hash",
            "claim_ledger_hash": "claim-hash",
            "operating_reconciliation_hash": "operating-hash",
            "peer_set_fingerprint": canonical_semantic_hash(resolved_comps),
            "treatment_set_fingerprint": canonical_semantic_hash(
                sorted(treatments)
            ),
            "prompt_contract_fingerprint": "prompt-contract-hash",
            "dcf_engine_fingerprint": "dcf-test-v1",
            "comps_engine_fingerprint": "comps-test-v1",
            "bridge_engine_fingerprint": "bridge-test-v1",
        }
    )


def test_approved_case_replay_is_provider_free_and_byte_identical() -> None:
    packs = _approved_packs()
    case = compile_approved_valuation_case(
        ticker="test",
        analysis_snapshot_hash="snapshot-123",
        base_drivers=_base_drivers(),
        approved_packs=packs,
        approval_fingerprints=_approval_fingerprints(),
        approved_treatment_hashes=("treatment-1",),
        frozen_comps_detail=_comps_detail(),
        valuation_policy={
            "scenario_probabilities": {"low": 0.25, "base": 0.50, "high": 0.25}
        },
        engine_fingerprint=_engine_fingerprint(),
        readiness=_readiness(packs),
    )

    first = replay_approved_valuation_case(case)
    second = replay_approved_valuation_case(case)

    assert case.ticker == "TEST"
    assert case.drivers_for("low").revenue_growth_near == 0.04
    assert case.drivers_for("base").tax_rate_target == 0.22
    assert case.drivers_for("high").exit_multiple == 15.0
    assert first.replay_key == second.replay_key == case.replay_key
    assert first.output_hash == second.output_hash
    assert first.canonical_output == second.canonical_output
    assert set(first.dcf_results) == {"low", "base", "high"}
    assert first.dcf_results["low"]["scenario"] == "bear"
    assert first.dcf_results["base"]["scenario"] == "base"
    assert first.dcf_results["high"]["scenario"] == "bull"
    assert first.comps_result is not None


def test_replay_comps_uses_full_bridge_and_usd_to_mm_units() -> None:
    packs = _approved_packs()
    drivers = replace(
        _base_drivers(),
        revenue_base=1_000_000_000.0,
        net_debt=2_000_000_000.0,
        minority_interest=300_000_000.0,
        shares_outstanding=50_000_000.0,
    )
    comps_detail = _comps_detail()
    comps_detail["target"].update(
        {
            "ebitda_ltm_mm": 1_000.0,
            "ebit_ltm_mm": None,
            "eps_ltm": None,
        }
    )
    for peer in comps_detail["peers"]:
        peer["tev_ebitda_ltm"] = 10.0
        peer["tev_ebit_ltm"] = None
        peer["pe_ltm"] = None

    case = compile_approved_valuation_case(
        ticker="test",
        analysis_snapshot_hash="snapshot-bridge",
        base_drivers=drivers,
        approved_packs=packs,
        approval_fingerprints=_approval_fingerprints(),
        approved_treatment_hashes=("treatment-1",),
        frozen_comps_detail=comps_detail,
        valuation_policy={
            "scenario_probabilities": {
                "low": 0.25,
                "base": 0.50,
                "high": 0.25,
            }
        },
        engine_fingerprint=_engine_fingerprint(),
        readiness=_readiness(packs, comps_detail=comps_detail),
    )

    replay = replay_approved_valuation_case(case)

    assert replay.comps_result is not None
    assert replay.comps_result["metrics"]["tev_ebitda_ltm"][
        "base_iv"
    ] == pytest.approx(154.0)
    assert replay.comps_result["ev_to_equity_adjustment_mm"] == (
        pytest.approx(2_300.0)
    )
    assert replay.ev_to_equity_bridge[
        "ev_to_equity_adjustment_usd"
    ] == pytest.approx(2_300_000_000.0)
    assert replay.ev_to_equity_bridge["components_usd"][
        "minority_interest"
    ] == pytest.approx(300_000_000.0)


@pytest.mark.parametrize(
    ("horizons", "message"),
    (
        ((9, 10, 10, 10), "one common horizon"),
        ((9, 9, 9, 9), "must match the DCF engine"),
    ),
)
def test_compile_rejects_driver_pack_horizon_mismatch(
    horizons: tuple[int, ...],
    message: str,
) -> None:
    packs = tuple(
        DriverFamilyProposal.model_validate(
            {
                **pack.model_dump(mode="json"),
                "horizon_years": horizon,
            }
        )
        for pack, horizon in zip(_approved_packs(), horizons, strict=True)
    )

    with pytest.raises(ValueError, match=message):
        compile_approved_valuation_case(
            ticker="test",
            analysis_snapshot_hash="snapshot-horizon",
            base_drivers=_base_drivers(),
            approved_packs=packs,
            approval_fingerprints=_approval_fingerprints(),
            approved_treatment_hashes=("treatment-1",),
            frozen_comps_detail=_comps_detail(),
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            engine_fingerprint=_engine_fingerprint(),
            readiness=_readiness(packs),
        )


def test_replay_identity_changes_when_one_approved_value_changes() -> None:
    packs = _approved_packs()
    changed_revenue_payload = deepcopy(packs[0].model_dump(mode="json"))
    changed_revenue_payload["assumptions"][0]["base"] = 0.081
    changed_packs = (
        DriverFamilyProposal.model_validate(changed_revenue_payload),
        *packs[1:],
    )
    common = {
        "ticker": "TEST",
        "analysis_snapshot_hash": "snapshot-123",
        "base_drivers": _base_drivers(),
        "approved_treatment_hashes": ("treatment-1",),
        "frozen_comps_detail": _comps_detail(),
        "valuation_policy": {
            "scenario_probabilities": {"low": 0.25, "base": 0.50, "high": 0.25}
        },
        "engine_fingerprint": _engine_fingerprint(),
    }

    original = compile_approved_valuation_case(
        approved_packs=packs,
        approval_fingerprints=_approval_fingerprints(),
        readiness=_readiness(packs),
        **common,
    )
    changed = compile_approved_valuation_case(
        approved_packs=changed_packs,
        approval_fingerprints=_approval_fingerprints(),
        readiness=_readiness(changed_packs),
        **common,
    )
    changed_approval = compile_approved_valuation_case(
        approved_packs=packs,
        approval_fingerprints=(
            "approval:revenue:v2",
            *_approval_fingerprints()[1:],
        ),
        readiness=_readiness(packs),
        **common,
    )

    assert original.replay_key != changed.replay_key
    assert original.replay_key != changed_approval.replay_key


def test_compile_rechecks_readiness_fingerprints_and_fails_closed() -> None:
    packs = _approved_packs()
    incomplete = _readiness(packs).model_copy(
        update={"operating_reconciliation": "pending"}
    )

    with pytest.raises(ValueError, match="not decision-grade"):
        compile_approved_valuation_case(
            ticker="TEST",
            analysis_snapshot_hash="snapshot-123",
            base_drivers=_base_drivers(),
            approved_packs=packs,
            approval_fingerprints=_approval_fingerprints(),
            approved_treatment_hashes=("treatment-1",),
            frozen_comps_detail=_comps_detail(),
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            engine_fingerprint=_engine_fingerprint(),
            readiness=incomplete,
        )

    stale_peer_set = _readiness(packs).model_copy(
        update={"peer_set_fingerprint": "stale-peer-set"}
    )
    with pytest.raises(ValueError, match="peer-set fingerprint"):
        compile_approved_valuation_case(
            ticker="TEST",
            analysis_snapshot_hash="snapshot-123",
            base_drivers=_base_drivers(),
            approved_packs=packs,
            approval_fingerprints=_approval_fingerprints(),
            approved_treatment_hashes=("treatment-1",),
            frozen_comps_detail=_comps_detail(),
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            engine_fingerprint=_engine_fingerprint(),
            readiness=stale_peer_set,
        )


def test_compile_requires_one_approval_fingerprint_per_family() -> None:
    packs = _approved_packs()

    with pytest.raises(
        ValueError,
        match="one approval fingerprint per driver family",
    ):
        compile_approved_valuation_case(
            ticker="TEST",
            analysis_snapshot_hash="snapshot-123",
            base_drivers=_base_drivers(),
            approved_packs=packs,
            approval_fingerprints=_approval_fingerprints()[:3],
            approved_treatment_hashes=("treatment-1",),
            frozen_comps_detail=_comps_detail(),
            valuation_policy={
                "scenario_probabilities": {
                    "low": 0.25,
                    "base": 0.50,
                    "high": 0.25,
                }
            },
            engine_fingerprint=_engine_fingerprint(),
            readiness=_readiness(packs),
        )


def test_replay_module_cannot_import_mutable_data_or_judgment_layers() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "stage_02_valuation"
        / "approved_case_replay.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    forbidden_prefixes = (
        "db",
        "src.stage_00_data",
        "src.stage_03_judgment",
        "src.stage_04_pipeline",
        "os",
        "datetime",
        "requests",
        "httpx",
    )
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in imported
        for prefix in forbidden_prefixes
    )
