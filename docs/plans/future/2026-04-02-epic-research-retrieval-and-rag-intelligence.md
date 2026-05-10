# Epic: Research Retrieval And RAG Intelligence

| Field | Value |
|---|---|
| Status | Planned |
| Priority | P1 |
| Target release | v0.3.0 Research Intelligence |
| GitHub | Epic issue to be created |
| Last updated | 2026-04-02 |

## Problem

Alpha Pod already stores filings and embeddings, but the research experience still needs stronger retrieval quality, clearer evidence contracts, and a cleaner split between deterministic retrieval and LLM-generated analysis.

## Smallest Valuable Outcome

The system can answer filing-backed questions with explicit citations and reliable retrieval filters, and higher-level RAG analysis stays clearly separate from the underlying evidence engine.

## In Scope

- Filing corpus storage audit and cleanup
- Section-aware retrieval with filing/date filters
- Evidence-first response contract for filing search
- RAG analysis layer for Q&A, synthesis, and memo assistance
- Retrieval diagnostics and evaluation coverage

## Out Of Scope

- Generic chatbot productization
- LLM-controlled valuation inputs
- Social or collaborative note features

## Dependencies

- Stable filing/chunk metadata
- Clear storage ownership for research artifacts
- Canonical dossier and audit surfaces to display evidence

## Acceptance Criteria

- Retrieval responses include answer, cited excerpts, and filing references
- Filing search supports useful scope filters instead of naive top-K only behavior
- RAG analysis outputs remain advisory and trace back to visible evidence
- Retrieval quality is measurable through focused evaluation tests or fixtures

## Notes

This epic absorbs the useful parts of the earlier XBRL/RAG exploration while removing the older Streamlit-first framing.
