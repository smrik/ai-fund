from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_build_news_materiality_view_ranks_headlines_and_enriches_analyst_signals(monkeypatch, tmp_path):
    from src.stage_04_pipeline import news_materiality

    db_path = tmp_path / "archive.db"
    with _temp_conn_factory(db_path)() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_report_archive (
                ticker, created_at, action, conviction, memo_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                "IBM",
                "2024-03-15T12:00:00+00:00",
                "buy",
                "high",
                '{"sentiment": {"direction": "neutral", "score": 0.1}, "filings": {"recent_quarter_updates": ["Margin pressure intensified"], "notes_watch_items": ["Lease liabilities increased"]}}',
            ],
        )
        conn.execute(
            """
            INSERT INTO pipeline_report_archive (
                ticker, created_at, action, conviction, memo_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                "IBM",
                "2025-07-01T12:00:00+00:00",
                "hold",
                "medium",
                '{"sentiment": {"direction": "cautious", "score": -0.2}, "filings": {"recent_quarter_updates": ["Guidance narrowed"], "notes_watch_items": ["Restructuring charges disclosed"]}}',
            ],
        )
        conn.commit()

    monkeypatch.setattr(news_materiality, "DB_PATH", db_path)
    monkeypatch.setattr(
        news_materiality.market_data,
        "get_news",
        lambda ticker, limit=25: [
            {
                "title": "Broker upgrades IBM after guidance raise",
                "publisher": "Reuters",
                "link": "https://example.com/1",
                "summary": "Analysts cite stronger demand.",
                "published": "2026-03-14T10:00:00Z",
            },
            {
                "title": "IBM launches new AI product",
                "publisher": "Bloomberg",
                "link": "https://example.com/2",
                "summary": "Incremental platform launch.",
                "published": "2026-02-10T10:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(
        news_materiality.market_data,
        "get_analyst_ratings",
        lambda ticker: {"recommendation": "buy", "target_mean": 120.0, "num_analysts": 15},
    )

    view = news_materiality.build_news_materiality_view("IBM")

    assert view["available"] is True
    assert view["headline_count"] == 2
    assert view["headlines"][0]["analyst_action"] is True
    assert view["headlines"][0]["topic_bucket"] == "analyst_action"
    assert view["headlines"][0]["materiality_score"] >= view["headlines"][1]["materiality_score"]
    assert view["analyst_snapshot"]["recommendation"] == "buy"
    assert view["sentiment_summary"]["direction"] == "cautious"
    assert view["historical_brief"]["event_timeline"]
    assert view["historical_brief"]["period_start"] == "2024-03-15T12:00:00+00:00"
    assert view["quarterly_headlines"][0]["title"] == "Broker upgrades IBM after guidance raise"


def test_build_news_materiality_view_handles_empty_news_and_missing_archive(monkeypatch, tmp_path):
    from src.stage_04_pipeline import news_materiality

    db_path = tmp_path / "archive.db"
    monkeypatch.setattr(news_materiality, "DB_PATH", db_path)
    monkeypatch.setattr(news_materiality.market_data, "get_news", lambda ticker, limit=25: [])
    monkeypatch.setattr(
        news_materiality.market_data,
        "get_analyst_ratings",
        lambda ticker: {"recommendation": "hold", "target_mean": None, "num_analysts": 0},
    )

    view = news_materiality.build_news_materiality_view("IBM")

    assert view["available"] is False
    assert view["headline_count"] == 0
    assert view["headlines"] == []
    assert view["quarterly_headlines"] == []
    assert view["sentiment_summary"] == {}
    assert view["historical_brief"]["summary"].startswith("Limited local history")
    assert "No recent headlines available" in view["audit_flags"]
