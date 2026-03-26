# Config Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate committed application and screening configuration into a single YAML file, keep `.env` for secrets and machine-local overrides, and document the configuration surface clearly enough for manual review and future wiki/docs growth.

**Architecture:** The new source of truth will be `config/config.yaml`. Python code will continue importing through the `config` package, but the package will become a loader/facade instead of a second configuration source. Compatibility exports will preserve current import sites while the actual values are read from YAML plus `.env` overrides where appropriate.

**Tech Stack:** Python 3.13, PyYAML, python-dotenv, pytest, pathlib.

---

### Task 1: Capture the desired config contract in tests

**Files:**
- Create: `tests/test_config_loader.py`
- Inspect: `config/__init__.py`
- Inspect: `config/settings.py`
- Inspect: `config/screening_rules.yaml`

**Step 1: Write the failing test**
- Assert the config package exposes current compatibility constants like `LLM_MODEL`, `DB_PATH`, `SCREENING_RULES_PATH`, and `CONVICTION_SIZING`.
- Assert screening rules load from a single YAML source.
- Assert `.env` values can override runtime settings such as `LLM_MODEL` and `PORTFOLIO_SIZE_USD`.

**Step 2: Run test to verify it fails**
- Run: `python -m pytest tests/test_config_loader.py -q`
- Expected: FAIL because no unified loader exists yet.

**Step 3: Write minimal implementation**
- Add the loader and compatibility exports only as needed to satisfy the tests.

**Step 4: Run test to verify it passes**
- Run: `python -m pytest tests/test_config_loader.py -q`
- Expected: PASS.

**Step 5: Commit**
- Stage only the config and test files for this task.

### Task 2: Replace the split config sources with one YAML-backed loader

**Files:**
- Create: `config/config.yaml`
- Modify: `config/__init__.py`
- Modify: `config/settings.py`
- Possibly modify: `.env.example`

**Step 1: Write the failing test**
- Extend tests to validate path resolution, screening rules lookup, and derived values like `CONVICTION_SIZING`.

**Step 2: Run test to verify it fails**
- Run only the new test case(s).

**Step 3: Write minimal implementation**
- Build a loader that reads YAML once.
- Resolve project-relative paths from the repo root.
- Keep `config.settings` as a compatibility shim backed by the loader instead of a second settings source.
- Keep `.env` limited to secrets and explicit runtime overrides.

**Step 4: Run test to verify it passes**
- Re-run `python -m pytest tests/test_config_loader.py -q`.

**Step 5: Commit**
- Stage only files changed in this task.

### Task 3: Move screening configuration into the unified YAML structure

**Files:**
- Modify: `config/config.yaml`
- Modify: `config/__init__.py`
- Modify: `config/settings.py`

**Step 1: Write the failing test**
- Assert `SCREENING_RULES_PATH` points to the unified YAML file and the screening rules remain accessible under expected keys.

**Step 2: Run test to verify it fails**
- Run the targeted test.

**Step 3: Write minimal implementation**
- Merge the old `screening_rules.yaml` content into a dedicated `screening` section inside `config/config.yaml`.
- Expose a `SCREENING_RULES` object and compatibility path/value exports for downstream callers.

**Step 4: Run test to verify it passes**
- Re-run the targeted config tests.

**Step 5: Commit**
- Stage only files changed in this task.

### Task 4: Add operator-facing documentation and a docs/wiki entrypoint

**Files:**
- Create: `docs/reference/config-reference.md`
- Create: `docs/index.md`
- Modify: `docs/design-docs/index.md`
- Possibly modify: `README.md`

**Step 1: Write the failing test**
- No automated test required for docs-only work.

**Step 2: Write the documentation**
- Document every YAML section, each supported option, which values belong in `.env`, and examples of safe edits.
- Add Mermaid diagrams showing config flow: YAML -> loader -> consumers, and `.env` -> runtime overrides.
- Create a docs index that can act as the starting point for a wiki.

**Step 3: Verify manually**
- Open the files and check links/paths.

**Step 4: Commit**
- Stage only docs files.

### Task 5: Verify the refactor end-to-end

**Files:**
- No new files required.

**Step 1: Run targeted config tests**
- Run: `python -m pytest tests/test_config_loader.py -q`

**Step 2: Run the full test suite**
- Run: `python -m pytest -q`

**Step 3: Spot-check runtime imports**
- Run a short Python command to print key config values from `config` and `config.settings`.

**Step 4: Update handoff state**
- Update `.agent/session-state.md` with completed work, open risks, and next steps.

**Step 5: Commit**
- Make a final commit summarizing the config consolidation and docs additions.

