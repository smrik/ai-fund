from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from config import DB_PATH
from db.schema import create_tables
from src.stage_00_data import market_data


_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "analyst_action": ("upgrade", "upgrades", "downgrade", "downgrades", "initiates", "price target"),
    "earnings": ("earnings", "results", "quarter"),
    "guidance": ("guidance", "outlook", "forecast"),
    "m&a": ("acquisition", "merger", "deal", "buyout"),
    "litigation": ("litigation", "lawsuit", "settlement", "investigation"),
    "regulatory": ("regulatory", "regulation", "approval", "antitrust"),
    "financing": ("debt", "refinancing", "bond", "capital raise"),
    "restructuring": ("restructuring", "layoff", "impairment", "charge"),
    "product/ai": ("ai", "product", "launch", "platform", "watsonx"),
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _days_old(value: str | None) -> int | None:
    ts = _parse_ts(value)
    if ts is None:
        return None
    now = datetime.now(timezone.utc)
    return max((now - ts.astimezone(timezone.utc)).days, 0)


def _topic_bucket(title: str) -> str:
    haystack = (title or "").lower()
    for bucket, keywords in _TOPIC_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return bucket
    return "general"


def _materiality_score(title: str, published: str | None) -> float:
    topic = _topic_bucket(title)
    topic_weight = {
        "analyst_action": 0.98,
        "earnings": 1.0,
        "guidance": 0.95,
        "m&a": 0.9,
        "litigation": 0.85,
        "regulatory": 0.8,
        "financing": 0.75,
        "restructuring": 0.8,
        "product/ai": 0.7,
        "general": 0.45,
    }[topic]
    age_days = _days_old(published)
    if age_days is None:
        recency = 0.35
    elif age_days <= 2:
        recency = 1.0
    elif age_days <= 7:
        recency = 0.8
    elif age_days <= 30:
        recency = 0.55
    else:
        recency = 0.3
    analyst_action_boost = 0.05 if topic == "analyst_action" else 0.0
    return round(100 * min(1.0, 0.65 * topic_weight + 0.35 * recency + analyst_action_boost), 1)


def _materiality_bucket(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def _latest_archived_sentiment(ticker: str) -> dict[str, Any]:
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT memo_json
                FROM pipeline_report_archive
                WHERE ticker = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                [ticker],
            ).fetchone()
    except Exception:
        return {}
    if row is None or not row["memo_json"]:
        return {}
    try:
        memo = json.loads(row["memo_json"])
    except Exception:
        return {}
    return memo.get("sentiment") or {}


def _archived_report_rows(ticker: str) -> list[dict[str, Any]]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, action, conviction, memo_json
                FROM pipeline_report_archive
                WHERE ticker = ?
                ORDER BY created_at ASC, id ASC
                """,
                [ticker],
            ).fetchall()
    except Exception:
        return []
    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            memo = json.loads(row["memo_json"]) if row["memo_json"] else {}
        except Exception:
            memo = {}
        results.append(
            {
                "created_at": row["created_at"],
                "action": row["action"],
                "conviction": row["conviction"],
                "memo": memo,
            }
        )
    return results


def _compact_date(value: str | None) -> str | None:
    if not value:
        return None
    parsed = _parse_ts(value)
    if parsed is None:
        return value
    return parsed.date().isoformat()


def _timeline_event(date_value: str | None, *, source: str, summary: str, category: str) -> dict[str, Any]:
    return {
        "date": date_value,
        "date_label": _compact_date(date_value),
        "source": source,
        "category": category,
        "summary": summary,
    }


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _build_historical_brief(ticker: str) -> tuple[dict[str, Any], list[str]]:
    archive_rows = _archived_report_rows(ticker)
    if not archive_rows:
        return (
            {
                "summary": "Limited local history: no archived reports are available yet, so the historical brief is based only on the current recent-news surface.",
                "event_timeline": [],
                "period_start": None,
                "period_end": None,
            },
            ["Limited historical brief uses limited local evidence"],
        )

    timeline: list[dict[str, Any]] = []
    recurring_topics: list[str] = []
    actions_seen: list[str] = []
    for row in archive_rows:
        memo = row["memo"] or {}
        filings = memo.get("filings") or {}
        earnings = memo.get("earnings") or {}
        updates = _coerce_list(filings.get("recent_quarter_updates"))
        notes = _coerce_list(filings.get("notes_watch_items"))
        disclosures = _coerce_list(earnings.get("quarterly_disclosure_changes"))
        key_risks = _coerce_list(memo.get("key_risks"))
        action = (row.get("action") or "").upper()
        conviction = row.get("conviction") or "n/a"
        if action:
            actions_seen.append(action)
            timeline.append(
                _timeline_event(
                    row["created_at"],
                    source="report_archive",
                    category="research_stance",
                    summary=f"Research stance {action} ({conviction})",
                )
            )
        for category, items in (
            ("quarter_update", updates[:1]),
            ("note_watch", notes[:1]),
            ("disclosure_change", disclosures[:1]),
            ("key_risk", key_risks[:1]),
        ):
            for item in items:
                timeline.append(
                    _timeline_event(
                        row["created_at"],
                        source="report_archive",
                        category=category,
                        summary=item,
                    )
                )
        recurring_topics.extend(notes[:1] + updates[:1] + disclosures[:1] + key_risks[:1])

    timeline.sort(key=lambda item: (item.get("date") or "", item.get("category") or ""))
    recurring = "; ".join(recurring_topics[:4]) if recurring_topics else "archived research stance changes"
    latest_action = actions_seen[-1] if actions_seen else "N/A"
    summary = (
        f"Local history from {len(archive_rows)} archived reports, most recently {latest_action}, highlights {recurring}. "
        "This brief is derived from archived report snapshots and current local evidence, not a full historical news database."
    )
    return (
        {
            "summary": summary,
            "event_timeline": timeline,
            "period_start": archive_rows[0]["created_at"],
            "period_end": archive_rows[-1]["created_at"],
        },
        ([] if len(archive_rows) >= 2 else ["Limited historical brief uses limited local evidence"]),
    )


def build_news_materiality_view(ticker: str, limit: int = 25) -> dict:
    ticker = ticker.upper().strip()
    headlines = market_data.get_news(ticker, limit=limit)
    ranked = []
    for item in headlines:
        title = item.get("title") or ""
        published = item.get("published")
        topic_bucket = _topic_bucket(title)
        score = _materiality_score(title, published)
        ranked.append(
            {
                "date": published,
                "source": item.get("publisher", ""),
                "title": title,
                "summary": item.get("summary") or item.get("snippet") or "",
                "url": item.get("link", ""),
                "materiality_score": score,
                "materiality_bucket": _materiality_bucket(score),
                "topic_bucket": topic_bucket,
                "analyst_action": topic_bucket == "analyst_action",
            }
        )
    ranked.sort(key=lambda row: (row["materiality_score"], row.get("date") or ""), reverse=True)
    quarterly_headlines = [row for row in ranked if (_days_old(row.get("date")) or 9999) <= 120]
    historical_brief, history_flags = _build_historical_brief(ticker)
    audit_flags = list(history_flags)
    if not ranked:
        audit_flags.append("No recent headlines available")
    return {
        "ticker": ticker,
        "available": bool(ranked),
        "headline_count": len(ranked),
        "historical_brief": historical_brief,
        "quarterly_headlines": quarterly_headlines,
        "headlines": ranked,
        "analyst_snapshot": market_data.get_analyst_ratings(ticker),
        "sentiment_summary": _latest_archived_sentiment(ticker),
        "audit_flags": audit_flags,
    }
