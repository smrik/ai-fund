# Dashboard Override Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dashboard workbench that lets the PM compare default vs agent vs custom valuation inputs, preview valuation impact, apply selected values to `config/valuation_overrides.yaml`, and keep an append-only audit trail.

**Architecture:** Keep `config/valuation_overrides.yaml` as the active deterministic source of truth. Add a separate backend helper layer in `src/stage_04_pipeline/override_workbench.py` to resolve UI selections, run deterministic preview valuations, write active overrides, and append audit records into SQLite (`valuation_override_audit`). Wire the Streamlit dashboard onto those helpers rather than embedding business logic in `dashboard/app.py`.

**Tech Stack:** Python 3.13, Streamlit, YAML, JSONL audit logging, pytest.

---

### Task 1: Define workbench contract

**Files:**
- Create: `src/stage_04_pipeline/override_workbench.py`
- Test: `tests/test_override_workbench.py`

Define dataclasses and helpers for:
- available assumption rows
- current/default/agent/custom option resolution
- deterministic valuation preview
- apply-to-overrides with audit log append
- audit history loading

### Task 2: Lock behavior with tests

**Files:**
- Create: `tests/test_override_workbench.py`

Cover:
- selection resolution for `default`, `agent`, and `custom`
- preview result deltas vs current valuation
- applying selections writes/removes ticker overrides correctly
- audit event includes before/after valuation and source metadata

### Task 3: Implement backend workbench

**Files:**
- Create: `src/stage_04_pipeline/override_workbench.py`
- Modify: `src/stage_04_pipeline/recommendations.py` only if shared helpers are worth reusing

Keep compute deterministic by reusing:
- `build_valuation_inputs()`
- `run_probabilistic_valuation()`
- `load_recommendations()`
- `clear_valuation_overrides_cache()`

### Task 4: Wire Streamlit dashboard

**Files:**
- Modify: `dashboard/app.py`

Add a new `Assumption Lab` tab that shows:
- current effective values and lineage
- agent recommendations where available
- per-field mode: default / agent / custom
- preview button
- apply button
- audit history table

### Task 5: Verify and document handoff

**Files:**
- Modify: `.agent/session-state.md`

Run:
- targeted `pytest` for the new backend tests
- dashboard-adjacent tests already in repo if affected
- full `pytest tests/ -q`

Record final status and any remaining limitations.
