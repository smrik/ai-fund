# CLAUDE.md — Alpha Pod

Follow [`AGENTS.md`](./AGENTS.md) in full. It is the operating map for all coding agents in this repo; everything there applies to Claude Code sessions.

Non-negotiables, restated for emphasis:

1. **Vision compliance:** [`docs/strategy/vision.md`](./docs/strategy/vision.md) holds the PM's settled decisions. Never re-litigate them; name conflicts instead of working around them. New plans must state which decision(s) they serve.
2. **Interview-first specs:** for non-trivial features, interview the PM to resolve ambiguity before writing a plan. Never draft specs cold from a one-line idea.
3. **Ambiguity split:** finance semantics (thresholds, ranges, valuation logic) block on the PM; engineering details get a conservative decision logged in the plan/PR.
4. **LLM boundary:** LLM code never touches the deterministic computation layer. The PM Decision Queue is the only bridge from judgment output to model mutation.
5. **One planning system:** active work lives in `docs/plans/active/` with an entry in `docs/plans/index.md`; current sequencing is the [Six-Month Execution Roadmap](./docs/plans/future/2026-06-12-six-month-execution-roadmap.md).
6. **Streamlit is frozen** (bugfix-only, retiring). New UI work goes to `frontend/` + `api/`.
