# Session State

**Updated:** 2026-07-11T19:51:32+02:00
**Agent:** Codex CLI
**Project:** C:/Projects/03-Finance/ai-fund

## Current Task
Plan the next accounting-evidence dispatch slice: deterministic focus subpackets with multi-finding responses, item-level repair, and ledger conflict handling.

## Recent Actions
- Ran the attended MSFT full-ticker workup on 2026-07-11 using `--use-codex --codex-model gpt-5.6-luna --codex-effort low`.
- Completed CIQ ingest, EDGAR evidence preparation, all six judgment profiles, queue review, analyst prep, and valuation exports with zero runtime errors.
- Documented the run as the first MVP weekly-loop review in `docs/reviews/weekly-loop/2026-07-11-MSFT-friction-draft.md`.
- Captured follow-up friction: item 123 stale preview guard and the opportunity to batch approved assumption applications.
- Diagnosed the accounting gap: the guided path bypasses existing `QoEAgent`/`AccountingRecastAgent` flows and sends generic business snippets instead of note-specific accounting packets.
- Created and registered `docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md` covering topic decomposition, typed accounting findings, semantic repair retries, and PM-safe queue translation.
- Implemented Tasks 1–3: typed accounting contracts, deterministic validation/repair seam, four topic-specific packet collectors, accounting handoff profiles, filing locator preservation, bridge/QoE facts, and retrieval coverage facts.
- Added offline packet-builder fixtures covering bridge provenance, QoE signals, selected sections, and `retrieval_unavailable` versus `searched_absent`.
- Ran a cache-only MSFT Task 3 smoke: four accounting packets built successfully (packet ids 184–187), with real source quality and deterministic bridge/QoE facts but only broad `notes_to_financials` section selection.
- Confirmed the current MSFT cached corpus exposes no extracted `note_leases`, `note_taxes`, `note_pension`, `note_segments`, or similar keys; cache-only retrieval also disables embeddings and falls back to the first broad-note chunks.
- Improved retrieval: bumped EDGAR parser to `sections_v5` and context query to `v5`, repaired split `FINANCI AL` headings, selected the latest body notes heading over the TOC span, extracted topic body headings, diversified focused-profile chunks by section, and filtered unrelated snippets from each accounting packet.
- Rebuilt and smoke-tested MSFT cache-only packets 196–199: QoE includes revenue/impairment/SBC/fair-value sections; bridge includes leases/fair-value sections; tax includes taxes/fair-value; segments includes revenue/fair-value. Remaining absent topics stay explicit.
- Explored the installed `edgartools` XBRL surface: `FinancialFact` retains accession, filing date, form, taxonomy, context ref, dimensions, statement metadata, and quality fields; `EntityFiling` exposes filing HTML/XBRL/footnotes, but the current fact model does not retain exact HTML DOM ids.
- Added XBRL Slice A plan notes to `docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md`.
- Added `src/stage_00_data/xbrl_evidence.py`, a pure provenance-preserving fact normalizer and live Company Facts adapter with explicit `ok`, `partial`, `no_facts`, `no_matching_facts`, and `error` statuses.
- Added `tests/test_xbrl_evidence.py` and documented the XBRL-facts/filing-narrative split in `docs/handbook/workflow-end-to-end.md`.
- Verified XBRL/accounting retrieval slice: `39 passed, 1 warning`; `compileall` and `git diff --check` passed. The warning remains the existing Windows `.pytest_cache` permission issue.
- Implemented XBRL Slice B: four topic-specific concept lists and an additive packet collector now persist normalized XBRL facts, original fact IDs, dimensions/period metadata, and SEC accession-index source refs.
- Added cache-only guardrails and exact local-concept filtering because `edgartools.by_concept()` is fuzzy by default; bounded retrieval now sorts by filing vintage/period before capping.
- Ran cache-only MSFT packet smoke: packet IDs 200–203, all four `cache_only_unavailable`, zero XBRL facts, no SEC client construction.
- Ran live MSFT four-profile packet smoke with SEC access: packet IDs 204–207, `xbrl_retrieval_status=ok`, fact counts 84/96/60/36 for QoE/bridge/taxes/segments; verified persisted round-trip counts match.
- Ran direct live adapter probe: `status=ok`, six facts for cash/operating lease concepts from recent 2026 filings; fuzzy related concepts were excluded.
- Final focused gate: `83 passed, 1 warning` in 2:13; compileall and `git diff --check` passed.
- Revised the active plan after PM feedback: the agent is not restricted to one finding. Added eight reasoning-level focus keys, a deterministic agent-context projection, 0..N finding envelopes with an engineering overflow guard, item-level repair that preserves valid siblings, and duplicate/conflict ledger handling.

## Next Steps
- Implementation is paused at the XBRL Slice B / focused-dispatch planning checkpoint; focus selector, multi-finding dispatch, item-level repair integration, exact Inline XBRL locators, and guided-run integration are not implemented yet.
- Next decision: confirm the plan's conservative accounting-treatment boundaries before implementation.
- Next implementation decision: build the focus selector and response envelope first, then test an MSFT multi-finding focus run before enabling guided dispatch.
- Existing later items remain: capture wall-clock timing, fix stale preview handling, and add approve-now/apply-at-end batching.
- Do not commit the working tree; preserve unrelated untracked artifacts.

## Known Issues
- The MVP run did not persist total wall-clock time, so the one-PM-hour requirement remains unmeasured.
- Item 123's approve+apply path failed on the preview-fingerprint guard; the operator skipped it after the error.
- Accounting evidence improvement still needs PM confirmation for treatment conventions and materiality semantics before proposal sizing/queue materiality is implemented.
- Remaining retrieval question: whether to add a conservative lexical fallback inside broad notes for topics without dedicated headings (pension, debt, contingencies, segments), or keep those as explicit missing evidence. No lexical fallback or agent dispatch has been implemented yet.
- XBRL facts are now persisted in the generic packet JSON columns without a SQLite migration; cache-only runs still lack a durable XBRL fact cache and therefore expose explicit unavailable status.
- Working tree remains `main...origin/main [ahead 3]` with unrelated untracked database/review artifacts; no cleanup or commit was performed.

## Notes
- Accounting-focused verification: `53 passed, 1 warning`; the warning is the existing Windows `.pytest_cache` permission issue.
- MSFT Task 3 smoke: four packets persisted successfully; no LLM, queue, or valuation mutation was run.
- Retrieval-hardening smoke: packets 196–199 persisted successfully; topic snippets were filtered per packet and no LLM, queue, or valuation mutation was run.
- MVP artifact JSON: `output/guided_workups/MSFT/MSFT-20260711T145754Z.json`.
- Active plan: `docs/plans/active/2026-07-11-accounting-evidence-packs-focused-repair.md`.
- No commits were created.
