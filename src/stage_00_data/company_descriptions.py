"""Reusable company business-description cache for peer similarity."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

import yfinance as yf

from config import DB_PATH
from db.loader import upsert_company_text_cache
from db.schema import create_tables
from src.stage_00_data import edgar_client


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fetch_yfinance_business_description(ticker: str) -> dict | None:
    info = yf.Ticker(ticker).info or {}
    text = (info.get("longBusinessSummary") or "").strip()
    if not text:
        return None
    return {
        "text": text,
        "source": "yfinance_longBusinessSummary",
        "as_of_date": None,
    }


def _extract_edgar_item1_business(ticker: str) -> dict | None:
    text = edgar_client.get_10k_text(ticker, max_chars=120_000)
    if not text:
        return None
    lower = text.lower()
    start = lower.find("item 1")
    if start < 0:
        return None
    end_candidates = [
        pos
        for pos in (lower.find("item 1a", start + 1), lower.find("item 2", start + 1))
        if pos > start
    ]
    end = min(end_candidates) if end_candidates else min(len(text), start + 12_000)
    item1 = text[start:end].strip()
    if not item1:
        return None
    return {
        "text": item1,
        "source": "edgar_item1_business",
        "as_of_date": None,
    }


def _load_cached_description(conn: sqlite3.Connection, ticker: str) -> dict | None:
    row = conn.execute(
        """
        SELECT ticker, source, source_as_of_date, text_hash, text_content
        FROM company_text_cache
        WHERE ticker = ? AND text_type = 'business_description'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        [ticker.upper()],
    ).fetchone()
    if row is None:
        return None
    return {
        "ticker": str(row["ticker"]),
        "text": str(row["text_content"]),
        "source": str(row["source"]),
        "text_hash": str(row["text_hash"]),
        "as_of_date": row["source_as_of_date"],
    }


def get_business_description(ticker: str) -> dict | None:
    """Return a cached or freshly fetched business description for a ticker."""
    ticker = ticker.upper().strip()
    conn = _connect()
    try:
        cached = _load_cached_description(conn, ticker)
        if cached is not None:
            return cached

        payload = _fetch_yfinance_business_description(ticker) or _extract_edgar_item1_business(ticker)
        if payload is None:
            return None

        text = str(payload["text"]).strip()
        text_hash = _hash_text(text)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        upsert_company_text_cache(
            conn,
            {
                "ticker": ticker,
                "text_type": "business_description",
                "source": payload["source"],
                "source_as_of_date": payload.get("as_of_date"),
                "text_hash": text_hash,
                "text_content": text,
                "fetched_at": now,
                "updated_at": now,
            },
        )
        return {
            "ticker": ticker,
            "text": text,
            "source": payload["source"],
            "text_hash": text_hash,
            "as_of_date": payload.get("as_of_date"),
        }
    finally:
        conn.close()
