# Business Context Evidence Packet Split Implementation Plan

> When execution is requested in a separate session, use the `executing-plans` skill to implement
> this plan task-by-task.

**Vision decisions served:** Decision 12 (learn through the real MSFT weekly loop), Decision 13
(judgment authors forward assumptions from evidence), and Decision 14 (business analysis precedes
industry analysis and driver decisions).

**Goal:** Replace the 2,765-line `evidence_packets.py` god module with a small compatibility facade
over cohesive packet modules, and produce a DB-backed Business Context packet that is literal,
inspectable, provider-free, and free of forecast targets.

**Architecture:** Introduce `src/stage_04_pipeline/evidence/` as the implementation package.
`assembly.py` owns generic packet construction, `context.py` owns the frozen context snapshot and
business/industry projections, `accounting.py` owns the four accounting profiles, and `reviews.py`
owns earnings/comps/valuation/risk/analyst-prep profiles. The existing `evidence_packets.py` remains
as a compatibility facade and persistence router; callers keep their current imports while the
implementation moves behind smaller interfaces.

**Tech Stack:** Python 3.11, Pydantic packet contracts, SQLite, pytest, Ruff, pre-commit, MkDocs.

---

## Starting State

- Work on branch `codex/handoff-msft-step3` from commit `58e5804` or later.
- `58e5804` already enforces that a DB-backed Business Context packet contains reported revenue and
  EBIT history but no `model_assumption_*` forecast targets.
- `src/stage_04_pipeline/evidence_packets.py` is 2,765 lines, with 41 top-level functions and 21
  imports spanning data acquisition, valuation, judgment, packet construction, and persistence.
- The current MSFT packet uses a generic filing profile and selected stale 2022-2023 debt, tax, and
  derivatives excerpts. Its sufficiency check can label that packet `sufficient` merely because
  some snippets and a current revenue series exist.
- The raw ride-along DB lacks `canonical_valuation_facts`. Use the deterministic Step 1 output:
  `output/ridealong_msft_20260804/_isolated_db/MSFT-20260804T173819Z-canonical.db`.
- Do not invoke an LLM during this plan. The deliverable is the exact frozen input packet only.

## Non-Negotiables

1. The external run contract is only `db_path + ticker`.
2. A DB-backed packet build performs no network/provider retrieval.
3. Business Context receives reported evidence and history, never current forecast targets.
4. No issuer-specific terms such as `software`, `consulting`, or `infrastructure` may determine
   generic company evidence eligibility.
5. The PM Decision Queue remains the only future model-mutation bridge.
6. Keep the existing import surface working while implementation moves.
7. Move behavior; do not duplicate it behind a second permanent router.
8. Commit after every green vertical slice. Do not use bulk regex edits.

## Target Module Interfaces

```python
# src/stage_04_pipeline/evidence/assembly.py
@dataclass(frozen=True)
class PacketMaterial:
    source_refs: tuple[dict[str, Any], ...]
    facts: tuple[dict[str, Any], ...]
    snippets: tuple[dict[str, Any], ...]
    run_metadata: Mapping[str, Any]


def assemble_packet(
    *,
    ticker: str,
    profile_name: str,
    material: PacketMaterial,
) -> EvidencePacket:
    """Validate and serialize already-selected evidence; perform no acquisition."""
```

```python
# src/stage_04_pipeline/evidence/context.py
@dataclass(frozen=True)
class ContextEvidenceSnapshot:
    ticker: str
    db_path: str
    financial_as_of_date: str
    ciq_run_id: int
    source_refs: tuple[dict[str, Any], ...]
    reported_facts: tuple[dict[str, Any], ...]
    filing_sections: tuple[FilingEvidenceSection, ...]


def load_context_snapshot(db_path: str, ticker: str) -> ContextEvidenceSnapshot:
    """Read one frozen, cache-only evidence snapshot from the supplied SQLite DB."""


def project_business_context(snapshot: ContextEvidenceSnapshot) -> PacketMaterial:
    """Select business evidence without forecast targets or issuer-specific keywords."""


def build_business_context_packet(db_path: str, ticker: str) -> EvidencePacket:
    """Public DB-backed Business Context interface used by the MSFT ride-along."""
```

```python
# src/stage_04_pipeline/evidence/accounting.py
def build_accounting_packet(ticker: str, profile_name: str) -> EvidencePacket:
    """Build one of the four legacy accounting profile packets."""
```

```python
# src/stage_04_pipeline/evidence/reviews.py
def build_review_packet(ticker: str, profile_name: str) -> EvidencePacket:
    """Build earnings, comps, valuation, risk, or analyst-prep packets."""
```

The production `build_business_context_packet()` interface stays small. Snapshot loading and
projection are separate internal seams so deterministic I/O and pure evidence selection can be
tested independently.

## Business Context Projection Policy

The policy may hardcode document semantics, not ticker vocabulary.

Required coverage:

- latest available 10-K business description;
- latest available 10-K MD&A;
- reported annual revenue and EBIT series through the resolved financial period;
- exact source references, filing dates, CIQ run, and financial as-of date.

Optional bounded coverage when present:

- latest 10-Q MD&A;
- operating-segment disclosure;
- material risk-factor changes;
- management commentary from already-persisted sources.

Selection rules:

- select by form, canonical section key, filing date, and source identity;
- prefer the latest filing for each required category;
- preserve whole sentences and never begin or end mid-word;
- retain source anchors on every fact and excerpt;
- use named packet budgets in one policy object, not scattered integer literals;
- if a required category is absent, record an evidence gap instead of filling it with a loosely
  keyword-matched passage.

`evidence_sufficiency` is `sufficient` only when all required coverage exists. `source_quality`
continues to describe authenticity and must not substitute for sufficiency.

---

### Task 1: Record The Baseline And Add The Package Skeleton

**Files:**

- Create: `src/stage_04_pipeline/evidence/__init__.py`
- Modify: `docs/plans/active/2026-08-05-business-context-evidence-packet-split.md`

**Step 1: Confirm the clean checkpoint**

Run:

```powershell
git status --short --branch
git log -4 --oneline
```

Expected: clean worktree; `58e5804` is present.

**Step 2: Run the focused baseline**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_evidence_packet_builders.py `
  tests/test_db_only_valuation_inputs.py `
  tests/test_context_evidence_sufficiency.py `
  tests/test_filing_retrieval.py `
  -q -p no:cacheprovider
```

Expected: PASS (47 passed). Record the exact count in this plan before moving code.

**Step 3: Create only the package marker**

```python
"""Cohesive evidence-packet implementations behind the legacy facade."""
```

**Step 4: Commit**

```powershell
git add src/stage_04_pipeline/evidence/__init__.py `
  docs/plans/active/2026-08-05-business-context-evidence-packet-split.md
git commit -m "chore: start evidence packet module split" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 2: Extract Generic Packet Assembly

**Files:**

- Create: `src/stage_04_pipeline/evidence/assembly.py`
- Create: `tests/test_evidence_packet_assembly.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`

**Step 1: Write the failing public-interface test**

```python
def test_assemble_packet_validates_material_without_acquiring_sources() -> None:
    material = PacketMaterial(
        source_refs=(SOURCE_REF,),
        facts=(REVENUE_FACT,),
        snippets=(BUSINESS_SNIPPET,),
        run_metadata={"source_quality": "real", "evidence_sufficiency": "sufficient"},
    )

    packet = assemble_packet(
        ticker="msft",
        profile_name="company_analysis",
        material=material,
    )

    assert packet.ticker == "MSFT"
    assert packet.facts[0].fact_name == "revenue_series_annual"
    assert packet.run_metadata["evidence_sufficiency"] == "sufficient"
```

**Step 2: Verify red**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_evidence_packet_assembly.py -q -p no:cacheprovider
```

Expected: FAIL because `PacketMaterial`/`assemble_packet` do not exist.

**Step 3: Implement the exact interface above**

Move only generic serialization behavior from `_build_profile_packet`. Do not import EDGAR,
valuation, market data, or persistence into `assembly.py`.

**Step 4: Route the legacy helper through `assemble_packet`**

Keep `_build_profile_packet` temporarily, but make its final construction call the new module.

**Step 5: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_evidence_packet_assembly.py tests/test_evidence_packet_builders.py `
  -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence/assembly.py `
  src/stage_04_pipeline/evidence_packets.py tests/test_evidence_packet_assembly.py
git commit -m "refactor: extract evidence packet assembly" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 3: Extract The Context Packet Deep Module

**Files:**

- Create: `src/stage_04_pipeline/evidence/context.py`
- Create: `tests/test_business_context_packet.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `tests/test_db_only_valuation_inputs.py`
- Modify: `tests/test_context_evidence_sufficiency.py`

**Step 1: Write the failing DB-backed contract test**

Build a temporary SQLite fixture containing run `20`, canonical valuation facts, five annual
revenue/EBIT rows, and persisted filing sections. Exercise only:

```python
packet = build_business_context_packet(str(db_path), "MSFT")
```

Assert:

```python
fact_names = {fact.fact_name for fact in packet.facts}
assert "revenue_series_annual" in fact_names
assert "ebit_series_annual" in fact_names
assert not any(name.startswith("model_assumption_") for name in fact_names)
assert not any(ref.source_kind == "valuation_inputs" for ref in packet.source_refs)
assert packet.run_metadata["ciq_run_id"] == 20
assert packet.run_metadata["financial_as_of_date"] == "2026-06-30"
assert packet.run_metadata["retrieval_mode"] == "db_only"
```

**Step 2: Verify red**

Expected: FAIL because `build_business_context_packet` does not exist.

**Step 3: Implement `ContextEvidenceSnapshot` and `load_context_snapshot`**

- Open the supplied DB explicitly; never resolve the process-global DB.
- Read filing/section cache rows from that DB only.
- Reuse `build_valuation_inputs_from_db` only for resolved lineage; do not copy its forecast values
  into the snapshot.
- Read reported annual series from the canonical statement ledger for the resolved CIQ run.
- Return a frozen dataclass. Perform no ranking or packet serialization here.

**Step 4: Move current company/industry code behind the new module**

First preserve current observable behavior. Keep compatibility wrappers:

```python
def build_company_analysis_packet(ticker: str, *, db_path: str | None = None) -> EvidencePacket:
    if db_path is not None:
        return build_business_context_packet(db_path, ticker)
    return build_legacy_company_analysis_packet(ticker)
```

**Step 5: Replace private-helper tests**

Move sufficiency assertions to `project_business_context(snapshot)` or
`build_business_context_packet()`. Delete tests that import
`_context_evidence_sufficiency` from the legacy facade once equivalent public behavior is covered.

**Step 6: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_business_context_packet.py `
  tests/test_db_only_valuation_inputs.py `
  tests/test_context_evidence_sufficiency.py `
  tests/test_evidence_packet_builders.py `
  -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence/context.py `
  src/stage_04_pipeline/evidence_packets.py `
  tests/test_business_context_packet.py `
  tests/test_db_only_valuation_inputs.py `
  tests/test_context_evidence_sufficiency.py
git commit -m "refactor: extract context evidence packets" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 4: Repair Business Context Selection And Sufficiency

**Files:**

- Modify: `src/stage_04_pipeline/evidence/context.py`
- Modify: `tests/test_business_context_packet.py`

**Step 1: Write one failing projection test**

Create an in-memory `ContextEvidenceSnapshot` containing:

- current 2026 business and MD&A sections;
- stale 2022 debt/tax passages with higher legacy scores;
- FY2022-FY2026 revenue and EBIT;
- no forecast assumptions.

Expected observable result:

```python
packet = assemble_packet(
    ticker="MSFT",
    profile_name="company_analysis",
    material=project_business_context(snapshot),
)
texts = [snippet.text for snippet in packet.snippets]
assert any("three operating segments" in text for text in texts)
assert any("AI infrastructure investment" in text for text in texts)
assert not any("credit default swap" in text for text in texts)
assert packet.run_metadata["evidence_sufficiency"] == "sufficient"
```

**Step 2: Verify red**

Expected: FAIL because the current generic keyword selection prefers stale passages.

**Step 3: Implement the Business Context policy**

- Select by canonical section category and latest filing date.
- Remove issuer-specific keyword eligibility.
- Preserve sentence boundaries.
- Put all size limits in one `BUSINESS_CONTEXT_POLICY` value.
- Report missing required categories as stable gap codes:
  `missing_latest_business_section`, `missing_latest_mda`,
  `missing_reported_revenue_history`, or `history_behind_resolved_period`.
- Do not silently substitute notes/debt/tax passages for missing business or MD&A.

**Step 4: Add the insufficient-evidence case**

Use a snapshot with authentic but stale/irrelevant filing text. Assert:

```python
assert material.run_metadata["source_quality"] == "real"
assert material.run_metadata["evidence_sufficiency"] == "insufficient_evidence"
assert "missing_latest_business_section" in material.run_metadata["evidence_gaps"]
```

**Step 5: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_business_context_packet.py -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence/context.py tests/test_business_context_packet.py
git commit -m "fix: select current business context evidence" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 5: Extract Accounting Packet Behavior

**Files:**

- Create: `src/stage_04_pipeline/evidence/accounting.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `tests/test_evidence_packet_builders.py`

**Step 1: Characterize the public family interface**

Parameterize the four accounting profile names and assert each returns the same packet kind,
source/fact/snippet identities, and metadata before and after extraction.

**Step 2: Move one profile at a time**

Move configuration and helpers used only by accounting packets. After each profile move, run its
existing focused test before moving the next profile.

**Step 3: Expose one family interface**

```python
def build_accounting_packet(ticker: str, profile_name: str) -> EvidencePacket:
    if profile_name not in ACCOUNTING_PROFILE_NAMES:
        raise KeyError(f"unsupported accounting evidence profile: {profile_name}")
    ...
```

**Step 4: Remove moved definitions from the legacy file**

Do not leave duplicate configs or helper implementations.

**Step 5: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_evidence_packet_builders.py -k accounting -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence/accounting.py `
  src/stage_04_pipeline/evidence_packets.py tests/test_evidence_packet_builders.py
git commit -m "refactor: extract accounting evidence packets" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 6: Extract Review Packet Behavior

**Files:**

- Create: `src/stage_04_pipeline/evidence/reviews.py`
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `tests/test_evidence_packet_builders.py`

**Step 1: Parameterize the review family**

Cover `earnings_update`, `comps_analysis`, `valuation_review`, `risk_review`, and
`analyst_prep_synthesis` through `build_review_packet`.

**Step 2: Move behavior in vertical slices**

Move one complete collector/builder/test group at a time. Do not create a generic dependency bag or
one callback parameter per imported function.

**Step 3: Move private valuation helpers with their only caller**

For example, `_terminal_reinvestment_facts` belongs with valuation review. Replace direct private
imports in tests with assertions through the public valuation packet interface.

**Step 4: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_evidence_packet_builders.py -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence/reviews.py `
  src/stage_04_pipeline/evidence_packets.py tests/test_evidence_packet_builders.py
git commit -m "refactor: extract review evidence packets" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 7: Reduce `evidence_packets.py` To A Compatibility Facade

**Files:**

- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `tests/test_agentic_handoff_mvp_flow.py`
- Modify: `tests/test_api_contracts.py`
- Modify: `tests/test_evidence_packet_builders.py`

**Step 1: Keep only the stable public surface**

The facade should contain:

- compatibility builder names;
- the profile-to-family router;
- persistence through `build_evidence_packet`;
- no acquisition, ranking, finance math, or excerpt logic.

Target: fewer than 250 lines and fewer than 10 imports.

**Step 2: Replace facade-internal monkeypatching**

Tests must stop patching `_collect_profile_inputs` and dozens of imported provider functions on the
facade. Test family modules through their interfaces; keep API tests at the HTTP/public builder
seam.

**Step 3: Prove caller compatibility**

Run the API, batch runner, manual scripts, and handoff tests that import the legacy module.

**Step 4: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_agentic_handoff_mvp_flow.py `
  tests/test_api_contracts.py `
  tests/test_evidence_packet_builders.py `
  -q -p no:cacheprovider
git add src/stage_04_pipeline/evidence_packets.py `
  tests/test_agentic_handoff_mvp_flow.py `
  tests/test_api_contracts.py tests/test_evidence_packet_builders.py
git commit -m "refactor: make evidence packets a compatibility facade" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 8: Add The Literal Packet Inspector

**Files:**

- Create: `scripts/manual/inspect_business_context_packet.py`
- Create: `tests/test_inspect_business_context_packet.py`
- Modify: `docs/handbook/workflow-end-to-end.md`

**Step 1: Write the failing CLI test**

Call `main(["--db-path", ..., "--ticker", "MSFT"])` against the temporary fixture. Parse stdout as
JSON and assert that it equals `build_business_context_packet(...).model_dump(mode="json")`.

**Step 2: Implement the CLI**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the exact frozen Business Context packet; makes no LLM call."
    )
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args(argv)
    packet = build_business_context_packet(args.db_path, args.ticker)
    print(packet.model_dump_json(indent=2))
    return 0
```

No output file option is needed in this tranche; stdout is the literal packet.

**Step 3: Document the exact MSFT command**

```powershell
$env:ALPHA_POD_EDGAR_CACHE_ONLY = '1'
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' `
  scripts\manual\inspect_business_context_packet.py `
  --db-path output\ridealong_msft_20260804\_isolated_db\MSFT-20260804T173819Z-canonical.db `
  --ticker MSFT
```

The environment variable is defensive only. The DB-backed builder itself must already prohibit
provider retrieval.

**Step 4: Verify and commit**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest `
  tests/test_inspect_business_context_packet.py -q -p no:cacheprovider
git add scripts/manual/inspect_business_context_packet.py `
  tests/test_inspect_business_context_packet.py docs/handbook/workflow-end-to-end.md
git commit -m "feat: print literal business context packets" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

---

### Task 9: Run The MSFT Acceptance Gate

**Files:**

- Modify: `docs/plans/active/2026-08-05-business-context-evidence-packet-split.md`
- Modify: `.agent/session-state.md`

**Step 1: Print the real packet without invoking an LLM**

Run the documented command and inspect the entire JSON.

**Step 2: Check the literal acceptance conditions**

- `ticker == "MSFT"`;
- CIQ run is `20` and financial as-of date is `2026-06-30`;
- revenue and EBIT series end at FY2026 and use absolute USD;
- no fact name starts with `model_assumption_`;
- no source ref has `source_kind == "valuation_inputs"`;
- every snippet points to a listed source ref;
- latest business and MD&A evidence are present;
- no 2022/2023 debt, tax, or derivative passage substitutes for missing company context;
- `source_quality` and `evidence_sufficiency` are independently justified;
- packet creation produces no network/provider call and no LLM call.

**Step 3: Run the full verification gate**

```powershell
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests -q -p no:cacheprovider
$env:PRE_COMMIT_HOME = "$PWD\.pre-commit-cache-run-codex"
pre-commit run --all-files
mkdocs build --strict
```

Expected: all commands exit `0`.

**Step 4: Record evidence and commit**

Write exact test counts, packet fact/snippet counts, evidence gaps, and any remaining compatibility
debt into this plan and `.agent/session-state.md`.

```powershell
git add docs/plans/active/2026-08-05-business-context-evidence-packet-split.md `
  .agent/session-state.md
git commit -m "docs: record business context packet split" `
  -m "Co-Authored-By: Luna <noreply@openai.com>"
```

Do not push or merge without PM confirmation.

## Stop Conditions For Luna

Stop and report instead of guessing when:

- the supplied canonical DB does not contain the filing text/section cache needed for DB-only
  context;
- a proposed selection rule requires PM judgment about finance meaning rather than engineering
  mechanics;
- preserving a legacy test would require duplicating provider logic or exposing a large dependency
  interface;
- any packet starts containing forecast targets again;
- a mechanical move changes a packet's observable JSON before the intended repair task;
- an unrelated dirty-worktree change overlaps a file in this plan.

## Definition Of Done

- `evidence_packets.py` is a facade under 250 lines with fewer than 10 imports.
- Context, accounting, and review behavior live in cohesive modules with small interfaces.
- The DB-backed Business Context packet is built from the supplied database only.
- The packet contains current reported history and relevant business evidence, but no forecast
  targets.
- The literal inspector command prints exactly what a future LLM would receive.
- Existing callers keep working.
- Focused tests, full tests, pre-commit, and strict docs build pass.
- No LLM call or model mutation occurred during the refactor.
