"""Tests for src/stage_04_pipeline/recommendations.py"""
from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.stage_00_data.sec_filing_metrics import SecFilingMetrics
from src.stage_04_pipeline.recommendations import (
    Recommendation,
    TickerRecommendations,
    _recs_from_dict,
    _recs_path,
    _recs_to_dict,
    apply_approved_to_overrides,
    extract_recommendations,
    load_recommendations,
    write_recommendations,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_drivers(**kwargs):
    """Return a minimal ForecastDrivers-like mock."""
    defaults = {
        "revenue_base": 10_000_000_000,  # $10B
        "ebit_margin_start": 0.15,
        "ebit_margin_target": 0.18,
        "revenue_growth_near": 0.08,
        "revenue_growth_mid": 0.06,
        "non_operating_assets": 500_000_000,
        "lease_liabilities": 200_000_000,
        "minority_interest": 0.0,
        "preferred_equity": 0.0,
        "pension_deficit": 0.0,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    m.__class__.__name__ = "ForecastDrivers"
    return m


QOE_RESULT_PENDING = {
    "ticker": "IBM",
    "qoe_score": 2,
    "qoe_flag": "RED",
    "llm": {
        "llm_available": True,
        "normalized_ebit": 1_200_000_000,   # $1.2B (current margin start = 0.15 → 10B×0.15 = 1.5B)
        "reported_ebit": 1_500_000_000,
        "ebit_haircut_pct": -20.0,
        "dcf_ebit_override_pending": True,
        "llm_confidence": "high",
        "ebit_adjustments": [
            {"item": "Restructuring", "amount": 300_000_000, "direction": "+", "rationale": "Non-recurring"},
        ],
    },
}

ACCOUNTING_RECAST_RESULT = {
    "ticker": "IBM",
    "confidence": "medium",
    "income_statement_adjustments": [],
    "balance_sheet_reclassifications": [
        {
            "line_item": "Operating leases",
            "reported_value": 2_500_000_000,
            "proposed_driver_field": "lease_liabilities",
            "rationale": "Capitalise operating leases per IFRS 16 equivalent",
            "citation_text": "Note 14: Operating lease right-of-use assets",
        }
    ],
    "override_candidates": {
        "normalized_ebit": None,
        "non_operating_assets": None,
        "lease_liabilities": 2_500_000_000,
        "minority_interest": None,
        "preferred_equity": None,
        "pension_deficit": None,
    },
    "approval_required": True,
    "pm_review_notes": "Review operating lease capitalisation",
}

INDUSTRY_RESULT = {
    "sector": "Technology",
    "industry": "IT Services",
    "consensus_growth_near": 0.12,  # 12% vs current 8% → delta 4pp > 1pp threshold
    "consensus_growth_mid": 0.09,   # 9% vs current 6% → delta 3pp
    "margin_benchmark": 0.20,       # 20% vs current target 18% → delta 2pp
    "confidence": "medium",
}

FILINGS_METRICS = SecFilingMetrics(
    ticker="IBM",
    cik="0000051143",
    as_of_date="2026-03-14",
    source_filing_date="2025-12-31",
    source_form="10-K",
    revenue_cagr_3y=0.12,
    ebit_margin_avg_3y=0.18,
    gross_margin_avg_3y=0.52,
    fcf_yield=None,
    net_debt_to_ebitda=None,
    revenue_series=[{"period": "2025-12-31", "value": 121.0}],
    ebit_series=[{"period": "2025-12-31", "value": 21.8}],
    metric_source="sec_xbrl_companyfacts",
)


# ── extract_recommendations ───────────────────────────────────────────────────

class TestExtractRecommendations:
    def test_qoe_pending_generates_ebit_margin_rec(self):
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        qoe_recs = [r for r in recs.recommendations if r.agent == "qoe"]
        assert len(qoe_recs) == 1
        rec = qoe_recs[0]
        assert rec.field == "ebit_margin_start"
        assert rec.status == "pending"
        assert rec.confidence == "high"
        # normalized_ebit / revenue_base = 1.2B / 10B = 0.12
        assert abs(rec.proposed_value - 0.12) < 1e-5
        assert rec.current_value == pytest.approx(0.15)

    def test_qoe_no_pending_flag_skips(self):
        result = copy.deepcopy(QOE_RESULT_PENDING)
        result["llm"]["dcf_ebit_override_pending"] = False
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", result, {}, {}, drivers)
        assert not any(r.agent == "qoe" for r in recs.recommendations)

    def test_accounting_recast_ev_bridge_fields(self):
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", {}, ACCOUNTING_RECAST_RESULT, {}, drivers)
        ar_recs = [r for r in recs.recommendations if r.agent == "accounting_recast"]
        # Only lease_liabilities has a non-None value AND material delta
        assert len(ar_recs) == 1
        rec = ar_recs[0]
        assert rec.field == "lease_liabilities"
        assert rec.proposed_value == 2_500_000_000
        assert rec.citation == "Note 14: Operating lease right-of-use assets"

    def test_accounting_recast_immaterial_delta_skipped(self):
        # If proposed is within $1M of current, skip
        recast = copy.deepcopy(ACCOUNTING_RECAST_RESULT)
        recast["override_candidates"]["lease_liabilities"] = 200_500_000  # only $500k delta
        drivers = _make_drivers(lease_liabilities=200_000_000)
        recs = extract_recommendations("IBM", {}, recast, {}, drivers)
        ar_recs = [r for r in recs.recommendations if r.agent == "accounting_recast"]
        assert not any(r.field == "lease_liabilities" for r in ar_recs)

    def test_industry_growth_and_margin_recs(self):
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", {}, {}, INDUSTRY_RESULT, drivers)
        ind_recs = [r for r in recs.recommendations if r.agent == "industry"]
        fields = {r.field for r in ind_recs}
        assert "revenue_growth_near" in fields
        assert "revenue_growth_mid" in fields
        assert "ebit_margin_target" in fields

    def test_industry_sub_threshold_delta_skipped(self):
        # Industry margin_benchmark 18.5% vs current 18% → delta 0.5pp < 1pp → skip
        ind = copy.deepcopy(INDUSTRY_RESULT)
        ind["margin_benchmark"] = 0.185
        drivers = _make_drivers(ebit_margin_target=0.18)
        recs = extract_recommendations("IBM", {}, {}, ind, drivers)
        ind_recs = [r for r in recs.recommendations if r.agent == "industry"]
        assert not any(r.field == "ebit_margin_target" for r in ind_recs)

    def test_empty_inputs_return_empty_recs(self):
        recs = extract_recommendations("IBM", {}, {}, {}, None)
        assert recs.recommendations == []
        assert recs.ticker == "IBM"

    def test_filings_metrics_generate_growth_and_margin_recommendations(self):
        drivers = _make_drivers(revenue_growth_near=0.08, ebit_margin_start=0.15)
        recs = extract_recommendations(
            "IBM",
            {},
            {},
            {},
            drivers,
            filings_metrics=FILINGS_METRICS,
        )
        filings_recs = [r for r in recs.recommendations if r.agent == "filings"]
        fields = {r.field for r in filings_recs}
        assert fields == {"revenue_growth_near", "ebit_margin_start"}
        assert all(r.confidence == "high" for r in filings_recs)
        assert all("SEC/XBRL" in r.rationale for r in filings_recs)
        assert all(r.citation == "SEC XBRL 10-K 2025-12-31" for r in filings_recs)

    def test_filings_metrics_sub_threshold_deltas_are_skipped(self):
        drivers = _make_drivers(revenue_growth_near=0.11, ebit_margin_start=0.175)
        recs = extract_recommendations(
            "IBM",
            {},
            {},
            {},
            drivers,
            filings_metrics=FILINGS_METRICS,
        )
        assert not any(r.agent == "filings" for r in recs.recommendations)

    def test_preserves_existing_approved_status(self, tmp_path, monkeypatch):
        """Re-run should not reset an already-approved item back to pending."""
        monkeypatch.setattr(
            "src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path
        )
        drivers = _make_drivers()
        # First run — write file with approved status
        recs1 = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        recs1.recommendations[0].status = "approved"
        write_recommendations(recs1)
        # Second run — should preserve approved
        recs2 = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        qoe_recs = [r for r in recs2.recommendations if r.agent == "qoe"]
        assert qoe_recs[0].status == "approved"


# ── write / load ──────────────────────────────────────────────────────────────

class TestWriteLoad:
    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, ACCOUNTING_RECAST_RESULT, INDUSTRY_RESULT, drivers)
        path = write_recommendations(recs)
        assert path.exists()
        loaded = load_recommendations("IBM")
        assert loaded is not None
        assert loaded.ticker == "IBM"
        assert len(loaded.recommendations) == len(recs.recommendations)

    def test_load_nonexistent_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        assert load_recommendations("NONEXISTENT") is None

    def test_yaml_status_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        recs.recommendations[0].status = "approved"
        write_recommendations(recs)
        loaded = load_recommendations("IBM")
        assert loaded.recommendations[0].status == "approved"

    def test_serialization_dict_roundtrip(self):
        rec = Recommendation(
            agent="qoe", field="ebit_margin_start",
            current_value=0.15, proposed_value=0.12,
            confidence="high", rationale="test", status="pending",
        )
        tr = TickerRecommendations(ticker="IBM", generated_at="2026-03-14T00:00:00+00:00",
                                   current_iv_base=150.0, recommendations=[rec])
        d = _recs_to_dict(tr)
        restored = _recs_from_dict(d)
        assert restored.ticker == "IBM"
        assert len(restored.recommendations) == 1
        assert restored.recommendations[0].field == "ebit_margin_start"
        assert restored.recommendations[0].proposed_value == pytest.approx(0.12)


# ── apply_approved_to_overrides ───────────────────────────────────────────────

class TestApplyApproved:
    def test_writes_approved_to_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.OVERRIDES_PATH",
                            tmp_path / "valuation_overrides.yaml")
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        recs.recommendations[0].status = "approved"
        write_recommendations(recs)

        count = apply_approved_to_overrides("IBM")
        assert count == 1

        overrides_path = tmp_path / "valuation_overrides.yaml"
        assert overrides_path.exists()
        data = yaml.safe_load(overrides_path.read_text())
        assert "IBM" in data["tickers"]
        assert "ebit_margin_start" in data["tickers"]["IBM"]

    def test_no_approved_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.OVERRIDES_PATH",
                            tmp_path / "valuation_overrides.yaml")
        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        # All remain pending
        write_recommendations(recs)
        count = apply_approved_to_overrides("IBM")
        assert count == 0

    def test_skips_dict_type_proposed_values(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.OVERRIDES_PATH",
                            tmp_path / "valuation_overrides.yaml")
        rec = Recommendation(
            agent="story", field="story_profile",
            current_value=None, proposed_value={"moat_strength": 4},
            confidence="medium", rationale="compound type", status="approved",
        )
        recs = TickerRecommendations(ticker="IBM", generated_at="2026-01-01",
                                     current_iv_base=None, recommendations=[rec])
        write_recommendations(recs)
        count = apply_approved_to_overrides("IBM")
        assert count == 0  # dict type skipped

    def test_preserves_existing_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.RECS_DIR", tmp_path)
        overrides_path = tmp_path / "valuation_overrides.yaml"
        monkeypatch.setattr("src.stage_04_pipeline.recommendations.OVERRIDES_PATH", overrides_path)

        existing = {"global": {}, "sectors": {}, "tickers": {"IBM": {"wacc": 0.09}}}
        overrides_path.write_text(yaml.dump(existing))

        drivers = _make_drivers()
        recs = extract_recommendations("IBM", QOE_RESULT_PENDING, {}, {}, drivers)
        recs.recommendations[0].status = "approved"
        write_recommendations(recs)
        apply_approved_to_overrides("IBM")

        data = yaml.safe_load(overrides_path.read_text())
        # Both wacc (pre-existing) and ebit_margin_start (new) should be present
        assert data["tickers"]["IBM"]["wacc"] == pytest.approx(0.09)
        assert "ebit_margin_start" in data["tickers"]["IBM"]
