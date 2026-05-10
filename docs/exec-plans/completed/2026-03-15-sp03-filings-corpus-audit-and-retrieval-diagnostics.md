# SP03 - Filings Corpus Audit and Retrieval Diagnostics

>Status: `todo`
>Primary Skills: `edgartools`, `earnings-analysis`, `model-update`, `systematic-debugging`

## Goal
Verify that the 10-K and 10-Q corpus is complete enough for accounting analysis and expose diagnostics showing exactly what the agents actually see.

## Files
- Modify: [src/stage_00_data/filing_retrieval.py](../../../src/stage_00_data/filing_retrieval.py)
- Modify: [src/stage_04_pipeline/filings_browser.py](../../../src/stage_04_pipeline/filings_browser.py)
- Modify: [dashboard/app.py](../../../dashboard/app.py)
- Optional Modify: [src/stage_00_data/edgar_client.py](../../../src/stage_00_data/edgar_client.py)
- Create: [tests/test_filing_retrieval_diagnostics.py](../../../tests/test_filing_retrieval_diagnostics.py)
- Create: [tests/test_filings_browser_diagnostics.py](../../../tests/test_filings_browser_diagnostics.py)

## Current Gaps
- The notes-first retrieval layer exists, but the UI does not clearly surface statement completeness.
- The filings browser shows text and chunks, but not whether Item 8, notes, or quarterly notes were actually present.
- Retrieval fallback mode and section-coverage decisions are not obvious to the user.

## Required Interface Extension
Extend filing corpus and/or agent filing context payloads with:

```python
{
  "statement_presence": {
    "financial_statements": bool,
    "notes_to_financials": bool,
    "mda": bool,
    "risk_factors": bool,
    "quarterly_notes": bool,
  },
  "section_coverage": dict,
  "retrieval_diagnostics": {
    "selected_chunk_count": int,
    "skipped_sections": list[str],
    "fallback_mode": bool,
    "embedding_model": str | None,
    "corpus_hash": str,
  },
}
```

Extend `build_filings_browser_view()` with:

```python
{
  "coverage_summary": dict,
  "retrieval_profiles": dict,
  "statement_presence_by_filing": dict,
}
```

## Functional Requirements
- Detect whether financial statements and notes are actually present in the extracted sections.
- Flag partial extraction and fallback behavior explicitly.
- Show chunk eligibility vs selected chunks by agent profile.
- Provide direct links from diagnostics to clean text, raw HTML, and selected chunks.
- Keep this work observability-only; do not mutate deterministic valuation logic.

## Execution Checklist
- [ ] Add failing tests for statement presence and fallback diagnostics.
- [ ] Extend `filing_retrieval.py` to emit coverage/diagnostic metadata.
- [ ] Extend `filings_browser.py` to aggregate that metadata into a UI-friendly view.
- [ ] Update the `Filings Browser` dashboard section with a statement-coverage panel and warnings.
- [ ] Verify graceful degradation on partial/malformed filing text.

## Verification
- `python -m pytest tests/test_filing_retrieval_diagnostics.py tests/test_filings_browser_diagnostics.py -q`
- `python -m py_compile src/stage_00_data/filing_retrieval.py src/stage_04_pipeline/filings_browser.py dashboard/app.py`
- Live IBM dashboard pass on `Filings Browser`
- Playwright validation on coverage summary, warnings, and source links

## Acceptance Criteria
- The user can tell whether the agents saw real statements/notes or only partial text.
- Missing notes or missing financial statements are explicit in the UI.
- Retrieval fallback behavior is visible instead of silent.
