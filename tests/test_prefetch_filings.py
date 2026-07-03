from __future__ import annotations

import sqlite3

from db.schema import create_tables
import src.stage_00_data.edgar_prefetch as prefetch


def _init_db(path):
    conn = sqlite3.connect(path)
    create_tables(conn)
    conn.close()


def test_prefetch_filings_fetches_text_and_writes_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    clean_dir = tmp_path / "edgar_clean"
    _init_db(db_path)
    monkeypatch.setattr(prefetch, "DB_PATH", db_path)
    monkeypatch.setattr(prefetch, "EDGAR_CACHE_CLEAN_DIR", clean_dir)
    monkeypatch.setattr(prefetch.edgar_client, "get_cik", lambda ticker: "0000789019")
    monkeypatch.setattr(
        prefetch.edgar_client,
        "get_recent_filing_metadata",
        lambda ticker, form_type, limit=4: [
            {
                "accession_no": "0000789019-26-000001",
                "filing_date": "2026-04-30",
                "primary_doc": "msft-20260430.htm",
            }
        ],
    )
    monkeypatch.setattr(
        prefetch.edgar_client,
        "get_filing_text_by_accession",
        lambda ticker, accession_no: "Item 1. Business\nMicrosoft filing text.",
    )

    result = prefetch.prefetch_filings("msft", forms=["10-Q"], limit=1)

    assert result.errors == []
    assert result.cached_count == 1
    assert result.rows[0].cache_status == "miss"
    assert result.rows[0].cached_chars == len("Item 1. Business\nMicrosoft filing text.")
    clean_files = list(clean_dir.rglob("*.txt"))
    assert len(clean_files) == 1
    assert clean_files[0].read_text(encoding="utf-8") == "Item 1. Business\nMicrosoft filing text."

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT ticker, cik, form_type, accession_no, clean_path, clean_text_hash
            FROM edgar_filing_cache
            WHERE ticker = 'MSFT'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == "MSFT"
    assert row[1] == "0000789019"
    assert row[2] == "10-Q"
    assert row[3] == "0000789019-26-000001"
    assert row[4].endswith(".txt")
    assert row[5]


def test_prefetch_filings_reuses_existing_cache(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    clean_dir = tmp_path / "edgar_clean"
    clean_path = clean_dir / "MSFT" / "10-K" / "cached.txt"
    clean_path.parent.mkdir(parents=True)
    clean_path.write_text("cached filing text", encoding="utf-8")
    _init_db(db_path)
    monkeypatch.setattr(prefetch, "DB_PATH", db_path)
    monkeypatch.setattr(prefetch, "EDGAR_CACHE_CLEAN_DIR", clean_dir)
    monkeypatch.setattr(prefetch.edgar_client, "get_cik", lambda ticker: "0000789019")
    monkeypatch.setattr(
        prefetch.edgar_client,
        "get_recent_filing_metadata",
        lambda ticker, form_type, limit=4: [
            {
                "accession_no": "0000789019-25-000010",
                "filing_date": "2025-07-31",
                "primary_doc": "msft-10k.htm",
            }
        ],
    )
    called = {"text": False}

    def _unexpected_fetch(ticker, accession_no):
        called["text"] = True
        return "fresh text"

    monkeypatch.setattr(prefetch.edgar_client, "get_filing_text_by_accession", _unexpected_fetch)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO edgar_filing_cache (
                ticker, cik, form_type, accession_no, filing_date, doc_name,
                source_url, raw_path, clean_path, raw_text_hash, clean_text_hash,
                parser_version, fetched_at, cleaned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "MSFT",
                "0000789019",
                "10-K",
                "0000789019-25-000010",
                "2025-07-31",
                "msft-10k.htm",
                "https://sec.example/msft",
                None,
                str(clean_path),
                "hash",
                "hash",
                "v1",
                "2026-06-13T00:00:00+00:00",
                "2026-06-13T00:00:00+00:00",
            ),
        )
        conn.commit()

    result = prefetch.prefetch_filings("MSFT", forms=["10-K"], limit=1)

    assert result.cached_count == 1
    assert result.rows[0].cache_status == "hit"
    assert result.rows[0].cached_chars == len("cached filing text")
    assert called["text"] is False


def test_summary_only_reports_cache_without_fetching(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "alpha_pod.db"
    clean_path = tmp_path / "cached.txt"
    clean_path.write_text("12345", encoding="utf-8")
    _init_db(db_path)
    monkeypatch.setattr(prefetch, "DB_PATH", db_path)
    monkeypatch.setattr(
        prefetch.edgar_client,
        "get_cik",
        lambda ticker: (_ for _ in ()).throw(AssertionError("summary should not fetch")),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO edgar_filing_cache (
                ticker, cik, form_type, accession_no, filing_date, doc_name,
                source_url, raw_path, clean_path, raw_text_hash, clean_text_hash,
                parser_version, fetched_at, cleaned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "MSFT",
                "0000789019",
                "8-K",
                "0000789019-26-000099",
                "2026-06-01",
                "msft-8k.htm",
                "https://sec.example/msft",
                None,
                str(clean_path),
                "hash",
                "hash",
                "v1",
                "2026-06-13T00:00:00+00:00",
                "2026-06-13T00:00:00+00:00",
            ),
        )
        conn.commit()

    from scripts.manual.prefetch_filings import main

    exit_code = main(["--ticker", "MSFT", "--forms", "8-K", "--summary-only"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "0000789019-26-000099" in output
    assert "cached" in output.lower()


def test_summary_only_marks_missing_cache_file(tmp_path, monkeypatch):
    db_path = tmp_path / "alpha_pod.db"
    missing_path = tmp_path / "missing.txt"
    _init_db(db_path)
    monkeypatch.setattr(prefetch, "DB_PATH", db_path)
    monkeypatch.setattr(
        prefetch.edgar_client,
        "get_cik",
        lambda ticker: (_ for _ in ()).throw(AssertionError("summary should not fetch")),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO edgar_filing_cache (
                ticker, cik, form_type, accession_no, filing_date, doc_name,
                source_url, raw_path, clean_path, raw_text_hash, clean_text_hash,
                parser_version, fetched_at, cleaned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "MSFT",
                "0000789019",
                "10-Q",
                "0000789019-26-000088",
                "2026-05-01",
                "msft-10q.htm",
                "https://sec.example/msft",
                None,
                str(missing_path),
                "hash",
                "hash",
                "v1",
                "2026-06-13T00:00:00+00:00",
                "2026-06-13T00:00:00+00:00",
            ),
        )
        conn.commit()

    result = prefetch.prefetch_filings("MSFT", forms=["10-Q"], limit=1, summary_only=True)

    assert result.cached_count == 0
    assert result.rows[0].cache_status == "missing"
    assert result.rows[0].cached_chars == 0


def test_prefetch_returns_actionable_error_when_cik_lookup_fails(monkeypatch):
    monkeypatch.setattr(prefetch.edgar_client, "get_cik", lambda ticker: (_ for _ in ()).throw(RuntimeError("network down")))

    result = prefetch.prefetch_filings("MSFT", forms=["10-K"], limit=1)

    assert result.cached_count == 0
    assert result.errors == ["CIK lookup failed for MSFT: network down"]
