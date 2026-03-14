# Accounting Recast Workflow

## Why This Exists

Professional valuation work requires recasting reported accounts before running a DCF. The accounting recast step helps identify:

- one-time items that distort EBIT
- lease, pension, minority interest, and preferred equity bridge items
- excess cash and other non-operating assets

## Workflow

1. Deterministic data fetch pulls filings and core market / CIQ data.
2. `AccountingRecastAgent` reads filing text and proposes classifications.
3. The proposal is shown in the full pipeline output as an advisory block.
4. The PM decides whether to copy any values into `config/valuation_overrides.yaml`.
5. Only approved overrides affect deterministic valuation.

## First-Version Scope

Covered:

- restructuring
- impairments
- litigation settlements
- gains / losses on asset sales
- lease liabilities
- pension deficits
- minority interest
- preferred equity
- non-operating assets

Not yet covered:

- full lease capitalization rebuild
- R&D capitalization
- tax-basis reconstruction
- OCI reserve treatment
