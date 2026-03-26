from __future__ import annotations

from src.stage_00_data import market_data, peer_similarity
from src.stage_00_data.ciq_adapter import get_ciq_comps_detail
from src.stage_02_valuation.comps_model import run_comps_model
from src.stage_04_pipeline.multiples_dashboard import build_multiples_dashboard_view

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
METRIC_LABELS = {
    "tev_ebitda_fwd": "TEV / EBITDA Fwd",
    "tev_ebitda_ltm": "TEV / EBITDA LTM",
    "tev_ebit_fwd": "TEV / EBIT Fwd",
    "tev_ebit_ltm": "TEV / EBIT LTM",
    "pe_ltm": "P / E LTM",
}


def _safe_round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _normalise_similarity_weights(scores: dict[str, float]) -> dict[str, float]:
    cleaned = {ticker: max(float(score), 0.0) for ticker, score in scores.items()}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {ticker: round(score / total, 4) for ticker, score in cleaned.items()}


def _compare_payload(target: dict, medians: dict) -> dict:
    keys = (
        "tev_ebitda_ltm",
        "tev_ebitda_fwd",
        "tev_ebit_ltm",
        "tev_ebit_fwd",
        "pe_ltm",
        "revenue_growth",
        "ebit_margin",
        "net_debt_to_ebitda",
    )
    return {
        "target": {key: target.get(key) for key in keys if target.get(key) is not None},
        "peer_medians": {key: medians.get(key) for key in keys if medians.get(key) is not None},
    }


def _median(values: list[float | None]) -> float | None:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return None
    midpoint = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[midpoint]
    return round((cleaned[midpoint - 1] + cleaned[midpoint]) / 2.0, 4)


def _derive_target_net_debt_to_ebitda(target: dict) -> float | None:
    tev_mm = target.get("tev_mm")
    market_cap_mm = target.get("market_cap_mm")
    ebitda_ltm_mm = target.get("ebitda_ltm_mm")
    if tev_mm is None or market_cap_mm is None or ebitda_ltm_mm in (None, 0):
        return None
    return round((float(tev_mm) - float(market_cap_mm)) / float(ebitda_ltm_mm), 4)


def _target_vs_peers_payload(target: dict, market: dict, medians: dict, peers: list[dict]) -> dict:
    target_payload = {
        "tev_ebitda_ltm": target.get("tev_ebitda_ltm") or market.get("ev_ebitda"),
        "tev_ebitda_fwd": target.get("tev_ebitda_fwd"),
        "tev_ebit_ltm": target.get("tev_ebit_ltm"),
        "tev_ebit_fwd": target.get("tev_ebit_fwd"),
        "pe_ltm": target.get("pe_ltm") or market.get("pe_trailing"),
        "revenue_growth": target.get("revenue_growth") or market.get("revenue_growth"),
        "ebit_margin": target.get("ebit_margin") or market.get("operating_margin"),
        "net_debt_to_ebitda": target.get("net_debt_to_ebitda") or _derive_target_net_debt_to_ebitda(target),
    }
    peer_medians = dict(medians or {})
    derived_peer_medians = {
        "revenue_growth": _median([row.get("revenue_growth") for row in peers]),
        "ebit_margin": _median([row.get("ebit_margin") for row in peers]),
        "net_debt_to_ebitda": _median([row.get("net_debt_to_ebitda") for row in peers]),
    }
    for key, value in derived_peer_medians.items():
        if value is not None and peer_medians.get(key) is None:
            peer_medians[key] = value

    deltas = {}
    for key, target_value in target_payload.items():
        peer_value = peer_medians.get(key)
        if target_value is not None and peer_value is not None:
            deltas[key] = round(float(target_value) - float(peer_value), 4)

    return {
        "target": {key: value for key, value in target_payload.items() if value is not None},
        "peer_medians": peer_medians,
        "deltas": deltas,
    }


def _valuation_range_by_metric(comps_result) -> dict[str, dict]:
    if comps_result is None:
        return {}
    results: dict[str, dict] = {}
    for metric_name, metric in comps_result.metrics.items():
        results[metric_name] = {
            "label": METRIC_LABELS.get(metric_name, metric_name.replace("_", " ").upper()),
            "bear": metric.bear_iv,
            "base": metric.base_iv,
            "bull": metric.bull_iv,
            "bear_multiple": getattr(metric, "bear_multiple", None),
            "base_multiple": getattr(metric, "base_multiple", None),
            "bull_multiple": getattr(metric, "bull_multiple", None),
        }
    return results


def _football_field(
    current_price: float | None,
    valuation_by_metric: dict[str, dict],
    analyst_target_mean: float | None,
) -> dict:
    markers: list[dict] = []
    ranges: list[dict] = []
    values: list[float] = []
    if current_price is not None:
        current_value = float(current_price)
        values.append(current_value)
        markers.append({"label": "Current Price", "value": current_value, "type": "spot"})
    for metric_name, payload in valuation_by_metric.items():
        label_prefix = payload.get("label") or METRIC_LABELS.get(metric_name, metric_name)
        bear = payload.get("bear")
        base = payload.get("base")
        bull = payload.get("bull")
        for band_value in (bear, base, bull):
            if band_value is not None:
                values.append(float(band_value))
        if bear is not None or base is not None or bull is not None:
            ranges.append(
                {
                    "metric": metric_name,
                    "label": label_prefix,
                    "bear": float(bear) if bear is not None else None,
                    "base": float(base) if base is not None else None,
                    "bull": float(bull) if bull is not None else None,
                }
            )
        for band in ("bear", "base", "bull"):
            band_value = payload.get(band)
            if band_value is None:
                continue
            markers.append(
                {
                    "label": f"{label_prefix} {band.title()}",
                    "metric": metric_name,
                    "band": band,
                    "value": float(band_value),
                    "type": "range_point",
                }
            )
    if analyst_target_mean is not None:
        analyst_value = float(analyst_target_mean)
        values.append(analyst_value)
        markers.append({"label": "Analyst Target Mean", "value": analyst_value, "type": "spot"})
    return {
        "ranges": ranges,
        "markers": markers,
        "range_min": min(values) if values else None,
        "range_max": max(values) if values else None,
    }


def _metric_options(valuation_by_metric: dict[str, dict], primary_metric: str | None) -> list[dict]:
    ordered_keys = list(valuation_by_metric.keys()) if valuation_by_metric else []
    if not ordered_keys and primary_metric:
        ordered_keys = [primary_metric]
    options = []
    for key in ordered_keys:
        payload = valuation_by_metric.get(key, {})
        options.append(
            {
                "key": key,
                "label": payload.get("label") or METRIC_LABELS.get(key, key.replace("_", " ").upper()),
            }
        )
    return options


def build_comps_dashboard_view(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    comps_detail = get_ciq_comps_detail(ticker)
    if not comps_detail:
        return {
            "ticker": ticker,
            "available": False,
            "target": {},
            "peers": [],
            "metric_options": [],
            "selected_metric_default": None,
            "valuation_range": {},
            "valuation_range_by_metric": {},
            "target_vs_peers": {"target": {}, "peer_medians": {}, "deltas": {}},
            "football_field": {"ranges": [], "markers": [], "range_min": None, "range_max": None},
            "historical_multiples_summary": {"available": False, "metrics": {}, "audit_flags": []},
            "audit_flags": ["No CIQ comps detail available"],
        }

    market = market_data.get_market_data(ticker)
    peer_rows_source = [row for row in comps_detail.get("peers", []) if row.get("ticker")]
    similarity_scores: dict[str, float] = {}
    similarity_warning: str | None = None
    if peer_rows_source:
        try:
            similarity_scores = peer_similarity.score_peer_similarity(
                ticker,
                peer_rows_source,
                DEFAULT_EMBEDDING_MODEL,
            )
        except Exception as exc:
            similarity_warning = f"Peer similarity unavailable: {exc}"
    shares_mm = None
    if market.get("shares_outstanding"):
        shares_mm = float(market["shares_outstanding"]) / 1_000_000.0

    target = comps_detail.get("target") or {}
    tev_mm = target.get("tev_mm")
    market_cap_mm = target.get("market_cap_mm")
    net_debt_mm = (tev_mm - market_cap_mm) if tev_mm is not None and market_cap_mm is not None else None
    comps_result = run_comps_model(
        comps_detail,
        net_debt_mm=net_debt_mm,
        shares_mm=shares_mm,
        similarity_scores=similarity_scores or None,
    )

    model_weights = _normalise_similarity_weights(similarity_scores)
    peer_rows = []
    for row in comps_detail.get("peers", []):
        peer_row = dict(row)
        peer_row["similarity_score"] = similarity_scores.get(row["ticker"])
        peer_row["model_weight"] = model_weights.get(row["ticker"])
        peer_rows.append(peer_row)
    peer_rows.sort(
        key=lambda row: (
            -(row.get("model_weight") or 0.0),
            -(row.get("similarity_score") or 0.0),
            row.get("ticker") or "",
        )
    )

    valuation_range = {}
    audit_flags: list[str] = []
    primary_metric = None
    valuation_by_metric = _valuation_range_by_metric(comps_result)
    if comps_result is not None:
        valuation_range = {
            "bear": comps_result.bear_iv,
            "base": comps_result.base_iv,
            "bull": comps_result.bull_iv,
            "blended_base": comps_result.blended_base_iv,
        }
        primary_metric = comps_result.primary_metric
        primary_detail = comps_result.metrics.get(primary_metric) if primary_metric else None
        if primary_detail and primary_detail.outliers_removed:
            audit_flags.append(
                f"Outliers removed from {primary_metric}: {', '.join(primary_detail.outliers_removed)}"
            )
        if comps_result.peer_count_clean < comps_result.peer_count_raw:
            audit_flags.append(
                f"Peer set cleaned from {comps_result.peer_count_raw} to {comps_result.peer_count_clean}"
            )
    else:
        audit_flags.append("Comps model unavailable for current peer set")
    if similarity_warning:
        audit_flags.append(similarity_warning)

    multiples_summary = build_multiples_dashboard_view(ticker)
    metric_options = _metric_options(valuation_by_metric, primary_metric)

    return {
        "ticker": ticker,
        "available": True,
        "target": {
            **target,
            "current_price": market.get("current_price"),
            "name": market.get("name"),
            "sector": market.get("sector"),
            "industry": market.get("industry"),
        },
        "peers": peer_rows,
        "peer_counts": {
            "raw": comps_result.peer_count_raw if comps_result else len(peer_rows),
            "clean": comps_result.peer_count_clean if comps_result else len(peer_rows),
        },
        "primary_metric": primary_metric,
        "metric_options": metric_options,
        "selected_metric_default": primary_metric,
        "valuation_range": valuation_range,
        "valuation_range_by_metric": valuation_by_metric,
        "similarity_method": comps_result.similarity_method if comps_result else "market_cap_only",
        "similarity_model": comps_result.similarity_model if comps_result else None,
        "weighting_formula": comps_result.weighting_formula if comps_result else "market_cap_proximity_only",
        "medians": comps_detail.get("medians") or {},
        "compare_to_target": _compare_payload(target, comps_detail.get("medians") or {}),
        "target_vs_peers": _target_vs_peers_payload(
            target,
            market,
            comps_detail.get("medians") or {},
            peer_rows,
        ),
        "football_field": _football_field(
            market.get("current_price"),
            valuation_by_metric,
            market.get("analyst_target_mean"),
        ),
        "historical_multiples_summary": multiples_summary,
        "source_lineage": {
            "as_of_date": target.get("as_of_date"),
            "source_file": target.get("source_file"),
        },
        "audit_flags": audit_flags,
        "notes": comps_result.notes if comps_result else "",
        "dcf_compare": {
            "current_price": _safe_round(market.get("current_price")),
        },
    }
