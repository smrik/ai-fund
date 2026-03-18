"""Manual EDGAR smoke script.

This is not part of the automated test suite. Run it manually when validating
the external `edgar` package behavior against a live ticker.
"""

from edgar import Company, set_identity


def main() -> None:
    set_identity("AI Fund Manager ai-fund@example.com")
    company = Company("MSFT")

    tenk = company.get_filings(form="10-K").latest()
    print(f"10-K length: {len(tenk.text())}")

    facts = company.get_facts()
    income_df = facts.income_statement(as_dataframe=True)
    print(income_df.head())

    revenue_query = facts.query().by_concept("Revenue").latest_periods(3, annual=True).to_dataframe()
    print(revenue_query.head())

    financials = company.get_financials()
    metrics = financials.get_financial_metrics()
    print(metrics)


if __name__ == "__main__":
    main()
