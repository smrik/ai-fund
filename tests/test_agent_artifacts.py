from __future__ import annotations

import sqlite3
from pathlib import Path

from db.schema import create_tables
from src.stage_04_pipeline.agent_cache import (
    AgentRunCache,
    artifact_has_meaningful_io,
    load_agent_run_artifact,
)


class _StubArtifactAgent:
    name = "ArtifactAgent"
    model = "stub-model"
    system_prompt = "system prompt"
    prompt_version = "v-test"
    tools = [{"type": "function", "function": {"name": "dummy", "parameters": {"type": "object", "properties": {}}}}]

    def __init__(self):
        self.last_run_artifact = {
            "system_prompt": self.system_prompt,
            "user_prompt": "user prompt",
            "tool_schema": self.tools,
            "api_trace": [{"step": 1, "finish_reason": "stop"}],
            "raw_final_output": "raw text",
            "parsed_output": {"ok": True},
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_agent_run_cache_persists_artifacts_and_reuses_on_cache_hit(tmp_path):
    db_path = tmp_path / "artifact_cache.db"
    cache = AgentRunCache(connection_factory=_temp_conn_factory(db_path))
    agent = _StubArtifactAgent()

    counter = {"runs": 0}

    def _runner():
        counter["runs"] += 1
        return {"answer": 42}

    output1, meta1 = cache.run_cached(
        ticker="IBM",
        agent_name="ArtifactAgent",
        agent=agent,
        input_payload={"ticker": "IBM"},
        runner=_runner,
        use_cache=True,
        force_refresh=False,
    )
    assert output1 == {"answer": 42}
    assert meta1["cache_hit"] is False

    output2, meta2 = cache.run_cached(
        ticker="IBM",
        agent_name="ArtifactAgent",
        agent=agent,
        input_payload={"ticker": "IBM"},
        runner=_runner,
        use_cache=True,
        force_refresh=False,
    )
    assert output2 == {"answer": 42}
    assert meta2["cache_hit"] is True
    assert counter["runs"] == 1

    with _temp_conn_factory(db_path)() as conn:
        rows = conn.execute("SELECT run_log_id, artifact_source FROM agent_run_artifacts ORDER BY id ASC").fetchall()
    assert len(rows) == 2
    assert rows[0]["artifact_source"] == "executed"
    assert rows[1]["artifact_source"] == "cache_reused"

    artifact = load_agent_run_artifact(rows[0]["run_log_id"], connection_factory=_temp_conn_factory(db_path))
    assert artifact["system_prompt"] == "system prompt"
    assert artifact["user_prompt"] == "user prompt"
    assert artifact["raw_final_output"] == "raw text"
    assert artifact["parsed_output_json"]["answer"] == 42
    assert artifact["tool_schema_json"][0]["function"]["name"] == "dummy"


def test_artifact_has_meaningful_io_detects_sparse_legacy_rows():
    sparse = {
        "system_prompt": None,
        "user_prompt": None,
        "tool_schema_json": None,
        "api_trace_json": [],
        "raw_final_output": None,
        "parsed_output_json": {"answer": 42},
    }
    full = {
        "system_prompt": "system",
        "user_prompt": "user",
        "tool_schema_json": [{"function": {"name": "dummy"}}],
        "api_trace_json": [{"step": 1}],
        "raw_final_output": "raw text",
        "parsed_output_json": {"answer": 42},
    }

    assert artifact_has_meaningful_io(sparse, "FilingsAgent") is False
    assert artifact_has_meaningful_io(full, "FilingsAgent") is True
    assert artifact_has_meaningful_io(sparse, "ValuationAgent") is True
