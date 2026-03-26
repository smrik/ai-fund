# Quality of Earnings (QoE) Agent

## What It Does

The QoE Agent answers one question for the PM: **is the EBIT number in the DCF trustworthy?**

It runs two independent analyses — a deterministic signal layer that never involves an LLM, and an LLM judgment layer that reads the 10-K — and combines them into a single output package.

---

## Two-Layer Architecture

```
┌───────────────────────────────────────────────────────────┐
│  Layer 1: Deterministic Signals  (qoe_signals.py)         │
│  Six accounting signals computed from financial data.      │
│  No LLM. Auditable. Always runs.                          │
└──────────────────────────────────────────────────────────┬┘
                                                           │
                                                           ▼ signals + flag
┌──────────────────────────────────────────────────────────┐
│  Layer 2: LLM Judgment  (qoe_agent.py)                    │
│  Reads MD&A / Notes. Normalises EBIT. Explains signals.   │
│  Flags revenue recognition risk. Notes auditor changes.   │
│  Runs only when 10-K text is available.                   │
└───────────────────────────────────────────────────────────┘
```

The two layers are combined into a single output dict (see §4). The deterministic score always flows through. The LLM layer adds context and EBIT normalization when text is available; otherwise it degrades gracefully.

---

## Layer 1: Deterministic Signals

Six signals, all computed from data already in the pipeline (no new data sources needed).

### Signal 1 — Sloan Accruals Ratio

```
Accruals = (Net Income − Operating Cash Flow) / Revenue
```

**Why it matters:** High accruals mean reported earnings contain large non-cash components. Sloan (1996) showed high-accrual firms systematically underperform. Accruals above ~8–10% of revenue often reverse in subsequent periods.

**Thresholds are sector-adjusted** because some sectors (Technology, Healthcare) structurally carry higher stock-based compensation and intangible amortization:

| Sector | Amber | Red |
|---|---|---|
| Technology | 8% | 15% |
| Communication Services | 7% | 13% |
| Healthcare | 7% | 13% |
| Consumer Cyclical | 5% | 10% |
| Consumer Defensive | 4% | 8% |
| Industrials | 5% | 10% |
| Energy | 6% | 12% |
| _default | 5% | 10% |

### Signal 2 — Cash Conversion

```
Cash Conversion = Operating Cash Flow / EBITDA (TTM)
```

**Why it matters:** A company converting 90%+ of EBITDA to cash has high-quality earnings. Persistent conversion below 65% suggests working capital deterioration, aggressive revenue recognition, or hidden cash costs.

**Data source preference:** EBITDA from CIQ (operating income TTM + D&A TTM) takes precedence over yfinance `ebitda_ttm`. Using TTM handles seasonality.

**Thresholds (universal):**
- ≥ 85%: green
- 65–85%: amber
- < 65%: red

### Signal 3, 4, 5 — NWC Drift (DSO, DIO, DPO)

```
DSO Drift = Current DSO − DSO Baseline
DIO Drift = Current DIO − DIO Baseline
DPO Drift = Current DPO − DPO Baseline
```

Drift measures deterioration from the company's own historical norm, not an absolute level.

**Baseline selection logic (per PM decision 2026-03-08):**

| CIQ history periods available | Baseline used | Source tag |
|---|---|---|
| 2 or more | Average of periods[1:] (older periods) | `"ciq_history"` |
| Exactly 1 | Sector default | `"sector_default"` |
| 0 | Signal marked unavailable | `"unavailable"` |

Unavailable signals are excluded from the composite score — they do not drag the score down.

**Drift thresholds (universal, in days):**
- < 5 days: green
- 5–15 days: amber
- > 15 days: red

For DPO: a high drift (payables stretching far above baseline) is flagged the same way as DSO/DIO drift — both indicate potential stress.

### Signal 6 — Capex / D&A Ratio

```
Capex/DA = Capital Expenditures / Depreciation & Amortisation
```

**Why it matters:** A ratio below 1.0 means a company is spending less on capex than it is depreciating. Sustained under-investment degrades the asset base and is a leading indicator of future revenue pressure.

**Thresholds:**
- ≥ 1.0: green
- 0.7–1.0: amber
- < 0.7: red

### Composite Score (1–5)

| Signals | Score | Flag |
|---|---|---|
| 0 reds, 0 ambers | 5 | green |
| 0 reds, 1 amber | 4 | green |
| 0 reds, 2+ ambers OR 1 red | 3 | amber |
| 2 reds OR 4+ ambers | 2 | red |
| 3+ reds | 1 | red |

Unavailable signals are excluded from the red/amber counts.

---

## Layer 2: LLM Judgment

Runs when 10-K text is available (from EDGAR or pre-supplied). Uses the deterministic signal results as structured context passed into the prompt.

### What the LLM Does

1. **EBIT normalization** — identifies one-time or non-core items (restructuring, impairments, gains on asset sales, litigation settlements, acquisition costs) and adjusts reported EBIT to a normalized figure. Each adjustment has `item`, `amount`, `direction` (+/−), and `rationale`.

2. **Signal explanations** — for each deterministic signal flagged amber or red, finds management's explanation in the MD&A and assesses whether it is credible (e.g., "DSO increase due to seasonal timing in government contracts — credible" vs "vague explanation, no quantification").

3. **Revenue recognition flags** — identifies specific concerns visible in the notes (e.g., "Unbilled AR growing 25% vs revenue +8%", "Channel mix shift to distributor with right of return").

4. **Auditor flags** — notes going concern language, material weakness disclosures, or auditor changes.

5. **PM summary** — 2–3 sentences in plain English summarizing overall earnings quality for the PM.

### Fallback Behaviour

If no 10-K text is available (EDGAR fetch returns nothing, or no text was pre-supplied):
- `llm_available = false`
- `normalized_ebit = reported_ebit` (no adjustment)
- `llm_confidence = "low"`
- `pm_summary` explains that only deterministic signals were available
- The deterministic score still flows through normally

If the LLM returns unparseable output:
- Same fallback as above
- `llm_available` reflects whether text was provided (the LLM attempted but failed)

---

## DCF Override Gate

The QoE agent **never auto-updates the DCF.** Normalized EBIT is advisory only.

```
If |normalized_ebit − reported_ebit| / |reported_ebit| > 10%:
    dcf_ebit_override_pending = true
```

When `dcf_ebit_override_pending = true`, the PM must explicitly review and approve the adjusted EBIT in `config/valuation_overrides.yaml` before the DCF uses it. This prevents automated LLM output from silently changing valuation inputs.

**Threshold rationale:** A <10% EBIT adjustment is within normal measurement noise and doesn't materially change intrinsic value. Adjustments >10% represent a genuine analytical disagreement that requires human judgment.

---

## Output Schema

```python
{
    "ticker": str,                    # e.g. "HALO"
    "qoe_score": int,                 # 1–5 composite
    "qoe_flag": str,                  # "green" | "amber" | "red"

    "deterministic": {
        "sector": str,
        "signal_scores": {
            "accruals": str,          # "green" | "amber" | "red" | "unavailable"
            "cash_conversion": str,
            "dso": str,
            "dio": str,
            "dpo": str,
            "capex_da": str,
        },
        "sloan_accruals_ratio": float | None,
        "cash_conversion": float | None,
        "dso_current": float | None,
        "dso_drift": float | None,
        "dso_baseline": float | None,
        "dso_baseline_source": str,   # "ciq_history" | "sector_default" | "unavailable"
        # ... same for dio, dpo
        "capex_da_ratio": float | None,
        "accruals_thresholds": {"amber": float, "red": float},
    },

    "llm": {
        "llm_available": bool,
        "normalized_ebit": float,
        "reported_ebit": float,
        "ebit_haircut_pct": float | None,      # (normalized − reported) / |reported| × 100
        "dcf_ebit_override_pending": bool,      # true when |haircut| > 10%
        "ebit_adjustments": [
            {"item": str, "amount": float, "direction": "+" | "−", "rationale": str}
        ],
        "signal_explanations": {
            "accruals": str | None,
            "cash_conversion": str | None,
            "dso": str | None,
            "dio": str | None,
            "dpo": str | None,
            "capex_da": str | None,
        },
        "revenue_recognition_flags": [str],
        "auditor_flags": [str],
        "narrative_credibility": "high" | "medium" | "low" | None,
        "llm_confidence": "high" | "medium" | "low",
        "data_source": str,           # "provided_10k_text" | "sec_edgar_10k" | "*_fallback"
    },

    "pm_summary": str,                # 2–3 sentence plain-English summary
}
```

---

## How to Run

```python
from src.stage_03_judgment.qoe_agent import QoEAgent

agent = QoEAgent()

# Standard run — fetches 10-K from EDGAR automatically
result = agent.analyze("HALO", reported_ebit=450_000_000.0)

# Pre-supply 10-K text (e.g., already fetched as part of a batch)
result = agent.analyze("HALO", reported_ebit=450_000_000.0, filing_text=text)

# Key fields to check
print(result["qoe_score"])                         # 1–5
print(result["qoe_flag"])                          # green/amber/red
print(result["llm"]["dcf_ebit_override_pending"])  # True = needs PM review
print(result["llm"]["ebit_haircut_pct"])           # % adjustment
print(result["pm_summary"])                        # plain English
```

---

## PM Decision Protocol

When `dcf_ebit_override_pending = true`:

1. Read `ebit_adjustments` in the output — each item has a rationale
2. Read `signal_explanations` — are the LLM's explanations for flagged signals credible?
3. Check `narrative_credibility` and `llm_confidence`
4. If you agree with the normalization, add to `config/valuation_overrides.yaml`:
   ```yaml
   HALO:
     normalized_ebit: 495000000   # your approved figure
     normalized_ebit_date: "2026-03-08"
     normalized_ebit_note: "Exclude $45M restructuring per QoE agent review"
   ```
5. Re-run the DCF — it will now use your approved figure

If you disagree with the LLM's normalization, do nothing. The DCF uses reported EBIT.
