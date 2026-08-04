# Codex CLI Judgment Backend Implementation Plan

> **For Codex:** Implement this plan task-by-task with TDD where practical. Do not commit changes in this work package.

**Goal:** Route Alpha Pod judgment agents through the local Codex CLI with subscription-backed defaults, OpenRouter free fallback, and truthful per-call provenance.

**Architecture:** `BaseAgent` keeps the current OpenAI-compatible client and artifact contract, but when `ALPHA_POD_AGENT_BACKEND=codex` it sends one constrained plain-text prompt to `codex exec` over stdin and reads the final answer from `--output-last-message`. Codex failures fall through to the existing client using the separately resolved fallback model; structured payload parsing remains deliberately skipped so the existing raw JSON formatting and corrective retry path handles Codex output.

**Tech Stack:** Python 3.13, `subprocess.run`, Codex CLI 0.144.1, pytest monkeypatch/MagicMock, argparse, environment-based routing.

## Vision Decisions Served

- Decision 1: agents remain analyst support; no Codex path can mutate deterministic model state.
- Decision 2: reliable unattended judgment-layer plumbing supports the daily PM review cadence.
- Decision 12: weekly-loop execution can use the PM’s existing Codex subscription without changing the PM Decision Queue boundary.

## Non-negotiables

- Do not touch `data/alpha_pod.db` or run live LLM calls in tests.
- Codex receives `-s read-only` plus a strict no-tools/no-files/no-commands preamble.
- Prompts go through stdin (`codex exec -`), never argv; final text is read from `-o/--output-last-message`.
- Codex defaults are `gpt-5.6-luna` and `low`; timeout is about 120 seconds.
- Any Codex nonzero exit, timeout, missing output, or empty output logs a warning and uses the existing OpenAI-compatible fallback; provenance includes `(fallback)`.

## Tasks

### Task 1: Codex backend in `BaseAgent`

**Files:**
- Modify: `src/stage_03_judgment/base_agent.py`
- Modify: `src/stage_04_pipeline/agent_cache.py`
- Test: `tests/test_base_agent.py`
- Test: `tests/test_agent_artifacts.py`

- Add env-driven Codex activation, model, effort, strict preamble, stdin/output-file subprocess invocation, and timeout handling.
- Preserve the existing run artifact fields and add a minimal Codex trace row with model provenance.
- Skip `run_structured_payload` under Codex.
- Reuse the existing OpenAI retry loop after Codex failure, with the configured fallback model and a `(fallback)` marker.
- Keep the requested model as cache identity while recording/restoring actual fallback provenance in run history and cache-hit artifacts.

### Task 2: Guided workup routing

**Files:**
- Modify: `scripts/manual/run_guided_ticker_workup.py`
- Test: `tests/test_guided_ticker_workup.py`

- Add `--use-codex`, `--codex-model`, and `--codex-effort`.
- Make Codex take precedence when both backend flags are passed, while configuring OpenRouter free as the fallback client.
- Render backend, model, effort, fallback, subscription cost, and source in the routing banner and persisted routing payload.

### Task 3: Verification and handoff

- Run the requested focused gate, then the full offline suite with `py -3.13 -m pytest ... -m "not live" -q`.
- Distinguish the known ACL-bricked `.tmp-tests`/`.codex-pytest-temp` environmental failures from regressions.
- Inspect the diff without staging or committing, and update `.agent/session-state.md` with exact tests and remaining blockers.

**Result:** Complete. The exact requested gate passed with `53 passed, 1 warning`. The final expanded focused set passed with `68 passed, 1 warning`. The final full offline suite reached `792 passed, 1 skipped, 2 deselected, 19 failed, 5 errors`; all 24 failures/errors are the known Windows ACL failures under `.tmp-tests` / `.codex-pytest-temp`, outside this work package.

## Verification commands

```powershell
py -3.13 -m pytest tests/test_base_agent.py tests/test_guided_ticker_workup.py tests/test_agentic_observations.py tests/test_api_contracts.py -m "not live" -q
py -3.13 -m pytest -m "not live" -q
```

## CLI invocation decision

The implementation will use:

```text
codex exec --ephemeral -s read-only -m <model> -c model_reasoning_effort=<effort> -o <temp-output-file> -
```

The prompt is passed as `subprocess.run(..., input=prompt, text=True)` so 10–30KB prompts avoid the Windows argv limit. `-o` provides only the final model message, avoiding banner, event, and token-usage scraping; `--ephemeral` avoids persistent Codex session state for each agent call.
