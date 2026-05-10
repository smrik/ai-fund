# SP02 - Comps and Multiples Workbench

>Status: `todo`
>Primary Skills: `financial-modeling`, `comps-analysis`, `competitive-analysis`, `check-model`, `initiating-coverage`, `model-update`

## Goal
Turn the current comps surface into a proper comparable-company workbench with metric selection, target-vs-peer context, football-field output, and a dedicated historical multiples tab.

## Files
- Modify: [dashboard/app.py](../../../dashboard/app.py)
- Modify: [src/stage_04_pipeline/comps_dashboard.py](../../../src/stage_04_pipeline/comps_dashboard.py)
- Modify: [src/stage_00_data/market_data.py](../../../src/stage_00_data/market_data.py)
- Optional Modify: [src/stage_00_data/ciq_adapter.py](../../../src/stage_00_data/ciq_adapter.py)
- Optional Modify: [src/stage_02_valuation/comps_model.py](../../../src/stage_02_valuation/comps_model.py)
- Create: [src/stage_04_pipeline/multiples_dashboard.py](../../../src/stage_04_pipeline/multiples_dashboard.py)
- Create: [tests/test_multiples_dashboard.py](../../../tests/test_multiples_dashboard.py)
- Modify: [tests/test_comps_dashboard.py](../../../tests/test_comps_dashboard.py)

## Current Gaps
- The existing comps tab exposes one primary metric and a peer table, but not metric switching.
- The user cannot easily compare the target company's actual values to peer medians/quartiles.
- There is no football chart and no historical multiples tab.

## Required View Contract
Extend `build_comps_dashboard_view()` to return:

```python
{
  "ticker": str,
  "available": bool,
  "target": dict,
  "peers": list[dict],
  "metric_options": list[str],
  "selected_metric_default": str,
  "target_vs_peers": dict,
  "football_field": list[dict],
  "historical_multiples_summary": dict,
  "valuation_range_by_metric": dict,
  "peer_counts": dict,
  "audit_flags": list[str],
}
```

Create `multiples_dashboard.py` with:

```python
def build_multiples_dashboard_view(
    ticker: str,
    *,
    period: str = "5y",
    metrics: tuple[str, ...] = ("pe_trailing", "ev_ebitda", "ev_revenue", "price_to_book"),
) -> dict: ...
```

## Functional Requirements
- Metric selector for:
  - `EV/Revenue`
  - `EV/EBITDA`
  - `EV/EBIT`
  - `P/E`
  - `P/B`
  - `P/S`
- Target-vs-peer panel for:
  - growth
  - margins
  - leverage
  - key multiples
- Football chart showing:
  - current price
  - DCF base value
  - comps bear/base/bull by selected metric
  - analyst target mean if available
- Historical multiples tab showing:
  - target historical bands
  - current vs 1Y/3Y/5Y percentile
  - current peer snapshot alongside
- Audit metadata:
  - source lineage
  - similarity model
  - weighting formula
  - outlier removals

## Execution Checklist
- [ ] Add failing tests for metric selection and historical multiples output.
- [ ] Extend `build_comps_dashboard_view()` with metric-oriented valuation payloads.
- [ ] Add `multiples_dashboard.py` for historical multiple calculations.
- [ ] Update the dashboard UI to show the selector, target-vs-peer block, football chart, and historical multiples tab.
- [ ] Degrade gracefully when CIQ or similarity data is partial.

## Verification
- `python -m pytest tests/test_comps_dashboard.py tests/test_multiples_dashboard.py -q`
- `python -m py_compile dashboard/app.py src/stage_04_pipeline/comps_dashboard.py src/stage_04_pipeline/multiples_dashboard.py`
- Live IBM dashboard pass on `Comps` and `Multiples`
- Playwright switch across metrics and tabs

## Acceptance Criteria
- The user can switch metrics and see valuation impact.
- The target company is visible beside peer medians/quartiles.
- A football chart and historical multiples tab are present and auditable.
- The surface reads like research analysis, not a raw table dump.
