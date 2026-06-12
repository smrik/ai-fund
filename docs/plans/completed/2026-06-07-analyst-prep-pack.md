# Analyst Prep Pack MVP

## Status

Active implementation slice for the v0.1 alpha PM workflow.

## Goal

Produce a junior-analyst prep packet for one ticker before senior PM review:

```text
CIQ / Yahoo / SEC / Comps data
-> deterministic evidence packets
-> grounded observation profiles
-> deterministic thesis/model bridge
-> Research UI + PM Queue + Excel export
```

## Shipped In This Slice

- `src/contracts/analyst_prep_pack.py` defines the pack contract, thesis cards, driver cards, comps card, missing-data flags, and segment rows.
- `src/stage_04_pipeline/analyst_prep_pack.py` builds the pack deterministically from valuation inputs, DCF audit, comps dashboard, existing evidence packets, PM Queue items, conflict groups, and default-resolution warnings.
- `GET /api/tickers/{ticker}/analyst-prep` returns the current pack.
- `POST /api/tickers/{ticker}/analyst-prep/run` queues a deterministic rebuild.
- `scripts/manual/run_analyst_prep_pack.py` runs the existing ticker valuation/profile flow, builds the pack, and exports JSON/Markdown/Excel artifacts.
- React Research page shows Analyst Prep above the existing research board.
- Valuation Summary/DCF tabs show a compact Thesis Bridge.
- Excel ticker exports now include `Analyst_Prep`, `Thesis_Bridge`, `Model_Driver_Map`, `Evidence_Map`, `Comps_Judgment`, and `Segment_Drivers`.
- `analyst_prep_synthesis` is registered as a non-mutating grounded observation profile over Analyst Prep pack payloads.
- Deterministic segment parsing now scans CIQ long-form rows that explicitly identify segments/business units and derives revenue growth, revenue mix, and margin only from those rows.

## Boundaries

- LLMs may produce grounded observations and explanations.
- Deterministic code owns numeric values, model-driver mapping, source lineage, preview/apply, and Excel export shape.
- No Analyst Prep card may mutate valuation assumptions. PM Queue approval remains the only model-change path.
- Segment economics still fail closed when no explicit CIQ segment/business-unit rows are present; the current MSFT clean workbook has no parsed segment rows, so the pack correctly flags segment evidence as missing.
- `analyst_prep_synthesis` produces observations only; deterministic cards remain the pack source of truth for v0.1.

## Operator Command

```powershell
rtk python scripts/manual/run_analyst_prep_pack.py --ticker IBM --agent-mode heuristic --isolated-db --export-xlsx
```

For CIQ-backed testing after manually refreshing `ciq/templates/ciq_cleandata.xlsx`:

```powershell
rtk python scripts/manual/run_analyst_prep_pack.py --ticker MSFT --ingest-ciq-template --agent-mode heuristic --isolated-db --export-xlsx
```

## Remaining Follow-Ups

- Extend segment extraction to SEC segment snippets if CIQ segment tabs are unavailable.
- Evaluate whether `analyst_prep_synthesis` observations should promote into richer thesis cards after enough real PM review.
- Persist built prep packs if historical pack comparison becomes useful.
- Add deeper UI affordances for evidence-anchor expansion.
