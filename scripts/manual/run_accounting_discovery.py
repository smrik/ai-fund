"""Run the two-pass accounting discovery and focused-retrieval trial.

The filing and market evidence stay cache-only. The discovery call is live and uses the
configured judgment backend. No valuation input or PM Queue item is changed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.loader import list_evidence_packets
from db.schema import get_connection
from scripts.manual.inspect_classification import stage0_evidence
from src.stage_00_data.ciq_adapter import get_ciq_snapshot
from src.stage_00_data.filing_retrieval import (
    get_accounting_section_inventory,
    get_discovery_filing_context,
)
from src.stage_02_valuation.input_assembler import build_valuation_inputs
from src.stage_03_judgment.accounting_recast_agent import (
    AccountingDiscoveryAgent,
)
from src.stage_04_pipeline.accounting_discovery_ledger import (
    DiscoveryJudgmentContext,
    run_discovery_accounting_pass,
)


def _latest_packet(ticker: str, profile_name: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        packets = list_evidence_packets(conn, ticker=ticker)
    return next(
        (
            packet
            for packet in packets
            if packet.get("profile_name") == profile_name
        ),
        None,
    )


def _render_facts(packet: dict[str, Any] | None, *, limit: int = 80) -> str:
    if not packet:
        return "No cached packet."
    lines = [
        f"{fact.get('fact_name')}: {fact.get('value')} "
        f"(metadata={fact.get('metadata') or {}})"
        for fact in (packet.get("facts") or [])[:limit]
    ]
    return "\n".join(lines) or "No facts in cached packet."


def _render_analysis_context(
    packet: dict[str, Any] | None,
    *,
    snippet_limit: int = 12,
) -> str:
    if not packet:
        return "No cached packet."
    lines: list[str] = []
    for observation in packet.get("observations") or []:
        lines.append("Observation: " + json.dumps(observation, sort_keys=True))
    for snippet in (packet.get("snippets") or [])[:snippet_limit]:
        metadata = snippet.get("metadata") or {}
        lines.append(
            f"[{metadata.get('section_key') or snippet.get('snippet_id')} | "
            f"{metadata.get('filing_date') or 'unknown-date'}]\n"
            f"{str(snippet.get('text') or '')[:1_200]}"
        )
    return "\n\n".join(lines) or "No observations or snippets in cached packet."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--codex-model",
        default=os.getenv("ALPHA_POD_CODEX_MODEL", "gpt-5.4-mini"),
    )
    parser.add_argument(
        "--codex-effort",
        default=os.getenv("ALPHA_POD_CODEX_EFFORT", "low"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "accounting_discovery",
    )
    parser.add_argument(
        "--with-recast",
        action="store_true",
        help="Run one focused accounting-recast call per discovered question.",
    )
    parser.add_argument(
        "--persist-queue",
        action="store_true",
        help=(
            "Write the translated PM Decision Queue items to the live database. "
            "Off by default: the pass is analysis-only and never applies a treatment."
        ),
    )
    args = parser.parse_args(argv)

    ticker = args.ticker.upper().strip()
    os.environ["ALPHA_POD_EDGAR_CACHE_ONLY"] = "1"
    os.environ["ALPHA_POD_MARKET_CACHE_ONLY"] = "1"
    os.environ["ALPHA_POD_AGENT_BACKEND"] = "codex"
    os.environ["ALPHA_POD_CODEX_MODEL"] = args.codex_model
    os.environ["ALPHA_POD_CODEX_EFFORT"] = args.codex_effort

    stage0_evidence(ticker, require_complete=True)
    inventory = get_accounting_section_inventory(ticker)
    company_packet = _latest_packet(ticker, "company_analysis")
    industry_packet = _latest_packet(ticker, "industry_analysis")
    accounting_packet = _latest_packet(ticker, "accounting_ev_equity_bridge")
    ciq_snapshot = get_ciq_snapshot(ticker) or {}
    valuation_inputs = build_valuation_inputs(ticker, apply_overrides=False)
    if valuation_inputs is None:
        raise RuntimeError(f"No valuation inputs available for {ticker}")
    claim_ledger = valuation_inputs.claim_ledger
    if not claim_ledger.get("reconciliation", {}).get("is_reconciled"):
        raise RuntimeError(
            f"EV bridge claim ledger is unreconciled for {ticker}: "
            f"{claim_ledger.get('reconciliation', {}).get('failure_message')}"
        )

    business_context = _render_analysis_context(company_packet)
    industry_context = (
        _render_facts(industry_packet, limit=40)
        + "\n\n"
        + _render_analysis_context(industry_packet, snippet_limit=8)
    )
    quantitative_context = _render_facts(company_packet) + "\n\n" + _render_facts(
        accounting_packet
    )
    current_model_context = (
        "Current exact-once EV-bridge claim ledger and operating-cash policy:\n"
        + json.dumps(
            {
                "claim_ledger": claim_ledger,
                "operating_cash_policy": valuation_inputs.operating_cash_policy,
            },
            sort_keys=True,
        )
        + "\n\nCurrent accounting/bridge packet facts and source metadata:\n"
        + _render_facts(accounting_packet)
    )

    discovery = AccountingDiscoveryAgent().discover(
        ticker,
        section_inventory=inventory,
        business_context=business_context,
        industry_context=industry_context,
        quantitative_context=quantitative_context,
        current_model_context=current_model_context,
    )
    focused = get_discovery_filing_context(ticker, discovery)
    focused_analyses: list[dict[str, Any]] = []
    ledger_payload: dict[str, Any] | None = None
    if args.with_recast:
        conn = get_connection() if args.persist_queue else None
        try:
            pass_result = run_discovery_accounting_pass(
                ticker=ticker,
                discovery=discovery,
                contexts=DiscoveryJudgmentContext(
                    business_context=business_context,
                    industry_context=industry_context,
                    quantitative_context=quantitative_context,
                    current_model_context=current_model_context,
                ),
                evidence_packet_id=(
                    accounting_packet.get("packet_id")
                    if accounting_packet
                    else "no_cached_accounting_packet"
                ),
                reported_ebit=ciq_snapshot.get("operating_income_ttm"),
                claim_ledger=claim_ledger,
                conn=conn,
                # stage0_evidence(require_complete=True) already gated this run.
                require_corpus_coverage=False,
            )
        finally:
            if conn is not None:
                conn.close()
        focused_analyses = pass_result.focused_analyses
        ledger_payload = {
            "ledger": pass_result.ledger.model_dump(mode="json"),
            "queue_items": [
                item.model_dump(mode="json") for item in pass_result.queue_items
            ],
            "rejected_findings": pass_result.rejected_findings,
            "persisted_queue_item_ids": pass_result.persisted_queue_item_ids,
        }

    artifact = {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.codex_model,
        "effort": args.codex_effort,
        "inventory_count": len(inventory),
        "raw_note_count": sum(
            item.get("inventory_role") == "raw_numbered_note"
            for item in inventory
        ),
        "context_packet_ids": {
            "company_analysis": (
                company_packet.get("packet_id") if company_packet else None
            ),
            "industry_analysis": (
                industry_packet.get("packet_id") if industry_packet else None
            ),
            "accounting_ev_equity_bridge": (
                accounting_packet.get("packet_id") if accounting_packet else None
            ),
        },
        "discovery": discovery,
        "focused_retrieval": {
            "summary": focused.retrieval_summary,
            "rendered_text": focused.rendered_text,
        },
        "focused_analyses": focused_analyses,
        "accounting_ledger": ledger_payload,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output_dir / f"{ticker}-{timestamp}.json"
    output_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print()
    print(f"inventory={len(inventory)} raw_notes={artifact['raw_note_count']}")
    print(
        f"questions={len(discovery.get('questions') or [])} "
        f"focused_chunks={len(focused.selected_chunks)}"
    )
    for question in discovery.get("questions") or []:
        print(
            f"  [{question.get('priority')}] {question.get('question_id')}: "
            f"{question.get('question')}"
        )
        print(
            "    sections="
            + ", ".join(question.get("requested_section_ids") or [])
        )
    for analysis in focused_analyses:
        recast = analysis["recast"]
        print(
            f"  recast[{analysis['question_id']}]: confidence="
            f"{recast.get('confidence')} adjustments="
            f"{len(recast.get('income_statement_adjustments') or [])} "
            f"reclasses={len(recast.get('reclassify') or [])} "
            f"model_changes={len(recast.get('model_change_proposals') or [])}"
        )
    if ledger_payload is not None:
        entries = ledger_payload["ledger"]["entries"]
        status_counts: dict[str, int] = {}
        for entry in entries:
            status = str(entry["ledger_status"])
            status_counts[status] = status_counts.get(status, 0) + 1
        item_counts: dict[str, int] = {}
        for item in ledger_payload["queue_items"]:
            item_type = str(item["item_type"])
            item_counts[item_type] = item_counts.get(item_type, 0) + 1
        print()
        print(f"  ledger entries={len(entries)} " + json.dumps(status_counts, sort_keys=True))
        print(
            f"  conflict groups={len(ledger_payload['ledger']['conflict_groups'])} "
            f"rejected={len(ledger_payload['rejected_findings'])}"
        )
        print(
            f"  queue items={len(ledger_payload['queue_items'])} "
            + json.dumps(item_counts, sort_keys=True)
        )
        if args.persist_queue:
            print(f"  persisted queue ids={ledger_payload['persisted_queue_item_ids']}")
        else:
            print("  persisted=none (dry run; pass --persist-queue to write the queue)")
    print(f"artifact={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
