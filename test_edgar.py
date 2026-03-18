import json
from edgar import Company, set_identity

set_identity("AI Fund Manager ai-fund@example.com")
company = Company("MSFT")

# Test 10-K text parsing
tenk = company.get_filings(form="10-K").latest()
print(f"10-K length: {len(tenk.text())}")

# Test XBRL metrics
facts = company.get_facts()

income_df = facts.income_statement(as_dataframe=True)
print(income_df.head())

revenue_query = facts.query().by_concept("Revenue").latest_periods(3, annual=True).to_dataframe()
print(revenue_query.head())

# Try generic metrics
financials = company.get_financials()
metrics = financials.get_financial_metrics()
print(metrics)
