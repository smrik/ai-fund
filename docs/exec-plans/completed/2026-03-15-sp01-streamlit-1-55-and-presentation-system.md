# SP01 - Streamlit 1.55 and Presentation System

>Status: `todo`
>Primary Skills: `ui-ux-pro-max`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`

## Goal
Finish the Streamlit 1.55 migration cleanly and establish one shared formatting contract for metrics, tables, and charts.

## Files
- Modify: [dashboard/app.py](../../dashboard/app.py)
- Create: [src/stage_04_pipeline/presentation_formatting.py](../../src/stage_04_pipeline/presentation_formatting.py)
- Create: [tests/test_presentation_formatting.py](../../tests/test_presentation_formatting.py)
- Create: [tests/test_dashboard_render_contracts.py](../../tests/test_dashboard_render_contracts.py)

## Current Gaps
- `use_container_width` still appears across the dashboard and continues to emit Streamlit 1.55 deprecation warnings.
- `_format_value()` exists in `dashboard/app.py`, but it does not govern all tables and dataframes.
- Percent rendering and numeric precision are inconsistent across tabs.

## Required Public Interface
Create `presentation_formatting.py` with:

```python
def format_metric_value(value: float | int | None, *, kind: str, decimals: int | None = None) -> str: ...
def format_table_value(value: object, *, kind: str | None = None) -> str: ...
def abbreviate_number(value: float | int | None, *, decimals: int = 1) -> str: ...
def format_percent(value: float | None, *, input_mode: str = "decimal", decimals: int = 1) -> str: ...
def format_negative(value: float | int | None, *, style: str = "parentheses") -> str: ...
def style_dataframe_rows(rows: list[dict], schema: dict[str, str]) -> list[dict]: ...
```

## Formatting Contract
- Percentages render as whole percent strings: `0.10 -> 10.0%`
- Large values abbreviate: `10_000 -> 10.0K`, `1_250_000 -> 1.3M`, `3_400_000_000 -> 3.4B`
- Negatives default to parentheses: `-12.5 -> (12.5)`
- Default decimal precision:
  - prices: `2`
  - percentages: `1`
  - multiples: `1`
  - financial values/counts: `1`
- Streamlit width migration:
  - `use_container_width=True -> width="stretch"`
  - `use_container_width=False -> width="content"`

## Execution Checklist
- [ ] Create failing unit tests for percent, abbreviation, and negative formatting.
- [ ] Implement `presentation_formatting.py` minimally until tests pass.
- [ ] Replace `_format_value()` call sites or route them through the shared module.
- [ ] Replace remaining `use_container_width` call sites in `dashboard/app.py`.
- [ ] Add render-contract tests for representative dashboard sections.
- [ ] Run Streamlit locally and confirm deprecation warnings are removed from primary surfaces.

## Verification
- `python -m pytest tests/test_presentation_formatting.py tests/test_dashboard_render_contracts.py -q`
- `python -m py_compile dashboard/app.py src/stage_04_pipeline/presentation_formatting.py`
- Live IBM dashboard run under `streamlit==1.55.0`
- Playwright check on DCF, Recommendations, Comps, News, and WACC sections

## Acceptance Criteria
- No Streamlit deprecation warnings from `use_container_width` in the main dashboard path.
- Shared formatting helpers govern primary user-facing numeric output.
- No raw decimal percentages leak into visible dashboard surfaces.
