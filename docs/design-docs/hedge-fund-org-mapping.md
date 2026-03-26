# Hedge Fund Org Chart → AI Agent Mapping

> **Core idea:** A well-run fundamental L/S equity fund with $500M–2B AUM has ~15–30 people across 5 functional areas. Each role has a defined workflow. Map every workflow to one of three categories: **deterministic code**, **LLM agent**, or **human (you)**. The org chart *is* the spec.

---

## The Actual Org Chart (Mid-Size Fundamental L/S Fund)

```
                    ┌─────────────────────┐
                    │   Founder / CIO     │
                    │   (Julian Robertson)│
                    └─────────┬───────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
   ┌────────▼──────┐  ┌──────▼───────┐  ┌──────▼───────┐
   │  Investment   │  │  Operations  │  │   Business   │
   │    Team       │  │  & Risk      │  │   Side       │
   └────────┬──────┘  └──────┬───────┘  └──────┬───────┘
            │                │                  │
     ┌──────┼──────┐    ┌────┼────┐        ┌───┼────┐
     │      │      │    │    │    │        │   │    │
    PM    Senior  Jr   Risk  Ops  IT     IR  Legal  Compliance
          Analyst Analyst Mgr
```

When you're running your own capital, the entire right column (**Business Side**) disappears. No investors = no IR, minimal legal, minimal compliance. That's a massive simplification.

What remains is the **Investment Team** and **Operations & Risk** — which is exactly what we're automating.

---

## Function 1: Portfolio Manager (PM)

### What they do at a real fund

The PM is the final decision-maker. At Tiger, Robertson himself filled this role. At Tiger Cubs like Lone Pine or Viking, it's the founder (Mandel, Halvorsen). The PM does not do primary research — they consume research and make capital allocation decisions.

**Daily workflow:**
- Morning: Review overnight moves, read risk report, scan analyst flags
- Throughout day: Meet with analysts pitching ideas, challenge their theses
- Decision points: Approve/reject new positions, adjust sizing, set risk limits
- Weekly: Portfolio review meeting — every position justified or cut
- Quarterly: Strategy review — is the process working, what needs to change

**What makes a great PM (from the Tiger tradition):**
- Ability to synthesize across sectors and see portfolio-level patterns
- Psychological discipline to size up winners and cut losers
- Willingness to concentrate when conviction is high
- Constant devil's advocacy — if the analyst can't defend it, it doesn't go in

### Your mapping

| PM task | Maps to | Why |
|---|---|---|
| Final yes/no on positions | **YOU** | This is the entire point of being PM |
| Position sizing decisions | **YOU** | Conviction-weighted, not formulaic |
| Setting risk limits | **YOU** (one-time, then code enforces) | Philosophy encoded into rules |
| Morning book review | **Dashboard** (deterministic) | P&L, exposure, alerts — no reasoning needed |
| Challenging analyst theses | **YOU + Red-team LLM** | LLM generates the pushback; you evaluate it |
| Portfolio construction (correlation, factor exposure) | **Deterministic code** | Quantitative constraints, not judgment |
| Strategy-level review | **YOU** | Meta-level: is the system working? |

**Bottom line:** The PM role is 80% you. The 20% you offload is the mechanical stuff — dashboards, risk calculations, alert systems.

---

## Function 2: Senior Analyst / Sector Head

### What they do at a real fund

The senior analyst is the engine of the fund. At a typical Tiger Cub, a senior analyst covers 15–30 names in a sector, maintains models on all of them, and is expected to generate 1–2 actionable ideas per month. They're the ones who write the IC memos the PM reads.

**Daily workflow:**
- 6:00 AM: Scan overnight news, earnings, filings for coverage universe
- 7:00–9:30: Update models for any new data, read sell-side research
- 9:30: Watch the open — any unusual movers in their sector?
- 10:00–12:00: Deep research — reading filings, building/updating models, channel checks
- 12:00–1:00: Sell-side lunch or management meeting (1–2x per week)
- 1:00–4:00: Continue research, prepare pitches for PM
- 4:00: Close review — any end-of-day moves to flag?
- Evening: Read long-form research, industry publications, prepare for next day

**The senior analyst's real value:**
- Deep sector knowledge that takes years to build
- Relationships with management teams and industry contacts
- Pattern recognition: "I've seen this margin story before, it ended badly at Company X"
- Ability to articulate a variant perception that is genuinely non-consensus

### Your mapping

| Senior analyst task | Maps to | Why |
|---|---|---|
| Overnight news/filing scan | **Deterministic pipeline** | RSS/API → filter → flag. No reasoning needed. |
| Model updates for new data | **Deterministic pipeline** | Data extraction → template population. Math, not judgment. |
| Read sell-side research | **LLM summarizer** | Extract consensus view, target prices, key debates. LLMs excel at this. |
| Watch unusual movers | **Deterministic alerts** | Price/volume threshold → notification. |
| Filing deep-dive (10-K, 10-Q) | **LLM extraction + your review** | LLM pulls structured data + MD&A summary. You read the summary. |
| Management meetings / channel checks | **NOT AUTOMATABLE** | Relationship-based, qualitative. This is a real gap for a solo operator. |
| Build/maintain financial models | **Hybrid** | Historical data auto-populated. Forward assumptions = you. |
| Write IC memo / pitch | **LLM first draft + you edit** | LLM assembles from agent outputs. You write the variant perception. |
| Pattern recognition across names | **YOU** | "I've seen this before" requires experience, not data. |
| Sector expertise / industry knowledge | **YOU + web search** | LLMs can surface info, but deep sector intuition is human. |

**Bottom line:** The senior analyst role is where AI creates the most leverage. ~60% of the daily workflow is information processing that LLMs and pipelines can handle. The 40% that stays human is the judgment, pattern recognition, and relationship-based channel checks.

**The gap to acknowledge:** Management meetings and channel checks (talking to suppliers, customers, competitors) are a real edge at funds like Tiger and Viking. As a solo operator, you compensate with: deeper public data analysis, alternative data (web scraping, job postings, app downloads), and sell-side relationships built over time.

---

## Function 3: Junior Analyst / Research Associate

### What they do at a real fund

The junior analyst is the workhorse. They do the grunt work the senior analyst doesn't have time for: data collection, model building, screening, comp tables, filing summaries. At many funds, the junior analyst spends 70%+ of their time on tasks that are mechanical and repetitive.

**Daily workflow:**
- Pull and organize data for the senior analyst
- Build and maintain comp tables and peer group analyses
- Summarize earnings calls and flagging key changes
- Screen the universe for names that meet criteria
- Format and update models with latest quarterly data
- Prepare materials for IC meetings
- Monitor news flow for the coverage universe

### Your mapping

| Junior analyst task | Maps to | Why |
|---|---|---|
| Data collection & organization | **Deterministic pipeline** | API calls, file downloads, database inserts |
| Comp table construction | **Deterministic pipeline** | Pull peer data → compute multiples → format |
| Earnings call summarization | **LLM** | This is exactly what LLMs were built for |
| Universe screening | **Deterministic pipeline** | SQL filters on structured data |
| Model data entry (historicals) | **Deterministic pipeline** | XBRL parsing → template mapping |
| IC meeting materials | **LLM assembly** | Template fill from structured data |
| News monitoring | **Deterministic + LLM classification** | RSS feed → LLM tags relevance/materiality |

**Bottom line:** The junior analyst role is **~95% automatable**. This is your highest-ROI automation target. Every hour you'd spend on this work is an hour you're not thinking like a PM.

---

## Function 4: Trader / Execution

### What they do at a real fund

The trader takes the PM's decision and executes it in the market with minimal market impact. At a small fund, the PM often trades themselves. At larger funds, dedicated traders manage execution algos, time entries/exits, and manage relationships with counterparties.

**Daily workflow:**
- Receive order from PM with size, urgency, and price limits
- Choose execution strategy (VWAP, TWAP, limit, market)
- Monitor execution quality and adjust
- Manage broker relationships for best execution
- Handle borrow for short positions
- Report execution quality back to PM

### Your mapping

| Trader task | Maps to | Why |
|---|---|---|
| Receive and validate orders | **Deterministic code** | Risk check → order validation → broker API |
| Execution algo selection | **Rules-based** | Size-based rules: <$50K = market, >$50K = TWAP/VWAP |
| Execution monitoring | **Deterministic alerts** | Slippage tracking, fill monitoring |
| Borrow availability for shorts | **API check** | IB provides borrow data via API |
| Best execution reporting | **Deterministic analytics** | Log fills, compute implementation shortfall |
| Broker relationship management | **N/A** | Irrelevant at your scale |

**Bottom line:** Execution is **~100% automatable** at your scale. Interactive Brokers' API handles everything. The only human input is the initial order (which comes from your PM decision).

---

## Function 5: Risk Manager

### What they do at a real fund

The risk manager is the independent check on the PM and analysts. At Citadel, risk management is famously aggressive — if you breach your drawdown limit, you're cut. At Tiger-style funds, it's more collaborative but still rigorous.

**Daily workflow:**
- Calculate portfolio-level metrics: gross/net exposure, beta, sector concentration
- Monitor single-name concentration and liquidity
- Run stress tests: what happens if rates spike 100bp, if a sector drops 20%
- Flag positions approaching risk limits
- Report to PM on factor exposures and unintended bets
- During crises: real-time monitoring and potential forced de-risking

### Your mapping

| Risk manager task | Maps to | Why |
|---|---|---|
| Exposure calculations (gross, net, beta) | **Deterministic code** | Pure math on position data |
| Concentration monitoring | **Deterministic code** | Threshold checks per name/sector |
| Liquidity analysis | **Deterministic code** | Position size ÷ avg volume = days to exit |
| Stress testing | **Deterministic code** | Scenario matrices applied to portfolio |
| Factor exposure analysis | **Deterministic code** | Regression-based factor decomposition |
| Limit breach alerts | **Deterministic alerts** | Threshold → notification |
| Crisis-mode judgment calls | **YOU** | When to de-risk is a PM decision |

**Bottom line:** Risk management is **~95% deterministic code**. This is one of the clearest wins — risk tools are well-established (even open-source options like `pyfolio`, `empyrical`). The only human input is setting the rules and making judgment calls in extreme scenarios.

---

## Function 6: Operations / Back Office

### What they do at a real fund

Ops handles trade reconciliation, NAV calculation, cash management, corporate actions, and reporting. At a fund with outside investors, this is a large function. For your own capital, it shrinks dramatically.

**Daily workflow:**
- Reconcile trades between internal records and broker
- Calculate daily NAV and P&L attribution
- Process corporate actions (dividends, splits, mergers)
- Manage cash balances and margin
- Generate reports for PM

### Your mapping

| Operations task | Maps to | Why |
|---|---|---|
| Trade reconciliation | **Deterministic code** | Compare order log vs. broker confirms via API |
| NAV calculation | **Deterministic code** | Position * price, marked daily |
| P&L attribution | **Deterministic code** | Standard Brinson attribution |
| Corporate actions | **Deterministic code** | Broker API handles most; flag exceptions |
| Cash/margin management | **Deterministic alerts** | Monitor margin utilization, flag if >70% |
| Performance reporting | **Deterministic code** | Standard time-weighted returns |

**Bottom line:** Operations is **100% automatable** at your scale. IB's account management API provides most of this natively.

---

## Function 7: IT / Data Infrastructure

### What they do at a real fund

IT maintains the data feeds, trading systems, research databases, and infrastructure. At quant funds this is a huge team. At fundamental funds it's smaller but still critical.

### Your mapping

This isn't a separate "agent" — it's your codebase and infrastructure. Python scripts, cron jobs, database (PostgreSQL or even SQLite for your scale), and monitoring.

| IT task | Maps to | Why |
|---|---|---|
| Data feed management | **Cron jobs + health checks** | API pull scripts with failure alerting |
| Database maintenance | **Automated** | PostgreSQL with scheduled backups |
| System monitoring | **Uptime checks** | Ping data sources, alert on failure |
| Security | **Standard DevOps** | SSH keys, encrypted storage, 2FA everywhere |

---

## The Complete Mapping Summary

### Headcount at a real fund vs. your system

| Role | Typical headcount (mid-size fund) | Your system | Category |
|---|---|---|---|
| CIO / PM | 1 | **YOU** | Human |
| Senior Analysts | 3–6 | **YOU + LLM agents** | Hybrid |
| Junior Analysts | 3–8 | **Pipelines + LLMs** | Automated |
| Trader(s) | 1–3 | **Broker API + rules** | Automated |
| Risk Manager | 1–2 | **Deterministic code** | Automated |
| Operations | 2–5 | **Broker API + scripts** | Automated |
| IT | 1–3 | **Your codebase** | Automated |
| IR / Marketing | 1–3 | **N/A** (own capital) | Eliminated |
| Legal / Compliance | 1–2 | **N/A** (own capital, below thresholds) | Eliminated |
| CFO / COO | 1 | **N/A** (own capital) | Eliminated |
| **Total** | **15–30 people** | **1 person + code** | — |

### Where LLMs actually sit (and only where they sit)

| LLM use case | Replacing which role | Model tier | Frequency |
|---|---|---|---|
| MD&A / risk factor extraction | Junior analyst | Haiku (cheap, fast) | Per filing (~4x/year/name) |
| Earnings call analysis | Junior + senior analyst | Sonnet (needs nuance) | Per earnings (~4x/year/name) |
| Sell-side consensus summary | Junior analyst | Haiku | Monthly refresh |
| News materiality classification | Junior analyst | Haiku | Daily batch |
| IC memo first draft assembly | Junior analyst | Sonnet | Per new idea |
| Red-team / devil's advocate | Senior analyst (peer challenge) | Sonnet (needs reasoning) | Per thesis |
| Narrative/sentiment monitoring | Junior analyst | Haiku | Weekly batch |

**Total: 7 LLM use cases.** Everything else is deterministic Python or human judgment.

### What stays irreducibly human

1. **Variant perception** — why the consensus is wrong
2. **Catalyst identification** — what event closes the gap and when
3. **Sizing conviction** — how much to bet and holding through drawdowns
4. **Short thesis construction** — structural/behavioral judgment
5. **Strategy-level review** — is the system adding value
6. **Crisis decision-making** — when to de-risk in a crash
7. **Channel checks / management assessment** — reading people, not filings

These seven things are what Robertson tested for with the 450-question psych test. They're what separated Tiger from every other value fund. And they're what you spend 100% of your time on once the system is built.

---

## The Workflow as a Single Pipeline

Putting it all together — how a name flows through your "fund":

```
[Screening Pipeline]  ← Deterministic: SQL filters, cron job
        │
        ▼
[Data Ingestion]      ← Deterministic: EDGAR API, market data API
        │
        ▼
[Filing Extraction]   ← LLM (Haiku): MD&A summary, risk flags
        │
        ▼
[Model Population]    ← Deterministic: XBRL → template mapping
        │
        ▼
[Earnings Analysis]   ← LLM (Sonnet): transcript comparison, tone shifts
        │
        ▼
[Consensus View]      ← LLM (Haiku): sell-side summary
        │
        ▼
[IC Memo Draft]       ← LLM (Sonnet): assembles from all prior outputs
        │
        ▼
┌───────────────────────────────────────────┐
│  ★ HUMAN CHECKPOINT ★                    │
│                                           │
│  You review the memo draft.               │
│  You set forward model assumptions.       │
│  You write the variant perception.        │
│  You identify catalysts and kill criteria. │
└───────────────────┬───────────────────────┘
                    │
                    ▼
[Red-Team Agent]    ← LLM (Sonnet): stress-test your thesis
        │
        ▼
┌───────────────────────────────────────────┐
│  ★ HUMAN DECISION ★                      │
│                                           │
│  You review the red-team output.          │
│  You decide: invest / pass / more work.   │
│  You set position size.                   │
└───────────────────┬───────────────────────┘
                    │
                    ▼
[Risk Check]        ← Deterministic: limit checks, exposure calc
        │
        ▼
[Execution]         ← Deterministic: broker API, TWAP/VWAP
        │
        ▼
[Monitoring]        ← Deterministic (daily) + LLM (weekly narrative scan)
```

Two human checkpoints. Everything before and after them is automated. That's the architecture.

---

## What This Tells You About Build Priority

The org chart mapping makes the build order obvious — **automate the roles with the highest headcount and lowest judgment first:**

1. **Junior analyst workflows** (Phase 1) — screening, data ingestion, model population, filing extraction. This is 3–8 people's worth of work at a real fund.
2. **Risk manager** (Phase 1) — deterministic code, well-defined, high value.
3. **Execution / operations** (Phase 2) — broker API integration, straightforward.
4. **Senior analyst LLM assists** (Phase 2) — earnings analysis, red-team, memo assembly. These need more prompt engineering and validation.
5. **Dashboard / PM tooling** (Phase 3) — the interface you use daily to consume everything above.

The junior analyst role is where your $50–150/month in API costs replaces what a real fund pays $150–300K/year in salary for. That's the economics of this project.

