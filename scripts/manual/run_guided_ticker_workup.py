from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manual.run_ticker_valuation_flow import (  # noqa: E402
    DEFAULT_PROFILES,
    attach_finance_quality_review,
    collect_data_freshness,
    configure_isolated_db,
    configure_openrouter_free,
    heuristic_agent_runs,
    refresh_current_ticker_dossier,
)
from src.stage_04_pipeline.analyst_prep_pack import (  # noqa: E402
    build_analyst_prep_payload,
    render_analyst_prep_markdown,
)


GUIDED_OUTPUT_DIR = ROOT / "output" / "guided_workups"
FRICTION_LOG_DIR = ROOT / "docs" / "reviews" / "weekly-loop"

# Engineering display default aligned with scripts/manual/weekly_preflight.py.
# M1 only warns in PM-facing markdown; staleness gating belongs to Milestone 3.
MARKET_CACHE_STALE_WARN_DAYS = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _split_model_list(value: Any) -> list[str]:
    if isinstance(value, list):
        parts = value
    else:
        parts = str(value or "").split(",")
    return [str(part).strip() for part in parts if str(part).strip()]


def _host_only(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return "not configured"
    parsed = urlparse(text)
    if parsed.hostname:
        return parsed.hostname
    parsed = urlparse(f"//{text}")
    return parsed.hostname or text.split("/")[0]


def _config_llm_defaults() -> dict[str, str]:
    try:
        from config import LLM_BASE_URL, LLM_MODEL

        return {"model": str(LLM_MODEL or ""), "base_url": str(LLM_BASE_URL or "")}
    except Exception:
        return {"model": "", "base_url": ""}


def build_llm_routing(
    *,
    source: str,
    configured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = _config_llm_defaults()
    configured = configured or {}
    model = str(configured.get("model") or os.getenv("LLM_MODEL") or defaults.get("model") or "not configured")
    base_url = (
        configured.get("base_url")
        or os.getenv("LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or defaults.get("base_url")
        or ""
    )
    fallback_models = configured.get("fallback_models")
    if fallback_models is None:
        fallback_models = _split_model_list(os.getenv("LLM_FALLBACK_MODELS"))
    return {
        "model": model,
        "base_url": _host_only(base_url),
        "fallbacks": _split_model_list(fallback_models),
        "source": source,
    }


def format_llm_routing_line(routing: dict[str, Any]) -> str:
    fallbacks = _as_list(routing.get("fallbacks"))
    fallback_label = ", ".join(str(value) for value in fallbacks) if fallbacks else "none"
    return (
        f"Agent LLM routing: model={routing.get('model') or 'not configured'} "
        f"base_url={routing.get('base_url') or 'not configured'} "
        f"fallbacks={fallback_label} "
        f"(source: {routing.get('source') or 'unknown'})"
    )


def _int_set(values: Any) -> set[int]:
    result: set[int] = set()
    for value in _as_list(values):
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _fmt_money(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"${float(value):,.2f}"
    except Exception:
        return "n/a"


def _fmt_pct(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):+.1f}%"
    except Exception:
        return "n/a"


def _parse_run_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return value[4] == "-" and value[7] == "-"


def _market_cache_age_days(fetched_at: Any, run_started_at: Any) -> float | None:
    fetched_text = str(fetched_at or "").strip()
    run_dt = _parse_run_datetime(run_started_at)
    if not fetched_text or run_dt is None:
        return None
    if _is_iso_date(fetched_text):
        fetched_date = datetime.fromisoformat(fetched_text).date()
        return float(max(0, (run_dt.date() - fetched_date).days))
    fetched_dt = _parse_run_datetime(fetched_text)
    if fetched_dt is None:
        return None
    return max(0.0, (run_dt - fetched_dt).total_seconds() / 86400.0)


def _fmt_warn_days(days: float) -> str:
    return f"{int(days)}d" if float(days).is_integer() else f"{days:.1f}d"


def _report_stat(report: Any, key: str) -> int:
    if isinstance(report, dict):
        value = report.get(key, 0)
    else:
        value = getattr(report, key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _render_ciq_freshness_line(ciq_info: Any, freshness: dict[str, Any]) -> str:
    ciq = _as_dict(ciq_info) or _as_dict(freshness.get("ciq")) or _as_dict(freshness.get("ciq_ingest"))
    if not ciq:
        return "- CIQ ingest: not recorded"
    if ciq.get("error"):
        return f"- CIQ ingest: failed ({ciq.get('error')})"
    if ciq.get("skipped"):
        return f"- CIQ ingest: skipped ({ciq.get('reason') or 'no reason recorded'})"

    report = _as_dict(ciq.get("ingest_report")) or ciq
    parts = ["- CIQ ingest:"]
    if ciq.get("ciq_symbol"):
        parts.append(f"symbol={ciq.get('ciq_symbol')}")
    if ciq.get("workbook_path"):
        parts.append(f"workbook={ciq.get('workbook_path')}")
    if report:
        parts.append(f"processed={_report_stat(report, 'processed')}")
        parts.append(f"skipped={_report_stat(report, 'skipped')}")
        parts.append(f"failed={_report_stat(report, 'failed')}")
    return " ".join(parts)


def render_data_freshness_section(
    freshness_value: Any,
    *,
    run_started_at: Any,
    ciq_info: Any = None,
) -> list[str]:
    freshness = _as_dict(freshness_value)
    lines = ["## Data Freshness", ""]
    if freshness.get("db_path"):
        lines.append(f"- Database: `{freshness.get('db_path')}`")

    lines.append(_render_ciq_freshness_line(ciq_info, freshness))

    if freshness.get("error"):
        lines.append(f"- Data freshness unavailable: {freshness.get('error')}")
        lines.append("")
        return lines

    market_rows = [row for row in _as_list(freshness.get("market_cache_rows")) if isinstance(row, dict)]
    if market_rows:
        warn_label = _fmt_warn_days(MARKET_CACHE_STALE_WARN_DAYS)
        for row in market_rows:
            data_type = row.get("data_type") or "unknown"
            fetched_at = row.get("fetched_at") or "n/a"
            age_days = _market_cache_age_days(fetched_at, run_started_at)
            if age_days is None:
                age_label = "n/a"
                stale_prefix = ""
            else:
                age_label = f"{age_days:.1f}d"
                stale_prefix = "[STALE] " if age_days > MARKET_CACHE_STALE_WARN_DAYS else ""
            lines.append(
                f"- {stale_prefix}{data_type} fetched {fetched_at} "
                f"(age {age_label}, warn >{warn_label})"
            )
    else:
        lines.append("- Market cache: no rows recorded")

    filing_cache = _as_dict(freshness.get("edgar_filing_cache"))
    if filing_cache:
        lines.append(
            f"- EDGAR filings: {filing_cache.get('filing_count', 0)} cached, "
            f"latest filing date={filing_cache.get('latest_filing_date') or 'n/a'}"
        )
    else:
        lines.append("- EDGAR filings: no cache summary recorded")

    filing_context = [row for row in _as_list(freshness.get("filing_context_cache")) if isinstance(row, dict)]
    if filing_context:
        context_bits = [
            f"{row.get('profile_name') or 'unknown'}={row.get('latest_context_at') or 'n/a'}"
            for row in filing_context
        ]
        lines.append(f"- Filing context cache: {', '.join(context_bits)}")
    lines.append("")
    return lines


@dataclass(slots=True)
class GuidedIO:
    input_fn: Callable[[str], str] = input
    output_fn: Callable[[str], None] = print

    def write(self, message: str = "") -> None:
        self.output_fn(message)

    def ask(self, prompt: str) -> str:
        return self.input_fn(prompt)


@dataclass(slots=True)
class GuidedDependencies:
    prepare_ciq_refresh: Callable[..., Path] | None = None
    resolve_ciq_symbol: Callable[..., str] | None = None
    ingest_ciq_folder: Callable[..., Any] | None = None
    prefetch_filings: Callable[..., Any] | None = None
    value_single_ticker: Callable[[str], Any] | None = None
    build_summary: Callable[..., dict[str, Any]] | None = None
    build_dcf: Callable[[str], dict[str, Any]] | None = None
    build_comps: Callable[[str], dict[str, Any]] | None = None
    build_assumptions: Callable[[str], dict[str, Any]] | None = None
    list_queue: Callable[..., dict[str, Any]] | None = None
    preview_queue_item: Callable[[str, int], dict[str, Any]] | None = None
    edit_queue_item: Callable[..., dict[str, Any]] | None = None
    approve_queue_item: Callable[..., dict[str, Any]] | None = None
    apply_queue_item: Callable[..., dict[str, Any]] | None = None
    reject_queue_item: Callable[..., dict[str, Any]] | None = None
    defer_queue_item: Callable[..., dict[str, Any]] | None = None
    run_profile: Callable[..., dict[str, Any]] | None = None
    build_prep_pack: Callable[[str], dict[str, Any]] = build_analyst_prep_payload
    render_prep_markdown: Callable[[dict[str, Any]], str] = render_analyst_prep_markdown
    export_xlsx: Callable[..., dict[str, Any]] | None = None
    refresh_dossier: Callable[[str], dict[str, Any]] = refresh_current_ticker_dossier
    collect_freshness: Callable[[str], dict[str, Any]] = collect_data_freshness

    def resolve(self) -> "GuidedDependencies":
        if self.prepare_ciq_refresh is None or self.resolve_ciq_symbol is None:
            from ciq.ciq_refresh import prepare_single_ticker_refresh, resolve_ciq_symbol

            self.prepare_ciq_refresh = self.prepare_ciq_refresh or prepare_single_ticker_refresh
            self.resolve_ciq_symbol = self.resolve_ciq_symbol or resolve_ciq_symbol
        if self.ingest_ciq_folder is None:
            from ciq.ingest import ingest_ciq_folder

            self.ingest_ciq_folder = ingest_ciq_folder
        if self.prefetch_filings is None:
            from src.stage_00_data.edgar_prefetch import prefetch_filings

            self.prefetch_filings = prefetch_filings
        if self.value_single_ticker is None:
            from src.stage_02_valuation.batch_runner import value_single_ticker

            self.value_single_ticker = value_single_ticker
        if any(
            value is None
            for value in (self.build_summary, self.build_dcf, self.build_comps, self.build_assumptions)
        ):
            from api.main import (
                build_valuation_assumptions_payload,
                build_valuation_comps_payload,
                build_valuation_dcf_payload,
                build_valuation_summary_payload,
            )

            self.build_summary = self.build_summary or build_valuation_summary_payload
            self.build_dcf = self.build_dcf or build_valuation_dcf_payload
            self.build_comps = self.build_comps or build_valuation_comps_payload
            self.build_assumptions = self.build_assumptions or build_valuation_assumptions_payload
        if any(
            value is None
            for value in (
                self.list_queue,
                self.preview_queue_item,
                self.edit_queue_item,
                self.approve_queue_item,
                self.apply_queue_item,
                self.reject_queue_item,
                self.defer_queue_item,
                self.run_profile,
            )
        ):
            from api.main import (
                apply_pm_decision_queue_payload,
                approve_pm_decision_queue_payload,
                defer_pm_decision_queue_payload,
                edit_pm_decision_queue_payload,
                list_pm_decision_queue_payload,
                preview_pm_decision_queue_payload,
                reject_pm_decision_queue_payload,
                run_agentic_handoff_profile_payload,
            )

            self.list_queue = self.list_queue or list_pm_decision_queue_payload
            self.preview_queue_item = self.preview_queue_item or preview_pm_decision_queue_payload
            self.edit_queue_item = self.edit_queue_item or edit_pm_decision_queue_payload
            self.approve_queue_item = self.approve_queue_item or approve_pm_decision_queue_payload
            self.apply_queue_item = self.apply_queue_item or apply_pm_decision_queue_payload
            self.reject_queue_item = self.reject_queue_item or reject_pm_decision_queue_payload
            self.defer_queue_item = self.defer_queue_item or defer_pm_decision_queue_payload
            self.run_profile = self.run_profile or run_agentic_handoff_profile_payload
        if self.export_xlsx is None:
            self.export_xlsx = _export_xlsx
        return self


@dataclass(slots=True)
class ReviewResult:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    applied_count: int = 0


@dataclass(slots=True)
class ProfileReviewPacket:
    path: str
    profile_name: str
    queue_item_ids: list[int]


def _export_xlsx(ticker: str, workup: dict[str, Any] | None = None) -> dict[str, Any]:
    """Emit the weekly-loop Excel artifact.

    Canonical path is the advanced DCF model: it reconciles to the backend IV, carries
    the judgment layer, and cannot corrupt (no PowerQuery). Falls back to the legacy
    PowerQuery template export when the model cannot be built (e.g. no excel_flat JSON
    yet, or a non-value_driver terminal mode), so the loop never loses its Excel output.

    When *workup* is supplied, its current deterministic ``latest_model`` is exported
    to a fresh valuation JSON, and its agent thesis/driver cards are surfaced — so the
    model reflects this run rather than auto-discovering a previous one.
    """
    try:
        from src.stage_04_pipeline.advanced_dcf_model import build_advanced_dcf_model
        from src.stage_02_valuation.json_exporter import export_ticker_json

        workup_path: str | None = None
        tmp_file: Path | None = None
        deterministic_result = _as_dict(
            _as_dict(_as_dict(workup or {}).get("latest_model")).get("deterministic")
        ).get("batch_row")
        deterministic_result = _as_dict(deterministic_result)
        if not deterministic_result or deterministic_result.get("error"):
            raise ValueError(
                "Advanced DCF export requires this run's deterministic batch_row; "
                "refusing to build from the default latest valuation JSON."
            )

        import tempfile

        with tempfile.TemporaryDirectory(prefix=f"{ticker}-valuation-json-") as tmp_dir:
            valuation_json_path = export_ticker_json(
                deterministic_result,
                output_dir=Path(tmp_dir),
                date_str=str(_as_dict(workup or {}).get("run_stamp") or _stamp()),
            )
            if workup and (workup.get("analyst_prep") or {}).get("thesis_cards"):
                fd, name = tempfile.mkstemp(prefix=f"{ticker}-workup-", suffix=".json")
                tmp_file = Path(name)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(workup, fh)
                workup_path = str(tmp_file)
            try:
                path = build_advanced_dcf_model(
                    ticker,
                    json_path=valuation_json_path,
                    guided_workup_path=workup_path,
                )
            finally:
                if tmp_file is not None:
                    tmp_file.unlink(missing_ok=True)
        return {"strategy": "advanced_dcf_model", "path": str(path)}
    except Exception as model_exc:
        try:
            from src.stage_04_pipeline.export_service import run_ticker_export

            result = run_ticker_export(
                ticker=ticker,
                export_format="xlsx",
                source_mode="loaded_backend_state",
                template_strategy="power_query",
                created_by="guided_ticker_workup_script",
            )
            if isinstance(result, dict):
                result["strategy"] = "power_query_fallback"
                result["advanced_dcf_model_error"] = str(model_exc)
            return result
        except Exception as fallback_exc:
            return {
                "strategy": "none",
                "advanced_dcf_model_error": str(model_exc),
                "power_query_fallback_error": str(fallback_exc),
            }


def _active_pack(item: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(item.get("pm_edited_proposal_pack") or item.get("proposal_pack"))


def _preview_base_delta(preview: dict[str, Any]) -> Any:
    return _as_dict(_as_dict(preview.get("preview")).get("delta_pct")).get("base")


def _summarize_packet(packet: dict[str, Any]) -> dict[str, Any]:
    facts = _as_list(packet.get("facts"))
    snippets = _as_list(packet.get("snippets"))
    refs = _as_list(packet.get("source_refs"))
    observations = _as_list(packet.get("observations"))
    metadata = _as_dict(packet.get("run_metadata"))
    return {
        "packet_id": packet.get("packet_id"),
        "source_quality": metadata.get("source_quality"),
        "facts": len(facts),
        "snippets": len(snippets),
        "source_refs": len(refs),
        "observations": len(observations),
        "sample_facts": facts[:3],
        "sample_snippets": snippets[:2],
        "sample_observations": observations[:3],
    }


def build_model_snapshot(
    ticker: str,
    *,
    deps: GuidedDependencies,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    deterministic: dict[str, Any] = {}
    try:
        deterministic["batch_row"] = _jsonable(deps.value_single_ticker(ticker))  # type: ignore[misc]
    except Exception as exc:
        deterministic["batch_row"] = {"error": str(exc)}
        errors.append({"step": "value_single_ticker", "message": str(exc)})
    try:
        deterministic["current_dossier_refresh"] = _jsonable(deps.refresh_dossier(ticker))
    except Exception as exc:
        deterministic["current_dossier_refresh"] = {"error": str(exc)}
        errors.append({"step": "refresh_current_ticker_dossier", "message": str(exc)})

    builders: tuple[tuple[str, Callable[..., Any], dict[str, Any]], ...] = (
        ("summary", deps.build_summary, {"source_mode": "loaded_backend_state"}),  # type: ignore[arg-type]
        ("dcf", deps.build_dcf, {}),  # type: ignore[arg-type]
        ("comps", deps.build_comps, {}),  # type: ignore[arg-type]
        ("assumptions", deps.build_assumptions, {}),  # type: ignore[arg-type]
    )
    for name, builder, kwargs in builders:
        try:
            deterministic[name] = _jsonable(builder(ticker, **kwargs))
        except Exception as exc:
            deterministic[name] = {"error": str(exc)}
            errors.append({"step": f"build_{name}", "message": str(exc)})

    result = {"ticker": ticker, "deterministic": deterministic, "errors": errors}
    try:
        attach_finance_quality_review(result)
    except Exception as exc:
        errors.append({"step": "finance_quality_review", "message": str(exc)})
    result["errors"] = errors
    return result


def stage_and_ingest_ciq(args: argparse.Namespace, ticker: str, *, deps: GuidedDependencies, io: GuidedIO) -> dict[str, Any]:
    if args.skip_ciq_stage:
        return {"skipped": True, "reason": "skip_ciq_stage"}

    symbol = deps.resolve_ciq_symbol(ticker, ciq_symbol=args.ciq_symbol, exchange=args.exchange)  # type: ignore[misc]
    workbook_path = deps.prepare_ciq_refresh(  # type: ignore[misc]
        ticker=ticker,
        ciq_symbol=symbol,
        as_of_date=args.as_of_date,
        currency=args.currency,
        template_path=args.ciq_template,
        input_json_path=args.ciq_input_json,
        output_folder=args.ciq_folder,
    )
    io.write("")
    io.write("CIQ manual refresh required")
    io.write(f"- CIQ symbol: {symbol}")
    io.write(f"- Workbook to refresh/save: {workbook_path}")
    io.write(f"- Input JSON: {args.ciq_input_json}")
    if args.non_interactive:
        io.write("- Non-interactive mode: CIQ workbook was staged, ingest is skipped.")
        return {
            "skipped": True,
            "reason": "non_interactive_after_stage",
            "ciq_symbol": symbol,
            "workbook_path": str(workbook_path),
            "input_json_path": str(args.ciq_input_json),
        }

    response = io.ask("Refresh/save the workbook, then press Enter to ingest (or type abort): ").strip().lower()
    if response == "abort":
        raise RuntimeError("operator aborted after CIQ staging")

    report = deps.ingest_ciq_folder(args.ciq_folder)  # type: ignore[misc]
    return {
        "skipped": False,
        "ciq_symbol": symbol,
        "workbook_path": str(workbook_path),
        "input_json_path": str(args.ciq_input_json),
        "ingest_report": _jsonable(report),
    }


def run_edgar_prefetch(args: argparse.Namespace, ticker: str, *, deps: GuidedDependencies, io: GuidedIO) -> dict[str, Any]:
    if args.skip_edgar_prefetch:
        return {"skipped": True, "reason": "skip_edgar_prefetch"}
    io.write(f"Prefetching EDGAR filings for {ticker}...")
    result = deps.prefetch_filings(  # type: ignore[misc]
        ticker,
        forms=args.edgar_forms,
        limit=args.edgar_limit,
        summary_only=args.edgar_summary_only,
    )
    return _jsonable(result)


def _list_queue_items(deps: GuidedDependencies, ticker: str) -> list[dict[str, Any]]:
    payload = deps.list_queue(ticker, status=None)  # type: ignore[misc]
    return [item for item in _as_list(payload.get("items")) if isinstance(item, dict)]


def _items_by_ids(items: list[dict[str, Any]], item_ids: set[int]) -> list[dict[str, Any]]:
    return [item for item in items if int(item.get("item_id") or 0) in item_ids]


def _print_profile_summary(io: GuidedIO, run_payload: dict[str, Any]) -> None:
    packet_summary = _summarize_packet(_as_dict(run_payload.get("evidence_packet")))
    io.write("")
    io.write(f"Profile `{run_payload.get('profile_name')}`")
    io.write(f"- Status: {run_payload.get('status')}")
    io.write(f"- Reason: {run_payload.get('reason') or 'n/a'}")
    io.write(
        "- Evidence: "
        f"quality={packet_summary.get('source_quality') or 'unknown'} "
        f"facts={packet_summary['facts']} snippets={packet_summary['snippets']} "
        f"refs={packet_summary['source_refs']} observations={packet_summary['observations']}"
    )
    for observation in packet_summary["sample_observations"]:
        if isinstance(observation, dict):
            io.write(f"- Observation: {observation.get('claim')}")
            if observation.get("pm_question"):
                io.write(f"  PM question: {observation.get('pm_question')}")


def _print_queue_item(io: GuidedIO, item: dict[str, Any], preview: dict[str, Any] | None) -> None:
    io.write("")
    io.write(f"Queue item {item.get('item_id')}: {item.get('title')}")
    io.write(f"- Type/status/profile: {item.get('item_type')} / {item.get('status')} / {item.get('profile_name')}")
    io.write(f"- Summary: {item.get('summary')}")
    metadata = _as_dict(item.get("metadata"))
    if metadata.get("pm_question"):
        io.write(f"- PM question: {metadata.get('pm_question')}")
    for proposal in _as_list(_active_pack(item).get("proposals")):
        if isinstance(proposal, dict):
            io.write(
                f"- Proposal: {proposal.get('assumption_name')} {proposal.get('proposal_mode')} "
                f"target={proposal.get('proposed_target_value')} delta={proposal.get('proposed_delta')}"
            )
    if preview:
        if preview.get("error"):
            io.write(f"- Preview error: {preview.get('error')}")
            return
        payload = _as_dict(preview.get("preview"))
        current_iv = _as_dict(payload.get("current_iv"))
        proposed_iv = _as_dict(payload.get("proposed_iv"))
        delta_pct = _as_dict(payload.get("delta_pct"))
        io.write(
            f"- Preview base IV: {_fmt_money(current_iv.get('base'))} -> "
            f"{_fmt_money(proposed_iv.get('base'))} ({_fmt_pct(delta_pct.get('base'))})"
        )


def _preview_item(
    ticker: str,
    item: dict[str, Any],
    *,
    deps: GuidedDependencies,
) -> dict[str, Any] | None:
    if item.get("item_type") != "assumption_change_pack":
        return None
    return _jsonable(deps.preview_queue_item(ticker, int(item["item_id"])))  # type: ignore[misc]


def _build_item_previews(
    ticker: str,
    items: list[dict[str, Any]],
    *,
    deps: GuidedDependencies,
) -> dict[int, dict[str, Any] | None]:
    previews: dict[int, dict[str, Any] | None] = {}
    for item in items:
        item_id = int(item["item_id"])
        try:
            previews[item_id] = _preview_item(ticker, item, deps=deps)
        except Exception as exc:
            previews[item_id] = {"error": str(exc)}
    return previews


def _render_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _append_wrapped_value(lines: list[str], label: str, value: Any) -> None:
    rendered = _render_value(value)
    if len(rendered) > 220:
        lines.extend([f"{label}:", "", "```text", rendered, "```"])
    else:
        lines.append(f"{label}: {rendered}")


def _decision_commands(ticker: str, item: dict[str, Any]) -> list[str]:
    item_id = int(item["item_id"])
    base = f"python scripts/manual/pm_decision_queue.py --ticker {ticker}"
    status = str(item.get("status") or "").lower()
    if status not in {"pending", "previewed"}:
        return [f"# No direct mutation command: item {item_id} is {status or 'not actionable'}."]
    commands = [
        f'{base} defer --item-id {item_id} --reason "Needs PM review"',
        f'{base} reject --item-id {item_id} --reason "Not decision-useful"',
    ]
    if item.get("item_type") == "assumption_change_pack":
        commands.insert(0, f"{base} preview --item-id {item_id}")
        for proposal in _as_list(_active_pack(item).get("proposals")):
            if isinstance(proposal, dict) and proposal.get("assumption_name"):
                commands.append(
                    f"{base} edit-target --item-id {item_id} "
                    f"--target {proposal.get('assumption_name')}=<value>"
                )
        commands.append(f"{base} approve-apply --item-id {item_id} --confirm APPLY")
    return commands


def _render_profile_review_markdown(
    *,
    ticker: str,
    run_stamp: str,
    run_started_at: Any,
    run_payload: dict[str, Any],
    queue_items: list[dict[str, Any]],
    previews: dict[int, dict[str, Any] | None],
    data_freshness: Any = None,
    ciq_info: Any = None,
) -> str:
    profile = str(run_payload.get("profile_name") or "unknown_profile")
    packet = _as_dict(run_payload.get("evidence_packet"))
    packet_summary = _summarize_packet(packet)
    lines = [
        f"# {ticker} {profile} Review",
        "",
        f"- Run: {run_stamp}",
        f"- Status: {run_payload.get('status')}",
        f"- Reason: {run_payload.get('reason') or 'n/a'}",
        f"- Source quality: {packet_summary.get('source_quality') or 'unknown'}",
        f"- Facts / snippets / refs / observations: {packet_summary['facts']} / {packet_summary['snippets']} / {packet_summary['source_refs']} / {packet_summary['observations']}",
        "",
    ]
    lines.extend(
        render_data_freshness_section(
            data_freshness,
            run_started_at=run_started_at,
            ciq_info=ciq_info,
        )
    )
    lines.extend(["## Observations", ""])
    observations = [
        item for item in _as_list(packet.get("observations")) if isinstance(item, dict)
    ]
    if observations:
        for idx, observation in enumerate(observations, start=1):
            lines.append(f"{idx}. {_render_value(observation.get('claim'))}")
            if observation.get("pm_question"):
                lines.append(f"PM question: {_render_value(observation.get('pm_question'))}")
            if observation.get("thesis_implication"):
                _append_wrapped_value(lines, "Thesis implication", observation.get("thesis_implication"))
            if observation.get("driver_implication"):
                _append_wrapped_value(lines, "Driver implication", observation.get("driver_implication"))
            lines.append("")
    else:
        lines.extend(["No observations produced.", ""])

    lines.extend(["## Evidence Samples", ""])
    for fact in packet_summary["sample_facts"]:
        if isinstance(fact, dict):
            lines.append(
                f"- Fact `{fact.get('fact_id') or fact.get('fact_name') or 'unknown'}`: "
                f"{_render_value(fact.get('value'))}"
            )
    for snippet in packet_summary["sample_snippets"]:
        if isinstance(snippet, dict):
            text = _render_value(snippet.get("text") or snippet.get("excerpt"))
            lines.append(f"- Snippet `{snippet.get('snippet_id') or 'unknown'}`: {text[:500]}")
    if not packet_summary["sample_facts"] and not packet_summary["sample_snippets"]:
        lines.append("- No sample facts or snippets available.")
    lines.append("")

    lines.extend(["## Queue Items", ""])
    if not queue_items:
        lines.extend(["No new PM Decision Queue items for this profile.", ""])
    for item in queue_items:
        item_id = int(item["item_id"])
        metadata = _as_dict(item.get("metadata"))
        lines.extend(
            [
                f"### Item {item_id}: {item.get('title')}",
                "",
                f"- Type: {item.get('item_type')}",
                f"- Status: {item.get('status')}",
                f"- Importance: {item.get('qualitative_importance') or 'n/a'}",
                f"- Summary: {_render_value(item.get('summary'))}",
            ]
        )
        if metadata.get("pm_question"):
            lines.append(f"- PM question: {_render_value(metadata.get('pm_question'))}")
        if metadata.get("thesis_implication"):
            _append_wrapped_value(lines, "- Thesis implication", metadata.get("thesis_implication"))
        if metadata.get("driver_implication"):
            _append_wrapped_value(lines, "- Driver implication", metadata.get("driver_implication"))
        proposals = [p for p in _as_list(_active_pack(item).get("proposals")) if isinstance(p, dict)]
        if proposals:
            lines.extend(["", "Proposals:"])
            for proposal in proposals:
                lines.append(
                    f"- `{proposal.get('assumption_name')}` "
                    f"{proposal.get('proposal_mode')} "
                    f"target={proposal.get('proposed_target_value')} "
                    f"delta={proposal.get('proposed_delta')}"
                )
                if proposal.get("rationale"):
                    lines.append(f"  Rationale: {_render_value(proposal.get('rationale'))}")
        preview = previews.get(item_id)
        if preview:
            lines.extend(["", "Preview:"])
            if preview.get("error"):
                lines.append(f"- Error: {preview.get('error')}")
            else:
                payload = _as_dict(preview.get("preview"))
                current_iv = _as_dict(payload.get("current_iv"))
                proposed_iv = _as_dict(payload.get("proposed_iv"))
                delta_pct = _as_dict(payload.get("delta_pct"))
                lines.append(
                    f"- Base IV: {_fmt_money(current_iv.get('base'))} -> "
                    f"{_fmt_money(proposed_iv.get('base'))} ({_fmt_pct(delta_pct.get('base'))})"
                )
                resolved = _as_dict(payload.get("resolved_values"))
                for name, values in resolved.items():
                    value_map = _as_dict(values)
                    lines.append(
                        f"- `{name}`: {value_map.get('current_value')} -> "
                        f"{value_map.get('proposed_value')}"
                    )
        lines.extend(["", "Decision commands:", "", "```powershell"])
        lines.extend(_decision_commands(ticker, item))
        lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## Decision Notes",
            "",
            "- Advisory findings can be rejected, deferred, or skipped.",
            "- Assumption-change packs can be edited, rejected, deferred, skipped, or approved/applied after a fresh preview.",
            "- Do not approve if the evidence and valuation impact do not both make sense.",
            "",
        ]
    )
    return "\n".join(lines)


def write_profile_review_packet(
    *,
    ticker: str,
    run_stamp: str,
    run_started_at: Any,
    output_dir: Path,
    run_payload: dict[str, Any],
    queue_items: list[dict[str, Any]],
    previews: dict[int, dict[str, Any] | None],
    data_freshness: Any = None,
    ciq_info: Any = None,
) -> ProfileReviewPacket:
    profile = str(run_payload.get("profile_name") or "unknown_profile")
    ticker_dir = output_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    path = ticker_dir / f"{ticker}-{run_stamp}-{profile}-review.md"
    path.write_text(
        _render_profile_review_markdown(
            ticker=ticker,
            run_stamp=run_stamp,
            run_started_at=run_started_at,
            run_payload=run_payload,
            queue_items=queue_items,
            previews=previews,
            data_freshness=data_freshness,
            ciq_info=ciq_info,
        ),
        encoding="utf-8",
    )
    return ProfileReviewPacket(
        path=str(path),
        profile_name=profile,
        queue_item_ids=[int(item["item_id"]) for item in queue_items],
    )


def _reason(io: GuidedIO, action: str) -> str:
    while True:
        reason = io.ask(f"Reason to {action}: ").strip()
        if reason:
            return reason
        io.write("Reason is required.")


def _edited_pack_from_inline_targets(item: dict[str, Any], io: GuidedIO) -> dict[str, Any] | None:
    pack = dict(_active_pack(item))
    proposals = []
    changed = False
    for proposal in _as_list(pack.get("proposals")):
        if not isinstance(proposal, dict):
            continue
        edited = dict(proposal)
        name = str(edited.get("assumption_name") or "").strip()
        if not name:
            proposals.append(edited)
            continue
        raw = io.ask(f"New target for {name} (blank keeps proposal): ").strip()
        if raw:
            edited["proposal_mode"] = "target"
            edited["proposed_target_value"] = float(raw)
            edited["proposed_delta"] = None
            changed = True
        proposals.append(edited)
    if not changed:
        return None
    pack["proposals"] = proposals
    return pack


def review_queue_items(
    ticker: str,
    items: list[dict[str, Any]],
    *,
    deps: GuidedDependencies,
    io: GuidedIO,
    non_interactive: bool,
    previews: dict[int, dict[str, Any] | None] | None = None,
) -> ReviewResult:
    result = ReviewResult()
    previews = previews or {}
    for item in items:
        item_id = int(item["item_id"])
        is_assumption_pack = item.get("item_type") == "assumption_change_pack"
        preview = previews.get(item_id)
        if item_id not in previews:
            try:
                preview = _preview_item(ticker, item, deps=deps)
            except Exception as exc:
                preview = {"error": str(exc)}
        _print_queue_item(io, item, preview)

        if non_interactive:
            result.decisions.append({"item_id": item_id, "action": "skipped", "reason": "non_interactive"})
            continue

        while True:
            prompt = (
                "Action [a=approve+apply, e=edit target, r=reject, d=defer, s=skip]: "
                if is_assumption_pack
                else "Action [r=reject, d=defer, s=skip]: "
            )
            action = io.ask(prompt).strip().lower()
            if action in {"", "s", "skip"}:
                result.decisions.append({"item_id": item_id, "action": "skipped"})
                break
            if action in {"r", "reject"}:
                reason = _reason(io, "reject")
                payload = deps.reject_queue_item(ticker, item_id, actor="pm", reason=reason)  # type: ignore[misc]
                result.decisions.append({"item_id": item_id, "action": "rejected", "payload": _jsonable(payload)})
                break
            if action in {"d", "defer"}:
                reason = _reason(io, "defer")
                payload = deps.defer_queue_item(ticker, item_id, actor="pm", reason=reason)  # type: ignore[misc]
                result.decisions.append({"item_id": item_id, "action": "deferred", "payload": _jsonable(payload)})
                break
            if action in {"e", "edit"}:
                if not is_assumption_pack:
                    io.write("Advisory findings cannot be edited into assumption changes from this CLI.")
                    continue
                try:
                    edited_pack = _edited_pack_from_inline_targets(item, io)
                except ValueError as exc:
                    io.write(f"Invalid target: {exc}")
                    continue
                if edited_pack is None:
                    io.write("No changes entered.")
                    continue
                edit_payload = deps.edit_queue_item(ticker, item_id, edited_pack, actor="pm")  # type: ignore[misc]
                item = _as_dict(edit_payload.get("item"))
                preview = _preview_item(ticker, item, deps=deps)
                _print_queue_item(io, item, preview)
                result.decisions.append(
                    {
                        "item_id": item_id,
                        "action": "edited",
                        "edited_pack": edited_pack,
                        "preview": preview,
                    }
                )
                continue
            if action in {"a", "approve", "apply"}:
                if not is_assumption_pack:
                    io.write("Advisory findings cannot be approve/applied; reject, defer, or skip them.")
                    continue
                preview = _preview_item(ticker, item, deps=deps)
                if not preview or preview.get("error"):
                    io.write("Cannot approve until preview resolves cleanly.")
                    continue
                _print_queue_item(io, item, preview)
                confirm = io.ask(f"Type APPLY to approve and apply queue item {item_id}: ").strip()
                if confirm != "APPLY":
                    io.write("Apply cancelled.")
                    continue
                try:
                    approved = deps.approve_queue_item(ticker, item_id, actor="pm")  # type: ignore[misc]
                    applied = deps.apply_queue_item(ticker, item_id, actor="pm")  # type: ignore[misc]
                except Exception as exc:
                    io.write(f"Approve/apply failed: {exc}")
                    continue
                result.applied_count += 1
                result.decisions.append(
                    {
                        "item_id": item_id,
                        "action": "approved_applied",
                        "preview_base_delta_pct": _preview_base_delta(preview or {}),
                        "approved": _jsonable(approved),
                        "applied": _jsonable(applied),
                    }
                )
                break
            io.write("Unknown action.")
    return result


def render_guided_markdown(result: dict[str, Any]) -> str:
    ticker = result["ticker"]
    latest_model = _as_dict(result.get("latest_model"))
    deterministic = _as_dict(latest_model.get("deterministic"))
    batch_row = _as_dict(deterministic.get("batch_row"))
    lines = [
        f"# {ticker} Guided Full-Ticker Workup",
        "",
        f"- Generated: {result.get('run_started_at')}",
        f"- Agent mode: {result.get('agent_mode')}",
        f"- Database mode: {_as_dict(result.get('database')).get('mode', 'live')}",
        f"- Profiles: {', '.join(result.get('profiles') or [])}",
        f"- Queue decisions: {len(result.get('queue_decisions') or [])}",
        f"- Applied queue items: {sum(1 for row in result.get('queue_decisions') or [] if row.get('action') == 'approved_applied')}",
        "",
    ]
    lines.extend(
        render_data_freshness_section(
            result.get("data_freshness"),
            run_started_at=result.get("run_started_at"),
            ciq_info=result.get("ciq"),
        )
    )
    llm_routing = _as_dict(result.get("llm_routing"))
    if llm_routing:
        lines.extend([format_llm_routing_line(llm_routing), ""])
    lines.extend(
        [
            "## Final Model Snapshot",
            "",
            f"- Current price: {_fmt_money(batch_row.get('price'))}",
            f"- Bear / Base / Bull IV: {_fmt_money(batch_row.get('iv_bear'))} / {_fmt_money(batch_row.get('iv_base'))} / {_fmt_money(batch_row.get('iv_bull'))}",
            f"- Base upside: {_fmt_pct(batch_row.get('upside_base_pct'))}",
            f"- Growth near/mid: {batch_row.get('growth_near', 'n/a')} / {batch_row.get('growth_mid', 'n/a')}",
            f"- EBIT margin: {batch_row.get('ebit_margin_used', 'n/a')}",
            f"- WACC: {batch_row.get('wacc', 'n/a')}",
            f"- Exit multiple: {batch_row.get('exit_multiple_used', 'n/a')}",
            "",
            "## Profile Reviews",
            "",
        ]
    )
    for run in _as_list(result.get("profile_runs")):
        packet_summary = _summarize_packet(_as_dict(run.get("evidence_packet")))
        lines.extend(
            [
                f"### {run.get('profile_name')}",
                "",
                f"- Status: {run.get('status')}",
                f"- Source quality: {packet_summary.get('source_quality') or 'unknown'}",
                f"- Observations / queue items: {run.get('observation_count', 0)} / {run.get('queue_item_count', 0)}",
                f"- Facts / snippets / refs: {packet_summary['facts']} / {packet_summary['snippets']} / {packet_summary['source_refs']}",
                "",
            ]
        )
    if result.get("queue_decisions"):
        lines.extend(["## Queue Decisions", ""])
        for decision in _as_list(result.get("queue_decisions")):
            if isinstance(decision, dict):
                lines.append(f"- Item {decision.get('item_id')}: {decision.get('action')}")
        lines.append("")
    if result.get("profile_review_packets"):
        lines.extend(["## Profile Review Packets", ""])
        for packet in _as_list(result.get("profile_review_packets")):
            if isinstance(packet, dict):
                lines.append(
                    f"- {packet.get('profile_name')}: `{packet.get('path')}` "
                    f"(queue items: {packet.get('queue_item_ids') or []})"
                )
        lines.append("")
    if result.get("errors"):
        lines.extend(["## Errors", "", "```json", json.dumps(result["errors"], indent=2, default=str), "```", ""])
    artifacts = _as_dict(result.get("artifacts"))
    if artifacts:
        lines.extend(["## Artifacts", ""])
        for key, value in artifacts.items():
            lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


def render_friction_draft(result: dict[str, Any]) -> str:
    ticker = result["ticker"]
    today = datetime.now(timezone.utc).date().isoformat()
    return "\n".join(
        [
            f"# Weekly Loop Friction Draft - {today} - {ticker}",
            "",
            f"- Ticker: {ticker}",
            "- Total time: TODO",
            "- Session number: TODO",
            "",
            "## Per-Phase Times",
            "",
            "- CIQ stage/ingest: TODO",
            "- EDGAR prefetch: TODO",
            "- Initial valuation: TODO",
            "- Profile review loop: TODO",
            "- Final export: TODO",
            "",
            "## Queue Decisions",
            "",
            f"- Approved/applied: {sum(1 for row in result.get('queue_decisions') or [] if row.get('action') == 'approved_applied')}",
            f"- Edited: {sum(1 for row in result.get('queue_decisions') or [] if row.get('action') == 'edited')}",
            f"- Rejected: {sum(1 for row in result.get('queue_decisions') or [] if row.get('action') == 'rejected')}",
            f"- Deferred: {sum(1 for row in result.get('queue_decisions') or [] if row.get('action') == 'deferred')}",
            "",
            "## Friction Items",
            "",
            "| Phase | Severity | Manual data surgery? | What happened | Fix/ticket |",
            "| --- | --- | --- | --- | --- |",
            "| TODO | TODO | TODO | TODO | TODO |",
            "",
            "## Keep / Change",
            "",
            "- Keep: TODO",
            "- Change: TODO",
            "",
        ]
    )


def write_artifacts(
    result: dict[str, Any],
    *,
    output_dir: Path,
    friction_log_dir: Path,
    prep_markdown: str,
) -> dict[str, str]:
    ticker = result["ticker"]
    stamp = result["run_stamp"]
    ticker_dir = output_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    friction_log_dir.mkdir(parents=True, exist_ok=True)

    json_path = ticker_dir / f"{ticker}-{stamp}.json"
    md_path = ticker_dir / f"{ticker}-{stamp}.md"
    prep_md_path = ticker_dir / f"{ticker}-{stamp}-analyst-prep.md"
    friction_path = next_friction_draft_path(friction_log_dir, ticker)

    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_guided_markdown(result), encoding="utf-8")
    prep_md_path.write_text(prep_markdown, encoding="utf-8")
    friction_path.write_text(render_friction_draft(result), encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "analyst_prep_markdown": str(prep_md_path),
        "friction_draft": str(friction_path),
    }


def next_friction_draft_path(friction_log_dir: Path, ticker: str) -> Path:
    today = datetime.now(timezone.utc).date().isoformat()
    base = friction_log_dir / f"{today}-{ticker}-friction-draft.md"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = friction_log_dir / f"{today}-{ticker}-friction-draft-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def run_guided_workup(
    args: argparse.Namespace,
    *,
    deps: GuidedDependencies | None = None,
    io: GuidedIO | None = None,
) -> dict[str, Any]:
    deps = (deps or GuidedDependencies()).resolve()
    io = io or GuidedIO()
    ticker = args.ticker.upper().strip()
    run_stamp = _stamp()
    database_info = configure_isolated_db(args, ticker, run_stamp)
    if args.edgar_cache_only:
        os.environ["ALPHA_POD_EDGAR_CACHE_ONLY"] = "1"
    if args.market_cache_only:
        os.environ["ALPHA_POD_MARKET_CACHE_ONLY"] = "1"
        os.environ["ALPHA_POD_ALLOW_STALE_MARKET_CACHE"] = "1"
    configured_llm_routing: dict[str, Any] | None = None
    if args.use_openrouter_free:
        configured_llm_routing = configure_openrouter_free(args.openrouter_model, args.openrouter_fallback_models)
    llm_routing = build_llm_routing(
        source="--use-openrouter-free" if args.use_openrouter_free else ".env/config",
        configured=configured_llm_routing,
    )
    io.write(format_llm_routing_line(llm_routing))

    result: dict[str, Any] = {
        "ticker": ticker,
        "run_stamp": run_stamp,
        "run_started_at": _now_iso(),
        "agent_mode": args.agent_mode,
        "profiles": list(args.profiles),
        "database": database_info or {"mode": "live", "path": str(ROOT / "data" / "alpha_pod.db")},
        "ciq": None,
        "edgar_prefetch": None,
        "initial_model": None,
        "latest_model": None,
        "model_snapshots": [],
        "profile_runs": [],
        "profile_review_packets": [],
        "queue_decisions": [],
        "analyst_prep": None,
        "excel_export": None,
        "data_freshness": None,
        "llm_routing": llm_routing,
        "errors": [],
        "artifacts": {},
    }

    try:
        result["ciq"] = stage_and_ingest_ciq(args, ticker, deps=deps, io=io)
    except Exception as exc:
        result["ciq"] = {"error": str(exc)}
        result["errors"].append({"step": "ciq_stage_ingest", "message": str(exc)})
        raise

    try:
        result["edgar_prefetch"] = run_edgar_prefetch(args, ticker, deps=deps, io=io)
    except Exception as exc:
        result["edgar_prefetch"] = {"error": str(exc)}
        result["errors"].append({"step": "edgar_prefetch", "message": str(exc)})

    io.write(f"Building initial deterministic model for {ticker}...")
    initial_model = build_model_snapshot(ticker, deps=deps)
    result["initial_model"] = initial_model
    result["latest_model"] = initial_model
    result["model_snapshots"].append({"label": "initial", "model": initial_model})
    result["errors"].extend(initial_model.get("errors") or [])

    try:
        result["data_freshness"] = deps.collect_freshness(ticker)
    except Exception as exc:
        result["data_freshness"] = {"error": str(exc)}

    try:
        initial_queue_ids = {int(item["item_id"]) for item in _list_queue_items(deps, ticker) if item.get("item_id")}
    except Exception:
        initial_queue_ids = set()
    seen_queue_ids = set(initial_queue_ids)

    with heuristic_agent_runs(args.agent_mode == "heuristic"):
        for profile in args.profiles:
            io.write("")
            io.write(f"Running {profile} ({args.agent_mode})...")
            try:
                run_payload = _jsonable(deps.run_profile(ticker, profile, include_agent_artifact=True))  # type: ignore[misc]
            except Exception as exc:
                run_payload = {
                    "ticker": ticker,
                    "profile_name": profile,
                    "status": "failed",
                    "reason": "script_exception",
                    "errors": [{"code": "script_exception", "message": str(exc)}],
                    "observation_count": 0,
                    "queue_item_count": 0,
                    "queue_item_ids": [],
                }
                result["errors"].append({"step": f"profile:{profile}", "message": str(exc)})
            result["profile_runs"].append(run_payload)
            _print_profile_summary(io, run_payload)

            queue_ids = _int_set(run_payload.get("queue_item_ids"))
            current_items = _list_queue_items(deps, ticker)
            if not queue_ids:
                queue_ids = {int(item["item_id"]) for item in current_items if int(item.get("item_id") or 0) not in seen_queue_ids}
            new_items = _items_by_ids(current_items, queue_ids)
            seen_queue_ids.update(queue_ids)
            previews = _build_item_previews(ticker, new_items, deps=deps)
            packet = write_profile_review_packet(
                ticker=ticker,
                run_stamp=run_stamp,
                output_dir=Path(args.output_dir),
                run_payload=run_payload,
                queue_items=new_items,
                previews=previews,
                run_started_at=result.get("run_started_at"),
                data_freshness=result.get("data_freshness"),
                ciq_info=result.get("ciq"),
            )
            result["profile_review_packets"].append(_jsonable(packet))
            io.write(f"Review packet: {packet.path}")
            if not new_items:
                io.write("No new PM Decision Queue items for this profile.")
                if not args.non_interactive:
                    io.ask("Press Enter after reviewing this profile's evidence summary: ")
                continue
            review = review_queue_items(
                ticker,
                new_items,
                deps=deps,
                io=io,
                non_interactive=args.non_interactive,
                previews=previews,
            )
            result["queue_decisions"].extend(review.decisions)
            if review.applied_count:
                io.write("Rebuilding deterministic model after approved changes...")
                latest_model = build_model_snapshot(ticker, deps=deps)
                result["latest_model"] = latest_model
                result["model_snapshots"].append({"label": f"after_{profile}", "model": latest_model})
                result["errors"].extend(latest_model.get("errors") or [])

    io.write("Building Analyst Prep Pack...")
    prep_pack = _jsonable(deps.build_prep_pack(ticker))
    prep_markdown = deps.render_prep_markdown(prep_pack)
    result["analyst_prep"] = prep_pack
    if args.export_xlsx:
        try:
            current_workup = {
                "ticker": ticker,
                "run_stamp": run_stamp,
                "analyst_prep": result.get("analyst_prep"),
                "queue_decisions": result.get("queue_decisions") or [],
                "latest_model": result.get("latest_model"),
            }
            try:
                export_result = deps.export_xlsx(ticker, current_workup)  # type: ignore[call-arg]
            except TypeError:
                # Injected/legacy exporters that take only the ticker.
                export_result = deps.export_xlsx(ticker)  # type: ignore[misc]
            result["excel_export"] = _jsonable(export_result)
        except Exception as exc:
            result["excel_export"] = {"error": str(exc)}
            result["errors"].append({"step": "export_xlsx", "message": str(exc)})
    try:
        result["data_freshness"] = deps.collect_freshness(ticker)
    except Exception as exc:
        result["data_freshness"] = {"error": str(exc)}

    artifacts = write_artifacts(
        result,
        output_dir=Path(args.output_dir),
        friction_log_dir=Path(args.friction_log_dir),
        prep_markdown=prep_markdown,
    )
    result["artifacts"] = artifacts
    Path(artifacts["json"]).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    io.write("")
    io.write("Guided ticker workup complete.")
    for label, path in artifacts.items():
        io.write(f"- {label}: {path}")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a guided PM-driven full ticker workup.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--profiles", nargs="*", default=list(DEFAULT_PROFILES))
    parser.add_argument("--agent-mode", choices=("live", "heuristic"), default="live")
    parser.add_argument("--isolated-db", action="store_true")
    parser.add_argument("--output-dir", default=str(GUIDED_OUTPUT_DIR))
    parser.add_argument("--friction-log-dir", default=str(FRICTION_LOG_DIR))
    parser.add_argument("--skip-ciq-stage", action="store_true")
    parser.add_argument("--skip-edgar-prefetch", action="store_true")
    parser.add_argument("--edgar-cache-only", action="store_true")
    parser.add_argument("--market-cache-only", action="store_true")
    parser.add_argument("--edgar-summary-only", action="store_true")
    parser.add_argument("--edgar-forms", nargs="+", default=["10-K", "10-Q", "8-K"])
    parser.add_argument("--edgar-limit", type=int, default=4)
    parser.add_argument("--ciq-symbol")
    parser.add_argument("--exchange")
    parser.add_argument("--as-of-date")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--ciq-template", default=str(ROOT / "ciq" / "templates" / "ciq_cleandata.xlsx"))
    parser.add_argument("--ciq-input-json", default=str(ROOT / "ciq" / "templates" / "financials_input.json"))
    parser.add_argument("--ciq-folder", default=str(ROOT / "data" / "exports"))
    parser.add_argument("--use-openrouter-free", action="store_true")
    parser.add_argument("--openrouter-model", default=os.getenv("OPENROUTER_FREE_MODEL", "openrouter/free"))
    parser.add_argument("--openrouter-fallback-models", nargs="*", default=[])
    parser.add_argument("--export-xlsx", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="For smoke tests only: stage/check data and skip queue decisions; never auto-approves.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_guided_workup(args)
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
