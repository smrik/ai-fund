# Dashboard Decomposition And Shell Normalization

## Summary

This plan makes the dashboard shell match the new product model: five primary tabs (`Overview`, `Valuation`, `Market`, `Research`, `Audit`) plus a persistent right-side dossier companion for scratch capture and durable note blocks.

The implementation goal is to turn `dashboard/app.py` into a thin shell and router, move page rendering into `dashboard/sections/`, and keep the dossier system as a companion research layer rather than a top-level destination.

## Key Changes

- Introduce a registry-driven `dashboard/sections/` package with shared helpers and top-level renderers for the five tabs.
- Normalize the shell to stateful top-tab routing instead of nested workspace/section/deep-dive navigation.
- Keep the dossier companion globally available from any loaded-ticker page as the note-taking surface.
- Recompose `Research` as the working board for thesis state, note blocks, and continuity context.
- Recompose `Audit` as the operational/evidence/export surface and retire `Ops` as a primary destination.
- Update the handbook and plan registry so docs match the shipped shell.

## Test Plan

- Add section-level contract tests for the new `dashboard/sections/*.py` renderers.
- Add dashboard shell tests for the five-tab routing model, tab persistence, and dossier companion visibility.
- Keep existing dossier/research tracker tests passing through the refactor.
- Verify extracted heavy surfaces such as comps, filings, export, recommendations, and portfolio risk.
- Run architecture boundary tests, compile checks, and the offline test suite before completion.

## Assumptions

- The new 5-tab IA is the target end state for this epic.
- Stateful routing is preferred over eager `st.tabs()` rendering.
- `deep_dive_sections.py` remains transitional until its functionality is fully redistributed.
- The dossier companion remains a right-side collapsible surface, not a second native Streamlit sidebar.
- No stage-boundary architecture changes are included in this epic.
