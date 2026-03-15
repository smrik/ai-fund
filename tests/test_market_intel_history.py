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


def test_market_intel_history_builds_timeline_from_archives_and_recent_news(monkeypatch, tmp_path):
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
                "2024-06-30T12:00:00+00:00",
                "WATCH",
                "medium",
                '{"sentiment": {"direction": "neutral", "score": 0.1}, "filings": {"notes_watch_items": ["Lease liabilities increased"], "recent_quarter_updates": ["Margin compressed"]}, "earnings": {"quarterly_disclosure_changes": ["Added litigation disclosure"]}, "key_risks": ["Consulting slowdown"]}',
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
                "2025-12-15T12:00:00+00:00",
                "BUY",
                "high",
                '{"sentiment": {"direction": "bullish", "score": 0.4}, "filings": {"notes_watch_items": ["Restructuring charge"], "recent_quarter_updates": ["Bookings improved"]}, "earnings": {"quarterly_disclosure_changes": ["Raised AI disclosures"]}, "key_risks": ["Execution risk"]}',
            ],
        )
        conn.commit()

    monkeypatch.setattr(news_materiality, "DB_PATH", db_path)
    monkeypatch.setattr(
        news_materiality.market_data,
        "get_news",
        lambda ticker, limit=25: [
            {"title": "IBM raises guidance after earnings", "publisher": "Reuters", "link": "https://example.com/1", "summary": "Demand improved", "published": "2026-03-10T10:00:00Z"},
            {"title": "IBM launches new AI platform", "publisher": "Bloomberg", "link": "https://example.com/2", "summary": "Platform update", "published": "2026-02-10T10:00:00Z"},
        ],
    )
    monkeypatch.setattr(
        news_materiality.market_data,
        "get_analyst_ratings",
        lambda ticker: {"recommendation": "buy", "target_mean": 120.0, "num_analysts": 15},
    )

    view = news_materiality.build_news_materiality_view("IBM")

    assert view["historical_brief"]["event_timeline"]
    assert "BUY" in view["historical_brief"]["summary"]
    assert view["historical_brief"]["period_start"].startswith("2024-06-30")
    assert len(view["quarterly_headlines"]) == 2


def test_market_intel_history_flags_limited_history(monkeypatch, tmp_path):
    from src.stage_04_pipeline import news_materiality

    db_path = tmp_path / "archive.db"
    monkeypatch.setattr(news_materiality, "DB_PATH", db_path)
    monkeypatch.setattr(news_materiality.market_data, "get_news", lambda ticker, limit=25: [])
    monkeypatch.setattr(news_materiality.market_data, "get_analyst_ratings", lambda ticker: {})

    view = news_materiality.build_news_materiality_view("IBM")

    assert view["historical_brief"]["summary"]
    assert "limited" in view["historical_brief"]["summary"].lower()
    assert "Limited historical brief" in view["audit_flags"][0]
