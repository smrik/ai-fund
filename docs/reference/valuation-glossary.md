# Valuation Glossary

This glossary maps deterministic Stage 02 valuation fields to finance meaning.

## 1. ForecastDrivers

| Field | Meaning |
|---|---|
| `revenue_base` | Starting revenue for the projection engine. |
| `revenue_growth_near` / `revenue_growth_mid` / `revenue_growth_terminal` | Near, fade, and terminal growth anchors. |
| `ebit_margin_start` / `ebit_margin_target` | Margin convergence path inputs. |
| `tax_rate_start` / `tax_rate_target` | Tax path inputs. |
| `capex_pct_*`, `da_pct_*` | Reinvestment intensity inputs. |
| `dso_*`, `dio_*`, `dpo_*` | Working-capital driver inputs (days-based). |
| `wacc` | Discount rate for FCFF valuation. |
| `cost_of_equity` | Discount rate for FCFE branch (if missing, deterministic fallback from WACC). |
| `exit_metric`, `exit_multiple` | Exit terminal method denominator and multiple. |
| `terminal_blend_gordon_weight`, `terminal_blend_exit_weight` | Terminal blending policy (default 60/40). |
| `invested_capital_start` | Starting invested capital for ROIC/EP diagnostics. |
| `ronic_terminal` | Terminal return on new invested capital for value-driver terminal FCFF. |
| `non_operating_assets` | Added to operations EV in EV->Equity bridge. |
| `net_debt`, `minority_interest`, `preferred_equity`, `pension_deficit`, `lease_liabilities`, `options_value`, `convertibles_value` | Non-equity claims deducted in EV->Equity bridge. |
| `shares_outstanding` | Per-share denominator. |

## 2. ProjectionYear

| Field | Meaning |
|---|---|
| `revenue`, `growth_rate` | Revenue path by year. |
| `ebit`, `nopat` | Operating profit path. |
| `capex`, `da`, `nwc`, `delta_nwc` | Reinvestment bridge components. |
| `reinvestment` | `capex - da + delta_nwc`. |
| `fcff`, `pv_fcff` | Firm cash flow and discounted value. |
| `invested_capital_start`, `invested_capital_end` | Invested-capital roll-forward. |
| `roic`, `economic_profit`, `pv_economic_profit` | ROIC/EP diagnostics by year. |
| `fcfe`, `pv_fcfe` | Equity-cash-flow branch values. |

## 3. TerminalBreakdown

| Field | Meaning |
|---|---|
| `tv_gordon`, `tv_exit`, `tv_blended` | Raw terminal values by method and selected blend/fallback. |
| `pv_tv_gordon`, `pv_tv_exit`, `pv_tv_blended` | Present values of terminal methods. |
| `terminal_growth`, `ronic_terminal` | Terminal-state assumptions used in TV logic. |
| `fcff_11_bridge` | Year-11 FCFF from operating bridge. |
| `fcff_11_value_driver` | Value-driver Year-11 FCFF (`NOPAT_11 * (1 - g/RONIC)`) when valid. |
| `gordon_formula_mode` | `value_driver` or `bridge` depending on terminal FCFF source. |
| `method_used` | `blend`, `gordon_only`, `exit_only`, or `none`. |

## 4. DCFComputationResult

| Field | Meaning |
|---|---|
| `intrinsic_value_per_share` | Final blended IV per share for the scenario. |
| `enterprise_value_operations` | EV from discounted FCFF + discounted blended terminal value. |
| `enterprise_value_total` | Operations EV plus non-operating assets. |
| `equity_value` | Total EV less non-equity claims. |
| `iv_gordon`, `iv_exit`, `iv_blended` | Per-share values by terminal method. |
| `tv_pct_of_ev` | Terminal-value concentration diagnostic. |
| `tv_method_fallback_flag` | True when blend could not be used. |
| `roic_consistency_flag` | Flags inconsistent implied terminal economics. |
| `nwc_driver_quality_flag` | Flags invalid/degenerate day-driver inputs. |
| `ep_enterprise_value`, `ep_intrinsic_value_per_share` | Economic-profit cross-check valuation outputs. |
| `dcf_ep_gap_pct`, `ep_reconcile_flag` | DCF vs EP reconciliation diagnostics. |
| `fcfe_intrinsic_value_per_share`, `fcfe_equity_value`, `fcfe_pv_sum`, `fcfe_terminal_value` | FCFE branch outputs. |
| `cost_of_equity_used` | Cost of equity used for FCFE branch discounting. |
| `health_flags` | Structured deterministic warnings (TV extremes, terminal guardrails, contamination checks). |

## 5. Batch Output Terms

| Column | Meaning |
|---|---|
| `expected_iv`, `expected_upside_pct` | Probability-weighted IV and implied upside. |
| `implied_growth_pct` | Reverse DCF implied near-term growth. |
| `ev_operations_mm`, `ev_total_mm` | EV bridge values in USD millions. |
| `ep_iv_base`, `fcfe_iv_base` | Base-scenario EP and FCFE per-share cross-checks. |
| `tv_gordon_mm`, `tv_exit_mm`, `tv_blended_mm` | Terminal value methods in USD millions. |
| `terminal_growth_pct`, `terminal_ronic_pct` | Terminal economic assumptions used by the base scenario. |
| `health_*` | Deterministic risk flags exported for PM review. |
| `*_source` | Source lineage stamps for each assumption family. |
