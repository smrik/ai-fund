import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_00_data import edgar_client


def test_get_10k_text_returns_latest_text_from_edgartools(monkeypatch):
    mock_company = MagicMock()
    mock_filings = MagicMock()
    mock_filing = MagicMock()

    mock_company.get_filings.return_value = mock_filings
    mock_filings.empty = False
    mock_filings.latest.return_value = mock_filing
    mock_filing.text.return_value = "This is a full 10-K text."

    monkeypatch.setattr(edgar_client, "Company", lambda ticker: mock_company)

    text = edgar_client.get_10k_text("IBM", max_chars=10)
    assert text == "This is a "
    mock_company.get_filings.assert_called_with(form="10-K")


def test_get_recent_10q_texts_returns_list_of_texts(monkeypatch):
    mock_company = MagicMock()
    mock_filings_list = [MagicMock(), MagicMock()]
    mock_filings_list[0].text.return_value = "Quarterly update 1"
    mock_filings_list[0].filing_date = "2026-06-30"
    mock_filings_list[0].accession_no = "acc-1"
    
    mock_filings_list[1].text.return_value = "Quarterly update 2"
    mock_filings_list[1].filing_date = "2026-03-31"
    mock_filings_list[1].accession_no = "acc-2"

    mock_filings = MagicMock()
    mock_filings.head.return_value = mock_filings_list
    mock_company.get_filings.return_value = mock_filings

    monkeypatch.setattr(edgar_client, "Company", lambda ticker: mock_company)

    results = edgar_client.get_recent_10q_texts("IBM", limit=2, max_chars_each=20)
    assert len(results) == 2
    assert results[0]["text"] == "Quarterly update 1"
    assert results[1]["text"] == "Quarterly update 2"


def test_get_8k_texts_returns_list_of_texts(monkeypatch):
    mock_company = MagicMock()
    mock_filing = MagicMock()
    mock_filing.text.return_value = "8-K event: CEO resigned."
    mock_filing.filing_date = "2026-05-01"
    mock_filing.accession_no = "acc-8k"

    mock_filings = MagicMock()
    mock_filings.head.return_value = [mock_filing]
    mock_company.get_filings.return_value = mock_filings

    monkeypatch.setattr(edgar_client, "Company", lambda ticker: mock_company)

    results = edgar_client.get_8k_texts("IBM", limit=1, max_chars_each=12)
    assert len(results) == 1
    assert results[0]["text"] == "8-K event: C"


def test_extract_financial_facts_returns_structured_metrics(monkeypatch):
    import pandas as pd
    
    mock_company = MagicMock()
    mock_facts = MagicMock()
    mock_company.get_facts.return_value = mock_facts

    mock_query_builder = MagicMock()
    mock_facts.query.return_value = mock_query_builder
    
    mock_query_concept = MagicMock()
    mock_query_builder.by_concept.return_value = mock_query_concept
    
    mock_query_quality = MagicMock()
    mock_query_concept.high_quality_only.return_value = mock_query_quality

    # Create a mock dataframe that to_dataframe will return
    df = pd.DataFrame([
        {"numeric_value": 1000.0, "form_type": "10-K", "fiscal_period": "FY", "period_end": "2023-12-31", "unit": "USD"}
    ])
    
    # We want it to be empty for everything except "Revenues" to limit the test scope
    def fake_to_dataframe():
        # Using sys._getframe to hack checking what concept was passed, 
        # but simpler: just return the df and let it map to multiple
        return df

    mock_query_quality.to_dataframe.side_effect = fake_to_dataframe

    monkeypatch.setattr(edgar_client, "Company", lambda ticker: mock_company)

    extracted = edgar_client.extract_financial_facts("IBM")
    
    assert isinstance(extracted, list)
    assert len(extracted) > 0
    # Items are sorted alphabetically by metric name ("Capex", "EarningsPerShareBasic", ...)
    metrics_returned = [x["metric"] for x in extracted]
    assert "Revenues" in metrics_returned
    
    rev_item = next(x for x in extracted if x["metric"] == "Revenues")
    assert rev_item["value"] == 1000.0
    assert rev_item["form"] == "10-K"
    assert "2023-12-31" in rev_item["end"]
