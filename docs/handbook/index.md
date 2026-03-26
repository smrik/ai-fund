# Handbook Index

This handbook is the practical wiki for operating and extending Alpha Pod.

It is written for two audiences:

1. **Finance operators**: how numbers are produced, what assumptions mean, and where human judgment belongs.
2. **Software engineers**: how data flows through the codebase, where to modify logic, and how to verify changes safely.

## Read This First

- [End-to-End Workflow](./workflow-end-to-end.md)
- [Finance Deep Dive](./finance-deep-dive.md)
- [Valuation And DCF Logic](./valuation-dcf-logic.md)
- [Valuation Task Breakdown](./valuation-task-breakdown.md)
- [Engineering Deep Dive](./engineering-deep-dive.md)
- [Operations Runbook](./operations-runbook.md)
- [Local Dashboard Validation](./local-dashboard-validation.md)
- [WSL Playwright Fallback](./wsl-playwright.md)
- [Quality And Verification](./quality-and-verification.md)
- [Deep Dive Dossier](./deep-dive-dossier.md)

## Mental Model

Alpha Pod has two analysis tracks in the repository:

1. Deterministic valuation track (recommended production path)

- Data ingest from yfinance/EDGAR/CIQ
- WACC + DCF + reverse DCF in pure Python
- Ranked outputs in SQLite + CSV

2. Full memo synthesis track (agent-heavy)

- Multi-agent IC memo orchestration in `src/stage_04_pipeline/orchestrator.py`
- Useful for narrative synthesis
- Not the authoritative path for deterministic intrinsic value ranking

```mermaid
flowchart TD
    A["Market Universe"] --> B["Stage 1 Screen (yfinance)"]
    B --> C["Batch WACC + DCF (deterministic)"]
    C --> D["SQLite + latest.csv outputs"]
    D --> E["Human PM Review"]

    B --> F["Optional Agent Layer"]
    F --> G["QoE / Industry Context"]
    G --> E

    H["Legacy IC Memo Orchestrator"] --> E
```

## Non-Negotiable Invariant

LLM agents may explain or contextualize numbers, but they must not write numbers back into the deterministic compute path unless explicitly reviewed and accepted by a deterministic transform.

## Suggested Reading Order

1. End-to-end workflow (process map)
2. Valuation and DCF logic (how intrinsic value is computed)
3. Finance deep dive (how to interpret and challenge outputs)
4. Engineering deep dive (where to change code safely)
5. Runbook and verification (how to operate and release changes)


