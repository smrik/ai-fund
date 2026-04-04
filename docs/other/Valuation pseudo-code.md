---
created: 2026-03-12T00:44
updated: 2026-03-14T11:43
---
Absolutely — here is a **deep, structured pseudo-code approach to corporate valuation** built around the BUSO97 course flow: business understanding → accounting adjustments → historical analysis → forecasting → cost of capital → valuation → bridge from enterprise value to equity value → diagnostics and interpretation. It is grounded in the DCF / economic profit framework emphasized in the course materials.

---

# Pseudo-code for Corporate Valuation

## 0. High-level philosophy

```text
GOAL:
    Estimate intrinsic value of the firm’s operations
    using fundamental analysis, forecasts, and discounting.

MAIN OUTPUTS:
    Enterprise Value
    Equity Value
    Value per Share
    Implied value drivers
    Sensitivity / scenario conclusions

CORE PRINCIPLE:
    Value is driven by:
        - cash flow generation
        - growth
        - return on invested capital (ROIC)
        - risk / cost of capital (WACC)
```

This matches the course emphasis that valuation is not just “plug into a formula,” but a full process involving analysis, adjustment, forecasting, and interpretation.

---

# 1. Master valuation algorithm

```text
FUNCTION VALUE_COMPANY(company_data, market_data, assumptions):

    STEP 1: UNDERSTAND BUSINESS AND CONTEXT
        business_profile = ANALYZE_BUSINESS(company_data)
        industry_profile = ANALYZE_INDUSTRY(company_data, market_data)
        value_drivers = IDENTIFY_KEY_VALUE_DRIVERS(business_profile, industry_profile)

    STEP 2: REORGANIZE AND ADJUST FINANCIAL STATEMENTS
        clean_financials = RECAST_FINANCIAL_STATEMENTS(company_data.financials)
        adjusted_financials = MAKE_ACCOUNTING_ADJUSTMENTS(clean_financials)

    STEP 3: PERFORM HISTORICAL PERFORMANCE ANALYSIS
        history_metrics = ANALYZE_HISTORICAL_PERFORMANCE(adjusted_financials)
        operating_patterns = EXTRACT_FORECAST_DRIVERS(history_metrics)

    STEP 4: FORECAST OPERATING PERFORMANCE
        forecast_horizon = SET_FORECAST_HORIZON(company_data, industry_profile)
        pro_forma = BUILD_PRO_FORMA_FORECASTS(adjusted_financials, operating_patterns, assumptions, forecast_horizon)

    STEP 5: ESTIMATE COST OF CAPITAL
        cost_of_equity = ESTIMATE_COST_OF_EQUITY(company_data, market_data, assumptions)
        cost_of_debt = ESTIMATE_COST_OF_DEBT(company_data, market_data, assumptions)
        capital_structure = ESTIMATE_TARGET_CAPITAL_STRUCTURE(company_data, market_data)
        WACC = COMPUTE_WACC(cost_of_equity, cost_of_debt, capital_structure, assumptions.tax_rate)

    STEP 6: COMPUTE FREE CASH FLOWS
        FCFF_series = COMPUTE_FCFF(pro_forma)

    STEP 7: ESTIMATE CONTINUING VALUE
        continuing_value = ESTIMATE_CONTINUING_VALUE(pro_forma, WACC, assumptions)

    STEP 8: DISCOUNT CASH FLOWS TO PRESENT VALUE
        enterprise_value_operations = DISCOUNT_FCFF_AND_CV(FCFF_series, continuing_value, WACC)

    STEP 9: MOVE FROM OPERATIONS VALUE TO EQUITY VALUE
        enterprise_value_total = ADD_NON_OPERATING_ASSETS(enterprise_value_operations, company_data)
        equity_value = SUBTRACT_NON_EQUITY_CLAIMS(enterprise_value_total, company_data)

    STEP 10: COMPUTE VALUE PER SHARE
        value_per_share = COMPUTE_PER_SHARE_VALUE(equity_value, company_data)

    STEP 11: CROSS-CHECK WITH ECONOMIC PROFIT METHOD
        EP_value = VALUE_USING_ECONOMIC_PROFIT(pro_forma, WACC, assumptions)
        RECONCILE_DCF_AND_EP(enterprise_value_operations, EP_value)

    STEP 12: DIAGNOSTICS AND SANITY CHECKS
        diagnostics = RUN_VALUATION_DIAGNOSTICS(pro_forma, WACC, continuing_value, value_per_share)
        sensitivity = RUN_SENSITIVITY_ANALYSIS(pro_forma, WACC, assumptions)
        scenarios = RUN_SCENARIO_ANALYSIS(base_case, upside_case, downside_case)

    STEP 13: INTERPRET RESULTS
        interpretation = FORMULATE_INVESTMENT_OR_VALUATION_CONCLUSION(value_per_share, diagnostics, scenarios)

    RETURN {
        business_profile,
        adjusted_financials,
        history_metrics,
        pro_forma,
        WACC,
        FCFF_series,
        continuing_value,
        enterprise_value_operations,
        equity_value,
        value_per_share,
        EP_value,
        diagnostics,
        sensitivity,
        scenarios,
        interpretation
    }
```

---

# 2. Step 1 — Analyze business, industry, and narrative

The course material stresses that valuation starts with understanding the business and converting the “story” into forecastable value drivers.

```text
FUNCTION ANALYZE_BUSINESS(company_data):

    IDENTIFY:
        products/services
        customer groups
        geography
        business segments
        revenue model
        cost structure
        strategy
        competitive advantage sources
        management quality
        cyclicality / seasonality
        exposure to macro variables

    ASK:
        What does this firm sell?
        Where does growth come from?
        What determines margins?
        What assets are required to support growth?
        What risks threaten performance?
        What is temporary vs structural?

    OUTPUT:
        business_profile
```

```text
FUNCTION ANALYZE_INDUSTRY(company_data, market_data):

    EVALUATE:
        industry growth
        competitive intensity
        entry barriers
        pricing power
        supplier/customer power
        regulation
        technological disruption
        maturity stage

    BENCHMARK:
        peer margins
        peer ROIC
        peer leverage
        peer valuation multiples

    OUTPUT:
        industry_profile
```

```text
FUNCTION IDENTIFY_KEY_VALUE_DRIVERS(business_profile, industry_profile):

    key_value_drivers = {
        revenue_growth,
        operating_margin,
        tax_rate,
        reinvestment_rate,
        invested_capital_turnover,
        ROIC,
        competitive_advantage_period,
        stable_growth_rate,
        WACC
    }

    MAP narrative -> numbers:
        if firm has scale advantage:
            expect stronger margins and/or capital efficiency
        if market still expanding:
            allow higher near-term revenue growth
        if competition intensifies:
            force margin convergence downward
        if business is capital intensive:
            require more reinvestment per unit of growth

    OUTPUT:
        key_value_drivers
```

---

# 3. Step 2 — Reorganize and adjust financial statements

A major part of the course is separating operating from non-operating items and correcting accounting distortions.

## 3.1 Recast statements

```text
FUNCTION RECAST_FINANCIAL_STATEMENTS(financials):

    RECAST income statement into:
        operating revenues
        operating expenses
        EBITA / EBIT
        operating taxes
        NOPAT

    RECAST balance sheet into:
        operating assets
        operating liabilities
        invested capital
        non-operating assets
        financing liabilities
        equity

    RECAST cash flow statement into:
        cash flow from operations
        investment in operations
        financing cash flows

    DEFINE invested capital:
        invested_capital = operating_assets - operating_liabilities

    OUTPUT:
        recast_statements
```

## 3.2 Make accounting adjustments

```text
FUNCTION MAKE_ACCOUNTING_ADJUSTMENTS(recast_statements):

    FOR each reported item:
        IF item is non-recurring / unusual / transitory:
            separate it from recurring operating performance

        IF item is non-operating:
            exclude from operating profit
            classify for later bridge to equity value

        IF leases are material:
            capitalize lease-like obligations consistently

        IF pension / retirement obligations are material:
            classify operating vs financing components carefully

        IF R&D should be treated as investment:
            consider capitalizing and amortizing for analysis consistency

        IF goodwill / acquisitions distort comparability:
            document treatment consistently

        IF excess cash exists:
            exclude from invested capital for operations valuation

        IF minority interest / associates / unconsolidated investments exist:
            classify consistently in EV-to-equity bridge

        IF deferred taxes / provisions matter:
            assess whether operating or financing-like

    ENSURE:
        NOPAT reflects after-tax operating performance
        invested capital reflects capital invested in operations
        non-operating items are not mixed into core performance

    OUTPUT:
        adjusted_financials
```

## 3.3 Core classification logic

```text
RULE:
    Include item in operations IF it is required to generate core operating profits.

    Exclude item from operations IF it is:
        excess cash
        marketable securities
        unrelated investments
        financing liability
        non-core asset
```

Common pitfall:

```text
DO NOT:
    use reported net income directly in enterprise DCF
    mix financing costs into operating profit
    leave excess cash inside invested capital
```

---

# 4. Step 3 — Historical performance analysis

This step is where you learn what has driven performance and what should or should not persist.

```text
FUNCTION ANALYZE_HISTORICAL_PERFORMANCE(adjusted_financials):

    FOR each historical year:
        revenue_growth = (Revenue_t / Revenue_t-1) - 1
        EBIT_margin = EBIT / Revenue
        NOPAT_margin = NOPAT / Revenue
        invested_capital_turnover = Revenue / InvestedCapital
        ROIC = NOPAT / InvestedCapital_previous_or_average
        reinvestment = NetInvestmentInOperatingCapital
        FCF = NOPAT + D&A - Capex - IncreaseNWC +/- other operating adjustments

    DECOMPOSE ROIC into:
        ROIC = NOPAT margin × invested capital turnover

    STUDY:
        trend stability
        cyclicality
        relation between growth and reinvestment
        relation between margins and competition
        relation between scale and returns
        accounting noise

    OUTPUT:
        history_metrics
```

```text
FUNCTION EXTRACT_FORECAST_DRIVERS(history_metrics):

    DETERMINE:
        normalized revenue growth
        normalized operating margin
        normalized tax burden
        normalized reinvestment intensity
        working capital behavior
        capital intensity
        historical ROIC persistence

    FLAG:
        one-off years
        boom/bust years
        acquisition-heavy periods
        restructuring periods
        abnormal commodity or FX effects

    OUTPUT:
        forecast_driver_set
```

---

# 5. Step 4 — Forecast pro forma statements

The McKinsey-style course approach emphasizes integrated forecasting rather than forecasting each line item blindly.

## 5.1 Set horizon

```text
FUNCTION SET_FORECAST_HORIZON(company_data, industry_profile):

    IF firm is mature and stable:
        horizon = 5 years (often reasonable)

    ELSE IF firm is high-growth / restructuring / cyclical recovery:
        horizon = longer until economics normalize

    CONDITION:
        explicit forecast should continue until:
            returns, growth, and reinvestment are moving toward steady-state

    RETURN horizon
```

## 5.2 Build integrated forecast logic

```text
FUNCTION BUILD_PRO_FORMA_FORECASTS(adjusted_financials, drivers, assumptions, horizon):

    INITIALIZE forecast years t = 1 to horizon

    FOR each year t:

        FORECAST revenue:
            Revenue_t = Revenue_t-1 × (1 + growth_t)

        FORECAST operating margin:
            EBITA_t = Revenue_t × margin_t

        FORECAST taxes on operations:
            NOPAT_t = EBITA_t × (1 - operating_tax_rate_t)
            OR
            NOPAT_t = EBIT_t - cash_operating_taxes_t

        FORECAST invested capital needs using one of:
            method A: turnover approach
                InvestedCapital_t = Revenue_t / IC_turnover_t

            method B: incremental investment approach
                Reinvestment_t = Growth-linked reinvestment requirement

            method C: driver approach
                separate operating working capital, PP&E, intangibles

        COMPUTE increase in invested capital:
            delta_IC_t = InvestedCapital_t - InvestedCapital_t-1

        COMPUTE FCFF:
            FCFF_t = NOPAT_t - delta_IC_t
            OR equivalently:
            FCFF_t = NOPAT_t + D&A_t - Capex_t - delta_NWC_t

        COMPUTE ROIC_t:
            ROIC_t = NOPAT_t / InvestedCapital_t-1_or_average

        ENFORCE consistency:
            growth_t ≈ reinvestment_rate_t × RONIC_t
            where reinvestment_rate_t = delta_IC_t / NOPAT_t (conceptually, if appropriate)

    RETURN pro_forma_forecasts
```

## 5.3 Economic consistency checks

```text
CHECK_FORECAST_CONSISTENCY:

    IF growth is high and reinvestment is low:
        FLAG inconsistency

    IF ROIC rises without strategic explanation:
        FLAG optimism risk

    IF margins exceed peer reality with no moat justification:
        FLAG forecast stretch

    IF stable-growth period assumes ROIC >> WACC forever:
        FLAG likely unrealistic

    IF growth > long-run nominal economy growth in perpetuity:
        FLAG terminal inconsistency
```

---

# 6. Step 5 — Estimate cost of capital

The course explicitly highlights cost of equity, cost of debt, and WACC as core inputs.

## 6.1 Cost of equity

```text
FUNCTION ESTIMATE_COST_OF_EQUITY(company_data, market_data, assumptions):

    risk_free_rate = SELECT_RISK_FREE_RATE(market_data, currency, maturity)
    equity_risk_premium = SELECT_ERP(market_data, geography)
    beta = ESTIMATE_BETA(company_data, peers, leverage_policy)

    cost_of_equity = risk_free_rate + beta × equity_risk_premium

    IF additional country risk is taught / relevant:
        add country risk premium consistently

    RETURN cost_of_equity
```

## 6.2 Beta estimation logic

```text
FUNCTION ESTIMATE_BETA(company_data, peers, leverage_policy):

    IF company beta unreliable:
        peer_betas = COLLECT_PEER_BETAS(peers)

        FOR each peer:
            unlever beta:
                beta_u = UNLEVER(peer_beta_e, peer_DE, peer_tax)

        industry_beta_u = MEDIAN(beta_u across peers)

        relever to target structure:
            beta_target = RELEVER(industry_beta_u, target_DE, target_tax)

        RETURN beta_target

    ELSE:
        RETURN adjusted company beta
```

The formula sheet also gives the leverage adjustment intuition and formulas for beta / ROE under leverage.

## 6.3 Cost of debt

```text
FUNCTION ESTIMATE_COST_OF_DEBT(company_data, market_data, assumptions):

    IF traded debt exists:
        pre_tax_cost_of_debt = current_yield_on_debt

    ELSE:
        pre_tax_cost_of_debt = risk_free_rate + default_spread

    after_tax_cost_of_debt = pre_tax_cost_of_debt × (1 - tax_rate)

    RETURN {
        pre_tax_cost_of_debt,
        after_tax_cost_of_debt
    }
```

## 6.4 WACC

```text
FUNCTION COMPUTE_WACC(cost_of_equity, cost_of_debt, capital_structure, tax_rate):

    E_over_V = target_equity_weight
    D_over_V = target_debt_weight

    WACC = E_over_V × cost_of_equity + D_over_V × cost_of_debt × (1 - tax_rate)

    RETURN WACC
```

---

# 7. Step 6 — Compute FCFF

In enterprise DCF, the standard operating cash flow measure is FCFF.

```text
FUNCTION COMPUTE_FCFF(pro_forma):

    FOR each year t:
        FCFF_t = NOPAT_t - IncreaseInInvestedCapital_t

    OPTIONAL expanded version:
        FCFF_t = EBIT_t × (1 - tax_rate)
                 + D&A_t
                 - Capex_t
                 - IncreaseInNWC_t
                 - Other operating investments_t

    RETURN FCFF_series
```

Key logic:

```text
FCFF belongs to all capital providers
therefore discount using WACC
```

Common pitfall:

```text
DO NOT:
    subtract interest expense in FCFF
    discount FCFF using cost of equity
```

---

# 8. Step 7 — Estimate continuing value

Continuing value is usually a large part of total value, so it must be economically disciplined. The formula sheet and lectures emphasize continuing value through growth, WACC, and return on new invested capital.

## 8.1 Growing perpetuity form

```text
FUNCTION ESTIMATE_CONTINUING_VALUE(pro_forma, WACC, assumptions):

    terminal_year = final explicit forecast year N

    SET stable assumptions:
        g = stable_growth_rate
        RONIC = return_on_new_invested_capital_in_stable_period
        NOPAT_Nplus1 = NOPAT_(N+1)

    continuing_value = NOPAT_Nplus1 × (1 - g / RONIC) / (WACC - g)

    RETURN continuing_value
```

This is the value-driver form from the formula sheet.

Equivalent cash flow form:

```text
FCFF_(N+1) = NOPAT_(N+1) × (1 - g / RONIC)

CV_N = FCFF_(N+1) / (WACC - g)
```

## 8.2 Stable-state rules

```text
STABLE_STATE_CONDITIONS:
    g < WACC normally
    g should be economically sustainable
    ROIC / RONIC should trend toward plausible mature levels
    reinvestment must support growth
    capital structure should be sustainable
```

Common pitfall:

```text
NEVER set terminal growth independently of reinvestment needs.
Growth requires investment.
```

---

# 9. Step 8 — Discount FCFF and continuing value

```text
FUNCTION DISCOUNT_FCFF_AND_CV(FCFF_series, continuing_value, WACC):

    PV_FCFF = 0

    FOR each year t:
        PV_FCFF += FCFF_t / (1 + WACC)^t

    PV_CV = continuing_value / (1 + WACC)^N

    enterprise_value_operations = PV_FCFF + PV_CV

    RETURN enterprise_value_operations
```

---

# 10. Step 9 — Bridge from enterprise value to equity value

This is one of the most tested and most misunderstood areas.

```text
FUNCTION ADD_NON_OPERATING_ASSETS(enterprise_value_operations, company_data):

    enterprise_value_total = enterprise_value_operations
    enterprise_value_total += excess_cash
    enterprise_value_total += marketable_securities
    enterprise_value_total += non-consolidated investments
    enterprise_value_total += other non-operating assets

    RETURN enterprise_value_total
```

```text
FUNCTION SUBTRACT_NON_EQUITY_CLAIMS(enterprise_value_total, company_data):

    equity_value = enterprise_value_total
    equity_value -= debt
    equity_value -= lease liabilities if treated as financing claim
    equity_value -= pension deficits if financing-like
    equity_value -= minority interest / noncontrolling interest when needed
    equity_value -= preferred stock
    equity_value -= other debt equivalents
    equity_value -= value of options / employee claims if relevant

    RETURN equity_value
```

Conceptually:

```text
Value of operations
+ non-operating assets
- debt and other non-equity claims
= equity value
```

That fits the lecture distinction between enterprise value, value of operations, and the bridge to equity.

---

# 11. Step 10 — Value per share

```text
FUNCTION COMPUTE_PER_SHARE_VALUE(equity_value, company_data):

    diluted_shares = basic_shares + dilutive_options + convertibles_effect

    value_per_share = equity_value / diluted_shares

    RETURN value_per_share
```

Common pitfall:

```text
Do not divide by basic shares if dilution is material.
```

---

# 12. Step 11 — Economic profit valuation cross-check

The course explicitly includes both DCF and economic profit techniques.

## 12.1 Economic profit logic

```text
FUNCTION VALUE_USING_ECONOMIC_PROFIT(pro_forma, WACC, assumptions):

    invested_capital_0 = current invested capital
    EP_value = invested_capital_0

    FOR each year t:
        ROIC_t = NOPAT_t / invested_capital_t-1_or_average
        economic_profit_t = (ROIC_t - WACC) × invested_capital_t-1_or_average
        EP_value += economic_profit_t / (1 + WACC)^t

    terminal_EP = ESTIMATE_CONTINUING_EP(pro_forma, WACC, assumptions)
    EP_value += terminal_EP / (1 + WACC)^N

    RETURN EP_value
```

## 12.2 Continuing economic profit

Formula-sheet version:

```text
CV_EP = IC_N × (ROIC_(N+1) - WACC) / WACC
        + [NOPAT_(N+1) × (g / RONIC) × (RONIC - WACC)] / [WACC × (WACC - g)]
```

or conceptually:

```text
firm value = invested capital today + PV(future economic profits)
```

If the model is consistent, enterprise DCF and economic profit should match.

```text
FUNCTION RECONCILE_DCF_AND_EP(DCF_value, EP_value):

    difference = DCF_value - EP_value

    IF abs(difference) is small:
        PASS consistency check
    ELSE:
        INVESTIGATE:
            NOPAT definition mismatch
            invested capital mismatch
            terminal assumptions mismatch
            discounting timing mismatch
```

---

# 13. Step 12 — Diagnostics and sanity checks

This step separates a mechanical valuation from a good valuation.

```text
FUNCTION RUN_VALUATION_DIAGNOSTICS(pro_forma, WACC, continuing_value, value_per_share):

    diagnostics = {}

    diagnostics["terminal_value_share"] = PV_CV / enterprise_value_operations
    diagnostics["margin_path"] = CHECK_MARGIN_CONVERGENCE(pro_forma)
    diagnostics["ROIC_path"] = CHECK_ROIC_CONVERGENCE(pro_forma)
    diagnostics["growth_path"] = CHECK_GROWTH_CONVERGENCE(pro_forma)
    diagnostics["reinvestment_consistency"] = CHECK_REINVESTMENT_CONSISTENCY(pro_forma)
    diagnostics["balance_sheet_balance"] = CHECK_MODEL_BALANCE(pro_forma)
    diagnostics["valuation_vs_peers"] = COMPARE_WITH_MARKET_MULTIPLES(value_per_share)
    diagnostics["implied_assumptions"] = EXTRACT_IMPLIED_VALUE_DRIVERS()

    RETURN diagnostics
```

Useful warning rules:

```text
IF terminal value > 80%–90% of total value:
    FLAG high dependence on terminal assumptions

IF forecast ROIC remains above WACC forever with no fade:
    FLAG likely too optimistic

IF stable growth > long-run nominal GDP growth:
    FLAG terminal growth issue

IF valuation depends on one extraordinary year:
    FLAG model fragility
```

---

# 14. Step 13 — Sensitivity and scenarios

Valuation is a range, not a single point estimate.

```text
FUNCTION RUN_SENSITIVITY_ANALYSIS(pro_forma, WACC, assumptions):

    VARY:
        WACC
        terminal growth
        operating margin
        revenue growth
        ROIC / RONIC
        capital intensity

    FOR each combination:
        recompute value_per_share

    RETURN sensitivity_table
```

```text
FUNCTION RUN_SCENARIO_ANALYSIS(base_case, upside_case, downside_case):

    DEFINE:
        downside = lower growth, lower margins, lower ROIC, maybe higher WACC
        base = most likely case
        upside = stronger competitive position and economics

    FOR each scenario:
        rerun full valuation

    RETURN scenario_results
```

---

# 15. Alternative branch — Equity valuation instead of enterprise valuation

Sometimes you may value equity directly using FCFE.

```text
FUNCTION VALUE_EQUITY_DIRECTLY(company_data, pro_forma, cost_of_equity):

    FOR each year t:
        FCFE_t = NetIncome_t
                 - NetCapex_t
                 - IncreaseInNoncashWorkingCapital_t
                 + NetDebtIssued_t

    terminal_equity_value = FCFE_(N+1) / (cost_of_equity - g)
    equity_value = PV(FCFE_series, cost_of_equity) + PV(terminal_equity_value)

    RETURN equity_value
```

But for BUSO97-style corporate valuation, enterprise DCF is generally the core route.

---

# 16. Compact exam-style pseudo code

Here is a cleaner “write-on-paper” version.

```text
1. Understand the firm
    - analyze business model, industry, strategy, and risks
    - identify key value drivers: growth, margin, ROIC, reinvestment, WACC

2. Reorganize statements
    - separate operating from non-operating items
    - compute NOPAT
    - compute invested capital

3. Analyze history
    - revenue growth
    - operating margins
    - invested capital turnover
    - ROIC
    - free cash flow patterns

4. Build forecast
    - forecast revenue
    - forecast operating profitability
    - forecast tax on operations
    - forecast invested capital needs
    - derive FCFF

5. Estimate WACC
    - cost of equity
    - cost of debt
    - target capital structure
    - compute weighted average

6. Estimate continuing value
    - choose stable growth
    - choose stable RONIC / ROIC assumptions
    - compute terminal value consistently

7. Discount
    - PV of explicit FCFF
    - PV of continuing value
    - sum = value of operations

8. Bridge to equity value
    - add non-operating assets
    - subtract debt and other non-equity claims

9. Divide by diluted shares
    - obtain value per share

10. Cross-check and interpret
    - compare with economic profit valuation
    - run sensitivity analysis
    - assess realism of assumptions
```

---

# 17. Mini-glossary of the key variables

```text
NOPAT:
    Net operating profit after tax.
    After-tax operating profit before financing effects.

Invested Capital:
    Capital invested in operations.
    Usually operating assets minus operating liabilities.

ROIC:
    Return on invested capital.
    Measures operating profitability relative to operating capital invested.

RONIC:
    Return on new invested capital.
    Important for terminal value because growth requires new investment.

FCFF:
    Free cash flow to the firm.
    Cash flow available to all capital providers.

WACC:
    Weighted average cost of capital.
    Discount rate for FCFF.

Continuing Value / Terminal Value:
    Value of all cash flows beyond explicit forecast horizon.

Economic Profit:
    NOPAT minus capital charge.
    Or (ROIC - WACC) × invested capital.
```

---

# 18. Common valuation mistakes

```text
MISTAKE 1:
    Using accounting numbers without adjustment.

MISTAKE 2:
    Mixing operating and financing items.

MISTAKE 3:
    Forecasting growth without forecasting reinvestment.

MISTAKE 4:
    Assuming margins and ROIC improve without strategic justification.

MISTAKE 5:
    Using an inconsistent discount rate.

MISTAKE 6:
    Treating excess cash as an operating asset.

MISTAKE 7:
    Forgetting minority interests, leases, options, or debt equivalents.

MISTAKE 8:
    Letting terminal value assumptions do all the work.

MISTAKE 9:
    Failing to reconcile DCF value and economic logic.

MISTAKE 10:
    Presenting a point estimate without sensitivity analysis.
```

---

# 19. Best-practice version: “story to numbers” logic

This is very aligned with the lecture framing.

```text
FUNCTION STORY_TO_VALUE(narrative):

    narrative -> assumptions on growth, margins, investment, competitive advantage duration

    assumptions -> pro forma statements

    pro forma statements -> NOPAT, invested capital, FCFF, ROIC

    ROIC + growth + WACC -> enterprise value

    enterprise value -> equity value -> value per share

    THEN ask:
        Does the value match the narrative?
        Are the assumptions economically coherent?
        What must be true for this value to hold?
```

---

# 20. One-line summary formula logic

At the deepest level, the valuation engine is:

```text
Enterprise Value = PV of forecast FCFF + PV of continuing value
```

with continuing value often written as:

```text
CV = NOPAT_(N+1) × (1 - g / RONIC) / (WACC - g)
```

and economic profit version:

```text
Value = Invested Capital today + PV of future Economic Profits
```

These are exactly the core formulas emphasized in the formula sheet and course structure.

---

I can also turn this into a **1-page exam cheat-sheet pseudo code** or a **worked example template with line-by-line formulas**.