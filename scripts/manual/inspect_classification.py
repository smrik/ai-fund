"""Inspect the classification pipeline stage by stage. Read-only.

Classifying financial data according to the valuation methodology is the most consequential
step in a valuation and the hardest to debug, because a wrong classification produces a
plausible number rather than an error. This walks the six stages between a CIQ workbook and an
equity value and prints what each one produced, so a wrong number can be traced to the stage
that made it wrong.

    python scripts/manual/inspect_classification.py --ticker MSFT
    python scripts/manual/inspect_classification.py --ticker MSFT --stage 4
    python scripts/manual/inspect_classification.py --ticker MSFT --with-packet

Stages:
    0 evidence  did CIQ parse, and which 10-K notes exist        read-only
    1 discovery all latest CIQ lines, ranked but never shortlisted read-only
    2 packet    what the accounting evidence packet contains     WRITES
    3 focus     what one focus projection hands the agent        WRITES (needs stage 2)
    4 bridge    every EV->equity claim, and double-count checks  read-only
    5 model     drivers, trust state, active approved overrides  read-only

Stages 0/1/4/5 open SQLite with ``mode=ro`` and never write — safe against the live DB at any
time. Stages 2/3 are NOT read-only: ``build_evidence_packet`` persists a row to
``evidence_packets`` and returns its id. They are therefore opt-in behind ``--with-packet``
(or an explicit ``--stage 2``/``--stage 3``), and the run announces the write.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stage_00_data.filing_retrieval import (
    SECTION_PARSER_VERSION,
    _raise_for_incomplete_coverage,
    get_accounting_corpus_coverage,
)

DB_PATH = ROOT / "data" / "alpha_pod.db"
LINE = "=" * 78


def _hdr(stage: int, title: str) -> None:
    print()
    print(LINE)
    print(f"STAGE {stage} — {title}")
    print(LINE)


def _ro_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------------------------------- stage 0
def stage0_evidence(ticker: str, *, require_complete: bool = False) -> set[str]:
    """CIQ snapshot health and which 10-K note sections were extracted.

    Returns the available note section keys so stage 1 can match against them.
    """
    _hdr(0, "EVIDENCE — did the sources parse")

    with _ro_conn() as conn:
        row = conn.execute(
            """select v.*, r.parser_version, r.ingest_ts
               from ciq_valuation_snapshot v join ciq_ingest_runs r on r.id = v.run_id
               where v.ticker = ? order by v.rowid desc limit 1""",
            (ticker,),
        ).fetchone()

    if row is None:
        print("  CIQ snapshot: MISSING — run the CIQ ingest first")
    else:
        print(f"  CIQ as_of={row['as_of_date']}  parser={row['parser_version']}  ingested={row['ingest_ts']}")
        # Zero/None on these is the signature of the D&A-style parse failure: a silent zero
        # that the assembler's clamp turns into a plausible small number.
        for key in ("revenue_mm", "operating_income_mm", "capex_mm", "da_mm",
                    "da_pct_avg_3yr", "capex_pct_avg_3yr", "total_debt_mm", "cash_mm"):
            value = row[key] if key in row.keys() else None
            flag = "   <-- ZERO/NULL, check the parser" if value in (None, 0, 0.0) else ""
            print(f"    {key:22} = {value}{flag}")

    # Filing inventory and current-parser coverage must remain separate. Historical
    # parser rows stay in SQLite for lineage but must not inflate current coverage.
    with _ro_conn() as conn:
        filing_sources = conn.execute(
            """select form_type, filing_date, accession_no, doc_name
               from edgar_filing_cache
               where ticker = ?
               order by filing_date desc, accession_no desc""",
            (ticker,),
        ).fetchall()
        coverage_rows = conn.execute(
            """select section_key, count(*) as section_count
               from edgar_section_cache
               where ticker = ? and parser_version = ?
               group by section_key""",
            (ticker, SECTION_PARSER_VERSION),
        ).fetchall()
        parsed_sources = conn.execute(
            """select form_type, filing_date, accession_no, doc_name,
                      count(*) as section_count,
                      sum(case when section_key glob 'note_[0-9][0-9][0-9]*' then 1 else 0 end)
                          as raw_note_count
               from edgar_section_cache
               where ticker = ? and parser_version = ?
               group by form_type, filing_date, accession_no, doc_name""",
            (ticker, SECTION_PARSER_VERSION),
        ).fetchall()

    coverage = {str(r["section_key"]): int(r["section_count"]) for r in coverage_rows}
    parsed_source_rows = {
        (str(r["accession_no"]), str(r["doc_name"])): r
        for r in parsed_sources
    }
    form_counts = Counter(str(r["form_type"]) for r in filing_sources)
    accounting_sources = [r for r in filing_sources if str(r["form_type"]) in {"10-K", "10-Q"}]
    parsed_accounting_count = sum(
        (str(r["accession_no"]), str(r["doc_name"])) in parsed_source_rows
        for r in accounting_sources
    )
    print()
    forms = ", ".join(f"{form}={count}" for form, count in sorted(form_counts.items()))
    print(f"  cached filings: {len(filing_sources)}" + (f" ({forms})" if forms else ""))
    print(f"  accounting filings parsed: {parsed_accounting_count}/{len(accounting_sources)}")
    print(
        f"  current parsed sections: {sum(coverage.values())} across "
        f"{len(parsed_source_rows)} filings  parser={SECTION_PARSER_VERSION}"
    )
    for src in filing_sources:
        source_key = (str(src["accession_no"]), str(src["doc_name"]))
        parsed = parsed_source_rows.get(source_key)
        if parsed is not None:
            status = "parsed"
            detail = f"sections={int(parsed['section_count'])} raw_notes={int(parsed['raw_note_count'])}"
        elif str(src["form_type"]) in {"10-K", "10-Q"}:
            status = "FAILED"
            detail = "required accounting filing was not parsed"
        else:
            status = "source"
            detail = "cached supplemental filing; outside accounting corpus"
        print(
            f"    [{status:8}] {str(src['form_type']):8} "
            f"{src['filing_date']}  {src['accession_no']}  {detail}"
        )

    raw_notes = sorted(k for k in coverage if re.fullmatch(r"note_\d{3}[a-z]?", k))
    topic_aliases = sorted(k for k in coverage if k.startswith("note_") and k not in raw_notes)
    print(f"  raw numbered note keys ({len(raw_notes)}): {raw_notes}")
    print(f"  topic note aliases ({len(topic_aliases)}): {topic_aliases}")
    # One verdict, one implementation. The operator view and the runtime gate used by
    # the discovery runner must never disagree about whether a corpus is usable.
    with _ro_conn() as conn:
        corpus_coverage = get_accounting_corpus_coverage(
            ticker,
            conn=conn,
            parser_version=SECTION_PARSER_VERSION,
        )
    if corpus_coverage["filings_without_notes"]:
        print(
            "  WARNING: parsed but noteless: "
            + ", ".join(
                f"{item['form_type']} {item['accession_no']} ({item['sections']} sections)"
                for item in corpus_coverage["filings_without_notes"]
            )
        )
    if require_complete:
        _raise_for_incomplete_coverage(corpus_coverage)
    return set(coverage)


# --------------------------------------------------------------------------- stage 1
def stage1_coverage(
    ticker: str,
    note_sections: set[str],
    *,
    limit: int = 40,
    offset: int = 0,
) -> None:
    """Show the open-ended metric catalog and which lines have exact note evidence."""
    _hdr(1, "DISCOVERY — all CIQ lines, ranked but never shortlisted")

    from src.stage_04_pipeline.ciq_note_matching import (
        find_classification_candidates,
        summarize_candidates,
    )

    with _ro_conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "select metric_key,row_label,period_date,calc_type,value_num from ciq_long_form "
                "where ticker = ? and sheet_name = 'Financial Statements'",
                (ticker,),
            )
        ]
        scale_row = conn.execute(
            "select revenue_mm from ciq_valuation_snapshot "
            "where ticker = ? order by rowid desc limit 1",
            (ticker,),
        ).fetchone()
    print(f"  CIQ long-form rows: {len(rows)}")

    scale_base = float(scale_row["revenue_mm"]) if scale_row and scale_row["revenue_mm"] else None
    candidates = find_classification_candidates(
        rows,
        note_sections,
        ticker=ticker,
        scale_base=scale_base,
        scale_label="revenue",
        limit=limit,
        offset=offset,
    )
    summary = summarize_candidates(candidates)

    print(
        f"  latest populated={summary['total_populated_metrics']}  "
        f"nonzero candidates={summary['total_candidate_metrics']}  "
        f"page offset={summary['offset']} shown={summary['shown']} "
        f"remaining={summary['withheld']}"
    )
    print()
    for item in candidates.items:
        if item.has_governing_note:
            evidence = "NOTE"
        elif item.note_section_key:
            evidence = "MISS"
        else:
            evidence = "----"
        scale = f"{item.scale_pct:8.2%}" if item.scale_pct is not None else "      n/a"
        signals = ",".join(item.signals) or "-"
        print(
            f"  {evidence} {item.metric_key:42} {_money(item.value):>14}  "
            f"{scale}  note={item.note_section_key or '-':22} signals={signals}"
        )

    if candidates.zero_valued_adjustment_lines:
        print()
        print(
            "  zero-valued lines carrying adjustment language "
            f"({len(candidates.zero_valued_adjustment_lines)}; disclosed, not ranked):"
        )
        for metric_key in candidates.zero_valued_adjustment_lines[:20]:
            print(f"    {metric_key}")
    if candidates.next_offset is not None:
        print()
        print(
            f"  More data is available: rerun stage 1 with "
            f"--candidate-offset {candidates.next_offset}."
        )
    print()
    print("  NOTE=exact extracted note available; MISS=note type inferred but not extracted.")
    print("  Ordering helps review; it does not decide materiality or treatment.")


# --------------------------------------------------------------------------- stage 2
def stage2_packet(ticker: str, profile: str) -> Any:
    """What the accounting evidence packet actually contains.

    NOT read-only: `build_evidence_packet` persists a row to `evidence_packets`.
    """
    _hdr(2, f"PACKET — {profile}")

    from src.stage_04_pipeline.evidence_packets import build_evidence_packet

    try:
        packet = build_evidence_packet(ticker, profile)
    except Exception as exc:
        print(f"  ERROR building packet: {exc}")
        return None

    print(f"  (wrote evidence_packets row id={packet.packet_id})")

    facts = list(packet.facts or [])
    snippets = list(packet.snippets or [])
    print(f"  facts={len(facts)}  snippets={len(snippets)}  source_refs={len(packet.source_refs or [])}")
    roles = Counter((f.metadata or {}).get("fact_role", "(none)") for f in facts)
    for role, count in roles.most_common():
        print(f"    fact_role {role:32} {count}")
    sections = Counter((s.metadata or {}).get("section_key", "(none)") for s in snippets)
    if sections:
        print(f"  snippet sections: {dict(sections)}")
    return packet


# --------------------------------------------------------------------------- stage 3
def stage3_focus(packet: Any, focus_key: str) -> None:
    """What one focus projection selects — and what it drops."""
    _hdr(3, f"FOCUS — {focus_key}")

    if packet is None:
        print("  skipped (no packet)")
        return

    from src.stage_04_pipeline.accounting_focus import (
        select_accounting_focus,
        to_focused_accounting_packet,
    )

    try:
        context = select_accounting_focus(packet, focus_key)
    except Exception as exc:
        print(f"  ERROR selecting focus: {exc}")
        return

    print(f"  packet_status={context.packet_status}  missing_data={context.missing_data_status}")
    print(f"  selected facts={len(context.selected_facts or [])}  snippets={len(context.selected_snippets or [])}")
    print(f"  driver fields: {context.selected_driver_fields}")
    for note in context.coverage_notes or []:
        print(f"    coverage note: {note}")
    print()
    focused = to_focused_accounting_packet(context, packet)
    print(f"  validator packet id={focused.packet_id}")
    print(
        f"    facts={len(focused.facts)} snippets={len(focused.snippets)} "
        f"source_refs={len(focused.source_refs)} anchors={len(focused.evidence_anchors)}"
    )
    print(f"    currently supported driver fields: {focused.allowed_driver_fields}")
    print("    novel treatments may instead return model_change_required + model_change_request.")


# --------------------------------------------------------------------------- stage 4
def stage4_bridge(ticker: str) -> Any:
    """Every EV->equity claim with its source, plus double-count checks.

    This is the stage that makes classification errors visible: each claim is printed with the
    lineage that produced it, and overlapping sources are checked explicitly.
    """
    _hdr(4, "BRIDGE — EV to equity claims and their sources")

    from src.stage_02_valuation.input_assembler import build_valuation_inputs

    try:
        inputs = build_valuation_inputs(ticker)
    except Exception as exc:
        print(f"  ERROR assembling inputs: {exc}")
        return None
    if inputs is None:
        print("  no inputs")
        return None

    drivers = inputs.drivers
    lineage = dict(inputs.source_lineage or {})

    from src.stage_02_valuation.assumption_register import FIELD_METADATA

    claim_fields = (
        "net_debt", "minority_interest", "preferred_equity", "pension_deficit",
        "lease_liabilities", "options_value", "convertibles_value",
    )
    print(f"  {'claim':22} {'value':>16}  {'source_lineage':32} register?")
    total = 0.0
    for name in claim_fields:
        value = float(getattr(drivers, name, 0.0) or 0.0)
        total += value
        registered = "yes" if name in FIELD_METADATA else "NO  <-- no range/flag"
        print(f"  {name:22} {_money(value):>16}  {str(lineage.get(name, '-')):32} {registered}")
    print(f"  {'TOTAL CLAIMS':22} {_money(total):>16}")
    print(f"  {'non_operating_assets':22} {_money(getattr(drivers, 'non_operating_assets', 0.0)):>16}  "
          f"{str(lineage.get('non_operating_assets', '-')):32} (added to EV)")

    print()
    print("  double-count checks:")
    _check_lease_double_count(ticker, drivers, lineage)
    _check_excess_cash(drivers, lineage)
    return inputs


def _check_lease_double_count(ticker: str, drivers: Any, lineage: dict[str, Any]) -> None:
    """CIQ's `debt` already includes leases; adding lease_liabilities again double-counts.

    The existing guard in input_assembler only fires for the yfinance branch.
    """
    lease = float(getattr(drivers, "lease_liabilities", 0.0) or 0.0)
    net_debt_source = str(lineage.get("net_debt", ""))
    if lease <= 0:
        print("    leases: lease_liabilities is 0 — no double-count")
        return

    with _ro_conn() as conn:
        row = conn.execute(
            "select metric_key, value_num from ciq_long_form where ticker = ? "
            "and sheet_name = 'Financial Statements' "
            "and metric_key in ('debt','total_debt_excl_leases','total_leases') "
            "order by period_date desc",
            (ticker,),
        ).fetchall()
    latest: dict[str, float] = {}
    for r in row:
        latest.setdefault(r["metric_key"], r["value_num"])

    debt = latest.get("debt")
    ex_leases = latest.get("total_debt_excl_leases")
    leases = latest.get("total_leases")
    if debt and ex_leases and leases and abs((ex_leases + leases) - debt) < 1.0:
        print(f"    leases: CIQ debt {_money(debt)} = ex-leases {_money(ex_leases)} + leases {_money(leases)}")
        if net_debt_source.startswith("ciq") and lease > 0:
            print(f"    *** DOUBLE-COUNT: net_debt (source={net_debt_source}) already includes leases,")
            print(f"        and lease_liabilities {_money(lease)} is added again in _claims_total().")
            shares = float(getattr(drivers, "shares_outstanding", 0.0) or 0.0)
            if shares:
                print(f"        effect: ~${lease / shares:.2f}/share understated equity value.")
        else:
            print(f"    leases: net_debt source={net_debt_source} — check the fold guard")
    else:
        print("    leases: could not confirm whether CIQ debt includes leases")


def _check_excess_cash(drivers: Any, lineage: dict[str, Any]) -> None:
    """net_debt nets full cash; non_operating_assets adds excess cash back to EV."""
    noa = float(getattr(drivers, "non_operating_assets", 0.0) or 0.0)
    if noa > 0 and str(lineage.get("net_debt", "")).startswith(("ciq", "yfinance")):
        print(f"    excess cash: non_operating_assets {_money(noa)} is added to EV while net_debt")
        print("        nets full cash — verify this is not credited twice (PM finance call).")


# --------------------------------------------------------------------------- stage 5
def stage5_model(ticker: str, inputs: Any) -> None:
    """Assembled drivers, trust state, and what has been approved into the model."""
    _hdr(5, "MODEL — trust state and active overrides")

    if inputs is not None:
        try:
            from src.stage_02_valuation.assumption_register import (
                build_assumption_register,
                summarize_assumption_register,
            )

            register = build_assumption_register(ticker, inputs)
            summary = summarize_assumption_register(register)
            print(f"  model_trust_state = {summary.get('model_trust_state')}")
            print(f"  max_flag_level    = {summary.get('max_flag_level')}")
            print(f"  flag counts       = {summary.get('flag_counts')}")
            for entry in (summary.get("flagged_entries") or [])[:10]:
                name = entry.get("assumption_name") if isinstance(entry, dict) else entry
                level = entry.get("flag_level") if isinstance(entry, dict) else ""
                print(f"    flagged: {name} {level}")
        except Exception as exc:
            print(f"  register ERROR: {exc}")

    print()
    try:
        from db.loader import get_approved_assumption_overrides

        approved = get_approved_assumption_overrides(ticker)
    except Exception as exc:
        print(f"  approved overrides ERROR: {exc}")
        return
    if approved:
        print(f"  active approved overrides ({len(approved)}) — these beat valuation_overrides.yaml:")
        for name, value in sorted(approved.items()):
            print(f"    {name:28} = {value}")
    else:
        print("  no active approved assumption overrides")
    print()
    print("  NOTE: approved entries persist metadata_json, but get_approved_assumption_overrides()")
    print("  returns {name: float} — the treatment/why is dropped before it reaches the model.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--stage", type=int, choices=range(0, 6), help="run only this stage")
    parser.add_argument("--profile", default="accounting_ev_equity_bridge")
    parser.add_argument("--focus", default="bridge_leases_pensions_claims")
    parser.add_argument("--candidate-limit", type=int, default=40)
    parser.add_argument("--candidate-offset", type=int, default=0)
    parser.add_argument(
        "--with-packet",
        action="store_true",
        help="include stages 2-3. These BUILD a packet, which persists a row to evidence_packets.",
    )
    args = parser.parse_args(argv)

    ticker = args.ticker.upper().strip()
    # Cache-only: inspection must never trigger a network fetch or mutate caches.
    os.environ.setdefault("ALPHA_POD_MARKET_CACHE_ONLY", "1")

    if not DB_PATH.exists():
        print(f"database not found: {DB_PATH}")
        return 1

    want = args.stage
    # Stages 2-3 persist an evidence packet, so they are opt-in rather than part of the
    # default sweep. Asking for them explicitly by --stage counts as opting in.
    run_packet_stages = args.with_packet or want in (2, 3)

    mode = "writes evidence_packets" if run_packet_stages else "read-only"
    print(f"\nClassification inspection — {ticker}   ({mode})")

    sections: set[str] = set()
    packet = None
    inputs = None

    if want in (None, 0, 1) or (run_packet_stages and want in (2, 3)):
        sections = stage0_evidence(ticker, require_complete=run_packet_stages)
    if want in (None, 1):
        stage1_coverage(
            ticker,
            sections,
            limit=args.candidate_limit,
            offset=args.candidate_offset,
        )
    if run_packet_stages and want in (None, 2, 3):
        packet = stage2_packet(ticker, args.profile)
    if run_packet_stages and want in (None, 3):
        stage3_focus(packet, args.focus)
    if not run_packet_stages and want is None:
        print()
        print("  (stages 2-3 skipped — they persist a packet row; pass --with-packet to include)")
    if want in (None, 4, 5):
        inputs = stage4_bridge(ticker)
    if want in (None, 5):
        stage5_model(ticker, inputs)

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
