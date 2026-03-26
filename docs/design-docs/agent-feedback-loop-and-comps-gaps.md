# Agent Feedback Loop, 10-K Wiring, and Comps Similarity — Design Notes

_Session: 2026-03-14_

---

## 1. What was built — recommendations feedback loop

### Problem

After `--full` runs 9 agents and prints an IC memo, all agent findings were discarded. QoE found an EBIT haircut, accounting recast found lease liabilities needed reclassification, industry agent found sector growth was higher than the current model assumption — but none of it fed back into the DCF. The plumbing existed (`qoe_pending.yaml`, `valuation_overrides.yaml`) but required manual YAML editing and separate CLI invocations with no unified view.

### What was implemented

`src/stage_04_pipeline/recommendations.py` — unified module that:

- Collects from three agent outputs after a `--full` run: QoE, AccountingRecast, IndustryAgent
- Writes `config/agent_recommendations_{TICKER}.yaml` with pending/approved/rejected status per item
- Preserves PM decisions across re-runs (approved/rejected items are not reset to pending)
- `apply_approved_to_overrides()` merges approved items into `config/valuation_overrides.yaml` under `tickers.{TICKER}`
- `preview_with_approvals()` runs a shadow DCF with proposed overrides applied via `dataclasses.replace()` and returns bear/base/bull IV delta

CLI additions to `batch_runner.py`:
- `--full` now collects and writes recommendations after the IC memo
- `--review TICKER` — display pending items
- `--approve TICKER` — interactive approval with IV before/after table

Dashboard: `dashboard/app.py` now runs the full 9-agent pipeline (was 6) and has a `🔧 Recommendations` tab with per-agent grouping, what-if preview, and Apply button.

### Recommendation extraction logic

| Source | Field extracted | Condition |
|---|---|---|
| QoE `llm.dcf_ebit_override_pending` | `ebit_margin_start` | Only when haircut > 10% |
| AccountingRecast `override_candidates` | `lease_liabilities`, `non_operating_assets`, `minority_interest`, `preferred_equity`, `pension_deficit` | Non-null and delta > $1M |
| AccountingRecast `override_candidates.normalized_ebit` | `ebit_margin_start` | Kept as alternative to QoE if delta > 0.5pp |
| IndustryAgent `consensus_growth_near/mid`, `margin_benchmark` | `revenue_growth_near`, `revenue_growth_mid`, `ebit_margin_target` | Only if delta > 1pp vs current drivers |

---

## 2. How approved recommendations flow into the DCF

### Operating items

`ebit_margin_start`, `revenue_growth_near`, `revenue_growth_mid`, `ebit_margin_target` drive the **FCFF projection loop** in `professional_dcf.py`. Approval writes the value to `valuation_overrides.yaml` → `_apply_overrides()` sets it on the `ForecastDrivers` dataclass → every year's EBIT/NOPAT/FCFF is recalculated.

The bear/base/bull scenario multipliers (`margin_shift`) apply on top of whatever `ebit_margin_start` is now. A QoE haircut is therefore baked into all three scenarios before scenario scaling.

### Non-operating / EV bridge items

`lease_liabilities`, `non_operating_assets`, `minority_interest`, `preferred_equity`, `pension_deficit` do **not touch the FCFF projections**. They adjust the EV → equity bridge at the end:

```
enterprise_value_operations = pv_fcff_sum + pv_tv
enterprise_value_total      = enterprise_value_operations + non_operating_assets   # ADD
non_equity_claims           = net_debt + minority_interest + preferred_equity
                              + pension_deficit + lease_liabilities + options + converts
equity_value                = enterprise_value_total - non_equity_claims           # SUBTRACT
iv_per_share                = equity_value / shares_outstanding
```

Adding $2.3B in operating leases that were previously excluded drops equity value by $2.3B and reduces IV per share directly. FCFF numbers are unchanged.

### Excel wiring

`value_single_ticker()` reads `source_lineage` and writes every source into the output row:
- `ebit_margin_used`, `ebit_margin_source` → `"override_ticker"` after approval
- `lease_liabilities_used_mm`, `lease_liabilities_source` → `"override_ticker"` after approval

This flows through `export_ticker_json()` → `{TICKER}_latest.json` → Power Query → Excel. The Excel workbook always reflects the approved state on the next valuation run.

### Audit trail gap

`source_lineage` records `"override_ticker"` for both hand-typed overrides and agent-approved items. There is no field in `valuation_overrides.yaml` that records _which agent_ proposed the value or when it was approved. The `agent_recommendations_{TICKER}.yaml` file is the audit record — it has agent name, rationale, proposed value, and `generated_at` timestamp. These two files should be read together for a full audit.

---

## 3. 10-K reading — where it does and doesn't affect valuation

### What FilingsAgent actually does

Fetches EDGAR XBRL facts + 10-K text (MD&A + risk factors, max 25k chars). Produces `FilingsSummary`:

```python
FilingsSummary(
    revenue_cagr_3y,   # computed from XBRL series
    ebit_margin_avg,   # computed from XBRL series
    margin_trend,      # expanding | stable | contracting
    red_flags,         # list of text flags
    management_guidance,
    raw_summary        # 2-3 paragraph qualitative
)
```

### Where it goes

```
FilingsSummary
  → EarningsAgent     (raw_summary passed as context, no numeric extraction)
  → ValuationAgent    (passed as filings arg — used for LLM commentary only)
  → ThesisAgent       (IC memo narrative)
```

**FilingsSummary does not feed into the deterministic DCF.** `value_single_ticker()` calls `build_valuation_inputs()` which uses yfinance + CIQ snapshots only. The `ebit_margin_avg` and `revenue_cagr_3y` computed by FilingsAgent are displayed in the IC memo but are never compared against or used to override DCF inputs.

### The one exception — QoE agent

QoE fetches the 10-K **separately** and uses it for EBIT normalization. If haircut > 10%, it writes to `qoe_pending.yaml` which can flow into DCF via the approval mechanism. This is the only path where 10-K text reading affects a DCF number.

### Gap to close

The `ebit_margin_avg` and `revenue_cagr_3y` from FilingsAgent could be surfaced as additional data points in the recommendations tab — shown alongside the current model assumption so the PM can see whether the DCF is using a number consistent with what the 10-K implies. They shouldn't auto-override (FilingsAgent is LLM-derived, not deterministic) but they're useful cross-checks.

---

## 4. Comps — current mechanics and similarity gap

### What's implemented

Peers come from the CIQ Excel workbook, ingested into `ciq_comps_snapshot` in SQLite. `run_comps_model()` applies:

1. **Tukey IQR fence** outlier removal per metric (skipped if < 4 peers)
2. **Log-market-cap proximity weighting** for the base multiple:
   ```python
   weight = exp(-|log(peer_mktcap / target_mktcap)|)
   ```
   A peer 5× larger or smaller gets weight ~0.20 vs a same-size match at 1.0.
3. **Bear/bull = 25th/75th percentile** of IQR-cleaned set (no similarity weighting)
4. **Metric priority**: forward EBITDA → LTM EBITDA → forward EBIT → LTM EBIT → P/E

### The gap

There is no business description comparison. The CIQ workbook is the peer list — the code trusts it completely. A mega-cap hardware company in an IT-services comps set would receive roughly the same multiple-weighting as a true peer (penalised only by size difference, not by business model distance).

The `ciq_comps_snapshot` DB table stores only numeric metric keys. There is no `business_description` or `similarity_score` field per peer.

### Proposed fix — description-based similarity weighting

**Data source**: `yf.Ticker(ticker).info["longBusinessSummary"]` is available for all US-listed tickers without additional data subscriptions. This could augment or replace the manual business description from CIQ.

**Two implementation options**:

**Option A — LLM pairwise scoring** (no embedding infra):
- For each peer: feed target description + peer description into one LLM call
- Score on 4 dimensions: revenue model, margin profile, cyclicality, geographic exposure
- Output `similarity_score: 0.0–1.0` per peer
- One LLM call per peer set per ticker (cacheable weekly)

**Option B — Cosine similarity on embeddings** (scales better):
- Embed target + all peer descriptions (Anthropic or local model)
- Compute cosine distance, normalize to 0–1
- Fully deterministic once cached
- Better for large peer sets (20+ peers)

**Integration point**: The change is entirely inside `_similarity_weights()` in `comps_model.py`. Replace or blend the log-mktcap weight with `similarity_score`. Nothing downstream changes.

**Schema change needed**: Add `business_description` and optionally `similarity_score` columns to the CIQ comps snapshot ingestion pipeline. Or store them in a separate `peer_descriptions` table keyed on `(target_ticker, peer_ticker)`.

**Recommended build order**:
1. Add `yfinance` description fetching to `ciq_adapter.py` → `get_ciq_comps_detail()` returns description per peer
2. New function `score_peer_similarity(target_ticker, peers, descriptions)` in `comps_model.py`
3. Cache scores in SQLite with weekly expiry
4. Blend weights: `final_weight = 0.5 * size_weight + 0.5 * similarity_score`

Estimated scope: ~150 lines + one new DB table + one new LLM call per peer set per week.

---

## 5. Open items / next build candidates

| Item | Priority | Notes |
|---|---|---|
| FilingsAgent `ebit_margin_avg` surfaced in recommendations as cross-check | Medium | Read-only display, not an override source |
| Peer description similarity scoring | Medium | yfinance `longBusinessSummary` is free; LLM pairwise is simplest starting point |
| `source_lineage` annotation for agent-approved overrides | Low | Current `"override_ticker"` is ambiguous; could add `"agent_rec_approved"` source label |
| `--approve` should also run `--full` re-run option | Low | Currently shows IV delta from preview DCF; user could opt into a full pipeline re-run |
