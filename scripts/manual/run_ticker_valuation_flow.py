from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_PROFILES = (
    "earnings_update",
    "company_analysis",
    "industry_analysis",
    "comps_analysis",
    "risk_review",
    "valuation_review",
)
EDGAR_SOURCE_KINDS = {"8-K", "10-K", "10-Q", "SEC_XBRL"}
EDGAR_SOURCE_PREFIXES = ("8k:", "10q:", "filing:", "risk-filing:", "sec-metrics:")

AGENT_MODEL_ENV_VARS = (
    "GROUNDED_OBSERVATION_AGENT_MODEL",
    "EARNINGS_AGENT_MODEL",
    "FILINGS_AGENT_MODEL",
    "INDUSTRY_AGENT_MODEL",
    "COMPS_AGENT_MODEL",
    "RISK_AGENT_MODEL",
    "VALUATION_AGENT_MODEL",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _fmt_money(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _fmt_pct(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):+.1f}%"
    except Exception:
        return "n/a"


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _driver_row_value(payload: dict[str, Any], field_name: str) -> float | None:
    for row in _as_list(payload.get("driver_rows")):
        if not isinstance(row, dict) or row.get("field") != field_name:
            continue
        return _float_or_none(row.get("value"))
    return None


def _assumption_field_value(payload: dict[str, Any], field_name: str) -> float | None:
    for row in _as_list(payload.get("fields")):
        if not isinstance(row, dict) or row.get("field") != field_name:
            continue
        value = _float_or_none(row.get("effective_value"))
        if value is not None:
            return value * 100.0
    return None


def _json_preview(payload: Any, *, max_chars: int = 1_400) -> str:
    text = json.dumps(payload, indent=2, default=str, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n..."


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _report_stat(report: Any, key: str) -> int:
    if isinstance(report, dict):
        value = report.get(key, 0)
    else:
        value = getattr(report, key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _collect_run_scope_ids(result: dict[str, Any]) -> tuple[set[int], set[int]]:
    packet_ids: set[int] = set()
    queue_item_ids: set[int] = set()
    for run in _as_list(result.get("profile_runs")):
        if not isinstance(run, dict):
            continue
        packet = run.get("evidence_packet")
        if isinstance(packet, dict):
            packet_id = _as_int_or_none(packet.get("packet_id"))
            if packet_id is not None:
                packet_ids.add(packet_id)
        for raw_id in _as_list(run.get("queue_item_ids")):
            queue_id = _as_int_or_none(raw_id)
            if queue_id is not None:
                queue_item_ids.add(queue_id)
    return packet_ids, queue_item_ids


def _source_ref_date(ref: dict[str, Any]) -> str | None:
    metadata = _as_dict(ref.get("metadata"))
    if metadata.get("filing_date"):
        return str(metadata["filing_date"])
    for value in (ref.get("source_label"), ref.get("source_locator")):
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return None


def collect_edgar_evidence_summary(result: dict[str, Any]) -> dict[str, Any]:
    refs_by_profile: list[tuple[str, dict[str, Any]]] = []
    for run in _as_list(result.get("profile_runs")):
        if not isinstance(run, dict):
            continue
        profile = str(run.get("profile_name") or "unknown")
        packet = _as_dict(run.get("evidence_packet"))
        for ref in _as_list(packet.get("source_refs")):
            if isinstance(ref, dict):
                refs_by_profile.append((profile, ref))
    for packet in _as_list(result.get("evidence_packets")):
        if not isinstance(packet, dict):
            continue
        profile = str(_as_dict(packet.get("run_metadata")).get("profile_name") or packet.get("packet_kind") or "unknown")
        for ref in _as_list(packet.get("source_refs")):
            if isinstance(ref, dict):
                refs_by_profile.append((profile, ref))

    seen: set[str] = set()
    unique_filing_refs: set[str] = set()
    latest_dates: list[str] = []
    forms: dict[str, int] = {}
    profiles: dict[str, int] = {}

    for profile, ref in refs_by_profile:
        source_kind = str(ref.get("source_kind") or "").strip()
        normalized_kind = source_kind.upper()
        source_ref_id = str(ref.get("source_ref_id") or "").strip()
        lower_ref_id = source_ref_id.lower()
        is_edgar = normalized_kind in EDGAR_SOURCE_KINDS or lower_ref_id.startswith(EDGAR_SOURCE_PREFIXES)
        if not is_edgar:
            continue
        dedupe_key = source_ref_id or str(ref.get("source_locator") or ref.get("source_label") or "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        forms[source_kind or "unknown"] = forms.get(source_kind or "unknown", 0) + 1
        profiles[profile] = profiles.get(profile, 0) + 1
        if not lower_ref_id.startswith("sec-metrics:"):
            unique_filing_refs.add(dedupe_key)
        ref_date = _source_ref_date(ref)
        if ref_date:
            latest_dates.append(ref_date)

    if not seen:
        return {}
    return {
        "source_ref_count": len(seen),
        "filing_count": len(unique_filing_refs),
        "latest_filing_date": max(latest_dates) if latest_dates else None,
        "forms": dict(sorted(forms.items())),
        "profiles": dict(sorted(profiles.items())),
    }


def configure_openrouter_free(model: str, fallback_models: list[str] | None = None) -> dict[str, Any]:
    os.environ["LLM_BASE_URL"] = "https://openrouter.ai/api/v1"
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_MODEL_FAST"] = model
    os.environ["LLM_SYNTHESIS_MODEL"] = model
    fallback_values = [str(value).strip() for value in (fallback_models or []) if str(value).strip()]
    if fallback_values:
        existing = [part.strip() for part in str(os.getenv("LLM_FALLBACK_MODELS", "")).split(",") if part.strip()]
        merged: list[str] = []
        for candidate in [*fallback_values, *existing]:
            if candidate not in merged and candidate != model:
                merged.append(candidate)
        if merged:
            os.environ["LLM_FALLBACK_MODELS"] = ",".join(merged)
    for env_name in AGENT_MODEL_ENV_VARS:
        os.environ[env_name] = model
    return {
        "base_url": os.environ["LLM_BASE_URL"],
        "model": os.environ["LLM_MODEL"],
        "fallback_models": [
            part.strip() for part in str(os.getenv("LLM_FALLBACK_MODELS", "")).split(",") if part.strip()
        ],
    }


def configure_isolated_db(args: argparse.Namespace, ticker: str, stamp: str) -> dict[str, Any] | None:
    if not args.isolated_db:
        return None

    output_dir = Path(args.output_dir)
    snapshot_dir = output_dir / "_isolated_db"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    source_path = ROOT / "data" / "alpha_pod.db"
    snapshot_path = snapshot_dir / f"{ticker.upper()}-{stamp}.db"
    if source_path.exists():
        with sqlite3.connect(str(source_path)) as source_conn:
            with sqlite3.connect(str(snapshot_path)) as snapshot_conn:
                source_conn.backup(snapshot_conn)
        copied_from = str(source_path)
    else:
        copied_from = None
    os.environ["ALPHA_POD_DB_PATH"] = str(snapshot_path)
    return {
        "mode": "isolated_snapshot",
        "path": str(snapshot_path),
        "copied_from": copied_from,
        "warning": "This run writes Evidence Packets and PM Queue items to the isolated snapshot, not the live Alpha Pod DB.",
    }


def _fetchone_dict(conn: sqlite3.Connection, sql: str, params: list[Any]) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def collect_data_freshness(ticker: str) -> dict[str, Any]:
    db_path = Path(os.environ.get("ALPHA_POD_DB_PATH") or ROOT / "data" / "alpha_pod.db")
    if not db_path.exists():
        return {"db_path": str(db_path), "error": "database_missing"}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            market_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT data_type, fetched_at
                    FROM market_data_cache
                    WHERE ticker = ?
                    ORDER BY data_type
                    """,
                    [ticker.upper()],
                ).fetchall()
            ]
            filing_cache = _fetchone_dict(
                conn,
                """
                SELECT COUNT(*) AS filing_count, MAX(filing_date) AS latest_filing_date
                FROM edgar_filing_cache
                WHERE ticker = ?
                """,
                [ticker.upper()],
            )
            filing_context = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT profile_name, MAX(created_at) AS latest_context_at
                    FROM filing_context_cache
                    WHERE ticker = ?
                    GROUP BY profile_name
                    ORDER BY profile_name
                    """,
                    [ticker.upper()],
                ).fetchall()
            ]
            sec_metrics = _fetchone_dict(
                conn,
                """
                SELECT as_of_date, source_filing_date, metric_source
                FROM sec_filing_metrics_snapshot
                WHERE ticker = ?
                ORDER BY as_of_date DESC
                LIMIT 1
                """,
                [ticker.upper()],
            )
    except Exception as exc:
        return {"db_path": str(db_path), "error": str(exc)}
    return {
        "db_path": str(db_path),
        "market_cache_rows": market_rows,
        "edgar_filing_cache": filing_cache or {},
        "filing_context_cache": filing_context,
        "sec_filing_metrics": sec_metrics or {},
    }


def _run_ciq_preflight(args: argparse.Namespace, ticker: str) -> dict[str, Any] | None:
    if not getattr(args, "refresh_ciq", False):
        return None

    from ciq.ciq_refresh import refresh_and_ingest_single_ticker

    return _jsonable(
        refresh_and_ingest_single_ticker(
            ticker=ticker,
            ciq_symbol=args.ciq_symbol,
            exchange=args.ciq_exchange,
            as_of_date=args.ciq_date,
            currency=args.ciq_currency,
            template_path=args.ciq_template,
            input_json_path=args.ciq_input_json,
            output_folder=args.ciq_folder,
            refresh=not args.ciq_no_refresh,
            timeout_sec=args.ciq_timeout_sec,
        )
    )


def _run_ciq_template_ingest(args: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(args, "ingest_ciq_template", False):
        return None

    from ciq.ingest import ingest_ciq_folder

    return _jsonable(ingest_ciq_folder(args.ciq_template_folder))


def refresh_current_ticker_dossier(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline import export_service

    payload = export_service._build_current_ticker_payload(ticker)
    export_service._persist_attached_ticker_dossier(payload)
    dossier = _as_dict(payload.get("ticker_dossier"))
    latest = _as_dict(dossier.get("latest_snapshot"))
    valuation = _as_dict(latest.get("valuation_snapshot"))
    market = _as_dict(latest.get("market_snapshot"))
    return {
        "source_mode": _as_dict(dossier.get("export_metadata")).get("source_mode"),
        "as_of_date": dossier.get("as_of_date"),
        "current_price": market.get("price") or valuation.get("current_price"),
        "base_iv": valuation.get("base_iv"),
    }


def attach_finance_quality_review(result: dict[str, Any]) -> None:
    from src.stage_04_pipeline.valuation_quality import build_professional_finance_review

    deterministic = _as_dict(result.get("deterministic"))
    review = build_professional_finance_review(
        summary=_as_dict(deterministic.get("summary")),
        dcf=_as_dict(deterministic.get("dcf")),
        assumptions=_as_dict(deterministic.get("assumptions")),
        comps=_as_dict(deterministic.get("comps")),
        batch_row=_as_dict(deterministic.get("batch_row")),
    )
    deterministic["finance_quality"] = review
    result["deterministic"] = deterministic


def _extract_summary_numbers(summary: dict[str, Any], dcf: dict[str, Any]) -> dict[str, Any]:
    valuation = _as_dict(summary.get("valuation"))
    ev_bridge = _as_dict(dcf.get("ev_bridge"))
    scenario_rows = _as_list(dcf.get("scenario_summary"))
    scenario_by_name = {
        str(row.get("scenario") or row.get("name") or "").lower(): row
        for row in scenario_rows
        if isinstance(row, dict)
    }
    base_row = scenario_by_name.get("base") or {}
    bear_row = scenario_by_name.get("bear") or {}
    bull_row = scenario_by_name.get("bull") or {}
    return {
        # Prefer the DCF-level price because scenario upside is calculated from it.
        "price": (
            dcf.get("current_price")
            or ev_bridge.get("current_price")
            or summary.get("current_price")
            or valuation.get("price")
        ),
        "base_iv": (
            base_row.get("intrinsic_value")
            or valuation.get("iv_base")
            or valuation.get("base_iv")
            or summary.get("base_iv")
            or ev_bridge.get("intrinsic_value_per_share")
        ),
        "bear_iv": (
            bear_row.get("intrinsic_value")
            or valuation.get("iv_bear")
            or summary.get("bear_iv")
        ),
        "bull_iv": (
            bull_row.get("intrinsic_value")
            or valuation.get("iv_bull")
            or summary.get("bull_iv")
        ),
        "base_upside_pct": (
            base_row.get("upside_pct")
            or valuation.get("upside_base_pct")
            or valuation.get("expected_upside_pct")
            or summary.get("upside_pct_base")
        ),
        "trust_state": summary.get("model_trust_state") or _as_dict(summary.get("readiness")).get("status"),
    }


def _packet_quality(packet: dict[str, Any]) -> str:
    return str(_as_dict(packet.get("run_metadata")).get("source_quality") or "unknown")


def _profile_quality_map(result: dict[str, Any]) -> dict[str, str]:
    qualities: dict[str, str] = {}
    for run in _as_list(result.get("profile_runs")):
        if not isinstance(run, dict):
            continue
        profile_name = str(run.get("profile_name") or "")
        if not profile_name:
            continue
        qualities[profile_name] = _packet_quality(_as_dict(run.get("evidence_packet")))
    return qualities


def _preview_base_delta_pct(preview: dict[str, Any]) -> float | None:
    try:
        payload = _as_dict(preview.get("preview"))
        delta_pct = _as_dict(payload.get("delta_pct"))
        value = delta_pct.get("base")
        return float(value) if value is not None else None
    except Exception:
        return None


def _comps_status(comps: dict[str, Any]) -> str:
    if not comps or comps.get("error"):
        return "error"
    audit_flags = [str(flag).lower() for flag in _as_list(comps.get("audit_flags"))]
    has_primary_metric = bool(comps.get("primary_metric"))
    has_metric_values = bool(comps.get("valuation_by_metric") or comps.get("valuation_by_metric_rows"))
    if any("comps model unavailable" in flag for flag in audit_flags) or not has_primary_metric or not has_metric_values:
        return "partial/no valuation signal"
    return "available"


def _flow_readiness(result: dict[str, Any], deterministic: dict[str, Any]) -> tuple[str, list[str]]:
    errors = _as_list(result.get("errors"))
    profile_runs = [run for run in _as_list(result.get("profile_runs")) if isinstance(run, dict)]
    blocked_profiles = [str(run.get("profile_name")) for run in profile_runs if str(run.get("status")) == "blocked"]
    live_mode = result.get("agent_mode") == "live"
    reasons: list[str] = []
    if errors:
        reasons.append(f"{len(errors)} deterministic/API step(s) errored")
    if blocked_profiles:
        reasons.append(f"blocked profiles: {', '.join(blocked_profiles)}")
    if result.get("agent_mode") == "heuristic":
        reasons.append("local heuristic agents prove the handoff path but are not investment-grade insights")
    if result.get("market_cache_only"):
        reasons.append("market cache-only mode may use stale market rows; refresh live market data before PM approval")
    if result.get("edgar_cache_only"):
        reasons.append("EDGAR cache-only mode uses local filings only; refresh filings before final memo work")
    if any(isinstance(value, dict) and value.get("error") for value in deterministic.values()):
        reasons.append("one or more deterministic payloads are degraded")
    summary = _as_dict(deterministic.get("summary"))
    dcf = _as_dict(deterministic.get("dcf"))
    batch_row = _as_dict(deterministic.get("batch_row"))
    price_values = [
        value
        for value in (
            _float_or_none(dcf.get("current_price")),
            _float_or_none(_as_dict(dcf.get("ev_bridge")).get("current_price")),
            _float_or_none(summary.get("current_price")),
            _float_or_none(_as_dict(summary.get("summary")).get("current_price")),
            _float_or_none(batch_row.get("price")),
        )
        if value is not None and value > 0
    ]
    if price_values and (max(price_values) / min(price_values) - 1.0) > 0.01:
        reasons.append(
            "current price differs across deterministic payloads by more than 1%; use DCF-level price for scenario math"
        )
    wacc_pct_values = [
        value
        for value in (
            _float_or_none(batch_row.get("wacc")),
            _float_or_none(_as_dict(dcf.get("model_integrity")).get("wacc_pct")),
            _driver_row_value(dcf, "wacc"),
            _assumption_field_value(_as_dict(deterministic.get("assumptions")), "wacc"),
        )
        if value is not None and value > 0
    ]
    if wacc_pct_values and (max(wacc_pct_values) - min(wacc_pct_values)) > 0.25:
        reasons.append(
            "WACC differs across deterministic payloads by more than 25 bps; reconcile source lineage before PM review"
        )
    summary_base_iv = _float_or_none(summary.get("base_iv"))
    dcf_base_iv = _float_or_none(_extract_summary_numbers(summary, dcf).get("base_iv"))
    if summary_base_iv and dcf_base_iv and abs(summary_base_iv / dcf_base_iv - 1.0) > 0.01:
        reasons.append("summary base IV differs from DCF base IV by more than 1%; use DCF-level IV for scenario math")
    if not reasons and live_mode:
        return "PM-reviewable live run", ["No deterministic errors or blocked agent profiles were reported."]
    if not reasons:
        return "PM-reviewable workflow run", ["No deterministic errors or blocked profiles were reported."]
    return "degraded / needs operator review", reasons


def _item_recommendation(
    *,
    item: dict[str, Any],
    preview: dict[str, Any],
    profile_qualities: dict[str, str],
    agent_mode: str,
) -> str:
    if agent_mode == "heuristic":
        return "Do not approve as an investment change; use this item to validate evidence, translation, preview, and PM approval mechanics."
    source_quality = profile_qualities.get(str(item.get("profile_name") or ""), "unknown")
    if source_quality != "real":
        return "Defer or reject until the evidence packet has real source quality."
    if item.get("item_type") == "advisory_finding":
        return "Read before sizing or memo work; no deterministic assumption change is proposed."
    delta = _preview_base_delta_pct(preview)
    if delta is None:
        return "Do not approve until the preview resolves cleanly."
    if abs(delta) >= 5:
        return "High-impact assumption proposal; PM should independently verify the evidence before approve/edit."
    return "Low-to-moderate valuation impact; approve only if the cited evidence directly supports the driver change."


def _queue_priority_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    previews = _as_dict(result.get("previews"))
    rows: list[dict[str, Any]] = []
    for item in _as_list(result.get("queue_items")):
        if not isinstance(item, dict):
            continue
        preview = _as_dict(previews.get(str(item.get("item_id"))))
        rows.append(
            {
                "item": item,
                "preview": preview,
                "abs_delta": abs(_preview_base_delta_pct(preview) or 0.0),
            }
        )
    return sorted(rows, key=lambda row: row["abs_delta"], reverse=True)


def _first_packet_anchor_ids(packet: Any) -> tuple[list[str], list[str]]:
    anchor_ids: list[str] = []
    snippet_ids: list[str] = []
    for fact in list(getattr(packet, "facts", []) or [])[:2]:
        _append_unique(anchor_ids, str(fact.fact_id))
    for snippet in list(getattr(packet, "snippets", []) or [])[:2]:
        _append_unique(snippet_ids, str(snippet.snippet_id))
        _append_unique(anchor_ids, str(snippet.snippet_id))
    if not anchor_ids:
        for source in list(getattr(packet, "source_refs", []) or [])[:1]:
            _append_unique(anchor_ids, str(source.source_ref_id))
    return anchor_ids, snippet_ids


def _anchor_ids_for_fact_names(packet: Any, fact_names: set[str]) -> list[str]:
    anchor_ids: list[str] = []
    for fact in getattr(packet, "facts", []) or []:
        if str(getattr(fact, "fact_name", "")) in fact_names:
            _append_unique(anchor_ids, str(fact.fact_id))
    return anchor_ids


def _packet_text(packet: Any) -> str:
    return " ".join(str(getattr(snippet, "text", "")) for snippet in getattr(packet, "snippets", []) or []).lower()


def _packet_facts(packet: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for fact in getattr(packet, "facts", []) or []:
        facts.setdefault(str(fact.fact_name), fact.value)
    return facts


def _heuristic_observation(packet: Any, profile_name: str) -> list[Any]:
    from src.contracts.evidence_packet import (
        EvidenceConfidence,
        EvidenceImportance,
        EvidencePacketObservation,
        EvidencePacketObservationKind,
    )

    if str((getattr(packet, "run_metadata", {}) or {}).get("source_quality") or "") != "real":
        return []
    anchor_ids, snippet_ids = _first_packet_anchor_ids(packet)
    if not anchor_ids:
        return []

    text = _packet_text(packet)
    facts = _packet_facts(packet)
    kind = EvidencePacketObservationKind.qualitative if snippet_ids else EvidencePacketObservationKind.numeric
    earnings_growth = facts.get("latest_quarter_revenue_yoy_pct")
    earnings_claim = (
        f"Recent quarterly evidence shows total revenue growth of {earnings_growth:.1f}% year over year, "
        "which is strong enough to review against the current near-term growth assumption."
        if isinstance(earnings_growth, (int, float))
        else "Recent earnings evidence contains quantified revenue or guidance signals that should be reviewed against the current near-term growth assumption."
    )

    valuation_type = (
        "terminal_value_fragility"
        if bool(facts.get("tv_high_flag")) or (_float_or_none(facts.get("tv_pct_of_ev")) or 0) >= 70
        else "wacc_method_disagreement"
        if bool(facts.get("wacc_method_spread_high"))
        else "assumption_inconsistency"
    )
    valuation_driver = (
        f"Review terminal value dependence: TV is {facts.get('tv_pct_of_ev')}% of EV and terminal growth is {facts.get('terminal_growth_pct')}%."
        if valuation_type == "terminal_value_fragility"
        else "Review WACC source lineage and selected methodology."
        if valuation_type == "wacc_method_disagreement"
        else "Review whether growth, margin, WACC, and exit multiple assumptions are internally consistent."
    )
    valuation_question = (
        "Is the base-case upside still investable if most of enterprise value comes from terminal value?"
        if valuation_type == "terminal_value_fragility"
        else "Which valuation driver explains most of the gap between current price and base IV?"
    )

    templates = {
        "earnings_update": {
            "observation_type": (
                "demand_strength_broad"
                if (
                    (isinstance(earnings_growth, (int, float)) and earnings_growth > 0)
                    or any(term in text for term in ("demand", "growth", "cloud", "artificial intelligence", "generative ai"))
                )
                else "pricing_pressure_improved"
            ),
            "claim": earnings_claim,
            "driver": "Review revenue_growth_near before relying on the base DCF.",
            "question": "Does the quantified revenue update justify changing near-term growth, or is it already captured in the model?",
        },
        "company_analysis": {
            "observation_type": (
                "pricing_pressure_improved"
                if "margin" in text or "profit" in text or "gross_margin_avg_3y" in facts
                else "execution_risk_increased"
            ),
            "claim": "Company filing evidence is material to the operating-margin thesis and should be checked against the current CIQ-derived margin bridge.",
            "driver": "Review ebit_margin_start and ebit_margin_target.",
            "question": "Does filing detail support a sustainable margin bridge or only a one-period improvement?",
        },
        "industry_analysis": {
            "observation_type": "demand_strength_broad",
            "claim": "Industry and filing context supports reviewing whether the embedded growth path is too conservative or too aggressive versus current demand drivers.",
            "driver": "Review revenue_growth_near and revenue_growth_mid.",
            "question": "Which segment or customer cohort is actually carrying the demand signal?",
        },
        "comps_analysis": {
            "observation_type": "multiple_premium_supported",
            "claim": "The deterministic comps packet has enough peer data for PM review of the exit multiple, but the comps model diagnostics still need inspection.",
            "driver": f"Review exit_multiple against peer medians: {facts}.",
            "question": "Is the peer set clean enough to justify changing the terminal exit multiple?",
        },
        "risk_review": {
            "observation_type": "execution_risk_increased",
            "claim": "Risk evidence should stay visible to the PM because execution, financing, or market-risk facts can materially change position sizing even when no automatic valuation edit is appropriate.",
            "driver": "Keep as advisory unless PM decides WACC or scenario probabilities need adjustment.",
            "question": "Is this risk already captured in WACC/scenarios, or would that double count it?",
        },
        "valuation_review": {
            "observation_type": valuation_type,
            "claim": "The valuation packet shows DCF scenario and driver evidence that warrants PM review before accepting the model output as investment-grade.",
            "driver": valuation_driver,
            "question": valuation_question,
        },
    }
    template = templates.get(profile_name)
    if template is None:
        return []
    if profile_name == "valuation_review" and valuation_type == "terminal_value_fragility":
        terminal_anchors = _anchor_ids_for_fact_names(packet, {"tv_pct_of_ev", "tv_high_flag", "terminal_growth_pct", "pv_tv_blended_mm"})
        if terminal_anchors:
            anchor_ids = terminal_anchors[:3]

    return [
        EvidencePacketObservation(
            observation_id=f"heuristic:{profile_name}:1",
            observation_kind=kind,
            observation_type=template["observation_type"],
            claim=template["claim"],
            evidence_anchor_ids=anchor_ids,
            text_snippet_ids=snippet_ids,
            qualitative_importance=EvidenceImportance.high,
            materiality=EvidenceImportance.high,
            agent_confidence=EvidenceConfidence.medium,
            evidence_rationale="The cited packet anchors are enough to raise a PM-review item, but not enough for an automatic model change.",
            thesis_implication="This could change the confidence in the deterministic base case if the PM agrees with the evidence interpretation.",
            driver_implication=template["driver"],
            pm_question=template["question"],
            what_would_change_mind="Fresh contradictory guidance, cleaner peer evidence, or deterministic source-lineage review could reverse this observation.",
            metadata={"agent_mode": "local_heuristic", "facts_snapshot": facts},
        )
    ]


@contextmanager
def heuristic_agent_runs(enabled: bool) -> Any:
    if not enabled:
        yield
        return

    from src.stage_03_judgment.grounded_observation_agent import GroundedObservationAgent
    from src.stage_03_judgment.comps_agent import CompsAgent
    from src.stage_03_judgment.earnings_agent import EarningsAgent
    from src.stage_03_judgment.filings_agent import FilingsAgent
    from src.stage_03_judgment.industry_agent import IndustryAgent
    from src.stage_03_judgment.risk_agent import RiskAgent
    from src.stage_03_judgment.valuation_agent import ValuationAgent

    classes = (GroundedObservationAgent, CompsAgent, EarningsAgent, FilingsAgent, IndustryAgent, RiskAgent, ValuationAgent)
    originals = {cls: cls.analyze_evidence_packet for cls in classes}

    def _analyze(self: Any, packet: Any, profile_name: str) -> list[Any]:
        return _heuristic_observation(packet, profile_name)

    try:
        for cls in classes:
            cls.analyze_evidence_packet = _analyze  # type: ignore[method-assign]
        yield
    finally:
        for cls, original in originals.items():
            cls.analyze_evidence_packet = original  # type: ignore[method-assign]


def run_flow(args: argparse.Namespace) -> dict[str, Any]:
    os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", str(ROOT / "data" / "cache" / "edgar_tools"))
    ticker = args.ticker.upper().strip()
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    database_info = configure_isolated_db(args, ticker, run_stamp)
    if args.edgar_cache_only:
        os.environ["ALPHA_POD_EDGAR_CACHE_ONLY"] = "1"
    if args.market_cache_only:
        os.environ["ALPHA_POD_MARKET_CACHE_ONLY"] = "1"
        os.environ["ALPHA_POD_ALLOW_STALE_MARKET_CACHE"] = "1"
    if args.use_openrouter_free:
        configure_openrouter_free(args.openrouter_model, args.openrouter_fallback_models)

    preflight_errors: list[dict[str, str]] = []
    ciq_refresh_result: dict[str, Any] | None = None
    ciq_template_ingest_result: dict[str, Any] | None = None
    if args.refresh_ciq:
        try:
            print(f"[ticker-flow] Staging CIQ input and refreshing Excel for {ticker}...", file=sys.stderr)
            ciq_refresh_result = _run_ciq_preflight(args, ticker)
        except Exception as exc:
            ciq_refresh_result = {"error": str(exc)}
            preflight_errors.append({"step": "refresh_ciq", "message": str(exc)})
    if args.ingest_ciq_template:
        try:
            print(f"[ticker-flow] Ingesting manually refreshed CIQ template workbook for {ticker}...", file=sys.stderr)
            ciq_template_ingest_result = _run_ciq_template_ingest(args)
        except Exception as exc:
            ciq_template_ingest_result = {"error": str(exc)}
            preflight_errors.append({"step": "ingest_ciq_template", "message": str(exc)})

    from api.main import (
        build_valuation_assumptions_payload,
        build_valuation_comps_payload,
        build_valuation_dcf_payload,
        build_valuation_summary_payload,
        list_evidence_packets_payload,
        list_pm_decision_queue_payload,
        preview_pm_decision_queue_payload,
        run_agentic_handoff_profile_payload,
    )
    from src.stage_02_valuation.batch_runner import value_single_ticker

    run_started_at = datetime.now(timezone.utc).isoformat()

    result: dict[str, Any] = {
        "ticker": ticker,
        "run_started_at": run_started_at,
        "openrouter_free": bool(args.use_openrouter_free),
        "edgar_cache_only": bool(args.edgar_cache_only),
        "market_cache_only": bool(args.market_cache_only),
        "agent_model": (
            "local_heuristic"
            if args.agent_mode == "heuristic"
            else args.openrouter_model if args.use_openrouter_free else os.getenv("LLM_MODEL")
        ),
        "agent_mode": args.agent_mode,
        "deterministic": {},
        "profile_runs": [],
        "evidence_packets": [],
        "queue_items": [],
        "previews": {},
        "errors": preflight_errors,
        "ciq_refresh": ciq_refresh_result,
        "ciq_template_ingest": ciq_template_ingest_result,
        "database": database_info or {
            "mode": "live",
            "path": str(ROOT / "data" / "alpha_pod.db"),
        },
        "data_freshness": collect_data_freshness(ticker),
        "run_scope": {
            "packet_ids": [],
            "queue_item_ids": [],
            "filtered_to_current_run": False,
        },
    }

    try:
        print(f"[ticker-flow] Building deterministic valuation for {ticker}...", file=sys.stderr)
        result["deterministic"]["batch_row"] = value_single_ticker(ticker)
    except Exception as exc:
        result["errors"].append({"step": "value_single_ticker", "message": str(exc)})

    try:
        print(f"[ticker-flow] Refreshing current ticker dossier for {ticker}...", file=sys.stderr)
        result["deterministic"]["current_dossier_refresh"] = refresh_current_ticker_dossier(ticker)
    except Exception as exc:
        result["deterministic"]["current_dossier_refresh"] = {"error": str(exc)}
        result["errors"].append({"step": "refresh_current_ticker_dossier", "message": str(exc)})

    for name, builder in (
        ("summary", lambda active_ticker: build_valuation_summary_payload(active_ticker, source_mode="loaded_backend_state")),
        ("dcf", build_valuation_dcf_payload),
        ("comps", build_valuation_comps_payload),
        ("assumptions", build_valuation_assumptions_payload),
    ):
        try:
            print(f"[ticker-flow] Building {name} payload...", file=sys.stderr)
            result["deterministic"][name] = builder(ticker)
        except Exception as exc:
            result["deterministic"][name] = {"error": str(exc)}
            result["errors"].append({"step": f"build_{name}", "message": str(exc)})

    initial_queue_item_ids: set[int] = set()
    try:
        initial_rows = list_pm_decision_queue_payload(ticker, status=None).get("items") or []
        initial_queue_item_ids = {int(row["item_id"]) for row in initial_rows if row.get("item_id") is not None}
    except Exception:
        initial_queue_item_ids = set()

    if not args.skip_agent_runs:
        with heuristic_agent_runs(args.agent_mode == "heuristic"):
            for profile in args.profiles:
                try:
                    print(f"[ticker-flow] Running profile {profile} ({args.agent_mode})...", file=sys.stderr)
                    payload = _jsonable(
                        run_agentic_handoff_profile_payload(
                            ticker,
                            profile,
                            include_agent_artifact=True,
                        )
                    )
                except Exception as exc:
                    payload = {
                        "ticker": ticker,
                        "profile_name": profile,
                        "status": "failed",
                        "reason": "script_exception",
                        "errors": [{"code": "script_exception", "message": str(exc)}],
                        "observation_count": 0,
                        "queue_item_count": 0,
                        "queue_item_ids": [],
                    }
                result["profile_runs"].append(payload)

    run_packet_ids, run_queue_item_ids = _collect_run_scope_ids(result)
    result["run_scope"] = {
        "packet_ids": sorted(run_packet_ids),
        "queue_item_ids": sorted(run_queue_item_ids),
        "filtered_to_current_run": bool(run_packet_ids or run_queue_item_ids),
    }

    try:
        print("[ticker-flow] Loading evidence packets...", file=sys.stderr)
        evidence_packets = _jsonable(list_evidence_packets_payload(ticker).get("evidence_packets") or [])
        if run_packet_ids:
            evidence_packets = [
                packet
                for packet in evidence_packets
                if _as_int_or_none(_as_dict(packet).get("packet_id")) in run_packet_ids
            ]
        result["evidence_packets"] = evidence_packets
    except Exception as exc:
        result["errors"].append({"step": "list_evidence_packets", "message": str(exc)})
    result["data_freshness"]["edgar_evidence_sources"] = collect_edgar_evidence_summary(result)

    try:
        print("[ticker-flow] Loading PM Decision Queue items...", file=sys.stderr)
        queue_items = _jsonable(list_pm_decision_queue_payload(ticker, status=None).get("items") or [])
        if not args.include_existing_queue:
            if run_queue_item_ids:
                queue_items = [
                    item
                    for item in queue_items
                    if _as_int_or_none(_as_dict(item).get("item_id")) in run_queue_item_ids
                ]
            else:
                queue_items = [
                    item
                    for item in queue_items
                    if int(item.get("item_id") or 0) not in initial_queue_item_ids
                ]
        result["queue_items"] = queue_items
    except Exception as exc:
        result["errors"].append({"step": "list_pm_decision_queue", "message": str(exc)})

    if args.preview_queue:
        for item in result["queue_items"]:
            if item.get("status") != "pending" or item.get("item_type") != "assumption_change_pack":
                continue
            item_id = int(item["item_id"])
            try:
                print(f"[ticker-flow] Previewing queue item {item_id}...", file=sys.stderr)
                result["previews"][str(item_id)] = _jsonable(preview_pm_decision_queue_payload(ticker, item_id))
            except Exception as exc:
                result["previews"][str(item_id)] = {"error": str(exc)}

    try:
        attach_finance_quality_review(result)
    except Exception as exc:
        result["errors"].append({"step": "finance_quality_review", "message": str(exc)})

    return _jsonable(result)


def render_markdown(result: dict[str, Any]) -> str:
    ticker = result["ticker"]
    deterministic = _as_dict(result.get("deterministic"))
    summary = _as_dict(deterministic.get("summary"))
    dcf = _as_dict(deterministic.get("dcf"))
    comps = _as_dict(deterministic.get("comps"))
    assumptions = _as_dict(deterministic.get("assumptions"))
    batch_row = _as_dict(deterministic.get("batch_row"))
    nums = _extract_summary_numbers(summary, dcf)
    price = nums.get("price") or batch_row.get("price")
    base_iv = nums.get("base_iv") or batch_row.get("iv_base")
    base_upside = nums.get("base_upside_pct") or batch_row.get("upside_base_pct")
    conclusion = "n/a"
    try:
        if price is not None and base_iv is not None:
            conclusion = "undervalued" if float(base_iv) > float(price) else "overvalued"
    except Exception:
        conclusion = "n/a"
    dcf_health = _as_dict(dcf.get("health_flags"))
    active_dcf_flags = [key for key, value in dcf_health.items() if value]
    scenario_rows = [row for row in _as_list(dcf.get("scenario_summary")) if isinstance(row, dict)]
    assumption_summary = _as_dict(assumptions.get("assumption_register_summary"))
    flagged_entries = [row for row in _as_list(assumption_summary.get("flagged_entries")) if isinstance(row, dict)]
    assumption_fields = [row for row in _as_list(assumptions.get("fields")) if isinstance(row, dict)]
    review_fields = [
        row
        for row in assumption_fields
        if row.get("ticker_override_present")
        or row.get("agent_status") == "pending"
        or row.get("effective_source") in {"approved_assumption_register", "override_ticker"}
    ]
    comps_peer_counts = _as_dict(comps.get("peer_counts"))
    comps_audit_flags = [str(flag) for flag in _as_list(comps.get("audit_flags"))]
    readiness_label, readiness_reasons = _flow_readiness(result, deterministic)
    finance_quality = _as_dict(deterministic.get("finance_quality"))
    finance_flags = [row for row in _as_list(finance_quality.get("flags")) if isinstance(row, dict)]
    profile_qualities = _profile_quality_map(result)
    prioritized_queue_rows = _queue_priority_rows(result)

    lines: list[str] = [
        f"# {ticker} Professional Valuation Flow",
        "",
        f"- Generated: {result.get('run_started_at')}",
        f"- Agent model: {result.get('agent_model') or 'not configured'}",
        f"- OpenRouter free mode: {result.get('openrouter_free')}",
        f"- EDGAR cache-only mode: {result.get('edgar_cache_only')}",
        f"- Market cache-only mode: {result.get('market_cache_only')}",
        f"- Database mode: {_as_dict(result.get('database')).get('mode', 'unknown')}",
        f"- Run-scope filter: {'enabled' if _as_dict(result.get('run_scope')).get('filtered_to_current_run') else 'disabled'}",
        "",
        "## PM Verdict Prep",
        "",
        f"- Current price: {_fmt_money(price)}",
        f"- Bear / Base / Bull IV: {_fmt_money(nums.get('bear_iv') or batch_row.get('iv_bear'))} / {_fmt_money(base_iv)} / {_fmt_money(nums.get('bull_iv') or batch_row.get('iv_bull'))}",
        f"- Base upside: {_fmt_pct(base_upside)}",
        f"- Initial deterministic read: {conclusion}",
        f"- Model trust state: {nums.get('trust_state') or batch_row.get('model_trust_state') or assumption_summary.get('model_trust_state') or 'n/a'}",
        f"- Finance quality state: {finance_quality.get('status') or 'n/a'}",
        f"- PM must inspect: {', '.join(active_dcf_flags or comps_audit_flags or ['no active DCF/comps flags'])}",
        f"- Workflow readiness: {readiness_label}",
        "- Approval rule: do not approve an agent/heuristic change unless the inline evidence and previewed IV impact both make sense.",
        "",
        "### Operator Readiness Notes",
        "",
    ]
    for reason in readiness_reasons:
        lines.append(f"- {reason}")
    if finance_flags:
        lines.extend(["", "### Professional Finance Review Gates", ""])
        for flag in finance_flags[:8]:
            lines.append(
                f"- [{flag.get('severity')}] {flag.get('title')}: {flag.get('detail')} "
                f"PM check: {flag.get('pm_check')}"
            )
    database_info = _as_dict(result.get("database"))
    if database_info.get("warning"):
        lines.append(f"- {database_info.get('warning')}")
    if database_info.get("path"):
        lines.append(f"- DB path for this run: {database_info.get('path')}")
    if prioritized_queue_rows:
        lines.extend(["", "### Highest-Impact PM Queue Items", ""])
        for row in prioritized_queue_rows[:5]:
            item = row["item"]
            preview = row["preview"]
            delta = _preview_base_delta_pct(preview)
            delta_text = f"{delta:+.1f}%" if delta is not None else "n/a"
            lines.append(
                f"- Item {item.get('item_id')} `{item.get('profile_name')}`: "
                f"{item.get('title')} changes base IV by {delta_text}"
            )
    lines.extend(
        [
            "",
        "## Deterministic Valuation Checks",
        "",
        f"- DCF available: {'error' not in dcf}",
        f"- Comps status: {_comps_status(comps)}",
        f"- Assumption payload available: {'error' not in assumptions}",
        f"- Assumption flags: {len(flagged_entries) or batch_row.get('assumption_flagged_count', 'n/a')} flagged, max level {assumption_summary.get('max_flag_level') or batch_row.get('assumption_max_flag_level', 'n/a')}",
        f"- Comps peer count: raw={comps_peer_counts.get('raw', 'n/a')} clean={comps_peer_counts.get('clean', 'n/a')}",
        f"- Comps audit flags: {', '.join(comps_audit_flags) if comps_audit_flags else 'none'}",
        "",
        "### Key Deterministic Inputs",
        "",
        f"- Revenue growth near/mid: {batch_row.get('growth_near', 'n/a')}% / {batch_row.get('growth_mid', 'n/a')}%",
        f"- EBIT margin used: {batch_row.get('ebit_margin_used', 'n/a')}%",
        f"- WACC: {batch_row.get('wacc', 'n/a')}%",
        f"- Exit multiple: {batch_row.get('exit_multiple_used', 'n/a')}x",
        f"- Growth source: {batch_row.get('growth_source', 'n/a')}",
        f"- Margin source: {batch_row.get('ebit_margin_source', 'n/a')}",
        "",
        "### Scenario Table",
        "",
        "| Scenario | Probability | IV | Upside |",
        "|---|---:|---:|---:|",
    ]
    )
    for row in scenario_rows:
        lines.append(
            f"| {row.get('scenario')} | {row.get('probability_pct', 'n/a')}% | "
            f"{_fmt_money(row.get('intrinsic_value'))} | {_fmt_pct(row.get('upside_pct'))} |"
        )
    lines.extend(
        [
            "",
            "### PM Assumption Review",
            "",
        ]
    )
    if not review_fields and not flagged_entries:
        lines.append("- No explicit override, pending-agent, or flagged assumptions found in the payload.")
    for row in review_fields[:10]:
        lines.append(
            f"- {row.get('field')}: effective={row.get('effective_value')} from {row.get('effective_source')} "
            f"(baseline={row.get('baseline_value')} from {row.get('baseline_source')}; "
            f"agent={row.get('agent_value')} {row.get('agent_confidence') or ''})"
        )
        if row.get("agent_rationale"):
            lines.append(f"  PM note: {row.get('agent_rationale')}")
    for row in flagged_entries[:8]:
        if row.get("assumption_name") in {field.get("field") for field in review_fields[:10]}:
            continue
        lines.append(
            f"- Flagged {row.get('assumption_name')}: {row.get('flag_level')} "
            f"scope={row.get('scope')} source={_as_dict(row.get('source_lineage')).get('source', 'n/a')}"
        )
    freshness = _as_dict(result.get("data_freshness"))
    lines.extend(["", "### Data Freshness", ""])
    ciq_refresh = _as_dict(result.get("ciq_refresh"))
    if ciq_refresh:
        if ciq_refresh.get("error"):
            lines.append(f"- CIQ preflight failed before refresh: {ciq_refresh.get('error')}")
        else:
            financials_input = _as_dict(ciq_refresh.get("financials_input"))
            report = _as_dict(ciq_refresh.get("ingest_report"))
            lines.append(
                f"- CIQ input staged: {financials_input.get('ticker', 'n/a')} "
                f"as_of={financials_input.get('date_year', 'n/a')}-"
                f"{financials_input.get('date_month', 'n/a')}-"
                f"{financials_input.get('date_day', 'n/a')} "
                f"currency={financials_input.get('currency', 'n/a')}"
            )
            lines.append(
                f"- CIQ refresh: refreshed={ciq_refresh.get('refreshed')} "
                f"processed={_report_stat(report, 'processed')} skipped={_report_stat(report, 'skipped')} "
                f"failed={_report_stat(report, 'failed')} archive={ciq_refresh.get('archive_path') or 'n/a'}"
            )
    ciq_template_ingest = _as_dict(result.get("ciq_template_ingest"))
    if ciq_template_ingest:
        if ciq_template_ingest.get("error"):
            lines.append(f"- CIQ template ingest failed: {ciq_template_ingest.get('error')}")
        else:
            lines.append(
                f"- CIQ template ingest: folder={ciq_template_ingest.get('folder')} "
                f"processed={_report_stat(ciq_template_ingest, 'processed')} "
                f"skipped={_report_stat(ciq_template_ingest, 'skipped')} "
                f"failed={_report_stat(ciq_template_ingest, 'failed')}"
            )
    if freshness.get("error"):
        lines.append(f"- Data freshness unavailable: {freshness.get('error')}")
    else:
        for row in _as_list(freshness.get("market_cache_rows")):
            if isinstance(row, dict):
                lines.append(f"- Market cache `{row.get('data_type')}` fetched_at={row.get('fetched_at')}")
        filing_cache = _as_dict(freshness.get("edgar_filing_cache"))
        if filing_cache:
            lines.append(
                f"- EDGAR filing cache: {filing_cache.get('filing_count')} filings, "
                f"latest filing date={filing_cache.get('latest_filing_date')}"
            )
        edgar_evidence = _as_dict(freshness.get("edgar_evidence_sources"))
        if edgar_evidence:
            lines.append(
                f"- EDGAR evidence used this run: {edgar_evidence.get('filing_count')} filing refs, "
                f"{edgar_evidence.get('source_ref_count')} source refs, "
                f"latest filing date={edgar_evidence.get('latest_filing_date')}"
            )
            lines.append(
                f"- EDGAR evidence by profile: "
                f"{json.dumps(edgar_evidence.get('profiles') or {}, sort_keys=True)}"
            )
        sec_metrics = _as_dict(freshness.get("sec_filing_metrics"))
        if sec_metrics:
            lines.append(
                f"- SEC metrics: as_of={sec_metrics.get('as_of_date')} "
                f"source_filing_date={sec_metrics.get('source_filing_date')} "
                f"source={sec_metrics.get('metric_source')}"
            )
    lines.extend(
        [
            "",
            "## Agentic Evidence And Queue",
            "",
        ]
    )

    for run in _as_list(result.get("profile_runs")):
        packet = _as_dict(run.get("evidence_packet"))
        metadata = _as_dict(packet.get("run_metadata"))
        lines.extend(
            [
                f"### {run.get('profile_name')}",
                "",
                f"- Status: {run.get('status')}",
                f"- Reason: {run.get('reason') or metadata.get('reason') or 'n/a'}",
                f"- Source quality: {_packet_quality(packet)}",
                f"- Observations / queue items: {run.get('observation_count', 0)} / {run.get('queue_item_count', 0)}",
                f"- Facts / snippets / refs: {len(_as_list(packet.get('facts')))} / {len(_as_list(packet.get('snippets')))} / {len(_as_list(packet.get('source_refs')))}",
            ]
        )
        facts = [fact for fact in _as_list(packet.get("facts")) if isinstance(fact, dict)]
        snippets = [snippet for snippet in _as_list(packet.get("snippets")) if isinstance(snippet, dict)]
        if facts or snippets:
            lines.append("")
            lines.append("Evidence sample:")
            for fact in facts[:3]:
                lines.append(f"- Fact `{fact.get('fact_name')}`: {fact.get('value')}")
            for snippet in snippets[:2]:
                text = str(snippet.get("text") or "").replace("\n", " ").strip()
                if len(text) > 260:
                    text = text[:260].rstrip() + "..."
                lines.append(f"- Snippet `{snippet.get('snippet_id')}`: {text}")
        errors = _as_list(run.get("errors"))
        if errors:
            lines.append(f"- Errors: {_json_preview(errors, max_chars=500)}")
        observations = _as_list(packet.get("observations"))
        for observation in observations[:2]:
            if not isinstance(observation, dict):
                continue
            lines.extend(
                [
                    "",
                    f"Observation: {observation.get('claim')}",
                    f"- Materiality: {observation.get('materiality') or observation.get('qualitative_importance') or 'n/a'}",
                    f"- Thesis implication: {observation.get('thesis_implication') or 'n/a'}",
                    f"- Driver implication: {observation.get('driver_implication') or 'n/a'}",
                    f"- PM question: {observation.get('pm_question') or 'n/a'}",
                ]
            )
        lines.append("")

    queue_items = _as_list(result.get("queue_items"))
    lines.extend(["## PM Decision Queue", ""])
    if not queue_items:
        lines.append("No queue items were created.")
    for item in queue_items[:20]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        preview = _as_dict(_as_dict(result.get("previews")).get(str(item_id)))
        metadata = _as_dict(item.get("metadata"))
        lines.extend(
            [
                f"### Item {item_id}: {item.get('title')}",
                "",
                f"- Status/type/profile: {item.get('status')} / {item.get('item_type')} / {item.get('profile_name')}",
                f"- Summary: {item.get('summary')}",
                f"- Importance/confidence: {item.get('qualitative_importance')} / agent {item.get('agent_confidence')} / translator {item.get('translator_confidence')}",
                f"- Evidence quality: {profile_qualities.get(str(item.get('profile_name') or ''), 'unknown')}",
                f"- Suggested PM action: {_item_recommendation(item=item, preview=preview, profile_qualities=profile_qualities, agent_mode=str(result.get('agent_mode') or 'live'))}",
            ]
        )
        if metadata.get("driver_implication"):
            lines.append(f"- Driver implication: {metadata.get('driver_implication')}")
        if metadata.get("pm_question"):
            lines.append(f"- PM question: {metadata.get('pm_question')}")
        if metadata.get("what_would_change_mind"):
            lines.append(f"- What would change mind: {metadata.get('what_would_change_mind')}")
        pack = _as_dict(item.get("pm_edited_proposal_pack") or item.get("proposal_pack"))
        proposals = _as_list(pack.get("proposals"))
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            lines.append(
                f"- Proposal: {proposal.get('assumption_name')} {proposal.get('proposal_mode')} "
                f"target={proposal.get('proposed_target_value')} delta={proposal.get('proposed_delta')}"
            )
        if preview:
            if "error" in preview:
                lines.append(f"- Preview error: {preview['error']}")
            else:
                p = _as_dict(preview.get("preview"))
                current_iv = _as_dict(p.get("current_iv"))
                proposed_iv = _as_dict(p.get("proposed_iv"))
                delta_pct = _as_dict(p.get("delta_pct"))
                lines.append(
                    f"- Preview base IV: {_fmt_money(current_iv.get('base'))} -> "
                    f"{_fmt_money(proposed_iv.get('base'))} ({_fmt_pct(delta_pct.get('base'))})"
                )
                resolved_values = _as_dict(p.get("resolved_values"))
                for field_name, resolved in resolved_values.items():
                    resolved_payload = _as_dict(resolved)
                    lines.append(
                        f"- Resolved `{field_name}`: {resolved_payload.get('current_value')} -> "
                        f"{resolved_payload.get('proposed_value')}"
                    )
                skipped = preview.get("skipped_fields") or []
                if skipped:
                    lines.append(f"- Skipped fields: {', '.join(skipped)}")
        lines.append("")

    if result.get("errors"):
        lines.extend(["## Run Errors", "", "```json", _json_preview(result["errors"], max_chars=2_000), "```", ""])

    lines.extend(
        [
            "## Raw Quality Snapshot",
            "",
            "```json",
            _json_preview(
                {
                    "deterministic_errors": {
                        key: value.get("error")
                        for key, value in deterministic.items()
                        if isinstance(value, dict) and value.get("error")
                    },
                    "profile_statuses": [
                        {
                            "profile": run.get("profile_name"),
                            "status": run.get("status"),
                            "source_quality": _packet_quality(_as_dict(run.get("evidence_packet"))),
                            "observations": run.get("observation_count"),
                            "queue_items": run.get("queue_item_count"),
                        }
                        for run in _as_list(result.get("profile_runs"))
                        if isinstance(run, dict)
                    ],
                    "queue_item_count": len(queue_items),
                },
                max_chars=3_000,
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a full ticker valuation and PM-review flow.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--profiles", nargs="*", default=list(DEFAULT_PROFILES))
    parser.add_argument("--skip-agent-runs", action="store_true")
    parser.add_argument("--include-existing-queue", action="store_true")
    parser.add_argument(
        "--agent-mode",
        choices=("live", "heuristic"),
        default="live",
        help="Use live LLM agents or local deterministic heuristic observations.",
    )
    parser.add_argument("--preview-queue", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--edgar-cache-only",
        action="store_true",
        help="Use project-local cached SEC filing text instead of live edgartools fetches.",
    )
    parser.add_argument(
        "--isolated-db",
        action="store_true",
        help="Copy the current SQLite DB to output/ticker_flows/_isolated_db and write PM Queue changes there.",
    )
    parser.add_argument(
        "--market-cache-only",
        action="store_true",
        help="Use cached market/yfinance rows even if stale; avoids live Yahoo calls during manual rehearsals.",
    )
    parser.add_argument(
        "--refresh-ciq",
        action="store_true",
        help="Before valuation, write ciq/templates/financials_input.json, refresh the CIQ Excel workbook, and ingest it.",
    )
    parser.add_argument("--ciq-symbol", type=str, help="Exact CIQ symbol for --refresh-ciq, e.g. NASDAQ:MSFT")
    parser.add_argument("--ciq-exchange", type=str, help="Exchange prefix for --refresh-ciq, e.g. NASDAQ or NYSE")
    parser.add_argument("--ciq-date", type=str, help="As-of date written to financials_input.json in YYYY-MM-DD format")
    parser.add_argument("--ciq-currency", type=str, default="USD", help="Currency written to financials_input.json")
    parser.add_argument(
        "--ciq-template",
        type=str,
        default=str(ROOT / "ciq" / "templates" / "ciq_cleandata.xlsx"),
        help="Template workbook used for --refresh-ciq staging.",
    )
    parser.add_argument(
        "--ciq-input-json",
        type=str,
        default=str(ROOT / "ciq" / "templates" / "financials_input.json"),
        help="financials_input.json path used by the CIQ template workbook.",
    )
    parser.add_argument(
        "--ciq-folder",
        type=str,
        default=None,
        help="CIQ workbook export/drop folder for the staged refreshed workbook.",
    )
    parser.add_argument(
        "--ciq-timeout-sec",
        type=int,
        default=300,
        help="Maximum seconds for the Excel/CIQ add-in validation loop during --refresh-ciq.",
    )
    parser.add_argument(
        "--ciq-no-refresh",
        action="store_true",
        help="With --refresh-ciq, stage the input/workbook and ingest without triggering Excel refresh.",
    )
    parser.add_argument(
        "--ingest-ciq-template",
        action="store_true",
        help="Before valuation, ingest the manually refreshed CIQ template workbook folder.",
    )
    parser.add_argument(
        "--ciq-template-folder",
        type=str,
        default=str(ROOT / "ciq" / "templates"),
        help="Folder containing manually refreshed ciq_cleandata.xlsx for --ingest-ciq-template.",
    )
    parser.add_argument("--use-openrouter-free", action="store_true")
    parser.add_argument(
        "--openrouter-model",
        default=os.getenv("OPENROUTER_FREE_MODEL", "openrouter/free"),
    )
    parser.add_argument(
        "--openrouter-fallback-models",
        nargs="*",
        default=None,
        help="Optional fallback ladder when the primary OpenRouter model errors/rate-limits.",
    )
    parser.add_argument("--output-dir", default=str(ROOT / "output" / "ticker_flows"))
    args = parser.parse_args()

    result = run_flow(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = output_dir / f"{args.ticker.upper()}-{stamp}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(f"Ticker flow complete for {args.ticker.upper()}")
    print(f"Markdown: {md_path}")
    print(f"JSON: {json_path}")
    print("Profile statuses:")
    for run in _as_list(result.get("profile_runs")):
        if isinstance(run, dict):
            print(
                f"- {run.get('profile_name')}: {run.get('status')} "
                f"obs={run.get('observation_count', 0)} queue={run.get('queue_item_count', 0)}"
            )
    print(f"Queue items: {len(_as_list(result.get('queue_items')))}")
    database = _as_dict(result.get("database"))
    if database.get("mode") == "isolated_snapshot":
        print(f"Isolated DB: {database.get('path')}")
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
