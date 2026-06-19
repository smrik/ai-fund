from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from scripts.manual import pm_decision_queue
from scripts.manual import run_guided_ticker_workup as guided


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
        collect_freshness=lambda ticker: {"ticker": ticker, "edgar_filing_cache": {"filing_count": 3}},
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
