from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import time
from typing import Any, Callable

from pydantic import BaseModel

from db.schema import create_tables, get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, set):
        return sorted(_normalize(v) for v in value)
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _serialize_output(output: Any) -> dict[str, Any]:
    if isinstance(output, BaseModel):
        payload = output.model_dump(mode="python")
        return {
            "output_format": "pydantic",
            "output_module": output.__class__.__module__,
            "output_class": output.__class__.__name__,
            "output_payload": json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
            "output_hash": _hash_payload(payload),
        }
    payload = _normalize(output)
    return {
        "output_format": "json",
        "output_module": None,
        "output_class": None,
        "output_payload": json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
        "output_hash": _hash_payload(payload),
    }


def _deserialize_output(row: Any) -> Any:
    payload = json.loads(row["output_payload"])
    if row["output_format"] == "pydantic" and row["output_module"] and row["output_class"]:
        module = importlib.import_module(row["output_module"])
        cls = getattr(module, row["output_class"])
        if hasattr(cls, "model_validate"):
            return cls.model_validate(payload)
        return cls(**payload)
    return payload


class AgentRunCache:
    def __init__(self, connection_factory: Callable[[], Any] | None = None):
        self._connection_factory = connection_factory or get_connection

    @staticmethod
    def _model_name(agent: Any) -> str:
        return str(getattr(agent, "model", "") or "")

    @staticmethod
    def _prompt_version(agent: Any) -> str:
        return str(getattr(agent, "prompt_version", "v1") or "v1")

    @staticmethod
    def _prompt_hash(agent: Any) -> str:
        prompt = str(getattr(agent, "system_prompt", "") or "")
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _fetch_cache(self, *, ticker: str, agent_name: str, input_hash: str, model: str, prompt_hash: str):
        with self._connection_factory() as conn:
            create_tables(conn)
            return conn.execute(
                """
                SELECT output_format, output_module, output_class, output_payload, output_hash, created_at
                FROM agent_run_cache
                WHERE ticker = ? AND agent_name = ? AND input_hash = ? AND model = ? AND prompt_hash = ?
                """,
                [ticker, agent_name, input_hash, model, prompt_hash],
            ).fetchone()

    def _upsert_cache(
        self,
        *,
        ticker: str,
        agent_name: str,
        input_hash: str,
        model: str,
        prompt_version: str,
        prompt_hash: str,
        serialized: dict[str, Any],
    ) -> None:
        with self._connection_factory() as conn:
            create_tables(conn)
            conn.execute(
                """
                INSERT INTO agent_run_cache (
                    ticker, agent_name, input_hash, model, prompt_hash,
                    output_format, output_module, output_class, output_payload,
                    output_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, agent_name, input_hash, model, prompt_hash) DO UPDATE SET
                    output_format = excluded.output_format,
                    output_module = excluded.output_module,
                    output_class = excluded.output_class,
                    output_payload = excluded.output_payload,
                    output_hash = excluded.output_hash,
                    created_at = excluded.created_at
                """,
                [
                    ticker,
                    agent_name,
                    input_hash,
                    model,
                    prompt_hash,
                    serialized["output_format"],
                    serialized["output_module"],
                    serialized["output_class"],
                    serialized["output_payload"],
                    serialized["output_hash"],
                    _now(),
                ],
            )
            conn.commit()

    def _insert_log(
        self,
        *,
        ticker: str,
        agent_name: str,
        input_hash: str,
        model: str,
        prompt_version: str,
        prompt_hash: str,
        cache_hit: bool,
        forced_refresh: bool,
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        output_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._connection_factory() as conn:
            create_tables(conn)
            conn.execute(
                """
                INSERT INTO agent_run_log (
                    run_ts, ticker, agent_name, status, cache_hit, forced_refresh,
                    input_hash, output_hash, model, prompt_version, prompt_hash,
                    started_at, finished_at, duration_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    _now(),
                    ticker,
                    agent_name,
                    status,
                    int(cache_hit),
                    int(forced_refresh),
                    input_hash,
                    output_hash,
                    model,
                    prompt_version,
                    prompt_hash,
                    started_at,
                    finished_at,
                    duration_ms,
                    error,
                ],
            )
            conn.commit()

    def run_cached(
        self,
        *,
        ticker: str,
        agent_name: str,
        agent: Any,
        input_payload: Any,
        runner: Callable[[], Any],
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> tuple[Any, dict[str, Any]]:
        ticker = ticker.upper().strip()
        model = self._model_name(agent)
        prompt_version = self._prompt_version(agent)
        prompt_hash = self._prompt_hash(agent)
        input_hash = _hash_payload(input_payload)
        started = _now()
        started_perf = time.perf_counter()

        if use_cache and not force_refresh:
            row = self._fetch_cache(
                ticker=ticker,
                agent_name=agent_name,
                input_hash=input_hash,
                model=model,
                prompt_hash=prompt_hash,
            )
            if row is not None:
                finished = _now()
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                output = _deserialize_output(row)
                self._insert_log(
                    ticker=ticker,
                    agent_name=agent_name,
                    input_hash=input_hash,
                    model=model,
                    prompt_version=prompt_version,
                    prompt_hash=prompt_hash,
                    cache_hit=True,
                    forced_refresh=force_refresh,
                    status="cache_hit",
                    started_at=started,
                    finished_at=finished,
                    duration_ms=duration_ms,
                    output_hash=row["output_hash"],
                )
                return output, {
                    "cache_hit": True,
                    "forced_refresh": force_refresh,
                    "input_hash": input_hash,
                    "output_hash": row["output_hash"],
                    "duration_ms": duration_ms,
                }

        try:
            output = runner()
            serialized = _serialize_output(output)
            self._upsert_cache(
                ticker=ticker,
                agent_name=agent_name,
                input_hash=input_hash,
                model=model,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                serialized=serialized,
            )
            finished = _now()
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            self._insert_log(
                ticker=ticker,
                agent_name=agent_name,
                input_hash=input_hash,
                model=model,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                cache_hit=False,
                forced_refresh=force_refresh,
                status="executed",
                started_at=started,
                finished_at=finished,
                duration_ms=duration_ms,
                output_hash=serialized["output_hash"],
            )
            return output, {
                "cache_hit": False,
                "forced_refresh": force_refresh,
                "input_hash": input_hash,
                "output_hash": serialized["output_hash"],
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            finished = _now()
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            self._insert_log(
                ticker=ticker,
                agent_name=agent_name,
                input_hash=input_hash,
                model=model,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                cache_hit=False,
                forced_refresh=force_refresh,
                status="error",
                started_at=started,
                finished_at=finished,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise


def load_agent_run_history(ticker: str, limit: int = 100) -> list[dict[str, Any]]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT run_ts, agent_name, status, cache_hit, forced_refresh, duration_ms,
                   model, prompt_version, prompt_hash, error
            FROM agent_run_log
            WHERE ticker = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            [ticker, limit],
        ).fetchall()
    return [dict(row) for row in rows]
