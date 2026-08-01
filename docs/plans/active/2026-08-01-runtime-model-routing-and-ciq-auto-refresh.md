# Runtime Model Routing And CIQ Auto-Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **Vision decisions served:** Decisions 13-14 and the Division Of Labor (judgment owns evidence-grounded forward-looking reasoning; valuation remains deterministic), with no finance-semantic changes.

**Goal:** Make role-based LLM configuration in `config/config.yaml` the shared runtime source for every judgment entry point, and let guided workups opt into the existing single-ticker CIQ Excel automation with explicit failure states.

**Architecture:** Add one provider/model/effort resolver with the exact CLI > environment > config > fallback precedence. Agent constructors select a role and delegate resolution to `BaseAgent`; manual runners resolve and log the same route before dispatch. Guided CIQ auto-refresh calls the existing `refresh_and_ingest_single_ticker` boundary and maps its result to explicit staged/ingested/failure reasons without duplicating Excel process control.

**Tech Stack:** Python 3, PyYAML, argparse, existing OpenAI/Codex adapters, pytest, mocked CIQ refresh boundary.

---

### Task 1: Establish the role-based runtime resolver

**Files:**
- Modify: `config/config.yaml`
- Modify: `config/__init__.py`
- Create: `config/llm_routing.py`
- Test: `tests/test_llm_routing.py`

Implement `judgment`, `valuation`, and `accounting` roles with seeded PM values, provider-aware hard-coded fallbacks, field-level source metadata, provider base URL resolution, and a stable route formatter. Keep legacy exported config aliases as compatibility views derived from the role block.

Test the full field-level precedence chain for both `judgment` and `accounting`, including provider and Codex effort, plus the seeded config values and dated model IDs.

### Task 2: Route all BaseAgent-backed judgment agents through roles

**Files:**
- Modify: `src/stage_03_judgment/base_agent.py`
- Modify: `src/stage_03_judgment/valuation_agent.py`
- Modify: `src/stage_03_judgment/comps_agent.py`
- Modify: `src/stage_03_judgment/accounting_recast_agent.py`
- Modify: `src/stage_03_judgment/grounded_observation_agent.py`
- Modify: remaining `src/stage_03_judgment/*_agent.py` constructors that still pass hard-coded model defaults
- Test: `tests/test_base_agent.py` and focused route tests

Make `BaseAgent` resolve provider/model/effort from the selected role, preserve legacy per-agent environment overrides as environment-layer inputs, configure Codex/OpenRouter behavior from the resolved provider, and record route/provider/source metadata in run artifacts and logs. Map valuation/comps profiles to `valuation`, accounting discovery/recast to `accounting`, and general judgment agents to `judgment`.

### Task 3: Migrate manual runner flags and logs

**Files:**
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Modify: `scripts/manual/run_accounting_discovery.py`
- Modify: `scripts/manual/run_analyst_prep_pack.py`
- Modify: `scripts/manual/run_ticker_valuation_flow.py`
- Modify: `src/stage_04_pipeline/valuation_provider_bindings.py`
- Modify: `src/stage_04_pipeline/valuation_workup_cli.py`
- Modify: `tests/test_guided_ticker_workup.py`
- Add/update: accounting and valuation runner routing tests

Remove environment-dependent argparse defaults, resolve explicit CLI selections without mutating their provenance, apply only the environment needed by the existing adapters, and log provider/model/effort plus field-level source layers in every runner artifact/banner. Preserve the existing Codex/OpenRouter flag conflict rule: explicit `--use-codex` wins over OpenRouter flags.

### Task 4: Add guided CIQ auto-refresh outcome handling

**Files:**
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Modify: `ciq/ciq_refresh.py` only to expose refresh status metadata while preserving the existing child-process timeout/kill path
- Test: `tests/test_guided_ticker_workup.py`
- Test: `tests/test_ciq_refresh.py`

Add `--auto-refresh-ciq`, defaulting off. With the flag, call the existing single-ticker refresh/ingest function after it stages the workbook; map results to `skipped-by-flag`, `refreshed-and-ingested`, `refresh-failed`, or `refresh-timed-out`. Catch refresh/ingest exceptions and return staged/not-ingested diagnostics instead of crashing the full workup. Mock only at the `refresh_and_ingest_single_ticker` boundary in tests.

### Task 5: Update operator reference and verify

**Files:**
- Modify: `docs/reference/config-reference.md`
- Modify: `.agent/session-state.md`

Document the role block, precedence, model provenance log, explicit CIQ flag, and Excel/add-in failure behavior. Run focused tests, the offline suite with the mandated interpreter and cache-provider workaround if needed, inspect the diff and restricted-file guard, and leave changes uncommitted.
