"""Adapter for reading CIQ snapshots into compute-friendly deterministic fields."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from statistics import median
from typing import Any

from config import DB_PATH


_MM_FIELDS = {
    "revenue_mm": "revenue_ttm",
    "operating_income_mm": "operating_income_ttm",
    "capex_mm": "capex_ttm",
    "da_mm": "da_ttm",
    "total_debt_mm": "total_debt",
    "cash_mm": "cash",
    "shares_out_mm": "shares_outstanding",
}

_METRIC_ALIASES = {
    "peer_tev_ebitda_ltm": ("tev_ebitda_ltm", "tev_ebitda"),
    "peer_tev_ebit_ltm": ("tev_ebit_ltm", "tev_ebit"),
    "peer_pe_ltm": ("pe_ltm", "pe"),
    "peer_tev_ebitda_fwd": ("tev_ebitda_cy_1", "tev_ebitda_cy1"),
    "peer_tev_ebit_fwd": ("tev_ebit_cy_1", "tev_ebit_cy1"),
    "target_ebitda_ltm": ("ebitda_ltm", "ebitda_fy", "ebitda"),
    "target_ebit_ltm": ("ebit_ltm", "ebit_fy", "ebit"),
    "target_eps_ltm": ("diluted_eps_ltm", "eps_ltm", "diluted_eps_fy", "eps_fy"),
    "target_shares_out": ("shares_out", "shares_outstanding"),
    "target_total_debt": ("total_debt", "debt"),
    "target_cash": ("cash", "cash_and_equivalents"),
    "target_revenue_fy1": ("total_revenue_cy_1", "revenue_cy_1", "revenue_fy1"),
    "target_revenue_fy2": ("total_revenue_cy_2", "revenue_cy_2", "revenue_fy2"),
}

_LONG_FORM_DAY_ALIASES = {
    "dso": ("dso", "days_sales_outstanding"),
    "dio": ("dio", "days_inventory_outstanding", "days_inventory"),
    "dpo": ("dpo", "days_payables_outstanding", "days_payable_outstanding"),
    "accounts_receivable": ("accounts_receivable", "receivables", "trade_receivables", "net_receivables"),
    "inventory": ("inventory", "inventories"),
    "accounts_payable": ("accounts_payable", "trade_payables", "payables"),
    "revenue": ("revenue", "total_revenue", "revenues"),
}


def _connect() -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches_metric_alias(metric_key: str, aliases: tuple[str, ...]) -> bool:
    return any(metric_key == alias or metric_key.startswith(f"{alias}__") for alias in aliases)


def _extract_nwc_day_drivers(conn: sqlite3.Connection, ticker: str, run_id: int) -> dict[str, float | None]:
    out: dict[str, float | None] = {"dso": None, "dio": None, "dpo": None}

    try:
        rows = conn.execute(
            """
            SELECT metric_key, value_num, period_date, column_index
            FROM ciq_long_form
            WHERE run_id = ? AND ticker = ? AND value_num IS NOT NULL
            ORDER BY COALESCE(period_date, '') DESC, column_index DESC
            """,
            [run_id, ticker],
        ).fetchall()
    except sqlite3.OperationalError:
        return out

    latest: dict[str, float] = {}
    for row in rows:
        metric_key = str(row["metric_key"] or "")
        value = _to_float(row["value_num"])
        if not metric_key or value is None:
            continue

        for canonical, aliases in _LONG_FORM_DAY_ALIASES.items():
            if canonical in latest:
                continue
            if _matches_metric_alias(metric_key, aliases):
                latest[canonical] = value

    if "dso" in latest:
        out["dso"] = round(float(latest["dso"]), 1)
    if "dio" in latest:
        out["dio"] = round(float(latest["dio"]), 1)
    if "dpo" in latest:
        out["dpo"] = round(float(latest["dpo"]), 1)

    revenue = latest.get("revenue")
    if revenue and revenue > 0:
        if out["dso"] is None and "accounts_receivable" in latest:
            out["dso"] = round(365.0 * latest["accounts_receivable"] / revenue, 1)
        if out["dio"] is None and "inventory" in latest:
            out["dio"] = round(365.0 * latest["inventory"] / revenue, 1)
        if out["dpo"] is None and "accounts_payable" in latest:
            out["dpo"] = round(365.0 * latest["accounts_payable"] / revenue, 1)

    return out


def _extract_forward_revenue_from_comps(conn: sqlite3.Connection, ticker: str) -> dict[str, float | None]:
    """Query the latest comps snapshot for target company forward revenue estimates (FY1/FY2)."""
    out: dict[str, float | None] = {"revenue_fy1": None, "revenue_fy2": None}
    try:
        latest = conn.execute(
            """
            SELECT run_id FROM ciq_comps_snapshot
            WHERE target_ticker = ? AND is_target = 1
            ORDER BY as_of_date DESC, run_id DESC
            LIMIT 1
            """,
            [ticker],
        ).fetchone()
        if latest is None:
            return out
        run_id = int(latest["run_id"])

        rows = conn.execute(
            """
            SELECT metric_key, value_num FROM ciq_comps_snapshot
            WHERE target_ticker = ? AND run_id = ? AND is_target = 1 AND value_num IS NOT NULL
            """,
            [ticker, run_id],
        ).fetchall()

        for row in rows:
            metric_key = str(row["metric_key"] or "")
            value = _to_float(row["value_num"])
            if value is None:
                continue
            if out["revenue_fy1"] is None and _matches_metric_alias(metric_key, _METRIC_ALIASES["target_revenue_fy1"]):
                out["revenue_fy1"] = value * 1_000_000.0  # stored in millions
            if out["revenue_fy2"] is None and _matches_metric_alias(metric_key, _METRIC_ALIASES["target_revenue_fy2"]):
                out["revenue_fy2"] = value * 1_000_000.0
    except sqlite3.OperationalError:
        pass
    return out


def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    out: dict[str, Any] = {
        "ticker": data.get("ticker"),
        "as_of_date": data.get("as_of_date"),
        "run_id": data.get("run_id"),
        "source_file": data.get("source_file"),
        "ebit_margin": data.get("ebit_margin"),
        "op_margin_avg_3yr": data.get("op_margin_avg_3yr"),
        "capex_pct_avg_3yr": data.get("capex_pct_avg_3yr"),
        "da_pct_avg_3yr": data.get("da_pct_avg_3yr"),
        "effective_tax_rate": data.get("effective_tax_rate"),
        "effective_tax_rate_avg": data.get("effective_tax_rate_avg"),
        "revenue_cagr_3yr": data.get("revenue_cagr_3yr"),
        "debt_to_ebitda": data.get("debt_to_ebitda"),
        "roic": data.get("roic"),
        "fcf_yield": data.get("fcf_yield"),
        "dso": _to_float(data.get("dso")),
        "dio": _to_float(data.get("dio")),
        "dpo": _to_float(data.get("dpo")),
    }

    for mm_key, out_key in _MM_FIELDS.items():
        value = data.get(mm_key)
        out[out_key] = float(value) * 1_000_000.0 if value is not None else None

    return out


def get_ciq_nwc_history(ticker: str, as_of_date: str | None = None) -> list[dict[str, Any]]:
    """
    Return up to 3 annual periods of DSO/DIO/DPO from CIQ long_form data.

    Uses the same snapshot run as get_ciq_snapshot(). Returns a list of dicts
    ordered newest period first: [{period_date, dso, dio, dpo}, ...].
    Returns [] if no CIQ data exists.
    """
    conn = _connect()
    if conn is None:
        return []
    try:
        if as_of_date:
            row = conn.execute(
                "SELECT run_id FROM ciq_valuation_snapshot WHERE ticker = ? AND as_of_date = ? ORDER BY run_id DESC LIMIT 1",
                [ticker.upper(), as_of_date],
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT run_id FROM ciq_valuation_snapshot WHERE ticker = ? ORDER BY as_of_date DESC, run_id DESC LIMIT 1",
                [ticker.upper()],
            ).fetchone()
        if row is None:
            return []
        run_id = int(row["run_id"])

        rows = conn.execute(
            """
            SELECT metric_key, value_num, period_date, column_index
            FROM ciq_long_form
            WHERE run_id = ? AND ticker = ? AND value_num IS NOT NULL
            ORDER BY COALESCE(period_date, '') DESC, column_index DESC
            """,
            [run_id, ticker.upper()],
        ).fetchall()

        # Group by period_date; within each period take first (highest column_index) match per metric
        period_data: dict[str, dict[str, float]] = defaultdict(dict)
        for r in rows:
            period = str(r["period_date"] or "unknown")
            metric_key = str(r["metric_key"] or "")
            value = _to_float(r["value_num"])
            if value is None:
                continue
            pdata = period_data[period]
            for canonical, aliases in _LONG_FORM_DAY_ALIASES.items():
                if canonical in pdata:
                    continue
                if _matches_metric_alias(metric_key, aliases):
                    pdata[canonical] = value

        results: list[dict[str, Any]] = []
        for period in sorted(period_data.keys(), reverse=True)[:3]:
            metrics = period_data[period]
            entry: dict[str, Any] = {"period_date": period, "dso": None, "dio": None, "dpo": None}

            if "dso" in metrics:
                entry["dso"] = round(float(metrics["dso"]), 1)
            if "dio" in metrics:
                entry["dio"] = round(float(metrics["dio"]), 1)
            if "dpo" in metrics:
                entry["dpo"] = round(float(metrics["dpo"]), 1)

            revenue = metrics.get("revenue")
            if revenue and revenue > 0:
                if entry["dso"] is None and "accounts_receivable" in metrics:
                    entry["dso"] = round(365.0 * metrics["accounts_receivable"] / revenue, 1)
                if entry["dio"] is None and "inventory" in metrics:
                    entry["dio"] = round(365.0 * metrics["inventory"] / revenue, 1)
                if entry["dpo"] is None and "accounts_payable" in metrics:
                    entry["dpo"] = round(365.0 * metrics["accounts_payable"] / revenue, 1)

            if any(v is not None for v in [entry["dso"], entry["dio"], entry["dpo"]]):
                results.append(entry)

        return results
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_ciq_snapshot(ticker: str, as_of_date: str | None = None) -> dict[str, Any] | None:
    """
    Read CIQ valuation snapshot for a ticker.

    Stored CIQ amount fields are in USD millions. This adapter normalizes those
    values to absolute USD for compute-layer compatibility.
    """
    conn = _connect()
    if conn is None:
        return None

    try:
        if as_of_date:
            row = conn.execute(
                """
                SELECT * FROM ciq_valuation_snapshot
                WHERE ticker = ? AND as_of_date = ?
                LIMIT 1
                """,
                [ticker.upper(), as_of_date],
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM ciq_valuation_snapshot
                WHERE ticker = ?
                ORDER BY as_of_date DESC, run_id DESC
                LIMIT 1
                """,
                [ticker.upper()],
            ).fetchone()

        if row is None:
            return None

        snapshot = _row_to_snapshot(row)
        run_id = snapshot.get("run_id")
        if run_id is not None:
            long_form_days = _extract_nwc_day_drivers(conn, ticker.upper(), int(run_id))
            for key, value in long_form_days.items():
                if snapshot.get(key) is None and value is not None:
                    snapshot[key] = value
        fwd_rev = _extract_forward_revenue_from_comps(conn, ticker.upper())
        snapshot["revenue_fy1"] = fwd_rev["revenue_fy1"]
        snapshot["revenue_fy2"] = fwd_rev["revenue_fy2"]
        return snapshot
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _fetch_ciq_comps_rows(ticker: str, as_of_date: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        if as_of_date is None:
            latest = conn.execute(
                """
                SELECT as_of_date, run_id
                FROM ciq_comps_snapshot
                WHERE target_ticker = ?
                ORDER BY as_of_date DESC, run_id DESC
                LIMIT 1
                """,
                [ticker.upper()],
            ).fetchone()
            if latest is None:
                return []
            as_of_date = latest["as_of_date"]
            run_id = int(latest["run_id"])
        else:
            latest_run = conn.execute(
                """
                SELECT run_id
                FROM ciq_comps_snapshot
                WHERE target_ticker = ? AND as_of_date = ?
                ORDER BY run_id DESC
                LIMIT 1
                """,
                [ticker.upper(), as_of_date],
            ).fetchone()
            if latest_run is None:
                return []
            run_id = int(latest_run["run_id"])

        rows = conn.execute(
            """
            SELECT target_ticker, peer_ticker, as_of_date, run_id, source_file,
                   metric_key, value_num, is_target
            FROM ciq_comps_snapshot
            WHERE target_ticker = ? AND as_of_date = ? AND run_id = ?
            """,
            [ticker.upper(), as_of_date, run_id],
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _pick_metric(metrics: dict[str, float], aliases: tuple[str, ...]) -> float | None:
    for key in aliases:
        val = _to_float(metrics.get(key))
        if val is not None:
            return val
    return None


def _median(values: list[float]) -> float | None:
    cleaned = [float(v) for v in values if v is not None]
    if not cleaned:
        return None
    return float(median(cleaned))


def get_ciq_comps_valuation(ticker: str, as_of_date: str | None = None) -> dict[str, Any] | None:
    """
    Build deterministic comps valuation inputs from CIQ comps snapshot.

    Returns peer medians and implied price outputs that can be used as:
    - DCF exit multiple anchor (peer median TEV/EBITDA or TEV/EBIT)
    - Standalone comps valuation (EV/EBITDA, EV/EBIT and P/E implied prices)
    """
    rows = _fetch_ciq_comps_rows(ticker, as_of_date=as_of_date)
    if not rows:
        return None

    peer_data: dict[str, dict[str, Any]] = {}
    for row in rows:
        peer_ticker = str(row.get("peer_ticker") or "").upper()
        if not peer_ticker:
            continue
        bucket = peer_data.setdefault(
            peer_ticker,
            {
                "is_target": int(row.get("is_target") or 0),
                "metrics": {},
                "run_id": row.get("run_id"),
                "source_file": row.get("source_file"),
                "as_of_date": row.get("as_of_date"),
            },
        )
        metric_key = row.get("metric_key")
        value_num = _to_float(row.get("value_num"))
        if metric_key and value_num is not None:
            bucket["metrics"][str(metric_key)] = value_num
        if int(row.get("is_target") or 0) == 1:
            bucket["is_target"] = 1

    target_ticker = ticker.upper()
    target = None
    for pt, bucket in peer_data.items():
        if bucket["is_target"] == 1 or pt == target_ticker:
            target = bucket
            break
    if target is None:
        return None

    peers = [bucket for pt, bucket in peer_data.items() if pt != target_ticker and bucket["is_target"] == 0]
    if not peers:
        return None

    peer_tev_ebitda = []
    peer_tev_ebit = []
    peer_pe = []
    peer_tev_ebitda_fwd = []
    peer_tev_ebit_fwd = []
    for peer in peers:
        tev_ebitda = _pick_metric(peer["metrics"], _METRIC_ALIASES["peer_tev_ebitda_ltm"])
        tev_ebit = _pick_metric(peer["metrics"], _METRIC_ALIASES["peer_tev_ebit_ltm"])
        pe = _pick_metric(peer["metrics"], _METRIC_ALIASES["peer_pe_ltm"])
        tev_ebitda_fwd = _pick_metric(peer["metrics"], _METRIC_ALIASES["peer_tev_ebitda_fwd"])
        tev_ebit_fwd = _pick_metric(peer["metrics"], _METRIC_ALIASES["peer_tev_ebit_fwd"])
        if tev_ebitda is not None and 0 < tev_ebitda < 100:
            peer_tev_ebitda.append(tev_ebitda)
        if tev_ebit is not None and 0 < tev_ebit < 100:
            peer_tev_ebit.append(tev_ebit)
        if pe is not None and 0 < pe < 150:
            peer_pe.append(pe)
        if tev_ebitda_fwd is not None and 0 < tev_ebitda_fwd < 100:
            peer_tev_ebitda_fwd.append(tev_ebitda_fwd)
        if tev_ebit_fwd is not None and 0 < tev_ebit_fwd < 100:
            peer_tev_ebit_fwd.append(tev_ebit_fwd)

    peer_median_tev_ebitda = _median(peer_tev_ebitda)
    peer_median_tev_ebit = _median(peer_tev_ebit)
    peer_median_pe = _median(peer_pe)
    peer_median_tev_ebitda_fwd = _median(peer_tev_ebitda_fwd)
    peer_median_tev_ebit_fwd = _median(peer_tev_ebit_fwd)

    target_metrics = target["metrics"]
    target_ebitda = _pick_metric(target_metrics, _METRIC_ALIASES["target_ebitda_ltm"])
    target_ebit = _pick_metric(target_metrics, _METRIC_ALIASES["target_ebit_ltm"])
    target_eps = _pick_metric(target_metrics, _METRIC_ALIASES["target_eps_ltm"])
    target_shares = _pick_metric(target_metrics, _METRIC_ALIASES["target_shares_out"])
    target_total_debt = _pick_metric(target_metrics, _METRIC_ALIASES["target_total_debt"]) or 0.0
    target_cash = _pick_metric(target_metrics, _METRIC_ALIASES["target_cash"]) or 0.0
    target_net_debt = target_total_debt - target_cash

    implied_price_ev_ebitda = None
    if peer_median_tev_ebitda is not None and target_ebitda is not None and target_shares and target_shares > 0:
        implied_ev = peer_median_tev_ebitda * target_ebitda
        implied_equity = implied_ev - target_net_debt
        implied_price_ev_ebitda = implied_equity / target_shares

    implied_price_ev_ebit = None
    if peer_median_tev_ebit is not None and target_ebit is not None and target_shares and target_shares > 0:
        implied_ev = peer_median_tev_ebit * target_ebit
        implied_equity = implied_ev - target_net_debt
        implied_price_ev_ebit = implied_equity / target_shares

    implied_price_pe = None
    if peer_median_pe is not None and target_eps is not None and target_eps > 0:
        implied_price_pe = peer_median_pe * target_eps

    comps_prices = [p for p in [implied_price_ev_ebitda, implied_price_ev_ebit, implied_price_pe] if p is not None]
    implied_price_base = sum(comps_prices) / len(comps_prices) if comps_prices else None

    return {
        "ticker": target_ticker,
        "as_of_date": target.get("as_of_date"),
        "run_id": target.get("run_id"),
        "source_file": target.get("source_file"),
        "peer_count": len(peers),
        "peer_median_tev_ebitda_ltm": round(peer_median_tev_ebitda, 4) if peer_median_tev_ebitda is not None else None,
        "peer_median_tev_ebit_ltm": round(peer_median_tev_ebit, 4) if peer_median_tev_ebit is not None else None,
        "peer_median_pe_ltm": round(peer_median_pe, 4) if peer_median_pe is not None else None,
        "peer_median_tev_ebitda_fwd": round(peer_median_tev_ebitda_fwd, 4) if peer_median_tev_ebitda_fwd is not None else None,
        "peer_median_tev_ebit_fwd": round(peer_median_tev_ebit_fwd, 4) if peer_median_tev_ebit_fwd is not None else None,
        "target_ebitda_ltm": target_ebitda,
        "target_ebit_ltm": target_ebit,
        "target_eps_ltm": target_eps,
        "target_shares_out": target_shares,
        "target_net_debt": target_net_debt,
        "implied_price_ev_ebitda": round(implied_price_ev_ebitda, 4) if implied_price_ev_ebitda is not None else None,
        "implied_price_ev_ebit": round(implied_price_ev_ebit, 4) if implied_price_ev_ebit is not None else None,
        "implied_price_pe": round(implied_price_pe, 4) if implied_price_pe is not None else None,
        "implied_price_base": round(implied_price_base, 4) if implied_price_base is not None else None,
    }


def get_ciq_comps_detail(ticker: str, as_of_date: str | None = None) -> dict | None:
    """Return target + per-peer metrics for the comps table.

    Returns:
        {
          "target": {"ticker", "market_cap_mm", "tev_mm", "revenue_ltm_mm",
                     "ebitda_ltm_mm", "ebit_ltm_mm", "eps_ltm",
                     "tev_ebitda_ltm", "tev_ebitda_fwd",
                     "tev_ebit_ltm", "tev_ebit_fwd", "pe_ltm"},
          "peers":  [same schema per peer, ...],
          "medians": {"tev_ebitda_ltm", "tev_ebitda_fwd",
                      "tev_ebit_ltm", "tev_ebit_fwd", "pe_ltm"}
        }
    Returns None if no CIQ comps data exists for the ticker.
    """
    rows = _fetch_ciq_comps_rows(ticker, as_of_date=as_of_date)
    if not rows:
        return None

    # ── Reuse peer_data grouping from get_ciq_comps_valuation() ─────────────
    peer_data: dict[str, dict[str, Any]] = {}
    for row in rows:
        peer_ticker = str(row.get("peer_ticker") or "").upper()
        if not peer_ticker:
            continue
        bucket = peer_data.setdefault(
            peer_ticker,
            {
                "is_target": int(row.get("is_target") or 0),
                "metrics": {},
                "run_id": row.get("run_id"),
                "source_file": row.get("source_file"),
                "as_of_date": row.get("as_of_date"),
            },
        )
        metric_key = row.get("metric_key")
        value_num = _to_float(row.get("value_num"))
        if metric_key and value_num is not None:
            bucket["metrics"][str(metric_key)] = value_num
        if int(row.get("is_target") or 0) == 1:
            bucket["is_target"] = 1

    target_ticker = ticker.upper()
    target_bucket = None
    for pt, bucket in peer_data.items():
        if bucket["is_target"] == 1 or pt == target_ticker:
            target_bucket = bucket
            break
    if target_bucket is None:
        return None

    peer_buckets = [
        (pt, b) for pt, b in peer_data.items()
        if pt != target_ticker and b["is_target"] == 0
    ]

    _EXTRA_MM_ALIASES: dict[str, tuple[str, ...]] = {
        "market_cap_mm": ("market_cap", "market_capitalization", "mktcap"),
        "tev_mm": ("tev", "enterprise_value", "total_enterprise_value"),
        "revenue_ltm_mm": ("total_revenue_ltm", "revenue_ltm", "total_revenue", "revenue_ttm"),
    }

    def _build_row(ticker_str: str, m: dict) -> dict:
        out: dict[str, Any] = {"ticker": ticker_str}
        for field, aliases in _EXTRA_MM_ALIASES.items():
            out[field] = next((_to_float(m.get(a)) for a in aliases if m.get(a) is not None), None)
        out["ebitda_ltm_mm"] = _pick_metric(m, _METRIC_ALIASES["target_ebitda_ltm"])
        out["ebit_ltm_mm"] = _pick_metric(m, _METRIC_ALIASES["target_ebit_ltm"])
        out["eps_ltm"] = _pick_metric(m, _METRIC_ALIASES["target_eps_ltm"])
        out["tev_ebitda_ltm"] = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebitda_ltm"])
        out["tev_ebitda_fwd"] = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebitda_fwd"])
        out["tev_ebit_ltm"] = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebit_ltm"])
        out["tev_ebit_fwd"] = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebit_fwd"])
        out["pe_ltm"] = _pick_metric(m, _METRIC_ALIASES["peer_pe_ltm"])
        return out

    peer_rows: list[dict] = []
    peer_tev_ebitda: list[float] = []
    peer_tev_ebitda_fwd: list[float] = []
    peer_tev_ebit: list[float] = []
    peer_tev_ebit_fwd: list[float] = []
    peer_pe: list[float] = []

    for pt, bucket in peer_buckets:
        m = bucket["metrics"]
        peer_rows.append(_build_row(pt, m))
        tev_ebitda = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebitda_ltm"])
        tev_ebitda_fwd_v = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebitda_fwd"])
        tev_ebit = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebit_ltm"])
        tev_ebit_fwd_v = _pick_metric(m, _METRIC_ALIASES["peer_tev_ebit_fwd"])
        pe = _pick_metric(m, _METRIC_ALIASES["peer_pe_ltm"])
        if tev_ebitda is not None and 0 < tev_ebitda < 100:
            peer_tev_ebitda.append(tev_ebitda)
        if tev_ebitda_fwd_v is not None and 0 < tev_ebitda_fwd_v < 100:
            peer_tev_ebitda_fwd.append(tev_ebitda_fwd_v)
        if tev_ebit is not None and 0 < tev_ebit < 100:
            peer_tev_ebit.append(tev_ebit)
        if tev_ebit_fwd_v is not None and 0 < tev_ebit_fwd_v < 100:
            peer_tev_ebit_fwd.append(tev_ebit_fwd_v)
        if pe is not None and 0 < pe < 150:
            peer_pe.append(pe)

    def _rnd(v: float | None) -> float | None:
        return round(v, 4) if v is not None else None

    return {
        "target": _build_row(target_ticker, target_bucket["metrics"]),
        "peers": peer_rows,
        "medians": {
            "tev_ebitda_ltm": _rnd(_median(peer_tev_ebitda)),
            "tev_ebitda_fwd": _rnd(_median(peer_tev_ebitda_fwd)),
            "tev_ebit_ltm": _rnd(_median(peer_tev_ebit)),
            "tev_ebit_fwd": _rnd(_median(peer_tev_ebit_fwd)),
            "pe_ltm": _rnd(_median(peer_pe)),
        },
    }
