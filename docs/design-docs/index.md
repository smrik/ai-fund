# Design Docs Index

These docs explain how Alpha Pod is designed to work.

Use design docs for architecture, boundaries, data flow, and implementation-facing system behavior. Finance-first valuation methodology lives in [`docs/valuation/`](../valuation/index.md).

## Use This When

- you need the architecture or boundary rules
- you need to know where business logic belongs
- you want implementation truth, not operator guidance

## Read First

> Before any valuation, assumption, or judgment-agent work, read
> [Vision: The Division Of Labor](../strategy/vision.md#the-division-of-labor) and
> [Deterministic Vs LLM Boundary](../valuation/12_deterministic-vs-llm-boundary.md).
> The design docs below describe structure and dependency rules; those two describe **who authors
> the forward-looking assumptions** (the judgment layer, PM-approved), which several older pages
> here predate.

- [Architecture Overview](./architecture-overview.md)
- [Core Beliefs](./core-beliefs.md)
- [TickerDossier Contract](./ticker-dossier-contract.md)
- [Deterministic Valuation Flow Spec](./deterministic-valuation-flow-spec.md)
- [Deterministic Valuation Inputs And CIQ Retrieval Spec](./deterministic-valuation-inputs-and-ciq-retrieval-spec.md)

## Core Design Docs

| Document | Topic |
| --- | --- |
| [`architecture-overview.md`](./architecture-overview.md) | Repository-wide layered architecture and boundaries |
| [`core-beliefs.md`](./core-beliefs.md) | Non-negotiable design principles |
| [`ticker-dossier-contract.md`](./ticker-dossier-contract.md) | Canonical ticker dossier contract for API, React, export, and drift tests |
| [`deterministic-valuation-flow-spec.md`](./deterministic-valuation-flow-spec.md) | Deterministic valuation flow and boundaries |
| [`deterministic-valuation-inputs-and-ciq-retrieval-spec.md`](./deterministic-valuation-inputs-and-ciq-retrieval-spec.md) | Field-level valuation input audit and CIQ retrieval requirements |
| [`deterministic-valuation-workflow.md`](./deterministic-valuation-workflow.md) | Current valuation system behavior |
| [`deterministic-valuation-benchmark-and-gap-analysis.md`](./deterministic-valuation-benchmark-and-gap-analysis.md) | Best-practice valuation benchmark, gap register, and issue map |
| [`valuation-methodology-critical-review-and-action-plan.md`](./valuation-methodology-critical-review-and-action-plan.md) | Consolidated critique and issue-ready action plan for valuation methodology |
| [`context-and-adjustment-analyst-call-architecture-spec.md`](./context-and-adjustment-analyst-call-architecture-spec.md) | Broad context analysts plus losslessly compiled, micro-family adjustment calls |

## Specialized Design Docs

| Document | Topic |
| --- | --- |
| [`hedge-fund-org-mapping.md`](./hedge-fund-org-mapping.md) | Hedge-fund workflow mapped to deterministic code, agents, and PM decisions |
| [`accounting-recast-agent-spec.md`](./accounting-recast-agent-spec.md) | Accounting recast agent design |
| [`qoe-agent-spec.md`](./qoe-agent-spec.md) | QoE agent design |
| [`risk-impact-agent-spec.md`](./risk-impact-agent-spec.md) | Risk-impact agent design |

## Less Common

- [Agent Feedback Loop And Comps Gaps](./agent-feedback-loop-and-comps-gaps.md)
- [Valuation Methodology Critical Review And Action Plan](./valuation-methodology-critical-review-and-action-plan.md)
- [Archived Data Architecture Legacy Note](./archive/data-architecture-legacy.md)
