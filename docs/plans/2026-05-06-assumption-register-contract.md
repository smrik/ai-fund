# Assumption Register Contract Implementation Plan

## Summary

Build the first executable assumption-register layer for Alpha Pod.

V1 is intentionally narrow:

- numeric ticker-level DCF drivers only
- deterministic-only population
- flag-only validation, no valuation blocking
- global contract available to all stages
- stage 02 builder populates the register from valuation inputs
- append-only audit table captures material events

This is the foundation for later LLM advisory inputs, Damodaran data, WACC policy inputs, and richer industry/company-specific range rules.

## Decisions

- Contract location: define shared types in `src/contracts/assumption_register.py`.
- Builder location: build valuation-specific entries in `src/stage_02_valuation/assumption_register.py`.
- Contract boundary: Pydantic models define the public boundary; stage 02 may build lightweight dict payloads internally and validate once into `AssumptionRegister`.
- V1 scope: populate ticker-level DCF driver assumptions only.
- Future scope: contract may represent ticker, sector, industry, and global identities, but sector/global policy population is V2.
- Entity identity: V1 entries represent effective ticker assumptions, so populated entries use `entity_type="ticker"` even when source lineage points to sector/global defaults or overrides.
- Value types: numeric only in V1; reserve `value_type="numeric"` for future compatibility.
- Scenarios: V1 does not add scenario probabilities or context scenario outputs to the register; scenario assumption packs are V2.
- Terminal value: terminal value drivers are first-class V1 assumption entries; terminal concentration and computed terminal values remain diagnostics.
- LLMs: no LLM or agent output populates or mutates the register in V1.
- Future LLM work: V2 connects `driver_assessments.py` and judgment agents as advisory inputs.
- Advisory reserve: V1 reserves neutral advisory attachment fields, but leaves them empty and does not import `driver_assessments.py` workflow states into the official contract.
- Ranges: static fallback ranges in V1; historical, industry, and scale-aware rules are V2.
- Flags: out-of-range values flag for review but do not block valuation.
- Flag semantics: V1 defines deterministic meanings for `none`, `watch`, `review_required`, and `critical`; flags are severity labels, not PM approval state.
- Model trust: out-of-range and critical flags do not block computation or export in V1, but they must downgrade the valuation's review/trust state on ranked and dossier/export surfaces.
- Model trust rollup: derive `model_trust_state` from max assumption flag level plus selected valuation diagnostics such as terminal concentration or mathematically dangerous guardrails.
- Approval: register displays approval state, but durable truth remains in PM override and audit records.
- Approval granularity: PM approval is value-specific; material value changes make approval stale or review-needed.
- Approval references: `approval_ref` points only to durable PM-applied audit rows, such as `valuation_override_audit` or `wacc_methodology_audit`; pending recommendation files belong in `advisory_refs`.
- WACC treatment: final WACC and its material cost-of-capital components are first-class assumption entries in V1.
- WACC approval staleness: assess staleness at the component level; material movement in beta, ERP, size premium, cost of debt, weights, or methodology can make that component stale even when final WACC moves less than 25 bps.
- Naming discipline: V1 uses stable field keys and controlled stage/scope/forecast-line vocabularies so register entries are filterable and testable.
- Accepted ranges: V1 range rules are PM-review ranges for effective values, not necessarily the same as input-assembly hard clamps.
- Materiality rules: keep provisional thresholds in a centralized table near the builder/diff logic rather than scattered inline conditionals.
- Audit: append material events only, not every generated assumption on every run.
- First-seen audit: log first-seen events only for review-relevant entries in V1; the full generated baseline remains in valuation JSON, not the audit table.
- Audit payloads: store concise prior/new diffs for changed fields, not full entry snapshots or full-register snapshots.
- Valuation impact: optional in entries; required only for override preview/apply paths.
- Automatic impact scoring: V1 does not run per-assumption what-if DCFs for every flagged entry; broader sensitivity-driven impact scoring is V2.
- Exports: full register in valuation JSON; compact flagged summary in ticker dossier V1.
- Compact summary: dossier/export/ranking summaries include trust state, flag counts, max flag, and flagged entries only; clean assumptions stay in the full valuation JSON register.
- API audit families: expose existing PM override audit and new assumption-register audit as separate payload keys in V1.

## Contract Shape

Create shared Pydantic v2 models under `src/contracts/assumption_register.py`.

Core enums:

- `AssumptionEntityType`: `ticker`, `sector`, `industry`, `global`
- `AssumptionOwner`: `deterministic`, `pm_override`, `system_flag`
- `AssumptionApprovalState`: `none`, `review_required`, `pm_approved`, `rejected`, `stale_approval`
- `FlagLevel`: `none`, `watch`, `review_required`, `critical`
- `AssumptionValueType`: `numeric`

Owner semantics:

- `deterministic`: official value is owned by deterministic data/config/model logic.
- `pm_override`: official value is owned by a PM-approved override, regardless of whether the idea originated from manual review or an advisory agent.
- `system_flag`: entry is generated to surface a system diagnostic or guardrail rather than a PM-authored value.

Detailed provenance remains in `source_lineage`, `approval_ref`, and `advisory_refs`; `owner` should not encode source strings such as `override_ticker`, `qoe_llm_approved`, or `story_profile`.

Naming conventions:

- `assumption_name`: machine-stable key matching `ForecastDrivers` or WACC input names where possible, such as `revenue_growth_near`, `ebit_margin_target`, `wacc`, `beta_relevered`, or `exit_multiple`.
- `stage`: controlled workflow location; V1 values are `input_assembly`, `wacc`, `dcf`, and `terminal_value`.
- `scope`: PM-facing grouping; V1 values are `growth`, `margin`, `tax`, `working_capital`, `reinvestment`, `wacc`, `terminal_value`, and `capital_structure`.
- `affected_forecast_lines`: stable line names; V1 values include `revenue`, `ebit`, `nopat`, `fcff`, `terminal_value`, `enterprise_value`, and `equity_value`.

Flag-level semantics:

- `none`: value is inside accepted range and has no review-state issue.
- `watch`: value is near a boundary or has a weak deterministic diagnostic, but is still usable.
- `review_required`: value is outside accepted range, approval is stale, source/range/owner changed materially, or PM review is required before trust improves.
- `critical`: value or diagnostic is mathematically dangerous or valuation-trust dangerous, such as impossible values, terminal denominator failure, terminal growth above guardrail, or WACC-method disagreement above the critical threshold.

Core entry fields:

- `entity_type`
- `entity_id`
- `ticker`
- `assumption_name`
- `scope`
- `stage`
- `value_type`
- `current_value`
- `accepted_low`
- `accepted_high`
- `range_rule_id`
- `range_rule_description`
- `source_lineage`
- `affected_forecast_lines`
- `flag_level`
- `owner`
- `approval_state`
- `approval_ref`
- `out_of_range`
- `valuation_impact`
- `evidence_refs`
- `advisory_refs`
- `notes`

Register fields:

- `ticker`
- `generated_at`
- `entries`
- `flag_counts`
- `max_flag_level`
- `has_critical`
- `model_trust_state`
- `summary`

Model trust semantics:

- `clean`: no assumption flags above `none` and no major valuation diagnostics.
- `watch`: max flag is `watch` or terminal concentration is elevated but not dangerous.
- `review_required`: max flag is `review_required`, stale approval exists, or major diagnostics such as `tv_high_flag` fire.
- `critical_review_required`: max flag is `critical` or mathematically dangerous diagnostics fire.

## Implementation

Execution requirements:

- Use relevant skills before implementation. Start with `executing-plans`; use `requesting-code-review` before final handoff.
- Use `rtk` for Git, test, and repo-inspection commands where available.
- Read `AGENTS.md`, `.agent/session-state.md`, and this plan before changing code.
- Keep `course/` and other unrelated untracked local artifacts out of the branch.
- Preserve the deterministic/LLM boundary: no LLM or advisory output may mutate official valuation inputs except through the PM-approved override path.
- Ship V1 as one coherent PR with internally sliced commits/checkpoints rather than multiple partially wired PRs.

1. Add shared contracts.
   - Create `src/contracts/__init__.py` if needed.
   - Add `src/contracts/assumption_register.py`.
   - Keep this module free of stage 02 imports.

2. Add stage 02 builder.
   - Create `src/stage_02_valuation/assumption_register.py`.
   - Build entries from `ForecastDrivers` and `source_lineage`.
   - Use lightweight internal payload construction if helpful, then validate once against `AssumptionRegister` at the contract boundary.
   - Cover the core numeric DCF drivers already shown in the assumptions workbench.
   - Cover terminal value drivers: `revenue_growth_terminal`, `ronic_terminal`, `exit_multiple`, `terminal_blend_gordon_weight`, and `terminal_blend_exit_weight`.
   - Cover WACC assumption inputs from `wacc_inputs`, including final WACC, risk-free rate, equity risk premium, beta, size premium, cost of debt, equity/debt weights, and selected methodology where available.
   - Populate V1 entries as effective ticker assumptions; preserve sector/global origins in lineage/scope without creating sector/global policy rows.
   - Use static fallback `RANGE_RULES`.
   - Do not simply mirror `_bounded()` hard clamps as accepted ranges when the PM-review range should be narrower or differently described.
   - If raw/pre-clamp evidence is readily available, mention it in `evidence_refs` or `notes`; do not add a V1 `raw_value` field.
   - Mark `owner=pm_override` when source lineage or override state indicates an approved override; keep detailed origin in lineage and references.

3. Add materiality and diff logic.
   - Define centralized `MATERIALITY_RULES` keyed by field class, scope, or explicit assumption name.
   - Implement field-class thresholds for V1:
     - WACC: 25 bps
     - WACC components: 25 bps for rate components, 0.10 beta points for beta, 5 percentage points for capital structure weights, any selected-methodology change
     - other percentage drivers: 50 bps
     - multiples: 0.5x
     - working-capital days: 5 days
     - money fields: greater of USD 10m or 1% of revenue base
   - Always treat flag, source, owner, approval, and range-rule changes as material.
   - Document these thresholds as provisional.

4. Add append-only audit.
   - Add `assumption_register_audit` to `db/schema.py`.
   - Add insert/list helpers to `db/loader.py` or a focused stage 04 helper.
   - Log only material events:
     - first seen when the entry is review-relevant
     - value materially changed
     - flag changed
     - source changed
     - owner or approval state changed
     - range rule changed
     - PM override applied or removed
   - Include `event_ts`, `actor`, `actor_type`, `entity_type`, `entity_id`, `ticker`, `assumption_name`, `scope`, `event_type`, prior/new diff JSON, optional valuation impact, and reason.
   - Keep audit rows concise; do not duplicate the full register or full entry payload in every audit row.

5. Wire valuation outputs.
   - In `batch_runner.value_single_ticker()`, attach `assumption_register_json`.
   - In `json_exporter`, add top-level `assumption_register`.
   - In `dcf_audit` or workspace views, expose a compact flag summary where useful.

6. Wire workbench and API.
   - Extend `override_workbench.build_override_workbench()` with `assumption_register`.
   - Add assumption-register audit rows to the valuation assumptions payload as `assumption_register_audit_rows`.
   - Preserve existing override audit rows separately as `override_audit_rows`; keep legacy `audit_rows` only as a compatibility alias if needed.
   - Preserve existing `valuation_overrides.yaml` as the official PM write path.
   - On override preview/apply, compute and store optional valuation-impact metadata.
   - Do not compute automatic per-flag valuation impact outside preview/apply paths in V1.

7. Wire dossier/export summary.
   - Keep full register in valuation JSON.
   - Add compact summary to ticker dossier/export surfaces:
     - max flag
     - flag counts
     - model trust state
     - flagged entries only
   - Do not include clean-but-important assumptions in the compact V1 summary; use full valuation JSON for drill-down.
   - Preserve deterministic output rows for flagged valuations, but make review-required or critical-review-required trust state visible in ranking/export payloads.

8. Update docs.
   - Mark the critical-review memo's P0 assumption-register item as implemented once shipped.
   - Add V2 notes for:
     - LLM advisory attachment through `driver_assessments.py`
     - population of reserved `advisory_refs`
     - scale-aware materiality
     - history/industry/Damodaran range rules
     - sector/global policy population

## Tests

Add or extend:

- `tests/test_assumption_register.py`
- `tests/test_api_contracts.py`
- `tests/test_batch_runner_professional.py`
- `tests/test_json_exporter.py`
- `tests/test_override_workbench.py`
- `tests/test_ticker_dossier_contract_runtime.py`

Required cases:

- contract JSON round-trip
- builder validates the final payload against the shared Pydantic contract
- deterministic builder creates numeric ticker-level entries
- terminal value drivers are included as assumption entries while terminal outputs remain diagnostics
- naming conventions are enforced for assumption_name, stage, scope, and affected_forecast_lines
- static range flags out-of-range values
- flag levels follow deterministic semantics for none/watch/review_required/critical
- out-of-range values do not block valuation
- out-of-range or critical values downgrade `model_trust_state`
- model trust state rolls up assumption flags plus selected valuation diagnostics
- material diff logic ignores tiny changes
- material diff logic logs source/flag/approval changes
- materiality thresholds are centralized and covered by field-class tests
- audit rows store concise prior/new diffs rather than full entry snapshots
- PM approval is value-specific
- stale approval is surfaced after material value change
- valuation result includes `assumption_register_json`
- JSON export includes full `assumption_register`
- assumptions API payload includes register and audit rows
- assumptions API payload keeps override and assumption-register audit families separate
- override preview/apply paths can include valuation-impact metadata
- ticker dossier/export includes compact flagged summary

Focused verification command:

```powershell
python -m pytest tests/test_assumption_register.py tests/test_api_contracts.py tests/test_batch_runner_professional.py tests/test_json_exporter.py tests/test_override_workbench.py tests/test_ticker_dossier_contract_runtime.py -q
```

## V2 Backlog

- Connect `driver_assessments.py` and judgment-stage agents as advisory register inputs.
- Feed register flags back to advisory agents so they can retry or revise proposed assumptions.
- Add `source_quality_state` or equivalent source-confidence classification separate from numeric range checks.
- Add automatic sensitivity-driven valuation-impact scoring for flagged assumptions.
- Add raw/pre-clamp value diagnostics if review of clamped assumptions becomes important.
- Replace fixed bps thresholds with scale-aware and valuation-impact-aware materiality.
- Compute accepted ranges from company history, peer/industry context, and Damodaran data.
- Populate sector, industry, and global assumption policy entries.
- Add qualitative/enum/text assumptions only after numeric register behavior is stable.
- Add scenario assumption packs for bear/base/bull and context-aware scenario cases.
- Integrate Damodaran ERP, country-risk, synthetic-rating, and sector data into range/source policy.

## Assumptions

- Existing deterministic valuation should continue to run even with critical register flags.
- Existing `valuation_overrides.yaml` and override audit paths remain authoritative for official PM changes.
- V1 should avoid broad React redesign; show register data through existing valuation assumptions surfaces first.
- The initial implementation should not scrape Damodaran data or build the config editor.
