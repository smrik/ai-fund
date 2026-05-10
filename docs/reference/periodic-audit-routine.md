# Periodic Reliability Audit Routine

Run this checklist roughly once a month, or before any significant infrastructure change. It keeps CI check names, branch rules, docs navigation, and release metadata aligned as the repo grows.

Each section lists the exact command and what a passing result looks like.

---

## 1. CI Check Names vs Branch Ruleset

**Why:** If a job is renamed in `.github/workflows/ci.yml` but the GitHub branch ruleset isn't updated, the old required check name silently becomes unenforced.

**Command:**
```bash
cat .github/workflows/ci.yml | grep "^  [a-z]" | grep "name:"
```

**Expected output (current required checks):**
```
  pre-commit:
  frontend-build:
  frontend-tests:
  backend-api-tests:
  docs-build:
  release-readiness:
```

**Verify live:** Go to GitHub → Settings → Branches → `main` ruleset → Status checks. Confirm each name above appears as a required check. If any are missing or renamed, update the ruleset to match.

---

## 2. Docs Build (Strict)

**Why:** Catches broken links, missing nav entries, and pages referenced in `mkdocs.yml` that don't exist.

**Command:**
```bash
python -m mkdocs build --strict
```

**Pass:** Exits 0. Any `WARNING` about missing pages or broken references is a failure to fix.

---

## 3. Docs Navigation Drift

**Why:** New docs pages are sometimes added without updating `mkdocs.yml` nav or `docs/index.md`. Pages in the tree but not in nav are invisible to readers.

**Command:**
```bash
python -m mkdocs build --strict 2>&1 | grep "exist in the docs directory, but are not included"
```

**Pass:** No output (all pages are in nav). If pages appear, add them to `mkdocs.yml` or deliberately archive them.

**Also check:** `docs/plans/index.md` — verify active plans list matches files under `docs/plans/active/`.

---

## 4. Release Metadata

**Why:** `VERSION`, `CHANGELOG.md`, and `.github/release.yml` must remain parseable. The release-readiness CI job checks this, but running locally confirms the exact error.

**Command:**
```bash
python scripts/release/prepare_mock_release.py --check-only
```

**Pass:** Exits 0 with no errors printed.

---

## 5. Architecture Boundary Tests

**Why:** Enforces that LLM code never touches deterministic valuation, and that raw `sqlite3.connect` calls don't proliferate outside the DB layer.

**Command:**
```bash
python -m pytest tests/test_architecture_boundaries.py -q
```

**Pass:** All tests pass.

---

## 6. Backend Contract Tests

**Why:** Confirms the API contract tests, export service, and dossier runtime contracts are not silently broken.

**Command:**
```bash
python -m pytest tests/test_api_contracts.py tests/test_export_service.py tests/test_ticker_dossier_contract_runtime.py -q
```

**Pass:** All tests pass offline (no live market data, no LLM calls).

---

## 7. Frontend Build and Tests

**Why:** Confirms the React shell builds cleanly and route/export smoke tests pass.

**Commands:**
```bash
npm --prefix frontend run build
npm --prefix frontend run test -- appRoutes.test.tsx exportFlows.test.tsx
```

**Pass:** Build exits 0 with no errors. Test runner reports all tests passing.

---

## 8. Operator Diagnostics

**Why:** Confirms the local runtime is healthy — DB tables present, universe loaded, exports writable.

**Command (API must be running):**
```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

**Or offline:**
```bash
python -c "from src.stage_04_pipeline.diagnostics import run_diagnostics; import json; print(json.dumps(run_diagnostics().as_dict(), indent=2))"
```

**Pass:** `"overall": "ok"`. Any `"degraded"` or `"unavailable"` check needs investigation before the next run.

---

## 9. Open Epic and Issue Alignment

**Why:** Epics accumulate done work that hasn't been closed. Stale open issues mislead prioritization.

**Command:**
```bash
gh issue list --label "type:epic" && gh issue list --assignee "@me" --limit 20
```

**Pass:** Epics and issues accurately reflect remaining work. Close anything that's fully implemented.

---

## 10. Git Hygiene

**Why:** Merged branches and stale local branches accumulate noise.

**Commands:**
```bash
git branch --merged main | grep -v "^\* main"   # branches safe to delete locally
git fetch --prune                                # prune remote-tracking refs for deleted remotes
```

**Pass:** No unexpected merged branches. Remote pruned cleanly.

---

## Recording Audit Results

Don't create a doc for every audit. Record only surprises: things that were broken, new debt sites added, or allowlists updated. Add a one-liner to `CHANGELOG.md` under an `## Ops` section if something substantive was found and fixed.

The audit itself is the artifact — if everything passes, nothing needs to be written down.
