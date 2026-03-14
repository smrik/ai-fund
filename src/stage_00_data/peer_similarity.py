"""Cached local-embedding peer similarity for CIQ comps weighting."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH
from db.loader import upsert_company_embedding, upsert_peer_similarity_cache
from db.schema import create_tables
from src.stage_00_data import company_descriptions

_MODEL_CACHE: dict[str, object] = {}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _encode_texts(texts: list[str], model_name: str) -> list[list[float]]:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "sentence-transformers is required for peer similarity; install requirements first"
        ) from exc

    model = _MODEL_CACHE.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model
    embeddings = model.encode(texts, convert_to_numpy=False, normalize_embeddings=False)
    return [[float(v) for v in vector] for vector in embeddings]


def _load_cached_embedding(
    conn: sqlite3.Connection,
    ticker: str,
    text_hash: str,
    model: str,
) -> list[float] | None:
    row = conn.execute(
        """
        SELECT embedding_blob
        FROM company_embeddings
        WHERE ticker = ? AND text_type = 'business_description' AND text_hash = ? AND embedding_model = ?
        LIMIT 1
        """,
        [ticker.upper(), text_hash, model],
    ).fetchone()
    if row is None:
        return None
    return [float(v) for v in json.loads(row["embedding_blob"])]


def get_or_create_embedding(ticker: str, text: str, text_hash: str, model: str) -> list[float]:
    """Load cached embedding or compute/store it using the local model."""
    conn = _connect()
    try:
        cached = _load_cached_embedding(conn, ticker, text_hash, model)
        if cached is not None:
            return cached
        embedding = _encode_texts([text], model)[0]
        upsert_company_embedding(
            conn,
            {
                "ticker": ticker.upper(),
                "text_type": "business_description",
                "text_hash": text_hash,
                "embedding_model": model,
                "embedding_dim": len(embedding),
                "embedding_blob": json.dumps(embedding, separators=(",", ":")),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        return embedding
    finally:
        conn.close()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _normalise_similarity(score: float) -> float:
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _load_cached_similarity(
    conn: sqlite3.Connection,
    target_ticker: str,
    peer_ticker: str,
    text_hash_target: str,
    text_hash_peer: str,
    embedding_model: str,
) -> float | None:
    row = conn.execute(
        """
        SELECT similarity_score
        FROM peer_similarity_cache
        WHERE target_ticker = ? AND peer_ticker = ?
          AND text_hash_target = ? AND text_hash_peer = ? AND embedding_model = ?
        LIMIT 1
        """,
        [
            target_ticker.upper(),
            peer_ticker.upper(),
            text_hash_target,
            text_hash_peer,
            embedding_model,
        ],
    ).fetchone()
    if row is None:
        return None
    return float(row["similarity_score"])


def score_peer_similarity(
    target_ticker: str,
    peers: list[dict],
    embedding_model: str,
) -> dict[str, float]:
    """Return {peer_ticker: similarity_score_0_to_1} using cached business-description embeddings."""
    target = company_descriptions.get_business_description(target_ticker)
    if not target:
        return {}

    target_embedding = get_or_create_embedding(
        target_ticker.upper(),
        target["text"],
        target["text_hash"],
        embedding_model,
    )

    conn = _connect()
    try:
        scores: dict[str, float] = {}
        for peer in peers:
            peer_ticker = str(peer.get("ticker") or "").upper()
            if not peer_ticker:
                continue
            peer_desc = company_descriptions.get_business_description(peer_ticker)
            if not peer_desc:
                continue

            cached = _load_cached_similarity(
                conn,
                target_ticker,
                peer_ticker,
                target["text_hash"],
                peer_desc["text_hash"],
                embedding_model,
            )
            if cached is not None:
                scores[peer_ticker] = cached
                continue

            peer_embedding = get_or_create_embedding(
                peer_ticker,
                peer_desc["text"],
                peer_desc["text_hash"],
                embedding_model,
            )
            similarity = _normalise_similarity(_cosine_similarity(target_embedding, peer_embedding))
            scores[peer_ticker] = similarity
            upsert_peer_similarity_cache(
                conn,
                {
                    "target_ticker": target_ticker.upper(),
                    "peer_ticker": peer_ticker,
                    "text_hash_target": target["text_hash"],
                    "text_hash_peer": peer_desc["text_hash"],
                    "embedding_model": embedding_model,
                    "similarity_score": similarity,
                    "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            )
        return scores
    finally:
        conn.close()
