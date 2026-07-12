from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from src.contracts.assumption_register import (
    AuditDiff,
    AssumptionApprovalState,
    AssumptionEntityType,
    AssumptionOwner,
    AssumptionRegister,
    AssumptionRegisterEntry,
    AssumptionValueType,
    FLAG_SEVERITY,
    FlagLevel,
    ModelTrustState,
)


FIELD_METADATA: dict[str, dict[str, Any]] = {
    "revenue_base": {"stage": "input_assembly", "scope": "growth", "lines": ["revenue", "fcff", "enterprise_value", "equity_value"], "class": "money"},
    "revenue_growth_near": {"stage": "input_assembly", "scope": "growth", "lines": ["revenue", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "revenue_growth_mid": {"stage": "input_assembly", "scope": "growth", "lines": ["revenue", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "revenue_growth_terminal": {"stage": "terminal_value", "scope": "terminal_value", "lines": ["terminal_value", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "ebit_margin_start": {"stage": "input_assembly", "scope": "margin", "lines": ["ebit", "nopat", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "ebit_margin_target": {"stage": "dcf", "scope": "margin", "lines": ["ebit", "nopat", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "tax_rate_start": {"stage": "input_assembly", "scope": "tax", "lines": ["nopat", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "tax_rate_target": {"stage": "dcf", "scope": "tax", "lines": ["nopat", "fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "capex_pct_start": {"stage": "input_assembly", "scope": "reinvestment", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "capex_pct_target": {"stage": "dcf", "scope": "reinvestment", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "da_pct_start": {"stage": "input_assembly", "scope": "reinvestment", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "da_pct_target": {"stage": "dcf", "scope": "reinvestment", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "dso_start": {"stage": "input_assembly", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "dso_target": {"stage": "dcf", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "dio_start": {"stage": "input_assembly", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "dio_target": {"stage": "dcf", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "dpo_start": {"stage": "input_assembly", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "dpo_target": {"stage": "dcf", "scope": "working_capital", "lines": ["fcff", "enterprise_value", "equity_value"], "class": "days"},
    "wacc": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "wacc"},
    "cost_of_equity": {"stage": "wacc", "scope": "wacc", "lines": ["equity_value"], "class": "wacc_component_rate"},
    "risk_free_rate": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "wacc_component_rate"},
    "equity_risk_premium": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "wacc_component_rate"},
    "beta_relevered": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "beta"},
    "beta_unlevered_median": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "beta"},
    "size_premium": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "wacc_component_rate"},
    "cost_of_debt": {"stage": "wacc", "scope": "wacc", "lines": ["enterprise_value", "equity_value"], "class": "wacc_component_rate"},
    "equity_weight": {"stage": "wacc", "scope": "capital_structure", "lines": ["enterprise_value", "equity_value"], "class": "capital_structure_weight"},
    "debt_weight": {"stage": "wacc", "scope": "capital_structure", "lines": ["enterprise_value", "equity_value"], "class": "capital_structure_weight"},
    "exit_multiple": {"stage": "terminal_value", "scope": "terminal_value", "lines": ["terminal_value", "enterprise_value", "equity_value"], "class": "multiple"},
    "terminal_blend_gordon_weight": {"stage": "terminal_value", "scope": "terminal_value", "lines": ["terminal_value", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "terminal_blend_exit_weight": {"stage": "terminal_value", "scope": "terminal_value", "lines": ["terminal_value", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "ronic_terminal": {"stage": "terminal_value", "scope": "terminal_value", "lines": ["terminal_value", "enterprise_value", "equity_value"], "class": "pct_driver"},
    "net_debt": {"stage": "input_assembly", "scope": "capital_structure", "lines": ["equity_value"], "class": "money"},
    "shares_outstanding": {"stage": "input_assembly", "scope": "capital_structure", "lines": ["equity_value"], "class": "money"},
}

RANGE_RULES: dict[str, dict[str, Any]] = {
    "revenue_base": {"low": 1.0, "high": None, "description": "Revenue base should be positive."},
    "revenue_growth_near": {"low": -0.20, "high": 0.30, "description": "Default PM review range for near-term revenue growth."},
    "revenue_growth_mid": {"low": -0.15, "high": 0.25, "description": "Default PM review range for mid-term revenue growth."},
    "revenue_growth_terminal": {"low": 0.00, "high": 0.04, "description": "Terminal growth capped at long-run nominal GDP growth (4%)."},
    "ebit_margin_start": {"low": -0.10, "high": 0.45, "description": "Default PM review range for starting EBIT margin."},
    "ebit_margin_target": {"low": -0.05, "high": 0.50, "description": "Default PM review range for target EBIT margin."},
    "tax_rate_start": {"low": 0.00, "high": 0.40, "description": "Default PM review range for effective tax rate."},
    "tax_rate_target": {"low": 0.00, "high": 0.40, "description": "Default PM review range for target tax rate."},
    "capex_pct_start": {"low": 0.00, "high": 0.30, "description": "Default PM review range for capex as percent of revenue."},
    "capex_pct_target": {"low": 0.00, "high": 0.30, "description": "Default PM review range for target capex as percent of revenue."},
    "da_pct_start": {"low": 0.00, "high": 0.25, "description": "Default PM review range for D&A as percent of revenue."},
    "da_pct_target": {"low": 0.00, "high": 0.25, "description": "Default PM review range for target D&A as percent of revenue."},
    "dso_start": {"low": 0.0, "high": 180.0, "description": "Default PM review range for days sales outstanding."},
    "dso_target": {"low": 0.0, "high": 180.0, "description": "Default PM review range for target DSO."},
    "dio_start": {"low": 0.0, "high": 240.0, "description": "Default PM review range for days inventory outstanding."},
    "dio_target": {"low": 0.0, "high": 240.0, "description": "Default PM review range for target DIO."},
    "dpo_start": {"low": 0.0, "high": 240.0, "description": "Default PM review range for days payables outstanding."},
    "dpo_target": {"low": 0.0, "high": 240.0, "description": "Default PM review range for target DPO."},
    "wacc": {"low": 0.04, "high": 0.20, "description": "Default PM review range for WACC."},
    "cost_of_equity": {"low": 0.04, "high": 0.30, "description": "Default PM review range for cost of equity."},
    "risk_free_rate": {"low": 0.00, "high": 0.10, "description": "Default PM review range for risk-free rate."},
    "equity_risk_premium": {"low": 0.02, "high": 0.10, "description": "Default PM review range for equity risk premium."},
    "beta_relevered": {"low": 0.20, "high": 3.00, "description": "Default PM review range for relevered beta."},
    "beta_unlevered_median": {"low": 0.20, "high": 3.00, "description": "Default PM review range for unlevered beta."},
    "size_premium": {
        "low": -0.001,
        "high": 0.08,
        "description": "PM review range for size premium; CRSP mega-cap deciles can be mildly negative.",
    },
    "cost_of_debt": {"low": 0.00, "high": 0.20, "description": "Default PM review range for pre-tax cost of debt."},
    "equity_weight": {"low": 0.20, "high": 1.00, "description": "Default PM review range for equity weight."},
    "debt_weight": {"low": 0.00, "high": 0.80, "description": "Default PM review range for debt weight."},
    "exit_multiple": {"low": 2.0, "high": 30.0, "description": "Default PM review range for terminal exit multiple."},
    "terminal_blend_gordon_weight": {"low": 0.0, "high": 1.0, "description": "Gordon terminal blend weight should be a probability-like weight."},
    "terminal_blend_exit_weight": {"low": 0.0, "high": 1.0, "description": "Exit terminal blend weight should be a probability-like weight."},
    "ronic_terminal": {"low": 0.00, "high": 0.40, "description": "Default PM review range for terminal RONIC."},
    "net_debt": {"low": None, "high": None, "description": "Capital-structure money field retained for review and audit."},
    "shares_outstanding": {"low": 1.0, "high": None, "description": "Share count should be positive."},
}

MATERIALITY_RULES: dict[str, dict[str, Any]] = {
    "wacc": {"threshold": 0.0025, "description": "25 bps WACC movement."},
    "wacc_component_rate": {"threshold": 0.0025, "description": "25 bps WACC component movement."},
    "beta": {"threshold": 0.10, "description": "0.10 beta point movement."},
    "capital_structure_weight": {"threshold": 0.05, "description": "5 percentage point capital structure movement."},
    "pct_driver": {"threshold": 0.005, "description": "50 bps percentage-driver movement."},
    "multiple": {"threshold": 0.5, "description": "0.5x multiple movement."},
    "days": {"threshold": 5.0, "description": "5 day working-capital movement."},
    "money": {"threshold": 10_000_000.0, "revenue_ratio": 0.01, "description": "Greater of USD 10m or 1% of revenue base."},
}

AUDIT_ALWAYS_MATERIAL_FIELDS = {
    "flag_level",
    "source_lineage",
    "owner",
    "approval_state",
    "approval_ref",
    "range_rule_id",
    "range_rule_description",
}

REVIEW_RELEVANT_FLAGS = {FlagLevel.watch, FlagLevel.review_required, FlagLevel.critical}
CRITICAL_DIAGNOSTICS = {
    "health_terminal_denominator_guardrail_flag",
    "terminal_denominator_guardrail_flag",
    "health_terminal_growth_guardrail_flag",
    "terminal_growth_guardrail_flag",
    "health_terminal_ronic_guardrail_flag",  # RONIC ≤ terminal_growth — mathematically invalid
    "forensic_flag_severe",                  # Beneish M-Score in manipulator zone (red)
}
REVIEW_DIAGNOSTICS = {
    "tv_high_flag",
    "health_tv_extreme_flag",
    "tv_extreme_flag",
    "wacc_method_spread_high",  # ≥150bps spread across WACC methods
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drivers_payload(inputs: Any) -> dict[str, Any]:
    drivers = getattr(inputs, "drivers", None)
    if drivers is None:
        return {}
    if is_dataclass(drivers):
        return asdict(drivers)
    if isinstance(drivers, dict):
        return dict(drivers)
    return {
        key: getattr(drivers, key)
        for key in FIELD_METADATA
        if hasattr(drivers, key)
    }


def _normalise_source(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {"source": "unknown"}
    return {"source": str(value)}


def _is_pm_override(source_lineage: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in source_lineage.values()).lower()
    return "override" in text or "pm_approved" in text


def _approval_ref(source_lineage: dict[str, Any]) -> str | None:
    for key in ("approval_ref", "audit_ref", "override_audit_ref", "wacc_methodology_audit_ref"):
        value = source_lineage.get(key)
        if value:
            return str(value)
    return None


def _rule_for(name: str) -> dict[str, Any]:
    return RANGE_RULES.get(name, {"low": None, "high": None, "description": "No V1 range rule configured."})


def _flag_for_value(name: str, value: float, low: float | None, high: float | None, diagnostics: dict[str, Any]) -> FlagLevel:
    if math.isnan(value) or math.isinf(value):
        return FlagLevel.critical
    if name == "wacc" and value <= 0:
        return FlagLevel.critical
    if name == "revenue_growth_terminal":
        wacc = diagnostics.get("wacc")
        if isinstance(wacc, (int, float)) and value >= float(wacc):
            return FlagLevel.critical
        if value > 0.05:
            return FlagLevel.critical
    if low is not None and value < low:
        return FlagLevel.review_required
    if high is not None and value > high:
        return FlagLevel.review_required
    if low is not None and high is not None and high > low:
        band = high - low
        if value < low + band * 0.10 or value > high - band * 0.10:
            return FlagLevel.watch
    return FlagLevel.none


def _entry_payload(
    *,
    ticker: str,
    name: str,
    value: Any,
    source_lineage: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    current_value = float(value)
    metadata = FIELD_METADATA[name]
    rule = _rule_for(name)
    lineage = _normalise_source(source_lineage.get(name))
    if name in {"risk_free_rate", "equity_risk_premium"} and name not in source_lineage:
        lineage = _normalise_source(source_lineage.get("risk_free_rate"))
    owner = AssumptionOwner.pm_override if _is_pm_override(lineage) else AssumptionOwner.deterministic
    approval_ref = _approval_ref(lineage)
    approval_state = AssumptionApprovalState.pm_approved if owner == AssumptionOwner.pm_override else AssumptionApprovalState.none
    flag = _flag_for_value(name, current_value, rule.get("low"), rule.get("high"), diagnostics)
    if flag in {FlagLevel.review_required, FlagLevel.critical} and approval_state == AssumptionApprovalState.none:
        approval_state = AssumptionApprovalState.review_required
    return {
        "entity_type": AssumptionEntityType.ticker,
        "entity_id": ticker,
        "ticker": ticker,
        "assumption_name": name,
        "scope": metadata["scope"],
        "stage": metadata["stage"],
        "value_type": AssumptionValueType.numeric,
        "current_value": current_value,
        "accepted_low": rule.get("low"),
        "accepted_high": rule.get("high"),
        "range_rule_id": f"{name}_v1_static",
        "range_rule_description": rule["description"],
        "source_lineage": lineage,
        "affected_forecast_lines": metadata["lines"],
        "flag_level": flag,
        "owner": owner,
        "approval_state": approval_state,
        "approval_ref": approval_ref,
        "valuation_impact": None,
        "evidence_refs": [],
        "advisory_refs": [],
        "notes": {},
    }


def _wacc_payloads(inputs: Any, drivers: dict[str, Any]) -> dict[str, Any]:
    raw = getattr(inputs, "wacc_inputs", None) or {}
    out = {
        "wacc": drivers.get("wacc", raw.get("wacc")),
        "cost_of_equity": raw.get("cost_of_equity", drivers.get("cost_of_equity")),
        "risk_free_rate": raw.get("risk_free_rate", drivers.get("risk_free_rate")),
        "equity_risk_premium": raw.get("equity_risk_premium", drivers.get("equity_risk_premium")),
        "beta_relevered": raw.get("beta_relevered"),
        "beta_unlevered_median": raw.get("beta_unlevered_median"),
        "size_premium": raw.get("size_premium", drivers.get("size_premium")),
        "cost_of_debt": raw.get("cost_of_debt", drivers.get("cost_of_debt")),
        "equity_weight": raw.get("equity_weight"),
        "debt_weight": raw.get("debt_weight", drivers.get("debt_weight")),
    }
    if out["equity_weight"] is None and isinstance(out["debt_weight"], (int, float)):
        out["equity_weight"] = 1.0 - float(out["debt_weight"])
    if out["debt_weight"] is None and isinstance(out["equity_weight"], (int, float)):
        out["debt_weight"] = 1.0 - float(out["equity_weight"])
    return out


def _apply_diagnostic_rollup(register: AssumptionRegister, diagnostics: dict[str, Any]) -> AssumptionRegister:
    max_flag = register.max_flag_level
    diagnostic_notes: list[str] = []
    if any(bool(diagnostics.get(key)) for key in CRITICAL_DIAGNOSTICS):
        max_flag = FlagLevel.critical
        diagnostic_notes.append("critical_terminal_guardrail")
    elif any(bool(diagnostics.get(key)) for key in REVIEW_DIAGNOSTICS):
        if FLAG_SEVERITY[max_flag] < FLAG_SEVERITY[FlagLevel.review_required]:
            max_flag = FlagLevel.review_required
        diagnostic_notes.append("terminal_concentration_or_extreme_tv")
    elif diagnostics.get("tv_pct_of_ev") is not None:
        try:
            tv_pct = float(diagnostics["tv_pct_of_ev"])
            if tv_pct > 0.70 and FLAG_SEVERITY[max_flag] < FLAG_SEVERITY[FlagLevel.watch]:
                max_flag = FlagLevel.watch
                diagnostic_notes.append("elevated_terminal_concentration")
        except (TypeError, ValueError):
            pass
    if max_flag == register.max_flag_level:
        if diagnostics.get("regime_weights_applied"):
            current_notes = dict(register.notes or {})
            current_notes["regime_label"] = diagnostics.get("regime_label") or "unknown"
            current_notes["regime_weights_applied"] = True
            object.__setattr__(register, "notes", current_notes)
        return register
    object.__setattr__(register, "max_flag_level", max_flag)
    object.__setattr__(register, "has_critical", max_flag == FlagLevel.critical)
    trust_state = (
        ModelTrustState.critical_review_required.value
        if max_flag == FlagLevel.critical
        else ModelTrustState.review_required.value
        if max_flag == FlagLevel.review_required
        else ModelTrustState.watch.value
    )
    object.__setattr__(register, "model_trust_state", ModelTrustState(trust_state))
    object.__setattr__(register, "summary", {
        **register.summary,
        "model_trust_state": trust_state,
        "max_flag_level": max_flag.value,
        "has_critical": max_flag == FlagLevel.critical,
        "diagnostic_notes": diagnostic_notes,
    })

    if diagnostics.get("regime_weights_applied"):
        current_notes = dict(register.notes or {})
        current_notes["regime_label"] = diagnostics.get("regime_label") or "unknown"
        current_notes["regime_weights_applied"] = True
        object.__setattr__(register, "notes", current_notes)

    return register


def build_assumption_register(ticker: str, inputs: Any, diagnostics: dict[str, Any] | None = None) -> AssumptionRegister:
    ticker = ticker.upper().strip()
    diagnostics = dict(diagnostics or {})
    drivers = _drivers_payload(inputs)
    source_lineage = dict(getattr(inputs, "source_lineage", None) or {})
    wacc_values = _wacc_payloads(inputs, drivers)
    diagnostics.setdefault("wacc", wacc_values.get("wacc") or drivers.get("wacc"))

    payloads: list[dict[str, Any]] = []
    for name in FIELD_METADATA:
        value = wacc_values.get(name) if name in wacc_values else drivers.get(name)
        payload = _entry_payload(
            ticker=ticker,
            name=name,
            value=value,
            source_lineage=source_lineage,
            diagnostics=diagnostics,
        )
        if payload is None:
            continue
        if name in wacc_values:
            selected = (getattr(inputs, "wacc_inputs", None) or {}).get("selected_methodology")
            if selected:
                payload["notes"]["selected_methodology"] = selected
        payloads.append(payload)

    register = AssumptionRegister.model_validate(
        {
            "ticker": ticker,
            "generated_at": _now(),
            "entries": payloads,
        }
    )
    return _apply_diagnostic_rollup(register, diagnostics)


def summarize_assumption_register(register: AssumptionRegister | dict[str, Any] | None) -> dict[str, Any]:
    if register is None:
        return {
            "model_trust_state": ModelTrustState.clean.value,
            "flag_counts": {level.value: 0 for level in FlagLevel},
            "max_flag_level": FlagLevel.none.value,
            "flagged_entries": [],
        }
    if isinstance(register, dict):
        register = AssumptionRegister.model_validate(register)
    flagged_entries = []
    for entry in register.entries:
        if entry.flag_level == FlagLevel.none:
            continue
        flagged_entries.append(
            {
                "assumption_name": entry.assumption_name,
                "scope": entry.scope,
                "stage": entry.stage,
                "current_value": entry.current_value,
                "accepted_low": entry.accepted_low,
                "accepted_high": entry.accepted_high,
                "flag_level": entry.flag_level.value,
                "approval_state": entry.approval_state.value,
                "source_lineage": entry.source_lineage,
                "out_of_range": entry.out_of_range,
            }
        )
    return {
        "model_trust_state": register.model_trust_state.value,
        "flag_counts": register.flag_counts,
        "max_flag_level": register.max_flag_level.value,
        "has_critical": register.has_critical,
        "flagged_entries": flagged_entries,
    }


def _entry_map(register: AssumptionRegister | dict[str, Any] | list[dict[str, Any]]) -> dict[str, AssumptionRegisterEntry]:
    if isinstance(register, AssumptionRegister):
        entries = register.entries
    elif isinstance(register, dict):
        entries = AssumptionRegister.model_validate(register).entries
    else:
        entries = [AssumptionRegisterEntry.model_validate(item) for item in register]
    return {entry.assumption_name: entry for entry in entries}


def _material_threshold(entry: AssumptionRegisterEntry, revenue_base: float | None = None) -> float:
    field_class = FIELD_METADATA.get(entry.assumption_name, {}).get("class", "pct_driver")
    rule = MATERIALITY_RULES.get(field_class, MATERIALITY_RULES["pct_driver"])
    if field_class == "money":
        revenue_threshold = abs(float(revenue_base or 0.0)) * float(rule.get("revenue_ratio", 0.0))
        return max(float(rule["threshold"]), revenue_threshold)
    return float(rule["threshold"])


def _changed_fields(previous: AssumptionRegisterEntry | None, current: AssumptionRegisterEntry) -> dict[str, dict[str, Any]]:
    if previous is None:
        return {
            "flag_level": {"prior": None, "new": current.flag_level.value},
            "current_value": {"prior": None, "new": current.current_value},
        }
    changes: dict[str, dict[str, Any]] = {}
    for field in AUDIT_ALWAYS_MATERIAL_FIELDS:
        prior_value = getattr(previous, field)
        new_value = getattr(current, field)
        if hasattr(prior_value, "value"):
            prior_value = prior_value.value
        if hasattr(new_value, "value"):
            new_value = new_value.value
        if prior_value != new_value:
            changes[field] = {"prior": prior_value, "new": new_value}
    return changes


def diff_assumption_register_entries(
    previous: AssumptionRegister | dict[str, Any] | list[dict[str, Any]],
    current: AssumptionRegister | dict[str, Any] | list[dict[str, Any]],
    *,
    actor: str = "system",
    actor_type: str = "system",
    revenue_base: float | None = None,
) -> list[AuditDiff]:
    previous_by_name = _entry_map(previous)
    current_by_name = _entry_map(current)
    diffs: list[AuditDiff] = []
    for name, current_entry in current_by_name.items():
        previous_entry = previous_by_name.get(name)
        changed = _changed_fields(previous_entry, current_entry)
        event_type = "first_seen"
        reason = None
        if previous_entry is not None:
            event_type = "metadata_changed" if changed else "value_changed"
            delta = abs(current_entry.current_value - previous_entry.current_value)
            if delta >= _material_threshold(current_entry, revenue_base=revenue_base):
                changed["current_value"] = {
                    "prior": previous_entry.current_value,
                    "new": current_entry.current_value,
                    "delta": delta,
                }
                event_type = "value_changed"
                if previous_entry.approval_state == AssumptionApprovalState.pm_approved:
                    changed["approval_state"] = {
                        "prior": AssumptionApprovalState.pm_approved.value,
                        "new": AssumptionApprovalState.stale_approval.value,
                    }
            elif not changed:
                continue
        elif current_entry.flag_level not in REVIEW_RELEVANT_FLAGS and current_entry.approval_state not in {
            AssumptionApprovalState.review_required,
            AssumptionApprovalState.stale_approval,
        }:
            continue
        if "flag_level" in changed:
            event_type = "flag_changed"
        if "approval_state" in changed or current_entry.approval_state == AssumptionApprovalState.stale_approval:
            reason = "approval_state_changed"
        diffs.append(
            AuditDiff.model_validate(
                {
                    "actor": actor,
                    "actor_type": actor_type,
                    "entity_type": current_entry.entity_type,
                    "entity_id": current_entry.entity_id,
                    "ticker": current_entry.ticker,
                    "assumption_name": current_entry.assumption_name,
                    "scope": current_entry.scope,
                    "event_type": event_type,
                    "changed_fields": changed,
                    "valuation_impact": current_entry.valuation_impact,
                    "reason": reason,
                }
            )
        )
    return diffs
