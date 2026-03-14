import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
from src.stage_00_data import company_descriptions


def _init_temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()
    return db_path


def test_get_business_description_prefers_yfinance_and_reuses_cache(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(company_descriptions, "DB_PATH", db_path)

    calls = {"count": 0}

    def _fake_yf(ticker: str):
        calls["count"] += 1
        return {
            "text": "IBM provides hybrid cloud software and IT consulting services.",
            "source": "yfinance_longBusinessSummary",
            "as_of_date": "2026-03-14",
        }

    monkeypatch.setattr(company_descriptions, "_fetch_yfinance_business_description", _fake_yf)
    monkeypatch.setattr(company_descriptions, "_extract_edgar_item1_business", lambda ticker: None)

    first = company_descriptions.get_business_description("IBM")
    second = company_descriptions.get_business_description("IBM")

    assert first is not None and second is not None
    assert first["source"] == "yfinance_longBusinessSummary"
    assert second["text"] == first["text"]
    assert calls["count"] == 1


def test_get_business_description_falls_back_to_edgar_item1(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(company_descriptions, "DB_PATH", db_path)
    monkeypatch.setattr(company_descriptions, "_fetch_yfinance_business_description", lambda ticker: None)
    monkeypatch.setattr(
        company_descriptions,
        "_extract_edgar_item1_business",
        lambda ticker: {
            "text": "Item 1. Business IBM designs software, infrastructure, and consulting solutions.",
            "source": "edgar_item1_business",
            "as_of_date": "2025-12-31",
        },
    )

    out = company_descriptions.get_business_description("IBM")

    assert out is not None
    assert out["source"] == "edgar_item1_business"
    assert "consulting solutions" in out["text"]
