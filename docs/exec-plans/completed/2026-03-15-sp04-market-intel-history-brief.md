# SP04 - Market Intel History Brief

>Status: `todo`
>Primary Skills: `initiating-coverage`, `model-update`, `thesis-tracker`, `sector-overview`

## Goal
Upgrade Market Intel from a short-horizon headline surface into a two-layer view: a multi-year company-event brief on top and a recent-quarter materiality table underneath.

## Files
- Modify: [src/stage_04_pipeline/news_materiality.py](../../../src/stage_04_pipeline/news_materiality.py)
- Modify: [dashboard/app.py](../../../dashboard/app.py)
- Modify: [src/stage_00_data/market_data.py](../../../src/stage_00_data/market_data.py)
- Optional Modify: [src/stage_04_pipeline/report_archive.py](../../../src/stage_04_pipeline/report_archive.py)
- Create: [tests/test_market_intel_history.py](../../../tests/test_market_intel_history.py)

## Chosen Source Strategy
`Hybrid Local`
- recent Yahoo Finance headlines
- archived report snapshots in `pipeline_report_archive`
- filing-derived events
- analyst snapshot changes where locally available
- no new external historical news provider in this tranche

## Required Interface Extension
Extend `build_news_materiality_view()` to return:

```python
{
  "ticker": str,
  "available": bool,
  "historical_brief": {
    "summary": str,
    "event_timeline": list[dict],
    "period_start": str | None,
    "period_end": str | None,
  },
  "quarterly_headlines": list[dict],
  "headlines": list[dict],
  "analyst_snapshot": dict,
  "sentiment_summary": dict,
  "audit_flags": list[str],
}
```

## Functional Requirements
- Build a multi-year event timeline from archived reports and filings-derived material events.
- Summarize that timeline deterministically into a top brief covering:
  - strategic shifts
  - capital structure events
  - acquisitions/divestitures
  - repeated risk themes
- Preserve the recent-quarter materiality table as the detailed layer.
- Display explicit date windows and note when the historical brief is weak because the archive is shallow.
- Be honest in UI copy that this is not a complete historical news database.

## Execution Checklist
- [ ] Add failing tests for limited-history and multi-archive cases.
- [ ] Extend `news_materiality.py` with event-timeline assembly and deterministic summary logic.
- [ ] Normalize recent-quarter vs longer-horizon payloads.
- [ ] Update the dashboard `News & Materiality` section with top brief, date windows, and source-limit warnings.
- [ ] Verify analyst snapshot still renders when headlines are sparse.

## Verification
- `python -m pytest tests/test_market_intel_history.py tests/test_news_materiality.py -q`
- `python -m py_compile src/stage_04_pipeline/news_materiality.py src/stage_00_data/market_data.py dashboard/app.py`
- Live IBM dashboard pass on `News & Materiality`
- Playwright validation on historical brief and quarterly table

## Acceptance Criteria
- The top of Market Intel provides a useful longer-horizon company-event brief.
- Recent-quarter material headlines remain ranked and auditable.
- Source limitations are explicit rather than implied.
