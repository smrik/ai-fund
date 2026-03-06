"""CIQ workbook parser for IBM Standard template (v1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


PARSER_VERSION = "ibm_standard_v1"
REQUIRED_SHEETS = [
    "Financial Statements",
    "Common Size",
    "Detailed Comps",
    "Summary Comps",
]


class CIQTemplateContractError(ValueError):
    """Raised when workbook layout does not match IBM_Standard v1 contract."""


@dataclass(slots=True)
class CIQWorkbookPayload:
    ticker: str
    source_file: str
    file_hash: str
    parser_version: str
    template_fingerprint: str
    long_form_records: list[dict[str, Any]]
    valuation_snapshot: dict[str, Any]
    comps_snapshot: list[dict[str, Any]]
    rows_parsed: int


_METRIC_MAP = {
    "Revenues": "revenue",
    "Total Revenues": "revenue",
    "Operating Income": "operating_income",
    "Capital Expenditure": "capex",
    "Depreciation & Amort.": "da",
    "Income Tax Expense": "income_tax_expense",
    "EBT Excl Unusual Items": "ebt_excl_unusual",
    "Total Debt": "total_debt",
    "Cash and Equivalents": "cash_and_equivalents",
    "Cash & Equivalents": "cash_and_equivalents",
    "Weighted Avg. Diluted Shares Out.": "shares_diluted",
    "ROIC": "roic",
    "FCF Yield": "fcf_yield",
    "Total Debt/": "debt_to_ebitda",
}


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"NM", "N/A", "--", "-", "na", "n/m"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_ticker(raw: str) -> str:
    if not raw:
        return ""
    text = raw.strip()
    if ":" in text:
        return text.split(":", 1)[1].strip().upper()
    return text.upper()


def _metric_key(label: str) -> str | None:
    if not label:
        return None
    if label in _METRIC_MAP:
        return _METRIC_MAP[label]
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return slug or None


def _percent_to_decimal(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1.5:
        return value / 100.0
    return value


def _default_unit_scale(sheet: str, section: str) -> tuple[str | None, float]:
    combined = f"{sheet} {section}".lower()
    if "usd in millions" in combined:
        return "USD", 1_000_000.0
    if "percentage" in combined or "margin" in combined or "cagr" in combined:
        return "%", 0.01
    if "multiple" in combined or "/" in combined:
        return "x", 1.0
    return None, 1.0


def _period_columns(ws: Worksheet) -> tuple[int, list[tuple[int, str]], dict[int, str | None]]:
    period_row = None
    for r in range(1, min(ws.max_row, 250) + 1):
        if _safe_str(ws.cell(r, 1).value) == "Period Date":
            period_row = r
            break

    if period_row is None:
        raise CIQTemplateContractError(f"{ws.title}: missing 'Period Date' header row")

    period_cols: list[tuple[int, str]] = []
    for c in range(4, min(ws.max_column, 80) + 1):
        value = ws.cell(period_row, c).value
        if isinstance(value, datetime):
            period_cols.append((c, value.date().isoformat()))
        elif isinstance(value, date):
            period_cols.append((c, value.isoformat()))
        elif value in (None, ""):
            if c > 8:
                break
        else:
            text = _safe_str(value)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                period_cols.append((c, text))

    if not period_cols:
        raise CIQTemplateContractError(f"{ws.title}: no period columns detected")

    calc_types: dict[int, str | None] = {}
    calc_row = period_row + 1
    if _safe_str(ws.cell(calc_row, 1).value) == "Calculation Type":
        for c, _ in period_cols:
            calc_val = _safe_str(ws.cell(calc_row, c).value)
            calc_types[c] = calc_val or None
    else:
        for c, _ in period_cols:
            calc_types[c] = None

    return period_row, period_cols, calc_types


def _parse_time_series_sheet(
    ws: Worksheet,
    ticker: str,
    source_file: str,
) -> list[dict[str, Any]]:
    period_row, period_cols, calc_types = _period_columns(ws)
    records: list[dict[str, Any]] = []

    section = "Uncategorized"
    for r in range(period_row + 1, ws.max_row + 1):
        label = _safe_str(ws.cell(r, 1).value)
        if not label:
            continue
        if label.startswith("Source:") or label.startswith("Copyright"):
            continue

        values = [ws.cell(r, c).value for c, _ in period_cols]
        has_values = any(v not in (None, "") for v in values)

        if not has_values:
            section = label
            continue

        unit, scale = _default_unit_scale(ws.title, section)
        row_metric_key = _metric_key(label)
        for c, period_date in period_cols:
            raw_value = ws.cell(r, c).value
            if raw_value in (None, ""):
                continue
            value_num = _to_num(raw_value)
            records.append(
                {
                    "ticker": ticker,
                    "sheet_name": ws.title,
                    "section_name": section,
                    "row_label": label,
                    "metric_key": row_metric_key,
                    "period_date": period_date,
                    "calc_type": calc_types.get(c),
                    "column_label": period_date,
                    "column_index": c,
                    "value_raw": str(raw_value),
                    "value_num": value_num,
                    "unit": unit,
                    "scale_factor": scale,
                    "source_file": source_file,
                }
            )

    return records


def _parse_comps_sheet(
    ws: Worksheet,
    target_ticker: str,
    source_file: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    comps_rows: list[dict[str, Any]] = []

    section = "Comps"
    headers: dict[int, str] = {}

    for r in range(1, ws.max_row + 1):
        c1 = _safe_str(ws.cell(r, 1).value)
        c3 = _safe_str(ws.cell(r, 3).value)

        if c3 in {
            "Trading Data and Size",
            "Leverage and Trading Multiples",
            "Operating Statistics",
        }:
            section = c3

        if c1 == "Ticker":
            headers = {}
            for c in range(1, min(ws.max_column, 80) + 1):
                h = _safe_str(ws.cell(r, c).value)
                if h:
                    headers[c] = h
            continue

        if not c1:
            continue
        if c1.startswith("Source:") or c1.startswith("Copyright"):
            continue

        row_ticker = _normalize_ticker(c1)
        row_name = c3

        for c in range(2, min(ws.max_column, 80) + 1):
            raw_value = ws.cell(r, c).value
            if raw_value in (None, ""):
                continue
            header = headers.get(c) or f"col_{c}"
            value_num = _to_num(raw_value)
            metric_label = header
            metric_key = _metric_key(metric_label)

            records.append(
                {
                    "ticker": target_ticker,
                    "sheet_name": ws.title,
                    "section_name": section,
                    "row_label": c1,
                    "metric_key": metric_key,
                    "period_date": None,
                    "calc_type": None,
                    "column_label": metric_label,
                    "column_index": c,
                    "value_raw": str(raw_value),
                    "value_num": value_num,
                    "unit": None,
                    "scale_factor": 1.0,
                    "source_file": source_file,
                }
            )

            if row_ticker and value_num is not None:
                comps_rows.append(
                    {
                        "target_ticker": target_ticker,
                        "peer_ticker": row_ticker,
                        "source_sheet": ws.title,
                        "peer_name": row_name,
                        "section_name": section,
                        "metric_key": metric_key,
                        "metric_label": metric_label,
                        "value_raw": str(raw_value),
                        "value_num": value_num,
                        "unit": None,
                        "is_target": 1 if row_ticker == target_ticker else 0,
                        "source_file": source_file,
                    }
                )

    return records, comps_rows


def _series(records: list[dict[str, Any]], keys: set[str]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for row in records:
        mk = row.get("metric_key")
        pd = row.get("period_date")
        val = row.get("value_num")
        if mk in keys and pd and val is not None:
            out.append((pd, float(val)))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _latest_value(records: list[dict[str, Any]], keys: set[str]) -> float | None:
    series = _series(records, keys)
    return series[0][1] if series else None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _build_valuation_snapshot(
    ticker: str,
    source_file: str,
    long_records: list[dict[str, Any]],
) -> dict[str, Any]:
    revenue = _series(long_records, {"revenue"})
    operating_income = _series(long_records, {"operating_income"})
    capex = _series(long_records, {"capex"})
    da = _series(long_records, {"da"})
    tax_exp = _series(long_records, {"income_tax_expense"})
    ebt = _series(long_records, {"ebt_excl_unusual"})

    revenue_vals = [v for _, v in revenue[:4]]
    op_vals = [v for _, v in operating_income[:4]]
    capex_vals = [abs(v) for _, v in capex[:4]]
    da_vals = [abs(v) for _, v in da[:4]]

    op_margins = [
        op_vals[i] / revenue_vals[i]
        for i in range(min(len(op_vals), len(revenue_vals)))
        if revenue_vals[i] not in (0, None)
    ]
    capex_pct = [
        capex_vals[i] / revenue_vals[i]
        for i in range(min(len(capex_vals), len(revenue_vals)))
        if revenue_vals[i] not in (0, None)
    ]
    da_pct = [
        da_vals[i] / revenue_vals[i]
        for i in range(min(len(da_vals), len(revenue_vals)))
        if revenue_vals[i] not in (0, None)
    ]

    tax_rates = []
    for i in range(min(len(tax_exp), len(ebt))):
        _, t = tax_exp[i]
        _, p = ebt[i]
        if p > 0:
            tax_rates.append(abs(t) / p)

    revenue_cagr = None
    if len(revenue_vals) >= 2 and revenue_vals[-1] > 0:
        years = len(revenue_vals) - 1
        revenue_cagr = (revenue_vals[0] / revenue_vals[-1]) ** (1 / years) - 1

    roic = _percent_to_decimal(_latest_value(long_records, {"roic"}))
    fcf_yield = _percent_to_decimal(_latest_value(long_records, {"fcf_yield"}))
    debt_to_ebitda = _latest_value(long_records, {"debt_to_ebitda"})

    as_of_date = revenue[0][0] if revenue else None

    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "source_file": source_file,
        "revenue_mm": revenue_vals[0] if revenue_vals else None,
        "operating_income_mm": op_vals[0] if op_vals else None,
        "capex_mm": capex_vals[0] if capex_vals else None,
        "da_mm": da_vals[0] if da_vals else None,
        "total_debt_mm": _latest_value(long_records, {"total_debt"}),
        "cash_mm": _latest_value(long_records, {"cash_and_equivalents"}),
        "shares_out_mm": _latest_value(long_records, {"shares_diluted"}),
        "ebit_margin": op_margins[0] if op_margins else None,
        "op_margin_avg_3yr": _avg(op_margins[:3]),
        "capex_pct_avg_3yr": _avg(capex_pct[:3]),
        "da_pct_avg_3yr": _avg(da_pct[:3]),
        "effective_tax_rate": _avg(tax_rates),
        "effective_tax_rate_avg": _avg(tax_rates),
        "revenue_cagr_3yr": revenue_cagr,
        "roic": roic,
        "fcf_yield": fcf_yield,
        "debt_to_ebitda": debt_to_ebitda,
    }


def _workbook_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_contract(wb) -> dict[str, Any]:
    missing = [sheet for sheet in REQUIRED_SHEETS if sheet not in wb.sheetnames]
    if missing:
        raise CIQTemplateContractError(f"Missing required sheets: {missing}")

    anchors = {
        "Financial Statements": [
            (1, 1, "Select Language"),
            (2, 1, "Ticker"),
            (9, 1, "INCOME STATEMENT"),
        ],
        "Detailed Comps": [
            (1, 1, "COMPARABLE COMPANY ANALYSIS"),
        ],
        "Summary Comps": [
            (1, 1, "COMPARABLE COMPANY ANALYSIS"),
        ],
    }

    for sheet_name, checks in anchors.items():
        ws = wb[sheet_name]
        for row, col, needle in checks:
            value = _safe_str(ws.cell(row, col).value)
            if needle.lower() not in value.lower():
                raise CIQTemplateContractError(
                    f"{sheet_name}!{row},{col} expected to contain '{needle}', got '{value}'"
                )

    fp = {
        "sheets": wb.sheetnames,
        "anchors": {
            sheet: [
                {
                    "row": row,
                    "col": col,
                    "value": _safe_str(wb[sheet].cell(row, col).value),
                }
                for row, col, _ in checks
            ]
            for sheet, checks in anchors.items()
        },
    }
    return fp


def parse_ciq_workbook(path: str | Path) -> CIQWorkbookPayload:
    """Parse a CIQ workbook into long-form records + deterministic snapshots."""
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(workbook_path)

    file_hash = _workbook_hash(workbook_path)
    wb = load_workbook(workbook_path, data_only=True, read_only=True)

    fingerprint = _validate_contract(wb)

    fs = wb["Financial Statements"]
    raw_ticker = _safe_str(fs.cell(2, 3).value)
    ticker = _normalize_ticker(raw_ticker)
    if not ticker:
        raise CIQTemplateContractError("Could not resolve ticker from Financial Statements!C2")

    long_records: list[dict[str, Any]] = []
    long_records.extend(_parse_time_series_sheet(wb["Financial Statements"], ticker, workbook_path.name))
    long_records.extend(_parse_time_series_sheet(wb["Common Size"], ticker, workbook_path.name))

    detailed_records, detailed_comps = _parse_comps_sheet(wb["Detailed Comps"], ticker, workbook_path.name)
    summary_records, summary_comps = _parse_comps_sheet(wb["Summary Comps"], ticker, workbook_path.name)
    long_records.extend(detailed_records)
    long_records.extend(summary_records)

    valuation_snapshot = _build_valuation_snapshot(ticker, workbook_path.name, long_records)
    comps_snapshot = detailed_comps + summary_comps

    return CIQWorkbookPayload(
        ticker=ticker,
        source_file=workbook_path.name,
        file_hash=file_hash,
        parser_version=PARSER_VERSION,
        template_fingerprint=json.dumps(fingerprint, sort_keys=True),
        long_form_records=long_records,
        valuation_snapshot=valuation_snapshot,
        comps_snapshot=comps_snapshot,
        rows_parsed=len(long_records),
    )
