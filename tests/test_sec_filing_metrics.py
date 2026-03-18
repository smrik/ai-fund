import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
from src.stage_00_data import sec_filing_metrics


def _init_temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()
    return db_path


def _make_series(periods_values: list[tuple[str, float]]) -> list[dict]:
    return [{"period": p, "value": v} for p, v in periods_values]


def _make_extract_annual_series(
    revenues: list[tuple[str, float]],
    operating_income: list[tuple[str, float]] | None = None,
    gross_profit: list[tuple[str, float]] | None = None,
):
    """Return a fake _extract_annual_series that yields pre-baked series by metric name."""
    def _fake(ticker: str, metric_names: tuple) -> list[dict]:
        if "Revenues" in metric_names or "RevenueFromContractWithCustomerExcludingAssessedTax" in metric_names:
            return _make_series(revenues)
        if "OperatingIncomeLoss" in metric_names:
            return _make_series(operating_income) if operating_income else []
        if "GrossProfit" in metric_names:
            return _make_series(gross_profit) if gross_profit else []
        return []
    return _fake


def test_get_sec_filing_metrics_computes_revenue_cagr_and_ebit_margin(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(sec_filing_metrics, "DB_PATH", db_path)
    monkeypatch.setattr(sec_filing_metrics, "get_cik", lambda ticker: "0000051143")
    monkeypatch.setattr(
        sec_filing_metrics,
        "_extract_annual_series",
        _make_extract_annual_series(
            revenues=[("2022-12-31", 100.0), ("2023-12-31", 110.0), ("2024-12-31", 121.0)],
            operating_income=[("2022-12-31", 10.0), ("2023-12-31", 11.0), ("2024-12-31", 12.1)],
            gross_profit=[("2022-12-31", 50.0), ("2023-12-31", 55.0), ("2024-12-31", 60.5)],
        ),
    )

    metrics = sec_filing_metrics.get_sec_filing_metrics("IBM")

    assert metrics is not None
    assert metrics.ticker == "IBM"
    assert metrics.cik == "0000051143"
    assert metrics.source_form == "10-K"
    assert metrics.source_filing_date == "2024-12-31"
    assert metrics.revenue_cagr_3y == pytest.approx(0.10, abs=1e-6)
    assert metrics.ebit_margin_avg_3y == pytest.approx(0.10, abs=1e-6)
    assert metrics.gross_margin_avg_3y == pytest.approx(0.50, abs=1e-6)
    assert len(metrics.revenue_series) == 3
    assert len(metrics.ebit_series) == 3


def test_get_sec_filing_metrics_uses_cache_before_recomputing(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(sec_filing_metrics, "DB_PATH", db_path)
    monkeypatch.setattr(sec_filing_metrics, "get_cik", lambda ticker: "0000051143")

    calls = {"count": 0}

    def _counting_extract(ticker: str, metric_names: tuple) -> list[dict]:
        if "Revenues" in metric_names or "RevenueFromContractWithCustomerExcludingAssessedTax" in metric_names:
            calls["count"] += 1
            return _make_series([("2022-12-31", 100.0), ("2023-12-31", 110.0), ("2024-12-31", 121.0)])
        if "OperatingIncomeLoss" in metric_names:
            return _make_series([("2022-12-31", 10.0), ("2023-12-31", 11.0), ("2024-12-31", 12.1)])
        return []

    monkeypatch.setattr(sec_filing_metrics, "_extract_annual_series", _counting_extract)

    first = sec_filing_metrics.get_sec_filing_metrics("IBM")
    second = sec_filing_metrics.get_sec_filing_metrics("IBM")

    assert first is not None and second is not None
    assert calls["count"] == 1
    assert second.revenue_cagr_3y == pytest.approx(first.revenue_cagr_3y)


def test_get_sec_filing_metrics_returns_partial_metrics_when_facts_incomplete(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(sec_filing_metrics, "DB_PATH", db_path)
    monkeypatch.setattr(sec_filing_metrics, "get_cik", lambda ticker: "0000051143")
    monkeypatch.setattr(
        sec_filing_metrics,
        "_extract_annual_series",
        _make_extract_annual_series(
            revenues=[("2022-12-31", 100.0), ("2023-12-31", 110.0), ("2024-12-31", 121.0)],
        ),
    )

    metrics = sec_filing_metrics.get_sec_filing_metrics("IBM")

    assert metrics is not None
    assert metrics.revenue_cagr_3y == pytest.approx(0.10, abs=1e-6)
    assert metrics.ebit_margin_avg_3y is None
    assert metrics.gross_margin_avg_3y is None
    assert metrics.ebit_series == []
