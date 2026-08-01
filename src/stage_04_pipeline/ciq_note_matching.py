"""Surface what is worth classifying in a filing, and pair it with the note that governs it.

CIQ carries ~500 line items per ticker. Any of them might warrant a valuation adjustment — an
unusual charge, a disclosed-but-unbooked obligation, a reclassification between operating and
financing. Deciding *which* ones matter is judgment, so this module does not decide it.

What it does instead is deterministic and narrow:

1. rank every populated line item by how large it is for this company,
2. flag the ones whose labels carry adjustment-relevant language,
3. derive which note section governs each, by token overlap with the note types the EDGAR
   parser actually extracts,
4. report what it is NOT showing, so the agent can ask for more.

Deliberately absent: any hand-written list of "the metrics that matter", and any materiality
threshold. A fixed shortlist would hide the ~470 lines it omits, and thresholds are finance
semantics the PM owns. Ranking exposes everything in order; it does not draw the line.

The only structure here is genuinely structural — the twelve note types come from
``filing_retrieval._NOTE_TOPIC_PATTERNS``, not from an opinion about what matters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The note types the EDGAR parser can actually extract. Mirrors
# `filing_retrieval._NOTE_TOPIC_PATTERNS`; kept as tokens so metric names can be matched
# against them by overlap rather than by a hand-maintained mapping table.
NOTE_SECTION_TOKENS: dict[str, tuple[str, ...]] = {
    "note_revenue": ("revenue", "unearned", "deferred_revenue", "contract", "backlog", "performance_obligation"),
    "note_segments": ("segment", "geographic", "disaggregat"),
    "note_leases": ("lease", "rou", "right_of_use"),
    "note_restructuring": ("restructur", "severance", "exit_cost"),
    "note_impairment": ("impair", "goodwill", "intangible", "writedown", "write_down", "amortization_of_goodwill"),
    "note_acquisitions": ("acquisition", "business_combination", "purchase_price"),
    "note_contingencies": ("contingen", "litigation", "legal", "warranty", "guarantee", "commitment"),
    "note_pension": ("pension", "retirement", "postretire", "post_retire", "benefit_obligation"),
    "note_taxes": ("tax", "deferred_tax", "valuation_allowance", "uncertain_tax"),
    "note_fair_value": ("fair_value", "invest", "securities", "derivative", "hedge", "marketable"),
    "note_debt": ("debt", "borrowing", "note_payable", "credit_facility", "covenant", "interest"),
    "note_sbc": ("stock_based", "stock_option", "share_based", "equity_award", "rsu"),
}

BROAD_NOTE_SECTION_KEYS = ("notes_to_financials", "notes_to_financials_q")

# Label language that marks an item as adjustment-relevant regardless of size. These are not a
# shortlist of what matters — they are cues that an item is *unusual*, which is precisely the
# case where magnitude alone would under-rank it.
ADJUSTMENT_LANGUAGE: tuple[str, ...] = (
    "unusual", "non_recurring", "nonrecurring", "one_time", "restructur", "impair",
    "writedown", "write_down", "settlement", "litigation", "discontinued", "divest",
    "supple", "adjustment", "extraordinary", "gain_loss", "other_operating", "special",
)

# Lines that are ratios/per-share/counts rather than amounts. Excluded from magnitude ranking
# because "days" or "x" cannot be compared against revenue, not because they do not matter.
NON_AMOUNT_HINTS: tuple[str, ...] = (
    "_pct", "_percent", "margin", "turnover", "yoy", "cagr", "per_share", "_share",
    "ratio", "days", "_employee", "employees", "_score", "growth",
)


@dataclass(frozen=True)
class AdjustableItem:
    """One line item the agent may want to classify, with the note that would govern it."""

    metric_key: str
    row_label: str
    value: float
    period_date: str
    calc_type: str
    scale_pct: float | None
    signals: tuple[str, ...]
    note_section_key: str | None
    note_available: bool

    @property
    def has_governing_note(self) -> bool:
        return bool(self.note_section_key) and self.note_available


@dataclass(frozen=True)
class ClassificationCandidates:
    ticker: str
    items: tuple[AdjustableItem, ...]
    scale_base: float | None
    scale_label: str
    total_populated_metrics: int
    total_candidate_metrics: int
    offset: int
    shown: int
    withheld: int
    zero_valued_adjustment_lines: tuple[str, ...] = ()
    notes_available: tuple[str, ...] = ()
    metrics_without_note: tuple[str, ...] = field(default_factory=tuple)

    @property
    def next_offset(self) -> int | None:
        next_value = self.offset + self.shown
        return next_value if next_value < self.total_candidate_metrics else None


def _is_amount(metric_key: str) -> bool:
    return not any(hint in metric_key for hint in NON_AMOUNT_HINTS)


def _tokens(metric_key: str, row_label: str) -> str:
    label = re.sub(r"[^a-z0-9]+", "_", str(row_label or "").lower())
    return f"{metric_key}_{label}"


def derive_note_section(metric_key: str, row_label: str = "") -> str | None:
    """Which extracted note type governs this line, by token overlap.

    Derived rather than mapped, so a metric nobody anticipated still routes somewhere. Returns
    None when nothing matches — an honest "no governing note" rather than a forced guess.
    """
    haystack = _tokens(metric_key, row_label)
    best_key: str | None = None
    best_score = 0
    for section_key, tokens in NOTE_SECTION_TOKENS.items():
        score = sum(len(token) for token in tokens if token in haystack)
        if score > best_score:
            best_score = score
            best_key = section_key
    return best_key


def _signals(metric_key: str, row_label: str) -> tuple[str, ...]:
    found: list[str] = []
    haystack = _tokens(metric_key, row_label)
    if any(term in haystack for term in ADJUSTMENT_LANGUAGE):
        found.append("adjustment_language")
    return tuple(found)


def _latest_rows(long_form_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in long_form_rows:
        key = row.get("metric_key")
        if not key or row.get("value_num") is None:
            continue
        period = str(row.get("period_date") or "")
        current = latest.get(key)
        if current is None or period > str(current.get("period_date") or ""):
            latest[key] = row
    return latest


def find_classification_candidates(
    long_form_rows: list[dict[str, Any]],
    available_note_sections: set[str] | frozenset[str] | None = None,
    *,
    ticker: str = "",
    scale_base: float | None = None,
    scale_label: str = "revenue",
    limit: int = 40,
    offset: int = 0,
) -> ClassificationCandidates:
    """Page through every latest nonzero line item in a useful review order.

    Eligibility is data-driven: there is no topic registry or materiality threshold. Adjustment
    language leads, lines that can be routed to an extracted note come next, and magnitude only
    orders within those groups. `offset` and `limit` make the complete population traversable.

    CIQ templates contain many irrelevant zero rows. Those do not enter the ranking; zero rows
    carrying explicit adjustment language are disclosed separately so they remain inspectable
    without swamping the useful nonzero population.
    """
    available = set(available_note_sections or ())
    latest = _latest_rows(long_form_rows)
    page_offset = max(0, offset)
    page_limit = max(0, limit)

    scored: list[tuple[int, float, AdjustableItem]] = []
    without_note: list[str] = []
    zero_flagged: list[str] = []

    for metric_key, row in sorted(latest.items()):
        value = float(row.get("value_num") or 0.0)
        row_label = str(row.get("row_label") or metric_key)

        scale_pct: float | None = None
        if scale_base and _is_amount(metric_key):
            scale_pct = abs(value) / abs(scale_base)

        signals = _signals(metric_key, row_label)
        if value == 0.0:
            if "adjustment_language" in signals:
                zero_flagged.append(metric_key)
            continue

        note_key = derive_note_section(metric_key, row_label)
        note_available = bool(note_key and note_key in available)
        if not note_available:
            without_note.append(metric_key)

        item = AdjustableItem(
            metric_key=metric_key,
            row_label=row_label,
            value=value,
            period_date=str(row.get("period_date") or ""),
            calc_type=str(row.get("calc_type") or ""),
            scale_pct=scale_pct,
            signals=signals,
            note_section_key=note_key,
            note_available=note_available,
        )
        tier = 2 if "adjustment_language" in signals else 1 if note_key else 0
        magnitude = scale_pct if scale_pct is not None else abs(value) if _is_amount(metric_key) else 0.0
        scored.append((tier, magnitude, item))

    scored.sort(key=lambda entry: (-entry[0], -entry[1], entry[2].metric_key))
    page = scored[page_offset : page_offset + page_limit]
    kept = [entry[2] for entry in page]
    remaining = max(0, len(scored) - (page_offset + len(kept)))

    return ClassificationCandidates(
        ticker=ticker.upper(),
        items=tuple(kept),
        scale_base=scale_base,
        scale_label=scale_label,
        total_populated_metrics=len(latest),
        total_candidate_metrics=len(scored),
        offset=page_offset,
        shown=len(kept),
        withheld=remaining,
        zero_valued_adjustment_lines=tuple(sorted(zero_flagged)),
        notes_available=tuple(sorted(k for k in available if k.startswith("note_"))),
        metrics_without_note=tuple(sorted(without_note)),
    )


def group_by_note(candidates: ClassificationCandidates) -> dict[str, list[AdjustableItem]]:
    """Group candidates by governing note so an agent can be asked one note at a time.

    `_unmatched` collects items no extracted note governs — their classification cannot be
    verified against disclosure, which is itself worth reporting.
    """
    grouped: dict[str, list[AdjustableItem]] = {}
    for item in candidates.items:
        key = item.note_section_key if item.has_governing_note else "_unmatched"
        grouped.setdefault(key, []).append(item)
    return grouped


def summarize_candidates(candidates: ClassificationCandidates) -> dict[str, Any]:
    grouped = group_by_note(candidates)
    return {
        "ticker": candidates.ticker,
        "total_populated_metrics": candidates.total_populated_metrics,
        "total_candidate_metrics": candidates.total_candidate_metrics,
        "offset": candidates.offset,
        "shown": candidates.shown,
        "withheld": candidates.withheld,
        "next_offset": candidates.next_offset,
        "zero_valued_adjustment_lines": list(candidates.zero_valued_adjustment_lines),
        "notes_available": list(candidates.notes_available),
        "items_with_governing_note": sum(1 for i in candidates.items if i.has_governing_note),
        "items_without_governing_note": len(grouped.get("_unmatched", [])),
        "by_note": {key: len(items) for key, items in sorted(grouped.items())},
    }
