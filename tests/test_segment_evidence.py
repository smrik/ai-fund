from __future__ import annotations

from datetime import date

from src.stage_00_data.segment_evidence import (
    REPORTABLE_SEGMENT_AXIS,
    build_segment_evidence_from_inline_xbrl,
)
from src.stage_00_data.segment_evidence_retrieval import (
    _aggregate,
    get_segment_evidence,
)


SEGMENTS = {
    "PBP": "msft:ProductivityAndBusinessProcessesMember",
    "IC": "msft:IntelligentCloudMember",
    "MPC": "msft:MorePersonalComputingMember",
}


def _filing(**overrides):
    values = {
        "cik": "0000789019",
        "form_type": "10-K",
        "filing_date": "2025-07-30",
        "period_of_report": "2025-06-30",
        "accession": "0000950170-25-100235",
        "primary_document": "msft-20250630.htm",
        "source_locator": (
            "https://www.sec.gov/Archives/edgar/data/789019/"
            "000095017025100235/msft-20250630.htm"
        ),
        "source_locator_type": "sec_filing_document",
    }
    values.update(overrides)
    return values


def _fact(
    concept,
    value,
    context_ref,
    *,
    start="2024-07-01",
    end="2025-06-30",
    label=None,
    decimals=-6,
    unit_ref="U_USD",
    currency="USD",
):
    return {
        "concept": concept,
        "label": label,
        "value": str(value),
        "numeric_value": float(value),
        "unit_ref": unit_ref,
        "currency": currency,
        "decimals": decimals,
        "period_type": "duration",
        "period_start": start,
        "period_end": end,
        "fiscal_year": int(end[:4]),
        "fiscal_period": "FY",
        "context_ref": context_ref,
        "fact_id": f"F_{context_ref}_{concept.rsplit(':', 1)[-1]}",
        "statement_type": "IncomeStatement",
        "statement_role": "https://www.microsoft.com/role/segment-detail",
    }


def _contexts():
    contexts = {"CONSOLIDATED": {"dimensions": {}}}
    contexts.update(
        {
            key: {"dimensions": {REPORTABLE_SEGMENT_AXIS: member}}
            for key, member in SEGMENTS.items()
        }
    )
    return contexts


def _core_facts(*, start="2024-07-01", end="2025-06-30"):
    revenue = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    operating_income = "us-gaap:OperatingIncomeLoss"
    facts = [
        _fact(revenue, 120_810_000_000, "PBP", start=start, end=end, label="Productivity and Business Processes"),
        _fact(revenue, 106_265_000_000, "IC", start=start, end=end, label="Intelligent Cloud"),
        _fact(revenue, 54_649_000_000, "MPC", start=start, end=end, label="More Personal Computing"),
        _fact(revenue, 281_724_000_000, "CONSOLIDATED", start=start, end=end),
        _fact(operating_income, 69_773_000_000, "PBP", start=start, end=end, label="Productivity and Business Processes"),
        _fact(operating_income, 44_589_000_000, "IC", start=start, end=end, label="Intelligent Cloud"),
        _fact(operating_income, 14_166_000_000, "MPC", start=start, end=end, label="More Personal Computing"),
        _fact(operating_income, 128_528_000_000, "CONSOLIDATED", start=start, end=end),
    ]
    return facts


def test_build_segment_evidence_preserves_provenance_and_ties_core_metrics():
    result = build_segment_evidence_from_inline_xbrl(
        ticker="msft",
        facts=_core_facts(),
        contexts=_contexts(),
        filing=_filing(),
    )

    assert result["status"] == "partial"
    assert result["schedules"]["revenue"]["row_count"] == 3
    assert result["schedules"]["operating_income"]["row_count"] == 3
    assert result["reconciliation_summary"] == {"tied": 2}
    assert {item["segment_total"] for item in result["reconciliations"]} == {
        281_724_000_000.0,
        128_528_000_000.0,
    }

    row = result["schedules"]["revenue"]["rows"][0]
    assert row["ticker"] == "MSFT"
    assert row["dimensions"] == {
        REPORTABLE_SEGMENT_AXIS: "msft:IntelligentCloudMember"
    }
    assert row["form_type"] == "10-K"
    assert row["filing_date"] == "2025-07-30"
    assert row["accession"] == "0000950170-25-100235"
    assert row["context_ref"] == "IC"
    assert row["xbrl_fact_id"].startswith("F_IC_")
    assert row["source_locator"].endswith("/msft-20250630.htm")
    assert row["source_locator_detail"]["concept"] == row["concept"]


def test_assets_and_kpis_are_unavailable_and_goodwill_is_not_substituted():
    facts = _core_facts()
    for context_ref, value in (("PBP", 31), ("IC", 26), ("MPC", 62)):
        facts.append(
            _fact(
                "us-gaap:Goodwill",
                value,
                context_ref,
                start=None,
                label=context_ref,
            )
        )

    result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT",
        facts=facts,
        contexts=_contexts(),
        filing=_filing(),
    )

    assert result["schedules"]["assets"] == {
        "status": "unavailable",
        "reason": "reportable_segment_assets_not_disclosed_in_requested_filings",
        "requested_concepts": ["us-gaap:Assets"],
        "row_count": 0,
        "rows": [],
    }
    assert result["schedules"]["kpis"]["status"] == "unavailable"
    assert result["schedules"]["kpis"]["reason"] == (
        "no_approved_kpi_concepts_no_semantic_inference"
    )
    assert "us-gaap:Goodwill" in result["coverage"]["segment_axis_concepts_present"]


def test_reconciliation_distinguishes_rounding_from_material_mismatch():
    concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = [
        _fact(concept, 33_000_000, key, decimals=-6)
        for key in SEGMENTS
    ]
    facts.append(_fact(concept, 100_000_000, "CONSOLIDATED", decimals=-6))
    rounded_result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT", facts=facts, contexts=_contexts(), filing=_filing()
    )
    rounded = rounded_result["reconciliations"][0]
    assert rounded["difference"] == -1_000_000.0
    assert rounded["rounding_tolerance"] == 2_000_000.0
    assert rounded["status"] == "tied_within_reported_rounding"
    assert rounded_result["schedules"]["revenue"]["status"] == "available"

    facts[-1] = _fact(concept, 110_000_000, "CONSOLIDATED", decimals=-6)
    mismatch_result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT", facts=facts, contexts=_contexts(), filing=_filing()
    )
    mismatch = mismatch_result["reconciliations"][0]
    assert mismatch["status"] == "mismatch"
    mismatch_schedule = mismatch_result["schedules"]["revenue"]
    assert mismatch_schedule["status"] == "unavailable"
    assert mismatch_schedule["reason"] == "segment_reconciliation_failed"
    assert mismatch_schedule["row_count"] == 3


def test_schedule_is_unavailable_when_consolidated_total_is_missing():
    concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = [_fact(concept, 10, key) for key in SEGMENTS]

    result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT", facts=facts, contexts=_contexts(), filing=_filing()
    )

    assert result["reconciliations"][0]["status"] == "consolidated_fact_unavailable"
    schedule = result["schedules"]["revenue"]
    assert schedule["status"] == "unavailable"
    assert schedule["reason"] == "segment_reconciliation_failed"
    assert schedule["row_count"] == 3
    assert len(schedule["rows"]) == 3


def test_kpi_extraction_requires_explicit_concept_allowlist():
    facts = _core_facts()
    for key, value in (("PBP", 10), ("IC", 20), ("MPC", 30)):
        facts.append(
            _fact(
                "msft:ActiveUsers",
                value,
                key,
                unit_ref="U_users",
                currency=None,
            )
        )
    without_allowlist = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT", facts=facts, contexts=_contexts(), filing=_filing()
    )
    with_allowlist = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT",
        facts=facts,
        contexts=_contexts(),
        filing=_filing(),
        kpi_concepts={"active_users": ("msft:ActiveUsers",)},
    )

    assert without_allowlist["schedules"]["kpis"]["row_count"] == 0
    assert with_allowlist["schedules"]["kpis"]["row_count"] == 3
    assert {
        row["metric_key"] for row in with_allowlist["schedules"]["kpis"]["rows"]
    } == {"kpi:active_users"}


def test_get_segment_evidence_aggregates_latest_filing_vintages(monkeypatch):
    class FakeFacts:
        def __init__(self, rows):
            self._rows = rows

        def get_facts(self):
            return self._rows

    class FakeXbrl:
        def __init__(self, rows):
            self.facts = FakeFacts(rows)
            self.contexts = _contexts()

    class FakeFiling:
        def __init__(self, form, accession, filing_date, period, document, rows):
            self.form = form
            self.accession_no = accession
            self.filing_date = filing_date
            self.period_of_report = period
            self.primary_document = document
            self._rows = rows

        def xbrl(self):
            return FakeXbrl(self._rows)

    class FakeFilings:
        empty = False

        def __init__(self, filing):
            self._filing = filing

        def latest(self):
            return self._filing

    class FakeCompany:
        cik = "0000789019"

        def __init__(self, ticker):
            assert ticker == "MSFT"

        def get_filings(self, form):
            if form == "10-K":
                filing = FakeFiling(
                    form,
                    "0000950170-25-100235",
                    date(2025, 7, 30),
                    date(2025, 6, 30),
                    "msft-20250630.htm",
                    _core_facts(),
                )
            else:
                filing = FakeFiling(
                    form,
                    "0001193125-26-191507",
                    date(2026, 4, 29),
                    date(2026, 3, 31),
                    "msft-20260331.htm",
                    _core_facts(start="2025-07-01", end="2026-03-31"),
                )
            return FakeFilings(filing)

    monkeypatch.delenv("ALPHA_POD_EDGAR_CACHE_ONLY", raising=False)
    monkeypatch.setattr(
        "src.stage_00_data.segment_evidence_retrieval.Company", FakeCompany
    )

    result = get_segment_evidence("msft")

    assert result["status"] == "partial"
    assert result["schedules"]["revenue"]["row_count"] == 6
    assert result["schedules"]["operating_income"]["row_count"] == 6
    assert result["reconciliation_summary"] == {"tied": 4}
    assert [filing["form_type"] for filing in result["filings"]] == ["10-K", "10-Q"]
    assert result["filings"][1]["source_locator"].endswith("/msft-20260331.htm")


def test_aggregate_rejects_metric_if_any_filing_reconciliation_fails():
    tied_result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT",
        facts=_core_facts(),
        contexts=_contexts(),
        filing=_filing(),
    )
    mismatch_facts = _core_facts(start="2025-07-01", end="2026-03-31")
    for fact in mismatch_facts:
        if (
            fact["context_ref"] == "CONSOLIDATED"
            and fact["concept"].endswith(
                "RevenueFromContractWithCustomerExcludingAssessedTax"
            )
        ):
            fact["numeric_value"] += 10_000_000
            fact["value"] = str(int(fact["numeric_value"]))
    mismatch_result = build_segment_evidence_from_inline_xbrl(
        ticker="MSFT",
        facts=mismatch_facts,
        contexts=_contexts(),
        filing=_filing(
            form_type="10-Q",
            filing_date="2026-04-29",
            period_of_report="2026-03-31",
        ),
    )

    result = _aggregate(
        "MSFT", [tied_result, mismatch_result], ("10-K", "10-Q"), (), None
    )

    schedule = result["schedules"]["revenue"]
    assert schedule["status"] == "unavailable"
    assert schedule["reason"] == "segment_reconciliation_failed"
    assert schedule["row_count"] == 6
    assert result["reconciliation_summary"] == {"mismatch": 1, "tied": 3}


def test_get_segment_evidence_fails_closed_in_cache_only_mode(monkeypatch):
    monkeypatch.setenv("ALPHA_POD_EDGAR_CACHE_ONLY", "1")

    class ForbiddenCompany:
        def __init__(self, ticker):
            raise AssertionError("cache-only retrieval must not construct Company")

    monkeypatch.setattr(
        "src.stage_00_data.segment_evidence_retrieval.Company", ForbiddenCompany
    )

    result = get_segment_evidence("MSFT")

    assert result["status"] == "cache_only_unavailable"
    assert result["schedules"]["revenue"]["status"] == "unavailable"
    assert result["errors"]
