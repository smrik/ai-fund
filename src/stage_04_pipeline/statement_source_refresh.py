"""Explicit source refresh and reconciliation for statement-ledger readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping

from db.schema import create_tables, get_connection


_TERMINAL_STATUSES = ("decision_grade", "provisional", "blocked")


@dataclass(frozen=True, slots=True)
class StatementSourceRefreshResult:
    request_index: int
    ticker: str
    status: str
    reason_codes: tuple[str, ...]
    errors: tuple[str, ...]
    xbrl_status: str | None
    xbrl_inserted_count: int
    xbrl_manifest_ids: tuple[str, ...]
    ciq_results: tuple[dict[str, Any], ...]
    reconciliation_run_hash: str | None
    reconciliation_as_of_date: str | None
    annual_period_count: int
    ltm_status: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_index": self.request_index,
            "ticker": self.ticker,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "errors": list(self.errors),
            "xbrl_status": self.xbrl_status,
            "xbrl_inserted_count": self.xbrl_inserted_count,
            "xbrl_manifest_ids": list(self.xbrl_manifest_ids),
            "ciq_results": [dict(item) for item in self.ciq_results],
            "reconciliation_run_hash": self.reconciliation_run_hash,
            "reconciliation_as_of_date": self.reconciliation_as_of_date,
            "annual_period_count": self.annual_period_count,
            "ltm_status": self.ltm_status,
        }


@dataclass(frozen=True, slots=True)
class StatementSourceRefreshBatch:
    results: tuple[StatementSourceRefreshResult, ...]

    @property
    def requested_count(self) -> int:
        return len(self.results)

    @property
    def status_counts(self) -> dict[str, int]:
        return {
            status: sum(result.status == status for result in self.results)
            for status in _TERMINAL_STATUSES
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_count": self.requested_count,
            "status_counts": self.status_counts,
            "results": [result.as_dict() for result in self.results],
        }


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _ciq_result_payload(item: Any) -> dict[str, Any]:
    return {
        "file": _value(item, "file"),
        "status": _value(item, "status"),
        "ticker": _value(item, "ticker"),
        "run_id": _value(item, "run_id"),
        "rows_parsed": int(_value(item, "rows_parsed", 0) or 0),
        "error": _value(item, "error"),
    }


def _normalise_tickers(tickers: Iterable[str]) -> list[str]:
    normalised = [str(ticker).strip().upper() for ticker in tickers]
    if not normalised or any(not ticker for ticker in normalised):
        raise ValueError("at least one non-empty ticker is required")
    return normalised


def refresh_statement_sources(
    tickers: Iterable[str],
    *,
    connection: sqlite3.Connection | None = None,
    evidence_cutoff: str | None = None,
    ciq_workbooks: Mapping[str, str | Path] | None = None,
    ciq_folder: str | Path | None = None,
    xbrl_refresh: Callable[..., Any] | None = None,
    ciq_ingest: Callable[..., Any] | None = None,
    reconcile: Callable[..., Any] | None = None,
) -> StatementSourceRefreshBatch:
    """Refresh explicit statement sources and reconcile every requested identity.

    Duplicate requests share source work but retain one terminal result per
    request. CIQ input is never discovered implicitly: callers either provide
    exact ticker-to-workbook paths, one explicit folder, or no CIQ refresh.
    """

    requested = _normalise_tickers(tickers)
    unique_tickers = list(dict.fromkeys(requested))
    if ciq_workbooks and ciq_folder:
        raise ValueError("provide CIQ workbooks or a CIQ folder, not both")
    explicit_workbooks = {
        str(ticker).strip().upper(): Path(path)
        for ticker, path in dict(ciq_workbooks or {}).items()
    }
    unknown_mappings = set(explicit_workbooks) - set(unique_tickers)
    if unknown_mappings:
        raise ValueError(
            "CIQ workbook mappings include unrequested tickers: "
            + ", ".join(sorted(unknown_mappings))
        )

    if xbrl_refresh is None:
        from src.stage_00_data.xbrl_evidence import (
            persist_xbrl_statement_evidence,
        )

        xbrl_refresh = persist_xbrl_statement_evidence
    if ciq_ingest is None:
        from ciq.ingest import ingest_ciq_folder

        ciq_ingest = ingest_ciq_folder
    if reconcile is None:
        from src.stage_04_pipeline.statement_reconciliation_service import (
            reconcile_ticker_statements,
        )

        reconcile = reconcile_ticker_statements

    close_connection = connection is None
    conn = connection or get_connection()
    create_tables(conn)
    state: dict[str, dict[str, Any]] = {
        ticker: {
            "reason_codes": [],
            "errors": [],
            "xbrl_status": None,
            "xbrl_inserted_count": 0,
            "xbrl_manifest_ids": (),
            "ciq_results": [],
            "reconciliation": None,
        }
        for ticker in unique_tickers
    }
    try:
        for ticker in unique_tickers:
            try:
                xbrl = xbrl_refresh(
                    conn,
                    ticker,
                    evidence_cutoff=evidence_cutoff,
                )
                state[ticker]["xbrl_status"] = str(
                    _value(xbrl, "status", "failed")
                )
                state[ticker]["xbrl_inserted_count"] = int(
                    _value(xbrl, "inserted_count", 0) or 0
                )
                state[ticker]["xbrl_manifest_ids"] = tuple(
                    str(item)
                    for item in (_value(xbrl, "manifest_ids", ()) or ())
                )
                if state[ticker]["xbrl_status"] != "completed":
                    state[ticker]["reason_codes"].append(
                        "xbrl_source_incomplete"
                    )
                state[ticker]["errors"].extend(
                    str(error)
                    for error in (_value(xbrl, "errors", ()) or ())
                    if error
                )
            except Exception as exc:
                state[ticker]["reason_codes"].append("xbrl_refresh_failed")
                state[ticker]["errors"].append(str(exc))

        if explicit_workbooks:
            for ticker, workbook in explicit_workbooks.items():
                try:
                    report = ciq_ingest(
                        workbook.parent,
                        as_of_date=evidence_cutoff,
                        workbook_paths=[workbook],
                        connection=conn,
                    )
                    report_results = tuple(
                        _ciq_result_payload(item)
                        for item in (_value(report, "results", ()) or ())
                    )
                    state[ticker]["ciq_results"].extend(report_results)
                    failures = [
                        item
                        for item in report_results
                        if item["status"] == "failed"
                    ]
                    mismatches = [
                        item
                        for item in report_results
                        if item["ticker"]
                        and str(item["ticker"]).upper() != ticker
                    ]
                    if not report_results:
                        state[ticker]["reason_codes"].append(
                            "ciq_ingest_missing_result"
                        )
                        state[ticker]["errors"].append(
                            f"CIQ ingest returned no result for {workbook}"
                        )
                    if failures:
                        state[ticker]["reason_codes"].append(
                            "ciq_ingest_failed"
                        )
                        state[ticker]["errors"].extend(
                            str(item["error"])
                            for item in failures
                            if item["error"]
                        )
                    if mismatches:
                        state[ticker]["reason_codes"].append(
                            "ciq_ticker_mismatch"
                        )
                        state[ticker]["errors"].append(
                            f"CIQ workbook for {ticker} parsed as "
                            f"{mismatches[0]['ticker']}"
                        )
                except Exception as exc:
                    state[ticker]["reason_codes"].append("ciq_ingest_failed")
                    state[ticker]["errors"].append(str(exc))
        elif ciq_folder is not None:
            try:
                report = ciq_ingest(
                    Path(ciq_folder),
                    as_of_date=evidence_cutoff,
                    connection=conn,
                )
                results_by_ticker: dict[str, list[dict[str, Any]]] = {}
                for item in (_value(report, "results", ()) or ()):
                    payload = _ciq_result_payload(item)
                    parsed_ticker = str(payload["ticker"] or "").upper()
                    if parsed_ticker:
                        results_by_ticker.setdefault(parsed_ticker, []).append(
                            payload
                        )
                for ticker in unique_tickers:
                    matched = results_by_ticker.get(ticker, [])
                    state[ticker]["ciq_results"].extend(matched)
                    if not matched:
                        state[ticker]["reason_codes"].append(
                            "ciq_ingest_missing_result"
                        )
                        state[ticker]["errors"].append(
                            f"CIQ folder returned no workbook for {ticker}"
                        )
                    failures = [
                        item for item in matched if item["status"] == "failed"
                    ]
                    if failures:
                        state[ticker]["reason_codes"].append(
                            "ciq_ingest_failed"
                        )
                        state[ticker]["errors"].extend(
                            str(item["error"])
                            for item in failures
                            if item["error"]
                        )
            except Exception as exc:
                for ticker in unique_tickers:
                    state[ticker]["reason_codes"].append("ciq_ingest_failed")
                    state[ticker]["errors"].append(str(exc))

        for ticker in unique_tickers:
            try:
                state[ticker]["reconciliation"] = reconcile(
                    conn,
                    ticker,
                    evidence_cutoff=evidence_cutoff,
                )
            except Exception as exc:
                state[ticker]["reason_codes"].append(
                    "statement_reconciliation_failed"
                )
                state[ticker]["errors"].append(str(exc))

        unique_results: dict[str, StatementSourceRefreshResult] = {}
        for ticker in unique_tickers:
            ticker_state = state[ticker]
            reconciliation = ticker_state["reconciliation"]
            readiness = _value(reconciliation, "readiness")
            readiness_status = str(
                _value(readiness, "status", "blocked")
            )
            reason_codes = [
                *(_value(readiness, "reason_codes", ()) or ()),
                *ticker_state["reason_codes"],
            ]
            reasons = tuple(dict.fromkeys(str(item) for item in reason_codes))
            errors = tuple(
                dict.fromkeys(
                    str(item) for item in ticker_state["errors"] if item
                )
            )
            operational_failure = bool(errors) and any(
                reason.endswith("_failed")
                or reason == "ciq_ticker_mismatch"
                for reason in reasons
            )
            status = "blocked" if operational_failure else readiness_status
            if status == "decision_grade" and reasons:
                status = "provisional"
            unique_results[ticker] = StatementSourceRefreshResult(
                request_index=-1,
                ticker=ticker,
                status=(
                    status if status in _TERMINAL_STATUSES else "blocked"
                ),
                reason_codes=reasons,
                errors=errors,
                xbrl_status=ticker_state["xbrl_status"],
                xbrl_inserted_count=ticker_state[
                    "xbrl_inserted_count"
                ],
                xbrl_manifest_ids=tuple(
                    ticker_state["xbrl_manifest_ids"]
                ),
                ciq_results=tuple(ticker_state["ciq_results"]),
                reconciliation_run_hash=_value(
                    reconciliation,
                    "run_hash",
                ),
                reconciliation_as_of_date=_value(
                    reconciliation,
                    "as_of_date",
                ),
                annual_period_count=int(
                    _value(readiness, "annual_period_count", 0) or 0
                ),
                ltm_status=_value(readiness, "ltm_status"),
            )
    finally:
        if close_connection:
            conn.close()

    expanded = tuple(
        StatementSourceRefreshResult(
            request_index=index,
            ticker=ticker,
            status=unique_results[ticker].status,
            reason_codes=unique_results[ticker].reason_codes,
            errors=unique_results[ticker].errors,
            xbrl_status=unique_results[ticker].xbrl_status,
            xbrl_inserted_count=unique_results[
                ticker
            ].xbrl_inserted_count,
            xbrl_manifest_ids=unique_results[ticker].xbrl_manifest_ids,
            ciq_results=unique_results[ticker].ciq_results,
            reconciliation_run_hash=unique_results[
                ticker
            ].reconciliation_run_hash,
            reconciliation_as_of_date=unique_results[
                ticker
            ].reconciliation_as_of_date,
            annual_period_count=unique_results[
                ticker
            ].annual_period_count,
            ltm_status=unique_results[ticker].ltm_status,
        )
        for index, ticker in enumerate(requested)
    )
    return StatementSourceRefreshBatch(results=expanded)


__all__ = [
    "StatementSourceRefreshBatch",
    "StatementSourceRefreshResult",
    "refresh_statement_sources",
]
