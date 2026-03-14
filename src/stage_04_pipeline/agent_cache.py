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


def _parsed_output_from_serialized(serialized: dict[str, Any]) -> Any:
    return json.loads(serialized["output_payload"])


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
    ) -> int:
        with self._connection_factory() as conn:
            create_tables(conn)
            cursor = conn.execute(
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
            return int(cursor.lastrowid)

    def _insert_artifact(
        self,
        *,
        run_log_id: int,
        ticker: str,
        agent_name: str,
        artifact_source: str,
        artifact: dict[str, Any] | None,
    ) -> None:
        artifact = artifact or {}
        with self._connection_factory() as conn:
            create_tables(conn)
            conn.execute(
                """
                INSERT INTO agent_run_artifacts (
                    run_log_id, ticker, agent_name, artifact_source,
                    system_prompt, user_prompt, tool_schema_json, api_trace_json,
                    raw_final_output, parsed_output_json,
                    prompt_tokens, completion_tokens, total_tokens, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_log_id,
                    ticker,
                    agent_name,
                    artifact_source,
                    artifact.get("system_prompt"),
                    artifact.get("user_prompt"),
                    json.dumps(_normalize(artifact.get("tool_schema")), default=str),
                    json.dumps(_normalize(artifact.get("api_trace")), default=str),
                    artifact.get("raw_final_output"),
                    json.dumps(_normalize(artifact.get("parsed_output")), default=str),
                    artifact.get("prompt_tokens"),
                    artifact.get("completion_tokens"),
                    artifact.get("total_tokens"),
                    _now(),
                ],
            )
            conn.commit()

    def _load_cached_artifact(
        self,
        *,
        ticker: str,
        agent_name: str,
        input_hash: str,
        model: str,
        prompt_hash: str,
    ) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            create_tables(conn)
            row = conn.execute(
                """
                SELECT a.system_prompt, a.user_prompt, a.tool_schema_json, a.api_trace_json,
                       a.raw_final_output, a.parsed_output_json,
                       a.prompt_tokens, a.completion_tokens, a.total_tokens
                FROM agent_run_artifacts a
                JOIN agent_run_log l ON l.id = a.run_log_id
                WHERE l.ticker = ? AND l.agent_name = ? AND l.input_hash = ? AND l.model = ? AND l.prompt_hash = ?
                ORDER BY a.id DESC
                LIMIT 1
                """,
                [ticker, agent_name, input_hash, model, prompt_hash],
            ).fetchone()
        if row is None:
            return None
        return {
            "system_prompt": row["system_prompt"],
            "user_prompt": row["user_prompt"],
            "tool_schema": json.loads(row["tool_schema_json"]) if row["tool_schema_json"] else None,
            "api_trace": json.loads(row["api_trace_json"]) if row["api_trace_json"] else [],
            "raw_final_output": row["raw_final_output"],
            "parsed_output": json.loads(row["parsed_output_json"]) if row["parsed_output_json"] else None,
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "total_tokens": row["total_tokens"],
        }

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
                run_log_id = self._insert_log(
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
                self._insert_artifact(
                    run_log_id=run_log_id,
                    ticker=ticker,
                    agent_name=agent_name,
                    artifact_source="cache_reused",
                    artifact=self._load_cached_artifact(
                        ticker=ticker,
                        agent_name=agent_name,
                        input_hash=input_hash,
                        model=model,
                        prompt_hash=prompt_hash,
                    ),
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
            run_log_id = self._insert_log(
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
            artifact_payload = dict(getattr(agent, "last_run_artifact", None) or {})
            artifact_payload["parsed_output"] = _parsed_output_from_serialized(serialized)
            self._insert_artifact(
                run_log_id=run_log_id,
                ticker=ticker,
                agent_name=agent_name,
                artifact_source="executed",
                artifact=artifact_payload,
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
            run_log_id = self._insert_log(
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
            self._insert_artifact(
                run_log_id=run_log_id,
                ticker=ticker,
                agent_name=agent_name,
                artifact_source="executed",
                artifact=getattr(agent, "last_run_artifact", None),
            )
            raise


def load_agent_run_history(ticker: str, limit: int = 100) -> list[dict[str, Any]]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT id, run_ts, agent_name, status, cache_hit, forced_refresh, duration_ms,
                   model, prompt_version, prompt_hash, error
            FROM agent_run_log
            WHERE ticker = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            [ticker, limit],
        ).fetchall()
    return [dict(row) for row in rows]


def load_agent_run_artifact(
    run_log_id: int,
    *,
    connection_factory: Callable[[], Any] | None = None,
) -> dict[str, Any] | None:
    connection_factory = connection_factory or get_connection
    with connection_factory() as conn:
        create_tables(conn)
        row = conn.execute(
            """
            SELECT run_log_id, ticker, agent_name, artifact_source,
                   system_prompt, user_prompt, tool_schema_json, api_trace_json,
                   raw_final_output, parsed_output_json,
                   prompt_tokens, completion_tokens, total_tokens, created_at
            FROM agent_run_artifacts
            WHERE run_log_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            [run_log_id],
        ).fetchone()
    if row is None:
        return None
    return {
        "run_log_id": row["run_log_id"],
        "ticker": row["ticker"],
        "agent_name": row["agent_name"],
        "artifact_source": row["artifact_source"],
        "system_prompt": row["system_prompt"],
        "user_prompt": row["user_prompt"],
        "tool_schema_json": json.loads(row["tool_schema_json"]) if row["tool_schema_json"] else None,
        "api_trace_json": json.loads(row["api_trace_json"]) if row["api_trace_json"] else [],
        "raw_final_output": row["raw_final_output"],
        "parsed_output_json": json.loads(row["parsed_output_json"]) if row["parsed_output_json"] else None,
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "created_at": row["created_at"],
    }


def artifact_has_meaningful_io(artifact: dict[str, Any] | None, agent_name: str) -> bool:
    if artifact is None:
        return False
    if agent_name == "ValuationAgent":
        return True
    return any(
        [
            artifact.get("system_prompt"),
            artifact.get("user_prompt"),
            artifact.get("tool_schema_json"),
            artifact.get("api_trace_json"),
            artifact.get("raw_final_output"),
        ]
    )


def load_latest_agent_artifacts_by_ticker(ticker: str, limit: int = 50) -> list[dict[str, Any]]:
    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT l.id AS run_log_id, l.run_ts, l.agent_name, l.status, l.cache_hit, l.forced_refresh,
                   l.duration_ms, l.model, l.prompt_version, l.prompt_hash, l.error,
                   a.artifact_source, a.prompt_tokens, a.completion_tokens, a.total_tokens
            FROM agent_run_log l
            LEFT JOIN agent_run_artifacts a ON a.run_log_id = l.id
            WHERE l.ticker = ?
            ORDER BY l.id DESC
            LIMIT ?
            """,
            [ticker, limit],
        ).fetchall()
    return [dict(row) for row in rows]
