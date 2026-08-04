"""Read active PM driver-family approvals and adapt them for deterministic DCFs.

Driver-family approvals are intentionally not copied into the scalar assumption
register.  This module therefore reads the queue item's approved pack directly,
which is the persistence contract written by the family approval path.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
import json
import sqlite3
from typing import Mapping

from src.contracts.assumption_registry import judgment_owned_fields
from src.contracts.pm_decision_queue import AssumptionChangePack
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_04_pipeline.driver_family_queue import (
    approved_scenario_values_from_queue_pack,
)


DCF_SCENARIO_FOR_APPROVED_CASE = {
    "low": "bear",
    "base": "base",
    "high": "bull",
}


@dataclass(frozen=True, slots=True)
class ApprovedDriverFamilyApproval:
    """One active, structurally validated approval read from the PM queue."""

    item_id: int
    pack_id: str
    family: str
    approval_fingerprint: str
    scenario_values: dict[str, dict[str, float]]


@dataclass(frozen=True, slots=True)
class ApprovedDriverFamilyResolution:
    """Resolved base and bear/base/bull drivers for one ticker run."""

    base_drivers: ForecastDrivers
    dcf_scenario_drivers: dict[str, ForecastDrivers] | None
    source_lineage: dict[str, str]
    approvals: tuple[ApprovedDriverFamilyApproval, ...]


def load_active_approved_driver_family_packs(
    conn: sqlite3.Connection,
    ticker: str,
) -> tuple[ApprovedDriverFamilyApproval, ...]:
    """Load the newest active approved pack for each driver family.

    The queue's ``approved_proposal_pack_json`` is authoritative for this
    workflow.  ``approved_assumption_entries`` is deliberately not consulted:
    the atomic family approval path creates no scalar rows.  Rows with any
    other status, including ``superseded``, are excluded by the SQL predicate.
    If historical data left two rows approved for one family, newest queue id
    wins; normal approval flow marks the previous row superseded.
    """

    normalized_ticker = str(ticker).strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")

    rows = conn.execute(
        """
        SELECT id, approved_proposal_pack_json, adapter_links_json
        FROM pm_decision_queue_items
        WHERE ticker = ?
          AND status = 'approved'
          AND item_type = 'assumption_change_pack'
          AND approved_proposal_pack_json IS NOT NULL
        ORDER BY id DESC
        """,
        (normalized_ticker,),
    ).fetchall()

    approvals: list[ApprovedDriverFamilyApproval] = []
    seen_families: set[str] = set()
    for row in rows:
        item_id = int(row[0])
        try:
            pack_payload = json.loads(str(row[1]))
            pack = AssumptionChangePack.model_validate(pack_payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"approved driver-family queue item {item_id} is invalid"
            ) from exc

        if pack.family is None:
            continue
        family = pack.family.value
        if family in seen_families:
            continue
        seen_families.add(family)

        if pack.critic_verdict != "accept":
            raise ValueError(
                f"approved driver-family queue item {item_id} lacks critic acceptance"
            )
        try:
            adapter_links = json.loads(str(row[2] or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"approved driver-family queue item {item_id} has invalid adapter links"
            ) from exc
        fingerprint = str((adapter_links or {}).get("approval_fingerprint") or "").strip()
        if not fingerprint:
            raise ValueError(
                f"approved driver-family queue item {item_id} lacks approval fingerprint"
            )

        approvals.append(
            ApprovedDriverFamilyApproval(
                item_id=item_id,
                pack_id=pack.pack_id,
                family=family,
                approval_fingerprint=fingerprint,
                scenario_values=approved_scenario_values_from_queue_pack(pack),
            )
        )
    return tuple(approvals)


def resolve_approved_driver_family_packs(
    conn: sqlite3.Connection,
    ticker: str,
    base_drivers: ForecastDrivers,
    source_lineage: Mapping[str, str],
) -> ApprovedDriverFamilyResolution:
    """Apply active family approvals after ordinary input precedence resolves.

    The approved base values replace the assembled base drivers.  The same
    pack's low/base/high values become bear/base/bull driver sets respectively,
    while the DCF still applies its existing scenario shocks to each set.
    """

    approvals = load_active_approved_driver_family_packs(conn, ticker)
    lineage = dict(source_lineage)
    if not approvals:
        return ApprovedDriverFamilyResolution(
            base_drivers=base_drivers,
            dcf_scenario_drivers=None,
            source_lineage=lineage,
            approvals=(),
        )

    driver_field_names = {field.name for field in fields(base_drivers)}
    updates_by_scenario: dict[str, dict[str, float]] = {
        "low": {},
        "base": {},
        "high": {},
    }
    source_by_field: dict[str, str] = {}
    for approval in approvals:
        expected_fields = set(judgment_owned_fields(approval.family))
        approval_fields = set(approval.scenario_values["base"])
        if approval_fields != expected_fields:
            raise ValueError(
                f"approved driver-family queue item {approval.item_id} does not "
                "cover its canonical family fields"
            )
        unknown_fields = approval_fields - driver_field_names
        if unknown_fields:
            raise ValueError(
                f"approved driver-family queue item {approval.item_id} has "
                f"unknown valuation drivers: {sorted(unknown_fields)}"
            )
        source = (
            "approved_driver_family_pack:"
            f"item_id={approval.item_id};pack_id={approval.pack_id};"
            f"approval_fingerprint={approval.approval_fingerprint}"
        )
        for scenario in ("low", "base", "high"):
            updates_by_scenario[scenario].update(
                approval.scenario_values[scenario]
            )
        for field_name in approval_fields:
            source_by_field[field_name] = source

    resolved_base = replace(base_drivers, **updates_by_scenario["base"])
    scenario_drivers = {
        DCF_SCENARIO_FOR_APPROVED_CASE[scenario]: replace(
            base_drivers,
            **updates_by_scenario[scenario],
        )
        for scenario in ("low", "base", "high")
    }
    lineage.update(source_by_field)
    return ApprovedDriverFamilyResolution(
        base_drivers=resolved_base,
        dcf_scenario_drivers=scenario_drivers,
        source_lineage=lineage,
        approvals=approvals,
    )


__all__ = [
    "ApprovedDriverFamilyApproval",
    "ApprovedDriverFamilyResolution",
    "DCF_SCENARIO_FOR_APPROVED_CASE",
    "load_active_approved_driver_family_packs",
    "resolve_approved_driver_family_packs",
]
