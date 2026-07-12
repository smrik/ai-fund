from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.stage_00_data.professional_model_evidence import (
    CORE_FIELD_KEYS,
    build_professional_model_evidence,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE ciq_ingest_runs (
            id INTEGER PRIMARY KEY,
            source_file TEXT,
            file_hash TEXT,
            ticker TEXT,
            parser_version TEXT,
            ingest_ts TEXT,
            status TEXT,
            as_of_date TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE ciq_source_facts_v2 (
            run_id INTEGER,
            ticker TEXT,
            sheet_name TEXT,
            row_index INTEGER,
            column_index INTEGER,
            row_label TEXT,
            metric_key TEXT,
            period_date TEXT,
            calc_type TEXT,
            column_label TEXT,
            cell_locator TEXT,
            value_raw TEXT,
            value_num REAL,
            unit TEXT,
            scale_factor REAL,
            source_file TEXT,
            formula_text TEXT,
            cached_value BLOB,
            has_formula INTEGER,
            has_cached_value INTEGER,
            formula_status TEXT,
            formula_error TEXT,
            cached_error TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO ciq_ingest_runs
        VALUES (3, 'MSFT_Standard.xlsx', ?, 'MSFT', 'ibm_standard_v4',
                '2026-07-11T22:48:25.391002Z', 'completed', '2026-03-31')
        """,
        ["a" * 64],
    )
    return conn


def _fact(
    conn: sqlite3.Connection,
    *,
    sheet: str,
    row: int,
    column: int,
    row_label: str,
    metric: str,
    cell: str,
    value: float,
    formula: str,
    period: str | None = None,
    calc_type: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO ciq_source_facts_v2 (
            run_id, ticker, sheet_name, row_index, column_index, row_label,
            metric_key, period_date, calc_type, column_label, cell_locator,
            value_raw, value_num, unit, scale_factor, source_file, formula_text,
            cached_value, has_formula, has_cached_value, formula_status,
            formula_error, cached_error
        ) VALUES (3, 'MSFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1.0,
                  'MSFT_Standard.xlsx', ?, ?, 1, 1, 'formula_cached', NULL, NULL)
        """,
        [
            sheet,
            row,
            column,
            row_label,
            metric,
            period,
            calc_type,
            metric,
            cell,
            str(value),
            value,
            formula,
            value,
        ],
    )


def _seed_msft_evidence(conn: sqlite3.Connection) -> None:
    market = (
        (5, "stock_price", "Detailed Comps!E10", 385.1, "IQ_LASTSALEPRICE"),
        (10, "shares_out", "Detailed Comps!J10", 7428.4347, "IQ_SHARESOUTSTANDING"),
        (11, "market_cap", "Detailed Comps!K10", 2860690.20297, "J10*E10"),
        (19, "total_revenue_cy_1", "Detailed Comps!S10", 354517.9778, "IQ_REVENUE_EST CY+1"),
        (20, "total_revenue_cy_2", "Detailed Comps!T10", 415081.783, "IQ_REVENUE_EST CY+2"),
        (23, "ebitda_cy_1", "Detailed Comps!W10", 217078.2784, "IQ_EBITDA_EST CY+1"),
        (24, "ebitda_cy_2", "Detailed Comps!X10", 266070.1343, "IQ_EBITDA_EST CY+2"),
        (27, "diluted_eps_cy_1", "Detailed Comps!AA10", 17.9186, "IQ_EPS_EST CY+1"),
        (28, "diluted_eps_cy_2", "Detailed Comps!AB10", 20.9536, "IQ_EPS_EST CY+2"),
    )
    for column, metric, cell, value, formula in market:
        _fact(
            conn,
            sheet="Detailed Comps",
            row=10,
            column=column,
            row_label="NASDAQ:MSFT",
            metric=metric,
            cell=cell,
            value=value,
            formula=f"={formula}(DateToday)",
        )

    statements = (
        (117, "interest_expense_incl_cap_interest", 2859.0),
        (127, "effective_tax_rate", 18.9556),
        (359, "finance_leases_current", 4063.0),
        (360, "finance_leases_long_term", 58869.0),
        (361, "total_finance_leases", 62932.0),
        (362, "current_portion_of_operating_lease_liabilities", 5535.0),
        (363, "long_term_portion_of_operating_lease_liabilities", 16703.0),
        (364, "total_operating_leases", 22238.0),
        (365, "total_leases", 85170.0),
        (369, "total_debt_excl_leases", 40262.0),
        (379, "debt", 125432.0),
    )
    for row, metric, value in statements:
        _fact(
            conn,
            sheet="Financial Statements",
            row=row,
            column=13,
            row_label=metric.replace("_", " ").title(),
            metric=metric,
            cell=f"Financial Statements!M{row}",
            value=value,
            formula=f"=CIQ({metric})",
            period="2026-03-31",
            calc_type="LTM",
        )
    conn.commit()


def test_builds_fail_closed_dated_evidence_without_selecting_wacc_methodology(tmp_path: Path) -> None:
    conn = _connection()
    _seed_msft_evidence(conn)
    config = tmp_path / "config.yaml"
    config.write_text(
        "wacc_params:\n  risk_free_rate: 0.045\n  equity_risk_premium: 0.050\n",
        encoding="utf-8",
    )

    packet = build_professional_model_evidence(
        conn,
        ticker="msft",
        run_id=3,
        valuation_date="2026-07-11",
        config_path=config,
    )
    repeated = build_professional_model_evidence(
        conn,
        ticker="MSFT",
        run_id=3,
        valuation_date="2026-07-11",
        config_path=config,
    )
    conn.close()

    assert packet["evidence_hash"] == repeated["evidence_hash"]
    assert len(packet["evidence_hash"]) == 64
    assert packet["source_run"]["target_comps_row"] == 10
    assert packet["source_run"]["financial_period_as_of"] == "2026-03-31"
    assert packet["source_run"]["market_and_consensus_timestamp"] is None

    fields = packet["fields"]
    price = fields["current_price"]
    assert price["status"] == "unavailable"
    assert price["reason_code"] == "source_timestamp_missing"
    assert price["value"] is None
    assert price["candidate_value"] == pytest.approx(385.1)
    assert price["source_locator"] == "MSFT_Standard.xlsx::Detailed Comps!E10"
    assert price["freshness"]["status"] == "unknown_source_as_of"
    assert price["observed_at"] == "2026-07-11T22:48:25.391002Z"

    assert fields["shares_outstanding"]["candidate_value"] == pytest.approx(7_428_434_700.0)
    assert fields["market_cap"]["candidate_value"] == pytest.approx(2_860_690_202_970.0)
    assert fields["total_debt"]["value"] == pytest.approx(125_432_000_000.0)
    assert fields["total_debt"]["freshness"]["age_days"] == 102
    assert fields["lease_liabilities"]["value"] == pytest.approx(85_170_000_000.0)
    assert fields["current_lease_liabilities"]["value"] == pytest.approx(9_598_000_000.0)
    assert fields["long_term_lease_liabilities"]["value"] == pytest.approx(75_572_000_000.0)
    assert fields["tax_rate"]["value"] == pytest.approx(0.189556)

    assert fields["cost_of_debt"]["status"] == "unavailable"
    assert fields["cost_of_debt"]["reason_code"] == "methodology_not_selected"
    assert fields["cost_of_debt_proxy_total_debt"]["value"] == pytest.approx(2859 / 125432)
    assert fields["cost_of_debt_proxy_borrowings_only"]["value"] == pytest.approx(2859 / 40262)
    assert packet["methodology_state"] == {
        "final_wacc_methodology_selected": False,
        "cost_of_debt_methodology_selected": False,
        "tax_rate_methodology_selected": False,
        "stale_threshold_selected": False,
    }

    assert fields["risk_free_rate"]["candidate_value"] == pytest.approx(0.045)
    assert fields["risk_free_rate"]["status"] == "unavailable"
    assert fields["risk_free_rate"]["reason_code"] == "source_as_of_missing"
    assert fields["equity_risk_premium"]["candidate_value"] == pytest.approx(0.05)
    assert fields["beta"]["reason_code"] == "source_evidence_absent"

    assert packet["consensus"]["status"] == "unavailable"
    assert packet["consensus"]["reason_code"] == "frozen_snapshot_timestamp_missing"
    assert packet["consensus"]["coverage"] == {
        "requested_count": 6,
        "candidate_count": 6,
        "usable_count": 0,
        "missing_count": 0,
    }
    assert all(item["normalized_period"] is None for item in packet["consensus"]["observations"])
    assert all(item["status"] == "unavailable" for item in packet["consensus"]["observations"])
    assert all(item["consensus_statistic"] == "unspecified" for item in packet["consensus"]["observations"])
    assert all(item["status"] == "tied" for item in packet["reconciliations"].values())


def test_absent_sources_remain_explicitly_unavailable() -> None:
    conn = _connection()
    packet = build_professional_model_evidence(
        conn,
        ticker="MSFT",
        run_id=3,
        valuation_date="2026-07-11",
    )
    conn.close()

    for field_key in CORE_FIELD_KEYS:
        assert field_key in packet["fields"]
        assert packet["fields"][field_key]["status"] == "unavailable"
        assert packet["fields"][field_key]["value"] is None
    assert packet["coverage"]["core_available_count"] == 0
    assert packet["coverage"]["core_unavailable_count"] == len(CORE_FIELD_KEYS)
    assert packet["consensus"]["reason_code"] == "consensus_evidence_absent"
    assert packet["consensus"]["coverage"]["missing_count"] == 6


def test_run_ticker_mismatch_is_rejected() -> None:
    conn = _connection()
    with pytest.raises(ValueError, match="belongs to MSFT"):
        build_professional_model_evidence(
            conn,
            ticker="ORCL",
            run_id=3,
            valuation_date="2026-07-11",
        )
    conn.close()


@pytest.mark.parametrize("status", ["started", "failed", ""])
def test_incomplete_run_is_rejected(status: str) -> None:
    conn = _connection()
    conn.execute("UPDATE ciq_ingest_runs SET status = ? WHERE id = 3", [status])
    conn.commit()

    with pytest.raises(ValueError, match=r"CIQ ingest run 3 is not completed"):
        build_professional_model_evidence(
            conn,
            ticker="MSFT",
            run_id=3,
            valuation_date="2026-07-11",
        )
    conn.close()
