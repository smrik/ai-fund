# TickerDossier Contract

## Purpose

`TickerDossier` is the canonical payload contract for one ticker across docs, drift tests, API responses, React preload payloads, and export staging.

It defines the stable shape that product surfaces should point at when they need a single-company view of facts, derived valuation data, QoE context, historical series, and export-ready metadata.

This document is the design contract and drift-test reference. The executable runtime schema now lives in `src/contracts/ticker_dossier.py`, and the first shared adapter lives in `src/stage_04_pipeline/ticker_dossier.py`.

## Non-Goals

- Do not normalize the contract into business-fact tables before a real SQL query need exists.
- Do not replace surface-specific API, React, Excel, or HTML compatibility payloads in one breaking step.
- Do not replace the deterministic valuation pipeline.
- Do not add new valuation logic or change model math.
- Do not treat this as a UI spec.
- Do not make this the source of truth for thesis journal content, private notes, or human-authored memo text.

## Contract Scope

The contract covers one ticker at one as-of date.

It must be usable for:

- API response envelopes
- React page preload payloads
- Excel template staging
- HTML export staging
- docs and drift tests that assert shape stability

The contract should help keep these surfaces aligned without forcing each surface to invent its own payload shape.

## Required Top-Level Envelope Fields

The envelope is the outer payload object. It must always include:

| Field | Required | Purpose |
| --- | --- | --- |
| `contract_name` | Yes | Fixed name for the payload family, always `TickerDossier` |
| `contract_version` | Yes | Version of this contract, not the runtime file format |
| `ticker` | Yes | The ticker symbol the dossier belongs to |
| `as_of_date` | Yes | The valuation / snapshot date used to anchor the payload |
| `display_name` | Yes | Human-readable company name |
| `currency` | Yes | Primary reporting currency for the payload |
| `latest_snapshot` | Yes | Latest canonical business snapshot section |
| `loaded_backend_state` | Yes | Normalized state of the backend payload that was loaded |
| `source_lineage` | Yes | Provenance for major fields and derived outputs |
| `export_metadata` | Yes | Staging and export context for downstream consumers |
| `optional_overlays` | Yes | Container for additive surface-specific overlays |

The envelope may also carry extra metadata fields when they are additive and do not change the meaning of the required fields. Those additions must follow the versioning rules below.

## Required Sections

The contract requires these sections at minimum:

| Section | Purpose |
| --- | --- |
| `latest_snapshot` | Canonical company snapshot for the current ticker and date |
| `loaded_backend_state` | Normalized record of what the backend loaded and how it was interpreted |
| `source_lineage` | Field-level or section-level provenance for the payload |
| `export_metadata` | Export, staging, and validation context |
| `company_identity` | Identity fields that every consumer needs |
| `market_snapshot` | Market and trading context |
| `valuation_snapshot` | Deterministic valuation summary and scenario outputs |
| `historical_series` | Time series needed for charts, review, and audit context |
| `qoe_snapshot` | Quality-of-earnings context when present |
| `comps_snapshot` | Comparable-company support data and diagnostics |

`company_identity`, `market_snapshot`, `valuation_snapshot`, `historical_series`, `qoe_snapshot`, and `comps_snapshot` may live inside `latest_snapshot`, but they are still required logical sections of the contract.

## Optional Overlays

Optional overlays are additive, surface-specific payloads that consumers may use when present. They must not redefine the meaning of the core contract.

Suggested overlays:

- `api_view`
- `react_view`
- `excel_view`
- `forecast_bridge`
- `html_view`
- `debug_view`
- `drift_test_view`

Use overlays for presentation hints, layout hints, test helpers, or payload shortcuts. Keep business meaning in the required contract sections.

`forecast_bridge` is the workbook-friendly year-by-year FCFF overlay when a consumer needs a table-shaped projection rather than the compact `latest_snapshot` view.

## Current Producer And Consumer Mapping

This mapping describes the current surfaces that should point at the contract.

| Surface | Current role | Contract relationship |
| --- | --- | --- |
| Deterministic valuation exporter | Produces the canonical valuation snapshot and projection bridge | Primary producer of `latest_snapshot` and `forecast_bridge` |
| Backend dossier loader / normalizer | Loads and normalizes staged payload state | Primary producer of `loaded_backend_state` |
| API | Serves ticker payloads to clients | Consumer of the canonical envelope |
| React | Renders the ticker cockpit and dossier views | Consumer of the canonical envelope and overlays |
| Excel export | Stages workbook-ready review payloads | Consumer of the canonical envelope and workbook overlay |
| HTML export | Stages report-ready payloads | Consumer of the canonical envelope and report overlay |
| Docs and drift tests | Assert payload stability | Consumer of the contract shape and version rules |

API, React, and export flows should point at this contract, not at ad hoc per-surface reshaping. Runtime migrations should keep legacy response fields stable and add or derive from the canonical envelope until downstream callers have fully moved over.

## Current Runtime Compatibility Roots

The first runtime adapter keeps the existing Excel/HTML export roots for compatibility and adds the canonical `ticker_dossier` envelope beside them. Until downstream templates and clients fully migrate, the legacy-compatible staged JSON roots below remain part of the export payload.

Current and archived snapshot export payloads must continue to share these roots:

- `$schema_version`
- `generated_at`
- `ticker`
- `company_name`
- `sector`
- `market`
- `assumptions`
- `wacc`
- `valuation`
- `scenarios`
- `terminal`
- `health_flags`
- `forecast_bridge`
- `source_lineage`
- `ciq_lineage`
- `comps_detail`
- `comps_analysis`

Mode-specific roots are allowed when they do not redefine the shared roots. Today, current backend-state exports may include `research`, while archived snapshot exports may include `snapshot`.

## Versioning Rules

`contract_version` uses semantic versioning:

- `MAJOR` changes break compatibility or rename/remove a required field or section.
- `MINOR` changes add backward-compatible fields, sections, or overlays.
- `PATCH` changes clarify documentation, examples, labels, or metadata without changing contract meaning.

Rules for consumers:

- Consumers should target a major version explicitly.
- Consumers must tolerate additive minor and patch fields they do not use.
- Consumers should reject or flag payloads that drop required fields for the major version they understand.
- Documentation drift tests should pin the contract version and the required section list.

Rules for producers:

- Do not remove or rename required fields within a major version.
- Additions should be additive unless the contract version is intentionally bumped.
- Overlays should never be required for core reading paths.

## `latest_snapshot`

### Purpose

`latest_snapshot` is the main company payload for the current ticker and date. It carries the stable fields most consumers need first.

### Section Skeleton

```json
{
  "latest_snapshot": {
    "identity": {
      "ticker": "IBM",
      "display_name": "International Business Machines",
      "sector": "Technology",
      "industry": "IT Services",
      "exchange": "NYSE"
    },
    "market_snapshot": {
      "as_of_date": "2026-04-30",
      "price": 0,
      "market_cap": 0,
      "enterprise_value": 0,
      "beta": 0
    },
    "valuation_snapshot": {
      "base_iv": 0,
      "bear_iv": 0,
      "bull_iv": 0,
      "expected_iv": 0,
      "upside_pct": 0
    },
    "qoe_snapshot": {
      "present": false,
      "score": null,
      "flags": []
    },
    "historical_series": {
      "revenue": [],
      "ebit": [],
      "fcff": [],
      "margin": []
    },
    "comps_snapshot": {
      "peer_count": 0,
      "primary_metric": "EV/EBITDA",
      "median_multiple": null
    },
    "source_lineage": {
      "identity": "market-data",
      "market_snapshot": "market-data",
      "valuation_snapshot": "deterministic-valuation",
      "qoe_snapshot": "qoe-agent",
      "historical_series": "market-data",
      "comps_snapshot": "ciq"
    }
  }
}
```

### Notes

- `latest_snapshot` should stay compact enough for API and React use.
- Derived values belong here when they are part of the normal review surface.
- Detailed audit history belongs in `loaded_backend_state` or separate provenance structures, not in this section.

## `loaded_backend_state`

### Purpose

`loaded_backend_state` records how the current payload was loaded, normalized, and validated. It gives consumers a way to understand the adapter state without re-running the backend.

### Section Skeleton

```json
{
  "loaded_backend_state": {
    "backend_name": "valuation-json",
    "backend_version": "1.0.0",
    "loaded_from": "data/valuations/json/IBM_latest.json",
    "loaded_at": "2026-04-30T09:15:00Z",
    "source_format": "json",
    "normalization_mode": "canonical",
    "validation": {
      "passed": true,
      "warnings": [],
      "missing_required_fields": []
    },
    "field_mappings": {
      "identity": "identity",
      "market_snapshot": "market_snapshot",
      "valuation_snapshot": "valuation_snapshot",
      "qoe_snapshot": "qoe_snapshot"
    },
    "adapter_state": {
      "react_ready": true,
      "excel_ready": true,
      "html_ready": true
    }
  }
}
```

### Notes

- This section is about load state and normalization state, not about business facts.
- It should make drift obvious when a consumer receives a payload that has been partially normalized or partially loaded.
- The exact field names inside this section may expand additively, but the purpose should stay stable.

## Drift-Test Expectations

Any contract drift test should verify at least:

- the envelope name
- the contract version
- the ticker and as-of date
- the required section list
- the presence of `latest_snapshot` and `loaded_backend_state`
- the producer/consumer mapping described above

The test goal is to catch accidental shape drift early, not to freeze every optional field forever.

## Implementation Boundary

This contract is implemented by:

- `src/contracts/ticker_dossier.py`
- `src/stage_04_pipeline/ticker_dossier.py`

It is the target for:

- API payload adapters
- React preload adapters
- export staging adapters

The current runtime path is intentionally additive: API and export callers can consume `ticker_dossier` while the legacy fields remain stable.

## V1 Adapter Enrichment

The v1 enrichment path is adapter-level mapping of fields that already exist in export or archive payloads. It may lift company identity metadata such as `industry`, `exchange`, `description`, and `country`; QoE context from an existing `qoe` block; and historical revenue, EBIT, margin, and FCFF series from existing payload sections.

This is not a new data collection path. Building or reading a `TickerDossier` must not call yfinance, CIQ refresh, EDGAR, QoE LLMs, or batch valuation just to fill enrichment fields. Missing QoE or history remains a valid payload state: QoE uses `present=false`, and missing historical series stay as empty lists.

## Persistence

Canonical dossier payloads are persisted additively in `ticker_dossier_snapshots`.
The table stores the full validated `TickerDossier` JSON payload plus minimal lookup columns:
`ticker`, `as_of_date`, `contract_version`, `source_mode`, `source_key`, `snapshot_id`,
`generated_at`, and `display_name`.

`source_key` is `snapshot:{snapshot_id}` for archived snapshot dossiers and
`asof:{as_of_date}` when no archived snapshot id exists. The unique persistence key is
`ticker`, `source_mode`, `source_key`, and `contract_version`.

The persistence path is intentionally not a normalized business schema. Valuation facts,
market facts, peer data, and source lineage remain inside `payload_json` in v1. New ticker
exports persist current or archived dossier payloads; API reads prefer persisted rows and
fall back to building a dossier without writing from the read path.
