from __future__ import annotations

import json
import os
import threading
from contextlib import nullcontext
from pathlib import Path

from scripts.manual import pm_decision_queue
from scripts.manual import run_guided_ticker_workup as guided
from scripts.manual.run_ticker_valuation_flow import AGENT_MODEL_ENV_VARS


class ScriptedIO(guided.GuidedIO):
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []
        super().__init__(input_fn=self._input, output_fn=self.messages.append)

    def _input(self, prompt: str) -> str:
        self.messages.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return self.answers.pop(0)


def _queue_item(item_id: int = 11) -> dict:
    return {
        "item_id": item_id,
        "item_type": "assumption_change_pack",
        "status": "pending",
        "profile_name": "company_analysis",
        "title": "Growth target review",
        "summary": "Evidence supports reviewing near-term growth.",
        "metadata": {"pm_question": "Does the evidence support the model change?"},
        "proposal_pack": {
            "pack_id": "pack:1",
            "proposals": [
                {
                    "assumption_name": "revenue_growth_near",
                    "proposal_mode": "delta",
                    "proposed_delta": 0.01,
                }
            ],
        },
    }


def _advisory_item(item_id: int = 22) -> dict:
    return {
        "item_id": item_id,
        "item_type": "advisory_finding",
        "status": "pending",
        "profile_name": "risk_review",
        "title": "Risk needs PM review",
        "summary": "Risk evidence is relevant but does not propose a model edit.",
        "metadata": {"pm_question": "Is this already captured in scenarios?"},
        "proposal_pack": None,
    }


def _profile_payload(profile: str, item_id: int = 11) -> dict:
    return {
        "ticker": "MSFT",
        "profile_name": profile,
        "status": "completed",
        "reason": None,
        "observation_count": 1,
        "queue_item_count": 1,
        "queue_item_ids": [item_id],
        "evidence_packet": {
            "packet_id": 7,
            "facts": [{"fact_name": "filing_source_count", "value": 3}],
            "snippets": [{"snippet_id": "snippet:1", "text": "Real filing evidence."}],
            "source_refs": [{"source_ref_id": "filing:1"}],
            "observations": [
                {
                    "claim": "Evidence supports reviewing the growth bridge.",
                    "pm_question": "Should the current growth assumption change?",
                }
            ],
            "run_metadata": {"source_quality": "real"},
        },
    }


def _preview_payload(item_id: int = 11) -> dict:
    return {
        "ticker": "MSFT",
        "item_id": item_id,
        "item": {"item_id": item_id},
        "preview": {
            "current_iv": {"base": 100.0},
            "proposed_iv": {"base": 106.0},
            "delta_pct": {"base": 6.0},
            "resolved_values": {
                "revenue_growth_near": {"current_value": 0.07, "proposed_value": 0.08}
            },
        },
        "skipped_fields": [],
    }


def _deps(tmp_path: Path, *, calls: dict | None = None) -> guided.GuidedDependencies:
    calls = calls if calls is not None else {}

    def _record(name: str, payload=None):
        calls.setdefault(name, []).append(payload)

    def _model_row(ticker: str) -> dict:
        _record("value_single_ticker", ticker)
        return {
            "ticker": ticker,
            "price": 100.0,
            "iv_bear": 80.0,
            "iv_base": 120.0,
            "iv_bull": 150.0,
            "upside_base_pct": 20.0,
            "growth_near": 7.0,
            "growth_mid": 5.0,
            "ebit_margin_used": 30.0,
            "wacc": 8.5,
            "exit_multiple_used": 18.0,
        }

    return guided.GuidedDependencies(
        prepare_ciq_refresh=lambda **kwargs: _record("prepare_ciq", kwargs) or (tmp_path / "MSFT_Standard.xlsx"),
        resolve_ciq_symbol=lambda ticker, **kwargs: f"NASDAQ:{ticker}",
        ingest_ciq_folder=lambda folder: _record("ingest_ciq", folder) or {"processed": 1, "failed": 0},
        prefetch_filings=lambda ticker, **kwargs: _record("prefetch", kwargs)
        or {"ticker": ticker, "cached_count": 3, "rows": [], "errors": []},
        value_single_ticker=_model_row,
        build_summary=lambda ticker, **kwargs: {"ticker": ticker, "base_iv": 120.0},
        build_dcf=lambda ticker: {"ticker": ticker, "scenario_summary": []},
        build_comps=lambda ticker: {"ticker": ticker, "audit_flags": []},
        build_assumptions=lambda ticker: {"ticker": ticker, "fields": []},
        list_queue=lambda ticker, **kwargs: {"ticker": ticker, "items": [_queue_item()]},
        preview_queue_item=lambda ticker, item_id: _record("preview", item_id) or _preview_payload(item_id),
        edit_queue_item=lambda ticker, item_id, proposal_pack, actor="api": _record("edit", proposal_pack)
        or {"item": {**_queue_item(item_id), "pm_edited_proposal_pack": proposal_pack}, "status": "pending"},
        approve_queue_item=lambda ticker, item_id, actor="api": _record("approve", item_id)
        or {"item": {"item_id": item_id, "status": "approved"}, "status": "approved"},
        apply_queue_item=lambda ticker, item_id, actor="api": _record("apply", item_id)
        or {"item": {"item_id": item_id, "status": "approved"}, "status": "approved"},
        reject_queue_item=lambda ticker, item_id, actor="api", reason="": _record("reject", reason)
        or {"item": {"item_id": item_id, "status": "rejected"}, "status": "rejected"},
        defer_queue_item=lambda ticker, item_id, actor="api", reason="": _record("defer", reason)
        or {"item": {"item_id": item_id, "status": "deferred"}, "status": "deferred"},
        run_profile=lambda ticker, profile_name, **kwargs: _record("profile", profile_name)
        or _profile_payload(profile_name),
        build_prep_pack=lambda ticker: {"ticker": ticker, "thesis_cards": [], "driver_cards": []},
        render_prep_markdown=lambda payload: f"# Analyst Prep {payload['ticker']}",
        export_xlsx=lambda ticker: {"ticker": ticker, "artifacts": []},
        refresh_dossier=lambda ticker: {"ticker": ticker, "source_mode": "loaded_backend_state"},
        collect_freshness=lambda ticker: {
            "ticker": ticker,
            "db_path": str(tmp_path / "alpha_pod.db"),
            "market_cache_rows": [{"data_type": "market_data", "fetched_at": "2026-06-12"}],
            "edgar_filing_cache": {"filing_count": 3, "latest_filing_date": "2026-06-05"},
            "filing_context_cache": [
                {"profile_name": "company_analysis", "latest_context_at": "2026-07-02T10:00:00+00:00"}
            ],
        },
    )


def _args(tmp_path: Path, *extra: str):
    return guided._parser().parse_args(
        [
            "--ticker",
            "MSFT",
            "--profiles",
            "company_analysis",
            "--output-dir",
            str(tmp_path / "out"),
            "--friction-log-dir",
            str(tmp_path / "reviews"),
            "--ciq-folder",
            str(tmp_path / "exports"),
            "--ciq-template",
            str(tmp_path / "ciq_cleandata.xlsx"),
            "--ciq-input-json",
            str(tmp_path / "financials_input.json"),
            "--no-export-xlsx",
            *extra,
        ]
    )


def test_guided_workup_stages_ciq_runs_profile_and_skips_queue(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    calls: dict = {}
    io = ScriptedIO(["", "s"])

    result = guided.run_guided_workup(_args(tmp_path), deps=_deps(tmp_path, calls=calls), io=io)

    assert result["ciq"]["skipped"] is False
    assert calls["prepare_ciq"][0]["ciq_symbol"] == "NASDAQ:MSFT"
    assert calls["ingest_ciq"] == [str(tmp_path / "exports")]
    assert calls["prefetch"][0]["limit"] == 4
    assert calls["profile"] == ["company_analysis"]
    assert result["queue_decisions"] == [{"item_id": 11, "action": "skipped"}]
    review_packet = Path(result["profile_review_packets"][0]["path"])
    assert review_packet.exists()
    review_text = review_packet.read_text(encoding="utf-8")
    assert "Item 11: Growth target review" in review_text
    assert "Base IV: $100.00 -> $106.00" in review_text
    assert "Decision commands:" in review_text
    assert "pm_decision_queue.py --ticker MSFT preview --item-id 11" in review_text
    assert "pm_decision_queue.py --ticker MSFT approve-apply --item-id 11 --confirm APPLY" in review_text
    assert Path(result["artifacts"]["json"]).exists()
    assert Path(result["artifacts"]["friction_draft"]).exists()


def test_guided_workup_lists_exported_valuation_json_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    deps = _deps(tmp_path)
    valuation_json = tmp_path / "out" / "MSFT" / "20260703T000000Z-valuation.json"
    valuation_json.parent.mkdir(parents=True)
    valuation_json.write_text("{}", encoding="utf-8")
    deps.export_xlsx = lambda ticker, workup: {
        "strategy": "advanced_dcf_model",
        "path": str(tmp_path / "MSFT_advanced_dcf_model.xlsx"),
        "valuation_json": str(valuation_json),
    }
    io = ScriptedIO(["", "s"])

    result = guided.run_guided_workup(_args(tmp_path, "--export-xlsx"), deps=deps, io=io)

    assert result["artifacts"]["valuation_json"] == str(valuation_json)


def test_guided_workup_approve_apply_requires_operator_confirmation_and_revalues(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    calls: dict = {}
    io = ScriptedIO(["", "a", "APPLY"])

    result = guided.run_guided_workup(_args(tmp_path), deps=_deps(tmp_path, calls=calls), io=io)

    assert calls["preview"] == [11, 11]
    assert calls["approve"] == [11]
    assert calls["apply"] == [11]
    assert len(calls["value_single_ticker"]) == 2
    assert result["queue_decisions"][0]["action"] == "approved_applied"
    assert result["queue_decisions"][0]["preview_base_delta_pct"] == 6.0


def test_guided_workup_inline_target_edit_repreviews_before_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    calls: dict = {}
    io = ScriptedIO(["", "e", "0.08", "a", "APPLY"])

    result = guided.run_guided_workup(_args(tmp_path), deps=_deps(tmp_path, calls=calls), io=io)

    edited_pack = calls["edit"][0]
    proposal = edited_pack["proposals"][0]
    assert proposal["proposal_mode"] == "target"
    assert proposal["proposed_target_value"] == 0.08
    assert proposal["proposed_delta"] is None
    assert calls["preview"] == [11, 11, 11]
    assert [row["action"] for row in result["queue_decisions"]] == ["edited", "approved_applied"]


def test_guided_workup_pauses_after_profile_with_no_queue_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    calls: dict = {}
    deps = _deps(tmp_path, calls=calls)
    deps.list_queue = lambda ticker, **kwargs: {"ticker": ticker, "items": []}
    deps.run_profile = lambda ticker, profile_name, **kwargs: {
        **_profile_payload(profile_name),
        "queue_item_count": 0,
        "queue_item_ids": [],
    }
    io = ScriptedIO(["", ""])

    result = guided.run_guided_workup(_args(tmp_path), deps=deps, io=io)

    assert result["queue_decisions"] == []
    assert any("Press Enter after reviewing" in message for message in io.messages)
    review_packet = Path(result["profile_review_packets"][0]["path"])
    assert review_packet.exists()
    assert "No new PM Decision Queue items" in review_packet.read_text(encoding="utf-8")


def test_guided_workup_does_not_approve_apply_advisory_findings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    calls: dict = {}
    deps = _deps(tmp_path, calls=calls)
    deps.list_queue = lambda ticker, **kwargs: {"ticker": ticker, "items": [_advisory_item()]}
    deps.run_profile = lambda ticker, profile_name, **kwargs: {
        **_profile_payload(profile_name, item_id=22),
        "queue_item_ids": [22],
    }
    io = ScriptedIO(["", "a", "r", "not a model change"])

    result = guided.run_guided_workup(_args(tmp_path), deps=deps, io=io)

    assert "approve" not in calls
    assert "apply" not in calls
    assert calls["reject"] == ["not a model change"]
    assert result["queue_decisions"][0]["action"] == "rejected"


def test_guided_workup_non_interactive_skips_ciq_ingest_and_queue_mutations(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    monkeypatch.setattr(
        guided,
        "configure_isolated_db",
        lambda args, ticker, stamp: {"mode": "isolated_snapshot", "path": str(tmp_path / "isolated.db")},
    )
    calls: dict = {}
    io = ScriptedIO([])

    result = guided.run_guided_workup(
        _args(tmp_path, "--agent-mode", "heuristic", "--isolated-db", "--non-interactive"),
        deps=_deps(tmp_path, calls=calls),
        io=io,
    )

    assert result["database"]["mode"] == "isolated_snapshot"
    assert result["agent_mode"] == "heuristic"
    assert result["ciq"]["reason"] == "non_interactive_after_stage"
    assert "ingest_ciq" not in calls
    assert "approve" not in calls
    assert "apply" not in calls
    assert result["queue_decisions"] == [{"item_id": 11, "action": "skipped", "reason": "non_interactive"}]


def test_guided_workup_non_interactive_runs_profiles_in_parallel_with_synthesis_last(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    monkeypatch.setattr(guided, "_stamp", lambda: "20260703T000000Z")
    deps = _deps(tmp_path)
    deps.list_queue = lambda ticker, **kwargs: {"ticker": ticker, "items": []}

    risk_started = threading.Event()
    company_done = threading.Event()
    risk_done = threading.Event()

    def _run_profile(ticker: str, profile_name: str, **kwargs):
        if profile_name == "company_analysis":
            assert risk_started.wait(timeout=1.0)
            company_done.set()
        elif profile_name == "risk_review":
            risk_started.set()
            risk_done.set()
        elif profile_name == "analyst_prep_synthesis":
            assert company_done.is_set()
            assert risk_done.is_set()
        return {
            **_profile_payload(profile_name),
            "queue_item_count": 0,
            "queue_item_ids": [],
        }

    deps.run_profile = _run_profile
    args = guided._parser().parse_args(
        [
            "--ticker",
            "MSFT",
            "--profiles",
            "analyst_prep_synthesis",
            "company_analysis",
            "risk_review",
            "--output-dir",
            str(tmp_path / "out"),
            "--friction-log-dir",
            str(tmp_path / "reviews"),
            "--ciq-folder",
            str(tmp_path / "exports"),
            "--ciq-template",
            str(tmp_path / "ciq_cleandata.xlsx"),
            "--ciq-input-json",
            str(tmp_path / "financials_input.json"),
            "--skip-ciq-stage",
            "--non-interactive",
            "--no-export-xlsx",
        ]
    )

    result = guided.run_guided_workup(args, deps=deps, io=ScriptedIO([]))

    assert [run["profile_name"] for run in result["profile_runs"]] == [
        "company_analysis",
        "risk_review",
        "analyst_prep_synthesis",
    ]


def test_guided_workup_non_interactive_deduplicates_profiles(tmp_path: Path) -> None:
    calls: dict = {}
    deps = _deps(tmp_path, calls=calls)
    args = guided._parser().parse_args(
        [
            "--ticker",
            "MSFT",
            "--profiles",
            "company_analysis",
            "company_analysis",
            "--output-dir",
            str(tmp_path / "out"),
            "--friction-log-dir",
            str(tmp_path / "reviews"),
            "--ciq-folder",
            str(tmp_path / "exports"),
            "--ciq-template",
            str(tmp_path / "ciq_cleandata.xlsx"),
            "--ciq-input-json",
            str(tmp_path / "financials_input.json"),
            "--skip-ciq-stage",
            "--non-interactive",
            "--no-export-xlsx",
        ]
    )

    runs = list(
        guided._run_profiles_for_mode(
            args,
            deps=deps,
            io=ScriptedIO([]),
            ticker="MSFT",
        )
    )

    assert [profile for profile, _, _ in runs] == ["company_analysis"]
    assert calls["profile"] == ["company_analysis"]


def test_guided_workup_interactive_keeps_requested_profile_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    deps = _deps(tmp_path)
    deps.list_queue = lambda ticker, **kwargs: {"ticker": ticker, "items": []}
    deps.run_profile = lambda ticker, profile_name, **kwargs: {
        **_profile_payload(profile_name),
        "queue_item_count": 0,
        "queue_item_ids": [],
    }
    args = guided._parser().parse_args(
        [
            "--ticker",
            "MSFT",
            "--profiles",
            "analyst_prep_synthesis",
            "company_analysis",
            "--output-dir",
            str(tmp_path / "out"),
            "--friction-log-dir",
            str(tmp_path / "reviews"),
            "--ciq-folder",
            str(tmp_path / "exports"),
            "--ciq-template",
            str(tmp_path / "ciq_cleandata.xlsx"),
            "--ciq-input-json",
            str(tmp_path / "financials_input.json"),
            "--skip-ciq-stage",
            "--no-export-xlsx",
        ]
    )

    result = guided.run_guided_workup(args, deps=deps, io=ScriptedIO(["", ""]))

    assert [run["profile_name"] for run in result["profile_runs"]] == [
        "analyst_prep_synthesis",
        "company_analysis",
    ]


def test_guided_workup_interactive_reviews_each_profile_before_running_next(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    events: list[str] = []

    class OrderingIO(ScriptedIO):
        def _input(self, prompt: str) -> str:
            events.append("review")
            return super()._input(prompt)

    deps = _deps(tmp_path)
    deps.list_queue = lambda ticker, **kwargs: {"ticker": ticker, "items": []}

    def _run_profile(ticker: str, profile_name: str, **kwargs):
        events.append(f"run:{profile_name}")
        return {
            **_profile_payload(profile_name),
            "queue_item_count": 0,
            "queue_item_ids": [],
        }

    deps.run_profile = _run_profile
    args = guided._parser().parse_args(
        [
            "--ticker",
            "MSFT",
            "--profiles",
            "company_analysis",
            "risk_review",
            "--output-dir",
            str(tmp_path / "out"),
            "--friction-log-dir",
            str(tmp_path / "reviews"),
            "--ciq-folder",
            str(tmp_path / "exports"),
            "--ciq-template",
            str(tmp_path / "ciq_cleandata.xlsx"),
            "--ciq-input-json",
            str(tmp_path / "financials_input.json"),
            "--skip-ciq-stage",
            "--no-export-xlsx",
        ]
    )

    guided.run_guided_workup(args, deps=deps, io=OrderingIO(["", ""]))

    assert events == [
        "run:company_analysis",
        "review",
        "run:risk_review",
        "review",
    ]


def test_guided_workup_renders_data_freshness_in_run_and_profile_packets(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    monkeypatch.setattr(guided, "_now_iso", lambda: "2026-07-03T00:00:00+00:00")
    monkeypatch.setattr(guided, "_stamp", lambda: "20260703T000000Z")
    io = ScriptedIO(["s"])

    result = guided.run_guided_workup(
        _args(tmp_path, "--skip-ciq-stage"),
        deps=_deps(tmp_path),
        io=io,
    )

    run_markdown = Path(result["artifacts"]["markdown"]).read_text(encoding="utf-8")
    review_markdown = Path(result["profile_review_packets"][0]["path"]).read_text(encoding="utf-8")

    for markdown in (run_markdown, review_markdown):
        assert "## Data Freshness" in markdown
        assert "[STALE] market_data fetched 2026-06-12 (age 21.0d, warn >1d)" in markdown
        assert "EDGAR filings: 3 cached, latest filing date=2026-06-05" in markdown
        assert "CIQ ingest: skipped (skip_ciq_stage)" in markdown
    assert "Agent LLM routing: model=" in run_markdown
    assert result["llm_routing"]["source"] == ".env/config"
    assert any(message.startswith("Agent LLM routing: model=") for message in io.messages)


def test_configure_openrouter_free_overrides_pre_set_env(monkeypatch) -> None:
    for env_name in [
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_MODEL_FAST",
        "LLM_SYNTHESIS_MODEL",
        "LLM_FALLBACK_MODELS",
        *AGENT_MODEL_ENV_VARS,
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "gemini-from-env")

    routing = guided.configure_openrouter_free("openai/gpt-oss-120b:free")

    assert os.environ["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert os.environ["LLM_MODEL"] == "openai/gpt-oss-120b:free"
    assert routing["base_url"] == "https://openrouter.ai/api/v1"
    assert routing["model"] == "openai/gpt-oss-120b:free"


def test_guided_workup_codex_routing_configures_subscription_backend_and_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(guided, "heuristic_agent_runs", lambda enabled: nullcontext())
    for env_name in [
        "ALPHA_POD_AGENT_BACKEND",
        "ALPHA_POD_CODEX_MODEL",
        "ALPHA_POD_CODEX_EFFORT",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_MODEL_FAST",
        "LLM_SYNTHESIS_MODEL",
        "LLM_FALLBACK_MODELS",
        *AGENT_MODEL_ENV_VARS,
    ]:
        monkeypatch.delenv(env_name, raising=False)

    io = ScriptedIO(["", "s"])
    routing_env_names = [
        "ALPHA_POD_AGENT_BACKEND",
        "ALPHA_POD_CODEX_MODEL",
        "ALPHA_POD_CODEX_EFFORT",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_MODEL_FAST",
        "LLM_SYNTHESIS_MODEL",
        "LLM_FALLBACK_MODELS",
        *AGENT_MODEL_ENV_VARS,
    ]
    try:
        result = guided.run_guided_workup(
            _args(
            tmp_path,
            "--skip-ciq-stage",
            "--use-codex",
            "--use-openrouter-free",
            "--openrouter-fallback-models",
            "openrouter/backup",
            "--codex-model",
                "gpt-5.6-luna",
                "--codex-effort",
                "low",
            ),
            deps=_deps(tmp_path),
            io=io,
        )
        observed_env = {name: os.environ.get(name) for name in routing_env_names}
    finally:
        for env_name in routing_env_names:
            os.environ.pop(env_name, None)

    assert observed_env["ALPHA_POD_AGENT_BACKEND"] == "codex"
    assert observed_env["ALPHA_POD_CODEX_MODEL"] == "gpt-5.6-luna"
    assert observed_env["ALPHA_POD_CODEX_EFFORT"] == "low"
    assert observed_env["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert observed_env["LLM_MODEL"] == "openrouter/free"
    assert result["llm_routing"] == {
        "backend": "codex",
        "model": "gpt-5.6-luna",
        "effort": "low",
        "fallback": "openrouter/free",
        "base_url": "openrouter.ai",
        "fallbacks": ["openrouter/free", "openrouter/backup"],
        "cost": "subscription",
        "source": "--use-codex",
    }
    assert io.messages[0] == (
        "Agent LLM routing: backend=codex model=gpt-5.6-luna effort=low "
        "fallback=openrouter/free cost=subscription (source: --use-codex)"
    )


def test_export_xlsx_builds_advanced_model_from_current_run_json(tmp_path: Path, monkeypatch) -> None:
    from src.stage_02_valuation import json_exporter
    from src.stage_04_pipeline import advanced_dcf_model

    calls: dict[str, object] = {}
    historicals = [{"period": "FY2025", "revenue": 100.0, "source": "ciq_standard_workbook"}]

    def _fake_export_ticker_json(result, *, output_dir=None, date_str=None, **kwargs):
        path = Path(output_dir) / f"{result['ticker']}_{date_str}.json"
        path.write_text(
            json.dumps(
                {
                    "ticker": result["ticker"],
                    "fresh": True,
                    "historical_financials": kwargs.get("historical_financials") or [],
                }
            ),
            encoding="utf-8",
        )
        calls["export_result"] = result
        calls["export_path"] = path
        calls["export_date_str"] = date_str
        calls["export_historical_financials"] = kwargs.get("historical_financials")
        return path

    def _fake_build_advanced_dcf_model(ticker, *, json_path=None, guided_workup_path=None, **kwargs):
        json_path = Path(json_path)
        assert json_path.exists()
        assert json_path == tmp_path / "guided" / "MSFT" / "20260703T000000Z-valuation.json"
        assert guided_workup_path is not None
        assert Path(guided_workup_path).exists()
        calls["build_json_path"] = json_path
        calls["guided_workup_path"] = Path(guided_workup_path)
        out = tmp_path / f"{ticker}_advanced_dcf_model.xlsx"
        out.write_text("fake workbook", encoding="utf-8")
        return out

    monkeypatch.setattr(json_exporter, "export_ticker_json", _fake_export_ticker_json)
    monkeypatch.setattr(advanced_dcf_model, "build_advanced_dcf_model", _fake_build_advanced_dcf_model)
    monkeypatch.setattr(guided, "_historical_financials_for_guided_json", lambda ticker, result: historicals)

    workup = {
        "ticker": "MSFT",
        "run_stamp": "20260703T000000Z",
        "output_dir": str(tmp_path / "guided"),
        "analyst_prep": {"thesis_cards": [{"title": "Current run thesis"}]},
        "queue_decisions": [],
        "latest_model": {
            "deterministic": {
                "batch_row": {
                    "ticker": "MSFT",
                    "iv_base": 123.45,
                    "forecast_bridge_json": "[]",
                }
            }
        },
    }

    result = guided._export_xlsx("MSFT", workup)

    assert result == {
        "strategy": "advanced_dcf_model",
        "path": str(tmp_path / "MSFT_advanced_dcf_model.xlsx"),
        "valuation_json": str(tmp_path / "guided" / "MSFT" / "20260703T000000Z-valuation.json"),
    }
    assert calls["export_result"] == workup["latest_model"]["deterministic"]["batch_row"]
    assert calls["export_date_str"] == "20260703T000000Z"
    assert calls["export_historical_financials"] == historicals
    assert calls["build_json_path"] == tmp_path / "guided" / "MSFT" / "20260703T000000Z-valuation.json"
    assert Path(result["valuation_json"]).exists()
    assert not Path(calls["export_path"]).exists()
    written_json = json.loads(Path(result["valuation_json"]).read_text(encoding="utf-8"))
    assert written_json["historical_financials"] == historicals
    assert not calls["guided_workup_path"].exists()


def test_friction_draft_write_never_clobbers_existing_same_day_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guided, "_now_iso", lambda: "2026-07-03T00:00:00+00:00")
    monkeypatch.setattr(guided, "_stamp", lambda: "20260703T000000Z")

    friction_dir = tmp_path / "reviews"
    friction_dir.mkdir()
    existing = guided.next_friction_draft_path(friction_dir, "MSFT")
    existing.write_text("sentinel completed log", encoding="utf-8")
    result = {
        "ticker": "MSFT",
        "run_stamp": "20260703T000000Z",
        "run_started_at": "2026-07-03T00:00:00+00:00",
        "agent_mode": "heuristic",
        "database": {"mode": "isolated_snapshot"},
        "profiles": [],
        "queue_decisions": [],
        "latest_model": {},
        "data_freshness": {},
        "llm_routing": {
            "model": "openai/gpt-oss-120b:free",
            "base_url": "openrouter.ai",
            "fallbacks": [],
            "source": "--use-openrouter-free",
        },
    }

    artifacts = guided.write_artifacts(
        result,
        output_dir=tmp_path / "out",
        friction_log_dir=friction_dir,
        prep_markdown="# Analyst Prep MSFT",
    )

    second = friction_dir / f"{existing.stem}-2.md"
    assert existing.read_text(encoding="utf-8") == "sentinel completed log"
    assert Path(artifacts["friction_draft"]) == second
    assert second.exists()
    assert second.read_text(encoding="utf-8").startswith("# Weekly Loop Friction Draft")


def test_friction_draft_reuses_pristine_template_from_same_day_rerun(tmp_path: Path) -> None:
    friction_dir = tmp_path / "reviews"
    friction_dir.mkdir()
    result = {"ticker": "MSFT", "queue_decisions": []}

    first = guided.next_friction_draft_path(friction_dir, "MSFT")
    first.write_text(guided.render_friction_draft(result), encoding="utf-8")

    # An untouched template from an earlier run today is overwritten in place,
    # so repeated smoke runs do not accumulate numbered duplicates.
    second = guided.next_friction_draft_path(friction_dir, "MSFT")
    assert second == first

    # Keeping all TODO markers is not enough: an added PM note in the friction
    # table must preserve the draft and force a new path.
    first.write_text(
        guided.render_friction_draft(result).replace(
            "| TODO | TODO | TODO | TODO | TODO |",
            "| TODO | TODO | TODO | TODO | TODO |\n| Review | medium | no | Added PM note | ticket-1 |",
        ),
        encoding="utf-8",
    )
    added_line_path = guided.next_friction_draft_path(friction_dir, "MSFT")
    assert added_line_path != first
    assert added_line_path.name.endswith("-2.md")

    # Once the PM fills in any TODO, the draft is preserved and a new file is minted.
    first.write_text(
        guided.render_friction_draft(result).replace("- Total time: TODO", "- Total time: 90 min"),
        encoding="utf-8",
    )
    third = guided.next_friction_draft_path(friction_dir, "MSFT")
    assert third != first
    assert third.name.endswith("-2.md")


def test_pm_queue_review_index_includes_commands_and_preview(tmp_path: Path) -> None:
    markdown = pm_decision_queue.render_review_index(
        "MSFT",
        {
            "ticker": "MSFT",
            "items": [
                {
                    **_queue_item(11),
                    "metadata": {"pm_question": "Should this change?"},
                    "decision_history": [],
                    "qualitative_importance": "high",
                }
            ],
        },
        previews={11: _preview_payload(11)},
        output_dir=tmp_path,
    )

    assert "Item 11: Growth target review" in markdown
    assert "Base IV preview: $100.00 -> $106.00 (+6.0%)" in markdown
    assert "pm_decision_queue.py --ticker MSFT preview --item-id 11" in markdown
    assert "pm_decision_queue.py --ticker MSFT approve-apply --item-id 11 --confirm APPLY" in markdown


def test_pm_queue_review_index_does_not_preview_advisory_items(tmp_path: Path) -> None:
    markdown = pm_decision_queue.render_review_index(
        "MSFT",
        {"ticker": "MSFT", "items": [_advisory_item(22)]},
        previews={22: None},
        output_dir=tmp_path,
    )

    assert "Item 22: Risk needs PM review" in markdown
    assert "pm_decision_queue.py --ticker MSFT preview --item-id 22" not in markdown
    assert "pm_decision_queue.py --ticker MSFT approve-apply --item-id 22" not in markdown
    assert 'pm_decision_queue.py --ticker MSFT defer --item-id 22 --reason "Needs PM review"' in markdown


def test_pm_queue_review_index_does_not_emit_dead_commands_for_deferred_items(tmp_path: Path) -> None:
    markdown = pm_decision_queue.render_review_index(
        "MSFT",
        {"ticker": "MSFT", "items": [{**_queue_item(33), "status": "deferred"}]},
        previews={33: {"error": "queue item with status=deferred cannot be previewed"}},
        output_dir=tmp_path,
    )

    assert "Stored preview" not in markdown
    assert "pm_decision_queue.py --ticker MSFT preview --item-id 33" not in markdown
    assert "pm_decision_queue.py --ticker MSFT defer --item-id 33" not in markdown
    assert "No direct mutation command: item 33 is deferred" in markdown
