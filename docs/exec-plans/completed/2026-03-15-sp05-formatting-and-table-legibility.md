# SP05 - Formatting and Table Legibility

>Status: `todo`
>Primary Skills: `ui-ux-pro-max`, `verification-before-completion`

## Goal
Apply one coherent readability standard across dashboard tables, metrics, and metadata so the UI stops leaking raw floats and inconsistent alignment.

## Files
- Modify: [dashboard/app.py](../../dashboard/app.py)
- Modify: [src/stage_04_pipeline/presentation_formatting.py](../../src/stage_04_pipeline/presentation_formatting.py)
- Create: [tests/test_dashboard_number_formatting.py](../../tests/test_dashboard_number_formatting.py)

## Display Rules
- percentages render as `10.0%`
- large values render as `10.0K`, `2.5M`, `3.4B`
- multiples render as `12.3x`
- negatives render as `(12.3)`
- numeric defaults use one decimal unless precision truly requires two
- table schemas define numeric rendering explicitly instead of ad hoc per table

## Surfaces In Scope
- DCF Audit
- Recommendations
- Assumption Lab
- Comps
- WACC Lab
- News & Materiality
- Past Reports summary rows
- Agent audit metadata with visible numeric fields

## Execution Checklist
- [ ] Add failing tests for dashboard-visible number formatting.
- [ ] Extend `presentation_formatting.py` to cover metric, table, multiple, and bracketed-negative use cases.
- [ ] Replace ad hoc formatting in visible dashboard tables with schema-driven rendering.
- [ ] Verify table alignment survives both empty and populated states.
- [ ] Confirm that no main user-facing surface shows raw decimal percentages or raw Python float artifacts.

## Verification
- `python -m pytest tests/test_presentation_formatting.py tests/test_dashboard_number_formatting.py -q`
- `python -m py_compile dashboard/app.py src/stage_04_pipeline/presentation_formatting.py`
- Live IBM dashboard sweep across key tabs
- Playwright spot-check on tables and summary metrics

## Acceptance Criteria
- Tables are materially easier to scan.
- Number formatting is consistent across tabs.
- There are no obvious raw-float leaks in the user-facing dashboard.
