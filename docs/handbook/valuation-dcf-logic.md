# Valuation and DCF Logic

Finance-first methodology now lives in [`docs/valuation/`](../valuation/index.md).
Use this handbook page for the current implementation explanation of how intrinsic value is computed in code.

This document is the source-of-truth explanation for how intrinsic value is computed in code.

Key modules:
- `src/stage_02_valuation/input_assembler.py` — assembles all DCF assumptions
- `src/stage_02_valuation/professional_dcf.py` — runs the DCF and scenarios
- `src/stage_02_valuation/wacc.py` — computes cost of capital
- `src/stage_02_valuation/batch_runner.py` — runs the full universe
- `src/stage_02_valuation/story_drivers.py` — loads narrative override overrides

---

## 1. Assumption Assembly (`input_assembler.py`)

Before any numbers are crunched, `assemble_inputs(ticker)` resolves every DCF driver from the best available source. The result is a `ForecastDrivers` dataclass plus a `source_lineage` dict that records where each number came from.

### 1.1 Revenue Growth

Near-term growth priority chain (first non-null wins):

1. **CIQ consensus** — `(revenue_fy1 / revenue_ttm) - 1`. Uses sell-side FY1 estimates stored in the CIQ snapshot. Source: `"ciq_consensus"`.
2. **CIQ 3yr CAGR** — computed from `ciq_long_form` historical revenues. Source: `"ciq_3yr_cagr"`.
3. **yfinance 3yr CAGR** — computed from `get_historical_financials()`. Source: `"yfinance_3yr_cagr"`.
4. **yfinance TTM YoY** — single year growth from TTM snapshot. Source: `"yfinance_ttm_yoy"`.
5. **Sector default** — from `SECTOR_DEFAULTS[sector]["revenue_growth_near"]`. Source: `"default"`.

Mid-term growth = near-term × `growth_fade_ratio` (sector-specific; see §1.6).

Terminal growth is set per sector from `SECTOR_DEFAULTS[sector]["terminal_growth"]` (e.g., Technology 3.5%, Utilities 2.5%).

Future hardening:
- the deterministic assembler currently uses one CIQ/yfinance/default precedence chain
- over time, the preferred anchor should come from the dedicated historical-analysis layer, including rolling growth windows such as `t-5 to t-2`, `t-4 to t-1`, and `t-3 to t`, rather than relying mainly on a single 3-year view

### 1.2 EBIT Margin

Priority chain:
1. CIQ TTM operating income / CIQ TTM revenue
2. yfinance TTM operating income / yfinance TTM revenue
3. Sector default

Margin converges from `ebit_margin_start` to `ebit_margin_target` over years 1–10 using a linear path that allows both expansion and compression.

Known limitation:
- today the model gives strong weight to CIQ or yfinance snapshot / average values
- the intended direction is for a broader historical-analysis layer to calculate multi-period margin evidence directly, with CIQ acting more as a control and validation source than as the only preferred anchor

### 1.3 Exit Multiple

The DCF terminal value uses an exit multiple on terminal-year EBIT or EBITDA. Priority:

**For EV/EBITDA exit:**
1. CIQ comps forward median (`peer_median_tev_ebitda_fwd` — based on `tev_ebitda_cy_1`)
2. CIQ comps LTM median (`peer_median_tev_ebitda_ltm`)
3. Sector default

**For EV/EBIT exit:**
1. CIQ comps forward EBIT median (`peer_median_tev_ebit_fwd`)
2. CIQ comps LTM EBIT median (`peer_median_tev_ebit_ltm`)
3. Sector default

Forward multiples are preferred because the terminal year is itself forward-looking.

### 1.4 Working Capital Drivers (DSO, DIO, DPO)

NWC is modelled as `delta_NWC / Revenue` using DSO, DIO, DPO day-counts to derive the percentage.

**Start values** (current period):
1. CIQ snapshot → yfinance → sector default

**Target values** (year 10 convergence):
- When company data is available: `0.70 × sector_default + 0.30 × company_start`
  - Source: `"ciq_blend"` or `"yfinance_blend"`
- When only sector default is known: pure sector default
  - Source: `"default"`

This blend reflects partial mean reversion — a company with structurally elevated DSO will not fully converge to sector average within 10 years.

### 1.5 Tax Rate

`tax_target = bounded(company_ETR, min=15%, max=30%, fallback=23%)`

The company's own effective tax rate becomes the convergence target (bounded to a plausible range), rather than a universal 23%.

### 1.6 Sector-Specific Parameters

All per-sector defaults live in `SECTOR_DEFAULTS` in `input_assembler.py`:

| Sector | Growth fade ratio | Terminal growth | Notes |
|---|---|---|---|
| Technology | 0.70 | 3.5% | High fade retention; reinvestment-heavy |
| Communication Services | 0.65 | 3.0% | |
| Healthcare | 0.65 | 3.0% | |
| Consumer Cyclical | 0.60 | 2.5% | |
| Consumer Defensive | 0.55 | 2.5% | Mature, slow fade |
| Industrials | 0.55 | 2.5% | |
| Energy | 0.50 | 2.0% | Commodity-linked; aggressive fade |
| Basic Materials | 0.50 | 2.0% | |
| Utilities | 0.50 | 2.5% | Regulated; growth bounded |
| _default | 0.65 | 3.0% | |

*Growth fade ratio:* `growth_mid = growth_near × fade_ratio`. A ratio of 0.70 means mid-term growth fades to 70% of near-term growth.

### 1.7 Source Lineage Audit

Every assembled set of inputs includes a `source_lineage` dict, e.g.:
```json
{
  "revenue_growth_near": "ciq_consensus",
  "ebit_margin": "ciq_ttm",
  "exit_multiple": "ciq_comps_tev_ebitda_fwd",
  "dso_start": "ciq",
  "dso_target": "ciq_blend",
  "tax_rate_target": "company_etr",
  "revenue_growth_terminal": "default"
}
```
Review this before taking any valuation at face value. `"default"` entries mean no company-specific data was found.

---

## 2. DCF Model (`professional_dcf.py`)

### 2.1 Explicit Forecast (Years 1–10)

Revenue:
```
Revenue_t = Revenue_(t-1) × (1 + g_t)
```
where g_t is near growth for years 1–5, mid growth for years 6–10.

Operating items per year:
```
EBIT_t       = Revenue_t × EBIT_Margin_t
NOPAT_t      = EBIT_t × (1 − Tax_t)
D&A_t        = Revenue_t × DA_pct
Capex_t      = Revenue_t × Capex_pct
ΔNW_t        = Revenue_t × NWC_pct_t
```

FCFF:
```
FCFF_t = NOPAT_t + D&A_t − Capex_t − ΔNWC_t
```

FCFE branch (when enabled):
```
FCFE_t = FCFF_t − Interest_t × (1 − Tax_t) + Net_Borrowing_t
```

### 2.2 Terminal Value

Exit multiple on terminal-year EBIT or EBITDA:
```
TV_10   = EBIT_10 × Exit_Multiple  (or EBITDA_10 × Exit_Multiple)
PV_TV   = TV_10 / (1 + WACC)^10
```

### 2.3 Discounting

```
PV_FCF   = Σ FCFF_t / (1 + WACC)^t  for t = 1..10
EV       = PV_FCF + PV_TV
```

EV-to-equity bridge:
```
Equity_Value = EV − Net_Debt − Minority_Interest + Cash_and_Equivalents
IV_per_Share = Equity_Value / Shares_Outstanding
```

### 2.4 Economic Profit Cross-Check

The model cross-checks DCF equity value against an Economic Profit (residual income) model:
```
EP_t  = NOPAT_t − WACC × Invested_Capital_t
EP_PV = Σ EP_t / (1 + WACC)^t
```
Large divergence between DCF and EP values flags aggressive margin or reinvestment assumptions.

### 2.5 Terminal Value Diagnostic

`tv_pct_of_ev` = terminal value as % of total EV. Values above 75% (`tv_high_flag = True`) warrant scrutiny — the valuation is heavily dependent on exit multiple and terminal assumptions.

---

## 3. Scenario Engine (`bear / base / bull`)

`run_scenario_dcf()` generates three scenarios by perturbing base assumptions:

| Parameter | Bear | Base | Bull |
|---|---|---|---|
| Near growth | × 0.6 | × 1.0 | × 1.4 |
| Mid growth | × 0.6 | × 1.0 | × 1.3 |
| EBIT margin | × 0.75 | × 1.0 | × 1.15 |
| Capex pct | × 1.2 | × 1.0 | × 0.9 |
| WACC delta | +2% | 0 | −1% |
| Exit multiple | × 0.7 | × 1.0 | × 1.3 |

Outputs: `iv_bear`, `iv_base`, `iv_bull` per share.

Future hardening:
- the current scenario engine is intentionally simple and deterministic
- it should eventually become more company-aware by reflecting:
  - size and maturity
  - past growth profile
  - business-cycle position
  - industry analysis
  - historical-analysis context
  - operating leverage and funding constraints

---

## 4. WACC Construction (`wacc.py`)

### 4.1 Input Parameters

Rf and ERP are loaded from `config/config.yaml`:
```yaml
wacc_params:
  risk_free_rate: 0.045      # 10Y US Treasury — update annually
  equity_risk_premium: 0.050 # Damodaran — update annually
```

### 4.2 Beta Unlevering (Hamada)

```
β_unlevered = β_levered / (1 + (1 − tax) × D/E)
```
Peer unlevered betas are filtered to a sanity range and the median is used.

### 4.3 Beta Relevering to Target Structure

```
β_relevered = β_unlevered_median × (1 + (1 − tax) × D/E_target)
```

### 4.4 Cost of Equity

```
Ke = Rf + β_relevered × ERP + size_premium
```

Size premia (Duff & Phelps buckets):
- Micro-cap (<$500M): +2.5%
- Small-cap ($500M–$2B): +1.5%
- Mid-cap ($2B–$10B): +0.5%
- Large-cap (>$10B): 0%

### 4.5 Final WACC

```
Kd_after_tax = cost_of_debt × (1 − tax)
WACC = Ke × E/(D+E) + Kd_after_tax × D/(D+E)
```

---

## 5. Reverse DCF (Implied Growth)

`reverse_dcf_professional()` in `professional_dcf.py` solves for the near-term growth rate such that the base-case DCF equals the current market price. Uses binary search over [−5%, +50%].

Interpretation:
- High implied growth → market embeds aggressive expectations; need strong conviction to be long
- Low implied growth → muted expectations; easier to be right

---

## 6. Valuation Override Gate

The PM can override any assembled assumption via `config/valuation_overrides.yaml`. This is the only way LLM analysis (from the QoE agent) flows into the DCF — via explicit PM approval of a `normalized_ebit` override.

See `docs/handbook/qoe-agent.md` for the full override workflow.

---

## 7. DCF Review Checklist (Per Name)

1. Check `source_lineage` — are growth and margin from actual data or sector defaults?
2. Does base-case upside survive the bear-case stress?
3. Is WACC coherent with the company's risk profile and size?
4. Is `tv_pct_of_ev` below 75%?
5. Is implied growth (reverse DCF) realistic versus business reality?
6. Is there a QoE override pending? If so, review `dcf_ebit_override_pending` in the QoE output.

---

## 8. Known Modeling Limits

Deliberately excluded from the deterministic core to maintain auditability:
- Multi-factor macro regime discounting
- Dynamic buyback / share count paths
- COGS-based DIO/DPO calculation (requires COGS series; current approach uses revenue-based ratios internally consistently)
- FCFF/FCFE interest contamination detection
- Peer beta levering (currently uses self-beta; peer betas deferred until CIQ comps provide tickers)
