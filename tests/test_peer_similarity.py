import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.schema import create_tables
from src.stage_00_data import peer_similarity


def _init_temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "alpha_pod.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.close()
    return db_path


def test_get_or_create_embedding_reuses_cached_vector(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(peer_similarity, "DB_PATH", db_path)

    calls = {"count": 0}

    def _fake_encode(texts, model_name):
        calls["count"] += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(peer_similarity, "_encode_texts", _fake_encode)

    first = peer_similarity.get_or_create_embedding(
        ticker="IBM",
        text="IBM provides hybrid cloud software.",
        text_hash="hash-1",
        model="all-MiniLM-L6-v2",
    )
    second = peer_similarity.get_or_create_embedding(
        ticker="IBM",
        text="IBM provides hybrid cloud software.",
        text_hash="hash-1",
        model="all-MiniLM-L6-v2",
    )

    assert first == pytest.approx([0.1, 0.2, 0.3])
    assert second == pytest.approx(first)
    assert calls["count"] == 1


def test_get_or_create_embedding_refreshes_when_text_hash_changes(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(peer_similarity, "DB_PATH", db_path)

    calls = {"count": 0}

    def _fake_encode(texts, model_name):
        calls["count"] += 1
        return [[float(calls["count"]), 0.0] for _ in texts]

    monkeypatch.setattr(peer_similarity, "_encode_texts", _fake_encode)

    first = peer_similarity.get_or_create_embedding("IBM", "old text", "hash-1", "all-MiniLM-L6-v2")
    second = peer_similarity.get_or_create_embedding("IBM", "new text", "hash-2", "all-MiniLM-L6-v2")

    assert first != second
    assert calls["count"] == 2


def test_score_peer_similarity_normalizes_and_reuses_cache(monkeypatch, tmp_path):
    db_path = _init_temp_db(tmp_path)
    monkeypatch.setattr(peer_similarity, "DB_PATH", db_path)

    descriptions = {
        "IBM": {
            "ticker": "IBM",
            "text": "Hybrid cloud software and consulting.",
            "source": "yfinance_longBusinessSummary",
            "text_hash": "ibm-hash",
            "as_of_date": "2026-03-14",
        },
        "ACN": {
            "ticker": "ACN",
            "text": "Global consulting and cloud services.",
            "source": "yfinance_longBusinessSummary",
            "text_hash": "acn-hash",
            "as_of_date": "2026-03-14",
        },
        "XOM": {
            "ticker": "XOM",
            "text": "Integrated oil and gas exploration.",
            "source": "yfinance_longBusinessSummary",
            "text_hash": "xom-hash",
            "as_of_date": "2026-03-14",
        },
    }

    monkeypatch.setattr(
        peer_similarity.company_descriptions,
        "get_business_description",
        lambda ticker: descriptions.get(ticker.upper()),
    )

    calls = {"count": 0}

    def _fake_encode(texts, model_name):
        calls["count"] += len(texts)
        vectors = []
        for text in texts:
            if "consulting" in text.lower():
                vectors.append([1.0, 0.0, 0.0])
            elif "oil" in text.lower():
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors

    monkeypatch.setattr(peer_similarity, "_encode_texts", _fake_encode)

    peers = [{"ticker": "ACN"}, {"ticker": "XOM"}]
    first = peer_similarity.score_peer_similarity("IBM", peers, "all-MiniLM-L6-v2")
    second = peer_similarity.score_peer_similarity("IBM", peers, "all-MiniLM-L6-v2")

    assert 0.0 <= first["ACN"] <= 1.0
    assert 0.0 <= first["XOM"] <= 1.0
    assert first["ACN"] > first["XOM"]
    assert second == pytest.approx(first)
    assert calls["count"] == 3
