import json
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

import db.schema as schema
import src.stage_03_judgment.base_agent as base_agent_module
from src.stage_02_valuation.driver_assessments import DriverAssessment, build_driver_consensus
from src.stage_02_valuation.valuation_types import ForecastDrivers
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_03_judgment.industry_agent import IndustryAgent


class _FakeResearchClient:
    model = "gemini-3-flash-preview"

    def __init__(self, payload: dict, metadata: dict | None = None):
        self.payload = payload
        self.metadata = metadata or {"sources": [{"title": "Source", "uri": "https://example.com"}]}
        self.calls = []

    def generate_json(self, *, system_prompt: str, user_prompt: str):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self.payload, self.metadata


@pytest.fixture
def isolated_db(monkeypatch):
    tmp_dir = Path(".tmp-tests") / "industry-agent"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_dir / f"industry_agent_{uuid.uuid4().hex}.db"
    monkeypatch.setattr(schema, "DB_PATH", db_path)
    monkeypatch.setattr(schema, "DATA_DIR", tmp_dir)
    schema.create_tables()
    return db_path


@pytest.fixture
def fixed_week(monkeypatch):
    monkeypatch.setattr(
        IndustryAgent,
        "_current_week_key",
        staticmethod(lambda: "2026-10"),
    )


@pytest.fixture
def mock_llm_client(monkeypatch):
    monkeypatch.setattr(base_agent_module, "OpenAI", lambda *args, **kwargs: object())


def _insert_cached_row(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO industry_benchmarks (
            sector, industry, week_key, consensus_growth_near, consensus_growth_mid,
            margin_benchmark, valuation_framework, source, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Technology",
            "Semiconductors",
            "2026-10",
            0.10,
            0.06,
            0.24,
            "ev_ebitda",
            "cached_source",
            "cached notes",
            "2026-03-06T00:00:00Z",
            "2026-03-06T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()


def _forecast_drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=1_000_000_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.18,
        ebit_margin_target=0.20,
        tax_rate_start=0.22,
        tax_rate_target=0.23,
        capex_pct_start=0.05,
        capex_pct_target=0.045,
        da_pct_start=0.03,
        da_pct_target=0.028,
        dso_start=45.0,
        dso_target=44.0,
        dio_start=40.0,
        dio_target=39.0,
        dpo_start=35.0,
        dpo_target=36.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=200_000_000.0,
        shares_outstanding=100_000_000.0,
    )


def test_research_cache_hit_skips_llm(isolated_db, fixed_week, mock_llm_client, monkeypatch):
    _insert_cached_row(isolated_db)
    run_mock = Mock(return_value="{}")
    monkeypatch.setattr(BaseAgent, "run", run_mock)

    agent = IndustryAgent(client=_FakeResearchClient({}))
    result = agent.research("Technology", "Semiconductors")

    assert run_mock.call_count == 0
    assert result["week_key"] == "2026-10"
    assert result["source"] == "cached_source"
    assert result["consensus_growth_near"] == 0.10


def test_research_cache_miss_calls_llm_and_persists(isolated_db, fixed_week, mock_llm_client, monkeypatch):
    payload = {
        "sector": "Technology",
        "industry": "Semiconductors",
        "week_key": "2026-10",
        "consensus_growth_near": 0.12,
        "consensus_growth_mid": 0.07,
        "margin_benchmark": 0.26,
        "valuation_framework": "ev_ebitda_plus_reverse_dcf",
        "source": "llm_synthesis",
        "notes": "Strong AI capex tailwinds.",
    }
    run_mock = Mock(return_value=json.dumps(payload))
    monkeypatch.setattr(BaseAgent, "run", run_mock)

    agent = IndustryAgent(client=_FakeResearchClient({}))
    result = agent.research("Technology", "Semiconductors")

    assert run_mock.call_count == 1
    assert result["week_key"] == "2026-10"
    assert result["consensus_growth_near"] == 0.12
    assert result["valuation_framework"] == "ev_ebitda_plus_reverse_dcf"

    conn = sqlite3.connect(str(isolated_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT * FROM industry_benchmarks
        WHERE sector = ? AND industry = ? AND week_key = ?
        """,
        ("Technology", "Semiconductors", "2026-10"),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["consensus_growth_mid"] == 0.07
    assert row["source"] == "llm_synthesis"


def test_research_force_refresh_calls_llm_even_with_cache(isolated_db, fixed_week, mock_llm_client, monkeypatch):
    _insert_cached_row(isolated_db)
    run_mock = Mock(
        return_value=json.dumps(
            {
                "sector": "Technology",
                "industry": "Semiconductors",
                "week_key": "2026-10",
                "consensus_growth_near": 0.15,
                "consensus_growth_mid": 0.09,
                "margin_benchmark": 0.30,
                "valuation_framework": "sum_of_the_parts",
                "source": "refreshed_llm",
                "notes": "Refreshed weekly benchmarks.",
            }
        )
    )
    monkeypatch.setattr(BaseAgent, "run", run_mock)

    agent = IndustryAgent(client=_FakeResearchClient({}))
    result = agent.research("Technology", "Semiconductors", force_refresh=True)

    assert run_mock.call_count == 1
    assert result["consensus_growth_near"] == 0.15
    assert result["source"] == "refreshed_llm"

    conn = sqlite3.connect(str(isolated_db))
    row = conn.execute(
        """
        SELECT consensus_growth_near, source
        FROM industry_benchmarks
        WHERE sector = ? AND industry = ? AND week_key = ?
        """,
        ("Technology", "Semiconductors", "2026-10"),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == 0.15
    assert row[1] == "refreshed_llm"


def test_research_company_uses_gemini_context_without_perplexity(isolated_db, mock_llm_client, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    run_mock = Mock(side_effect=AssertionError("research_company should use Gemini adapter"))
    monkeypatch.setattr(BaseAgent, "run", run_mock)
    client = _FakeResearchClient(
        {
            "ticker": "NVDA",
            "company_name": "NVIDIA",
            "sector": "Technology",
            "industry": "Semiconductors",
            "industry_structure": "Accelerated compute market is concentrated.",
            "current_cycle": "AI capex remains strong.",
            "company_positioning": "Leader in data-center GPUs.",
            "valuation_framework": "revenue growth and margin durability",
            "consensus_growth_near": 0.14,
            "consensus_growth_mid": 0.09,
            "margin_benchmark": 0.29,
            "recent_events": ["AI infrastructure spending remains elevated."],
            "sector_tailwinds": ["Cloud AI capex"],
            "sector_headwinds": ["Export controls"],
            "macro_relevance": "Rates matter less than capex cycle.",
            "key_catalyst_watch": "Next earnings guide.",
            "driver_assessments": [
                {
                    "field": "revenue_growth_near",
                    "proposed_value": 0.14,
                    "range_low": 0.10,
                    "range_high": 0.18,
                    "confidence": "high",
                    "rationale": "AI demand supports near-term growth.",
                    "evidence_reference": "grounded search + company context",
                },
                {
                    "field": "ebit_margin_target",
                    "proposed_value": 0.29,
                    "range_low": 0.26,
                    "range_high": 0.31,
                    "confidence": "medium",
                    "rationale": "Scale and mix support margin expansion.",
                    "evidence_reference": "grounded search + margin profile",
                },
            ],
            "source_notes": ["Google Search grounding used."],
            "confidence": "medium",
        }
    )
    agent = IndustryAgent(client=client)

    result = agent.research_company(
        {
            "ticker": "NVDA",
            "company_name": "NVIDIA",
            "sector": "Technology",
            "industry": "Semiconductors",
            "business_description": "Designs accelerated computing platforms.",
            "current_drivers": {
                "revenue_growth_near": 0.08,
                "revenue_growth_mid": 0.05,
                "ebit_margin_target": 0.20,
            },
        }
    )

    assert run_mock.call_count == 0
    assert client.calls
    assert "Designs accelerated computing platforms" in client.calls[0]["user_prompt"]
    assert result["model"] == "gemini-3-flash-preview"
    assert result["ticker"] == "NVDA"
    assert result["grounding"]["sources"][0]["uri"] == "https://example.com"
    assert result["driver_assessments"][0]["approval_status"] == "advisory"

    assessments = [DriverAssessment(**item) for item in result["driver_assessments"]]
    consensus = build_driver_consensus(_forecast_drivers(), assessments)
    consensus_by_field = {row.field: row for row in consensus}
    assert consensus_by_field["revenue_growth_near"].suggested_value == pytest.approx(0.14)
    assert consensus_by_field["ebit_margin_target"].suggested_value == pytest.approx(0.29)


def test_get_recent_events_wraps_company_research(isolated_db, mock_llm_client):
    client = _FakeResearchClient(
        {
            "ticker": "MSFT",
            "company_name": "Microsoft",
            "sector": "Technology",
            "industry": "Technology",
            "industry_structure": "Cloud and software.",
            "current_cycle": "AI/cloud demand.",
            "company_positioning": "Hyperscale leader.",
            "valuation_framework": "cloud growth",
            "consensus_growth_near": 0.08,
            "consensus_growth_mid": 0.06,
            "margin_benchmark": 0.35,
            "recent_events": ["Azure AI demand healthy."],
            "sector_tailwinds": ["AI workloads"],
            "sector_headwinds": ["Capacity constraints"],
            "macro_relevance": "Enterprise spend resilient.",
            "key_catalyst_watch": "Azure growth.",
            "confidence": "medium",
        }
    )
    agent = IndustryAgent(client=client)

    events = agent.get_recent_events("MSFT", "Technology")

    assert events["ticker"] == "MSFT"
    assert events["recent_events"] == ["Azure AI demand healthy."]
    assert events["search_available"] is True
