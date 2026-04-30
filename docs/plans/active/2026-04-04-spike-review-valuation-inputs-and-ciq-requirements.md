# Program: Valuation Methodology Hardening And CIQ Retrieval Requirements

## Goal

Harden the valuation methodology into concrete contracts, deterministic checks, PM review gates, and CIQ/API requirements.

The CIQ retrieval audit remains part of this work, but it now sits inside a broader valuation-methodology hardening program.

## Scope

- review the valuation canon under `docs/valuation/` against public-equity PM best practice
- trace the deterministic valuation flow from `build_valuation_inputs()` through `value_single_ticker()`
- document step-by-step inputs, outputs, formulas, lineage, and weak contracts
- build a CIQ retrieval requirement matrix for snapshot, long-form, comps, and bridge-item data
- identify structural methodology gaps, not only field-coverage gaps
- convert the PM checklist comments into concrete methodology fixes and issue-ready tracks
- keep the methodology review layer lean: one critical review and action memo, not a recursive research pack

## Workflow

1. **Audit**
   - review the valuation canon and current deterministic flow
2. **Consolidate**
   - maintain one critical review and action memo with the live methodology gaps
3. **Canon fixes**
   - update `docs/valuation/` where the finance logic is already clear enough
4. **Executable contracts**
   - specify schemas and deterministic range rules before implementation
5. **Split into issues**
   - convert approved methodology gaps into implementation issues and sequencing

## Deliverables

- `docs/design-docs/deterministic-valuation-inputs-and-ciq-retrieval-spec.md`
- `docs/design-docs/deterministic-valuation-benchmark-and-gap-analysis.md`
- `docs/design-docs/valuation-methodology-critical-review-and-action-plan.md`
- updates to the design-doc index and plan registry

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
- the benchmark doc records:
  - external valuation principles
  - Alpha Pod alignment vs gaps
  - issue-ready follow-up recommendations
- the methodology action memo records:
  - stage-by-stage critical findings
  - PM checklist decisions
  - prioritized recommendations
  - concrete schema and control candidates
- `python -m mkdocs build --strict` passes

## Remaining Follow-Up

- specify executable contracts for:
  - assumption register and accepted-range design
  - LLM-assisted reclassification board
  - multi-method WACC triangulation
  - multi-source peer-universe construction
  - impact / confidence PM decision queue
- continue adjusting the canonical valuation docs where the action memo identifies concrete finance gaps
- decide which CIQ gaps should be solved first in the retrieval layer versus deferred to downstream API/JSON contract work
- translate the approved recommendation set into implementation issues
- use the approved methodology and CIQ specs as the basis for canonical dossier/API contract work under the dossier-integrity epic
