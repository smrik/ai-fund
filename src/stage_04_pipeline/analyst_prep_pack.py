from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from config import ROOT_DIR
from db.schema import create_tables, get_connection
from src.contracts.analyst_prep_pack import (
    AnalystPrepPack,
    AnalystPrepSection,
    CompsJudgmentCard,
    MissingDataFlag,
    ModelDriverBridgeCard,
    SegmentDriverRow,
    ThesisBridgeCard,
)
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
from src.stage_04_pipeline.override_workbench import build_override_workbench
from src.stage_04_pipeline.pm_decision_queue import build_pm_decision_queue_conflict_groups
from src.stage_04_pipeline.dossier_view import build_research_board_view


DRIVER_FIELDS: tuple[tuple[str, str], ...] = (
    ("revenue_growth_near", "Revenue Growth (Near)"),
    ("revenue_growth_mid", "Revenue Growth (Mid)"),
    ("ebit_margin_start", "EBIT Margin (Start)"),
    ("ebit_margin_target", "EBIT Margin (Target)"),
    ("wacc", "WACC"),
    ("revenue_growth_terminal", "Terminal Growth"),
    ("exit_multiple", "Exit Multiple"),
)

SEGMENT_MARKERS = (
    "segment",
    "business unit",
    "business units",
    "business division",
    "business divisions",
    "operating division",
    "reportable segment",
)

REVENUE_TOKENS = ("revenue", "revenues", "sales", "net_sales")
PROFIT_TOKENS = ("operating_income", "segment_profit", "profit", "ebit")
MARGIN_TOKENS = ("margin", "operating_margin", "ebit_margin")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_decimal_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100.0 if abs(value) > 1.0 else value


def _base_scenario(dcf: dict[str, Any]) -> dict[str, Any]:
    for row in dcf.get("scenario_summary") or []:
        if str((row or {}).get("scenario") or "").lower() == "base":
            return dict(row)
    return {}


def _latest_packet_per_profile(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Current evidence state is the newest packet per profile. Older packets
    stay in the store for audit, but rendering them here would resurface
    superseded (and possibly corrected) facts next to fresh ones."""
    latest: dict[str, dict[str, Any]] = {}
    for packet in packets:
        profile = str(packet.get("profile_name") or "")
        packet_id = int(packet.get("packet_id") or 0)
        current = latest.get(profile)
        if current is None or packet_id > int(current.get("packet_id") or 0):
            latest[profile] = packet
    return sorted(latest.values(), key=lambda p: int(p.get("packet_id") or 0))


def _load_store_state(ticker: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from db.loader import list_evidence_packets, list_pm_decision_queue_items

    with get_connection() as conn:
        create_tables(conn)
        packets = _latest_packet_per_profile(list_evidence_packets(conn, ticker=ticker))
        queue_items = list_pm_decision_queue_items(conn, ticker=ticker, status=None)
        return packets, queue_items


def _source_quality_from_packets(packets: list[dict[str, Any]], *, comps_available: bool, dcf_available: bool) -> str:
    qualities = {
        str((packet.get("run_metadata") or {}).get("source_quality") or "").lower()
        for packet in packets
    }
    if qualities == {"real"}:
        return "real"
    if comps_available or dcf_available or qualities.intersection({"real", "partial"}):
        return "partial"
    if "placeholder" in qualities:
        return "placeholder"
    return "missing"


def _evidence_map(packets: list[dict[str, Any]], workbench: dict[str, Any], comps: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for packet in packets:
        packet_id = packet.get("packet_id")
        for fact in packet.get("facts") or []:
            fact_id = str(fact.get("fact_id") or fact.get("id") or "")
            rows.append(
                {
                    "anchor_id": f"packet:{packet_id}:fact:{fact_id}" if fact_id else f"packet:{packet_id}",
                    "packet_id": packet_id,
                    "profile_name": packet.get("profile_name"),
                    "kind": "packet_fact",
                    "label": fact.get("label") or fact.get("name") or fact_id,
                    "value": fact.get("value"),
                    "unit": fact.get("unit"),
                    "source_quality": (packet.get("run_metadata") or {}).get("source_quality"),
                    "source_ref": fact.get("source_ref") or fact.get("source_id"),
                }
            )
        for observation in packet.get("observations") or []:
            rows.append(
                {
                    "anchor_id": observation.get("observation_id") or f"packet:{packet_id}:observation",
                    "packet_id": packet_id,
                    "profile_name": packet.get("profile_name"),
                    "kind": "packet_observation",
                    "label": observation.get("claim") or observation.get("title") or "Observation",
                    "value": observation.get("observation_type"),
                    "unit": None,
                    "source_quality": (packet.get("run_metadata") or {}).get("source_quality"),
                    "source_ref": "; ".join(observation.get("evidence_anchor_ids") or []),
                }
            )

    for field in workbench.get("fields") or []:
        rows.append(
            {
                "anchor_id": f"deterministic:assumption:{field.get('field')}",
                "packet_id": None,
                "profile_name": "deterministic_model",
                "kind": "model_assumption",
                "label": field.get("label") or field.get("field"),
                "value": field.get("effective_value"),
                "unit": field.get("unit"),
                "source_quality": "partial",
                "source_ref": field.get("effective_source") or field.get("baseline_source"),
            }
        )

    lineage = comps.get("source_lineage") or {}
    if comps.get("available"):
        rows.append(
            {
                "anchor_id": "deterministic:comps:peer_set",
                "packet_id": None,
                "profile_name": "deterministic_comps",
                "kind": "comps_peer_set",
                "label": "Comparable company peer set",
                "value": (comps.get("peer_counts") or {}).get("clean") or (comps.get("peer_counts") or {}).get("raw"),
                "unit": "peers",
                "source_quality": "real" if lineage.get("source") != "public_market_yfinance_fallback" else "partial",
                "source_ref": lineage.get("source_file") or lineage.get("source"),
            }
        )
    return rows


def _has_segment_marker(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in SEGMENT_MARKERS)


def _segment_metric_type(row: dict[str, Any]) -> str | None:
    metric_key = str(row.get("metric_key") or "").lower()
    label_text = f"{row.get('section_name') or ''} {row.get('row_label') or ''}".lower()
    if any(token in metric_key or token.replace("_", " ") in label_text for token in MARGIN_TOKENS):
        return "margin"
    if any(token in metric_key or token.replace("_", " ") in label_text for token in REVENUE_TOKENS):
        return "revenue"
    if any(token in metric_key or token.replace("_", " ") in label_text for token in PROFIT_TOKENS):
        return "profit"
    return None


def _clean_segment_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(
        r"\b(reportable|operating|business|unit|units|division|divisions|segment|segments|"
        r"revenue|revenues|sales|net sales|operating income|income|profit|ebitda|ebit|margin|"
        r"percentage|percent|by)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[^A-Za-z0-9&+./ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -:/")
    if len(text) < 2 or text.lower() in {"total", "all", "other", "business"}:
        return None
    return text


def _segment_name_for_record(row: dict[str, Any], metric_type: str) -> str | None:
    row_label = row.get("row_label")
    section = row.get("section_name")
    section_text = str(section or "").lower()
    cleaned = _clean_segment_name(row_label)
    if cleaned:
        return cleaned
    if metric_type in {"revenue", "profit", "margin"} and _has_segment_marker(section_text):
        return _clean_segment_name(section)
    return None


def _latest_two(values: list[tuple[str, float]]) -> list[tuple[str, float]]:
    seen: dict[str, float] = {}
    for period, value in sorted(values, key=lambda item: item[0], reverse=True):
        if period not in seen:
            seen[period] = value
        if len(seen) >= 2:
            break
    return list(seen.items())


def _segment_driver_rows_from_records(ticker: str, records: list[dict[str, Any]]) -> list[SegmentDriverRow]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"revenue": [], "profit": [], "margin": [], "source_refs": []})
    for row in records:
        if row.get("ticker") and str(row.get("ticker")).upper().strip() != ticker.upper().strip():
            continue
        if not (
            _has_segment_marker(row.get("sheet_name"))
            or _has_segment_marker(row.get("section_name"))
            or _has_segment_marker(row.get("row_label"))
        ):
            continue
        metric_type = _segment_metric_type(row)
        if not metric_type:
            continue
        segment = _segment_name_for_record(row, metric_type)
        value = _safe_float(row.get("value_num"))
        period = str(row.get("period_date") or row.get("column_label") or row.get("column_index") or "")
        if not segment or value is None or not period:
            continue
        entry = grouped[segment]
        entry[metric_type].append((period, value))
        source_ref = f"{row.get('source_file') or row.get('sheet_name')}:{row.get('section_name')}:{row.get('row_label')}"
        if source_ref not in entry["source_refs"]:
            entry["source_refs"].append(source_ref)

    total_latest_revenue = 0.0
    latest_revenue_by_segment: dict[str, float] = {}
    for segment, rows in grouped.items():
        latest = _latest_two(rows["revenue"])
        if latest:
            latest_revenue_by_segment[segment] = latest[0][1]
            if latest[0][1] > 0:
                total_latest_revenue += latest[0][1]

    segment_rows: list[SegmentDriverRow] = []
    for segment, rows in sorted(grouped.items()):
        revenue_growth = None
        revenue_latest = _latest_two(rows["revenue"])
        if len(revenue_latest) >= 2 and revenue_latest[1][1]:
            revenue_growth = revenue_latest[0][1] / revenue_latest[1][1] - 1.0

        margin = None
        margin_latest = _latest_two(rows["margin"])
        if margin_latest:
            margin = _to_decimal_ratio(margin_latest[0][1])
        elif rows["profit"] and rows["revenue"]:
            profit_by_period = dict(_latest_two(rows["profit"]))
            revenue_by_period = dict(_latest_two(rows["revenue"]))
            for period, profit in profit_by_period.items():
                revenue = revenue_by_period.get(period)
                if revenue:
                    margin = profit / revenue
                    break

        revenue_mix = None
        latest_revenue = latest_revenue_by_segment.get(segment)
        if latest_revenue is not None and total_latest_revenue > 0 and len(latest_revenue_by_segment) >= 2:
            revenue_mix = latest_revenue / total_latest_revenue

        if revenue_growth is None and margin is None and revenue_mix is None:
            continue
        quality = "real" if revenue_mix is not None and (revenue_growth is not None or margin is not None) else "partial"
        segment_rows.append(
            SegmentDriverRow(
                segment=segment,
                revenue_growth=revenue_growth,
                margin=margin,
                revenue_mix=revenue_mix,
                source_ref="; ".join(rows["source_refs"][:3]) or None,
                quality=quality,
            )
        )
    return segment_rows


def _packet_anchor_ids(packets: list[dict[str, Any]], limit: int = 4) -> list[str]:
    anchors: list[str] = []
    for packet in packets:
        packet_id = packet.get("packet_id")
        for fact in packet.get("facts") or []:
            fact_id = str(fact.get("fact_id") or fact.get("id") or "")
            if packet_id and fact_id:
                anchors.append(f"packet:{packet_id}:fact:{fact_id}")
            elif packet_id:
                anchors.append(f"packet:{packet_id}")
            if len(anchors) >= limit:
                return anchors
    return anchors


def _default_resolution_by_field(default_resolution: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("field")): dict(item)
        for item in default_resolution.get("fields") or []
        if isinstance(item, dict) and item.get("field")
    }


def _default_item_needs_pm_review(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    if "needs_pm_review" in item:
        return bool(item.get("needs_pm_review"))
    return str(item.get("status") or item.get("source_class") or "").lower() in {
        "review_required",
        "review_required_high",
        "default",
        "unproven_zero",
    }


def _conflict_group_by_field(conflict_groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(group.get("assumption_name")): dict(group)
        for group in conflict_groups
        if isinstance(group, dict) and group.get("assumption_name")
    }


def _active_pack(item: dict[str, Any]) -> dict[str, Any] | None:
    pack = item.get("pm_edited_proposal_pack") or item.get("proposal_pack") or item.get("approved_proposal_pack")
    return dict(pack) if isinstance(pack, dict) else None


def _queue_value_for_field(items: list[dict[str, Any]], field: str) -> tuple[float | None, dict[str, Any] | None]:
    for item in items:
        if str(item.get("status") or "").lower() == "rejected":
            continue
        pack = _active_pack(item)
        if not pack:
            continue
        for proposal in pack.get("proposals") or []:
            if proposal.get("assumption_name") != field:
                continue
            value = _safe_float(proposal.get("proposed_target_value"))
            if value is None:
                value = _safe_float((item.get("adapter_links") or {}).get("last_preview_manual_values", {}).get(field))
            return value, item
    return None, None


def _driver_cards(
    workbench: dict[str, Any],
    effective_inputs: Any,
    queue_items: list[dict[str, Any]],
    conflict_groups: list[dict[str, Any]],
) -> list[ModelDriverBridgeCard]:
    rows = {row.get("field"): dict(row) for row in workbench.get("fields") or []}
    default_by_field = _default_resolution_by_field(workbench.get("default_resolution") or {})
    conflict_by_field = _conflict_group_by_field(conflict_groups)
    cards: list[ModelDriverBridgeCard] = []
    for field, label in DRIVER_FIELDS:
        row = rows.get(field)
        baseline = _safe_float((row or {}).get("baseline_value"))
        effective = _safe_float((row or {}).get("effective_value"))
        source = (row or {}).get("effective_source") or (row or {}).get("baseline_source")
        if field == "revenue_growth_terminal" and effective_inputs is not None:
            drivers = getattr(effective_inputs, "drivers", None)
            if drivers is not None and hasattr(drivers, field):
                baseline = effective if baseline is None else baseline
                effective = _safe_float(getattr(drivers, field))
                source = (getattr(effective_inputs, "source_lineage", {}) or {}).get(field) or source
        proposed, queue_item = _queue_value_for_field(queue_items, field)
        default_item = default_by_field.get(field)
        default_needs_review = _default_item_needs_pm_review(default_item)
        conflict_group = conflict_by_field.get(field)
        queue_status = str((queue_item or {}).get("status") or "").lower()
        active_proposal = proposed is not None and queue_status not in {"deferred", "rejected"}
        displayed_value = proposed if active_proposal else effective
        status = "review_required" if default_needs_review or active_proposal or conflict_group else "ok"
        if proposed is not None and queue_status == "deferred":
            status = "review_required"
        elif proposed is not None and queue_status == "approved":
            status = "ok"
        if (conflict_group or {}).get("conflict_level") == "conflict":
            status = "conflict"
        if effective is None and displayed_value is None:
            status = "missing"
        anchors = [f"deterministic:assumption:{field}"]
        if queue_item:
            anchors.extend(str(value) for value in queue_item.get("evidence_anchor_ids") or [])
        cards.append(
            ModelDriverBridgeCard(
                assumption_name=field,
                label=label,
                current_value=baseline,
                proposed_or_effective_value=displayed_value,
                source=source,
                rationale=_driver_rationale(field, source, default_item if default_needs_review else None, queue_item, conflict_group),
                valuation_impact=(queue_item or {}).get("valuation_impact") if queue_item else None,
                evidence_anchor_ids=anchors,
                pm_review_status=status,
            )
        )
    return cards


def _driver_rationale(
    field: str,
    source: str | None,
    default_item: dict[str, Any] | None,
    queue_item: dict[str, Any] | None,
    conflict_group: dict[str, Any] | None = None,
) -> str:
    if conflict_group:
        note = conflict_group.get("review_note") or "Multiple profiles touch this driver."
        return f"{note} Review queue items {', '.join(str(item_id) for item_id in conflict_group.get('item_ids') or [])} together."
    if queue_item:
        status = str(queue_item.get("status") or "pending")
        return (
            f"PM Queue item {queue_item.get('item_id')} is {status} and discusses this driver: "
            f"{queue_item.get('summary') or queue_item.get('title')}"
        )
    if default_item:
        replacement = default_item.get("preferred_replacement_source") or default_item.get("replacement_source")
        if replacement:
            return f"Default-resolution layer flags this field for review; preferred replacement source: {replacement}."
        return "Default-resolution layer flags this field for PM review."
    if source:
        return f"Current deterministic model source: {source}."
    return "No reliable deterministic source found yet."


def _missing_data_flags(
    *,
    packets: list[dict[str, Any]],
    workbench: dict[str, Any],
    comps: dict[str, Any],
    segment_rows: list[SegmentDriverRow],
    store_error: str | None = None,
) -> list[MissingDataFlag]:
    flags: list[MissingDataFlag] = []
    if store_error:
        flags.append(
            MissingDataFlag(
                flag_id="store_state_load_error",
                label="Evidence store unavailable",
                severity="high",
                reason=store_error,
                suggested_check="Check SQLite path/schema and rerun the Analyst Prep command.",
                source="pm_decision_queue_store",
            )
        )
    if not segment_rows:
        flags.append(
            MissingDataFlag(
                flag_id="segment_data_missing",
                label="Segment evidence missing",
                severity="medium",
                reason="No deterministic segment rows were found in the current CIQ/SEC payload.",
                suggested_check="Refresh CIQ segment tabs or add SEC segment snippets before relying on mix-shift margin claims.",
                source="segment_driver_rows",
            )
        )
    if not packets:
        flags.append(
            MissingDataFlag(
                flag_id="evidence_packets_missing",
                label="Agent evidence packets missing",
                severity="medium",
                reason="No persisted evidence packets were available for this ticker.",
                suggested_check="Run the company, industry, comps, risk, and valuation profiles.",
                source="evidence_packets",
            )
        )
    lineage = comps.get("source_lineage") or {}
    if lineage.get("source") == "public_market_yfinance_fallback" or "public" in str(lineage.get("source_file") or ""):
        flags.append(
            MissingDataFlag(
                flag_id="public_comps_fallback",
                label="Public comps fallback used",
                severity="medium",
                reason="Comparable company support is from public-market fallback data rather than CIQ comps.",
                suggested_check="Refresh the CIQ template and verify peer set/multiple coverage.",
                source=lineage.get("source_file") or lineage.get("source"),
            )
        )
    for item in (workbench.get("default_resolution") or {}).get("fields") or []:
        if not _default_item_needs_pm_review(item):
            continue
        flags.append(
            MissingDataFlag(
                flag_id=f"default_resolution:{item.get('field')}",
                label=f"{item.get('field')} default needs review",
                severity=str(item.get("severity") or "medium"),
                reason=str(item.get("reason") or "Default-resolution layer flagged this assumption."),
                suggested_check=item.get("preferred_replacement_source"),
                source=item.get("source"),
            )
        )
    return flags


def _comps_card(comps: dict[str, Any]) -> CompsJudgmentCard | None:
    if not comps:
        return None
    peer_counts = comps.get("peer_counts") or {}
    clean_count = peer_counts.get("clean") or peer_counts.get("raw")
    lineage = comps.get("source_lineage") or {}
    quality = "missing"
    if comps.get("available"):
        quality = "partial" if lineage.get("source") == "public_market_yfinance_fallback" else "real"
    primary_metric = comps.get("primary_metric") or comps.get("selected_metric_default")
    target_vs_peers = comps.get("target_vs_peers") or {}
    deltas = target_vs_peers.get("deltas") or {}
    argument = None
    if primary_metric and primary_metric in deltas:
        delta = _safe_float(deltas.get(primary_metric))
        if delta is not None:
            direction = "discount" if delta < 0 else "premium"
            argument = f"Target trades at a {direction} versus peer median on {primary_metric}."
    return CompsJudgmentCard(
        peer_set_quality=quality,
        peer_count=int(clean_count) if clean_count is not None else None,
        primary_metric=primary_metric,
        target_vs_peer_median=target_vs_peers,
        premium_discount_argument=argument,
        exit_multiple_support=(
            f"Primary comps metric {primary_metric} supports reviewing exit_multiple."
            if primary_metric
            else "No primary comps metric available."
        ),
        warnings=list(comps.get("audit_flags") or []),
        evidence_anchor_ids=["deterministic:comps:peer_set"] if comps.get("available") else [],
    )


def _thesis_cards(
    *,
    ticker: str,
    packets: list[dict[str, Any]],
    dcf: dict[str, Any],
    comps: dict[str, Any],
    driver_cards: list[ModelDriverBridgeCard],
    source_quality: str,
) -> list[ThesisBridgeCard]:
    anchors = _packet_anchor_ids(packets)
    if not anchors:
        anchors = ["deterministic:assumption:revenue_growth_near"]
    numeric_refs = [anchor for anchor in anchors if anchor.startswith("packet:")]
    base = _base_scenario(dcf)
    cards: list[ThesisBridgeCard] = []
    base_iv = _safe_float(base.get("intrinsic_value"))
    current_price = _safe_float(dcf.get("current_price"))
    if base_iv is not None and current_price is not None:
        cards.append(
            ThesisBridgeCard(
                card_id=f"{ticker}:valuation_setup",
                title="Valuation Setup",
                claim=(
                    f"Base DCF IV is {base_iv:.2f} versus current price {current_price:.2f} "
                    "(effective model: includes approved PM overrides, so it can differ from the raw pipeline snapshot)."
                ),
                business_evidence_summary="Deterministic DCF bridge provides the starting valuation gap.",
                model_implication="Review revenue growth, margin, WACC, terminal growth, and exit multiple before trusting the spread.",
                linked_assumption_fields=[
                    "revenue_growth_near",
                    "ebit_margin_target",
                    "wacc",
                    "revenue_growth_terminal",
                    "exit_multiple",
                ],
                evidence_anchor_ids=["deterministic:dcf:base_iv", *anchors[:2]],
                numeric_fact_refs=["deterministic:dcf:base_iv", "deterministic:dcf:current_price", *numeric_refs[:2]],
                source_quality=source_quality,
                deterministic_confidence="medium",
                what_would_change_mind="A stale CIQ refresh, unresolved default driver, or rejected PM Queue item would invalidate the spread.",
            )
        )

    review_drivers = [
        card.label
        for card in driver_cards
        if card.pm_review_status in {"review_required", "missing", "conflict"}
    ][:4]
    if review_drivers:
        cards.append(
            ThesisBridgeCard(
                card_id=f"{ticker}:driver_review",
                title="Model Driver Review",
                claim="The main senior-review work is concentrated in " + ", ".join(review_drivers) + ".",
                business_evidence_summary="Driver cards combine deterministic sources, PM Queue proposals, and default-resolution warnings.",
                model_implication="Resolve these drivers before converting the prep pack into approved model changes.",
                linked_assumption_fields=[
                    card.assumption_name
                    for card in driver_cards
                    if card.pm_review_status in {"review_required", "missing", "conflict"}
                ][:4],
                evidence_anchor_ids=[card.evidence_anchor_ids[0] for card in driver_cards if card.evidence_anchor_ids][:4],
                numeric_fact_refs=[],
                source_quality=source_quality,
                deterministic_confidence="medium",
                what_would_change_mind="Accepted PM Queue previews or refreshed CIQ facts that eliminate the warning set.",
            )
        )

    if comps.get("available"):
        peer_count = (comps.get("peer_counts") or {}).get("clean") or (comps.get("peer_counts") or {}).get("raw")
        metric = comps.get("primary_metric") or comps.get("selected_metric_default") or "primary multiple"
        cards.append(
            ThesisBridgeCard(
                card_id=f"{ticker}:comps_support",
                title="Comps Support",
                claim=f"Comps support uses {peer_count or 0} peers and primary metric {metric}.",
                business_evidence_summary="Comparable-company diagnostics show peer coverage, outliers, and target-vs-peer multiple positioning.",
                model_implication="Use the comps card to challenge the exit multiple and triangulate DCF value.",
                linked_assumption_fields=["exit_multiple"],
                evidence_anchor_ids=["deterministic:comps:peer_set"],
                numeric_fact_refs=["deterministic:comps:peer_set"],
                source_quality="partial"
                if (comps.get("source_lineage") or {}).get("source") == "public_market_yfinance_fallback"
                else "real",
                deterministic_confidence="medium",
                counter_evidence="Public fallback comps should not override CIQ comps without manual review."
                if (comps.get("source_lineage") or {}).get("source") == "public_market_yfinance_fallback"
                else None,
                what_would_change_mind="Different peer set, outlier handling, or CIQ comps refresh.",
            )
        )
    return cards


def _segment_driver_rows(ticker: str) -> list[SegmentDriverRow]:
    workbook_path = Path(ROOT_DIR) / "ciq" / "templates" / "ciq_cleandata.xlsx"
    if not workbook_path.exists():
        return []
    try:
        from ciq.workbook_parser import parse_ciq_workbook

        payload = parse_ciq_workbook(workbook_path)
    except Exception:
        return []
    if payload.ticker.upper().strip() != ticker.upper().strip():
        return []
    return _segment_driver_rows_from_records(ticker, payload.long_form_records)


def build_analyst_prep_pack(ticker: str) -> AnalystPrepPack:
    ticker = ticker.upper().strip()
    workbench = build_override_workbench(ticker)
    dcf = build_dcf_audit_view(ticker)
    comps = build_comps_dashboard_view(ticker)
    try:
        research = build_research_board_view(ticker)
    except Exception:
        research = {}
    try:
        effective_inputs = build_valuation_inputs(ticker, apply_overrides=True)
    except Exception:
        effective_inputs = None
    store_error = None
    try:
        packets, queue_items = _load_store_state(ticker)
    except Exception as exc:
        packets, queue_items = [], []
        store_error = str(exc)
    segment_rows = _segment_driver_rows(ticker)
    source_quality = _source_quality_from_packets(
        packets,
        comps_available=bool(comps.get("available")),
        dcf_available=bool(dcf.get("available")),
    )
    conflict_groups = build_pm_decision_queue_conflict_groups(queue_items)
    driver_cards = _driver_cards(workbench, effective_inputs, queue_items, conflict_groups)
    missing_data = _missing_data_flags(
        packets=packets,
        workbench=workbench,
        comps=comps,
        segment_rows=segment_rows,
        store_error=store_error,
    )
    sections = [
        AnalystPrepSection(
            section_id="investment_thesis",
            title="Investment Thesis",
            summary="Prep pack combines deterministic valuation state, evidence packets, PM Queue items, and comps diagnostics.",
            source_quality=source_quality,
            evidence_anchor_ids=_packet_anchor_ids(packets, limit=6),
            warnings=[flag.label for flag in missing_data if flag.severity in {"medium", "high"}],
        ),
        AnalystPrepSection(
            section_id="diligence_queue",
            title="Diligence Queue",
            summary="Inspect missing segment evidence, default-resolution warnings, comps fallback status, and unresolved PM Queue conflicts first.",
            source_quality=source_quality,
            evidence_anchor_ids=[],
            warnings=[group.get("review_note") for group in conflict_groups],
        ),
    ]
    pack = AnalystPrepPack(
        ticker=ticker,
        source_quality=source_quality,
        sections=sections,
        thesis_cards=_thesis_cards(
            ticker=ticker,
            packets=packets,
            dcf=dcf,
            comps=comps,
            driver_cards=driver_cards,
            source_quality=source_quality,
        ),
        driver_cards=driver_cards,
        comps_card=_comps_card(comps),
        missing_data=missing_data,
        segment_driver_rows=segment_rows,
        evidence_packet_ids=[int(packet["packet_id"]) for packet in packets if packet.get("packet_id") is not None],
        evidence_map=_evidence_map(packets, workbench, comps),
        conflict_groups=conflict_groups,
        export_metadata={
            "builder": "src.stage_04_pipeline.analyst_prep_pack",
            "workbench_available": bool(workbench.get("available")),
            "dcf_available": bool(dcf.get("available")),
            "comps_available": bool(comps.get("available")),
            "research_available": bool(research),
            "default_resolution_status": (workbench.get("default_resolution") or {}).get("status"),
            "ciq_lineage": workbench.get("ciq_lineage") or {},
            "store_error": store_error,
        },
    )
    return pack


def build_analyst_prep_payload(ticker: str) -> dict[str, Any]:
    return build_analyst_prep_pack(ticker).model_dump(mode="json")


def render_analyst_prep_markdown(pack_or_payload: AnalystPrepPack | dict[str, Any]) -> str:
    pack = (
        pack_or_payload
        if isinstance(pack_or_payload, AnalystPrepPack)
        else AnalystPrepPack.model_validate(pack_or_payload)
    )
    lines = [
        f"# Analyst Prep Pack - {pack.ticker}",
        "",
        f"- Generated: {pack.generated_at}",
        f"- Source quality: {pack.source_quality}",
        f"- Evidence packets: {len(pack.evidence_packet_ids)}",
        f"- Missing flags: {len(pack.missing_data)}",
        "",
        "## Thesis Cards",
    ]
    for card in pack.thesis_cards:
        lines.extend(
            [
                f"### {card.title}",
                f"- Claim: {card.claim}",
                f"- Model implication: {card.model_implication}",
                f"- Linked fields: {', '.join(card.linked_assumption_fields) or 'none'}",
                f"- Anchors: {', '.join(card.evidence_anchor_ids)}",
                f"- What would change mind: {card.what_would_change_mind or 'n/a'}",
                "",
            ]
        )
    lines.append("## Model Driver Map")
    for card in pack.driver_cards:
        lines.append(
            f"- {card.assumption_name}: current={card.current_value}, proposed/effective={card.proposed_or_effective_value}, status={card.pm_review_status}, source={card.source}"
        )
    lines.extend(["", "## Missing Data"])
    for flag in pack.missing_data:
        lines.append(f"- [{flag.severity}] {flag.label}: {flag.reason}")
    lines.extend(["", "## Raw JSON", "```json", json.dumps(pack.model_dump(mode="json"), indent=2), "```"])
    return "\n".join(lines) + "\n"
