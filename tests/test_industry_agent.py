import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

import db.schema as schema
import src.agents.base_agent as base_agent_module
from src.agents.base_agent import BaseAgent
from src.agents.industry_agent import IndustryAgent


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    db_path = tmp_path / "industry_agent_test.db"
    monkeypatch.setattr(schema, "DB_PATH", db_path)
    monkeypatch.setattr(schema, "DATA_DIR", tmp_path)
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
def mock_anthropic(monkeypatch):
    monkeypatch.setattr(base_agent_module, "Anthropic", lambda *args, **kwargs: object())


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


def test_research_cache_hit_skips_llm(isolated_db, fixed_week, mock_anthropic, monkeypatch):
    _insert_cached_row(isolated_db)
    run_mock = Mock(return_value="{}")
    monkeypatch.setattr(BaseAgent, "run", run_mock)

    agent = IndustryAgent()
    result = agent.research("Technology", "Semiconductors")

    assert run_mock.call_count == 0
    assert result["week_key"] == "2026-10"
    assert result["source"] == "cached_source"
    assert result["consensus_growth_near"] == 0.10


def test_research_cache_miss_calls_llm_and_persists(isolated_db, fixed_week, mock_anthropic, monkeypatch):
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

    agent = IndustryAgent()
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


def test_research_force_refresh_calls_llm_even_with_cache(isolated_db, fixed_week, mock_anthropic, monkeypatch):
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

    agent = IndustryAgent()
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
