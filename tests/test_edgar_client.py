import sys
from pathlib import Path
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
from src.stage_00_data import edgar_client


def test_strip_html_tags_removes_ix_noise_and_decodes_entities():
    raw = """
    <html>
      <head>
        <style>.hide { display:none; }</style>
        <script>console.log("ignore");</script>
      </head>
      <body>
        <ix:header>
          <xbrli:context>metadata only</xbrli:context>
        </ix:header>
        <div>Revenue increased 12% &amp; margins improved&nbsp;meaningfully.</div>
        <p>Operating income reached &#160; $500 million.</p>
      </body>
    </html>
    """

    cleaned = edgar_client._strip_html_tags(raw)

    assert "metadata only" not in cleaned
    assert "console.log" not in cleaned
    assert "display:none" not in cleaned
    assert "Revenue increased 12% & margins improved meaningfully." in cleaned
    assert "Operating income reached $500 million." in cleaned
    assert "<div>" not in cleaned
    assert "  " not in cleaned


def test_get_10k_text_cleans_markup_before_truncation(monkeypatch):
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000123456")
    monkeypatch.setattr(
        edgar_client,
        "get_recent_filings",
        lambda cik, form_type, limit=4: [
            {
                "accession_no": "0000123456-26-000001",
                "filing_date": "2026-02-20",
                "primary_doc": "annual.htm",
            }
        ],
    )
    monkeypatch.setattr(
        edgar_client,
        "get_filing_text",
        lambda accession_no, cik, doc_name: (
            "<html><ix:header>" + ("X" * 2000) + "</ix:header>"
            "<body><p>Management discussion and analysis starts here.</p></body></html>"
        ),
    )

    text = edgar_client.get_10k_text("IBM", max_chars=30)

    assert text == "Management discussion and anal"


def test_get_8k_texts_cleans_each_markup_document(monkeypatch):
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000123456")
    monkeypatch.setattr(
        edgar_client,
        "get_recent_filings",
        lambda cik, form_type, limit=4: [
            {
                "accession_no": "0000123456-26-000010",
                "filing_date": "2026-03-01",
                "primary_doc": "earnings1.htm",
            },
            {
                "accession_no": "0000123456-26-000011",
                "filing_date": "2026-02-01",
                "primary_doc": "earnings2.htm",
            },
        ],
    )

    def fake_text(accession_no, cik, doc_name):
        return (
            "<html><body><script>ignore()</script>"
            f"<p>{doc_name} says guidance was raised &amp; cash flow improved.</p>"
            "</body></html>"
        )

    monkeypatch.setattr(edgar_client, "get_filing_text", fake_text)

    filings = edgar_client.get_8k_texts("IBM", limit=2, max_chars_each=80)

    assert len(filings) == 2
    assert filings[0]["text"] == "earnings1.htm says guidance was raised & cash flow improved."
    assert filings[1]["text"] == "earnings2.htm says guidance was raised & cash flow improved."


def test_get_recent_10q_texts_returns_cleaned_quarterly_text(monkeypatch):
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000123456")
    monkeypatch.setattr(
        edgar_client,
        "get_recent_filings",
        lambda cik, form_type, limit=2: [
            {
                "accession_no": "0000123456-26-000002",
                "filing_date": "2026-06-30",
                "primary_doc": "q2.htm",
            },
            {
                "accession_no": "0000123456-26-000003",
                "filing_date": "2026-03-31",
                "primary_doc": "q1.htm",
            },
        ],
    )
    monkeypatch.setattr(
        edgar_client,
        "_get_cached_or_fetch_filing_text",
        lambda **kwargs: f"{kwargs['doc_name']} discusses deferred revenue and restructuring.",
    )

    results = edgar_client.get_recent_10q_texts("IBM", limit=2, max_chars_each=200)

    assert [item["accession_no"] for item in results] == ["0000123456-26-000002", "0000123456-26-000003"]
    assert "deferred revenue and restructuring" in results[0]["text"]


def test_get_10k_text_uses_cached_clean_text_before_refetch(monkeypatch, tmp_path):
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()

    monkeypatch.setattr(edgar_client, "DB_PATH", db_path)
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_CLEAN_DIR", tmp_path / "clean")
    monkeypatch.setattr(edgar_client, "EDGAR_PARSER_VERSION", "v1")
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000123456")
    monkeypatch.setattr(
        edgar_client,
        "get_recent_filings",
        lambda cik, form_type, limit=4: [
            {
                "accession_no": "0000123456-26-000001",
                "filing_date": "2026-02-20",
                "primary_doc": "annual.htm",
            }
        ],
    )

    calls = {"count": 0}

    def _fake_fetch(accession_no, cik, doc_name):
        calls["count"] += 1
        return "<html><body><p>Cached management discussion text.</p></body></html>"

    monkeypatch.setattr(edgar_client, "get_filing_text", _fake_fetch)

    first = edgar_client.get_10k_text("IBM", max_chars=200)
    second = edgar_client.get_10k_text("IBM", max_chars=200)

    assert first == "Cached management discussion text."
    assert second == "Cached management discussion text."
    assert calls["count"] == 1


def test_get_10k_text_reparses_raw_cache_when_parser_version_changes(monkeypatch, tmp_path):
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()

    monkeypatch.setattr(edgar_client, "DB_PATH", db_path)
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(edgar_client, "EDGAR_CACHE_CLEAN_DIR", tmp_path / "clean")
    monkeypatch.setattr(edgar_client, "get_cik", lambda ticker: "0000123456")
    monkeypatch.setattr(
        edgar_client,
        "get_recent_filings",
        lambda cik, form_type, limit=4: [
            {
                "accession_no": "0000123456-26-000001",
                "filing_date": "2026-02-20",
                "primary_doc": "annual.htm",
            }
        ],
    )

    monkeypatch.setattr(
        edgar_client,
        "get_filing_text",
        lambda accession_no, cik, doc_name: "<html><body><p>Parser version rollover text.</p></body></html>",
    )
    monkeypatch.setattr(edgar_client, "EDGAR_PARSER_VERSION", "v1")
    first = edgar_client.get_10k_text("IBM", max_chars=200)

    monkeypatch.setattr(edgar_client, "EDGAR_PARSER_VERSION", "v2")
    monkeypatch.setattr(
        edgar_client,
        "get_filing_text",
        lambda accession_no, cik, doc_name: (_ for _ in ()).throw(AssertionError("should not refetch")),
    )
    second = edgar_client.get_10k_text("IBM", max_chars=200)

    assert first == "Parser version rollover text."
    assert second == "Parser version rollover text."
