"""Validation gate for the canonical Step 1 database boundary."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import sqlite3

from src.stage_00_data.unit_contract import (
    CanonicalUnit,
    UnitContractError,
    normalize_source_value,
)


_REQUIRED_CIQ_SNAPSHOT_UNITS: dict[str, CanonicalUnit] = {
    "revenue": CanonicalUnit.USD,
    "operating_income": CanonicalUnit.USD,
    "capex": CanonicalUnit.USD,
    "da": CanonicalUnit.USD,
    "total_debt": CanonicalUnit.USD,
    "cash": CanonicalUnit.USD,
    "diluted_shares": CanonicalUnit.SHARES,
    "ebit_margin": CanonicalUnit.DECIMAL,
    "op_margin_avg_3yr": CanonicalUnit.DECIMAL,
    "capex_pct_avg_3yr": CanonicalUnit.DECIMAL,
    "da_pct_avg_3yr": CanonicalUnit.DECIMAL,
    "effective_tax_rate": CanonicalUnit.DECIMAL,
    "effective_tax_rate_avg": CanonicalUnit.DECIMAL,
    "revenue_cagr_3yr": CanonicalUnit.DECIMAL,
}


@dataclass(frozen=True, slots=True)
class UnitContractValidation:
    status: str
    ticker: str
    latest_ciq_run_id: int | None
    financial_as_of_date: str | None
    facts_checked: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanonicalBackfillSummary:
    ticker: str
    ciq_valuation_facts: int
    ciq_comps_facts: int
    statement_facts: int
    market_cache_facts: int
    macro_facts: int
    sec_filing_facts: int

    @property
    def total_facts(self) -> int:
        return (
            self.ciq_valuation_facts
            + self.ciq_comps_facts
            + self.statement_facts
            + self.market_cache_facts
            + self.macro_facts
            + self.sec_filing_facts
        )


def backfill_canonical_database(
    database: sqlite3.Connection | str | Path,
    ticker: str,
) -> CanonicalBackfillSummary:
    """Idempotently project legacy raw rows into the canonical Step 1 table."""
    from db.loader import upsert_canonical_valuation_facts
    from db.schema import create_tables
    from src.stage_00_data.ciq_unit_mapping import (
        canonicalize_ciq_comps_snapshot,
        canonicalize_ciq_valuation_snapshot,
        ciq_comps_unit_spec,
    )
    from src.stage_00_data.source_unit_mapping import (
        canonicalize_macro_observation,
        canonicalize_market_cache,
        canonicalize_sec_filing_metrics_snapshot,
        canonicalize_statement_facts,
    )

    normalized_ticker = str(ticker or "").strip().upper()
    close_connection = not isinstance(database, sqlite3.Connection)
    conn = (
        sqlite3.connect(str(database))
        if close_connection
        else database
    )
    conn.row_factory = sqlite3.Row
    try:
        create_tables(conn)

        ciq_valuation_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ciq_valuation_snapshot WHERE ticker = ?",
                (normalized_ticker,),
            ).fetchall()
        ]
        ciq_valuation_facts = [
            fact
            for row in ciq_valuation_rows
            for fact in canonicalize_ciq_valuation_snapshot(row)
        ]

        legacy_comps_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM ciq_comps_snapshot
                WHERE target_ticker = ? AND value_num IS NOT NULL
                """,
                (normalized_ticker,),
            ).fetchall()
        ]
        typed_comps_rows: list[dict[str, object]] = []
        for row in legacy_comps_rows:
            spec = ciq_comps_unit_spec(str(row.get("metric_key") or ""))
            row["unit"] = spec.raw_unit
            row["scale_factor"] = spec.raw_scale
            typed_comps_rows.append(row)
        ciq_comps_facts = canonicalize_ciq_comps_snapshot(typed_comps_rows)

        raw_statement_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM statement_facts
                WHERE ticker = ? AND numeric_value IS NOT NULL
                """,
                (normalized_ticker,),
            ).fetchall()
        ]
        statement_facts = canonicalize_statement_facts(raw_statement_rows)

        market_cache_facts: list[dict[str, object]] = []
        for row in conn.execute(
            """
            SELECT data_type, data_json, fetched_at
            FROM market_data_cache
            WHERE ticker = ?
            """,
            (normalized_ticker,),
        ).fetchall():
            market_cache_facts.extend(
                canonicalize_market_cache(
                    ticker=normalized_ticker,
                    data_type=str(row["data_type"]),
                    data=json.loads(row["data_json"]),
                    fetched_at=str(row["fetched_at"]),
                )
            )

        macro_facts = [
            canonicalize_macro_observation(
                series_id=str(row["series_id"]),
                series_date=str(row["series_date"]),
                value=float(row["value"]),
                fetched_at=str(row["fetched_at"]),
            )
            for row in conn.execute(
                "SELECT * FROM macro_series WHERE value IS NOT NULL"
            ).fetchall()
        ]

        sec_filing_facts = [
            fact
            for row in conn.execute(
                "SELECT * FROM sec_filing_metrics_snapshot WHERE ticker = ?",
                (normalized_ticker,),
            ).fetchall()
            for fact in canonicalize_sec_filing_metrics_snapshot(dict(row))
        ]

        all_facts = [
            *ciq_valuation_facts,
            *ciq_comps_facts,
            *statement_facts,
            *market_cache_facts,
            *macro_facts,
            *sec_filing_facts,
        ]
        upsert_canonical_valuation_facts(conn, all_facts)
        return CanonicalBackfillSummary(
            ticker=normalized_ticker,
            ciq_valuation_facts=len(ciq_valuation_facts),
            ciq_comps_facts=len(ciq_comps_facts),
            statement_facts=len(statement_facts),
            market_cache_facts=len(market_cache_facts),
            macro_facts=len(macro_facts),
            sec_filing_facts=len(sec_filing_facts),
        )
    finally:
        if close_connection:
            conn.close()


def validate_canonical_database(
    database: sqlite3.Connection | str | Path,
    ticker: str,
) -> UnitContractValidation:
    """Validate the latest completed ticker snapshot at the Step 1 boundary."""
    normalized_ticker = str(ticker or "").strip().upper()
    close_connection = not isinstance(database, sqlite3.Connection)
    conn = (
        sqlite3.connect(str(database))
        if close_connection
        else database
    )
    conn.row_factory = sqlite3.Row
    errors: list[str] = []
    run_id: int | None = None
    as_of_date: str | None = None
    facts_checked = 0
    try:
        table = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'canonical_valuation_facts'
            """
        ).fetchone()
        if table is None:
            errors.append("canonical.table_missing")
            return UnitContractValidation(
                status="fail",
                ticker=normalized_ticker,
                latest_ciq_run_id=None,
                financial_as_of_date=None,
                facts_checked=0,
                errors=tuple(errors),
            )

        latest = conn.execute(
            """
            SELECT id, as_of_date
            FROM ciq_ingest_runs
            WHERE ticker = ? AND status = 'completed'
            ORDER BY as_of_date DESC, ingest_ts DESC, id DESC
            LIMIT 1
            """,
            (normalized_ticker,),
        ).fetchone()
        if latest is None:
            errors.append("canonical.completed_ciq_snapshot_missing")
        else:
            run_id = int(latest["id"])
            as_of_date = str(latest["as_of_date"] or "") or None

        rows: list[sqlite3.Row] = []
        if run_id is not None:
            rows = conn.execute(
                """
                SELECT *
                FROM canonical_valuation_facts
                WHERE ticker = ?
                  AND source = 'ciq_valuation_snapshot'
                  AND source_snapshot_id = ?
                """,
                (normalized_ticker, f"ciq:{run_id}"),
            ).fetchall()
        all_rows = conn.execute(
            """
            SELECT *
            FROM canonical_valuation_facts
            WHERE ticker IN (?, '__GLOBAL__')
            """,
            (normalized_ticker,),
        ).fetchall()
        facts_checked = len(all_rows)
        by_metric: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_metric.setdefault(str(row["metric_key"]), []).append(row)

        for metric_key, expected_unit in _REQUIRED_CIQ_SNAPSHOT_UNITS.items():
            metric_rows = by_metric.get(metric_key, [])
            if not metric_rows:
                errors.append(f"canonical.required_metric_missing:{metric_key}")
                continue
            if any(row["canonical_unit"] != expected_unit.value for row in metric_rows):
                errors.append(f"canonical.required_unit_mismatch:{metric_key}")

        for metric_key, metric_rows in by_metric.items():
            values = {float(row["canonical_value"]) for row in metric_rows}
            units = {str(row["canonical_unit"]) for row in metric_rows}
            if len(values) > 1 or len(units) > 1:
                errors.append(f"canonical.source_metric_conflict:{metric_key}")

        for row in all_rows:
            metric_key = str(row["metric_key"])
            canonical_value = float(row["canonical_value"])
            if not math.isfinite(canonical_value):
                errors.append(f"canonical.value_not_finite:{metric_key}")
                continue
            try:
                reproduced = normalize_source_value(
                    value=float(row["raw_value"]),
                    raw_unit=str(row["raw_unit"]),
                    raw_scale=float(row["raw_scale"]),
                    canonical_unit=CanonicalUnit(str(row["canonical_unit"])),
                    source_ref=str(row["source_ref"]),
                ).value
            except (UnitContractError, ValueError):
                errors.append(f"canonical.provenance_invalid:{metric_key}")
                continue
            if not math.isclose(
                reproduced,
                canonical_value,
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                errors.append(f"canonical.provenance_mismatch:{metric_key}")

        return UnitContractValidation(
            status="pass" if not errors else "fail",
            ticker=normalized_ticker,
            latest_ciq_run_id=run_id,
            financial_as_of_date=as_of_date,
            facts_checked=facts_checked,
            errors=tuple(sorted(set(errors))),
        )
    finally:
        if close_connection:
            conn.close()
