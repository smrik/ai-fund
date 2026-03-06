import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from types import SimpleNamespace

from src.valuation import batch_runner
from src.valuation.wacc import WACCResult


class _ScenarioResult:
    def __init__(self, iv: float):
        self.intrinsic_value_per_share = iv
        self.terminal_value = 700.0
        self.enterprise_value = 1000.0



def _fake_wacc_result() -> WACCResult:
    return WACCResult(
        wacc=0.09,
        cost_of_equity=0.11,
        cost_of_debt_after_tax=0.04,
        equity_weight=0.8,
        debt_weight=0.2,
        risk_free_rate=0.045,
        equity_risk_premium=0.05,
        beta_relevered=1.1,
        size_premium=0.01,
        beta_unlevered_median=0.9,
        peers_used=["TEST"],
        peer_betas_unlevered=[0.9],
        target_de_ratio=0.2,
        target_market_cap=10_000_000,
        target_net_debt=2_000_000,
    )


def test_value_single_ticker_prefers_ciq_over_yfinance(monkeypatch):
    monkeypatch.setattr(
        batch_runner.md_client,
        "get_market_data",
        lambda ticker: {
            "current_price": 100.0,
            "revenue_ttm": 500_000_000.0,
            "operating_margin": 0.10,
            "revenue_growth": 0.05,
            "sector": "Technology",
            "industry": "Software",
            "name": "Test Co",
            "market_cap": 5_000_000_000.0,
            "enterprise_value": 6_000_000_000.0,
            "free_cashflow": 100_000_000.0,
            "total_debt": 1_500_000_000.0,
            "cash": 300_000_000.0,
            "shares_outstanding": 100_000_000.0,
            "beta": 1.2,
            "number_of_analysts": 10,
        },
    )

    monkeypatch.setattr(
        batch_runner.md_client,
        "get_historical_financials",
        lambda ticker: {
            "revenue_cagr_3yr": 0.06,
            "op_margin_avg_3yr": 0.11,
            "capex_pct_avg_3yr": 0.05,
            "da_pct_avg_3yr": 0.03,
            "effective_tax_rate_avg": 0.20,
        },
    )

    monkeypatch.setattr(
        batch_runner,
        "get_ciq_snapshot",
        lambda ticker: {
            "revenue_ttm": 800_000_000.0,
            "revenue_cagr_3yr": 0.12,
            "op_margin_avg_3yr": 0.22,
            "capex_pct_avg_3yr": 0.07,
            "da_pct_avg_3yr": 0.04,
            "effective_tax_rate_avg": 0.19,
            "total_debt": 900_000_000.0,
            "cash": 200_000_000.0,
            "shares_outstanding": 50_000_000.0,
            "run_id": 42,
            "source_file": "TEST_Standard.xlsx",
            "as_of_date": "2025-12-31",
        },
    )

    monkeypatch.setattr(batch_runner, "compute_wacc_from_yfinance", lambda *a, **k: _fake_wacc_result())
    monkeypatch.setattr(
        batch_runner,
        "run_scenario_dcf",
        lambda rev, assumptions: {
            "bear": _ScenarioResult(90.0),
            "base": _ScenarioResult(120.0),
            "bull": _ScenarioResult(150.0),
        },
    )
    monkeypatch.setattr(batch_runner, "reverse_dcf", lambda **kwargs: 0.11)

    result = batch_runner.value_single_ticker("TEST")

    assert result is not None
    assert result["revenue_source"] == "ciq"
    assert result["growth_source"] == "ciq"
    assert result["ebit_margin_source"] == "ciq"
    assert result["capex_source"] == "ciq"
    assert result["da_source"] == "ciq"
    assert result["tax_source"] == "ciq"
    assert result["net_debt_source"] == "ciq"
    assert result["shares_source"] == "ciq"
    assert result["ciq_snapshot_used"] is True
    assert result["ciq_run_id"] == 42


