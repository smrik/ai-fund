from __future__ import annotations

from statistics import median
from typing import Any

from src.stage_00_data import market_data
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail


_METRIC_SOURCE_MAP: dict[str, dict[str, str | None]] = {
    "pe_trailing": {"market_key": "pe_trailing", "peer_key": "pe_ltm", "mode": "price"},
    "ev_ebitda": {"market_key": "ev_ebitda", "peer_key": "tev_ebitda_ltm", "mode": "enterprise"},
    "ev_revenue": {"market_key": "ev_revenue", "peer_key": None, "mode": "enterprise"},
    "price_to_book": {"market_key": "price_to_book", "peer_key": None, "mode": "price"},
    "price_to_sales": {"market_key": "price_to_sales", "peer_key": None, "mode": "price"},
}


def _percentile_rank(value: float, series: list[float]) -> float | None:
    if not series:
        return None
    count = sum(1 for item in series if item <= value)
    return round(count / len(series), 4)


def _median(values: list[float]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return round(float(median(cleaned)), 4)


def _historical_multiple_series(
    *,
    current_multiple: float,
    current_price: float,
    history: list[dict],
    mode: str,
    market_cap: float | None,
    enterprise_value: float | None,
) -> list[dict]:
    if current_price <= 0:
        return []

    if mode == "enterprise":
        if enterprise_value is None or market_cap is None or enterprise_value <= 0:
            return []
        net_debt = float(enterprise_value) - float(market_cap)
        denominator = float(enterprise_value) / float(current_multiple) if current_multiple else None
        if denominator is None or denominator <= 0:
            return []
    else:
        denominator = float(current_price) / float(current_multiple) if current_multiple else None
        if denominator is None or denominator <= 0:
            return []

    series: list[dict] = []
    for row in history:
        close = row.get("close")
        if close in (None, 0):
            continue
        close_value = float(close)
        if mode == "enterprise":
            historical_market_cap = float(market_cap) * (close_value / float(current_price))
            historical_ev = historical_market_cap + net_debt
            multiple = historical_ev / denominator
        else:
            multiple = close_value / denominator
        series.append(
            {
                "date": row.get("date"),
                "price": close_value,
                "multiple": round(float(multiple), 4),
            }
        )
    return series


def build_multiples_dashboard_view(
    ticker: str,
    *,
    period: str = "5y",
    metrics: tuple[str, ...] = ("pe_trailing", "ev_ebitda", "ev_revenue", "price_to_book"),
) -> dict:
    ticker = ticker.upper().strip()
    market = market_data.get_market_data(ticker)
    current_price = market.get("current_price")
    history = market_data.get_price_history(ticker, period=period)
    audit_flags: list[str] = []
    if not current_price:
        audit_flags.append("Current price unavailable for historical multiples")
    if not history:
        audit_flags.append("No price history available")
    if audit_flags:
        return {
            "ticker": ticker,
            "available": False,
            "period": period,
            "history_points": len(history or []),
            "metrics": {},
            "peer_snapshot": {},
            "audit_flags": audit_flags,
        }

    comps_detail = get_ciq_comps_detail(ticker) or {}
    peer_snapshot = comps_detail.get("medians") or {}
    result_metrics: dict[str, Any] = {}
    market_cap = market.get("market_cap")
    enterprise_value = market.get("enterprise_value")

    for metric_name in metrics:
        spec = _METRIC_SOURCE_MAP.get(metric_name)
        if spec is None:
            continue
        current_multiple = market.get(spec["market_key"])
        if current_multiple is None:
            continue
        series = _historical_multiple_series(
            current_multiple=float(current_multiple),
            current_price=float(current_price),
            history=history,
            mode=str(spec["mode"]),
            market_cap=float(market_cap) if market_cap is not None else None,
            enterprise_value=float(enterprise_value) if enterprise_value is not None else None,
        )
        if not series:
            continue
        scalar_values = [float(point["multiple"]) for point in series]
        current_value = round(float(current_multiple), 4)
        result_metrics[metric_name] = {
            "current": round(current_value, 4),
            "series": series,
            "summary": {
                "current": current_value,
                "min": round(min(scalar_values), 4),
                "max": round(max(scalar_values), 4),
                "median": _median(scalar_values),
                "current_percentile": _percentile_rank(current_value, scalar_values),
                "percentile_1y": _percentile_rank(
                    current_value,
                    scalar_values[-252:] if len(scalar_values) > 252 else scalar_values,
                ),
                "percentile_3y": _percentile_rank(current_value, scalar_values),
                "percentile_5y": _percentile_rank(current_value, scalar_values),
                "peer_current": peer_snapshot.get(spec["peer_key"]) if spec["peer_key"] else None,
            },
        }

    return {
        "ticker": ticker,
        "available": bool(result_metrics),
        "period": period,
        "history_points": len(history),
        "metrics": result_metrics,
        "peer_snapshot": peer_snapshot,
        "audit_flags": [] if result_metrics else ["No multiples history available"],
    }
