"""Deterministic evidence marshalling for the story-profile judgment call.

The story profile (moat, pricing power, cyclicality, capital intensity, governance risk,
advantage durability) drives eight quantitative valuation drivers via
`story_drivers.apply_story_driver_adjustments`. Under
[Vision Decision 13](../../docs/strategy/vision.md#the-division-of-labor) it is authored by the
judgment layer — which means it has to be authored *from evidence*, not from what a model happens
to recall about a well-known ticker.

This module is the deterministic half of that seam: it marshals real filing evidence out of the
`company_analysis` evidence packet and hands the agent a bounded, anchored context. It contains
no LLM call and makes no judgment; deciding the scores is the agent's job.

The refusal path matters as much as the happy path. An agent asked to score a moat with no
evidence will still produce confident-looking numbers, and those numbers now carry full authority
(`story_ticker_pending_approved`). Emitting nothing is the correct outcome when there is nothing
to reason over.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bounded so a long 10-K cannot blow up the agent context. These are engineering choices, logged
# per Decision 11: enough disclosure to judge a moat, not the whole filing.
MAX_SNIPPETS = 14
MAX_SNIPPET_CHARS = 1_200
MIN_SNIPPETS_REQUIRED = 2

# Terms that indicate an excerpt bears on one of the six profile fields. This is a deterministic
# relevance heuristic, not semantic retrieval — it is here because taking excerpts in packet order
# fills the context with the front matter of a 10-K. Measured on MSFT: packet order yielded one
# boilerplate block, four generic business-description blocks, and one about the sustainability
# report; none discussed competitive position.
_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "moat_strength": (
        "switching cost", "network effect", "proprietary", "patent", "intellectual property",
        "barrier to entry", "competitive advantage", "differentiat", "ecosystem", "lock-in",
    ),
    "pricing_power": (
        "pricing", "price increase", "premium", "discount", "renewal rate", "contract value",
        "average selling price", "monetiz",
    ),
    "cyclicality": (
        "cyclical", "demand environment", "macroeconomic", "recession", "seasonal", "downturn",
        "volatility in demand",
    ),
    "capital_intensity": (
        "capital expenditure", "capex", "datacenter", "data center", "property and equipment",
        "infrastructure investment", "build-out", "capacity",
    ),
    "governance_risk": (
        "capital allocation", "share repurchase", "dividend", "acquisition", "related party",
        "internal control", "material weakness", "executive compensation",
    ),
    "competition": (
        "compet", "market share", "rival", "alternative offerings", "substitut",
    ),
}

# Front-matter and cross-reference language that carries no analytical signal.
_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "forward-looking statement", "cautioned not to place", "undue reliance", "safe harbor",
    "incorporated by reference", "see item", "refer to note", "table of contents",
    "sustainability report", "this annual report on form",
)


def _relevance_score(text: str) -> tuple[int, int]:
    """Return (matched_field_count, total_term_hits) for a candidate excerpt.

    Field count leads so an excerpt touching several profile dimensions outranks one that repeats
    a single term.
    """
    low = text.lower()
    fields = 0
    hits = 0
    for terms in _FIELD_TERMS.values():
        matched = sum(1 for term in terms if term in low)
        if matched:
            fields += 1
            hits += matched
    return fields, hits


def _is_boilerplate(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _BOILERPLATE_MARKERS)


@dataclass(frozen=True)
class StoryProfileContext:
    """Evidence handed to the judgment layer for the story-profile call.

    `status` is `ok` when there is enough evidence to reason over, and
    `insufficient_evidence` otherwise. Callers must not ask the agent for a profile when the
    status is not `ok` — see module docstring.
    """

    ticker: str
    company_name: str
    sector: str
    industry: str
    status: str
    context_text: str
    evidence_anchor_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    snippet_count: int = 0
    fact_count: int = 0
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return self.status == "ok"


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _format_fact(fact: Any) -> str | None:
    name = _clean(getattr(fact, "fact_name", ""))
    if not name:
        return None
    value = getattr(fact, "value", None)
    if value is None:
        return None
    unit = _clean(getattr(fact, "unit", "") or "")
    rendered = f"{value}{f' {unit}' if unit else ''}"
    return f"- {name}: {_clean(rendered)}"


def build_story_profile_context(
    packet: Any,
    *,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    industry_packet: Any | None = None,
) -> StoryProfileContext:
    """Marshal a `company_analysis` evidence packet into anchored story-profile context.

    `industry_packet` is optional upstream context (Decision 14: business analysis reads the
    industry view). When absent the context is still usable — it is a narrowing of evidence, not
    a failure.
    """
    ticker = _clean(getattr(packet, "ticker", "")).upper()
    snippets = list(getattr(packet, "snippets", None) or [])
    facts = list(getattr(packet, "facts", None) or [])
    source_refs = list(getattr(packet, "source_refs", None) or [])

    # Rank by relevance to the six profile fields rather than taking packet order. Boilerplate
    # with no signal is dropped outright; boilerplate that also discusses competition is kept,
    # since risk-factor sections often mix the two.
    candidates: list[tuple[int, int, int, str, str, str]] = []
    for position, snippet in enumerate(snippets):
        text = _clean(getattr(snippet, "text", ""))
        if not text:
            continue
        fields, hits = _relevance_score(text)
        if fields == 0 and _is_boilerplate(text):
            continue
        snippet_id = _clean(getattr(snippet, "snippet_id", ""))
        source_ref_id = _clean(getattr(snippet, "source_ref_id", ""))
        candidates.append((fields, hits, -position, text, snippet_id, source_ref_id))

    # Highest relevance first; original order breaks ties so selection stays deterministic.
    candidates.sort(reverse=True)

    anchor_ids: list[str] = []
    snippet_blocks: list[str] = []
    for fields, hits, _pos, text, snippet_id, source_ref_id in candidates[:MAX_SNIPPETS]:
        if snippet_id:
            anchor_ids.append(snippet_id)
        label = source_ref_id or snippet_id or "filing"
        snippet_blocks.append(f"[{label}] {text[:MAX_SNIPPET_CHARS]}")

    fact_lines: list[str] = []
    for fact in facts:
        line = _format_fact(fact)
        if line is None:
            continue
        fact_lines.append(line)
        fact_id = _clean(getattr(fact, "fact_id", ""))
        if fact_id:
            anchor_ids.append(fact_id)

    ref_lines: list[str] = []
    ref_ids: list[str] = []
    for ref in source_refs:
        ref_id = _clean(getattr(ref, "source_ref_id", ""))
        if not ref_id:
            continue
        ref_ids.append(ref_id)
        label = _clean(getattr(ref, "source_label", "")) or _clean(getattr(ref, "source_kind", ""))
        locator = _clean(getattr(ref, "source_locator", ""))
        ref_lines.append(f"- {ref_id}: {label}{f' ({locator})' if locator else ''}")

    industry_blocks: list[str] = []
    if industry_packet is not None:
        for snippet in list(getattr(industry_packet, "snippets", None) or [])[:4]:
            text = _clean(getattr(snippet, "text", ""))
            if text:
                industry_blocks.append(f"- {text[:MAX_SNIPPET_CHARS]}")

    resolved = {
        "company_name": _clean(company_name) or ticker,
        "sector": _clean(sector) or "Unknown",
        "industry": _clean(industry) or "Unknown",
    }

    if len(snippet_blocks) < MIN_SNIPPETS_REQUIRED:
        return StoryProfileContext(
            ticker=ticker,
            company_name=resolved["company_name"],
            sector=resolved["sector"],
            industry=resolved["industry"],
            status="insufficient_evidence",
            context_text="",
            snippet_count=len(snippet_blocks),
            fact_count=len(fact_lines),
            detail=(
                f"Only {len(snippet_blocks)} usable filing excerpt(s); "
                f"{MIN_SNIPPETS_REQUIRED} required. A story profile scored without disclosure "
                "evidence is model recall, not analysis, and would carry full driver authority."
            ),
        )

    sections = [
        f"TICKER: {ticker}",
        f"COMPANY: {resolved['company_name']}",
        f"SECTOR: {resolved['sector']}",
        f"INDUSTRY: {resolved['industry']}",
        "",
        "=== FILING EXCERPTS (cite these anchors in your evidence_basis) ===",
        *snippet_blocks,
    ]
    if fact_lines:
        sections += ["", "=== DETERMINISTIC FACTS ===", *fact_lines]
    if industry_blocks:
        sections += ["", "=== INDUSTRY CONTEXT (upstream) ===", *industry_blocks]
    if ref_lines:
        sections += ["", "=== SOURCE REFERENCES ===", *ref_lines]

    return StoryProfileContext(
        ticker=ticker,
        company_name=resolved["company_name"],
        sector=resolved["sector"],
        industry=resolved["industry"],
        status="ok",
        context_text="\n".join(sections),
        evidence_anchor_ids=tuple(dict.fromkeys(anchor_ids)),
        source_ref_ids=tuple(dict.fromkeys(ref_ids)),
        snippet_count=len(snippet_blocks),
        fact_count=len(fact_lines),
        metadata={
            "industry_context_used": bool(industry_blocks),
            "packet_id": getattr(packet, "packet_id", None),
        },
    )
