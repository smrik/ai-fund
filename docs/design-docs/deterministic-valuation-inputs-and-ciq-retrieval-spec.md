# Deterministic Valuation Inputs And CIQ Retrieval Spec

## 1. Purpose

This document is the current-state audit for the deterministic valuation path.

Its job is to answer four practical questions:

1. What does the single-ticker deterministic valuation process actually do today?
2. What inputs does each step require?
3. Which of those inputs come from CIQ versus yfinance, XBRL, config defaults, or derived calculations?
4. What must CIQ retrieve reliably before API, JSON export, and Excel work can be completed cleanly?

This is a companion to:

- `docs/design-docs/deterministic-valuation-flow-spec.md`
- `docs/design-docs/deterministic-valuation-workflow.md`
- `docs/design-docs/deterministic-valuation-benchmark-and-gap-analysis.md`
- `docs/handbook/valuation-dcf-logic.md`

Those docs explain the valuation system at a higher level.
This document is the field-level audit and CIQ requirement map.

## 2. Canonical Entry Points

| Layer | Module | Role |
| --- | --- | --- |
| Data pull | `src/stage_00_data/market_data.py` | yfinance-backed market snapshot and historical financials |
| Data pull | `src/stage_00_data/ciq_adapter.py` | compute-friendly CIQ snapshot, long-form NWC data, and comps adapters |
| Data pull | `src/stage_00_data/sec_filing_metrics.py` | XBRL bridge items for non-equity claims and related balance-sheet items |
| Assumption assembly | `src/stage_02_valuation/input_assembler.py` | canonical deterministic input builder and source-lineage owner |
| Compute | `src/stage_02_valuation/professional_dcf.py` | DCF engine, scenarios, reverse DCF, terminal bridge, diagnostics |
| Orchestration | `src/stage_02_valuation/batch_runner.py` | single-ticker row assembly and JSON/export handoff |
| Export | `src/stage_02_valuation/json_exporter.py` | nested JSON shape for downstream consumers |

Primary single-ticker execution path:

1. `value_single_ticker(ticker)`
2. `build_valuation_inputs(ticker)`
3. `run_probabilistic_valuation(drivers, scenario_specs, current_price)`
4. `reverse_dcf_professional(drivers, target_price, scenario="base")`
5. row assembly for CLI/API/JSON/export consumers

## 3. End-To-End Step Map

| Step | Owner | Required inputs | Produced outputs | Primary sources |
| --- | --- | --- | --- | --- |
| 1. Market and identity snapshot | `market_data.py` + `input_assembler.py` | ticker | price, company name, sector, industry, TTM snapshot, beta, debt/cash, shares | yfinance |
| 2. Historical operating context | `market_data.py` | ticker | CAGR, margin averages, capex/D&A %, tax averages, NWC-derived days, balance-sheet proxies | yfinance |
| 3. CIQ snapshot and comps pull | `ciq_adapter.py` | ticker, optional `as_of_date` | valuation snapshot, long-form NWC day drivers, peer medians, comps implied prices, peer detail | CIQ SQLite tables |
| 4. XBRL bridge pull | `sec_filing_metrics.py` | ticker | pension, lease, preferred, minority, and related bridge items when available | SEC / XBRL |
| 5. Deterministic input assembly | `input_assembler.py` | yfinance + CIQ + XBRL + config defaults | `ValuationInputsWithLineage` and `ForecastDrivers` | mixed |
| 6. Cost of capital and scenario valuation | `professional_dcf.py` | `ForecastDrivers`, WACC methodology set, scenario specs | bear/base/bull DCF outputs, EV bridge, diagnostics, health flags | deterministic compute |
| 7. Reverse DCF | `professional_dcf.py` | base drivers + market price | implied near-term growth | deterministic compute |
| 8. Output assembly | `batch_runner.py` | valuation inputs + scenario outputs + comps outputs | flat result row, `drivers_json`, `forecast_bridge_json` | deterministic compute |
| 9. Nested export assembly | `json_exporter.py` | result row, optional QoE/comps payloads | nested ticker JSON | deterministic export transform |

## 4. Step-By-Step Inputs And Outputs

### 4.1 Step 1: Market and identity snapshot

Purpose:
- establish ticker identity and the present-day market anchor
- provide the minimum inputs required to decide whether the ticker is valu-able at all

Main fields consumed:

| Field | Used for | Current source |
| --- | --- | --- |
| `current_price` | valuation anchor, reverse DCF target | yfinance |
| `name` | output identity only | yfinance |
| `sector`, `industry` | defaults, exit metric policy, model applicability | yfinance |
| `revenue_ttm` | fallback revenue base | yfinance |
| `operating_margin` | fallback margin | yfinance |
| `revenue_growth` | fallback near-term growth | yfinance |
| `total_debt`, `cash` | net debt fallback | yfinance |
| `shares_outstanding` | share-count fallback | yfinance |
| `beta` | WACC | yfinance |
| `market_cap`, `enterprise_value` | output context only | yfinance |
| `analyst_target_mean`, `analyst_recommendation`, `number_of_analysts` | output context only | yfinance |

Produced outputs:
- identity: ticker, company, sector, industry
- valuation gate: `price > 0`, `revenue_base > 0`
- market-context fields used later in the output row

### 4.2 Step 2: Historical operating context

Purpose:
- stabilize assumptions with historical averages instead of one noisy TTM point
- provide fallback data when CIQ is absent or incomplete

Main historical fields consumed from `get_historical_financials()`:

| Field | Used for |
| --- | --- |
| `revenue_cagr_3yr` | near-term growth fallback |
| `op_margin_avg_3yr` | EBIT margin start fallback |
| `capex_pct_avg_3yr` | capex % start fallback |
| `da_pct_avg_3yr` | D&A % start fallback |
| `effective_tax_rate_avg` | tax start fallback |
| `dso_derived`, `dio_derived`, `dpo_derived` | working-capital day fallbacks |
| `invested_capital_derived` | invested-capital fallback |
| `minority_interest_bs`, `preferred_equity_bs`, `lease_liabilities_bs` | EV-to-equity bridge fallbacks |
| `sbc` | options-value proxy |
| `cogs_pct_of_revenue` | DIO/DPO denominator fix |

Produced outputs:
- operating averages used directly in `ForecastDrivers`
- balance-sheet proxies used in bridge-item fallbacks
- several documented fallback paths that are still partially heuristic

### 4.3 Step 3: CIQ snapshot, long-form, and comps pull

Purpose:
- provide the strongest company-specific deterministic inputs where yfinance is weak
- anchor exit multiples and comparable valuation

`get_ciq_snapshot()` currently returns or derives:

| Field | Current use |
| --- | --- |
| `revenue_ttm` | top-priority revenue base |
| `revenue_fy1`, `revenue_fy2` | consensus near-term growth anchor |
| `ebit_margin`, `op_margin_avg_3yr` | margin start |
| `capex_pct_avg_3yr`, `da_pct_avg_3yr` | capex / D&A starts |
| `effective_tax_rate`, `effective_tax_rate_avg` | tax start |
| `revenue_cagr_3yr` | growth fallback |
| `total_debt`, `cash`, `shares_outstanding` | net debt and shares |
| `debt_to_ebitda`, `roic`, `fcf_yield` | leverage / ROIC context, terminal RONIC |
| `dso`, `dio`, `dpo` | working-capital starts |
| `run_id`, `as_of_date`, `source_file` | lineage and reproducibility |

`get_ciq_nwc_history()` currently returns:
- up to three historical periods of `dso`, `dio`, `dpo`
- only used in QoE today, not in deterministic driver assembly

`get_ciq_comps_valuation()` currently returns:

| Field | Current use |
| --- | --- |
| `peer_median_tev_ebitda_fwd`, `peer_median_tev_ebitda_ltm` | EBITDA exit-multiple anchor |
| `peer_median_tev_ebit_fwd`, `peer_median_tev_ebit_ltm` | EBIT exit-multiple anchor |
| `peer_median_pe_ltm` | comparable valuation output |
| `implied_price_ev_ebitda`, `implied_price_ev_ebit`, `implied_price_pe`, `implied_price_base` | standalone comps outputs |
| `peer_count`, `run_id`, `as_of_date`, `source_file` | lineage |

`get_ciq_comps_detail()` currently returns:
- target and peer rows for revenue, EBITDA, EBIT, EPS, market cap, TEV, and trading multiples
- medians used by the richer comps appendix / dashboard paths

### 4.4 Step 4: XBRL bridge pull

Purpose:
- fill non-equity claim and bridge-item gaps not always covered in yfinance

Current XBRL bridge items consumed:

| Field | Used for |
| --- | --- |
| `minority_interest` | EV-to-equity bridge |
| `preferred_equity` | EV-to-equity bridge |
| `pension_deficit` | EV-to-equity bridge |
| `lease_liabilities` | EV-to-equity bridge |
| `sbc` | options-value proxy support |

XBRL is not the first source for most of these fields today; it is generally a fallback after CIQ and before default `0.0`.

### 4.5 Step 5: Deterministic input assembly

Purpose:
- convert mixed-source raw facts into one validated deterministic driver object with source lineage

The canonical output object is `ValuationInputsWithLineage`, containing:
- identity and timing
- `ForecastDrivers`
- `source_lineage`
- `ciq_lineage`
- `wacc_inputs`
- optional story-profile metadata

Current resolved `ForecastDrivers` fields:

| Driver | Resolution summary |
| --- | --- |
| `revenue_base` | CIQ revenue TTM -> yfinance revenue TTM |
| `revenue_growth_near` | CIQ consensus FY1/LTM -> CIQ 3Y CAGR -> yfinance 3Y CAGR -> yfinance TTM YoY -> sector default |
| `revenue_growth_mid` | deterministic fade from near-term growth |
| `revenue_growth_terminal` | sector default |
| `ebit_margin_start` | CIQ margin -> yfinance margin averages -> yfinance TTM margin -> sector default |
| `ebit_margin_target` | blend of company start and sector default |
| `tax_rate_start`, `tax_rate_target` | CIQ / yfinance effective tax average with bounds |
| `capex_pct_start`, `capex_pct_target` | CIQ -> yfinance -> default, then bounded target |
| `da_pct_start`, `da_pct_target` | CIQ -> yfinance -> default, then bounded target |
| `dso/dio/dpo start` | CIQ -> yfinance-derived -> default |
| `dso/dio/dpo target` | partial mean-reversion blend if company data exists, else default |
| `wacc`, `cost_of_equity`, `debt_weight` | WACC methodology set built primarily from yfinance / market data |
| `exit_multiple` | CIQ comps forward -> CIQ comps LTM -> sector default |
| `exit_metric` | sector policy |
| `net_debt` | CIQ -> yfinance, with lease fold-in for yfinance path |
| `shares_outstanding` | CIQ -> yfinance diluted -> yfinance basic |
| `invested_capital_start` | CIQ invested capital -> CIQ-derived NOPAT/ROIC -> yfinance-derived -> default turnover |
| `ronic_terminal` | CIQ ROIC -> sector default |
| `non_operating_assets` | CIQ cash excess -> yfinance cash excess -> default `0` |
| bridge claims | CIQ -> yfinance / XBRL -> default `0` |
| `cogs_pct_of_revenue` | yfinance only -> default `0.60` |

### 4.6 Step 6: Deterministic valuation compute

Purpose:
- translate `ForecastDrivers` into explicit DCF outputs

Main output families from `professional_dcf.py`:

| Output family | Examples |
| --- | --- |
| scenario IVs | `iv_bear`, `iv_base`, `iv_bull`, `expected_iv` |
| EV bridge | `enterprise_value_operations`, `enterprise_value_total`, `non_equity_claims` |
| terminal bridge | Gordon, exit, and blended TVs plus PVs |
| diagnostics | `tv_pct_of_ev`, `roic_consistency_flag`, `nwc_driver_quality_flag` |
| cross-checks | EP and FCFE branches |
| artifacts | year-by-year forecast bridge |

### 4.7 Step 7: Output row and export handoff

Purpose:
- flatten deterministic outputs for ranking, API transport, JSON export, and workbook consumers

`value_single_ticker()` adds:
- display context fields
- assumption / lineage audit fields
- CIQ lineage metadata
- comps outputs
- JSON payload fields:
  - `drivers_json`
  - `forecast_bridge_json`
  - `story_profile_json`
  - `story_adjustments_json`

`export_ticker_json()` then nests those into sections such as:
- `market`
- `assumptions`
- `wacc`
- `valuation`
- `scenarios`
- `terminal`
- `health_flags`
- `source_lineage`
- optional `qoe`, `comps_detail`, `comps_analysis`

## 5. CIQ Retrieval Requirement Matrix

The table below answers the core spike question: what does CIQ need to retrieve for valuation support?

| Category | Field(s) needed | Current use | Current status | Fallback if missing |
| --- | --- | --- | --- | --- |
| Identity and timing | `as_of_date`, `run_id`, `source_file` | lineage, reproducibility, export audit | present | none |
| Revenue base and near-term estimates | `revenue_ttm`, `revenue_fy1`, `revenue_fy2` | revenue base, consensus near-term growth | present | yfinance TTM + historical CAGR |
| Historical operating quality snapshot | `op_margin_avg_3yr`, `capex_pct_avg_3yr`, `da_pct_avg_3yr`, `effective_tax_rate_avg`, `revenue_cagr_3yr` | core DCF assumptions | present | yfinance averages / defaults |
| Capital structure snapshot | `total_debt`, `cash`, `shares_outstanding` | net debt, shares, EV bridge | present | yfinance |
| Returns and leverage | `roic`, `debt_to_ebitda`, `fcf_yield` | terminal RONIC, review context | partly used | defaults / not all downstream consumers use them |
| Working-capital day drivers | `dso`, `dio`, `dpo` | DCF NWC starts | present, with long-form derivation fallback | yfinance-derived / defaults |
| Historical NWC detail | receivables, inventory, payables, revenue by period | historical DSO/DIO/DPO, QoE support | long-form partially present | yfinance-derived |
| Invested capital | explicit invested capital or components to derive it | EP cross-check and reinvestment quality | partial / ambiguous | CIQ ROIC-derived -> yfinance-derived -> turnover default |
| Non-equity claims | `minority_interest`, `preferred_equity`, `pension_deficit`, `lease_liabilities`, `options_value`, `convertibles_value` | EV-to-equity bridge | partial; many names likely fall to XBRL/default | yfinance / XBRL / `0.0` |
| Comps trading multiples | peer LTM/FY1 TEV/EBITDA, TEV/EBIT, P/E | exit multiple anchor and comps valuation | present | sector default or yfinance peer fallback |
| Comps peer detail | target + peer revenue, EBITDA, EBIT, EPS, TEV, market cap | richer comps outputs and workbook views | present for current comps scope | yfinance peer fallback |
| Historical operating series beyond snapshot averages | multi-period revenue, EBIT, EBITDA, capex, D&A, tax, shares | robust API/JSON/Excel history surfaces | weak from current CIQ adapter into valuation flow | yfinance currently owns most historical series |
| Company master metadata | full legal name, sector, industry, exchange, CEO, IPO date | dossier / API / overview UX | not owned by CIQ path today | yfinance or other market data |

## 6. Key Current Gaps

### Gap A: CIQ is strong on snapshots and comps, weak in the current flow for deep history

The deterministic flow still relies heavily on yfinance for multi-period operating history.
CIQ currently contributes:
- snapshot averages already pre-shaped into `ciq_valuation_snapshot`
- long-form day-driver support
- comps data

It does **not** currently serve as the main historical engine for:
- multi-period revenue / EBIT / EBITDA series
- capex / D&A history
- tax history
- share-count history
- invested-capital history

That matters because the next API / JSON / Excel work wants richer history and stronger auditability than a few pre-aggregated CIQ snapshot fields.

### Gap B: Invested-capital support is still partially heuristic

`invested_capital_start` currently resolves as:
1. explicit CIQ invested capital
2. CIQ-derived NOPAT / ROIC
3. yfinance-derived invested capital
4. sector turnover default

This is a meaningful audit gap because EP and reinvestment diagnostics become less trustworthy when invested capital falls through to heuristics.

### Gap C: COGS-based DIO/DPO support is still thin

The code explicitly flags a gap around `cogs_pct_of_revenue`.
Current state:
- `cogs_pct_of_revenue` comes only from yfinance history or a `0.60` default
- CIQ is not currently documented as a source for this denominator support

That weakens the quality of inventory/payables forecasting even when CIQ day counts are present.

### Gap D: Non-equity claims are only partially CIQ-backed

The EV-to-equity bridge supports:
- minority interest
- preferred equity
- pension deficit
- lease liabilities
- options value
- convertibles value

But in practice, several of these can still fall through to:
- yfinance balance-sheet proxies
- XBRL bridge items
- or default zero

Before API/JSON/Excel become more formal, these fields should be treated as required bridge-item audit points.

### Gap E: QoE inputs are downstream and optional, not part of the canonical deterministic contract

QoE support currently exists in `batch_runner.py` and the judgment layer, but it is not part of the required deterministic valuation input contract.
That means:
- the deterministic valuation path is correct architecturally
- but the broader dossier/export contract still lacks a first-class, stable place for QoE inputs and outputs

### Gap F: Identity and overview metadata are outside the CIQ valuation contract

For the future API and Overview surface, the product needs:
- full name
- sector / industry consistency
- exchange
- price history
- executive / IPO / share metadata

That is broader than the current CIQ valuation contract.
It does not block deterministic DCF, but it does block a clean canonical dossier contract if left implicit.

## 7. Downstream Contract Implications

### 7.1 API requirements

The API should eventually be able to expose, for one ticker:
- raw identity and market context
- deterministic valuation inputs
- deterministic valuation outputs
- source lineage
- CIQ lineage
- historical series for charts and audits

This spike shows that the clean API contract cannot be designed from the DCF output row alone.
It needs an explicit valuation-input section and lineage section.

### 7.2 API valuation -> JSON export

JSON export currently serializes:
- `drivers_json`
- `forecast_bridge_json`
- result-row context
- optional `qoe`, `comps_detail`, `comps_analysis`

The missing piece is not the ability to export JSON.
The missing piece is a clearer canonical dossier contract that distinguishes:
- raw retrieved data
- deterministic derived drivers
- deterministic valuation outputs
- optional advisory layers

### 7.3 JSON export -> Excel template

The workbook already wants more than just final IVs.
It needs:
- assumptions and lineage
- terminal bridge
- forecast bridge
- comps details
- historical context
- QoE context where relevant

That means the CIQ retrieval layer should be designed with workbook support in mind, not only with DCF arithmetic in mind.

## 8. Implementation-Grounded Pseudocode

```text
function value_single_ticker(ticker):
    inputs = build_valuation_inputs(ticker)
    if inputs is None:
        return None

    market = get_market_data(ticker)
    scenario_specs = default_scenario_specs()
    probabilistic = run_probabilistic_valuation(inputs.drivers, scenario_specs, current_price=inputs.current_price)
    reverse_growth = reverse_dcf_professional(inputs.drivers, target_price=inputs.current_price, scenario="base")

    row = flatten(
        identity=inputs.identity,
        market_context=market,
        drivers=inputs.drivers,
        source_lineage=inputs.source_lineage,
        ciq_lineage=inputs.ciq_lineage,
        wacc_inputs=inputs.wacc_inputs,
        scenario_outputs=probabilistic,
        reverse_dcf=reverse_growth,
        terminal_and_health=probabilistic.base_case
    )

    attach serialized artifacts:
        drivers_json
        forecast_bridge_json
        story_profile_json
        story_adjustments_json

    return row

function build_valuation_inputs(ticker):
    market = get_market_data(ticker)
    hist = get_historical_financials(ticker)
    ciq_snapshot = get_ciq_snapshot(ticker)
    ciq_comps = get_ciq_comps_valuation(ticker)
    ciq_comps_detail = get_ciq_comps_detail(ticker)
    edgar_bridge = get_bridge_items_from_xbrl(ticker)

    resolve revenue base and growth with explicit precedence
    resolve operating assumptions with CIQ -> yfinance -> default precedence
    compute WACC methodology set using market data and peers
    resolve exit multiple from CIQ comps or defaults
    resolve bridge items and non-equity claims
    build ForecastDrivers
    stamp source_lineage, ciq_lineage, and wacc_inputs

    return ValuationInputsWithLineage
```

## 9. Recommended Next Work After This Spike

1. Decide which fields become mandatory in the future canonical ticker dossier.
2. Convert the gap list above into CIQ retrieval implementation issues.
3. Separate clearly:
   - retrieval contracts
   - deterministic derived-driver contracts
   - API/dossier contracts
   - export contracts
4. Revisit CIQ historical coverage before finalizing the API valuation payload shape.
