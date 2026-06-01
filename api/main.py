from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.run_tracker import submit_background_run, update_run, get_run
from src.utils import coerce_ticker
from src.stage_04_pipeline.workspace_views import (
    build_ticker_workspace_payload,
    build_overview_payload,
    build_valuation_summary_payload,
    build_valuation_dcf_payload,
    build_valuation_comps_payload,
    build_valuation_assumptions_payload,
    build_wacc_payload,
    build_valuation_recommendations_payload,
    build_market_payload,
    build_research_payload,
    build_audit_payload,
    build_ticker_dossier_payload,
    load_latest_ticker_dossier_payload,  # noqa: F401 — patched by tests
    build_ticker_dossier_from_source,  # noqa: F401 — patched by tests
    _attach_api_ticker_dossier,
    _normalize_assumptions_preview_payload,
    _normalize_wacc_preview_payload,
    _normalize_recommendations_preview_payload,
)


class WatchlistRefreshRequest(BaseModel):
    tickers: list[str] | None = None
    shortlist_size: int = Field(default=10, ge=1, le=25)
    export_xlsx: bool = False


class AssumptionsApplyRequest(BaseModel):
    selections: dict[str, str] = Field(default_factory=dict)
    custom_values: dict[str, float | None] = Field(default_factory=dict)


class WaccSelectionRequest(BaseModel):
    mode: str = "single_method"
    selected_method: str | None = None
    weights: dict[str, float] = Field(default_factory=dict)


class RecommendationsPreviewRequest(BaseModel):
    approved_fields: list[str] = Field(default_factory=list)


class RecommendationsApplyRequest(BaseModel):
    approved_fields: list[str] = Field(default_factory=list)


class ValuationPolicyEditRequest(BaseModel):
    global_defaults: dict[str, float] = Field(default_factory=dict)
    sector_defaults: dict[str, dict[str, float]] = Field(default_factory=dict)
    notes: str | None = None


class PendingAssumptionPreviewRequest(BaseModel):
    change_ids: list[int] = Field(default_factory=list)
    manual_values: dict[str, float] = Field(default_factory=dict)


class PendingAssumptionApplyRequest(BaseModel):
    change_ids: list[int] = Field(default_factory=list)


class PendingAssumptionDecisionRequest(BaseModel):
    change_ids: list[int] = Field(default_factory=list)


class PMDecisionQueueEditRequest(BaseModel):
    proposal_pack: dict[str, Any]


class PMDecisionQueueActionRequest(BaseModel):
    reason: str = Field(min_length=1)


class AnalysisRunRequest(BaseModel):
    use_cache: bool = True
    force_refresh_agents: list[str] = Field(default_factory=list)


class TickerExportRequest(BaseModel):
    format: str = Field(default="html")
    source_mode: str = Field(default="latest_snapshot")
    template_strategy: str | None = None


class WatchlistExportRequest(BaseModel):
    format: str = Field(default="xlsx")
    source_mode: str = Field(default="saved_watchlist")
    shortlist_size: int = Field(default=10, ge=1, le=25)


def api_coerce_ticker(value: str) -> str:
    try:
        return coerce_ticker(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _raise_pm_queue_http_error(exc: Exception) -> None:
    detail = str(exc)
    lower_detail = detail.lower()
    if "queue item not found" in lower_detail:
        status_code = 404
    elif "previewed after the latest edit" in lower_detail:
        status_code = 409
    else:
        status_code = 400
    raise HTTPException(status_code=status_code, detail=detail) from exc


def load_saved_watchlist(shortlist_size: int = 10) -> dict[str, Any]:
    from src.stage_04_pipeline.batch_funnel import load_saved_watchlist as _impl

    return _impl(shortlist_size=shortlist_size)


def run_deterministic_batch(**kwargs) -> dict[str, Any]:
    from src.stage_04_pipeline.batch_funnel import run_deterministic_batch as _impl

    return _impl(**kwargs)


def load_latest_snapshot_for_ticker(ticker: str) -> dict[str, Any] | None:
    from src.stage_04_pipeline.batch_funnel import load_latest_snapshot_for_ticker as _impl

    return _impl(ticker)


def run_deep_analysis_for_tickers(tickers, **kwargs) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.batch_funnel import run_deep_analysis_for_tickers as _impl

    return _impl(tickers, **kwargs)


def run_ticker_export(
    *,
    ticker: str,
    export_format: str,
    source_mode: str,
    template_strategy: str | None = None,
    created_by: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.export_service import run_ticker_export as _impl

    return _impl(
        ticker=ticker,
        export_format=export_format,
        source_mode=source_mode,
        template_strategy=template_strategy,
        created_by=created_by,
    )


def run_watchlist_export(
    *,
    export_format: str,
    source_mode: str,
    shortlist_size: int = 10,
    created_by: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.export_service import run_watchlist_export as _impl

    return _impl(
        export_format=export_format,
        source_mode=source_mode,
        shortlist_size=shortlist_size,
        created_by=created_by,
    )





def list_saved_exports(*, ticker: str | None = None, scope: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.export_service import list_saved_exports as _impl

    return _impl(ticker=ticker, scope=scope, limit=limit)


def load_saved_export(export_id: str) -> dict[str, Any] | None:
    from src.stage_04_pipeline.export_service import load_saved_export as _impl

    return _impl(export_id)


def resolve_export_download_path(export_id: str, artifact_key: str | None = None):
    from src.stage_04_pipeline.export_service import resolve_export_download_path as _impl

    return _impl(export_id, artifact_key=artifact_key)


def get_market_data(ticker: str, use_cache: bool = True) -> dict[str, Any]:
    from src.stage_00_data.market_data import get_market_data as _impl

    return _impl(ticker, use_cache=use_cache)


def get_analyst_ratings(ticker: str) -> dict[str, Any]:
    from src.stage_00_data.market_data import get_analyst_ratings as _impl

    return _impl(ticker)


def get_revision_signals(ticker: str) -> Any:
    from src.stage_00_data.estimate_tracker import get_revision_signals as _impl

    return _impl(ticker)


def get_macro_snapshot(lookback_days: int = 5) -> dict[str, Any]:
    from src.stage_00_data.fred_client import get_macro_snapshot as _impl

    return _impl(lookback_days=lookback_days)


def get_yield_curve() -> dict[str, Any]:
    from src.stage_00_data.fred_client import get_yield_curve as _impl

    return _impl()


def detect_current_regime() -> Any:
    from src.stage_02_valuation.regime_model import detect_current_regime as _impl

    return _impl()


def get_scenario_weights(regime: Any | None = None) -> Any:
    from src.stage_02_valuation.regime_model import get_scenario_weights as _impl

    return _impl(regime)


def decompose_factor_exposure(ticker: str) -> Any:
    from src.stage_02_valuation.factor_model import decompose_factor_exposure as _impl

    return _impl(ticker)


def get_factor_summary_text(exposure: Any) -> str:
    from src.stage_02_valuation.factor_model import get_factor_summary_text as _impl

    return _impl(exposure)


def build_dcf_audit_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view as _impl

    return _impl(ticker)


def build_comps_dashboard_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view as _impl

    return _impl(ticker)


def build_filings_browser_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.filings_browser import build_filings_browser_view as _impl

    return _impl(ticker)


def build_news_materiality_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.news_materiality import build_news_materiality_view as _impl

    return _impl(ticker)


def build_override_workbench(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import build_override_workbench as _impl

    return _impl(ticker)


def apply_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import apply_override_selections as _impl

    return _impl(ticker, selections=selections, custom_values=custom_values or {}, actor=actor)


def preview_override_selections(
    ticker: str,
    selections: dict[str, str],
    custom_values: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    from src.stage_04_pipeline.override_workbench import preview_override_selections as _impl

    return _impl(ticker, selections=selections, custom_values=custom_values or {})


def build_research_board_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_research_board_view as _impl

    return _impl(ticker)


def build_thesis_tracker_view(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_thesis_tracker_view as _impl

    return _impl(ticker)


def build_publishable_memo_context(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.dossier_view import build_publishable_memo_context as _impl

    return _impl(ticker)


def build_wacc_workbench(ticker: str, apply_overrides: bool = True) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import build_wacc_workbench as _impl

    return _impl(ticker, apply_overrides=apply_overrides)


def preview_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import preview_wacc_methodology_selection as _impl

    return _impl(ticker, mode=mode, selected_method=selected_method, weights=weights)


def apply_wacc_methodology_selection(
    ticker: str,
    *,
    mode: str,
    selected_method: str | None = None,
    weights: dict[str, float] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.wacc_workbench import apply_wacc_methodology_selection as _impl

    return _impl(ticker, mode=mode, selected_method=selected_method, weights=weights, actor=actor)


def load_wacc_methodology_audit_history(ticker: str, limit: int = 50) -> list[dict[str, Any]]:
    from src.stage_04_pipeline.wacc_workbench import load_wacc_methodology_audit_history as _impl

    return _impl(ticker, limit=limit)


def load_recommendations(ticker: str):
    from src.stage_04_pipeline.recommendations import load_recommendations as _impl

    return _impl(ticker)


def preview_recommendations_with_approvals(ticker: str, approved_fields: list[str]) -> dict[str, Any]:
    from src.stage_04_pipeline.recommendations import preview_with_approvals as _impl

    return _impl(ticker, approved_fields)


def apply_recommendations_to_overrides(
    ticker: str,
    approved_fields: list[str] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.recommendations import apply_approved_to_overrides as _impl

    return _impl(ticker, approved_fields=approved_fields, actor=actor)


def load_valuation_policy_payload() -> dict[str, Any]:
    from src.stage_04_pipeline.assumption_policy import load_current_valuation_policy

    return load_current_valuation_policy().model_dump()


def preview_valuation_policy_payload(payload: ValuationPolicyEditRequest) -> dict[str, Any]:
    from src.stage_04_pipeline.assumption_policy import preview_valuation_policy_edits

    return preview_valuation_policy_edits(
        global_defaults=payload.global_defaults,
        sector_defaults=payload.sector_defaults,
    ).model_dump()


def save_valuation_policy_payload(payload: ValuationPolicyEditRequest, actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.assumption_policy import preview_valuation_policy_edits, save_valuation_policy

    preview = preview_valuation_policy_edits(
        global_defaults=payload.global_defaults,
        sector_defaults=payload.sector_defaults,
    )
    policy = preview.proposed_policy.model_copy(update={"notes": payload.notes})
    return save_valuation_policy(policy, actor=actor).model_dump()


def parse_damodaran_policy_drafts_payload() -> dict[str, Any]:
    from src.stage_04_pipeline.assumption_policy import parse_damodaran_drop_folder

    return parse_damodaran_drop_folder()


def list_pending_assumptions_payload(ticker: str) -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import list_pending_assumption_changes

    changes = [change.model_dump() for change in list_pending_assumption_changes(ticker)]
    return {"ticker": ticker.upper(), "pending_changes": changes}


def preview_pending_assumptions_payload(
    ticker: str,
    change_ids: list[int],
    manual_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import preview_pending_assumption_stack

    return preview_pending_assumption_stack(ticker, change_ids, manual_values=manual_values).model_dump()


def apply_pending_assumptions_payload(
    ticker: str,
    change_ids: list[int],
    actor: str = "api",
) -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import apply_pending_assumption_stack

    return apply_pending_assumption_stack(ticker, change_ids, actor=actor)


def run_agentic_handoff_profile_payload(
    ticker: str,
    profile_name: str,
    *,
    include_agent_artifact: bool = False,
) -> dict[str, Any]:
    from db.loader import insert_pm_decision_queue_item, update_evidence_packet_run
    from db.schema import create_tables, get_connection
    from src.contracts.evidence_packet import EvidencePacket, EvidenceSourceQuality
    from src.stage_03_judgment.grounded_observation_agent import GroundedObservationAgent
    from src.stage_04_pipeline.agentic_handoff_profiles import (
        GROUNDED_OBSERVATION_RUNNER_KEY,
        get_agentic_handoff_profile,
    )
    from src.stage_04_pipeline.evidence_packets import build_evidence_packet
    from src.stage_04_pipeline.observation_translator import translate_observations_to_queue_items

    ticker = ticker.upper().strip()
    try:
        profile = get_agentic_handoff_profile(profile_name)
    except KeyError:
        return {
            "ticker": ticker,
            "profile_name": profile_name,
            "status": "not_runnable",
            "reason": "unknown_profile",
            "evidence_packet": None,
            "observation_count": 0,
            "queue_item_count": 0,
            "queue_item_ids": [],
            "errors": [{"code": "unknown_profile", "message": f"Unknown profile: {profile_name}"}],
        }

    packet = build_evidence_packet(ticker, profile_name)

    def _persist_packet(
        *,
        observations: list[Any],
        status: str,
        errors: list[dict[str, Any]],
        queue_item_count: int,
        reason: str | None = None,
        agent_observation_artifact: dict[str, Any] | None = None,
    ) -> EvidencePacket:
        if packet.packet_id is None:
            run_metadata = dict(packet.run_metadata or {})
            run_metadata.update(
                {
                    "handoff_run_status": status,
                    "handoff_errors": errors,
                    "observation_count": len(observations),
                    "queue_item_count": queue_item_count,
                }
            )
            if reason:
                run_metadata["reason"] = reason
            if agent_observation_artifact is not None:
                run_metadata["agent_observation_artifact"] = agent_observation_artifact
            return packet.model_copy(update={"observations": observations, "run_metadata": run_metadata})

        updates = {
            "handoff_run_status": status,
            "handoff_errors": errors,
            "observation_count": len(observations),
            "queue_item_count": queue_item_count,
        }
        if reason:
            updates["reason"] = reason
        if agent_observation_artifact is not None:
            updates["agent_observation_artifact"] = agent_observation_artifact
        with get_connection() as conn:
            create_tables(conn)
            updated = update_evidence_packet_run(
                conn,
                int(packet.packet_id),
                updated_at=packet.generated_at,
                observations=[observation.model_dump() for observation in observations],
                run_metadata_updates=updates,
            )
        return EvidencePacket(
            packet_id=updated.get("packet_id"),
            ticker=updated["ticker"],
            profile_name=updated["profile_name"],
            packet_kind=updated["packet_kind"],
            bundle_id=updated.get("bundle_id"),
            generated_at=updated["generated_at"],
            source_refs=updated.get("source_refs") or [],
            facts=updated.get("facts") or [],
            snippets=updated.get("snippets") or [],
            observations=updated.get("observations") or [],
            run_metadata=updated.get("run_metadata") or {},
        )

    source_quality = str(
        (packet.run_metadata or {}).get("source_quality") or EvidenceSourceQuality.placeholder.value
    ).strip().lower()

    if not profile.runnable:
        reason = profile.not_runnable_reason or "profile_not_runnable"
        packet = _persist_packet(
            observations=[],
            status="not_runnable",
            errors=[],
            queue_item_count=0,
            reason=reason,
        )
        return {
            "ticker": ticker,
            "profile_name": profile_name,
            "status": "not_runnable",
            "reason": reason,
            "evidence_packet": packet.model_dump(),
            "observation_count": 0,
            "queue_item_count": 0,
            "queue_item_ids": [],
            "errors": [],
        }

    if source_quality != EvidenceSourceQuality.real.value:
        packet = _persist_packet(
            observations=[],
            status="blocked",
            errors=[],
            queue_item_count=0,
            reason="insufficient_real_evidence",
        )
        return {
            "ticker": ticker,
            "profile_name": profile_name,
            "status": "blocked",
            "reason": "insufficient_real_evidence",
            "evidence_packet": packet.model_dump(),
            "observation_count": 0,
            "queue_item_count": 0,
            "queue_item_ids": [],
            "errors": [],
        }

    if profile.runner_key != GROUNDED_OBSERVATION_RUNNER_KEY:
        reason = "runner_not_registered"
        packet = _persist_packet(
            observations=[],
            status="not_runnable",
            errors=[],
            queue_item_count=0,
            reason=reason,
        )
        return {
            "ticker": ticker,
            "profile_name": profile_name,
            "status": "not_runnable",
            "reason": reason,
            "evidence_packet": packet.model_dump(),
            "observation_count": 0,
            "queue_item_count": 0,
            "queue_item_ids": [],
            "errors": [],
        }
    observations = []
    agent = GroundedObservationAgent(profile_name=profile_name)
    try:
        observations = agent.analyze_evidence_packet(packet, profile_name)
    except Exception as exc:
        errors = [
            {
                "code": "agent_execution_failed",
                "agent": agent.name,
                "profile_name": profile_name,
                "message": str(exc) or exc.__class__.__name__,
            }
        ]
        packet = _persist_packet(
            observations=[],
            status="failed",
            errors=errors,
            queue_item_count=0,
            reason="agent_execution_failed",
            agent_observation_artifact=getattr(agent, "last_agentic_observation_artifact", None),
        )
        return {
            "ticker": ticker,
            "profile_name": profile_name,
            "status": "failed",
            "reason": "agent_execution_failed",
            "evidence_packet": packet.model_dump(),
            "observation_count": 0,
            "queue_item_count": 0,
            "queue_item_ids": [],
            "errors": errors,
            **(
                {"agent_observation_artifact": getattr(agent, "last_agentic_observation_artifact", None)}
                if include_agent_artifact
                else {}
            ),
        }
    queue_items = translate_observations_to_queue_items(
        ticker=ticker,
        profile_name=profile_name,
        evidence_packet_id=int(packet.packet_id or 0),
        observations=observations,
        evidence_packet=packet,
        require_evidence_packet=True,
    )

    saved_queue_item_ids: list[int] = []
    with get_connection() as conn:
        create_tables(conn)
        for item in queue_items:
            item_id = insert_pm_decision_queue_item(
                conn,
                {
                    **item.model_dump(),
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                    "item_type": item.item_type.value,
                    "status": item.status.value,
                    "qualitative_importance": item.qualitative_importance.value if item.qualitative_importance else None,
                    "valuation_impact_bucket": item.metadata.get("valuation_impact_bucket"),
                    "proposal_pack": item.proposal_pack.model_dump() if item.proposal_pack else None,
                    "pm_edited_proposal_pack": item.pm_edited_proposal_pack.model_dump() if item.pm_edited_proposal_pack else None,
                    "approved_proposal_pack": item.approved_proposal_pack.model_dump() if item.approved_proposal_pack else None,
                    "agent_confidence": item.agent_confidence.value if item.agent_confidence else None,
                    "translator_confidence": item.translator_confidence.value if item.translator_confidence else None,
                    "pm_confidence": item.pm_confidence.value if item.pm_confidence else None,
                    "valuation_impact": item.valuation_impact,
                    "evidence_anchor_ids": item.evidence_anchor_ids,
                    "evidence_packet_ids": item.evidence_packet_ids,
                    "adapter_links": item.adapter_links,
                    "decision_history": item.decision_history,
                    "metadata": item.metadata,
                },
            )
            saved_queue_item_ids.append(item_id)

    status = "completed_with_items" if saved_queue_item_ids else "completed_no_items"
    packet = _persist_packet(
        observations=observations,
        status=status,
        errors=[],
        queue_item_count=len(saved_queue_item_ids),
        agent_observation_artifact=getattr(agent, "last_agentic_observation_artifact", None),
    )
    return {
        "ticker": ticker,
        "profile_name": profile_name,
        "status": status,
        "evidence_packet": packet.model_dump(),
        "observation_count": len(observations),
        "queue_item_count": len(saved_queue_item_ids),
        "queue_item_ids": saved_queue_item_ids,
        "errors": [],
        **(
            {"agent_observation_artifact": getattr(agent, "last_agentic_observation_artifact", None)}
            if include_agent_artifact
            else {}
        ),
    }


def list_evidence_packets_payload(ticker: str) -> dict[str, Any]:
    from db.loader import list_evidence_packets
    from db.schema import create_tables, get_connection

    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        packets = list_evidence_packets(conn, ticker=ticker)
    list_safe_packets = []
    for packet in packets:
        run_metadata = dict(packet.get("run_metadata") or {})
        artifact = run_metadata.pop("agent_observation_artifact", None)
        if artifact is not None:
            run_metadata["agent_observation_artifact_available"] = True
            run_metadata["agent_observation_artifact_status"] = artifact.get("status")
        list_safe_packets.append({**packet, "run_metadata": run_metadata})
    return {"ticker": ticker, "evidence_packets": list_safe_packets}


def get_agent_observation_artifact_payload(ticker: str, packet_id: int) -> dict[str, Any]:
    from db.loader import load_evidence_packet
    from db.schema import create_tables, get_connection

    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        packet = load_evidence_packet(conn, packet_id)
    if packet is None or packet.get("ticker") != ticker:
        raise ValueError(f"evidence packet not found for ticker={ticker} packet_id={packet_id}")
    artifact = (packet.get("run_metadata") or {}).get("agent_observation_artifact")
    if artifact is None:
        raise ValueError(f"agent observation artifact not found for ticker={ticker} packet_id={packet_id}")
    return {"ticker": ticker, "packet_id": int(packet_id), "agent_observation_artifact": artifact}


def list_pm_decision_queue_payload(
    ticker: str,
    *,
    status: str | None = None,
    item_type: str | None = None,
    qualitative_importance: str | None = None,
    valuation_impact_bucket: str | None = None,
) -> dict[str, Any]:
    from db.loader import list_pm_decision_queue_items
    from db.schema import create_tables, get_connection
    from src.stage_04_pipeline.pm_decision_queue import build_pm_decision_queue_conflict_groups

    ticker = ticker.upper().strip()
    with get_connection() as conn:
        create_tables(conn)
        all_items = list_pm_decision_queue_items(conn, ticker=ticker, status=None)
        items = list_pm_decision_queue_items(
            conn,
            ticker=ticker,
            status=status,
            item_type=item_type,
            qualitative_importance=qualitative_importance,
            valuation_impact_bucket=valuation_impact_bucket,
        )
    return {
        "ticker": ticker,
        "items": items,
        "conflict_groups": build_pm_decision_queue_conflict_groups(all_items),
        "filters": {
            "status": status,
            "item_type": item_type,
            "qualitative_importance": qualitative_importance,
            "valuation_impact_bucket": valuation_impact_bucket,
        },
    }


def preview_pm_decision_queue_payload(ticker: str, item_id: int) -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import preview_pm_decision_queue_item

    payload = preview_pm_decision_queue_item(ticker, item_id)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "item": payload.get("item"),
        "preview": payload.get("preview"),
        "skipped_fields": payload.get("skipped_fields") or [],
        "preview_fingerprint": payload.get("preview_fingerprint"),
        "previewed_at": payload.get("previewed_at"),
    }


def edit_pm_decision_queue_payload(ticker: str, item_id: int, proposal_pack: dict[str, Any], actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import edit_pm_decision_queue_item

    item = edit_pm_decision_queue_item(ticker, item_id, proposal_pack, actor=actor)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "status": item.get("status"),
        "item": item,
        "pm_edited_proposal_pack": item.get("pm_edited_proposal_pack"),
    }


def approve_pm_decision_queue_payload(ticker: str, item_id: int, actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import approve_pm_decision_queue_item

    item = approve_pm_decision_queue_item(ticker, item_id, actor=actor)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "status": item.get("status"),
        "item": item,
    }


def apply_pm_decision_queue_payload(ticker: str, item_id: int, actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import apply_pm_decision_queue_item

    item = apply_pm_decision_queue_item(ticker, item_id, actor=actor)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "status": item.get("status"),
        "item": item,
    }


def reject_pm_decision_queue_payload(ticker: str, item_id: int, actor: str = "api", reason: str = "") -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import reject_pm_decision_queue_item

    item = reject_pm_decision_queue_item(ticker, item_id, actor=actor, reason=reason)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "status": item.get("status"),
        "reason": reason,
        "item": item,
    }


def defer_pm_decision_queue_payload(ticker: str, item_id: int, actor: str = "api", reason: str = "") -> dict[str, Any]:
    from src.stage_04_pipeline.pm_decision_queue import defer_pm_decision_queue_item

    item = defer_pm_decision_queue_item(ticker, item_id, actor=actor, reason=reason)
    return {
        "ticker": ticker.upper().strip(),
        "item_id": int(item_id),
        "status": item.get("status"),
        "reason": reason,
        "item": item,
    }


def approve_pending_assumptions_payload(ticker: str, change_ids: list[int], actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import approve_pending_assumption_changes

    return approve_pending_assumption_changes(ticker, change_ids, actor=actor)


def reject_pending_assumptions_payload(ticker: str, change_ids: list[int], actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import reject_pending_assumption_changes

    return reject_pending_assumption_changes(ticker, change_ids, actor=actor)


def defer_pending_assumptions_payload(ticker: str, change_ids: list[int], actor: str = "api") -> dict[str, Any]:
    from src.stage_04_pipeline.pending_assumption_changes import defer_pending_assumption_changes

    return defer_pending_assumption_changes(ticker, change_ids, actor=actor)


build_ticker_overview_payload = build_overview_payload


build_valuation_wacc_payload = build_wacc_payload


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        from db.schema import create_tables, get_connection

        with get_connection() as conn:
            create_tables(conn)
        yield

    app = FastAPI(title="Alpha Pod API", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def get_health() -> dict[str, Any]:
        from src.stage_04_pipeline.diagnostics import run_diagnostics
        return run_diagnostics().as_dict()

    @app.get("/api/watchlist")
    def get_watchlist(shortlist_size: int = 10) -> dict[str, Any]:
        return load_saved_watchlist(shortlist_size=shortlist_size)

    @app.post("/api/watchlist/refresh", status_code=202)
    def refresh_watchlist(payload: WatchlistRefreshRequest) -> dict[str, Any]:
        tickers = [api_coerce_ticker(value) for value in (payload.tickers or [])]

        def _runner(run_id: str) -> dict[str, Any]:
            def _on_progress(event: dict[str, Any]) -> None:
                total = max(int(event.get("total") or 0), 1)
                completed = min(int(event.get("completed") or 0), total)
                progress = completed / total
                message = event.get("ticker")
                status = event.get("status")
                update_run(
                    run_id,
                    status="running",
                    progress=progress,
                    message=f"{status}:{message}" if status and message else status,
                )

            return run_deterministic_batch(
                tickers=tickers or None,
                shortlist_size=payload.shortlist_size,
                export_xlsx=payload.export_xlsx,
                progress_callback=_on_progress,
            )

        run_id = submit_background_run(
            "watchlist_refresh",
            _runner,
            metadata={"shortlist_size": payload.shortlist_size, "ticker_count": len(tickers)},
        )
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/watchlist/exports")
    def get_watchlist_exports(limit: int = 25) -> dict[str, Any]:
        return {"exports": list_saved_exports(scope="batch", limit=limit)}

    @app.post("/api/watchlist/exports", status_code=202)
    def create_watchlist_export(payload: WatchlistExportRequest | None = None) -> dict[str, Any]:
        request_payload = payload or WatchlistExportRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return run_watchlist_export(
                export_format=request_payload.format,
                source_mode=request_payload.source_mode,
                shortlist_size=request_payload.shortlist_size,
                created_by="api",
            )

        run_id = submit_background_run(
            "watchlist_export",
            _runner,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/runs/{run_id}")
    def get_run_status(run_id: str) -> dict[str, Any]:
        run = get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/api/tickers/{ticker}/workspace")
    def get_ticker_workspace(ticker: str) -> dict[str, Any]:
        return build_ticker_workspace_payload(ticker)

    @app.get("/api/tickers/{ticker}/overview")
    def get_ticker_overview(ticker: str) -> dict[str, Any]:
        return build_ticker_overview_payload(ticker)

    @app.get("/api/tickers/{ticker}/dossier")
    def get_ticker_dossier(ticker: str, source_mode: str | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return build_ticker_dossier_payload(ticker, source_mode=source_mode)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tickers/{ticker}/valuation/summary")
    def get_ticker_valuation_summary(ticker: str, source_mode: str | None = None) -> dict[str, Any]:
        if source_mode is None:
            return build_valuation_summary_payload(ticker)
        return build_valuation_summary_payload(ticker, source_mode=source_mode)

    @app.get("/api/tickers/{ticker}/valuation/dcf")
    def get_ticker_valuation_dcf(ticker: str) -> dict[str, Any]:
        return build_valuation_dcf_payload(ticker)

    @app.get("/api/tickers/{ticker}/valuation/comps")
    def get_ticker_valuation_comps(ticker: str) -> dict[str, Any]:
        return build_valuation_comps_payload(ticker)

    @app.get("/api/tickers/{ticker}/valuation/assumptions")
    def get_ticker_valuation_assumptions(ticker: str) -> dict[str, Any]:
        return build_valuation_assumptions_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/assumptions/preview")
    def preview_ticker_valuation_assumptions(
        ticker: str,
        payload: AssumptionsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        selections = (payload.selections if payload else {})
        custom_values = (payload.custom_values if payload else {})
        preview = preview_override_selections(
            ticker,
            selections=selections,
            custom_values=custom_values,
        )
        return _normalize_assumptions_preview_payload(ticker, preview)

    @app.post("/api/tickers/{ticker}/valuation/assumptions/apply", status_code=202)
    def apply_ticker_valuation_assumptions(
        ticker: str,
        payload: AssumptionsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        selections = (payload.selections if payload else {})
        custom_values = (payload.custom_values if payload else {})

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_override_selections(
                ticker,
                selections=selections,
                custom_values=custom_values,
                actor="api",
            )

        run_id = submit_background_run("valuation_assumptions_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/tickers/{ticker}/valuation/wacc")
    def get_ticker_wacc(ticker: str) -> dict[str, Any]:
        return build_valuation_wacc_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/wacc/preview")
    def preview_ticker_wacc(
        ticker: str,
        payload: WaccSelectionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or WaccSelectionRequest()
        preview = preview_wacc_methodology_selection(
            ticker,
            mode=request_payload.mode,
            selected_method=request_payload.selected_method,
            weights=request_payload.weights,
        )
        return _normalize_wacc_preview_payload(ticker, preview, request_payload)

    @app.post("/api/tickers/{ticker}/valuation/wacc/apply", status_code=202)
    def apply_ticker_wacc(
        ticker: str,
        payload: WaccSelectionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or WaccSelectionRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_wacc_methodology_selection(
                ticker,
                mode=request_payload.mode,
                selected_method=request_payload.selected_method,
                weights=request_payload.weights,
                actor="api",
            )

        run_id = submit_background_run("valuation_wacc_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/tickers/{ticker}/valuation/recommendations")
    def get_ticker_valuation_recommendations(ticker: str) -> dict[str, Any]:
        return build_valuation_recommendations_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/recommendations/preview")
    def preview_ticker_valuation_recommendations(
        ticker: str,
        payload: RecommendationsPreviewRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or RecommendationsPreviewRequest()
        preview = preview_recommendations_with_approvals(ticker, request_payload.approved_fields)
        return _normalize_recommendations_preview_payload(ticker, preview)

    @app.post("/api/tickers/{ticker}/valuation/recommendations/apply", status_code=202)
    def apply_ticker_valuation_recommendations(
        ticker: str,
        payload: RecommendationsApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or RecommendationsApplyRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_recommendations_to_overrides(
                ticker,
                approved_fields=request_payload.approved_fields,
                actor="api",
            )

        run_id = submit_background_run("valuation_recommendations_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/valuation/policy")
    def get_valuation_policy() -> dict[str, Any]:
        return load_valuation_policy_payload()

    @app.post("/api/valuation/policy/preview")
    def preview_valuation_policy(payload: ValuationPolicyEditRequest | None = None) -> dict[str, Any]:
        return preview_valuation_policy_payload(payload or ValuationPolicyEditRequest())

    @app.put("/api/valuation/policy")
    def save_valuation_policy(payload: ValuationPolicyEditRequest | None = None) -> dict[str, Any]:
        return save_valuation_policy_payload(payload or ValuationPolicyEditRequest(), actor="api")

    @app.post("/api/valuation/policy/damodaran/parse")
    def parse_damodaran_policy_drafts() -> dict[str, Any]:
        return parse_damodaran_policy_drafts_payload()

    @app.get("/api/tickers/{ticker}/valuation/pending-changes")
    def get_ticker_pending_assumption_changes(ticker: str) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return list_pending_assumptions_payload(ticker)

    @app.post("/api/tickers/{ticker}/valuation/pending-changes/preview")
    def preview_ticker_pending_assumption_changes(
        ticker: str,
        payload: PendingAssumptionPreviewRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or PendingAssumptionPreviewRequest()
        return preview_pending_assumptions_payload(
            ticker,
            request_payload.change_ids,
            manual_values=request_payload.manual_values,
        )


    @app.post("/api/tickers/{ticker}/valuation/pending-changes/approve", status_code=202)
    def approve_ticker_pending_assumption_changes(
        ticker: str,
        payload: PendingAssumptionDecisionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or PendingAssumptionDecisionRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return approve_pending_assumptions_payload(ticker, request_payload.change_ids, actor="api")

        run_id = submit_background_run("valuation_pending_changes_approve", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/tickers/{ticker}/valuation/pending-changes/reject", status_code=202)
    def reject_ticker_pending_assumption_changes(
        ticker: str,
        payload: PendingAssumptionDecisionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or PendingAssumptionDecisionRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return reject_pending_assumptions_payload(ticker, request_payload.change_ids, actor="api")

        run_id = submit_background_run("valuation_pending_changes_reject", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/tickers/{ticker}/valuation/pending-changes/defer", status_code=202)
    def defer_ticker_pending_assumption_changes(
        ticker: str,
        payload: PendingAssumptionDecisionRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or PendingAssumptionDecisionRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return defer_pending_assumptions_payload(ticker, request_payload.change_ids, actor="api")

        run_id = submit_background_run("valuation_pending_changes_defer", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/tickers/{ticker}/valuation/pending-changes/apply", status_code=202)
    def apply_ticker_pending_assumption_changes(
        ticker: str,
        payload: PendingAssumptionApplyRequest | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or PendingAssumptionApplyRequest()

        def _runner(_run_id: str) -> dict[str, Any]:
            return apply_pending_assumptions_payload(ticker, request_payload.change_ids, actor="api")

        run_id = submit_background_run("valuation_pending_changes_apply", _runner, ticker=ticker)
        return {"run_id": run_id, "status": "queued"}

    @app.post("/api/tickers/{ticker}/agentic-handoff/{profile_name}/run")
    def run_agentic_handoff_profile(ticker: str, profile_name: str) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return run_agentic_handoff_profile_payload(ticker, profile_name)

    @app.get("/api/tickers/{ticker}/evidence-packets")
    def get_ticker_evidence_packets(ticker: str) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return list_evidence_packets_payload(ticker)

    @app.get("/api/tickers/{ticker}/evidence-packets/{packet_id}/agent-artifact")
    def get_ticker_agent_observation_artifact(ticker: str, packet_id: int) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return get_agent_observation_artifact_payload(ticker, packet_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/tickers/{ticker}/pm-decision-queue")
    def get_ticker_pm_decision_queue(
        ticker: str,
        status: str | None = None,
        item_type: str | None = None,
        qualitative_importance: str | None = None,
        valuation_impact_bucket: str | None = None,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return list_pm_decision_queue_payload(
            ticker,
            status=status,
            item_type=item_type,
            qualitative_importance=qualitative_importance,
            valuation_impact_bucket=valuation_impact_bucket,
        )

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/preview")
    def preview_ticker_pm_decision_queue_item(ticker: str, item_id: int) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return preview_pm_decision_queue_payload(ticker, item_id)
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/edit")
    def edit_ticker_pm_decision_queue_item(
        ticker: str,
        item_id: int,
        payload: PMDecisionQueueEditRequest,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return edit_pm_decision_queue_payload(ticker, item_id, payload.proposal_pack, actor="api")
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/approve")
    def approve_ticker_pm_decision_queue_item(ticker: str, item_id: int) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return approve_pm_decision_queue_payload(ticker, item_id, actor="api")
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/apply")
    def apply_ticker_pm_decision_queue_item(ticker: str, item_id: int) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return apply_pm_decision_queue_payload(ticker, item_id, actor="api")
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/reject")
    def reject_ticker_pm_decision_queue_item(
        ticker: str,
        item_id: int,
        payload: PMDecisionQueueActionRequest,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return reject_pm_decision_queue_payload(ticker, item_id, actor="api", reason=payload.reason)
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.post("/api/tickers/{ticker}/pm-decision-queue/{item_id}/defer")
    def defer_ticker_pm_decision_queue_item(
        ticker: str,
        item_id: int,
        payload: PMDecisionQueueActionRequest,
    ) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        try:
            return defer_pm_decision_queue_payload(ticker, item_id, actor="api", reason=payload.reason)
        except ValueError as exc:
            _raise_pm_queue_http_error(exc)

    @app.get("/api/tickers/{ticker}/market")
    def get_ticker_market(ticker: str) -> dict[str, Any]:
        return build_market_payload(ticker)

    @app.get("/api/tickers/{ticker}/research")
    def get_ticker_research(ticker: str) -> dict[str, Any]:
        return build_research_payload(ticker)

    @app.get("/api/tickers/{ticker}/audit")
    def get_ticker_audit(ticker: str) -> dict[str, Any]:
        return build_audit_payload(ticker)

    @app.get("/api/tickers/{ticker}/exports")
    def get_ticker_exports(ticker: str, limit: int = 25) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        return {"exports": list_saved_exports(ticker=ticker, scope="ticker", limit=limit)}

    @app.post("/api/tickers/{ticker}/exports", status_code=202)
    def create_ticker_export(ticker: str, payload: TickerExportRequest | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or TickerExportRequest()
        if request_payload.source_mode == "latest_snapshot" and load_latest_snapshot_for_ticker(ticker) is None:
            raise HTTPException(status_code=409, detail="no archived snapshot found for export")

        def _runner(_run_id: str) -> dict[str, Any]:
            return run_ticker_export(
                ticker=ticker,
                export_format=request_payload.format,
                source_mode=request_payload.source_mode,
                template_strategy=request_payload.template_strategy,
                created_by="api",
            )

        run_id = submit_background_run(
            "ticker_export",
            _runner,
            ticker=ticker,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued", "ticker": ticker}

    @app.get("/api/exports/{export_id}")
    def get_export_detail(export_id: str) -> dict[str, Any]:
        payload = load_saved_export(export_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="export not found")
        return payload

    @app.get("/api/exports/{export_id}/download")
    def download_export(export_id: str):
        try:
            path = resolve_export_download_path(export_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path=path, filename=path.name)

    @app.get("/api/exports/{export_id}/artifacts/{artifact_key}")
    def download_export_artifact(export_id: str, artifact_key: str):
        try:
            path = resolve_export_download_path(export_id, artifact_key=artifact_key)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path=path, filename=path.name)

    @app.post("/api/tickers/{ticker}/analysis/run", status_code=202)
    def run_ticker_analysis(ticker: str, payload: AnalysisRunRequest | None = None) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        request_payload = payload or AnalysisRunRequest()

        def _runner(_run_id: str) -> list[dict[str, Any]]:
            return run_deep_analysis_for_tickers(
                [ticker],
                use_cache=request_payload.use_cache,
                force_refresh_agents=request_payload.force_refresh_agents,
            )

        run_id = submit_background_run(
            "deep_analysis",
            _runner,
            ticker=ticker,
            metadata=request_payload.model_dump(),
        )
        return {"run_id": run_id, "status": "queued", "ticker": ticker}

    @app.post("/api/tickers/{ticker}/snapshot/open-latest")
    def open_ticker_latest_snapshot(ticker: str) -> dict[str, Any]:
        ticker = api_coerce_ticker(ticker)
        payload = load_latest_snapshot_for_ticker(ticker)
        if payload is None:
            raise HTTPException(status_code=404, detail="no archived snapshot found")
        return _attach_api_ticker_dossier(dict(payload), ticker, source_mode="latest_snapshot")

    return app




app = create_app()
