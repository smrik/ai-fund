from __future__ import annotations

from datetime import date

from edgar.entity.models import DataQuality, FinancialFact

from src.stage_00_data.xbrl_evidence import (
    get_xbrl_fact_evidence,
    normalize_financial_fact,
)


def _fact(**overrides) -> FinancialFact:
    values = {
        "concept": "us-gaap:OperatingLeaseLiability",
        "taxonomy": "us-gaap",
        "label": "Operating lease liability",
        "value": 125000000,
        "numeric_value": 125000000.0,
        "unit": "USD",
        "period_end": date(2025, 6, 30),
        "period_type": "instant",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "filing_date": date(2025, 7, 30),
        "form_type": "10-K",
        "accession": "0000950170-25-100235",
        "data_quality": DataQuality.HIGH,
        "is_audited": True,
        "confidence_score": 0.99,
        "context_ref": "D2025",
        "dimensions": {"us-gaap:ProductOrServiceAxis": "msft:CloudMember"},
        "statement_type": "BalanceSheet",
        "section": "Noncurrent liabilities",
        "line_item_sequence": 17,
        "depth": 2,
        "parent_concept": "us-gaap:Liabilities",
        "presentation_order": 12.0,
    }
    values.update(overrides)
    return FinancialFact(**values)


def test_normalize_financial_fact_preserves_provenance_and_dimensions():
    record = normalize_financial_fact(_fact(), ticker="MSFT", cik="0000789019")

    assert record["fact_id"].startswith("xbrl:MSFT:0000950170-25-100235:")
    assert record["fact_name"] == "us-gaap:OperatingLeaseLiability"
    assert record["value"] == 125000000
    assert record["numeric_value"] == 125000000.0
    assert record["period"] == "2025-06-30"
    assert record["source_locator"] == (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000095017025100235-index.html"
    )
    assert record["metadata"]["taxonomy"] == "us-gaap"
    assert record["metadata"]["accession"] == "0000950170-25-100235"
    assert record["metadata"]["context_ref"] == "D2025"
    assert record["metadata"]["dimensions"] == {
        "us-gaap:ProductOrServiceAxis": "msft:CloudMember"
    }
    assert record["metadata"]["statement_type"] == "BalanceSheet"
    assert record["metadata"]["data_quality"] == "high"


def test_normalize_financial_fact_keeps_duration_period():
    record = normalize_financial_fact(
        _fact(
            concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            period_start=date(2024, 7, 1),
            period_end=date(2025, 6, 30),
            period_type="duration",
            value=281724000000,
            numeric_value=281724000000.0,
        ),
        ticker="MSFT",
        cik="0000789019",
    )

    assert record["period"] == "2024-07-01/2025-06-30"
    assert record["metadata"]["period_type"] == "duration"


def test_get_xbrl_fact_evidence_uses_fact_objects_and_returns_status(monkeypatch):
    fact = _fact()

    class FakeQuery:
        def by_concept(self, concept):
            assert concept == "OperatingLeaseLiability"
            return self

        def execute(self):
            return [fact]

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        cik = "0000789019"

        def __init__(self, ticker):
            assert ticker == "MSFT"

        def get_facts(self):
            return FakeFacts()

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_fact_evidence("MSFT", ["OperatingLeaseLiability"])

    assert result["status"] == "ok"
    assert result["fact_count"] == 1
    assert result["facts"][0]["metadata"]["accession"] == "0000950170-25-100235"


def test_get_xbrl_fact_evidence_distinguishes_no_facts(monkeypatch):
    class FakeCompany:
        cik = "0000789019"

        def __init__(self, ticker):
            pass

        def get_facts(self):
            return None

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_fact_evidence("MSFT", ["OperatingLeaseLiability"])

    assert result["status"] == "no_facts"
    assert result["facts"] == []
    assert result["fact_count"] == 0


def test_get_xbrl_fact_evidence_reports_adapter_errors(monkeypatch):
    class FakeCompany:
        def __init__(self, ticker):
            raise RuntimeError("SEC unavailable")

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_fact_evidence("MSFT", ["OperatingLeaseLiability"])

    assert result["status"] == "error"
    assert result["facts"] == []
    assert "SEC unavailable" in result["error"]
    assert result["errors"] == [result["error"]]


def test_get_xbrl_fact_evidence_respects_cache_only(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_EDGAR_CACHE_ONLY", "1")

    class ForbiddenCompany:
        def __init__(self, ticker):
            raise AssertionError("cache-only XBRL retrieval must not construct Company")

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        ForbiddenCompany,
    )

    result = get_xbrl_fact_evidence("MSFT", ["OperatingLeaseLiability"])

    assert result["status"] == "cache_only_unavailable"
    assert result["facts"] == []
    assert result["fact_count"] == 0
    assert result["errors"] == [result["error"]]


def test_get_xbrl_fact_evidence_caps_to_newest_filing_vintage(monkeypatch):
    old_fact = _fact(
        accession="0000000-20-000001",
        filing_date=date(2020, 7, 30),
        period_end=date(2020, 6, 30),
        context_ref="OLD",
    )
    new_fact = _fact(
        accession="0000000-25-000001",
        filing_date=date(2025, 7, 30),
        period_end=date(2025, 6, 30),
        context_ref="NEW",
    )

    class FakeQuery:
        def by_concept(self, concept):
            return self

        def execute(self):
            return [old_fact, new_fact]

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        cik = "0000789019"

        def __init__(self, ticker):
            pass

        def get_facts(self):
            return FakeFacts()

    monkeypatch.delenv("ALPHA_POD_EDGAR_CACHE_ONLY", raising=False)
    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_fact_evidence(
        "MSFT",
        ["OperatingLeaseLiability"],
        max_facts_per_concept=1,
    )

    assert result["status"] == "ok"
    assert result["facts"][0]["metadata"]["accession"] == "0000000-25-000001"


def test_get_xbrl_fact_evidence_filters_fuzzy_related_concepts(monkeypatch):
    exact_fact = _fact(concept="us-gaap:OperatingLeaseLiability", context_ref="EXACT")
    related_fact = _fact(
        concept="us-gaap:RightOfUseAssetObtainedInExchangeForOperatingLeaseLiability",
        context_ref="RELATED",
    )

    class FakeQuery:
        def by_concept(self, concept):
            return self

        def execute(self):
            return [related_fact, exact_fact]

    class FakeFacts:
        def query(self):
            return FakeQuery()

    class FakeCompany:
        cik = "0000789019"

        def __init__(self, ticker):
            pass

        def get_facts(self):
            return FakeFacts()

    monkeypatch.delenv("ALPHA_POD_EDGAR_CACHE_ONLY", raising=False)
    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_fact_evidence("MSFT", ["OperatingLeaseLiability"])

    assert result["status"] == "ok"
    assert result["fact_count"] == 1
    assert result["facts"][0]["fact_name"] == "us-gaap:OperatingLeaseLiability"
