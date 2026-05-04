# Epic: Canonical Ticker Dossier And Export Integrity

| Field | Value |
|---|---|
| Status | Planned |
| Priority | P0 |
| Target release | v0.2.0 Dossier Integrity |
| GitHub | [#14](https://github.com/smrik/ai-fund/issues/14) |
| Last updated | 2026-05-04 |

## Problem

Alpha Pod already has useful API, React, and export surfaces, but the underlying ticker payload is still not cleanly canonical. JSON export, workbook export, and UI views still carry shape gaps and inconsistent richness, especially around QoE, historical data, sensitivity, and comps support data.

## Smallest Valuable Outcome

One canonical ticker dossier contract can feed API responses, React pages, and Excel/HTML exports without ad hoc reshaping or missing core fields. The contract is documented in [docs/design-docs/ticker-dossier-contract.md](../../design-docs/ticker-dossier-contract.md) and is the target for future adapters and drift tests.

## In Scope

- Canonical ticker dossier payload
- Full name, sector, industry, and as-of date in the export contract
- Historical series needed for charts and model context
- QoE inclusion in canonical export paths
- Sensitivity analysis cleanup
- Richer comps support data: EBITDA, EBIT, margins, leverage, and related diagnostics
- Workbook/export polish where it materially improves review quality

## Out Of Scope

- Team collaboration features
- New deployment infrastructure
- Generic AI chat features
- Major frontend redesign beyond what the dossier contract directly unlocks

## Dependencies

- Stable deterministic valuation outputs
- Clear export-service ownership
- Agreement that the dossier contract is canonical across product surfaces
- The canonical contract doc at [docs/design-docs/ticker-dossier-contract.md](../../design-docs/ticker-dossier-contract.md)

## Acceptance Criteria

- One documented dossier contract exists and is reused by API, React preload payloads, and export flows
- JSON export includes full name, sector/industry, as-of date, QoE, and historical series needed by the product
- Sensitivity and comps payloads are complete enough for dashboard and workbook use without custom patch-up logic
- Export surfaces consume canonical fields rather than bespoke per-surface reshaping
- Child issues can implement adapters against the contract without changing the contract definition first

## Notes

This is the first roadmap epic because every later product surface becomes easier once the ticker dossier is reliable.
