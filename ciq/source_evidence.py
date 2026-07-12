"""Deterministic evidence-layer projections for CIQ source facts.

The immutable SQLite fact table intentionally preserves the existing schema.
This module projects those facts into an explicit audit contract without
changing their storage grain or silently treating formula caches as refreshed
facts.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any


SOURCE_EVIDENCE_SCHEMA_VERSION = "ciq_source_evidence_v1"


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    data = getattr(value, "__dict__", None)
    if isinstance(data, Mapping):
        return data
    return {}


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _repair_index(repair_ledger: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not repair_ledger:
        return {}
    rows = repair_ledger.get("repairs") or repair_ledger.get("entries") or repair_ledger.get("ledger") or ()
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in rows:
        row = _mapping(item)
        locator = str(
            row.get("cell_locator")
            or row.get("source_locator")
            or (
                f"{row.get('sheet')}!{row.get('cell')}"
                if row.get("sheet") and row.get("cell")
                else ""
            )
        ).strip()
        if locator:
            indexed[locator] = row
    return indexed


def _consumer_index(
    downstream_consumers: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if not downstream_consumers:
        return {}
    return {
        str(locator): tuple(sorted({str(item) for item in consumers if str(item)}))
        for locator, consumers in downstream_consumers.items()
    }


def build_source_evidence_records(
    source_facts: Iterable[Mapping[str, Any]],
    *,
    source_hash: str,
    run_id: int | None,
    source_refresh_timestamp: str | None,
    repair_ledger: Mapping[str, Any] | None = None,
    downstream_consumers: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, Any]]:
    """Project cell facts into explicit raw, normalized, and formula layers."""

    repairs = _repair_index(repair_ledger)
    consumers = _consumer_index(downstream_consumers)
    records: list[dict[str, Any]] = []
    ordered = sorted(
        source_facts,
        key=lambda row: (
            str(row.get("sheet_name") or ""),
            int(row.get("row_index") or 0),
            int(row.get("column_index") or 0),
        ),
    )
    for row in ordered:
        locator = str(row.get("cell_locator") or "").strip()
        repair = repairs.get(locator, {})
        scale = _number(row.get("scale_factor"))
        scale = 1.0 if scale is None else scale
        parsed_value = _number(row.get("value_num"))
        normalized_value = parsed_value
        has_formula = bool(row.get("has_formula"))
        unit = row.get("unit")
        original_formula = repair.get("original_formula") or row.get("formula_text")
        repaired_formula = repair.get("repaired_formula")
        formula_status = str(row.get("formula_status") or "unknown")
        if parsed_value is None:
            transformation_rule = "numeric_value_unavailable"
        elif scale == 1.0:
            transformation_rule = "numeric_cast;scale_identity"
        else:
            transformation_rule = f"numeric_cast;retain_source_display_scale:{scale:g}"

        records.append(
            {
                "schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
                "evidence_layer": "source_cell",
                "ticker": row.get("ticker"),
                "run_id": run_id,
                "source_hash": source_hash,
                "raw_cached_value": row.get("cached_value"),
                "normalized_model_value": normalized_value,
                "derived_value": None,
                "transformation_rule": transformation_rule,
                "sign_rule": "source_sign_preserved",
                "source_formula": original_formula,
                "repaired_formula": repaired_formula,
                "formula_error_state": {
                    "status": formula_status,
                    "formula_error": row.get("formula_error"),
                    "cached_error": row.get("cached_error"),
                    "has_formula": has_formula,
                    "has_cached_value": bool(row.get("has_cached_value")),
                    "refresh_verification": repair.get("refresh_verification")
                    or repair.get("refresh_verification_status")
                    or repair.get("refresh_status")
                    or "not_applicable",
                },
                "unit": unit,
                "unit_provenance": "source_parser" if unit else "source_unit_unavailable",
                "scale": scale,
                "scale_provenance": (
                    "source_parser"
                    if unit
                    else "parser_scale_without_unit_contract_unverified"
                ),
                "source_period": row.get("period_date"),
                "source_period_end": row.get("period_date"),
                "source_refresh_timestamp": source_refresh_timestamp,
                "exact_source_locator": locator,
                "source_row_id": row.get("source_row_id"),
                "row_label": row.get("row_label"),
                "downstream_consumers": list(consumers.get(locator, ())),
            }
        )
    return records


def index_source_evidence(records: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("exact_source_locator")): row
        for row in records
        if row.get("exact_source_locator")
    }


def build_model_evidence_records(
    lineage: Iterable[Any],
    *,
    source_evidence: Iterable[Mapping[str, Any]],
    unit_by_canonical_key: Mapping[str, str] | None = None,
    source_refresh_timestamp: str | None = None,
) -> list[dict[str, Any]]:
    """Project historical lineage into direct/derived normalized model evidence."""

    source_by_locator = index_source_evidence(source_evidence)
    units = unit_by_canonical_key or {}
    output: list[dict[str, Any]] = []
    ordered = sorted(
        lineage,
        key=lambda item: (
            str(_field(item, "canonical_key") or ""),
            str(_field(item, "period_key") or ""),
        ),
    )
    for item in ordered:
        canonical_key = str(_field(item, "canonical_key") or "")
        method_id = str(_field(item, "method_id") or "unknown")
        refs = tuple(_field(item, "source_refs", ()) or ())
        locators = [str(_field(ref, "cell_locator") or "") for ref in refs]
        source_rows = [source_by_locator[locator] for locator in locators if locator in source_by_locator]
        formulas = [row.get("source_formula") for row in source_rows if row.get("source_formula")]
        repaired = [row.get("repaired_formula") for row in source_rows if row.get("repaired_formula")]
        formula_states = [row.get("formula_error_state") for row in source_rows]
        raw_cached = [row.get("raw_cached_value") for row in source_rows]
        scales = sorted({row.get("scale") for row in source_rows if row.get("scale") is not None})
        periods = sorted({str(row.get("source_period")) for row in source_rows if row.get("source_period")})
        period_ends = sorted(
            {str(row.get("source_period_end")) for row in source_rows if row.get("source_period_end")}
        )
        normalized = _field(item, "normalized_value")
        derived = normalized if method_id == "historical:derived" else None
        formula_id = _field(item, "formula_id")
        output.append(
            {
                "schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
                "evidence_layer": "normalized_model_line",
                "canonical_key": canonical_key,
                "period_key": _field(item, "period_key"),
                "method_id": method_id,
                "raw_cached_value": raw_cached,
                "normalized_model_value": normalized,
                "derived_value": derived,
                "transformation_rule": formula_id or method_id,
                "sign_rule": _field(item, "normalization_rule", "not_available"),
                "source_formula": formulas or ([formula_id] if formula_id else []),
                "repaired_formula": repaired,
                "formula_error_state": formula_states,
                "unit": units.get(canonical_key),
                "scale": scales,
                "source_period": periods,
                "source_period_end": period_ends,
                "source_refresh_timestamp": source_refresh_timestamp,
                "exact_source_locator": locators,
                "downstream_consumers": [canonical_key],
            }
        )
    return output


def summarize_evidence_layers(
    source_records: Iterable[Mapping[str, Any]],
    model_records: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    raw = list(source_records)
    model = list(model_records)
    return {
        "source_cell_count": len(raw),
        "source_formula_cell_count": sum(
            bool(row.get("formula_error_state", {}).get("has_formula")) for row in raw
        ),
        "source_repaired_formula_count": sum(bool(row.get("repaired_formula")) for row in raw),
        "source_unit_available_count": sum(row.get("unit") is not None for row in raw),
        "source_unit_unavailable_count": sum(row.get("unit") is None for row in raw),
        "source_scale_verified_count": sum(
            row.get("scale_provenance") == "source_parser" for row in raw
        ),
        "source_scale_unverified_count": sum(
            row.get("scale_provenance") != "source_parser" for row in raw
        ),
        "source_period_available_count": sum(row.get("source_period") is not None for row in raw),
        "source_period_unavailable_count": sum(
            row.get("source_period") is None for row in raw
        ),
        "model_line_count": len(model),
        "model_direct_value_count": sum(row.get("method_id") == "historical:direct" for row in model),
        "model_derived_value_count": sum(row.get("method_id") == "historical:derived" for row in model),
        "model_sign_normalized_count": sum(
            row.get("method_id") == "historical:direct"
            and row.get("sign_rule") not in {"source_sign_preserved", "not_available"}
            for row in model
        ),
    }


__all__ = [
    "SOURCE_EVIDENCE_SCHEMA_VERSION",
    "build_model_evidence_records",
    "build_source_evidence_records",
    "index_source_evidence",
    "summarize_evidence_layers",
]
