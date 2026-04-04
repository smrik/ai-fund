# Spike: Review Valuation Inputs And CIQ Retrieval Requirements

## Goal

Audit the actual deterministic single-ticker valuation path to identify every material input it needs, which systems currently provide those inputs, and what CIQ must retrieve to support the next API, JSON export, and Excel-template work cleanly.

## Scope

- trace the deterministic valuation flow from `build_valuation_inputs()` through `value_single_ticker()`
- document step-by-step inputs, outputs, formulas, and lineage
- build a CIQ retrieval requirement matrix for snapshot, long-form, comps, and bridge-item data
- identify key current-state gaps and ambiguous ownership between CIQ, yfinance, XBRL, config defaults, and derived values
- map the deterministic outputs that downstream API, JSON export, and Excel flows depend on

## Deliverables

- `docs/design-docs/deterministic-valuation-inputs-and-ciq-retrieval-spec.md`
- updates to the design-doc index and plan registry
- cross-links from the existing deterministic valuation workflow docs to the new audit/spec

## Verification

- the new design doc reflects the current code path in:
  - `src/stage_02_valuation/input_assembler.py`
  - `src/stage_02_valuation/batch_runner.py`
  - `src/stage_00_data/ciq_adapter.py`
- each deterministic valuation step has explicit inputs, outputs, and source systems
- every material DCF driver and EV bridge item is covered by either:
  - a documented retrieval source
  - a documented fallback
  - or an explicit gap entry
- `python -m mkdocs build --strict` passes

## Remaining Follow-Up

- decide which CIQ gaps should be solved first in the retrieval layer versus deferred to downstream API/JSON contract work
- translate the documented gap list into implementation issues once the spike is reviewed
- use this spec as the basis for the canonical dossier/API contract work under the dossier-integrity epic
