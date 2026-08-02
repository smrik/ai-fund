# Judgment-Driver Provenance Gate

**Vision decisions served:** Decision 13 (judgment owns forward-looking drivers and the PM Decision Queue is the mutation bridge) and Decision 14 (valuation trust state must be visible and fail closed).

## Objective

Make every valuation run explicit about whether each judgment-owned driver is backed by a judgment-authored value. A run may remain usable for review while it is provisional, but it must not claim `decision_grade` when a used judgment-owned driver is defaulted, consensus-derived, otherwise non-judgment, or absent from provenance.

## Design decisions

- Extend `ValuationReadinessEvidence` and its existing trust-state computation; do not add a parallel gate.
- Keep raw `source_lineage` labels unchanged. Add a small strength taxonomy over labels already emitted by the assembler: PM-approved, consensus (`ciq*` except deterministic blends), deterministic fallback (`default`, `ciq_blend`, public-market/prior labels), and unrecorded.
- A PM-approved assumption-register source or a complete approved driver-family pack satisfies the driver gate. Generic overrides do not count as judgment approval unless the existing source label explicitly records approval.
- Any used non-approved judgment-owned driver downgrades the valuation to `provisional`, with default fallbacks more severe than consensus and missing lineage most severe. Existing structural failures remain `blocked`; no existing blocker is weakened.
- A lineage key absent from `source_lineage` is reported as `unrecorded`. Usage is determined from the valuation driver payload where available; a driver not used by a model is reported as unused and does not create a provenance failure.
- The input assembler may gain provenance-only entries, but no default value or valuation math changes.

## Implementation slices

1. Add red tests for source-strength classification, default/consensus/approved distinctions, missing lineage, all-approved readiness, and PM markdown output.
2. Add the provenance contract and feed its verdicts into `ValuationReadinessEvidence`.
3. Preserve the complete source-lineage mapping through the override/export surfaces and add all-driver verdicts to the PM-facing guided markdown.
4. Run focused tests, the offline suite with the required interpreter, inspect the current MSFT artifact, and update the handoff state.

## Verification commands

```powershell
C:/Users/patri/miniconda3/envs/ai-fund/python.exe -m pytest -p no:cacheprovider tests/test_judgment_driver_provenance.py tests/test_valuation_readiness.py -q
C:/Users/patri/miniconda3/envs/ai-fund/python.exe -m pytest -p no:cacheprovider -q
```

The known `.tmp-tests` Windows ACL failures are unrelated and will be reported separately if they recur.
