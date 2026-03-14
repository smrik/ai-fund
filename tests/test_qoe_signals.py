"""Tests for the deterministic QoE signal compute layer."""
import pytest
from src.stage_03_judgment.qoe_signals import (
    SECTOR_ACCRUALS_THRESHOLDS,
    _composite_score,
    _nwc_baseline,
    _score_high_is_bad,
    _score_low_is_bad,
    compute_qoe_signals,
)


# ── Unit tests for scoring helpers ───────────────────────────────────────────

def test_score_high_is_bad_green():
    assert _score_high_is_bad(0.03, amber_threshold=0.05, red_threshold=0.10) == "green"

def test_score_high_is_bad_amber():
    assert _score_high_is_bad(0.07, amber_threshold=0.05, red_threshold=0.10) == "amber"

def test_score_high_is_bad_red():
    assert _score_high_is_bad(0.12, amber_threshold=0.05, red_threshold=0.10) == "red"

def test_score_high_is_bad_none_is_unavailable():
    assert _score_high_is_bad(None, 0.05, 0.10) == "unavailable"

def test_score_low_is_bad_green():
    assert _score_low_is_bad(0.90, green_threshold=0.85, amber_threshold=0.65) == "green"

def test_score_low_is_bad_amber():
    assert _score_low_is_bad(0.75, green_threshold=0.85, amber_threshold=0.65) == "amber"

def test_score_low_is_bad_red():
    assert _score_low_is_bad(0.50, green_threshold=0.85, amber_threshold=0.65) == "red"

def test_score_low_is_bad_none_is_unavailable():
    assert _score_low_is_bad(None, 0.85, 0.65) == "unavailable"


# ── NWC baseline logic ────────────────────────────────────────────────────────

def test_nwc_baseline_two_or_more_periods_uses_older_average():
    history = [
        {"period_date": "2025", "dso": 60.0, "dio": None, "dpo": None},
        {"period_date": "2024", "dso": 50.0, "dio": None, "dpo": None},
        {"period_date": "2023", "dso": 48.0, "dio": None, "dpo": None},
    ]
    baseline, source = _nwc_baseline(history, "dso", sector_default=45.0)
    assert baseline == pytest.approx(49.0, abs=0.1)  # avg(50, 48)
    assert source == "ciq_history"

def test_nwc_baseline_one_period_uses_sector_default():
    history = [{"period_date": "2025", "dso": 60.0, "dio": None, "dpo": None}]
    baseline, source = _nwc_baseline(history, "dso", sector_default=45.0)
    assert baseline == 45.0
    assert source == "sector_default"

def test_nwc_baseline_zero_periods_is_unavailable():
    baseline, source = _nwc_baseline([], "dso", sector_default=45.0)
    assert baseline is None
    assert source == "unavailable"

def test_nwc_baseline_skips_none_values_in_older_periods():
    history = [
        {"period_date": "2025", "dso": 60.0, "dio": None, "dpo": None},
        {"period_date": "2024", "dso": None, "dio": None, "dpo": None},  # missing
        {"period_date": "2023", "dso": 50.0, "dio": None, "dpo": None},
    ]
    baseline, source = _nwc_baseline(history, "dso", sector_default=45.0)
    assert baseline == pytest.approx(50.0, abs=0.1)  # only 2023 available
    assert source == "ciq_history"


# ── Composite score ───────────────────────────────────────────────────────────

def test_composite_all_green_is_5():
    scores = {"accruals": "green", "cash_conversion": "green", "dso": "green",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 5
    assert flag == "green"

def test_composite_one_amber_is_4():
    scores = {"accruals": "green", "cash_conversion": "amber", "dso": "green",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 4
    assert flag == "green"

def test_composite_two_ambers_is_3():
    scores = {"accruals": "amber", "cash_conversion": "amber", "dso": "green",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 3
    assert flag == "amber"

def test_composite_one_red_is_3():
    scores = {"accruals": "red", "cash_conversion": "green", "dso": "green",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 3
    assert flag == "amber"

def test_composite_two_reds_is_2():
    scores = {"accruals": "red", "cash_conversion": "red", "dso": "green",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 2
    assert flag == "red"

def test_composite_four_ambers_is_2():
    scores = {"accruals": "amber", "cash_conversion": "amber", "dso": "amber",
              "dio": "amber", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 2
    assert flag == "red"

def test_composite_three_reds_is_1():
    scores = {"accruals": "red", "cash_conversion": "red", "dso": "red",
              "dio": "green", "dpo": "green", "capex_da": "green"}
    score, flag = _composite_score(scores)
    assert score == 1
    assert flag == "red"

def test_composite_unavailable_signals_excluded():
    # Only 2 signals available — both green → score 5
    scores = {"accruals": "unavailable", "cash_conversion": "unavailable",
              "dso": "green", "dio": "green", "dpo": "unavailable", "capex_da": "unavailable"}
    score, flag = _composite_score(scores)
    assert score == 5
    assert flag == "green"


# ── Sector-specific accruals thresholds ──────────────────────────────────────

def test_tech_accruals_threshold_higher_than_default():
    tech = SECTOR_ACCRUALS_THRESHOLDS["Technology"]
    default = SECTOR_ACCRUALS_THRESHOLDS["_default"]
    assert tech["amber"] > default["amber"]
    assert tech["red"] > default["red"]

def test_all_sectors_have_amber_less_than_red():
    for sector, thresh in SECTOR_ACCRUALS_THRESHOLDS.items():
        assert thresh["amber"] < thresh["red"], f"{sector}: amber must be < red"


# ── Full compute_qoe_signals integration ─────────────────────────────────────

def _base_hist(**overrides):
    base = {
        "revenue": [1_000_000_000.0, 900_000_000.0, 800_000_000.0],
        "operating_income": [150_000_000.0, 130_000_000.0, 110_000_000.0],
        "net_income": [100_000_000.0, 90_000_000.0, 80_000_000.0],
        "cffo": [95_000_000.0, 85_000_000.0, 75_000_000.0],
        "capex": [60_000_000.0, 55_000_000.0, 50_000_000.0],
        "da": [50_000_000.0, 45_000_000.0, 40_000_000.0],
    }
    base.update(overrides)
    return base


def _base_mkt(**overrides):
    base = {
        "sector": "Technology",
        "ebitda_ttm": 200_000_000.0,
    }
    base.update(overrides)
    return base


def test_compute_qoe_signals_returns_required_keys():
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot={"dso": 50.0, "dio": 35.0, "dpo": 38.0,
                      "operating_income_ttm": 150_000_000.0, "da_ttm": 50_000_000.0},
        ciq_nwc_history=[
            {"period_date": "2025", "dso": 50.0, "dio": 35.0, "dpo": 38.0},
            {"period_date": "2024", "dso": 48.0, "dio": 33.0, "dpo": 36.0},
        ],
        hist=_base_hist(),
        mkt=_base_mkt(),
    )

    assert result["ticker"] == "TEST"
    assert result["qoe_score"] in range(1, 6)
    assert result["qoe_flag"] in {"green", "amber", "red"}
    assert "signal_scores" in result
    assert "accruals_thresholds" in result
    assert set(result["signal_scores"].keys()) == {
        "accruals", "cash_conversion", "dso", "dio", "dpo", "capex_da"
    }


def test_sloan_accruals_computed_correctly():
    # net_income=100M, cffo=95M, revenue=1B → accruals = (100-95)/1000 = 0.5%
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist=_base_hist(
            net_income=[100_000_000.0],
            cffo=[95_000_000.0],
            revenue=[1_000_000_000.0],
        ),
        mkt=_base_mkt(),
    )
    assert result["sloan_accruals_ratio"] == pytest.approx(0.005, abs=0.0001)
    assert result["signal_scores"]["accruals"] == "green"


def test_high_accruals_flagged_red_for_default_sector():
    # net_income=200M, cffo=70M, revenue=1B → accruals = 13% → red for default (>10%)
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Consumer Defensive",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist=_base_hist(
            net_income=[200_000_000.0],
            cffo=[70_000_000.0],
            revenue=[1_000_000_000.0],
        ),
        mkt=_base_mkt(sector="Consumer Defensive"),
    )
    assert result["sloan_accruals_ratio"] == pytest.approx(0.13, abs=0.001)
    assert result["signal_scores"]["accruals"] == "red"


def test_same_accruals_amber_for_tech_sector():
    # 13% accruals is only amber for Tech (threshold: amber=8%, red=15%)
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist=_base_hist(
            net_income=[200_000_000.0],
            cffo=[70_000_000.0],
            revenue=[1_000_000_000.0],
        ),
        mkt=_base_mkt(),
    )
    assert result["signal_scores"]["accruals"] == "amber"


def test_cash_conversion_uses_ciq_ebitda_when_available():
    # cffo=95M, CIQ EBITDA=200M (op_income=150M + da=50M) → 47.5% → red
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot={"operating_income_ttm": 150_000_000.0, "da_ttm": 50_000_000.0},
        ciq_nwc_history=[],
        hist=_base_hist(cffo=[95_000_000.0]),
        mkt=_base_mkt(ebitda_ttm=999_999_999.0),  # should be ignored — CIQ wins
    )
    assert result["cash_conversion"] == pytest.approx(95 / 200, abs=0.001)
    assert result["signal_scores"]["cash_conversion"] == "red"


def test_dso_drift_uses_ciq_history_baseline():
    # current DSO=65, baseline=avg(48,50)=49 → drift=16 → red (>15)
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot={"dso": 65.0},
        ciq_nwc_history=[
            {"period_date": "2025", "dso": 65.0, "dio": None, "dpo": None},
            {"period_date": "2024", "dso": 48.0, "dio": None, "dpo": None},
            {"period_date": "2023", "dso": 50.0, "dio": None, "dpo": None},
        ],
        hist=_base_hist(),
        mkt=_base_mkt(),
    )
    assert result["dso_drift"] == pytest.approx(16.0, abs=0.2)
    assert result["signal_scores"]["dso"] == "red"
    assert result["dso_baseline_source"] == "ciq_history"


def test_dso_unavailable_when_no_ciq_dso():
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,  # no CIQ data at all
        ciq_nwc_history=[],
        hist=_base_hist(),
        mkt=_base_mkt(),
    )
    assert result["dso_current"] is None
    assert result["signal_scores"]["dso"] == "unavailable"


def test_capex_da_ratio_below_threshold_is_amber():
    # capex=60M, da=100M → ratio=0.60 → red (< 0.70)
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist=_base_hist(capex=[60_000_000.0], da=[100_000_000.0]),
        mkt=_base_mkt(),
    )
    assert result["capex_da_ratio"] == pytest.approx(0.60, abs=0.01)
    assert result["signal_scores"]["capex_da"] == "red"


def test_capex_da_ratio_above_one_is_green():
    # capex=120M, da=100M → ratio=1.20 → green
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist=_base_hist(capex=[120_000_000.0], da=[100_000_000.0]),
        mkt=_base_mkt(),
    )
    assert result["capex_da_ratio"] == pytest.approx(1.20, abs=0.01)
    assert result["signal_scores"]["capex_da"] == "green"


def test_missing_hist_data_gives_unavailable_signals():
    result = compute_qoe_signals(
        ticker="TEST",
        sector="Technology",
        ciq_snapshot=None,
        ciq_nwc_history=[],
        hist={},  # empty — all series missing
        mkt={},
    )
    assert result["sloan_accruals_ratio"] is None
    assert result["signal_scores"]["accruals"] == "unavailable"
    assert result["capex_da_ratio"] is None
    assert result["signal_scores"]["capex_da"] == "unavailable"
