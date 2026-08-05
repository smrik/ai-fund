# Source Code

This folder contains the main analysis code.

| Folder | Purpose | Owner |
| --- | --- | --- |
| `stage_00_data/` | Get and normalize source data | Deterministic code |
| `stage_01_screening/` | Filter the investment universe | Deterministic code |
| `stage_02_valuation/` | Run model and valuation calculations | Deterministic code |
| `stage_03_judgment/` | Analyze evidence and propose assumptions | LLM agents |
| `stage_04_pipeline/` | Control workflows and the PM Decision Queue | Pipeline code |

The frontend and API do not belong in this folder. They have separate root folders.

Read [Learn The Codebase](../docs/learn-codebase.md) for the full workflow.

Read [Architecture](../docs/design-docs/architecture-overview.md) for layer rules.
