# SP06 - Skill Gap Review and Research Surface Audit

>Status: `verified`
>Primary Skills: `brainstorming`, `writing-plans`, `comps-analysis`, `competitive-analysis`, `initiating-coverage`

## Goal
Systematically compare the implemented dashboard and research surfaces against the repo-local financial-analysis and equity-research skills, then produce an explicit residual backlog that a future agent can pick up without re-running the review.

## What Was Reviewed
- `skills/financial-analysis/skills/comps-analysis/SKILL.md`
- `skills/financial-analysis/skills/competitive-analysis/SKILL.md`
- `skills/financial-analysis/skills/check-model/SKILL.md`
- `skills/financial-analysis/skills/dcf-model/SKILL.md`
- `skills/equity-research/skills/initiating-coverage/SKILL.md`
- `skills/equity-research/skills/model-update/SKILL.md`
- `skills/equity-research/skills/earnings-analysis/SKILL.md`
- `skills/equity-research/skills/sector-overview/SKILL.md`
- `skills/equity-research/skills/thesis-tracker/SKILL.md`
- `skills/edgartools/SKILL.md`

## Coverage Review

### `comps-analysis`
Current coverage is materially better than the baseline. The dashboard now exposes metric switching, peer weights, target-vs-peer medians, a football field, and target historical multiples. That covers the skill's core requirements around comparability, medians, quartile-style benchmarking, and transparent valuation statistics well enough for the current tranche.

The remaining gap is depth rather than absence. The current UI still does not show explicit quartile rows, max/min statistics, or a fully source-cited peer-statistics appendix the way a spreadsheet-grade comp would. That belongs in the next tranche, not this one.

### `competitive-analysis`
The dashboard now has a stronger target-vs-peer comparison surface, but it is still a valuation-first view rather than a full competitive landscape map. The skill expects competitor grouping, positioning frameworks, segment/context mapping, and clearer strategic differentiation. The current product only partially covers that through the peer table and Market Intel narrative.

This gap belongs in the next tranche. The missing user value is a dedicated competitor-landscape surface that explains who the real competitors are, why they belong together, and how the target is positioned across growth, margins, scale, and moat.

### `check-model`
The product now has DCF Audit and WACC Lab, which cover scenario review and assumption inspection, but it still does not expose model-integrity checks in the style this skill expects. There is no explicit surface for balance-sheet tie checks, cash-flow tie checks, hardcode detection, or logic warnings such as terminal value concentration or formula integrity.

This is a next-tranche gap. The missing user value is confidence that the deterministic model is not only interpretable, but mechanically sound in a model-audit sense.

### `dcf-model`
The current dashboard already had DCF Audit, WACC Lab, and sensitivity analysis, and this tranche improved readability and formatting. That covers the skill's user-facing need for scenario visibility and WACC inspection. The remaining gap is that the dashboard still does not expose the deeper model-builder artifacts the skill expects, such as a documented assumption-source registry, formula-level integrity checks, or a stronger sensitivity-summary narrative.

This belongs partly in the next tranche and partly as ongoing tech debt. The dashboard is already useful, but not yet a full "model-builder companion" surface.

### `initiating-coverage`
The dashboard now covers many components that matter to initiation-style work: thesis, filings, valuation, sentiment, market intel, and comps. What remains missing is a cohesive "initiation pack" view that deliberately assembles company background, sector context, moat framing, peer set rationale, and valuation into a publication-style surface.

This is a deferred backlog item rather than an immediate next-tranche requirement. The current system is more PM workbench than formal initiation report.

### `model-update`
This skill expects explicit old-vs-new estimate comparison, quarterly plug analysis, and model revision history. The dashboard currently surfaces the latest report state and archived snapshots, but it does not expose estimate revision tables, prior-vs-current assumption deltas, or an earnings-driven model-update panel.

This belongs in the next tranche. The missing user value is a structured "what changed in the model" view after new results or guidance.

### `earnings-analysis`
The system already has an EarningsAgent and now pairs it with filing context plus Market Intel. However, the dashboard still does not provide a dedicated beat/miss table, consensus-versus-actual bridge, or estimate revision block in the way the skill prescribes.

This belongs in the next tranche. The missing user value is a post-earnings update surface that shows what was new, what beat or missed, and how that changed forward expectations.

### `sector-overview`
The current IndustryAgent summary is useful, but it is still a lightweight benchmark and context layer. The skill expects a real market landscape: top players, industry structure, value-chain map, sector trading context, and thematic implications.

This is a deferred backlog item. It is important, but it is a larger research product surface than the current tranche needed to solve.

### `thesis-tracker`
The report archive gives historical snapshots, but there is still no structured thesis scorecard, no catalyst calendar, and no running record of whether thesis pillars are strengthening or weakening over time.

This belongs in the next tranche. The missing user value is a durable way to track whether the current position thesis is intact between reports.

### `edgartools`
The current filings browser is much more auditable now: raw HTML, clean text, extracted sections, selected chunks, coverage status, and retrieval diagnostics are all visible. That addresses the immediate trust problem around what the agents actually saw.

The remaining gap is structured statement browsing. The skill expects richer financial-statement and XBRL-style extraction, whereas the current surface is still text-first. That is a deferred backlog item because the current tranche solved the more urgent auditability problem.

## Residual Backlog

### Next Tranche
- Add a dedicated competitor-landscape view with peer grouping, positioning axes, and moat/strategy comparisons.
- Add a model-integrity panel with balance-sheet tie checks, cash-flow tie checks, terminal-value concentration, and explicit audit warnings.
- Add an earnings-update panel with beat/miss, consensus vs. actual, and old-vs-new estimate revisions.
- Add a thesis-tracker surface with thesis pillars, catalyst calendar, update log, and conviction trend.

### Deferred
- Add a richer sector-overview workspace with market structure, top players, and valuation context across the sector.
- Add a formal initiation-style assembly view for research packs and client-facing writeups.
- Add structured XBRL / statement-table browsing in the filings surface so users can move beyond text and chunk provenance.

## Output Decision
The current tranche is sufficient to mark the original dashboard-research plan complete. The residual items above are real gaps, but they are follow-on product work, not incomplete execution of the current ExecPlan.

## Verification
- Manual review of the listed skills completed on 2026-03-15.
- Residual backlog captured here and mirrored into `docs/exec-plans/tech-debt-tracker.md`.
- Canonical ExecPlan updated to reflect the review outcome.
