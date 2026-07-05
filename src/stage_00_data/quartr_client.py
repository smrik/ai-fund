from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from db.schema import create_tables, get_connection
from src.contracts.transcript import TranscriptDocument, TranscriptParagraph

logger = logging.getLogger(__name__)

BASE_URL = "https://api.quartr.com/public/v1"
MISSING_API_KEY_ERROR = "QUARTR_API_KEY is required; set the env var before calling Quartr APIs"


def _api_key() -> str:
    key = os.getenv("QUARTR_API_KEY", "").strip()
    if not key:
        raise RuntimeError(MISSING_API_KEY_ERROR)
    return key


def _request_json(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    logger.debug("Calling Quartr API: %s", path)
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {_api_key()}"},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _date_only(value: Any) -> str:
    if not value:
        raise ValueError("event_date is required")
    return str(value)[:10]


def _paragraph_from_payload(index: int, payload: dict[str, Any]) -> TranscriptParagraph:
    return TranscriptParagraph(
        index=int(_pick(payload, "index", "paragraphIndex") or index),
        speaker_name=str(_pick(payload, "speaker_name", "speakerName", "name") or "").strip(),
        speaker_role=str(_pick(payload, "speaker_role", "speakerRole", "role") or "").strip(),
        start_time=_pick(payload, "start_time", "startTime"),
        end_time=_pick(payload, "end_time", "endTime"),
        text=str(_pick(payload, "text", "paragraph", "content") or "").strip(),
        deep_link_url=_pick(payload, "deep_link_url", "deepLinkUrl", "deepLinkURL"),
    )


def _normalize_transcript(event: dict[str, Any], payload: dict[str, Any]) -> TranscriptDocument:
    transcript_payload = payload.get("transcript") if isinstance(payload.get("transcript"), dict) else payload
    paragraph_payloads = _items(transcript_payload, "paragraphs", "items")
    paragraphs = [
        _paragraph_from_payload(index, paragraph)
        for index, paragraph in enumerate(paragraph_payloads)
    ]

    event_id = str(_pick(event, "event_id", "eventId", "id") or _pick(transcript_payload, "event_id", "eventId") or "")
    document_id = str(_pick(transcript_payload, "document_id", "documentId", "id") or _pick(event, "document_id", "documentId") or "")
    transcript_source = _pick(transcript_payload, "transcript_source", "transcriptSource")

    return TranscriptDocument(
        ticker=str(_pick(event, "ticker", "companyTicker") or _pick(transcript_payload, "ticker") or ""),
        source="quartr",
        event_id=event_id,
        event_title=str(_pick(event, "event_title", "eventTitle", "title", "name") or _pick(transcript_payload, "event_title", "eventTitle") or ""),
        event_date=_date_only(_pick(event, "event_date", "eventDate", "date", "startDate")),
        fiscal_quarter=_pick(event, "fiscal_quarter", "fiscalQuarter"),
        fiscal_year=_pick(event, "fiscal_year", "fiscalYear"),
        document_id=document_id,
        document_url=str(_pick(transcript_payload, "document_url", "documentUrl", "url") or _pick(event, "document_url", "documentUrl") or ""),
        transcript_source=transcript_source,
        paragraphs=paragraphs,
    )


def _fiscal_label(doc: TranscriptDocument) -> str | None:
    if doc.fiscal_quarter is not None and doc.fiscal_year is not None:
        return f"Q{doc.fiscal_quarter} FY{doc.fiscal_year}"
    if doc.fiscal_year is not None:
        return f"FY{doc.fiscal_year}"
    return None


def resolve_company(ticker: str) -> dict:
    """Resolve a ticker to a Quartr company payload."""
    normalized = ticker.strip().upper()
    payload = _request_json("/companies", {"query": normalized})
    companies = _items(payload, "companies", "results")
    for company in companies:
        if str(_pick(company, "ticker", "symbol") or "").upper() == normalized:
            return company
    if len(companies) == 1:
        return companies[0]
    raise RuntimeError(f"Quartr company not found for ticker {normalized}")


def list_recent_earnings_events(company_id: str, limit: int = 4) -> list[dict]:
    """List recent Quartr earnings events for a company id."""
    payload = _request_json(
        f"/companies/{company_id}/events",
        {"type": "earnings", "limit": int(limit)},
    )
    return _items(payload, "events", "earningsEvents")


def fetch_transcript(event: dict) -> TranscriptDocument:
    """Fetch and normalize a Quartr transcript for one event."""
    event_id = _pick(event, "event_id", "eventId", "id")
    if not event_id:
        raise ValueError("event must include event_id, eventId, or id")
    payload = _request_json(f"/events/{event_id}/transcript")
    if not isinstance(payload, dict):
        raise ValueError("Quartr transcript response must be a JSON object")
    return _normalize_transcript(event, payload)


def persist_transcript(doc: TranscriptDocument) -> None:
    """Upsert a normalized transcript into transcript_cache."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(doc.model_dump(mode="json"), sort_keys=True)
    with get_connection() as conn:
        create_tables(conn)
        conn.execute(
            """
            INSERT INTO transcript_cache (
                ticker, event_date, fiscal_label, source, document_id, fetched_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, source, document_id) DO UPDATE SET
                event_date = excluded.event_date,
                fiscal_label = excluded.fiscal_label,
                fetched_at = excluded.fetched_at,
                payload = excluded.payload
            """,
            (
                doc.ticker,
                doc.event_date,
                _fiscal_label(doc),
                doc.source,
                doc.document_id,
                fetched_at,
                payload,
            ),
        )
        conn.commit()
