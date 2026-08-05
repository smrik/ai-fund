# Repository Navigation Cleanup Implementation Plan

> Use the `executing-plans` skill if a separate session does this work.

**Vision decisions served:** Decision 10 (interview-first design), Decision 11 (safe engineering choices), Decision 12 (real weekly use), Decision 13 (LLM agents propose assumptions), and Decision 14 (analysis order).

**Goal:** Make the repository easy to follow in analyst-workflow order without changing system behavior.

**Architecture:** Keep all working file paths. Improve the documents that help users find code, inputs, templates, saved data, and outputs. Add short README files to the four folders that cause the most confusion.

**Tech stack:** Markdown, MkDocs, Git, pre-commit, and pytest architecture tests.

**Design source:** `docs/design-docs/repository-navigation-cleanup-spec.md`

---

## Work Rules

- Do not move or delete a working file.
- Do not change Python, TypeScript, YAML, JSON, or workbook behavior.
- Use simple English.
- Keep each README short.
- Link to the main document instead of copying it.
- Commit each completed task.

### Task 1: Put The Six Steps In The Main Guide

**Files:**

- Modify: `docs/learn-codebase.md`

**Step 1: Correct the three-layer description**

Replace the old judgment-layer description. State that LLM agents study evidence and propose future assumptions.

State that the PM must approve each proposal. State that deterministic code runs the approved assumptions.

**Step 2: Add the six-step workflow table**

Put this order near the start of the guide:

1. Get data.
2. Build reported history and the current-state model.
3. Analyze the business and industry.
4. Propose changes to forecast inputs.
5. Run DCF and comparable-company valuation.
6. Review decisions and outputs as PM.

For each step, give the owner, main paths, input, output, and next step.

**Step 3: Keep the detailed folder guide**

Keep the current folder table after the workflow map. Correct terms that conflict with Vision Decision 13.

**Step 4: Check the change**

Run:

```powershell
git diff --check -- docs/learn-codebase.md
rg -n "only.*narrative|do not own|six-step|Get data" docs/learn-codebase.md
```

Expected result: no diff errors. The new workflow is present. Old judgment wording is absent.

**Step 5: Commit**

```powershell
git add docs/learn-codebase.md
git commit -m "docs: put analyst workflow first"
```

### Task 2: Add Short Folder Guides

**Files:**

- Create: `src/README.md`
- Create: `data/README.md`
- Create: `ciq/README.md`
- Create: `templates/README.md`

**Step 1: Add `src/README.md`**

Explain the five code stages. Show which stage is deterministic and which stage uses LLM agents.

Link to `docs/design-docs/architecture-overview.md` and `docs/learn-codebase.md`.

**Step 2: Add `data/README.md`**

Explain saved data, generated files, and the SQLite database. Separate files that users must keep from files they can rebuild.

Link to `docs/reference/storage-runtime-map.md`.

**Step 3: Add `ciq/README.md`**

Show the CIQ loading chain. Mark `ciq/templates/ciq_cleandata.xlsx` as the main CIQ Standard source template.

State that Power Query reads `ciq/templates/financials_input.json` from a fixed local path.

**Step 4: Add `templates/README.md`**

Explain that this folder contains PM review templates. Explain that it does not contain the CIQ source template.

Mark `templates/ticker_review.xlsx` as the main PM review template.

**Step 5: Check the new files**

Run:

```powershell
git diff --check -- src/README.md data/README.md ciq/README.md templates/README.md
rg -n "ciq_cleandata|financials_input|ticker_review|alpha_pod.db" src/README.md data/README.md ciq/README.md templates/README.md
```

Expected result: no diff errors. Each important file appears in the correct folder guide.

**Step 6: Commit**

```powershell
git add src/README.md data/README.md ciq/README.md templates/README.md
git commit -m "docs: add folder navigation guides"
```

### Task 3: Make Storage Terms Consistent

**Files:**

- Modify: `docs/reference/storage-runtime-map.md`
- Modify: `docs/index.md`

**Step 1: Add the workflow storage table**

Put a short table near the start of `docs/reference/storage-runtime-map.md`.

Use the exact roles from the design specification. Do not change file paths.

**Step 2: Correct unsafe cleanup guidance**

Do not tell users to delete all of `data/exports/`. That folder can contain refreshed CIQ workbooks.

Limit cleanup instructions to generated subfolders and files that the system can rebuild.

**Step 3: Add the repository guide to the docs home**

Make the six-step guide easy to find from `docs/index.md`.

Do not add a second copy of the workflow.

**Step 4: Check terms and links**

Run:

```powershell
git diff --check -- docs/reference/storage-runtime-map.md docs/index.md
rg -n "CIQ Standard source template|refreshed CIQ workbook|PM review" docs/reference/storage-runtime-map.md docs/index.md
```

Expected result: no diff errors. The storage roles use the same terms as the design specification.

**Step 5: Commit**

```powershell
git add docs/reference/storage-runtime-map.md docs/index.md
git commit -m "docs: make storage terms consistent"
```

### Task 4: Test The Documentation Change

**Files:**

- Modify: `.agent/session-state.md`
- Move: `docs/plans/active/2026-08-05-repository-navigation-cleanup.md` to `docs/plans/completed/2026-08-05-repository-navigation-cleanup.md`
- Modify: `docs/plans/index.md`

**Step 1: Confirm that no working file changed**

Run:

```powershell
git diff --name-only origin/main...HEAD
```

Expected result: only Markdown files and the approved agent instruction files appear.

**Step 2: Build the documentation**

Run:

```powershell
mkdocs build --strict
```

Expected result: the build completes without an error.

**Step 3: Run the architecture tests**

Run:

```powershell
C:/Users/patri/miniconda3/envs/ai-fund/python.exe -m pytest -p no:cacheprovider tests/test_architecture_boundaries.py -q
```

Expected result: all architecture tests pass.

**Step 4: Run pre-commit**

Run:

```powershell
$env:PRE_COMMIT_HOME = "$PWD\.pre-commit-cache-run-codex"
pre-commit run --all-files
```

Expected result: all hooks pass.

**Step 5: Record the result**

Update `.agent/session-state.md`. Add the commands and results.

Move this plan to `docs/plans/completed/`. Update `docs/plans/index.md`.

**Step 6: Commit**

```powershell
git add .agent/session-state.md docs/plans/index.md docs/plans/completed/2026-08-05-repository-navigation-cleanup.md
git commit -m "docs: complete repository navigation cleanup"
```

### Task 5: Prepare The Pull Request

**Files:** None.

**Step 1: Review the final branch**

Run:

```powershell
git status --short --branch
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected result: the worktree is clean. The branch contains only this documentation change.

**Step 2: Push the branch**

Push only after the PM confirms the final branch.

```powershell
git push -u origin codex/repository-navigation-cleanup
```

**Step 3: Open the pull request**

Use a short summary. Include all test results. State that the pull request does not change system behavior.
