from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.stage_00_data.filing_presentation import (
    extract_filing_presentation,
    get_filing_presentation_evidence,
)
from src.stage_00_data.xbrl_evidence import get_xbrl_statement_evidence


def _node(
    element_id: str,
    *,
    parent: str | None = None,
    children: list[str] | None = None,
    depth: int = 0,
    order: float = 0.0,
    label: str | None = None,
    is_abstract: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        element_id=element_id,
        element_name=element_id,
        parent=parent,
        children=list(children or []),
        child_preferred_labels=[None for _ in children or []],
        depth=depth,
        order=order,
        preferred_label=None,
        display_label=label or element_id,
        is_abstract=is_abstract,
    )


def _tree(
    role: str,
    root: str,
    nodes: list[SimpleNamespace],
) -> SimpleNamespace:
    return SimpleNamespace(
        role_uri=role,
        definition=role.rsplit("/", 1)[-1],
        root_element_id=root,
        all_nodes={node.element_id: node for node in nodes},
    )


def _fact(
    element_id: str,
    context_ref: str,
    value: str,
    *,
    numeric_value: float,
    fact_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        element_id=element_id,
        context_ref=context_ref,
        value=value,
        numeric_value=numeric_value,
        unit_ref="usd",
        decimals=-6,
        instance_id=None,
        fact_id=fact_id,
    )


def test_extract_filing_presentation_emits_complete_lineage_and_manifest():
    income_role = "http://example.test/role/IncomeStatement"
    balance_role = "http://example.test/role/BalanceSheet"
    cash_flow_role = "http://example.test/role/CashFlowStatement"
    income_root = "us-gaap_IncomeStatementAbstract"
    income_section = "us-gaap_OperatingRevenueAbstract"
    revenue = "us-gaap_Revenues"
    balance_root = "us-gaap_BalanceSheetAbstract"
    balance_section = "us-gaap_CurrentAssetsAbstract"
    assets = "us-gaap_Assets"
    cash_flow_root = "us-gaap_CashFlowStatementAbstract"
    cash_flow_section = "us-gaap_OperatingActivitiesAbstract"
    operating_cash = "us-gaap_NetCashProvidedByUsedInOperatingActivities"

    xbrl = _period_xbrl(
        period_start="2025-01-01",
        period_end="2025-12-31",
        revenue_value=100.0,
        assets_value=500.0,
        cash_flow_value=50.0,
    )

    income_root_node = _node(
        income_root,
        children=[income_section],
        label="Income statement",
        is_abstract=True,
    )
    income_root_node.child_preferred_labels = ["Operating revenue section"]
    income_section_node = _node(
        income_section,
        parent=income_root,
        children=[revenue],
        depth=1,
        order=1.0,
        label="Operating revenue",
        is_abstract=True,
    )
    income_section_node.child_preferred_labels = ["Net sales label"]
    revenue_node = _node(
        revenue,
        parent=income_section,
        depth=2,
        order=2.0,
        label="Revenue",
    )
    income_nodes = [income_root_node, income_section_node, revenue_node]

    balance_root_node = _node(
        balance_root,
        children=[balance_section],
        label="Balance sheet",
        is_abstract=True,
    )
    balance_section_node = _node(
        balance_section,
        parent=balance_root,
        children=[assets],
        depth=1,
        order=1.0,
        label="Current assets",
        is_abstract=True,
    )
    balance_section_node.child_preferred_labels = ["Total assets label"]
    assets_node = _node(
        assets,
        parent=balance_section,
        depth=2,
        order=2.0,
        label="Assets",
    )
    balance_nodes = [balance_root_node, balance_section_node, assets_node]

    cash_flow_root_node = _node(
        cash_flow_root,
        children=[cash_flow_section],
        label="Cash flow statement",
        is_abstract=True,
    )
    cash_flow_section_node = _node(
        cash_flow_section,
        parent=cash_flow_root,
        children=[operating_cash],
        depth=1,
        order=1.0,
        label="Operating activities",
        is_abstract=True,
    )
    cash_flow_section_node.child_preferred_labels = ["Cash from operations label"]
    operating_cash_node = _node(
        operating_cash,
        parent=cash_flow_section,
        depth=2,
        order=2.0,
        label="Cash from operations",
    )
    cash_flow_nodes = [
        cash_flow_root_node,
        cash_flow_section_node,
        operating_cash_node,
    ]

    xbrl.presentation_trees = {
        income_role: _tree(income_role, income_root, income_nodes),
        balance_role: _tree(balance_role, balance_root, balance_nodes),
        cash_flow_role: _tree(
            cash_flow_role,
            cash_flow_root,
            cash_flow_nodes,
        ),
    }
    xbrl.contexts["segment"] = SimpleNamespace(
        context_id="segment",
        entity={"identifier": "0000000001"},
        period={
            "type": "duration",
            "startDate": "2025-01-01",
            "endDate": "2025-12-31",
        },
        dimensions={"segment": "north-america"},
    )
    xbrl.parser.facts.update(
        {
            "income_root": _fact(
                income_root,
                "duration",
                "100",
                numeric_value=100.0,
                fact_id="income-root-fact",
            ),
            "income_section": _fact(
                income_section,
                "duration",
                "100",
                numeric_value=100.0,
                fact_id="income-section-fact",
            ),
            "income_segment": _fact(
                revenue,
                "segment",
                "90",
                numeric_value=90.0,
                fact_id="income-segment-fact",
            ),
            "balance_root": _fact(
                balance_root,
                "instant",
                "500",
                numeric_value=500.0,
                fact_id="balance-root-fact",
            ),
            "balance_section": _fact(
                balance_section,
                "instant",
                "500",
                numeric_value=500.0,
                fact_id="balance-section-fact",
            ),
            "cash_flow_root": _fact(
                cash_flow_root,
                "duration",
                "50",
                numeric_value=50.0,
                fact_id="cash-flow-root-fact",
            ),
            "cash_flow_section": _fact(
                cash_flow_section,
                "duration",
                "50",
                numeric_value=50.0,
                fact_id="cash-flow-section-fact",
            ),
        }
    )
    income_section_node.weight = 1.0
    revenue_node.weight = 1.0
    xbrl.calculation_trees = {
        income_role: _tree(
            income_role,
            income_root,
            [income_root_node, income_section_node, revenue_node],
        )
    }

    filing = _FakeFiling(
        form="10-K",
        filing_date="2026-02-01",
        accession_no="annual-2025",
        xbrl=xbrl,
    )
    result = extract_filing_presentation(
        filing,
        ticker="generic",
        evidence_cutoff="2026-01-31",
        source_run_id=17,
    )

    assert result["ticker"] == "GENERIC"
    assert result["source"] == "sec_xbrl_filing_presentation_v1"
    assert result["accession"] == "annual-2025"
    assert result["status"] == "completed"
    assert result["errors"] == []
    assert result["fact_count"] == len(result["facts"]) == 10
    assert {fact["statement"] for fact in result["facts"]} == {
        "IncomeStatement",
        "BalanceSheet",
        "CashFlowStatement",
    }

    income_facts = [
        fact
        for fact in result["facts"]
        if fact["hierarchy"]["statement_role"] == income_role
        and not fact["dimensions"]
    ]
    assert [fact["concept"] for fact in income_facts] == [
        income_root,
        income_section,
        revenue,
    ]
    assert [
        fact["hierarchy"]["presentation_path"] for fact in income_facts
    ] == [
        [income_root],
        [income_root, income_section],
        [income_root, income_section, revenue],
    ]
    assert [
        fact["hierarchy"]["presentation_sibling_path"] for fact in income_facts
    ] == [[], [0], [0, 0]]
    assert [fact["hierarchy"]["parent_concept"] for fact in income_facts] == [
        None,
        income_root,
        income_section,
    ]
    assert [fact["hierarchy"]["depth"] for fact in income_facts] == [0, 1, 2]
    assert [fact["hierarchy"]["presentation_order"] for fact in income_facts] == [
        0.0,
        1.0,
        2.0,
    ]
    assert [fact["label"] for fact in income_facts] == [
        "Income statement",
        "Operating revenue",
        "Revenue",
    ]
    assert [
        fact["hierarchy"]["preferred_label"] for fact in income_facts
    ] == [None, "Operating revenue section", "Net sales label"]
    assert [fact["hierarchy"]["is_abstract"] for fact in income_facts] == [
        True,
        True,
        False,
    ]
    assert [
        fact["hierarchy"]["consolidated_view_eligible"] for fact in income_facts
    ] == [True, True, True]
    assert [fact["hierarchy"]["line_item_sequence"] for fact in income_facts] == [
        7,
        8,
        9,
    ]

    revenue_facts = [
        fact for fact in result["facts"] if fact["concept"] == revenue
    ]
    assert len(revenue_facts) == 2
    dimensioned_revenue = next(fact for fact in revenue_facts if fact["dimensions"])
    assert dimensioned_revenue["dimensions"] == {"segment": "north-america"}
    assert dimensioned_revenue["hierarchy"]["consolidated_view_eligible"] is False
    assert dimensioned_revenue["hierarchy"]["presentation_path"] == [
        income_root,
        income_section,
        revenue,
    ]

    manifest = result["coverage_manifest"]
    assert manifest["contract_version"] == "statement_coverage_manifest.v1"
    assert manifest["ticker"] == "GENERIC"
    assert manifest["source"] == result["source"]
    assert manifest["accession"] == "annual-2025"
    assert manifest["source_run_id"] == 17
    assert manifest["status"] == "completed"
    assert manifest["filing_date"] == "2026-02-01"
    assert manifest["evidence_cutoff"] == "2026-01-31"
    assert manifest["manifest_id"] == f"sha256:{manifest['manifest_hash']}"
    assert len(manifest["manifest_hash"]) == 64

    coverage = manifest["coverage"]
    entries = coverage["entries"]
    assert coverage["entry_count"] == len(entries) == 3
    assert {entry["statement"] for entry in entries} == {
        "IncomeStatement",
        "BalanceSheet",
        "CashFlowStatement",
    }
    for entry in entries:
        entry_facts = [
            fact
            for fact in result["facts"]
            if fact["hierarchy"]["statement_role"] == entry["statement_role"]
            and fact["statement"] == entry["statement"]
            and fact["period_start"] == entry["period_start"]
            and fact["period_end"] == entry["period_end"]
            and fact["period_type"] == entry["period_type"]
            and fact["period_kind"] == entry["period_kind"]
        ]
        presented_ids = {fact["fact_id"] for fact in entry_facts}
        consolidated_ids = {
            fact["fact_id"] for fact in entry_facts if not fact["dimensions"]
        }
        dimensioned_ids = {
            fact["fact_id"] for fact in entry_facts if fact["dimensions"]
        }
        assert entry["coverage_key"].startswith("statement-coverage:")
        assert entry["canonical_roles"] == [entry["statement"]]
        assert entry["units"] == ["USD"]
        assert entry["currencies"] == ["USD"]
        assert set(entry["presented_fact_ids"]) == presented_ids
        assert set(entry["consolidated_fact_ids"]) == consolidated_ids
        assert set(entry["dimensioned_fact_ids"]) == dimensioned_ids
        assert set(entry["presented_fact_ids"]) == (
            set(entry["consolidated_fact_ids"])
            | set(entry["dimensioned_fact_ids"])
        )

    assert manifest["calculation_edge_count"] == len(
        manifest["calculation_edges"]
    ) == 2
    assert {
        (
            edge["parent_concept"],
            edge["child_concept"],
            edge["weight"],
            edge["order"],
        )
        for edge in manifest["calculation_edges"]
    } == {
        (income_root, income_section, 1.0, 1.0),
        (income_section, revenue, 1.0, 2.0),
    }
    assert all(
        edge["edge_id"].startswith("calculation-edge:")
        and edge["source_locator"].startswith("https://www.sec.gov/")
        for edge in manifest["calculation_edges"]
    )


def _period_xbrl(
    *,
    period_start: str,
    period_end: str,
    revenue_value: float,
    assets_value: float,
    cash_flow_value: float,
    extra_balance_period_end: str | None = None,
) -> SimpleNamespace:
    income_role = "http://example.test/role/IncomeStatement"
    balance_role = "http://example.test/role/BalanceSheet"
    cash_flow_role = "http://example.test/role/CashFlowStatement"
    revenue = "us-gaap_Revenues"
    assets = "us-gaap_Assets"
    operating_cash = "us-gaap_NetCashProvidedByUsedInOperatingActivities"
    acquired_assets = "us-gaap_AssetsAcquired"
    income_root = "us-gaap_IncomeStatementAbstract"
    balance_root = "us-gaap_BalanceSheetAbstract"
    cash_flow_root = "us-gaap_CashFlowStatementAbstract"
    contexts = {
        "duration": SimpleNamespace(
            context_id="duration",
            entity={"identifier": "0000000001"},
            period={
                "type": "duration",
                "startDate": period_start,
                "endDate": period_end,
            },
            dimensions={},
        ),
        "instant": SimpleNamespace(
            context_id="instant",
            entity={"identifier": "0000000001"},
            period={"type": "instant", "instant": period_end},
            dimensions={},
        ),
    }
    if extra_balance_period_end:
        contexts["special_instant"] = SimpleNamespace(
            context_id="special_instant",
            entity={"identifier": "0000000001"},
            period={"type": "instant", "instant": extra_balance_period_end},
            dimensions={},
        )
    balance_children = [assets]
    if extra_balance_period_end:
        balance_children.append(acquired_assets)
    balance_nodes = [
        _node(balance_root, children=balance_children, is_abstract=True),
        _node(assets, parent=balance_root, depth=1, label="Assets"),
    ]
    if extra_balance_period_end:
        balance_nodes.append(
            _node(
                acquired_assets,
                parent=balance_root,
                depth=1,
                label="Assets acquired",
            )
        )
    presentation_trees = {
        income_role: _tree(
            income_role,
            income_root,
            [
                _node(income_root, children=[revenue], is_abstract=True),
                _node(revenue, parent=income_root, depth=1, label="Revenue"),
            ],
        ),
        balance_role: _tree(
            balance_role,
            balance_root,
            balance_nodes,
        ),
        cash_flow_role: _tree(
            cash_flow_role,
            cash_flow_root,
            [
                _node(
                    cash_flow_root,
                    children=[operating_cash],
                    is_abstract=True,
                ),
                _node(
                    operating_cash,
                    parent=cash_flow_root,
                    depth=1,
                    label="Cash from operations",
                ),
            ],
        ),
    }
    facts = {
        "revenue": _fact(
            revenue,
            "duration",
            str(revenue_value),
            numeric_value=revenue_value,
            fact_id=f"revenue-{period_end}",
        ),
        "assets": _fact(
            assets,
            "instant",
            str(assets_value),
            numeric_value=assets_value,
            fact_id=f"assets-{period_end}",
        ),
        "cash_flow": _fact(
            operating_cash,
            "duration",
            str(cash_flow_value),
            numeric_value=cash_flow_value,
            fact_id=f"cash-{period_end}",
        ),
    }
    if extra_balance_period_end:
        facts["acquired_assets"] = _fact(
            acquired_assets,
            "special_instant",
            "10",
            numeric_value=10.0,
            fact_id=f"acquired-assets-{extra_balance_period_end}",
        )
    xbrl = SimpleNamespace(
        parser=SimpleNamespace(facts=facts),
        presentation_trees=presentation_trees,
        calculation_trees={},
        contexts=contexts,
        units={"usd": {"type": "simple", "measure": "iso4217:USD"}},
        entity_info={
            "identifier": "0000000001",
            "fiscal_year": int(period_end[:4]),
            "fiscal_period": "FY",
            "document_period_end_date": period_end,
        },
    )
    xbrl.get_all_statements = lambda: [
        {"role": income_role, "type": "IncomeStatement"},
        {"role": balance_role, "type": "BalanceSheet"},
        {"role": cash_flow_role, "type": "CashFlowStatement"},
    ]
    return xbrl


class _FakeFiling:
    cik = 1

    def __init__(
        self,
        *,
        form: str,
        filing_date: str,
        accession_no: str,
        xbrl: Any,
    ):
        self.form = form
        self.filing_date = filing_date
        self.accession_no = accession_no
        self.homepage_url = (
            "https://www.sec.gov/Archives/edgar/data/1/"
            f"{accession_no.replace('-', '')}/{accession_no}-index.html"
        )
        self._xbrl = xbrl

    def xbrl(self):
        return self._xbrl


class _FakeFilings(list):
    def head(self, count: int):
        return _FakeFilings(self[:count])


def test_filing_evidence_selects_five_annual_periods_and_exact_ltm_components():
    annual_values = {
        2025: 110.0,
        2024: 100.0,
        2023: 90.0,
        2022: 80.0,
        2021: 70.0,
        2020: 60.0,
    }
    annual_filings = _FakeFilings(
        [
            _FakeFiling(
                form="10-K",
                filing_date=f"{year + 1}-02-01",
                accession_no=f"annual-{year}",
                xbrl=_period_xbrl(
                    period_start=f"{year}-01-01",
                    period_end=f"{year}-12-31",
                    revenue_value=value,
                    assets_value=value * 5,
                    cash_flow_value=value / 2,
                ),
            )
            for year, value in sorted(
                annual_values.items(),
                reverse=True,
            )
        ]
    )
    interim_filings = _FakeFilings(
        [
            _FakeFiling(
                form="10-Q",
                filing_date="2025-10-30",
                accession_no="q3-2025",
                xbrl=_period_xbrl(
                    period_start="2025-01-01",
                    period_end="2025-09-30",
                    revenue_value=90.0,
                    assets_value=600.0,
                    cash_flow_value=45.0,
                ),
            ),
            _FakeFiling(
                form="10-Q",
                filing_date="2025-07-30",
                accession_no="q2-2025",
                xbrl=_period_xbrl(
                    period_start="2025-01-01",
                    period_end="2025-06-30",
                    revenue_value=58.0,
                    assets_value=580.0,
                    cash_flow_value=29.0,
                ),
            ),
            _FakeFiling(
                form="10-Q",
                filing_date="2024-10-30",
                accession_no="q3-2024",
                xbrl=_period_xbrl(
                    period_start="2024-01-01",
                    period_end="2024-09-30",
                    revenue_value=70.0,
                    assets_value=500.0,
                    cash_flow_value=35.0,
                ),
            ),
        ]
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "GENERIC"
            self.calls: list[dict] = []

        def get_facts(self):
            raise AssertionError("Company Facts must not drive presentation coverage")

        def get_filings(self, **kwargs):
            self.calls.append(kwargs)
            forms = kwargs["form"]
            return (
                annual_filings
                if any(form in {"10-K", "20-F", "40-F"} for form in forms)
                else interim_filings
            )

    first = get_filing_presentation_evidence(
        "generic",
        company_factory=FakeCompany,
        max_annual_periods=5,
        include_ltm=True,
    )
    second = get_filing_presentation_evidence(
        "GENERIC",
        company_factory=FakeCompany,
        max_annual_periods=5,
        include_ltm=True,
    )

    assert first["status"] == "completed"
    assert first["annual_periods"] == [
        "2025-12-31",
        "2024-12-31",
        "2023-12-31",
        "2022-12-31",
        "2021-12-31",
    ]
    assert not any(fact["period_end"] == "2020-12-31" for fact in first["facts"])
    assert first["ltm_status"] == "constructed"
    revenue_ltm = next(
        fact
        for fact in first["facts"]
        if fact["statement"] == "IncomeStatement" and fact["period_kind"] == "ltm"
    )
    assert revenue_ltm["numeric_value"] == 120.0
    assert revenue_ltm["period_start"] == "2024-10-01"
    assert revenue_ltm["period_end"] == "2025-09-30"
    assert {
        component.split(":")[2]
        for component in revenue_ltm["derivation"]["component_fact_ids"]
    } == {"annual-2024", "q3-2024", "q3-2025"}
    assert {
        fact["accession"] for fact in first["facts"] if fact["period_kind"] == "interim"
    } == {"q3-2024", "q3-2025"}
    assert all(
        manifest["status"] in {"completed", "partial", "failed"}
        for manifest in first["coverage_manifests"]
    )
    assert [fact["fact_id"] for fact in first["facts"]] == [
        fact["fact_id"] for fact in second["facts"]
    ]


def test_filing_evidence_does_not_count_special_balance_sheet_instants_as_fiscal_years():
    annual_filings = _FakeFilings(
        [
            _FakeFiling(
                form="10-K",
                filing_date="2023-07-30",
                accession_no="annual-2023",
                xbrl=_period_xbrl(
                    period_start="2022-07-01",
                    period_end="2023-06-30",
                    revenue_value=100.0,
                    assets_value=500.0,
                    cash_flow_value=50.0,
                    extra_balance_period_end="2023-10-13",
                ),
            ),
            _FakeFiling(
                form="10-K",
                filing_date="2022-07-30",
                accession_no="annual-2022",
                xbrl=_period_xbrl(
                    period_start="2021-07-01",
                    period_end="2022-06-30",
                    revenue_value=90.0,
                    assets_value=450.0,
                    cash_flow_value=45.0,
                ),
            ),
        ]
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_filings(self, **kwargs):
            return (
                annual_filings
                if any(
                    form in {"10-K", "20-F", "40-F"}
                    for form in kwargs["form"]
                )
                else _FakeFilings()
            )

    result = get_filing_presentation_evidence(
        "generic",
        company_factory=FakeCompany,
        max_annual_periods=2,
        include_ltm=False,
    )

    assert result["annual_periods"] == ["2023-06-30", "2022-06-30"]
    assert not any(
        fact["period_end"] == "2023-10-13"
        for fact in result["facts"]
    )


def test_statement_public_api_uses_filing_xbrl_instead_of_company_facts(
    monkeypatch,
):
    annual = _FakeFiling(
        form="10-K",
        filing_date="2025-07-30",
        accession_no="annual-2025",
        xbrl=_period_xbrl(
            period_start="2024-07-01",
            period_end="2025-06-30",
            revenue_value=100.0,
            assets_value=500.0,
            cash_flow_value=50.0,
        ),
    )

    class FakeCompany:
        cik = 1
        queries: list[dict] = []

        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_facts(self):
            raise AssertionError("Company Facts path was invoked")

        def get_filings(self, **kwargs):
            self.queries.append(kwargs)
            return (
                _FakeFilings([annual]) if "10-K" in kwargs["form"] else _FakeFilings()
            )

    monkeypatch.setattr(
        "src.stage_00_data.xbrl_evidence.Company",
        FakeCompany,
    )

    result = get_xbrl_statement_evidence(
        "generic",
        max_annual_periods=1,
        include_ltm=False,
    )

    assert result["status"] == "completed"
    assert result["annual_periods"] == ["2025-06-30"]
    assert result["fact_count"] == 3
    assert result["coverage_manifests"][0]["accession"] == "annual-2025"
    assert all(query["trigger_full_load"] is False for query in FakeCompany.queries)


def test_evidence_cutoff_excludes_later_filing_vintages():
    later = _FakeFiling(
        form="10-K",
        filing_date="2026-02-01",
        accession_no="annual-2025",
        xbrl=_period_xbrl(
            period_start="2025-01-01",
            period_end="2025-12-31",
            revenue_value=110.0,
            assets_value=550.0,
            cash_flow_value=55.0,
        ),
    )
    available = _FakeFiling(
        form="10-K",
        filing_date="2025-02-01",
        accession_no="annual-2024",
        xbrl=_period_xbrl(
            period_start="2024-01-01",
            period_end="2024-12-31",
            revenue_value=100.0,
            assets_value=500.0,
            cash_flow_value=50.0,
        ),
    )

    class FakeCompany:
        cik = 1

        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_filings(self, **kwargs):
            return (
                _FakeFilings([later, available])
                if "10-K" in kwargs["form"]
                else _FakeFilings()
            )

    result = get_filing_presentation_evidence(
        "GENERIC",
        company_factory=FakeCompany,
        max_annual_periods=5,
        include_ltm=False,
        evidence_cutoff="2025-12-31",
    )

    assert result["annual_periods"] == ["2024-12-31"]
    assert {fact["accession"] for fact in result["facts"]} == {"annual-2024"}
    assert result["coverage_manifests"][0]["evidence_cutoff"] == "2025-12-31"


def test_repeated_presented_concept_keeps_distinct_occurrence_fact_ids():
    role = "http://example.test/role/ConsolidatedCashFlows"
    root_id = "us-gaap_CashFlowStatementAbstract"
    cash = "us-gaap_CashAndCashEquivalentsAtCarryingValue"
    root = _node(
        root_id,
        children=[cash, cash],
        is_abstract=True,
    )
    root.child_preferred_labels = [
        "http://www.xbrl.org/2003/role/periodStartLabel",
        "http://www.xbrl.org/2003/role/periodEndLabel",
    ]
    xbrl = SimpleNamespace(
        parser=SimpleNamespace(
            facts={
                "cash": _fact(
                    cash,
                    "instant",
                    "100",
                    numeric_value=100.0,
                    fact_id="cash-fact",
                )
            }
        ),
        presentation_trees={
            role: _tree(
                role,
                root_id,
                [
                    root,
                    _node(cash, parent=root_id, depth=1, label="Cash"),
                ],
            )
        },
        calculation_trees={},
        contexts={
            "instant": SimpleNamespace(
                context_id="instant",
                entity={"identifier": "0000000001"},
                period={"type": "instant", "instant": "2025-12-31"},
                dimensions={},
            )
        },
        units={"usd": {"type": "simple", "measure": "iso4217:USD"}},
        entity_info={"identifier": "0000000001", "fiscal_year": 2025},
    )
    xbrl.get_all_statements = lambda: [{"role": role, "type": "CashFlowStatement"}]
    filing = _FakeFiling(
        form="10-K",
        filing_date="2026-02-01",
        accession_no="annual-2025",
        xbrl=xbrl,
    )

    result = extract_filing_presentation(filing, ticker="GENERIC")

    assert result["status"] == "partial"
    assert len(result["facts"]) == 2
    assert len({fact["fact_id"] for fact in result["facts"]}) == 2
    assert (
        len(
            {
                fact["hierarchy"]["presentation_occurrence_id"]
                for fact in result["facts"]
            }
        )
        == 2
    )
    assert {
        fact["hierarchy"]["preferred_label"].rsplit("/", 1)[-1]
        for fact in result["facts"]
    } == {"periodStartLabel", "periodEndLabel"}
    entry = result["coverage_manifest"]["coverage"]["entries"][0]
    assert len(entry["presented_fact_ids"]) == 2


def test_ltm_output_never_mixes_incompatible_reporting_windows():
    annual_xbrl = _period_xbrl(
        period_start="2024-01-01",
        period_end="2024-12-31",
        revenue_value=100.0,
        assets_value=500.0,
        cash_flow_value=50.0,
    )
    q3_current = _period_xbrl(
        period_start="2025-01-01",
        period_end="2025-09-30",
        revenue_value=90.0,
        assets_value=600.0,
        cash_flow_value=45.0,
    )
    q3_prior = _period_xbrl(
        period_start="2024-01-01",
        period_end="2024-09-30",
        revenue_value=70.0,
        assets_value=500.0,
        cash_flow_value=35.0,
    )
    q2_current = _period_xbrl(
        period_start="2025-01-01",
        period_end="2025-06-30",
        revenue_value=58.0,
        assets_value=580.0,
        cash_flow_value=29.0,
    )
    q2_prior = _period_xbrl(
        period_start="2024-01-01",
        period_end="2024-06-30",
        revenue_value=45.0,
        assets_value=490.0,
        cash_flow_value=22.0,
    )
    q3_current.parser.facts.pop("cash_flow")
    q3_prior.parser.facts.pop("cash_flow")
    q2_current.parser.facts.pop("revenue")
    q2_prior.parser.facts.pop("revenue")

    annual_filings = _FakeFilings(
        [
            _FakeFiling(
                form="10-K",
                filing_date="2025-02-01",
                accession_no="annual-2024",
                xbrl=annual_xbrl,
            )
        ]
    )
    interim_filings = _FakeFilings(
        [
            _FakeFiling(
                form="10-Q",
                filing_date="2025-10-30",
                accession_no="q3-2025",
                xbrl=q3_current,
            ),
            _FakeFiling(
                form="10-Q",
                filing_date="2025-07-30",
                accession_no="q2-2025",
                xbrl=q2_current,
            ),
            _FakeFiling(
                form="10-Q",
                filing_date="2024-10-30",
                accession_no="q3-2024",
                xbrl=q3_prior,
            ),
            _FakeFiling(
                form="10-Q",
                filing_date="2024-07-30",
                accession_no="q2-2024",
                xbrl=q2_prior,
            ),
        ]
    )

    class FakeCompany:
        cik = 1

        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_filings(self, **kwargs):
            return annual_filings if "10-K" in kwargs["form"] else interim_filings

    result = get_filing_presentation_evidence(
        "GENERIC",
        company_factory=FakeCompany,
    )

    ltm = [fact for fact in result["facts"] if fact["period_kind"] == "ltm"]
    assert {(fact["period_start"], fact["period_end"]) for fact in ltm} == {
        ("2024-10-01", "2025-09-30")
    }
    assert {fact["statement"] for fact in ltm} == {"IncomeStatement"}
    assert result["ltm_status"] == "partial"
    assert result["ltm_details"]["target_period_end"] == "2025-09-30"
    assert result["ltm_details"]["attempted_identity_count"] == 2
    assert result["ltm_details"]["constructed_identity_count"] == 1


def test_aggregate_status_is_partial_when_an_annual_statement_is_missing():
    incomplete_xbrl = _period_xbrl(
        period_start="2024-01-01",
        period_end="2024-12-31",
        revenue_value=100.0,
        assets_value=500.0,
        cash_flow_value=50.0,
    )
    incomplete_xbrl.parser.facts.pop("cash_flow")
    annual = _FakeFiling(
        form="10-K",
        filing_date="2025-02-01",
        accession_no="annual-2024",
        xbrl=incomplete_xbrl,
    )

    class FakeCompany:
        cik = 1

        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_filings(self, **kwargs):
            return (
                _FakeFilings([annual]) if "10-K" in kwargs["form"] else _FakeFilings()
            )

    result = get_filing_presentation_evidence(
        "GENERIC",
        company_factory=FakeCompany,
        include_ltm=False,
    )

    assert result["status"] == "partial"
    assert result["coverage_manifests"][0]["status"] == "partial"


def test_fact_ids_do_not_depend_on_raw_parser_mapping_order():
    role = "http://example.test/role/IncomeStatement"
    root_id = "us-gaap_IncomeStatementAbstract"
    revenue = "us-gaap_Revenues"
    tree = _tree(
        role,
        root_id,
        [
            _node(root_id, children=[revenue], is_abstract=True),
            _node(revenue, parent=root_id, depth=1, label="Revenue"),
        ],
    )
    contexts = {
        "consolidated": SimpleNamespace(
            context_id="consolidated",
            entity={"identifier": "0000000001"},
            period={
                "type": "duration",
                "startDate": "2024-01-01",
                "endDate": "2024-12-31",
            },
            dimensions={},
        ),
        "segment": SimpleNamespace(
            context_id="segment",
            entity={"identifier": "0000000001"},
            period={
                "type": "duration",
                "startDate": "2024-01-01",
                "endDate": "2024-12-31",
            },
            dimensions={"example_SegmentAxis": "example_CloudMember"},
        ),
    }
    consolidated = _fact(
        revenue,
        "consolidated",
        "100",
        numeric_value=100.0,
        fact_id="revenue-total",
    )
    segment = _fact(
        revenue,
        "segment",
        "60",
        numeric_value=60.0,
        fact_id="revenue-segment",
    )

    def make_xbrl(facts: dict[str, SimpleNamespace]) -> SimpleNamespace:
        xbrl = SimpleNamespace(
            parser=SimpleNamespace(facts=facts),
            presentation_trees={role: tree},
            calculation_trees={},
            contexts=contexts,
            units={"usd": {"type": "simple", "measure": "iso4217:USD"}},
            entity_info={"identifier": "0000000001", "fiscal_year": 2024},
        )
        xbrl.get_all_statements = lambda: [{"role": role, "type": "IncomeStatement"}]
        return xbrl

    first = extract_filing_presentation(
        _FakeFiling(
            form="10-K",
            filing_date="2025-02-01",
            accession_no="annual-2024",
            xbrl=make_xbrl({"total": consolidated, "segment": segment}),
        ),
        ticker="GENERIC",
    )
    reordered = extract_filing_presentation(
        _FakeFiling(
            form="10-K",
            filing_date="2025-02-01",
            accession_no="annual-2024",
            xbrl=make_xbrl({"segment": segment, "total": consolidated}),
        ),
        ticker="GENERIC",
    )

    assert {fact["context_ref"]: fact["fact_id"] for fact in first["facts"]} == {
        fact["context_ref"]: fact["fact_id"] for fact in reordered["facts"]
    }


def test_malformed_filing_xbrl_fails_closed_with_a_manifest():
    class BrokenXbrl:
        def get_all_statements(self):
            raise ValueError("presentation linkbase is malformed")

    filing = _FakeFiling(
        form="10-K",
        filing_date="2025-02-01",
        accession_no="annual-2024",
        xbrl=BrokenXbrl(),
    )

    result = extract_filing_presentation(filing, ticker="GENERIC")

    assert result["status"] == "failed"
    assert result["facts"] == []
    assert result["errors"] == ["presentation linkbase is malformed"]
    assert result["coverage_manifest"]["status"] == "failed"
    assert result["coverage_manifest"]["accession"] == "annual-2024"


def test_missing_annual_filings_are_accounted_for_as_a_failure():
    class FakeCompany:
        cik = 1

        def __init__(self, ticker: str):
            assert ticker == "GENERIC"

        def get_filings(self, **kwargs):
            return _FakeFilings()

    result = get_filing_presentation_evidence(
        "GENERIC",
        company_factory=FakeCompany,
    )

    assert result["status"] == "failed"
    assert result["fact_count"] == 0
    assert result["coverage_manifests"] == []
    assert result["errors"] == ["no accession-specific annual XBRL filings available"]


# --------------------------------------------------------------- LTM readiness rule


def _ltm_record(
    concept: str,
    *,
    statement: str = "IncomeStatement",
    dimensions: dict | None = None,
    period_end: str = "2025-06-30",
    label: str = "",
) -> dict:
    return {
        "statement": statement,
        "concept": concept,
        "label": label,
        "unit": "USD",
        "currency": "USD",
        "scale_factor": 1.0,
        "period_type": "duration",
        "period_end": period_end,
        "metadata": {"dimensions": dimensions or {}},
    }


_LTM_CORE = (
    ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "IncomeStatement"),
    ("us-gaap_OperatingIncomeLoss", "IncomeStatement"),
    ("us-gaap_NetIncomeLoss", "IncomeStatement"),
    ("us-gaap_DepreciationDepletionAndAmortization", "CashFlowStatement"),
    ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "CashFlowStatement"),
    ("us-gaap_NetCashProvidedByUsedInOperatingActivities", "CashFlowStatement"),
)


def _core_records() -> list[dict]:
    return [
        _ltm_record(concept, statement=statement)
        for concept, statement in _LTM_CORE
    ]


def test_ltm_status_is_constructed_when_every_required_key_is_present():
    from src.stage_00_data.filing_presentation import resolve_ltm_status

    core = _core_records()
    status, _, _ = resolve_ltm_status(
        annual_records=core,
        derived_ltm=core,
        annual_component_ends={"2025-06-30"},
    )
    assert status == "constructed"


def test_sparse_line_item_does_not_block_ltm_readiness():
    """PM decision 6: LTM is built only from period-compatible facts.

    A cash-flow line that appears in some years but cannot be quarterly-differenced
    (impairments, debt restructuring costs) must not block the whole ticker.
    """

    from src.stage_00_data.filing_presentation import resolve_ltm_status

    core = _core_records()
    sparse = _ltm_record(
        "us-gaap_PaymentsOfDebtRestructuringCosts",
        statement="CashFlowStatement",
    )
    status, expected, constructed = resolve_ltm_status(
        annual_records=[*core, sparse],
        derived_ltm=core,
        annual_component_ends={"2025-06-30"},
    )
    assert status == "constructed"
    # The gap stays visible even though it does not block.
    assert len(expected) - len(constructed) == 1


def test_dimensioned_facts_never_gate_ltm_readiness():
    """PM decision 7: dimensioned facts do not enter the consolidated view implicitly."""

    from src.stage_00_data.filing_presentation import resolve_ltm_status

    core = _core_records()
    segment = _ltm_record(
        "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
        dimensions={"srt:ProductOrServiceAxis": "msft:DevicesMember"},
    )
    status, expected, _ = resolve_ltm_status(
        annual_records=[*core, segment],
        derived_ltm=core,
        annual_component_ends={"2025-06-30"},
    )
    assert status == "constructed"
    # The dimensioned identity is excluded from the expected set entirely.
    assert len(expected) == len(core)


def test_missing_required_key_still_blocks_ltm():
    from src.stage_00_data.filing_presentation import resolve_ltm_status

    core = _core_records()
    without_da = [
        record
        for record in core
        if "Depreciation" not in record["concept"]
    ]
    status, _, _ = resolve_ltm_status(
        annual_records=core,
        derived_ltm=without_da,
        annual_component_ends={"2025-06-30"},
    )
    assert status == "partial"
