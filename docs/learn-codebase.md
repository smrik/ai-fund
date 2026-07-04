# Learn The Codebase

This guide is for a PM, operator, or beginner coder who wants to review Alpha Pod without having to understand every implementation detail on day one.

The goal is not to turn you into a full-time engineer. The goal is to help you read the repo confidently, know where important decisions live, and spot changes that could affect the investment workflow.

## What This Page Helps You Do

Use this page when you want to:

- understand what each folder is responsible for
- review a pull request without getting lost in syntax
- trace one ticker from raw data to valuation output
- know which files are safe to skim and which deserve careful review
- ask better questions when an agent or engineer changes the system

## The Most Important Mental Model

Alpha Pod has three layers:

| Layer | What it does | Beginner translation | What to watch for |
| --- | --- | --- | --- |
| Data layer | Pulls and caches raw market, filing, CIQ, and workbook data | “Get the ingredients.” | Is the source clear? Is stale or missing data flagged? |
| Computation layer | Runs deterministic screens, WACC, DCF, reverse DCF, and portfolio math | “Do the math the same way every time.” | No LLM calls. Assumptions must have source lineage and sanity bounds. |
| Judgment layer | Uses LLM agents for qualitative research and narrative synthesis | “Write analyst notes and context.” | Agents may explain; they must not silently change deterministic valuation math. |

If you remember only one rule, remember this: **LLMs can help with narrative and review, but they do not own the deterministic numbers.**

## A 30-Minute First Tour

Do this before trying to read individual functions.

### 1. Read the product rules first

Start with the product direction so you know what the code is trying to protect:

1. `docs/strategy/vision.md` — settled product decisions
2. `docs/design-docs/architecture-overview.md` — data/computation/judgment boundaries
3. `docs/handbook/workflow-end-to-end.md` — how a ticker moves through the system
4. `docs/handbook/engineering-deep-dive.md` — practical repo map

Do not try to memorize these. Read them once so file names and concepts feel familiar.

### 2. Open the repo tree at the top level

The top-level folders are the map:

| Path | Plain-English purpose | How closely to review |
| --- | --- | --- |
| `docs/` | The system manual and source of truth for product, architecture, workflow, and plans | High. If behavior changes, docs should change too. |
| `config/` | Committed settings, universe lists, and valuation overrides | High. Small config changes can meaningfully change outputs. |
| `src/stage_00_data/` | Data ingestion adapters | High when data freshness, CIQ, EDGAR, or market fields change. |
| `src/stage_01_screening/` | Universe filters | High when screening criteria or candidate counts change. |
| `src/stage_02_valuation/` | Deterministic valuation math | Very high. Treat changes here like model changes. |
| `src/stage_03_judgment/` | LLM research agents | Medium-high. Review outputs and guardrails, not just prompts. |
| `src/stage_04_pipeline/` | Orchestration that assembles workflows for the UI and reports | High. This is where pieces get wired together. |
| `api/` | FastAPI transport layer for the React app | Medium. It should mostly pass data through, not invent business logic. |
| `frontend/` | React UI | Medium. Important for operator workflow, but should not contain valuation logic. |
| `dashboard/` | Legacy Streamlit UI | Low unless bugfixing. This surface is frozen. |
| `db/` | SQLite schema and loaders | High when persistence or table contracts change. |
| `tests/` | Offline-first test suite | High. Tests explain expected behavior. |
| `scripts/` | Manual run, review, and validation helpers | Medium. Useful for reproducing workflows. |

### 3. Learn one path end-to-end

Pick one ticker and trace the production path conceptually:

```text
config/universe.csv
  -> src/stage_01_screening/stage1_filter.py
  -> ciq/ciq_refresh.py, when CIQ is refreshed
  -> data/alpha_pod.db
  -> src/stage_02_valuation/input_assembler.py
  -> src/stage_02_valuation/professional_dcf.py and wacc.py
  -> src/stage_02_valuation/batch_runner.py
  -> data/valuations/latest.csv and SQLite valuation tables
  -> api/ and frontend/ for review
```

You do not need to understand every line. Your first goal is to know **which file owns each step**.

## How To Read Code When You Are Not A Coder

Use this order. It is slower than jumping around, but much less confusing.

### Step 1: Read names before logic

Look at:

- file name
- function names
- class names
- comments and docstrings
- input and output field names

Ask: “What job does this file appear to own?”

If you cannot answer in one sentence, write that down as a review question.

### Step 2: Find the inputs and outputs

For any important function, look for:

- parameters in the function definition
- data loaded from CSV, SQLite, JSON, Excel, or APIs
- returned dictionaries or dataclasses
- files or tables written at the end

Beginner shortcut: search within the file for words like `return`, `write`, `insert`, `upsert`, `to_csv`, `read_csv`, `connect`, and `SELECT`.

### Step 3: Ignore syntax until you understand the pipeline

Most code blocks follow this shape:

```text
load inputs
clean or normalize them
apply rules
handle missing data
return or save output
```

When reviewing, summarize each block in plain English. If you cannot summarize a block, that is often more important than whether the code “looks right.”

### Step 4: Look for assumptions and fallbacks

In Alpha Pod, the dangerous bugs are often not crashes. They are silent fallbacks that produce plausible-looking numbers.

Search for:

- `default`
- `fallback`
- `None`
- `if not`
- `except`
- `source`
- `lineage`
- `quality`
- `missing`
- `bounded`

Questions to ask:

- If data is missing, does the output say so clearly?
- Is the fallback conservative?
- Is the source of each assumption preserved?
- Would the PM notice that the result is lower quality?

### Step 5: Read the tests as examples

Tests are often easier to read than production code because they show small stories:

```text
Given this input,
when this function runs,
we expect this output.
```

For a changed file, search `tests/` for the function or field name. If there is no test for an important behavior, ask why.

## The Review Checklist For Pull Requests

When an agent or engineer opens a PR, use this checklist.

### 1. Product fit

- Which Vision decision does this serve?
- Does it help the weekly loop run on real tickers?
- Does it keep the PM as the final investment decision-maker?
- Does it avoid adding features to the frozen Streamlit surface unless it is a bugfix?

### 2. Boundary safety

- Did `src/stage_00_data/` or `src/stage_02_valuation/` start calling an LLM? That should be a red flag.
- Did `frontend/` gain valuation logic? That should be a red flag.
- Did `api/` gain business logic instead of calling pipeline helpers? Usually a red flag.
- Are judgment-agent outputs clearly marked as context or pending PM review?

### 3. Finance semantics

Block and ask the PM if the PR changes:

- WACC methodology
- DCF formula or forecast period
- terminal growth rules
- accepted ranges or bounds
- screening thresholds
- quality score meaning
- valuation override semantics
- what a metric means

Do not let code review quietly settle finance meaning.

### 4. Data quality

- Are stale data, missing data, and defaulted assumptions visible?
- Are source fields or lineage fields updated with new outputs?
- Does the code distinguish “zero” from “unknown”? This matters a lot.
- Does a failed API or workbook read create a warning rather than fake confidence?

### 5. Tests and verification

- Are there tests for the changed behavior?
- Did the PR run the relevant backend tests?
- If the UI changed, are there screenshots or route-matrix review notes?
- If outputs changed, is there a before/after explanation?

## Red Flags To Notice Quickly

These are worth pausing on even if you cannot fully read the code:

- valuation math changes without docs or tests
- new LLM calls inside data or valuation modules
- broad `except` blocks that hide errors without flags
- new defaults without source-lineage fields
- changes to `config/valuation_overrides.yaml` without explanation
- frontend code calculating financial outputs instead of displaying API results
- API endpoints that duplicate logic already in `src/`
- tests deleted or weakened to make a change pass
- generated files or local caches committed unintentionally
- changes to CIQ or Excel paths that only work on one machine

## A Practical One-Hour Review Routine

Use this when you have a real PR to review.

### First 10 minutes: understand scope

Run or inspect:

```bash
git status --short
git diff --stat
git diff --name-only
```

Then group files by folder. Ask: “Is this a docs change, UI change, data change, valuation change, or orchestration change?”

### Next 20 minutes: inspect high-risk files first

Review in this order:

1. `src/stage_02_valuation/`
2. `src/stage_00_data/`
3. `db/`
4. `config/`
5. `src/stage_04_pipeline/`
6. `api/`
7. `frontend/`
8. `docs/`
9. `tests/`

For each file, write one sentence: “This change does X.” If you cannot, ask for a clearer PR explanation.

### Next 20 minutes: compare behavior to tests

Look for tests that match the changed files:

```bash
rg "function_or_field_name" tests
```

Then run the smallest relevant checks first. Examples:

```bash
python -m pytest tests/test_api_contracts.py -q
python -m pytest tests/test_analyst_prep_contracts.py -q
npm --prefix frontend test -- --run
```

The exact command depends on the change. You are checking whether the PR author verified the right risk area, not just whether “some tests passed.”

### Final 10 minutes: write review questions

Good beginner review questions are concrete:

- “What happens if CIQ is missing this field?”
- “Where does the UI show that this assumption defaulted?”
- “Which test proves this does not change deterministic valuation output?”
- “Is this finance meaning or engineering plumbing?”
- “Why does this belong in `api/` instead of `src/stage_04_pipeline/`?”
- “What should I manually inspect in the app?”

## How To Trace A Value From UI Back To Source

When a number looks surprising in the UI, trace it backward:

1. UI label in `frontend/`
2. API response field in `api/`
3. pipeline helper in `src/stage_04_pipeline/`
4. valuation or data function in `src/stage_02_valuation/` or `src/stage_00_data/`
5. SQLite table, CSV, cache, CIQ workbook, or external source
6. test that defines expected behavior

Do not stop at “the UI displayed it.” The useful question is: **where did the number first enter the system, and what assumptions transformed it?**

## Search Commands Worth Learning

You can review a lot of the repo with a few commands.

| Need | Command |
| --- | --- |
| Find a file by name | `rg --files -g "*batch_runner*"` |
| Find a function or field | `rg "source_lineage"` |
| See changed files | `git diff --name-only` |
| See a compact change summary | `git diff --stat` |
| See changes in one file | `git diff -- path/to/file.py` |
| Find tests mentioning a field | `rg "field_name" tests` |
| Show recent commits | `git log --oneline -10` |

Prefer `rg` over recursive `grep`; it is faster and respects ignore rules better.

## What To Manually Inspect After Changes

After implementation, do not rely only on test output. Manually inspect the thing the PM actually uses.

| Change type | Manual inspection |
| --- | --- |
| Valuation math | Compare one ticker before/after; inspect source lineage, default flags, WACC, DCF assumptions, and upside. |
| Screening | Check survivor count and examples of included/excluded tickers. |
| CIQ or workbook ingest | Verify ticker identity, period dates, units, missing fields, and archive output. |
| Agent output | Confirm evidence is cited, uncertainty is visible, and no agent output silently becomes deterministic truth. |
| API | Open the endpoint or test payload and confirm field names match UI expectations. |
| React UI | Run the route, inspect screenshots, and compare visible fields against the API payload. |
| Docs | Confirm links work and the page points to the canonical source instead of duplicating stale detail. |

## A Gentle Learning Path

If you want to build skill over time, follow this path:

1. **Week 1: Navigation** — learn folders, docs, and the end-to-end ticker path.
2. **Week 2: Tests** — read tests for one small feature and run targeted pytest commands.
3. **Week 3: Data lineage** — trace one output field from UI/API back to source.
4. **Week 4: Safe edits** — make a tiny docs or UI copy change and verify it.
5. **Week 5: Config awareness** — review a valuation override or config change with an engineer.
6. **Week 6: Model-risk review** — review a small deterministic valuation change with special attention to assumptions, bounds, and tests.

## Glossary For Non-Engineers

| Term | Meaning in this repo |
| --- | --- |
| API | The backend interface the React app calls. It should transport workflow data, not invent finance logic. |
| Cache | A saved copy of external data so the system does not refetch constantly. Cache freshness matters. |
| CLI | Command-line entry point, usually run with `python -m ...`. |
| Contract | The expected shape and meaning of inputs/outputs between modules. |
| Deterministic | Same inputs produce same outputs; no LLM judgment or randomness. |
| Fallback | A backup value used when preferred data is missing. Must be visible and conservative. |
| Fixture | Test data used to prove behavior without needing live external services. |
| Lineage | A record of where a value came from and why the system used it. |
| Orchestration | Code that wires multiple steps together into a workflow. |
| Schema | The structure of a database table or typed data object. |
| Smoke test | A quick test that proves the main path starts and returns something plausible. |

## When To Stop And Ask For Help

Stop and ask before approving if:

- the change affects finance semantics and the PM has not explicitly decided it
- a number changes and nobody can explain why
- missing data becomes less visible
- an LLM gets closer to deterministic math
- the UI looks correct but the API payload disagrees
- tests pass but the manual workflow feels wrong

A good review is not about pretending to understand every line. It is about protecting the workflow, asking clear questions, and making sure the system remains auditable.
