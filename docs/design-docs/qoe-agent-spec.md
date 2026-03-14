# Quality of Earnings Agent — Design Specification

**Date:** 2026-03-08
**Status:** Pending finance review before implementation
**Audience:** Finance/PM review (not engineering)

---

## 1. Purpose

The QoE agent answers one question: **are reported earnings real?**

For a long/short fund, this matters asymmetrically:
- **Longs:** Confirm earnings are cash-backed before sizing up
- **Shorts:** Catch earnings inflation before the market does — the biggest alpha source in QoE

The agent operates in two layers:
1. **Deterministic** — calculate every measurable signal from numbers already in the pipeline (no LLM, fully auditable)
2. **LLM judgment** — read the MD&A/10-K footnotes and score management's explanation of the signals

---

## 2. What the Agent Receives as Input

All inputs come from data already computed in the pipeline. No new data fetches required.

| Input | Source | Already in pipeline? |
|---|---|---|
| Revenue (TTM) | CIQ / yfinance | ✓ |
| Operating Income / EBIT (TTM) | CIQ / yfinance | ✓ |
| CFFO — Cash Flow from Operations | yfinance historical | ✓ |
| Net Income (TTM) | yfinance historical | ✓ |
| EBITDA (TTM) | CIQ / yfinance | ✓ |
| D&A (TTM) | CIQ / yfinance | ✓ |
| Capex (TTM) | CIQ / yfinance | ✓ |
| DSO — Days Sales Outstanding | CIQ / yfinance (via input_assembler) | ✓ |
| DIO — Days Inventory Outstanding | CIQ / yfinance | ✓ |
| DPO — Days Payables Outstanding | CIQ / yfinance | ✓ |
| DSO 3-year history | yfinance historical | ✓ |
| Total Assets | yfinance | ✓ |
| 10-K filing text (MD&A + Notes) | SEC EDGAR | ✓ via edgar_client |

---

## 3. Deterministic Signal Layer (No LLM)

These are computed before the LLM sees anything. Each signal has a clear formula and a threshold that triggers a flag.

### 3.1 Sloan Accruals Ratio

**What it is:** The gap between accounting earnings and cash earnings. High accruals = earnings are outrunning cash generation. Sloan (1996) showed this predicts future earnings reversals.

```
Accruals = Net Income − CFFO − CFFI (investing cash flow)
Sloan Accruals Ratio = Accruals / Average Total Assets

Simplified (operating only):
Operating Accruals Ratio = (Net Income − CFFO) / Revenue
```

**Interpretation:**
- < 0%: Cash earnings exceed accounting earnings → high quality
- 0–5%: Normal range
- 5–10%: Elevated, watch
- > 10%: **Red flag** — earnings inflated relative to cash

**Why it matters as a short signal:** Companies with persistent high accruals subsequently underperform by ~10% per year (Sloan, 1996; replicated extensively). This is one of the most durable quant factors in accounting.

---

### 3.2 Cash Conversion — CFFO / EBITDA

**What it is:** What fraction of EBITDA actually becomes operating cash flow after working capital and other items.

```
Cash Conversion Ratio = CFFO / EBITDA
```

**Interpretation:**
- > 90%: Excellent — EBITDA is nearly all cash
- 70–90%: Normal
- 50–70%: Needs explanation (working capital drag, deferred revenue unwind, etc.)
- < 50%: **Red flag** — significant gap between reported profit and cash

**Short signal:** Management guides to "EBITDA growth" but CFFO / EBITDA is declining — earnings quality is eroding while the headline number looks good.

---

### 3.3 DSO Drift

**What it is:** Is the company collecting receivables faster or slower than historically? Rising DSO relative to history means revenue may be pulled forward (recognizing sales before cash is collected).

```
DSO Drift = Current DSO − 3-Year Average DSO
DSO Drift % = Drift / 3-Year Average DSO
```

**Interpretation:**
- < +5 days: Normal
- +5 to +15 days: Watch — ask management
- > +15 days OR > +20% relative: **Red flag** — potential revenue pull-forward or collection deterioration

**Short signal:** Revenue growing strongly but DSO rising — classic pattern before an earnings miss. Often appears 1–2 quarters before management acknowledges the problem.

---

### 3.4 Inventory Build (DIO Drift)

**What it is:** Is inventory growing faster than revenue? That would signal either demand weakness (goods aren't selling) or cost inflation.

```
DIO Drift = Current DIO − 3-Year Average DIO
Revenue Growth vs Inventory Growth Gap = Δ Revenue (%) − Δ Inventory (%)
```

**Interpretation:**
- < +5 days drift: Normal
- +5 to +15 days: Elevated, cross-check with management commentary
- > +15 days OR inventory growing >2x revenue growth: **Red flag**

**Why it matters for longs too:** High DIO with stable DSO = company is building safety stock or capacity for growth → bullish if intentional. Context from the LLM layer matters here.

---

### 3.5 DPO Stretch

**What it is:** Is the company paying suppliers slower than historically? Rising DPO boosts short-term CFFO artificially — it's borrowed cash from suppliers, not operational improvement.

```
DPO Drift = Current DPO − 3-Year Average DPO
```

**Interpretation:**
- < +5 days: Normal
- +5 to +15 days: Watch
- > +15 days: **Amber flag** — CFFO inflated by supplier squeeze; not sustainable

**Important nuance:** Rising DPO in isolation is common and sometimes benign (better purchasing terms, scale). It only becomes a red flag when combined with deteriorating DSO or falling CFFO/EBITDA.

---

### 3.6 Capex vs D&A

**What it is:** D&A represents the annual consumption of existing assets. Capex below D&A for multiple years means the company is not reinvesting enough to maintain its asset base.

```
Capex / D&A Ratio = Capex (TTM) / D&A (TTM)
```

**Interpretation:**
- > 1.5x: Growth investment — fine for growth companies
- 1.0–1.5x: Maintenance mode — typical for mature businesses
- 0.7–1.0x: Under-investing — watch for future margin pressure or asset write-downs
- < 0.7x: **Red flag** — especially combined with rising margins (inflating margins by cutting investment)

**Short signal:** Company shows margin expansion but Capex/D&A < 0.8 for 3 years → earnings are temporarily elevated; assets degrading.

---

### 3.7 Composite QoE Score (Deterministic)

All signals are scored individually, then combined into a single score for the PM:

| Signal | Green | Amber | Red |
|---|---|---|---|
| Sloan Accruals Ratio | < 5% | 5–10% | > 10% |
| Cash Conversion (CFFO/EBITDA) | > 90% | 70–90% | < 70% |
| DSO Drift | < +5d | +5 to +15d | > +15d |
| DIO Drift | < +5d | +5 to +15d | > +15d |
| DPO Stretch | < +5d | +5 to +15d | > +15d |
| Capex / D&A | > 1.0x | 0.7–1.0x | < 0.7x |

**Composite score:**
- 0 reds, ≤ 1 amber → QoE Score 4–5 (High quality)
- 1 red or 2–3 ambers → QoE Score 3 (Moderate)
- 2 reds or 4+ ambers → QoE Score 2 (Elevated concern)
- 3+ reds → QoE Score 1 (Short-side flag)

---

## 4. LLM Judgment Layer

The LLM receives the deterministic scores **and** the MD&A / footnotes text. It does NOT compute numbers — it reads management's explanation of the signals.

### 4.1 What the LLM is asked to do

1. **EBIT Normalization** (already in the current agent): identify and remove non-recurring items (restructuring, impairments, gains on asset sales, litigation settlements, acquisition costs). Compute adjusted/normalized EBIT.

2. **Explain flagged signals**: For each amber or red signal from the deterministic layer, does management's disclosure explain it?
   - DSO rising → did management disclose a timing issue with a large customer? A new billing cycle change?
   - DIO rising → is the company deliberately building safety stock ahead of a product launch?
   - Capex below D&A → has the company been selling/leasing assets, or deliberately managing capex?

3. **Revenue recognition risk**: Does MD&A mention:
   - Changes in revenue recognition policy?
   - Increased use of percentage-of-completion or multi-element arrangements?
   - Channel stuffing indicators (high returns, extended payment terms to distributors)?
   - Unbilled receivables growing as a share of total AR?

4. **Auditor signals** (secondary check):
   - Going concern language
   - Material weakness disclosures
   - Auditor change within last 2 years

5. **Overall narrative credibility**: Does management's explanation of weak cash conversion or rising DSO hold up? Or is it vague/deflecting?

### 4.2 LLM Output Schema

```json
{
  "normalized_ebit": <float>,
  "reported_ebit": <float>,
  "ebit_adjustments": [
    {
      "item": <string>,
      "amount": <float>,
      "direction": "+" or "-",
      "rationale": <string>
    }
  ],
  "signal_explanations": {
    "dso_drift": <string | null>,
    "dio_drift": <string | null>,
    "dpo_stretch": <string | null>,
    "cash_conversion": <string | null>,
    "capex_da": <string | null>
  },
  "revenue_recognition_flags": [<string>],
  "auditor_flags": [<string>],
  "narrative_credibility": "high" | "medium" | "low",
  "confidence": "high" | "medium" | "low",
  "data_source": <string>
}
```

---

## 5. Combined Output to the Pipeline

After both layers complete, the agent produces a single QoE summary:

```json
{
  "ticker": "XYZ",
  "qoe_score": 1-5,
  "qoe_flag": "green" | "amber" | "red",

  "deterministic": {
    "sloan_accruals_ratio": 0.08,
    "cash_conversion": 0.72,
    "dso_current": 62.0,
    "dso_3yr_avg": 47.0,
    "dso_drift": 15.0,
    "dio_drift": 8.0,
    "dpo_drift": 3.0,
    "capex_da_ratio": 0.85,
    "signal_scores": {
      "accruals": "red",
      "cash_conversion": "amber",
      "dso": "red",
      "dio": "amber",
      "dpo": "green",
      "capex_da": "amber"
    }
  },

  "llm": {
    "normalized_ebit": 450.0,
    "reported_ebit": 520.0,
    "ebit_haircut_pct": -13.5,
    "ebit_adjustments": [...],
    "revenue_recognition_flags": ["unbilled AR growing 30% vs revenue +8%"],
    "auditor_flags": [],
    "narrative_credibility": "low",
    "confidence": "medium"
  },

  "pm_summary": "3 signals flagged (2 red, 2 amber). DSO up 15 days with no credible management explanation. Accruals ratio at 8% — earnings are running ahead of cash. Normalized EBIT $450M vs $520M reported (-14%). Short-side alert."
}
```

The `pm_summary` is a 2-3 sentence plain-English synthesis written by the LLM specifically for the PM.

---

## 6. How This Feeds the Broader Pipeline

```
Deterministic pipeline (DCF/WACC)
        │
        ▼
QoE Agent
        │
        ├─── normalized_ebit → replaces reported_ebit in DCF margin calculation
        ├─── qoe_score → gates position sizing in risk agent
        │      (score 1-2: halve position size; score 4-5: no discount)
        ├─── revenue_recognition_flags → fed to Thesis Agent
        └─── pm_summary → included in IC memo
```

Key integration points:
- **DCF**: Normalized EBIT is flagged and surfaced in the IC memo. DCF does NOT re-run automatically — PM approves via `valuation_overrides.yaml` if the haircut is > 10%.
- **Position sizing**: QoE score 1–2 escalates to PM via IC memo flag. No automatic sizing change.
- **Short thesis**: `qoe_flag = "red"` promotes to short-side watchlist for Thesis Agent review.
- **LLM unavailable**: Deterministic signals still flow. IC memo notes missing LLM layer prominently.

---

## 7. What This Spec Does NOT Cover (Deferred)

- **Segment-level QoE**: Which segments are driving margin improvement? Is the growing segment the one with good or bad QoE? Requires segment data not currently in pipeline.
- **Tax rate quality**: Effective tax rate below statutory for sustained periods (deferred tax asset build, uncertain tax positions). Deferred — needs 10-K Notes extraction.
- **Off-balance-sheet obligations**: Operating leases, contingent liabilities, pension underfunding. ROIC/valuation already adjusts for these mechanically; narrative flagging deferred.
- **Pension accounting quality**: Deferred.
- **Earnings guidance track record**: Systematic above/below history requires time-series of estimates vs actuals. Deferred to when consensus data matures.

---

## 8. PM Design Decisions — Confirmed 2026-03-08

| # | Question | Decision |
|---|---|---|
| 1 | Sloan accruals threshold | **Sector-adjusted** — thresholds calibrated per sector, not universal |
| 2 | Cash conversion threshold | **Seasonality-adjusted** — annualised TTM CFFO/EBITDA, not point-in-time quarter |
| 3 | DSO baseline data source | **CIQ historical data** — use CIQ 3-year DSO where available; do not rely on yfinance derivation |
| 4 | EBIT normalization → DCF | **PM approval gate** — normalized EBIT is surfaced as a flag; does not auto-override DCF |
| 5 | QoE score 1–2 impact | **Escalate to PM** — no automatic sizing change; flag is surfaced in IC memo for PM decision |
| 6 | Low LLM confidence | **Deterministic score flows** — pipeline unaffected; `llm_confidence: "low"` noted in output with `llm_available: false` |

---

## 9. Revised Signal Thresholds (Post PM Review)

### 9.1 Sector-Adjusted Accruals Thresholds

Accruals are elevated in sectors with high stock comp (Tech) or lumpy contract revenue (Healthcare, Industrials). Thresholds adjusted:

| Sector | Green | Amber | Red |
|---|---|---|---|
| Technology | < 8% | 8–15% | > 15% |
| Communication Services | < 7% | 7–13% | > 13% |
| Healthcare | < 7% | 7–13% | > 13% |
| Consumer Cyclical | < 5% | 5–10% | > 10% |
| Consumer Defensive | < 4% | 4–8% | > 8% |
| Industrials | < 5% | 5–10% | > 10% |
| Energy | < 6% | 6–12% | > 12% |
| Basic Materials | < 5% | 5–10% | > 10% |
| _default | < 5% | 5–10% | > 10% |

Rationale: Tech companies have large non-cash stock comp charges that depress CFFO relative to Net Income, structurally elevating the accruals ratio. Using a tighter threshold for Tech would produce false reds.

### 9.2 Seasonality-Adjusted Cash Conversion

Use TTM (trailing twelve months) CFFO and EBITDA — not quarterly — to neutralise seasonality. Thresholds remain:

| All sectors | Green | Amber | Red |
|---|---|---|---|
| CFFO / EBITDA (TTM) | > 85% | 65–85% | < 65% |

Note: The 70% midpoint from the draft is tightened slightly (green threshold raised to 85%) to be more discriminating. Retailers with well-understood seasonal patterns are evaluated on TTM, so the seasonality issue is addressed at the measurement level, not the threshold level.

### 9.3 DSO Baseline — CIQ Only

DSO baseline comes from CIQ historical data (3-year average from `ciq_long_form` or snapshot). If CIQ does not have 3-year history:
- Fall back to a single-year CIQ DSO — compare to sector default DSO from `SECTOR_DEFAULTS`
- If no CIQ data at all — DSO signal is marked `"unavailable"`, does not contribute to composite score
- Never use yfinance-derived DSO as baseline (too noisy)

### 9.4 Output Field for LLM Unavailability

When 10-K text cannot be retrieved (edgar_client returns None or empty):
```json
{
  "llm_available": false,
  "llm_confidence": "low",
  "normalized_ebit": null,
  "ebit_adjustments": [],
  "signal_explanations": {},
  "revenue_recognition_flags": [],
  "auditor_flags": [],
  "narrative_credibility": null,
  "pm_summary": "Deterministic signals only — no 10-K text available for LLM review. Scores reflect quantitative data; management narrative not assessed."
}
```

The deterministic `qoe_score` and all signal flags still populate normally. The IC memo notes `"LLM layer unavailable"` prominently.

### 9.5 EBIT Normalization — PM Approval Gate

When `|normalized_ebit - reported_ebit| / reported_ebit > 10%`:
- The adjustment is surfaced in the IC memo with full itemised adjustments
- `dcf_ebit_override_pending: true` is set in output
- The DCF continues to run on reported EBIT until PM explicitly approves the override
- PM approval is recorded as a manual entry in `valuation_overrides.yaml` under the ticker

This means the QoE agent never silently changes the valuation model.
