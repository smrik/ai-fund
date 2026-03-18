# Tech Debt Tracker

Items tracked here get addressed on a rolling basis — not queued forever.
When fixed, move to the relevant sprint's completed log.

---

## Active Debt

| ID | Location | Issue | Priority | Added |
|---|---|---|---|---|
| TD-01 | `src/stage_02_valuation/batch_runner.py:151` | `ebit_margin_override` is `None` for all sectors — fallback is 15% hardcoded regardless of sector | High | 2026-03-06 |
| TD-02 | `src/stage_02_valuation/batch_runner.py:158` | `growth_mid = growth_near * 0.65` — mechanical fade with no business logic | Medium | 2026-03-06 |
| TD-03 | `src/stage_00_data/market_data.py` | `get_peer_multiples()` returns self only — no real peer data | High | 2026-03-06 |
| TD-04 | `src/stage_02_valuation/wacc.py:25` | `RISK_FREE_RATE = 0.045` hardcoded — should pull live 10Y Treasury | Medium | 2026-03-06 |
| TD-05 | `src/stage_03_judgment/base_agent.py:8` | Uses OpenAI SDK (`from openai import OpenAI`) — agents should use Anthropic SDK | High | 2026-03-06 |
| TD-06 | `config/settings.py:41` | `MIN_MARKET_CAP_MM = 2000` conflicts with Stage 1 filter's `500` floor — two sources of truth | Medium | 2026-03-06 |
| TD-07 | `src/stage_02_valuation/templates/dcf_model.py:103-115` | Bear/bull scenario multipliers are generic (0.6x/0.75x) — should be company-specific (Sprint 6) | Low | 2026-03-06 |
| TD-08 | `dashboard/app.py`, `src/stage_04_pipeline/comps_dashboard.py` | Comps workbench is now usable but still lacks explicit quartile statistics, competitor taxonomy, and source-cited peer rationale expected by the repo's competitive/comps skills | Medium | 2026-03-15 |
| TD-09 | `dashboard/app.py`, `src/stage_04_pipeline/dcf_audit.py` | Dashboard lacks a model-integrity panel for balance-sheet ties, cash-flow ties, terminal-value concentration, and logic warnings despite existing DCF/WACC surfaces | High | 2026-03-15 |
| TD-10 | `dashboard/app.py`, `src/stage_04_pipeline/news_materiality.py`, `src/stage_04_pipeline/agent_cache.py` | No structured thesis-tracker or earnings-update surface for beat/miss, old-vs-new estimates, catalyst calendar, and thesis-pillar drift over time | High | 2026-03-15 |
| TD-11 | `dashboard/app.py`, `src/stage_04_pipeline/filings_browser.py`, `src/stage_00_data/edgar_client.py` | Filings Browser is audit-friendly but still text-first; it does not yet expose structured XBRL/statement-table browsing or exhibit-level navigation | Medium | 2026-03-15 |

---

## Resolved Debt

| ID | Resolution | Sprint | Date |
|---|---|---|---|
| TD-12 | Replaced Streamlit `use_container_width` calls with 1.55 `width=` usage and introduced shared presentation formatting helpers used by the dashboard | Dashboard research remediation | 2026-03-15 |
| TD-13 | Added filings statement-coverage diagnostics, retrieval observability, Market Intel historical brief, comps metric switching, football field, and target historical multiples | Dashboard research remediation | 2026-03-15 |
| TD-14 | **P0 lease double-count** — `input_assembler.py` now zeros `lease_liabilities_raw` when folding into `net_debt_raw` (yfinance source), preventing `_claims_total()` from subtracting leases twice. Net debt source set to `"yfinance+leases"`. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-15 | **NWC COGS denominator** — `_nwc_components()` now uses `cogs = revenue * cogs_pct` for inventory and AP projections. `cogs_pct_of_revenue` sourced from yfinance 3-year average, wired through `market_data` → `input_assembler` → `ForecastDrivers`. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-16 | **Story drivers exit multiple** — `apply_story_driver_adjustments()` now applies cyclicality (±10%) and governance risk (±10%) multipliers to `exit_multiple`, clamped to [2, 40]. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-17 | **Share dilution** — Added `annual_dilution_pct` to `ForecastDrivers`; per-share IV outputs now use `shares_y10 = shares * (1 + dilution_pct)^10`. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-18 | **Invested capital from yfinance** — `market_data.py` derives `invested_capital = total_assets - current_liabilities - cash`; added to `_pick()` chain in `_derive_invested_capital_start()` as `"yfinance_derived"` source. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-19 | **Size premium interpolation** — Replaced step-function `_get_size_premium()` with linear interpolation across 5 D&P breakpoints (250M→2.5%, 1.25B→1.5%, 6B→1.0%, 30B→0.5%, 75B→0.0%). Eliminates 50bp cliff at $2B. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-20 | **Batch error summary** — `batch_runner.py` collects failed tickers and prints summary + writes `batch_errors.json` at end of run. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-21 | **DCF IV history in DB** — Added `dcf_valuations` table (PK: ticker, run_date) with iv_bear/base/bull/expected, wacc, exit_multiple, source flags. `persist_results_to_db()` returns 3-tuple. | Valuation pipeline deep gap fix | 2026-03-16 |
| TD-22 | **Comps target EBIT/EPS** — `batch_runner.py` enriches target dict with `ebit_ltm_mm` and `eps_ltm` before calling comps; `build_comps_detail_from_yfinance()` reads them from `target_data`. | Valuation pipeline deep gap fix | 2026-03-16 |

