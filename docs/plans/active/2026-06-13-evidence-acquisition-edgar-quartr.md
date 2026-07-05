# Evidence Acquisition: EDGAR End-To-End And Quartr Transcripts

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> **For Codex:** Use `/goals` with the goal prompt below, then execute this file in order. TDD where practical, small changes, verify after each task.

| Field | Value |
| --- | --- |
| Status | Active |
| Milestone | M1 — Weekly Loop v1 (unblocks 4 of 6 agent profiles) |
| Vision decisions served | 12 (loop runs for real), 5 (event-driven runs need automated evidence), 9 (transcripts close a named evidence gap for `earnings_update`) |
| Created | 2026-06-13 |
| PM input pending | Whether a Quartr REST API key is available (`QUARTR_API_KEY`); Task 4 ships transport-pluggable either way |

**Goal:** Real filings and earnings transcripts flow into Evidence Packets so all six Agentic Handoff Profiles can produce anchored observations. Verified end state: a glass-box MSFT run where no profile blocks on `insufficient_real_evidence` for acquisition reasons.

**Context (verified 2026-06-12):** The EDGAR machinery exists (`edgar_client.py`, `filing_retrieval.py`, 1,700 lines) but nothing populates the cache as an operator step — `edgar_filing_cache.filing_count = 0`, so `earnings_update`, `company_analysis`, `industry_analysis`, and `risk_review` fail closed. There is no transcript source at all. Quartr connector prototype (2026-06-13, MSFT): transcripts are speaker-attributed paragraphs with `speakerName`, `speakerRole`, `startTime`/`endTime`, and per-paragraph deep-link URLs — a direct fit for Evidence Anchors and Text Evidence Snippets; each earnings event also carries the release, 10-Q, and slides.

**Architecture:** Acquisition is deterministic stage-00 work. LLM agents never fetch; they consume packets built from cached sources. Transcript ingestion is transport-pluggable: a normalized on-disk/DB contract that either the REST client (preferred, needs `QUARTR_API_KEY`) or a connector-assisted manual export can fill. Fail-closed stays: no real source, no observations.

## Implementation Status

| Task | Status | Evidence |
| --- | --- | --- |
| 1. EDGAR prefetch CLI | Completed 2026-06-13 | `scripts/manual/prefetch_filings.py --ticker MSFT` cached 12 filings; `--summary-only` confirmed 12 cache hits |
| 2. Section extraction on real filings | Completed 2026-06-13 | MSFT cached corpus now extracts 10-K business/risk/MD&A/financials/notes plus two 10-Q financials/notes/MD&A/risk sections; regression fixtures added under `tests/fixtures/filings/` |
| 3. Filing-backed profiles | Completed 2026-06-13 | MSFT glass-box run completed 6/6 profiles; generated JSON shows `source_quality=real` for all packets and filing-backed packets include source refs, facts, and snippets |
| 4. Quartr transcript contract and client | Completed 2026-07-05 | Transcript contract, `transcript_cache`, fail-closed Quartr client, manual importer, fixture, and focused tests added; `pytest tests/test_quartr_client.py tests/test_transcript_contract.py -q` passed |
| 5. Transcripts into `earnings_update` | Not started | Pending |
| 6. Docs and runbook integration | Not started | Pending |

Engineering notes from Tasks 1-3:

- EDGAR cache rows are now populated by an explicit operator command; acquisition remains in `src/stage_00_data/` and `scripts/manual/`.
- Section parser version moved to `v4` so prior partial parser output does not mask fixed real-filing extraction.
- Cache-only filing lookup now prefers the most recently fetched cached CIK before ordering filings by date; this prevents stale synthetic rows from outranking real rows.
- Filing-backed evidence packets emit deterministic filing coverage facts (`filing_source_count`, selected chunks, section counts), so `company_analysis`, `industry_analysis`, and `risk_review` can be real on filing evidence even when unrelated market/valuation cache rows are absent.
- `ALPHA_POD_EDGAR_CACHE_ONLY=1` disables embedding downloads and uses the existing section-priority fallback, avoiding long Hugging Face retry loops in offline/operator cache-only runs.

---

## `/goals` Prompt

```text
Implement docs/plans/active/2026-06-13-evidence-acquisition-edgar-quartr.md task-by-task.

Primary objective: populate real filing and transcript evidence so all agentic handoff profiles can run un-blocked, with provenance preserved.

Non-negotiables:
- Acquisition code lives in src/stage_00_data/ and scripts/; agents never fetch.
- Every snippet carries a source reference (accession number or Quartr event/document URL with paragraph deep link).
- Fail closed: missing source means blocked profile, never invented evidence.
- Network calls are never required by tests; fixtures mirror real payload shapes.
- Finance semantics questions (what counts as material, observation taxonomy changes) stop and ask the PM; engineering details are decided conservatively and logged.

Work task-by-task. After each task run the listed verification and report pass/fail with file references.
```

## Task 1: EDGAR Prefetch CLI

**Goal:** One operator command populates the filing cache for a ticker.

**Files:**
- Create: `scripts/manual/prefetch_filings.py`
- Test: `tests/test_prefetch_filings.py`

**Steps:**

1. CLI: `--ticker` (required), `--forms` (default `10-K 10-Q 8-K`), `--limit` per form (default 4), `--summary-only` to report cache state without fetching.
2. Reuse `edgar_client` fetch + cache paths; do not duplicate fetch logic. The script orchestrates and reports.
3. Output a compact table: form, accession, filing date, cached chars, cache hit/miss.
4. Exit 0 with ≥1 filing cached, 1 on total failure, with actionable messages (CIK not found, SEC rate limit, network down).
5. Tests monkeypatch the client functions; assert orchestration, cache-row writes, and summary output. No network in tests.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_prefetch_filings.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/prefetch_filings.py --ticker MSFT
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/prefetch_filings.py --ticker MSFT --summary-only
```

**Expected:** Live run caches MSFT 10-K/10-Q/8-K; summary shows non-zero counts.

**Commit:** `feat: add EDGAR prefetch CLI to populate filing cache`

## Task 2: Verify And Fix Section Extraction On Real Filings

**Goal:** `filing_retrieval` section extraction proven against the real cached filings, with regression fixtures.

**Files:**
- Modify: `src/stage_00_data/filing_retrieval.py` (only where real filings expose failures)
- Test: `tests/test_filing_section_extraction.py` (extend)
- Create: `tests/fixtures/filings/` (truncated real excerpts)

**Steps:**

1. With Task 1's cache, build filing context bundles for MSFT and two structurally different names (pick from `config/universe.csv`, e.g., one industrial, one healthcare).
2. Report per-filing section coverage (Item 1A, 7, 7A, notes presence) using the existing coverage payload helpers.
3. Fix extraction failures found — wrong boundaries, empty sections, heading-format misses. Conservative changes only; log each in the PR.
4. Freeze short real excerpts (a few KB each, headings + first paragraphs) as fixtures; assert section boundaries on them so future parser edits can't silently regress.
5. Do not chase fidelity beyond what profiles consume (this plan is end-to-end first; deep parse quality is a later pass).

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_filing_section_extraction.py -q
```

**Expected:** Coverage report committed in the PR description; fixtures lock current behavior.

**Commit:** `fix: harden filing section extraction against real filings with regression fixtures`

## Task 3: Unblock Filing-Backed Profiles

**Goal:** `company_analysis`, `industry_analysis`, `risk_review` complete with real anchored evidence.

**Files:**
- Modify: `src/stage_04_pipeline/evidence_packets.py` (collector gaps only)
- Test: `tests/test_evidence_packet_builders.py` (extend)

**Steps:**

1. Run the glass-box flow with the populated cache (drop nothing — keep `--edgar-cache-only` to prove cache sufficiency):
   `run_ticker_valuation_flow.py --ticker MSFT --agent-mode heuristic --isolated-db --market-cache-only --edgar-cache-only`
2. For each formerly blocked profile, confirm packets now carry facts + source refs from cached filings; fix collector gaps where the cache has data but the packet stays empty (verified 2026-06-12: `company_analysis` had 0 facts).
3. Fix the known export bug: packet `source_quality` serializes as `None` in the flow JSON while the DB knows the real value.
4. Extend builder tests: cache-backed packet has `source_quality=real` and ≥1 source reference; empty cache still blocks.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_evidence_packet_builders.py tests/test_agentic_handoff_profiles.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --agent-mode heuristic --isolated-db --market-cache-only --edgar-cache-only
```

**Expected:** Profile statuses show `company_analysis`, `industry_analysis`, `risk_review` no longer blocked; flow JSON shows real `source_quality`.

**Commit:** `feat: feed cached filings into filing-backed evidence profiles`

## Task 4: Quartr Transcript Contract And Client

**Goal:** A normalized transcript store the pipeline reads, fillable by REST (preferred) or connector-assisted export.

**Files:**
- Create: `src/contracts/transcript.py`
- Create: `src/stage_00_data/quartr_client.py`
- Create: `scripts/manual/import_transcript.py`
- Modify: `db/schema.py` (transcript cache table)
- Test: `tests/test_quartr_client.py`, `tests/test_transcript_contract.py`

**Steps:**

1. Contract (Pydantic): `TranscriptDocument` with ticker, source (`quartr`), event id/title/date, fiscal quarter/year, document id, document url, `transcript_source` (`indexed`/`live`), and `paragraphs[]` of {index, speaker_name, speaker_role, start_time, end_time, text, deep_link_url}. Mirrors the validated Quartr payload shape exactly.
2. DB table `transcript_cache`: ticker, event_date, fiscal_label, source, document_id, fetched_at, payload JSON; unique on (ticker, source, document_id).
3. `quartr_client.py`: `QUARTR_API_KEY` from env; `resolve_company(ticker)`, `list_recent_earnings_events(company_id, limit)`, `fetch_transcript(event)` → `TranscriptDocument`; persists to `transcript_cache`. Fail-closed without a key: clear error naming the env var, never a stub transcript. Engineering note: REST endpoint shapes must be confirmed against Quartr API docs when the key arrives — isolate all HTTP in one module so only it changes.
4. `import_transcript.py`: validates a JSON file against `TranscriptDocument` and upserts into `transcript_cache` — the connector-assisted fallback (a Claude session exports transcript JSON; the pipeline ingests it identically to REST output).
5. Tests: fixture JSON copied from the real MSFT Q3 FY26 payload shape; contract round-trip, importer upsert/idempotency, client behavior with key absent. No network.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_quartr_client.py tests/test_transcript_contract.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/import_transcript.py --file tests/fixtures/transcripts/msft_q3_fy26_sample.json
```

**Expected:** Tests pass; importer loads the fixture into `transcript_cache`.

**Commit:** `feat: add transcript contract, cache, Quartr client, and import fallback`

## Task 5: Wire Transcripts Into earnings_update Packets

**Goal:** The earnings profile consumes transcripts and produces anchored observations.

**Files:**
- Modify: `src/stage_04_pipeline/evidence_packets.py`
- Modify: `src/stage_04_pipeline/agentic_handoff_profiles.py` (earnings profile inputs)
- Test: `tests/test_evidence_packet_builders.py`, `tests/test_agentic_handoff_profiles.py`

**Steps:**

1. Earnings collector reads the latest `transcript_cache` row for the ticker: facts = event date, fiscal label, transcript source, speaker count; source reference = Quartr event/document URL.
2. Text Evidence Snippets carry paragraph text plus the paragraph `deep_link_url` so every qualitative observation anchors to the exact moment in the call.
3. Snippet selection for the packet is deterministic (e.g., prepared-remarks executive paragraphs + Q&A, bounded count) — **the selection rule is a finance-relevant choice: propose a default, flag it for PM review in the PR, do not bury it.**
4. Blocked behavior unchanged when neither transcript nor 8-K release evidence exists.
5. Heuristic-mode glass-box run on MSFT with the fixture transcript imported: `earnings_update` completes with ≥1 observation anchored to a transcript snippet.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_evidence_packet_builders.py tests/test_agentic_handoff_profiles.py tests/test_agentic_handoff_mvp_flow.py -q
C:\Users\patri\miniconda3\envs\ai-fund\python.exe scripts/manual/run_ticker_valuation_flow.py --ticker MSFT --agent-mode heuristic --isolated-db --market-cache-only --edgar-cache-only
```

**Expected:** 6/6 profiles non-blocked on MSFT with populated caches; earnings packet shows Quartr provenance.

**Commit:** `feat: wire quartr transcripts into earnings evidence packets`

## Task 6: Docs And Runbook Integration

**Files:**
- Modify: `docs/handbook/pipeline-glass-box.md` (gaps table: mark fixed items, add prefetch/import steps)
- Modify: `docs/handbook/workflow-end-to-end.md` (evidence acquisition step)
- Modify: `.env.example` (`QUARTR_API_KEY=`)

**Steps:** Update both handbook pages with the new acquisition steps and flag semantics; keep one canonical home per concept (glass-box owns inspection, workflow owns sequence). Strict docs build must pass.

**Verification:**

```powershell
C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m mkdocs build --strict
```

**Commit:** `docs: add evidence acquisition steps to operator workflow`

## Out Of Scope

- Deep parse-fidelity work (XBRL structured facts, table extraction) — separate later pass by PM decision
- Scheduled/event-driven acquisition — M3 owns triggers; this plan makes the manual step exist
- Live-LLM observation quality on transcript evidence — heuristic mode proves plumbing; LLM quality is reviewed in weekly sessions
- Any non-Quartr transcript provider
