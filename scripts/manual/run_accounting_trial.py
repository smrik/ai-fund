"""Run one cache-only accounting evidence trial through the PM queue.

This is an offline plumbing trial, not the production judgment agent. It loads
an already-persisted accounting packet, makes one inspectable lease-source
reconciliation finding, validates it, and optionally writes the advisory item
to the PM Decision Queue.

    python scripts/manual/run_accounting_trial.py --ticker MSFT
    python scripts/manual/run_accounting_trial.py --ticker MSFT --persist
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "alpha_pod.db"


def _latest_packet_id(conn: sqlite3.Connection, ticker: str, profile: str) -> int:
    row = conn.execute(
        """
        SELECT id
        FROM evidence_packets
        WHERE ticker = ? AND profile_name = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        [ticker, profile],
    ).fetchone()
    if row is None:
        raise ValueError(f"no cached {profile} packet found for {ticker}")
    return int(row["id"])


def _lease_reconciliation_judgment(packet: dict[str, Any]) -> dict[str, Any]:
    facts = list(packet.get("facts") or [])
    snippets = list(packet.get("snippets") or [])
    current = next(
        (fact for fact in facts if fact.get("fact_name") == "lease_liabilities"),
        None,
    )

    by_period: dict[str, dict[str, dict[str, Any]]] = {}
    for fact in facts:
        name = str(fact.get("fact_name") or "")
        period = str(fact.get("period") or "")
        if not period or name not in {
            "xbrl_us-gaap_OperatingLeaseLiability",
            "xbrl_us-gaap_FinanceLeaseLiability",
        }:
            continue
        by_period.setdefault(period, {})[name] = fact

    complete_periods = {
        period: values
        for period, values in by_period.items()
        if len(values) == 2
    }
    if current is None or not complete_periods:
        return {
            "focus_key": "bridge_leases_pensions_claims",
            "packet_status": "missing_evidence",
            "findings": [],
            "coverage_notes": [
                "A current model lease balance and comparable operating/finance "
                "lease XBRL facts were not both available."
            ],
        }

    latest_period = max(complete_periods)
    components = complete_periods[latest_period]
    operating = components["xbrl_us-gaap_OperatingLeaseLiability"]
    finance = components["xbrl_us-gaap_FinanceLeaseLiability"]
    current_value = float(current["value"])
    xbrl_value = float(operating["value"]) + float(finance["value"])
    difference = xbrl_value - current_value
    anchors = [
        str(current["fact_id"]),
        str(operating["fact_id"]),
        str(finance["fact_id"]),
    ]
    if snippets:
        anchors.append(str(snippets[0]["snippet_id"]))

    return {
        "focus_key": "bridge_leases_pensions_claims",
        "packet_status": "complete",
        "coverage_notes": [],
        "findings": [
            {
                "finding_id": f"finding:lease-source-reconciliation:{latest_period}",
                "topic": "ev_equity_bridge",
                "focus_key": "bridge_leases_pensions_claims",
                "finding_status": "candidate",
                "finding_type": "lease_source_reconciliation",
                "line_item": "Lease liabilities",
                "claim": (
                    f"The current model packet carries lease liabilities of "
                    f"${current_value / 1e9:.3f}bn, while latest same-period XBRL "
                    f"operating and finance lease liabilities total "
                    f"${xbrl_value / 1e9:.3f}bn at {latest_period}. The "
                    "difference must be reconciled to the CIQ net-debt convention "
                    "before changing the DCF bridge."
                ),
                "claim_driver_field": "lease_liabilities",
                "proposed_driver_field": "lease_liabilities",
                "reported_value": current_value,
                "proposed_value": xbrl_value,
                "currency": "USD",
                "period": latest_period,
                "booked_or_disclosed_status": "booked",
                "accounting_treatment": "unclear",
                "valuation_treatment": "scenario_only",
                "evidence_anchor_ids": anchors,
                "citation_text": (
                    f"Operating lease liabilities ${float(operating['value']) / 1e9:.3f}bn "
                    f"plus finance lease liabilities ${float(finance['value']) / 1e9:.3f}bn."
                ),
                "confidence": "medium",
                "pm_question": (
                    "Which lease components are already included in CIQ net debt, "
                    "and which valuation-date balance should govern the bridge?"
                ),
                "what_would_change_mind": (
                    "A source reconciliation showing the current model balance "
                    "uses the same date and includes the same lease components."
                ),
                "materiality_rationale": (
                    f"The source difference is ${difference / 1e9:.3f}bn and a "
                    "wrong convention could double-count an EV-to-equity claim."
                ),
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--packet-id", type=int)
    parser.add_argument("--profile", default="accounting_ev_equity_bridge")
    parser.add_argument("--focus", default="bridge_leases_pensions_claims")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    from db.loader import load_evidence_packet
    from db.schema import create_tables
    from src.stage_04_pipeline.accounting_evidence_runner import (
        run_accounting_evidence_trial,
    )

    ticker = args.ticker.upper().strip()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    packet_id = args.packet_id or _latest_packet_id(conn, ticker, args.profile)
    packet = load_evidence_packet(conn, packet_id)
    if packet is None:
        raise ValueError(f"evidence packet {packet_id} not found")
    if args.persist:
        create_tables(conn)

    result = run_accounting_evidence_trial(
        source_packet=packet,
        focus_key=args.focus,
        judgment_callable=_lease_reconciliation_judgment,
        repair_callable=lambda request: request["original_finding"],
        conn=conn if args.persist else None,
    )
    conn.close()

    print(f"ticker={ticker} packet_id={packet_id} focus={args.focus}")
    print(
        f"focused facts={len(result.focused_packet.facts)} "
        f"snippets={len(result.focused_packet.snippets)} "
        f"repair_status={result.repair_result.status}"
    )
    for item in result.queue_items:
        print(f"queue_type={item.item_type.value} title={item.title}")
        print(f"claim={item.summary}")
        print(f"anchors={item.evidence_anchor_ids}")
        print(f"queue_reason={item.metadata.get('queue_reason', 'advisory_treatment')}")
    if args.persist:
        print(f"persisted_queue_item_ids={result.persisted_queue_item_ids}")
    else:
        print("dry_run=true (pass --persist to write the PM Decision Queue)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
