# DCF Pipeline Implementation Plan

> **For Claude / Codex:** Use `superpowers:executing-plans` to implement task-by-task.

**Goal:** Build a defensible, human-reviewable DCF pipeline — deterministic engine first, LLM agents layered on top in dependency order.

**Architecture:** Three layers — Data (yfinance/CIQ, deterministic) → Computation (DCF/WACC, deterministic) → Judgment (4 LLM agents, selective). LLM never touches the compute layer.

**Tech Stack:** Python 3.11, yfinance, pandas, openpyxl, anthropic SDK, SQLite (db/), xlwings (CIQ), EDGAR API

**Codex execution pattern:**
```bash
codex exec -m gpt-5-codex -s workspace-write -c model_reasoning_effort=high "<task prompt>"
```

---

## Sprint 1: Deterministic Engine Hardening
**Unblocked. No CIQ, no LLM. Run on current Stage 1 survivors.**
**Done when:** `python -m src.stage_02_valuation.batch_runner` produces output with 3yr data, reverse DCF column, TV% flag, and zero silent failures on 95%+ of tickers.

---

### Task 1.1: Historical financials pull

**Files:**
- Modify: `src/stage_00_data/market_data.py`
- Create: `tests/test_market_data.py`

**Step 1: Write the failing test**
```python
# tests/test_market_data.py
from src.stage_00_data.market_data import get_historical_financials

def test_historical_financials_returns_three_years():
    result = get_historical_financials("MSFT")
    assert "revenue" in result
    assert len(result["revenue"]) >= 3
    assert "operating_income" in result
    assert "capex" in result
    assert "da" in result
    assert "nwc_change" in result

def test_historical_financials_returns_cagr():
    result = get_historical_financials("MSFT")
    assert "revenue_cagr_3yr" in result
    assert isinstance(result["revenue_cagr_3yr"], float)

def test_historical_financials_returns_averages():
    result = get_historical_financials("MSFT")
    assert "op_margin_avg_3yr" in result
    assert "capex_pct_avg_3yr" in result
    assert "da_pct_avg_3yr" in result
    assert "effective_tax_rate_avg" in result
```

**Step 2: Run to verify fail**
```bash
pytest tests/test_market_data.py -v
# Expected: FAIL — get_historical_financials not defined
```

**Step 3: Implement**

Add to `src/stage_00_data/market_data.py`:
```python
def get_historical_financials(ticker: str) -> dict:
    """
    Pull 3-year annual financials from yfinance.
    Returns revenue history, margins, capex, D&A, NWC — all as lists (newest first)
    plus derived averages and CAGR.
    """
    import numpy as np
    t = yf.Ticker(ticker)

    fin = t.financials          # P&L: rows=line items, cols=dates (newest first)
    cf = t.cashflow             # Cash flow statement
    bs = t.balance_sheet        # Balance sheet

    def _row(df, *keys):
        """Extract a row by trying multiple key names, return list of values."""
        if df is None or df.empty:
            return []
        for key in keys:
            if key in df.index:
                vals = df.loc[key].dropna().tolist()
                return [float(v) for v in vals[:3]]  # max 3 years
        return []

    revenue     = _row(fin, "Total Revenue")
    op_income   = _row(fin, "Operating Income", "EBIT")
    net_income  = _row(fin, "Net Income")
    tax_expense = _row(fin, "Tax Provision", "Income Tax Expense")
    pretax_inc  = _row(fin, "Pretax Income")
    capex       = _row(cf,  "Capital Expenditure")
    da          = _row(cf,  "Depreciation And Amortization", "Depreciation")
    curr_assets = _row(bs,  "Current Assets")
    curr_liab   = _row(bs,  "Current Liabilities")
    cash_bs     = _row(bs,  "Cash And Cash Equivalents")

    # capex from yfinance is negative — flip sign
    capex = [abs(v) for v in capex]

    # NWC = (current assets - cash) - current liabilities
    nwc = []
    for i in range(min(len(curr_assets), len(curr_liab), len(cash_bs))):
        nwc.append((curr_assets[i] - cash_bs[i]) - curr_liab[i])
    nwc_change = [nwc[i] - nwc[i+1] for i in range(len(nwc) - 1)]

    def _pct(numerator_list, denominator_list):
        result = []
        for n, d in zip(numerator_list, denominator_list):
            result.append(n / d if d and d != 0 else None)
        return [r for r in result if r is not None]

    op_margins  = _pct(op_income, revenue)
    capex_pcts  = _pct(capex, revenue[:len(capex)])
    da_pcts     = _pct(da, revenue[:len(da)])
    nwc_pcts    = _pct(nwc_change, revenue[:len(nwc_change)])

    # Effective tax rate
    tax_rates = []
    for te, pi in zip(tax_expense, pretax_inc):
        if pi and pi > 0:
            tax_rates.append(te / pi)

    # 3yr revenue CAGR
    cagr = None
    if len(revenue) >= 2:
        n = len(revenue) - 1
        cagr = (revenue[0] / revenue[-1]) ** (1 / n) - 1 if revenue[-1] > 0 else None

    def _avg(lst):
        return float(np.mean(lst)) if lst else None

    return {
        # Raw series (newest first)
        "revenue": revenue,
        "operating_income": op_income,
        "capex": capex,
        "da": da,
        "nwc_change": nwc_change,

        # Derived — use these as DCF inputs
        "revenue_cagr_3yr": round(cagr, 4) if cagr is not None else None,
        "op_margin_avg_3yr": round(_avg(op_margins), 4) if op_margins else None,
        "capex_pct_avg_3yr": round(_avg(capex_pcts), 4) if capex_pcts else None,
        "da_pct_avg_3yr": round(_avg(da_pcts), 4) if da_pcts else None,
        "nwc_pct_avg_3yr": round(_avg(nwc_pcts), 4) if nwc_pcts else None,
        "effective_tax_rate_avg": round(_avg(tax_rates), 4) if tax_rates else None,
    }
```

**Step 4: Run to verify pass**
```bash
pytest tests/test_market_data.py -v
```

**Step 5: Commit**
```bash
git add src/stage_00_data/market_data.py tests/test_market_data.py
git commit -m "feat: add get_historical_financials with 3yr CAGR and averages"
```

**Codex alternative:**
```bash
codex exec -m gpt-5-codex -s workspace-write \
  "Add get_historical_financials(ticker) to src/stage_00_data/market_data.py. \
   Pull 3yr annual revenue, op income, capex, D&A, NWC from yf.Ticker.financials/.cashflow/.balance_sheet. \
   Return dict with raw series + derived: revenue_cagr_3yr, op_margin_avg_3yr, capex_pct_avg_3yr, \
   da_pct_avg_3yr, nwc_pct_avg_3yr, effective_tax_rate_avg. \
   Write tests in tests/test_market_data.py using MSFT as fixture."
```

---

### Task 1.2: Wire historical data into batch_runner assumptions

**Files:**
- Modify: `src/stage_02_valuation/batch_runner.py:127-178` (value_single_ticker)
- Modify: `tests/test_valuation_pipeline.py`

**Step 1: Write failing test**
```python
# tests/test_valuation_pipeline.py
from src.stage_02_valuation.batch_runner import value_single_ticker

def test_value_single_ticker_uses_3yr_cagr_not_ttm():
    result = value_single_ticker("MSFT")
    assert result is not None
    # assumption_source should show historical data was used
    assert result["assumption_source_growth"] in ("historical_3yr", "sector_default")

def test_value_single_ticker_has_audit_columns():
    result = value_single_ticker("MSFT")
    assert result is not None
    for col in ["assumption_source_growth", "assumption_source_margin",
                "assumption_source_capex", "data_quality_score"]:
        assert col in result, f"Missing audit column: {col}"

def test_data_quality_score_between_0_and_1():
    result = value_single_ticker("MSFT")
    assert result is not None
    score = result["data_quality_score"]
    assert 0.0 <= score <= 1.0
```

**Step 2: Run to verify fail**
```bash
pytest tests/test_valuation_pipeline.py::test_value_single_ticker_uses_3yr_cagr_not_ttm -v
```

**Step 3: Update `value_single_ticker` in `src/stage_02_valuation/batch_runner.py`**

Replace lines 133–178 with:
```python
    # 1. Market data (price, sector, beta, shares, debt, cash)
    mkt = md_client.get_market_data(ticker)
    price = mkt.get("current_price")
    rev_ttm = mkt.get("revenue_ttm")
    if not price or not rev_ttm or rev_ttm <= 0:
        return None

    sector = mkt.get("sector", "")
    defaults = _get_sector_defaults(sector)

    # 2. Historical financials (3yr)
    hist = md_client.get_historical_financials(ticker)
    base_revenue = rev_ttm  # always use TTM as starting point for DCF

    # Growth: prefer 3yr CAGR, fallback to TTM YoY, fallback to sector default
    if hist.get("revenue_cagr_3yr") and hist["revenue_cagr_3yr"] > -0.10:
        growth_near = max(min(hist["revenue_cagr_3yr"], 0.35), 0.02)
        source_growth = "historical_3yr"
    elif mkt.get("revenue_growth") and mkt["revenue_growth"] > -0.10:
        growth_near = max(min(mkt["revenue_growth"], 0.30), 0.02)
        source_growth = "ttm_yoy"
    else:
        growth_near = defaults["revenue_growth_near"]
        source_growth = "sector_default"

    growth_mid = growth_near * 0.65

    # Margin: prefer 3yr average, fallback to TTM, fallback to sector default
    if hist.get("op_margin_avg_3yr") and hist["op_margin_avg_3yr"] > 0:
        ebit_margin = hist["op_margin_avg_3yr"]
        source_margin = "historical_3yr_avg"
    elif mkt.get("operating_margin") and mkt["operating_margin"] > 0:
        ebit_margin = mkt["operating_margin"]
        source_margin = "ttm"
    else:
        ebit_margin = defaults.get("ebit_margin_override") or 0.15
        source_margin = "sector_default"

    # Capex/D&A: prefer actuals, fallback to sector defaults
    if hist.get("capex_pct_avg_3yr") and 0 < hist["capex_pct_avg_3yr"] < 0.30:
        capex_pct = hist["capex_pct_avg_3yr"]
        source_capex = "historical_3yr_avg"
    else:
        capex_pct = defaults["capex_pct"]
        source_capex = "sector_default"

    da_pct = hist.get("da_pct_avg_3yr") or defaults["da_pct"]
    nwc_pct = hist.get("nwc_pct_avg_3yr") or 0.01
    tax_rate = hist.get("effective_tax_rate_avg") or 0.21
    if not (0.05 <= tax_rate <= 0.40):  # sanity bounds
        tax_rate = 0.21

    # Data quality score: 1.0 = all actuals, 0.0 = all defaults
    sources = [source_growth, source_margin, source_capex]
    historical_count = sum(1 for s in sources if "historical" in s)
    data_quality_score = round(historical_count / len(sources), 2)

    # 3. WACC
    wacc_result = compute_wacc_from_yfinance(ticker)

    # 4. Net debt, shares
    net_debt = (mkt.get("total_debt") or 0) - (mkt.get("cash") or 0)
    shares = mkt.get("shares_outstanding") or 1
```

Also append to the returned dict:
```python
            # Audit trail
            "assumption_source_growth": source_growth,
            "assumption_source_margin": source_margin,
            "assumption_source_capex": source_capex,
            "data_quality_score": data_quality_score,
```

**Step 4: Run tests**
```bash
pytest tests/test_valuation_pipeline.py -v
```

**Step 5: Commit**
```bash
git add src/stage_02_valuation/batch_runner.py tests/test_valuation_pipeline.py
git commit -m "feat: use 3yr historical financials for DCF assumptions with audit trail"
```

---

### Task 1.3: Add reverse DCF and TV% warning to batch output

**Files:**
- Modify: `src/stage_02_valuation/batch_runner.py` (value_single_ticker return dict + export_to_excel)

**Step 1: Write failing test**
```python
def test_value_single_ticker_has_reverse_dcf():
    result = value_single_ticker("MSFT")
    assert result is not None
    assert "implied_growth_rate" in result
    assert isinstance(result["implied_growth_rate"], float)

def test_value_single_ticker_has_tv_pct_flag():
    result = value_single_ticker("MSFT")
    assert result is not None
    assert "tv_pct_of_ev" in result
    assert "tv_flag" in result  # "HIGH" if tv_pct > 70
```

**Step 2: Run to verify fail**
```bash
pytest tests/test_valuation_pipeline.py::test_value_single_ticker_has_reverse_dcf -v
```

**Step 3: Add reverse DCF solve to `value_single_ticker`**

After `scenarios = run_scenario_dcf(rev, assumptions)`, add:
```python
        # Reverse DCF: solve for implied growth rate at current price
        ev_current = mkt.get("enterprise_value") or 0
        implied_growth = None
        if ev_current > 0:
            lo, hi = -0.05, 0.50
            for _ in range(60):
                mid = (lo + hi) / 2
                test_assum = DCFAssumptions(
                    revenue_growth_near=mid,
                    revenue_growth_mid=mid * 0.65,
                    revenue_growth_terminal=0.03,
                    ebit_margin=ebit_margin,
                    tax_rate=tax_rate,
                    capex_pct_revenue=capex_pct,
                    da_pct_revenue=da_pct,
                    nwc_change_pct_revenue=nwc_pct,
                    wacc=wacc_result.wacc,
                    exit_multiple=defaults["exit_multiple"],
                    net_debt=net_debt,
                    shares_outstanding=shares,
                )
                from src.templates.dcf_model import run_dcf as _run_dcf
                implied_ev = _run_dcf(rev, test_assum).enterprise_value
                if abs(implied_ev - ev_current) / ev_current < 0.005:
                    break
                if implied_ev < ev_current:
                    lo = mid
                else:
                    hi = mid
            implied_growth = round(mid, 4)

        # TV% flag
        base = scenarios["base"]
        tv_pct = round(base.terminal_value / base.enterprise_value * 100, 0) \
            if base.enterprise_value else None
        tv_flag = "HIGH" if tv_pct and tv_pct > 70 else "OK"
```

Add to return dict:
```python
            "implied_growth_rate": round(implied_growth * 100, 1) if implied_growth is not None else None,
            "tv_flag": tv_flag,
```

**Step 4: Run tests**
```bash
pytest tests/test_valuation_pipeline.py -v
```

**Step 5: Commit**
```bash
git add src/stage_02_valuation/batch_runner.py tests/test_valuation_pipeline.py
git commit -m "feat: add reverse DCF implied growth and TV% flag to batch output"
```

---

### Task 1.4: Cost of debt from actuals

**Files:**
- Modify: `src/stage_00_data/market_data.py`
- Modify: `src/stage_02_valuation/wacc.py` (compute_wacc_from_yfinance)

**Step 1: Write failing test**
```python
# tests/test_wacc.py
from src.stage_02_valuation.wacc import compute_wacc_from_yfinance

def test_wacc_uses_derived_cost_of_debt():
    result = compute_wacc_from_yfinance("JPM")  # High debt company
    # Should not default to 6% for everyone
    assert result.wacc > 0
    assert hasattr(result, "cost_of_debt_source")
```

**Step 2: Add interest expense to `get_market_data` and `get_historical_financials`**

In `src/stage_00_data/market_data.py`, add to `get_market_data` return dict:
```python
        "interest_expense": info.get("interestExpense"),
```

In `get_historical_financials`, add:
```python
    interest_exp = _row(fin, "Interest Expense")
    interest_exp = [abs(v) for v in interest_exp]  # usually negative
```

And to the return dict:
```python
        "interest_expense": interest_exp,
        "cost_of_debt_derived": round(
            abs(interest_exp[0]) / max(sum(_row(bs, "Total Debt")[:1] or [1]), 1), 4
        ) if interest_exp else None,
```

**Step 3: Use derived cost of debt in `compute_wacc_from_yfinance`**

In `src/stage_02_valuation/wacc.py`, update `compute_wacc_from_yfinance`:
```python
    hist = None
    try:
        from src.stage_00_data.market_data import get_historical_financials
        hist = get_historical_financials(ticker)
    except Exception:
        pass

    derived_kd = hist.get("cost_of_debt_derived") if hist else None
    # Sanity: derived CoD must be between 2% and 15%
    if derived_kd and 0.02 <= derived_kd <= 0.15:
        cost_of_debt = derived_kd
        kd_source = "derived"
    else:
        cost_of_debt = DEFAULT_COST_OF_DEBT
        kd_source = "default"

    target = PeerData(
        ticker=ticker,
        beta=mkt.get("beta"),
        market_cap=mkt.get("market_cap"),
        total_debt=mkt.get("total_debt"),
        cash=mkt.get("cash"),
        cost_of_debt=cost_of_debt,
    )
```

**Step 4: Run tests**
```bash
pytest tests/test_wacc.py tests/test_market_data.py -v
```

**Step 5: Commit**
```bash
git add src/stage_00_data/market_data.py src/stage_02_valuation/wacc.py tests/test_wacc.py
git commit -m "feat: derive cost of debt from interest expense / total debt"
```

---

### Task 1.5: Sprint 1 end-to-end validation

**Step 1: Run full batch on Stage 1 universe**
```bash
python -m src.stage_02_valuation.batch_runner --top 50
```

**Step 2: Verify acceptance gates**
```bash
python -c "
import pandas as pd
df = pd.read_csv('data/valuations/latest.csv')
total = len(df)
print(f'Coverage: {total} tickers valued')
assert total >= 95, f'Coverage too low: {total}'
# Check audit columns present
for col in ['assumption_source_growth', 'data_quality_score', 'implied_growth_rate', 'tv_flag']:
    assert col in df.columns, f'Missing: {col}'
# Check no NaN in core valuation columns
assert df['iv_base'].notna().mean() > 0.95, 'Too many missing IV values'
print('All acceptance gates passed.')
print(df['assumption_source_growth'].value_counts())
print(df['data_quality_score'].describe())
"
```

**Step 3: Commit**
```bash
git add data/valuations/
git commit -m "chore: Sprint 1 batch valuation output — 3yr data, reverse DCF, TV flags"
```

---

## Sprint 2: CIQ Data Layer
**Blocked until: Excel + CIQ plugin configured.**
**Done when:** `python -m ciq.ciq_refresh` exports data, loads to DB, Stage 2 filter runs on it.

---

### Task 2.1: Define CIQ schema config

**Files:**
- Create: `config/ciq_schema.yaml`
- Create: `tests/test_ciq_loader.py`

**Step 1: Write failing test**
```python
# tests/test_ciq_loader.py
from db.loader import validate_ciq_row

def test_validate_ciq_row_passes_complete_row():
    row = {
        "ticker": "AAPL",
        "revenue_fy1": 400e9,
        "revenue_fy2": 420e9,
        "ebit_fy1": 120e9,
        "net_debt": -50e9,
        "roic_ltm": 0.45,
        "fcf_conversion": 1.1,
        "peers": "MSFT,GOOGL,META",
    }
    assert validate_ciq_row(row) is True

def test_validate_ciq_row_fails_missing_ticker():
    row = {"revenue_fy1": 400e9}
    assert validate_ciq_row(row) is False
```

**Step 2: Create `config/ciq_schema.yaml`**
```yaml
# Canonical CIQ Export field mapping
# Left = CIQ column header (as exported), Right = internal field name
field_map:
  "Ticker":                    ticker
  "Company Name":              company_name
  "Revenue LTM":               revenue_ltm
  "Revenue FY+1E":             revenue_fy1
  "Revenue FY+2E":             revenue_fy2
  "EBIT LTM":                  ebit_ltm
  "EBIT FY+1E":                ebit_fy1
  "EBIT Margin LTM":           ebit_margin_ltm
  "EBIT Margin FY+1E":         ebit_margin_fy1
  "Net Debt":                  net_debt
  "ROIC LTM":                  roic_ltm
  "FCF Conversion LTM":        fcf_conversion
  "EV/EBIT LTM":               ev_ebit_ltm
  "EV/EBITDA LTM":             ev_ebitda_ltm
  "Revenue Growth 3yr CAGR":   revenue_cagr_3yr_ciq
  "EBIT Margin 3yr Avg":       ebit_margin_avg_3yr_ciq
  "Peers":                     peers

required_fields:
  - ticker
  - revenue_ltm
  - ebit_ltm
  - net_debt
```

**Step 3: Create `db/loader.py` validate function**
```python
import yaml
from pathlib import Path

_SCHEMA = None

def _get_schema():
    global _SCHEMA
    if _SCHEMA is None:
        schema_path = Path(__file__).resolve().parent.parent / "config" / "ciq_schema.yaml"
        with open(schema_path) as f:
            _SCHEMA = yaml.safe_load(f)
    return _SCHEMA

def validate_ciq_row(row: dict) -> bool:
    schema = _get_schema()
    required = schema.get("required_fields", [])
    return all(row.get(f) is not None for f in required)

def normalize_ciq_export(df):
    """Rename CIQ column headers to internal field names."""
    schema = _get_schema()
    field_map = schema.get("field_map", {})
    return df.rename(columns=field_map)
```

**Step 4: Run tests**
```bash
pytest tests/test_ciq_loader.py -v
```

**Step 5: Commit**
```bash
git add config/ciq_schema.yaml db/loader.py tests/test_ciq_loader.py
git commit -m "feat: CIQ schema config and row validation"
```

---

### Task 2.2: Complete CIQ export ingestion

**Files:**
- Modify: `ciq/ciq_refresh.py:83-126` (extract_and_load)
- Modify: `db/loader.py`

**Step 1: Write failing test**
```python
def test_load_ciq_csv_to_db(tmp_path):
    from db.loader import load_ciq_csv
    import pandas as pd

    # Minimal valid CIQ export
    df = pd.DataFrame([{
        "Ticker": "AAPL", "Revenue LTM": 400e9, "EBIT LTM": 120e9,
        "Net Debt": -50e9, "Company Name": "Apple Inc",
        "ROIC LTM": 0.45, "FCF Conversion LTM": 1.1,
    }])
    csv_path = tmp_path / "test_ciq.csv"
    df.to_csv(csv_path, index=False)

    db_path = tmp_path / "test.db"
    result = load_ciq_csv(csv_path, db_path=db_path)
    assert result["rows_loaded"] == 1
    assert result["rows_failed"] == 0
```

**Step 2: Add `load_ciq_csv` to `db/loader.py`**
```python
import sqlite3
import pandas as pd
from pathlib import Path
from config.settings import DB_PATH

def load_ciq_csv(csv_path: Path, db_path: Path = DB_PATH) -> dict:
    """
    Load normalized CIQ export CSV into SQLite ciq_fundamentals table.
    Returns counts of rows loaded and failed.
    """
    df = pd.read_csv(csv_path)
    df = normalize_ciq_export(df)

    rows_loaded = 0
    rows_failed = 0
    failed_tickers = []

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ciq_fundamentals (
                ticker TEXT PRIMARY KEY,
                company_name TEXT,
                revenue_ltm REAL,
                revenue_fy1 REAL,
                revenue_fy2 REAL,
                ebit_ltm REAL,
                ebit_fy1 REAL,
                ebit_margin_ltm REAL,
                ebit_margin_fy1 REAL,
                net_debt REAL,
                roic_ltm REAL,
                fcf_conversion REAL,
                ev_ebit_ltm REAL,
                ev_ebitda_ltm REAL,
                revenue_cagr_3yr_ciq REAL,
                ebit_margin_avg_3yr_ciq REAL,
                peers TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        for _, row in df.iterrows():
            if not validate_ciq_row(row.to_dict()):
                rows_failed += 1
                failed_tickers.append(row.get("ticker", "unknown"))
                continue
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO ciq_fundamentals
                    (ticker, company_name, revenue_ltm, revenue_fy1, revenue_fy2,
                     ebit_ltm, ebit_fy1, ebit_margin_ltm, ebit_margin_fy1,
                     net_debt, roic_ltm, fcf_conversion, ev_ebit_ltm, ev_ebitda_ltm,
                     revenue_cagr_3yr_ciq, ebit_margin_avg_3yr_ciq, peers, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """, (
                    row.get("ticker"), row.get("company_name"),
                    row.get("revenue_ltm"), row.get("revenue_fy1"), row.get("revenue_fy2"),
                    row.get("ebit_ltm"), row.get("ebit_fy1"),
                    row.get("ebit_margin_ltm"), row.get("ebit_margin_fy1"),
                    row.get("net_debt"), row.get("roic_ltm"), row.get("fcf_conversion"),
                    row.get("ev_ebit_ltm"), row.get("ev_ebitda_ltm"),
                    row.get("revenue_cagr_3yr_ciq"), row.get("ebit_margin_avg_3yr_ciq"),
                    row.get("peers"),
                ))
                rows_loaded += 1
            except Exception as e:
                rows_failed += 1
                failed_tickers.append(row.get("ticker", "unknown"))

    return {
        "rows_loaded": rows_loaded,
        "rows_failed": rows_failed,
        "failed_tickers": failed_tickers,
    }
```

**Step 3: Run tests**
```bash
pytest tests/test_ciq_loader.py -v
```

**Step 4: Commit**
```bash
git add db/loader.py tests/test_ciq_loader.py
git commit -m "feat: load_ciq_csv normalizes headers and upserts to SQLite"
```

---

## Sprint 3: Quality of Earnings Agent
**Unblocked. Uses EDGAR — no CIQ needed.**
**Done when:** Agent returns adjusted EBIT margin and one-time item flags for any S&P 1500 ticker with a 10-K on file.

---

### Task 3.1: EDGAR 10-K text fetch

**Files:**
- Modify: `src/stage_00_data/edgar_client.py`
- Create: `tests/test_edgar_client.py`

**Step 1: Write failing test**
```python
# tests/test_edgar_client.py
from src.stage_00_data.edgar_client import get_latest_10k_text, get_10k_sections

def test_get_latest_10k_returns_text():
    text = get_latest_10k_text("AAPL")
    assert text is not None
    assert len(text) > 10_000  # 10-K should be substantial

def test_get_10k_sections_returns_mda_and_risk():
    sections = get_10k_sections("AAPL")
    assert "mda" in sections
    assert "risk_factors" in sections
    assert len(sections["mda"]) > 1000
```

**Step 2: Implement**

Read current `src/stage_00_data/edgar_client.py` first, then add:
```python
import requests
import re

EDGAR_BASE = "https://data.sec.gov/submissions"
HEADERS = {"User-Agent": "alpha-pod research@example.com"}  # SEC requires this

def get_latest_10k_url(ticker: str) -> str | None:
    """Get the URL of the most recent 10-K filing for a ticker."""
    # Look up CIK via SEC company search
    search_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
    resp = requests.get(
        f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=10-K",
        headers=HEADERS, timeout=15
    )
    if not resp.ok:
        return None
    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None
    # Most recent first
    filing = hits[0]["_source"]
    accession = filing.get("file_date", "")
    entity_id = filing.get("entity_id", "")
    file_url = filing.get("file_url", "")
    return file_url if file_url else None

def get_latest_10k_text(ticker: str, max_chars: int = 200_000) -> str | None:
    """
    Fetch the full text of the most recent 10-K for a ticker.
    Returns first max_chars characters (enough for MD&A + risk factors).
    """
    import yfinance as yf
    t = yf.Ticker(ticker)

    # yfinance exposes SEC filings
    try:
        filings = t.get_sec_tickers()
    except Exception:
        filings = None

    # Fallback: use SEC EDGAR full-text search
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=10-K"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if not resp.ok:
        return None

    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None

    doc_url = hits[0].get("_source", {}).get("file_url", "")
    if not doc_url:
        return None

    doc_resp = requests.get(f"https://efts.sec.gov{doc_url}", headers=HEADERS, timeout=30)
    if not doc_resp.ok:
        return None

    return doc_resp.text[:max_chars]

def get_10k_sections(ticker: str) -> dict:
    """
    Extract key sections from the 10-K: MD&A and Risk Factors.
    Returns dict with 'mda' and 'risk_factors' keys.
    """
    text = get_latest_10k_text(ticker)
    if not text:
        return {"mda": "", "risk_factors": ""}

    # Simple section extraction by header patterns
    def extract_section(text, start_patterns, end_patterns, max_len=40_000):
        text_upper = text.upper()
        start_idx = -1
        for pat in start_patterns:
            idx = text_upper.find(pat.upper())
            if idx != -1:
                start_idx = idx
                break
        if start_idx == -1:
            return ""
        end_idx = len(text)
        for pat in end_patterns:
            idx = text_upper.find(pat.upper(), start_idx + 100)
            if idx != -1:
                end_idx = min(end_idx, idx)
        return text[start_idx:min(start_idx + max_len, end_idx)]

    mda = extract_section(
        text,
        ["ITEM 7.", "ITEM 7 .", "MANAGEMENT'S DISCUSSION"],
        ["ITEM 7A.", "ITEM 8.", "QUANTITATIVE AND QUALITATIVE"],
    )
    risk = extract_section(
        text,
        ["ITEM 1A.", "RISK FACTORS"],
        ["ITEM 1B.", "ITEM 2.", "UNRESOLVED STAFF COMMENTS"],
    )
    return {"mda": mda, "risk_factors": risk}
```

**Step 3: Run tests**
```bash
pytest tests/test_edgar_client.py -v
```

**Step 4: Commit**
```bash
git add src/stage_00_data/edgar_client.py tests/test_edgar_client.py
git commit -m "feat: EDGAR 10-K text fetch with MD&A and risk factor extraction"
```

---

### Task 3.2: Quality of Earnings Agent

**Files:**
- Create: `src/stage_03_judgment/qoe_agent.py`
- Create: `tests/test_qoe_agent.py`

**Step 1: Write failing test**
```python
# tests/test_qoe_agent.py
from src.stage_03_judgment.qoe_agent import QoEAgent, QoEResult

def test_qoe_agent_returns_result_schema():
    agent = QoEAgent()
    result = agent.analyze("AAPL")
    assert isinstance(result, QoEResult)
    assert result.ticker == "AAPL"
    assert result.adjusted_ebit_margin is not None
    assert isinstance(result.one_time_items, list)
    assert result.earnings_quality_score in ("HIGH", "MEDIUM", "LOW")

def test_qoe_result_has_adjustment_magnitude():
    agent = QoEAgent()
    result = agent.analyze("AAPL")
    # Adjustment should be within plausible range
    assert -0.15 <= result.margin_adjustment <= 0.15
```

**Step 2: Create `src/stage_03_judgment/qoe_agent.py`**
```python
"""
Quality of Earnings Agent.

Reads 10-K MD&A + footnotes + financial statement notes.
Classifies one-time items, adjusts reported EBIT margin to normalized.
Runs per ticker after each annual filing.

Input: ticker (str), optionally FilingsSummary
Output: QoEResult — adjusted margin, one-time flags, quality score
"""

import json
from dataclasses import dataclass, field
from anthropic import Anthropic

from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_00_data import market_data as md_client
from src.stage_00_data.edgar_client import get_10k_sections


@dataclass
class OneTimeItem:
    description: str
    amount_mm: float        # positive = income boost, negative = expense hit
    classification: str     # "restructuring", "impairment", "legal", "gain_on_sale", "other"
    recurring_probability: float  # 0-1: how likely to recur


@dataclass
class QoEResult:
    ticker: str
    reported_ebit_margin: float
    adjusted_ebit_margin: float
    margin_adjustment: float        # adjusted - reported
    one_time_items: list[OneTimeItem] = field(default_factory=list)
    earnings_quality_score: str = "MEDIUM"  # HIGH / MEDIUM / LOW
    ocf_to_ni_ratio: float = None
    dso_trend: str = None           # "IMPROVING" / "STABLE" / "DETERIORATING"
    commentary: str = ""


SYSTEM_PROMPT = """You are a forensic accounting analyst specializing in earnings quality assessment.

Your job is to read a company's MD&A and financial statement notes and:
1. Identify one-time, non-recurring items that distort reported EBIT
2. Classify each item: restructuring, impairment, legal settlement, gain/loss on asset sale, other
3. Estimate the dollar magnitude of each adjustment
4. Compute an adjusted (normalized) EBIT margin
5. Assess overall earnings quality: HIGH / MEDIUM / LOW

Rules:
- Be specific. Every adjustment must cite the source text.
- "Recurring restructuring" is NOT one-time — if a company restructures every 2 years, it's an ongoing cost.
- Stock-based compensation: note it but do not adjust EBIT (it's a real expense).
- When in doubt, do NOT adjust — conservative bias.
- Quantify in millions USD.

Output ONLY valid JSON in this exact schema:
{
  "adjusted_ebit_margin": <float>,
  "margin_adjustment": <float>,
  "one_time_items": [
    {
      "description": "<what it is>",
      "amount_mm": <float, positive=income, negative=expense>,
      "classification": "<restructuring|impairment|legal|gain_on_sale|other>",
      "recurring_probability": <0.0-1.0>
    }
  ],
  "earnings_quality_score": "<HIGH|MEDIUM|LOW>",
  "dso_trend": "<IMPROVING|STABLE|DETERIORATING|UNKNOWN>",
  "commentary": "<2-3 sentences on key findings>"
}"""


class QoEAgent:
    def __init__(self):
        self.client = Anthropic()

    def analyze(self, ticker: str) -> QoEResult:
        mkt = md_client.get_market_data(ticker)
        reported_margin = mkt.get("operating_margin") or 0
        revenue = mkt.get("revenue_ttm") or 1

        # Get 10-K sections
        sections = get_10k_sections(ticker)
        mda_text = sections.get("mda", "")[:30_000]
        risk_text = sections.get("risk_factors", "")[:10_000]

        # Compute OCF/NI ratio
        fcf = mkt.get("free_cashflow") or 0
        net_income = (mkt.get("profit_margin") or 0) * revenue
        ocf_ni = round(fcf / net_income, 2) if net_income and net_income != 0 else None

        prompt = f"""Analyze earnings quality for {ticker.upper()}.

Reported operating margin: {reported_margin*100:.1f}%
TTM revenue: ${revenue/1e9:.1f}B
OCF/Net Income ratio: {ocf_ni if ocf_ni else 'N/A'}

--- MD&A (excerpt) ---
{mda_text}

--- Risk Factors (excerpt) ---
{risk_text}

Identify all material one-time items. Compute adjusted EBIT margin.
Output JSON only."""

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # cheap + fast for classification
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
        except Exception:
            # Fallback: no adjustment
            return QoEResult(
                ticker=ticker,
                reported_ebit_margin=reported_margin,
                adjusted_ebit_margin=reported_margin,
                margin_adjustment=0.0,
                earnings_quality_score="MEDIUM",
                ocf_to_ni_ratio=ocf_ni,
                commentary="Could not parse 10-K text.",
            )

        items = [
            OneTimeItem(
                description=i.get("description", ""),
                amount_mm=i.get("amount_mm", 0),
                classification=i.get("classification", "other"),
                recurring_probability=i.get("recurring_probability", 0.5),
            )
            for i in data.get("one_time_items", [])
        ]

        return QoEResult(
            ticker=ticker,
            reported_ebit_margin=reported_margin,
            adjusted_ebit_margin=data.get("adjusted_ebit_margin", reported_margin),
            margin_adjustment=data.get("margin_adjustment", 0.0),
            one_time_items=items,
            earnings_quality_score=data.get("earnings_quality_score", "MEDIUM"),
            ocf_to_ni_ratio=ocf_ni,
            dso_trend=data.get("dso_trend", "UNKNOWN"),
            commentary=data.get("commentary", ""),
        )
```

**Step 3: Run tests**
```bash
pytest tests/test_qoe_agent.py -v
# Note: requires ANTHROPIC_API_KEY set
```

**Step 4: Commit**
```bash
git add src/stage_03_judgment/qoe_agent.py tests/test_qoe_agent.py
git commit -m "feat: Quality of Earnings agent — normalize EBIT from 10-K footnotes"
```

---

### Task 3.3: Wire QoE into batch_runner (optional flag)

**Files:**
- Modify: `src/stage_02_valuation/batch_runner.py`

Add `--qoe` flag: when set, run QoE agent before computing DCF and use `adjusted_ebit_margin` instead of raw margin.

```python
# In value_single_ticker, after margin derivation:
if use_qoe:
    from src.stage_03_judgment.qoe_agent import QoEAgent
    qoe = QoEAgent().analyze(ticker)
    if qoe.margin_adjustment != 0:
        ebit_margin = qoe.adjusted_ebit_margin
        source_margin = f"qoe_adjusted ({qoe.earnings_quality_score})"
```

```bash
git commit -m "feat: --qoe flag wires QoE agent into batch_runner margin assumption"
```

---

## Sprint 4: Comps Matching Agent
**Blocked until Sprint 2 (CIQ) complete.**
**Done when:** Agent takes CIQ peer list, scores each by business similarity, returns ranked top-10 with WACC and exit multiple calibration.

---

### Task 4.1: Comps Matching Agent

**Files:**
- Create: `src/stage_03_judgment/comps_agent.py`
- Create: `tests/test_comps_agent.py`

**Step 1: Write failing test**
```python
from src.stage_03_judgment.comps_agent import CompsAgent, CompsResult

def test_comps_agent_returns_ranked_peers():
    # Requires CIQ data in DB for these tickers
    agent = CompsAgent()
    result = agent.match("HALO", ciq_peer_list=["IONS", "ALNY", "MDLZ", "AMGN", "REGN"])
    assert isinstance(result, CompsResult)
    assert len(result.selected_peers) <= 10
    assert len(result.selected_peers) >= 1
    assert result.suggested_exit_multiple > 0
    # Each selected peer should have a similarity score
    for peer in result.selected_peers:
        assert "ticker" in peer
        assert "similarity_score" in peer
        assert 0 <= peer["similarity_score"] <= 1
```

**Step 2: Create `src/stage_03_judgment/comps_agent.py`**

See pattern from `qoe_agent.py`. Agent:
- Takes target ticker + CIQ peer list (~50 tickers)
- Fetches business description for each via yfinance `.info["longBusinessSummary"]`
- Asks LLM to score each peer 0-1 on business similarity
- Returns top 10 ranked peers
- Computes median EV/EBIT of selected peers → `suggested_exit_multiple`
- These peers feed `compute_wacc_from_yfinance(ticker, peer_tickers=result.peer_tickers)`

```bash
git commit -m "feat: Comps Matching agent scores CIQ peers by business similarity"
```

---

## Sprint 5: Industry Research Agent
**Unblocked. Runs independently, weekly per sector.**
**Done when:** Agent outputs structured sector report — TAM, growth rates, margin benchmarks, valuation framework — consumed by batch_runner as assumption override layer.

---

### Task 5.1: Industry Research Agent + weekly cache

**Files:**
- Create: `src/stage_03_judgment/industry_agent.py`
- Create: `data/industry_cache/` (output dir)
- Create: `tests/test_industry_agent.py`

**Step 1: Write failing test**
```python
from src.stage_03_judgment.industry_agent import IndustryAgent, IndustryReport

def test_industry_agent_returns_report():
    agent = IndustryAgent()
    report = agent.research("Technology", "Application Software")
    assert isinstance(report, IndustryReport)
    assert report.sector == "Technology"
    assert 0 < report.consensus_growth_near < 0.50
    assert report.valuation_framework in (
        "DCF", "Rule_of_40", "EV_Revenue", "EV_EBITDA", "Normalized_Earnings"
    )

def test_industry_report_is_cached():
    agent = IndustryAgent()
    report1 = agent.research("Technology", "Application Software")
    report2 = agent.research("Technology", "Application Software")
    # Second call should be from cache (same object or same values)
    assert report1.consensus_growth_near == report2.consensus_growth_near
```

**Step 2: Agent design**
- Uses `perplexity_research` MCP tool or Anthropic web search for current sector data
- Output: `IndustryReport` dataclass with growth, margin benchmarks, framework, key risks
- Cache as JSON in `data/industry_cache/{sector}_{industry}_{YYYY-WW}.json` (weekly)
- batch_runner checks cache age, uses if < 7 days old

```bash
git commit -m "feat: Industry Research agent with weekly sector cache"
```

---

## Sprint 6: Scenario / Catalyst Agent
**Unblocked. Uses EDGAR + news.**
**Done when:** Agent replaces generic ±40% scalars with 2-3 named, probability-weighted scenarios derived from actual 10-K risk factors and recent news.

---

### Task 6.1: Scenario Agent

**Files:**
- Create: `src/stage_03_judgment/scenario_agent.py`
- Create: `tests/test_scenario_agent.py`

**Step 1: Write failing test**
```python
from src.stage_03_judgment.scenario_agent import ScenarioAgent, ScenarioSet

def test_scenario_agent_returns_named_scenarios():
    agent = ScenarioAgent()
    result = agent.build_scenarios("AAPL")
    assert isinstance(result, ScenarioSet)
    assert len(result.scenarios) >= 2
    for s in result.scenarios:
        assert s.name != ""
        assert 0 < s.probability <= 1.0
        assert s.growth_adjustment is not None  # multiplier vs base
        assert s.margin_adjustment is not None

def test_scenario_probabilities_sum_to_1():
    agent = ScenarioAgent()
    result = agent.build_scenarios("AAPL")
    total = sum(s.probability for s in result.scenarios)
    assert abs(total - 1.0) < 0.05  # within 5%
```

**Step 2: Agent design**
- Reads `get_10k_sections(ticker)["risk_factors"]` + recent news headlines
- Constructs 3 scenarios: bear (name it), base (name it), bull (name it)
- Each scenario has: name, description, probability, growth_adjustment, margin_adjustment
- These replace the generic 0.6x/1.0x/1.4x scalars in `run_scenario_dcf`

```bash
git commit -m "feat: Scenario agent builds named probability-weighted scenarios from 10-K risks"
```

---

## Codex CLI Execution Reference

Each sprint can be handed to Codex CLI. Use this pattern:

```bash
# Sprint 1 — deterministic, safe to give workspace-write access
codex exec -m gpt-5-codex -s workspace-write \
  "Implement Task 1.1 from docs/plans/2026-03-06-dcf-pipeline.md. \
   Add get_historical_financials() to src/stage_00_data/market_data.py. \
   Write tests first in tests/test_market_data.py. \
   Run tests before committing."

# Sprint 3 — agent code, reads API
codex exec -m gpt-5-codex -s workspace-write \
  "Implement Task 3.2 from docs/plans/2026-03-06-dcf-pipeline.md. \
   Create src/stage_03_judgment/qoe_agent.py using the Anthropic SDK. \
   Follow the exact QoEResult dataclass schema in the plan."

# Analysis / review tasks
codex exec -m gpt-5 -s read-only \
  "Review src/stage_02_valuation/batch_runner.py and src/stage_00_data/market_data.py. \
   List every place where a sector default is used instead of actual data. \
   Output a table: location, what's hardcoded, what should replace it."
```

---

## Dependency Graph

```
Sprint 1 (deterministic hardening)     ← START HERE, unblocked
    |
Sprint 2 (CIQ data layer)              ← needs Excel + CIQ plugin configured
    |
    +-- Sprint 4 (Comps agent)         ← blocked on Sprint 2
    |
Sprint 3 (QoE agent)                   ← unblocked, runs parallel to Sprint 2
Sprint 5 (Industry agent)              ← unblocked, runs parallel to Sprint 2
Sprint 6 (Scenario agent)              ← unblocked, runs parallel to Sprint 2
```

## Acceptance Gates per Sprint

| Sprint | Gate |
|--------|------|
| 1 | `batch_runner` values 95%+ of universe, all audit columns present, <15 min runtime |
| 2 | `ciq_refresh` loads to DB, Stage 2 filter runs, zero schema errors |
| 3 | QoE agent classifies one-time items for 10 test tickers, margin delta <±15% |
| 4 | Comps agent selects 5-10 peers, WACC changes vs self-beta on 5 test tickers |
| 5 | Industry cache populated for all 8 sectors, growth rates within published ranges |
| 6 | Scenario agent names match actual business risks, probabilities sum to ~1.0 |


