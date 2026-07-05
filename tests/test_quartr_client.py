from __future__ import annotations

from typing import Any

from db.schema import get_connection
from src.contracts.transcript import TranscriptDocument
from src.stage_00_data import quartr_client


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def test_quartr_client_raises_when_api_key_absent(monkeypatch) -> None:
    monkeypatch.delenv("QUARTR_API_KEY", raising=False)

    try:
        quartr_client.resolve_company("MSFT")
    except RuntimeError as exc:
        assert str(exc) == "QUARTR_API_KEY is required; set the env var before calling Quartr APIs"
    else:
        raise AssertionError("resolve_company should fail closed without QUARTR_API_KEY")


def test_quartr_client_fetches_and_persists_mock_transcript(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "alpha_pod.db"
    monkeypatch.setenv("ALPHA_POD_DB_PATH", str(db_path))
    monkeypatch.setenv("QUARTR_API_KEY", "test-key")
    calls: list[tuple[str, dict[str, Any] | None]] = []

    def fake_get(url: str, headers: dict[str, str], params: dict[str, Any] | None, timeout: int) -> _FakeResponse:
        assert headers == {"Authorization": "Bearer test-key"}
        assert timeout == 30
        path = url.removeprefix(quartr_client.BASE_URL)
        calls.append((path, params))
        if path == "/companies":
            return _FakeResponse(
                {
                    "data": [
                        {
                            "id": "company-msft",
                            "ticker": "MSFT",
                            "name": "Microsoft Corporation",
                        }
                    ]
                }
            )
        if path == "/companies/company-msft/events":
            return _FakeResponse(
                {
                    "events": [
                        {
                            "id": "event-msft-q3-fy26",
                            "ticker": "MSFT",
                            "title": "Microsoft Q3 FY26 Earnings Call",
                            "date": "2025-05-01T20:30:00Z",
                            "fiscalQuarter": 3,
                            "fiscalYear": 2026,
                        }
                    ]
                }
            )
        if path == "/events/event-msft-q3-fy26/transcript":
            return _FakeResponse(
                {
                    "documentId": "msft-q3-fy26-live",
                    "documentUrl": "https://example.quartr.com/msft/events/event-msft-q3-fy26/transcript",
                    "transcriptSource": "live",
                    "paragraphs": [
                        {
                            "speakerName": "Satya Nadella",
                            "speakerRole": "Chairman and Chief Executive Officer",
                            "startTime": "00:01:00",
                            "endTime": "00:02:30",
                            "text": "Customers continue to adopt Microsoft Cloud and AI services.",
                            "deepLinkUrl": "https://example.quartr.com/msft/events/event-msft-q3-fy26?t=60",
                        },
                        {
                            "speakerName": "Amy Hood",
                            "speakerRole": "Executive Vice President and Chief Financial Officer",
                            "startTime": "00:12:00",
                            "endTime": "00:13:45",
                            "text": "We delivered disciplined operating leverage while investing in cloud infrastructure.",
                            "deepLinkUrl": "https://example.quartr.com/msft/events/event-msft-q3-fy26?t=720",
                        },
                    ],
                }
            )
        raise AssertionError(f"unexpected URL path: {path}")

    monkeypatch.setattr(quartr_client.requests, "get", fake_get)

    company = quartr_client.resolve_company("msft")
    events = quartr_client.list_recent_earnings_events(company["id"], limit=1)
    doc = quartr_client.fetch_transcript(events[0])
    quartr_client.persist_transcript(doc)

    assert company["id"] == "company-msft"
    assert len(events) == 1
    assert isinstance(doc, TranscriptDocument)
    assert doc.ticker == "MSFT"
    assert doc.document_id == "msft-q3-fy26-live"
    assert doc.transcript_source == "live"
    assert doc.paragraphs[0].deep_link_url.endswith("t=60")
    assert calls == [
        ("/companies", {"query": "MSFT"}),
        ("/companies/company-msft/events", {"type": "earnings", "limit": 1}),
        ("/events/event-msft-q3-fy26/transcript", None),
    ]

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT ticker, source, document_id, fiscal_label, payload
            FROM transcript_cache
            """
        ).fetchone()

    assert row is not None
    assert row["ticker"] == "MSFT"
    assert row["source"] == "quartr"
    assert row["document_id"] == "msft-q3-fy26-live"
    assert row["fiscal_label"] == "Q3 FY2026"
    assert TranscriptDocument.model_validate_json(row["payload"]) == doc
