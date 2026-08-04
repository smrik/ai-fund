# CLAUDE.md — Alpha Pod

Follow [`AGENTS.md`](./AGENTS.md) in full. It is the operating map for all coding agents in this repo; everything there applies to Claude Code sessions.

Non-negotiables, restated for emphasis:

1. **Vision compliance:** [`docs/strategy/vision.md`](./docs/strategy/vision.md) holds the PM's settled decisions. Never re-litigate them; name conflicts instead of working around them. New plans must state which decision(s) they serve.
2. **Interview-first specs:** for non-trivial features, interview the PM to resolve ambiguity before writing a plan. Never draft specs cold from a one-line idea.
3. **Ambiguity split:** finance semantics (thresholds, ranges, valuation logic) block on the PM; engineering details get a conservative decision logged in the plan/PR.
4. **LLM boundary:** LLM code never *executes inside* the deterministic computation layer, and the PM Decision Queue is the only bridge from judgment output to model mutation. This is a rule about where code runs — the judgment layer is nonetheless what *sets* the key forward-looking assumptions, reasoning over qualitative and quantitative evidence ([Vision Decision 13](./docs/strategy/vision.md#the-division-of-labor)). Sector constants and mechanical transforms in `*_target` drivers are fallbacks that signal missing judgment, not the intended design.
5. **One planning system:** active work lives in `docs/plans/active/` with an entry in `docs/plans/index.md`; current sequencing is the [Six-Month Execution Roadmap](./docs/plans/future/2026-06-12-six-month-execution-roadmap.md).
6. **Streamlit is frozen** (bugfix-only, retiring). New UI work goes to `frontend/` + `api/`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repository's GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The repository uses the five default triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

The repository uses a single-context domain-documentation layout. See `docs/agents/domain.md`.
