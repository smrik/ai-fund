import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stage_00_data.filing_retrieval import (
    FilingChunk,
    FilingSection,
    build_accounting_section_inventory,
    get_discovery_filing_context,
)
from src.stage_03_judgment.accounting_recast_agent import AccountingDiscoveryAgent


def _fake_agent_init(self, *args, **kwargs):
    self.client = None
    self.model = "test-model"
    self.name = "AccountingDiscoveryAgent"
    self.system_prompt = ""
    self.tools = []
    self.tool_handlers = {}


def _section(
    accession_no: str,
    section_key: str,
    label: str,
    text: str,
    *,
    form_type: str = "10-K",
    filing_date: str = "2025-07-30",
) -> FilingSection:
    return FilingSection(
        form_type=form_type,
        accession_no=accession_no,
        filing_date=filing_date,
        section_key=section_key,
        section_label=label,
        text=text,
        text_hash=f"hash-{accession_no}-{section_key}",
    )


def _chunk(
    accession_no: str,
    section_key: str,
    chunk_index: int,
    text: str,
) -> FilingChunk:
    return FilingChunk(
        form_type="10-K",
        accession_no=accession_no,
        filing_date="2025-07-30",
        section_key=section_key,
        chunk_index=chunk_index,
        text=text,
        chunk_hash=f"chunk-{accession_no}-{section_key}-{chunk_index}",
    )


def test_inventory_preserves_every_raw_note_and_marks_topic_aliases():
    sections = [
        _section("a1", "note_001", "NOTE 1 — ACCOUNTING POLICIES", "Note 1 accounting policies"),
        _section("a1", "note_002", "NOTE 2 — ACQUISITIONS", "Note 2 acquisitions"),
        _section("a1", "note_taxes", "Note Taxes", "Income tax uncertainty disclosure"),
        _section("a1", "mda", "MD&A", "Management discussion"),
    ]

    inventory = build_accounting_section_inventory(sections)

    assert [item["section_id"] for item in inventory] == [
        "a1::note_001",
        "a1::note_002",
        "a1::note_taxes",
    ]
    assert inventory[0]["heading"] == "NOTE 1 — ACCOUNTING POLICIES"
    assert inventory[0]["inventory_role"] == "raw_numbered_note"
    assert inventory[2]["inventory_role"] == "semantic_alias"


def test_discovery_agent_uses_all_context_and_rejects_invented_section_ids(monkeypatch):
    monkeypatch.setattr(
        "src.stage_03_judgment.accounting_recast_agent.BaseAgent.__init__",
        _fake_agent_init,
    )
    inventory = [
        {
            "section_id": "a1::note_001",
            "form_type": "10-K",
            "filing_date": "2025-07-30",
            "heading": "NOTE 1 — ACCOUNTING POLICIES",
            "preview": "Accounting policies include capitalization judgments.",
            "inventory_role": "raw_numbered_note",
        },
        {
            "section_id": "a1::note_002",
            "form_type": "10-K",
            "filing_date": "2025-07-30",
            "heading": "NOTE 2 — ACQUISITIONS",
            "preview": "Acquisition and purchase price allocation disclosures.",
            "inventory_role": "raw_numbered_note",
        },
    ]
    response = {
        "discovery_summary": "Acquisition accounting may affect comparability and reinvestment.",
        "questions": [
            {
                "question_id": "acquisition_recast",
                "question": "Are acquired-intangible amortization and deal costs distorting normalized EBIT?",
                "why_it_matters": "The answer can affect normalized margins and comparability.",
                "requested_section_ids": ["a1::note_002", "invented::note_999"],
                "search_terms": ["amortization", "transaction costs", "purchase price"],
                "possible_model_implications": [
                    "historical EBIT recast",
                    "forecast margin treatment",
                ],
                "priority": "high",
            }
        ],
        "coverage_notes": ["Headings alone do not prove an adjustment."],
    }
    prompts = []
    agent = AccountingDiscoveryAgent()
    monkeypatch.setattr(
        agent,
        "run",
        lambda prompt: prompts.append(prompt) or json.dumps(response),
    )

    result = agent.discover(
        "MSFT",
        section_inventory=inventory,
        business_context="Cloud and software platform with subscription economics.",
        industry_context="Cloud infrastructure demand is capital intensive.",
        quantitative_context="Historical EBIT margin 46%; capex/revenue rose to 31%.",
        current_model_context="CIQ debt includes lease liabilities.",
    )

    question = result["questions"][0]
    assert question["requested_section_ids"] == ["a1::note_002"]
    assert question["invalid_section_ids"] == ["invented::note_999"]
    assert "subscription economics" in prompts[0]
    assert "capital intensive" in prompts[0]
    assert "Historical EBIT margin" in prompts[0]
    assert "CIQ debt includes lease liabilities" in prompts[0]
    assert "NOTE 1 — ACCOUNTING POLICIES" in prompts[0]
    assert "Do not limit discovery to a predefined adjustment taxonomy" in prompts[0]


def test_discovery_requests_drive_focused_chunk_retrieval(monkeypatch):
    chunks = [
        _chunk("a1", "note_001", 0, "General accounting policies and estimates."),
        _chunk("a1", "note_002", 0, "The company completed two acquisitions."),
        _chunk(
            "a1",
            "note_002",
            1,
            "Acquired intangible amortization was material and transaction costs were expensed.",
        ),
        _chunk("a1", "note_003", 0, "Income taxes and uncertain tax positions."),
    ]
    corpus = {
        "ticker": "MSFT",
        "sources": [
            {
                "form_type": "10-K",
                "accession_no": "a1",
                "filing_date": "2025-07-30",
                "doc_name": "msft-2025-10k",
                "section_keys": ["note_001", "note_002", "note_003"],
            }
        ],
        "sections": [],
        "chunks": chunks,
        "corpus_hash": "corpus-hash",
        "section_coverage": {},
        "statement_presence": {},
    }
    monkeypatch.setattr(
        "src.stage_00_data.filing_retrieval.build_filing_corpus",
        lambda *args, **kwargs: corpus,
    )
    discovery = {
        "questions": [
            {
                "question_id": "acquisition_recast",
                "requested_section_ids": ["a1::note_002"],
                "search_terms": ["amortization", "transaction costs"],
            }
        ]
    }

    bundle = get_discovery_filing_context("MSFT", discovery, max_selected_chunks=2)

    assert [chunk.section_key for chunk in bundle.selected_chunks] == [
        "note_002",
        "note_002",
    ]
    assert "Acquired intangible amortization" in bundle.selected_chunks[0].text
    assert bundle.retrieval_summary["requested_section_ids"] == ["a1::note_002"]
    assert bundle.retrieval_summary["unmatched_section_ids"] == []
    assert "acquisition_recast" in bundle.retrieval_summary["question_ids"]
