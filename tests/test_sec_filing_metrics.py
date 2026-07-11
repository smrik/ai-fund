import sqlite3
import sys
from types import SimpleNamespace
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


def _extract_fake_annual_series(monkeypatch, concept_rows: dict[str, list[dict]], ticker: str = "TEST"):
    class FakeFrame:
        def __init__(self, rows):
            self._rows = rows
            self.empty = not rows

        def iterrows(self):
            return enumerate(self._rows)

    class FakeQuery:
        def __init__(self):
            self._concept = ""

        def by_concept(self, concept):
            self._concept = concept
            return self

        def latest_periods(self, *_args, **_kwargs):
            return self

        def to_dataframe(self):
            return FakeFrame(concept_rows.get(self._concept, []))

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        def __init__(self, company_ticker):
            self.ticker = company_ticker

        def get_facts(self):
            return FakeFacts()

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))
    return sec_filing_metrics._extract_annual_series(ticker, ("Revenues",))


def test_extract_annual_series_prefers_fresh_concept_and_deduplicates_years(
    monkeypatch,
):
    concept_rows = {
        "Revenues": [
            {"period_end": "2010-03-31", "numeric_value": 14.5},
            {"period_end": "2010-06-30", "numeric_value": 62.4},
            {"period_end": "2010-06-30", "numeric_value": 16.0},
        ],
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            {"period_end": "2023-06-30", "numeric_value": 211.9},
            {"period_end": "2024-06-30", "numeric_value": 245.1},
            {"period_end": "2024-06-30", "numeric_value": 245.1},
            {"period_end": "2025-06-30", "numeric_value": 281.7},
        ],
    }

    class FakeFrame:
        def __init__(self, rows):
            self._rows = rows
            self.empty = not rows

        def iterrows(self):
            return enumerate(self._rows)

    class FakeQuery:
        def __init__(self):
            self._concept = ""

        def by_concept(self, concept):
            self._concept = concept
            return self

        def latest_periods(self, *_args, **_kwargs):
            return self

        def to_dataframe(self):
            return FakeFrame(concept_rows.get(self._concept, []))

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        def __init__(self, ticker):
            self.ticker = ticker

        def get_facts(self):
            return FakeFacts()

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    series = sec_filing_metrics._extract_annual_series(
        "MSFT",
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    )

    assert series == [
        {"period": "2023-06-30", "value": 211.9},
        {"period": "2024-06-30", "value": 245.1},
        {"period": "2025-06-30", "value": 281.7},
    ]


def test_extract_annual_series_drops_quarterly_duration_facts(monkeypatch):
    # CALM-style CompanyFacts: the FY filing reports quarterly facts under the
    # same concept, including a Q4 fact sharing period_end with the annual fact.
    concept_rows = {
        "Revenues": [
            {"period_start": "2023-06-04", "period_end": "2024-06-01", "numeric_value": 2326000000.0},
            {"period_start": "2024-03-03", "period_end": "2024-06-01", "numeric_value": 640000000.0},
            {"period_start": "2024-06-02", "period_end": "2025-05-31", "numeric_value": 4260000000.0},
            {"period_start": "2025-03-02", "period_end": "2025-05-31", "numeric_value": 1100000000.0},
        ],
    }

    class FakeFrame:
        def __init__(self, rows):
            self._rows = rows
            self.empty = not rows

        def iterrows(self):
            return enumerate(self._rows)

    class FakeQuery:
        def __init__(self):
            self._concept = ""

        def by_concept(self, concept):
            self._concept = concept
            return self

        def latest_periods(self, *_args, **_kwargs):
            return self

        def to_dataframe(self):
            return FakeFrame(concept_rows.get(self._concept, []))

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        def __init__(self, ticker):
            self.ticker = ticker

        def get_facts(self):
            return FakeFacts()

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    series = sec_filing_metrics._extract_annual_series("CALM", ("Revenues",))

    assert series == [
        {"period": "2024-06-01", "value": 2326000000.0},
        {"period": "2025-05-31", "value": 4260000000.0},
    ]


def test_extract_annual_series_deduplicates_by_spacing_not_calendar_year(monkeypatch):
    series = _extract_fake_annual_series(
        monkeypatch,
        {
            "Revenues": [
                {"period_end": "2018-03-31", "numeric_value": 100.0},
                {"period_end": "2018-06-30", "numeric_value": 110.0},
                {"period_end": "2023-01-01", "numeric_value": 120.0},
                {"period_end": "2023-12-31", "numeric_value": 130.0},
            ]
        },
    )

    assert series == [
        {"period": "2018-06-30", "value": 110.0},
        {"period": "2023-01-01", "value": 120.0},
        {"period": "2023-12-31", "value": 130.0},
    ]


def test_extract_annual_series_prefers_newer_fiscal_year_restatement_and_drops_ties(monkeypatch):
    series = _extract_fake_annual_series(
        monkeypatch,
        {
            "Revenues": [
                {"period_end": "2024-03-31", "numeric_value": 100.0, "fiscal_year": 2024},
                {"period_end": "2024-03-31", "numeric_value": 102.0, "fiscal_year": 2025},
                {"period_end": "2025-03-31", "numeric_value": 200.0, "fiscal_year": 2025},
                {"period_end": "2025-03-31", "numeric_value": 201.0, "fiscal_year": 2025},
            ]
        },
    )

    assert series == [{"period": "2024-03-31", "value": 102.0}]


def test_compute_cagr_returns_none_for_series_with_year_gaps():
    # BAH-style series: three observations spanning four fiscal years. Annualizing
    # as if they were consecutive would fabricate a growth rate.
    gapped = [
        {"period": "2022-03-31", "value": 8364000000.0},
        {"period": "2025-03-31", "value": 11021000000.0},
        {"period": "2026-03-31", "value": 12300000000.0},
    ]
    assert sec_filing_metrics._compute_cagr(gapped) is None

    consecutive = [
        {"period": "2024-03-31", "value": 100.0},
        {"period": "2025-03-31", "value": 110.0},
        {"period": "2026-03-31", "value": 121.0},
    ]
    assert sec_filing_metrics._compute_cagr(consecutive) == pytest.approx(0.10, abs=1e-6)


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


def test_get_sec_filing_metrics_ignores_snapshots_from_older_extractor_versions(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(sec_filing_metrics, "DB_PATH", db_path)
    monkeypatch.setattr(sec_filing_metrics, "get_cik", lambda ticker: "0000789019")

    # Poisoned snapshot written by the pre-fix extractor (2010 revenue mixed with
    # 2024-25 EBIT), stamped with the legacy metric_source.
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.execute(
        """
        INSERT INTO sec_filing_metrics_snapshot (
            ticker, cik, as_of_date, source_filing_date, source_form,
            revenue_cagr_3y, revenue_series_json, ebit_series_json, metric_source, pulled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "MSFT", "0000789019", "2010-06-30", "2010-06-30", "10-K",
            0.0516,
            '[{"period":"2010-06-30","value":62484000000.0}]',
            '[{"period":"2025-06-30","value":128528000000.0}]',
            "sec_xbrl_companyfacts",
            "2026-07-05T22:16:48+00:00",
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        sec_filing_metrics,
        "_extract_annual_series",
        _make_extract_annual_series(
            revenues=[("2023-06-30", 211.9), ("2024-06-30", 245.1), ("2025-06-30", 281.7)],
        ),
    )

    metrics = sec_filing_metrics.get_sec_filing_metrics("MSFT")

    assert metrics is not None
    assert metrics.source_filing_date == "2025-06-30"
    assert metrics.metric_source == sec_filing_metrics._METRIC_SOURCE
    assert [item["period"] for item in metrics.revenue_series] == [
        "2023-06-30", "2024-06-30", "2025-06-30",
    ]

    # The recomputed snapshot is served from cache on the next call.
    cached = sec_filing_metrics.get_sec_filing_metrics("MSFT")
    assert cached is not None
    assert cached.source_filing_date == "2025-06-30"


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
