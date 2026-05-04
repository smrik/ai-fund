from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from db.schema import create_tables, get_connection
from db.ticker_dossier import upsert_ticker_dossier_snapshot
from src.stage_04_pipeline.batch_funnel import load_saved_watchlist
from src.stage_04_pipeline.comps_dashboard import build_comps_dashboard_view
from src.stage_04_pipeline.dcf_audit import build_dcf_audit_view
from src.stage_04_pipeline.dossier_view import build_publishable_memo_context, build_research_board_view
from src.stage_04_pipeline.override_workbench import build_override_workbench
from src.stage_04_pipeline.report_archive import list_report_snapshots, load_report_snapshot
from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload, ticker_dossier_to_payload
from src.stage_04_pipeline.wacc_workbench import build_wacc_workbench

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_ROOT = PROJECT_ROOT / "data" / "exports" / "generated"
TICKER_EXPORT_TEMPLATE = PROJECT_ROOT / "templates" / "ticker_review.xlsx"
TITLE_FONT = Font(name="Calibri", size=14, bold=True, color="1F3864")
SECTION_FONT = Font(name="Calibri", size=11, bold=True)
HEADER_FONT = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(fill_type="solid", start_color="1F3864", end_color="1F3864")
SECTION_FILL = PatternFill(fill_type="solid", start_color="D9E1F2", end_color="D9E1F2")
SUBTLE_FILL = PatternFill(fill_type="solid", start_color="F5F7FA", end_color="F5F7FA")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_ticker(value: str) -> str:
    ticker = (value or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def _ensure_schema(conn) -> None:
    create_tables(conn)


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _artifact_row(
    *,
    artifact_key: str,
    artifact_role: str,
    title: str,
    path: Path,
    mime_type: str,
    is_primary: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_key": artifact_key,
        "artifact_role": artifact_role,
        "title": title,
        "path": Path(path),
        "mime_type": mime_type,
        "is_primary": bool(is_primary),
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
    }


def _safe_sheet_title(value: str | None) -> str:
    return str(value or "").strip()


def _normalise_comps_analysis(comps: dict[str, Any] | None) -> dict[str, Any]:
    comps = dict(comps or {})
    target_vs_peers = comps.get("target_vs_peers") or {"target": {}, "peer_medians": {}, "deltas": {}}
    comparison_summary = comps.get("comparison_summary") or [
        {
            "metric": key,
            "label": key.replace("_", " ").title(),
            "target": value,
            "peer_median": (target_vs_peers.get("peer_medians") or {}).get(key),
            "delta": (target_vs_peers.get("deltas") or {}).get(key),
        }
        for key, value in (target_vs_peers.get("target") or {}).items()
    ]
    peer_table = comps.get("peer_table") or [
        {
            **row,
            "display_name": row.get("display_name") or row.get("name") or row.get("ticker"),
        }
        for row in comps.get("peers") or []
    ]
    return {
        "primary_metric": comps.get("primary_metric"),
        "peer_counts": comps.get("peer_counts") or {"raw": len(peer_table), "clean": len(peer_table)},
        "valuation_range": comps.get("valuation_range") or {},
        "valuation_by_metric_rows": comps.get("valuation_by_metric_rows") or [],
        "comparison_summary": comparison_summary,
        "peer_table": peer_table,
        "metric_status_rows": comps.get("metric_status_rows") or [],
        "football_field": comps.get("football_field") or {"ranges": [], "markers": [], "range_min": None, "range_max": None},
        "historical_multiples_summary": comps.get("historical_multiples_summary") or {"available": False, "metrics": {}},
        "operating_context": comps.get("operating_context") or {"target": {}, "peer_medians": {}, "peer_count": 0},
        "support_data_quality": comps.get("support_data_quality")
        or {
            "target_missing_fields": [],
            "peer_coverage": {},
            "valuation_metric_count": len(comps.get("valuation_by_metric_rows") or []),
            "common_patchups_needed": [],
        },
        "audit_flags": list(comps.get("audit_flags") or []),
        "notes": comps.get("notes") or "",
        "source_lineage": comps.get("source_lineage") or {},
        "similarity_method": comps.get("similarity_method"),
        "similarity_model": comps.get("similarity_model"),
        "weighting_formula": comps.get("weighting_formula"),
    }


def _attach_ticker_dossier(
    payload: dict[str, Any],
    *,
    source_mode: str,
    snapshot_id: int | None = None,
) -> dict[str, Any]:
    dossier = build_ticker_dossier_from_export_payload(
        payload,
        source_mode=source_mode,
        snapshot_id=snapshot_id,
    )
    payload["ticker_dossier"] = ticker_dossier_to_payload(dossier)
    return payload


def _persist_attached_ticker_dossier(payload: dict[str, Any]) -> None:
    dossier_payload = payload.get("ticker_dossier")
    if not isinstance(dossier_payload, dict):
        return
    upsert_ticker_dossier_snapshot(dossier_payload, connection_factory=get_connection)


def _clear_sheet(ws) -> None:
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))
    for row in ws.iter_rows():
        for cell in row:
            cell.value = None
            cell.number_format = "General"
            cell.font = Font(name="Calibri", size=10)
            cell.fill = PatternFill(fill_type=None)
            cell.alignment = Alignment(horizontal="general", vertical="bottom")


def _style_section_title(ws, cell_ref: str, title: str) -> None:
    ws[cell_ref] = title
    ws[cell_ref].font = SECTION_FONT
    ws[cell_ref].fill = SECTION_FILL


def _write_table(ws, start_row: int, headers: list[str], rows: list[list[Any]]) -> int:
    for idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    data_row = start_row + 1
    for row_values in rows:
        for idx, value in enumerate(row_values, start=1):
            cell = ws.cell(row=data_row, column=idx, value=value)
            cell.alignment = Alignment(horizontal="left", vertical="center")
        data_row += 1
    return data_row


def _autosize_columns(ws, widths: dict[int, float]) -> None:
    for idx, width in widths.items():
        ws.column_dimensions[get_column_letter(idx)].width = width


def _populate_comps_sheet(workbook, ticker: str, company_name: str | None, market: dict[str, Any], comps_analysis: dict[str, Any]) -> None:
    ws = workbook["Comps"] if "Comps" in workbook.sheetnames else workbook.create_sheet("Comps")
    _clear_sheet(ws)

    source_lineage = comps_analysis.get("source_lineage") or {}
    valuation_range = comps_analysis.get("valuation_range") or {}
    peer_counts = comps_analysis.get("peer_counts") or {}

    ws["A1"] = f"{ticker} - Comparable Companies Appendix"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:H1")

    metadata_pairs = [
        ("Company", company_name or ticker),
        ("As Of", source_lineage.get("as_of_date")),
        ("Source File", source_lineage.get("source_file")),
        ("Current Price", (market or {}).get("price")),
    ]
    for offset, (label, value) in enumerate(metadata_pairs):
        row = 2 + offset // 2
        col = 1 + (offset % 2) * 3
        ws.cell(row=row, column=col, value=label).font = SECTION_FONT
        ws.cell(row=row, column=col + 1, value=value)

    _style_section_title(ws, "A4", "Headline Valuation")
    headline_rows = [
        ["Primary Metric", comps_analysis.get("primary_metric")],
        ["Blended Base IV", valuation_range.get("blended_base")],
        ["Bear / Base / Bull", f"{valuation_range.get('bear')} / {valuation_range.get('base')} / {valuation_range.get('bull')}"],
        ["Peer Counts (raw / clean)", f"{peer_counts.get('raw')} / {peer_counts.get('clean')}"],
        ["Similarity Method", comps_analysis.get("similarity_method") or "market_cap_only"],
        ["Weighting Formula", comps_analysis.get("weighting_formula") or "market_cap_proximity_only"],
    ]
    for row_idx, (label, value) in enumerate(headline_rows, start=5):
        ws.cell(row=row_idx, column=1, value=label).fill = SUBTLE_FILL
        ws.cell(row=row_idx, column=1).font = SECTION_FONT
        ws.cell(row=row_idx, column=2, value=value)

    next_row = 12
    _style_section_title(ws, f"A{next_row}", "Valuation By Metric")
    next_row = _write_table(
        ws,
        next_row + 1,
        [
            "Metric",
            "Target Multiple",
            "Peer Median",
            "Bear Multiple",
            "Base Multiple",
            "Bull Multiple",
            "Bear IV",
            "Base IV",
            "Bull IV",
            "N Raw",
            "N Clean",
            "Primary",
        ],
        [
            [
                row.get("label"),
                row.get("target_multiple"),
                row.get("peer_median_multiple"),
                row.get("bear_multiple"),
                row.get("base_multiple"),
                row.get("bull_multiple"),
                row.get("bear_iv"),
                row.get("base_iv"),
                row.get("bull_iv"),
                row.get("n_raw"),
                row.get("n_clean"),
                "Yes" if row.get("is_primary") else "",
            ]
            for row in comps_analysis.get("valuation_by_metric_rows") or []
        ],
    )

    next_row += 1
    _style_section_title(ws, f"A{next_row}", "Target Vs Peer Benchmarks")
    next_row = _write_table(
        ws,
        next_row + 1,
        ["Metric", "Target", "Peer Median", "Delta"],
        [
            [row.get("label"), row.get("target"), row.get("peer_median"), row.get("delta")]
            for row in comps_analysis.get("comparison_summary") or []
        ],
    )

    next_row += 1
    _style_section_title(ws, f"A{next_row}", "Peer Table")
    _write_table(
        ws,
        next_row + 1,
        [
            "Ticker",
            "Company",
            "Similarity Score",
            "Model Weight",
            "Revenue LTM",
            "EBITDA LTM",
            "EBIT LTM",
            "Revenue Growth",
            "EBIT Margin",
            "Net Debt / EBITDA",
            "TEV / EBITDA LTM",
            "TEV / EBIT LTM",
            "P / E LTM",
        ],
        [
            [
                row.get("ticker"),
                row.get("display_name"),
                row.get("similarity_score"),
                row.get("model_weight"),
                row.get("revenue_ltm_mm"),
                row.get("ebitda_ltm_mm"),
                row.get("ebit_ltm_mm"),
                row.get("revenue_growth"),
                row.get("ebit_margin"),
                row.get("net_debt_to_ebitda"),
                row.get("tev_ebitda_ltm"),
                row.get("tev_ebit_ltm"),
                row.get("pe_ltm"),
            ]
            for row in comps_analysis.get("peer_table") or []
        ],
    )
    _autosize_columns(ws, {1: 24, 2: 28, 3: 14, 4: 14, 5: 14, 6: 14, 7: 18, 8: 16, 9: 14, 10: 12, 11: 12, 12: 12})


def _populate_comps_diagnostics_sheet(workbook, ticker: str, comps_analysis: dict[str, Any]) -> None:
    if "Comps Diagnostics" not in workbook.sheetnames:
        comps_index = workbook.sheetnames.index("Comps") + 1 if "Comps" in workbook.sheetnames else len(workbook.sheetnames)
        workbook.create_sheet("Comps Diagnostics", comps_index)
    ws = workbook["Comps Diagnostics"]
    _clear_sheet(ws)

    ws["A1"] = f"{ticker} - Comps Diagnostics"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:F1")

    _style_section_title(ws, "A4", "Audit Flags")
    audit_flags = list(comps_analysis.get("audit_flags") or []) or ["None"]
    for idx, flag in enumerate(audit_flags, start=5):
        ws.cell(row=idx, column=1, value=flag)

    notes_row = 5 + len(audit_flags) + 1
    ws.cell(row=notes_row, column=1, value="Notes").font = SECTION_FONT
    ws.cell(row=notes_row, column=2, value=comps_analysis.get("notes"))

    next_row = notes_row + 2
    _style_section_title(ws, f"A{next_row}", "Metric Status")
    next_row = _write_table(
        ws,
        next_row + 1,
        ["Ticker", "Company", "Metric", "Label", "Raw Multiple", "Status"],
        [
            [
                row.get("ticker"),
                row.get("display_name"),
                row.get("metric"),
                row.get("label"),
                row.get("raw_multiple"),
                row.get("status"),
            ]
            for row in comps_analysis.get("metric_status_rows") or []
        ],
    )

    next_row += 1
    _style_section_title(ws, f"A{next_row}", "Football Field")
    next_row = _write_table(
        ws,
        next_row + 1,
        ["Label", "Bear", "Base", "Bull"],
        [
            [row.get("label"), row.get("bear"), row.get("base"), row.get("bull")]
            for row in (comps_analysis.get("football_field") or {}).get("ranges") or []
        ],
    )

    next_row += 1
    _style_section_title(ws, f"A{next_row}", "Historical Multiples Summary")
    metrics = (comps_analysis.get("historical_multiples_summary") or {}).get("metrics") or {}
    _write_table(
        ws,
        next_row + 1,
        ["Metric", "Current", "Median", "P25", "P75", "Current Percentile"],
        [
            [
                metric,
                payload.get("current"),
                (payload.get("summary") or {}).get("median"),
                (payload.get("summary") or {}).get("p25"),
                (payload.get("summary") or {}).get("p75"),
                (payload.get("summary") or {}).get("current_percentile"),
            ]
            for metric, payload in metrics.items()
        ],
    )
    _autosize_columns(ws, {1: 18, 2: 24, 3: 18, 4: 18, 5: 18, 6: 18})


def _copy_public_artifacts(artifacts: list[dict[str, Any]], bundle_dir: Path) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    assets_dir = bundle_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        if artifact.get("path_mode") != "absolute":
            continue
        source_path = Path(str(artifact.get("path_value") or ""))
        if not source_path.exists() or not source_path.is_file():
            continue
        target_path = assets_dir / source_path.name
        shutil.copy2(source_path, target_path)
        copied.append(
            _artifact_row(
                artifact_key=str(artifact.get("artifact_key") or target_path.stem),
                artifact_role="sidecar_asset",
                title=str(artifact.get("title") or target_path.name),
                path=target_path,
                mime_type="application/octet-stream",
            )
        )
    return copied


def _render_html_report(context: dict[str, Any]) -> str:
    ticker = _coerce_ticker(str(context.get("ticker") or ""))
    company_name = str(context.get("company_name") or ticker)
    source_mode = str(context.get("source_mode") or "loaded_backend_state")
    summary = str(context.get("summary") or "No publishable memo summary is available.")
    valuation = context.get("valuation") or {}
    current_price = valuation.get("current_price") or context.get("current_price") or "—"
    base_iv = valuation.get("iv_base") or valuation.get("base_iv") or context.get("base_iv") or "—"
    expected_iv = valuation.get("expected_iv") or context.get("expected_iv") or "—"
    artifacts = context.get("artifacts") or []
    artifact_links = "".join(
        f"<li>{item.get('title') or item.get('artifact_key')}</li>"
        for item in artifacts
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{ticker} Export</title>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px auto; max-width: 960px; line-height: 1.6; color: #111827; }}
    .hero {{ border-bottom: 1px solid #d1d5db; padding-bottom: 16px; margin-bottom: 24px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 16px 0 24px; }}
    .metric {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px 14px; }}
    .label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; }}
    .value {{ font-size: 1.2rem; font-weight: 700; margin-top: 4px; }}
    .summary {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
  <section class="hero">
    <p>{source_mode}</p>
    <h1>{ticker} - {company_name}</h1>
  </section>
  <section class="metrics">
    <article class="metric"><div class="label">Current Price</div><div class="value">{current_price}</div></article>
    <article class="metric"><div class="label">Base IV</div><div class="value">{base_iv}</div></article>
    <article class="metric"><div class="label">Expected IV</div><div class="value">{expected_iv}</div></article>
  </section>
  <section>
    <h2>Summary</h2>
    <div class="summary">{summary}</div>
  </section>
  <section>
    <h2>Linked Public Artifacts</h2>
    <ul>{artifact_links or "<li>None</li>"}</ul>
  </section>
</body>
</html>
"""


def stage_power_query_workbook(ticker: str, payload: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    template_path = Path(TICKER_EXPORT_TEMPLATE)
    if not template_path.exists():
        raise FileNotFoundError(f"Ticker export template not found: {template_path}")

    json_path = bundle_dir / f"{_coerce_ticker(ticker)}_latest.json"
    _json_dump(json_path, payload)

    workbook_path = bundle_dir / f"{_coerce_ticker(ticker)}_review.xlsx"
    shutil.copy2(template_path, workbook_path)

    workbook = load_workbook(workbook_path)
    if "Config" not in workbook.sheetnames:
        raise ValueError("Ticker export template must contain a Config sheet")
    workbook["Config"]["B2"] = str(json_path.resolve())
    comps_analysis = _normalise_comps_analysis(payload.get("comps_analysis"))
    _populate_comps_sheet(
        workbook,
        _coerce_ticker(ticker),
        payload.get("company_name"),
        payload.get("market") or {},
        comps_analysis,
    )
    _populate_comps_diagnostics_sheet(
        workbook,
        _coerce_ticker(ticker),
        comps_analysis,
    )
    workbook.save(workbook_path)

    manifest_path = bundle_dir / "manifest.json"
    _json_dump(
        manifest_path,
        {
            "ticker": _coerce_ticker(ticker),
            "format": "xlsx",
            "template": str(template_path),
            "artifacts": ["excel_workbook", "power_query_json"],
        },
    )

    return {
        "primary_path": str(workbook_path),
        "bundle_dir": str(bundle_dir),
        "artifacts": [
            _artifact_row(
                artifact_key="excel_workbook",
                artifact_role="primary",
                title=f"{_coerce_ticker(ticker)} review workbook",
                path=workbook_path,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                is_primary=True,
            ),
            _artifact_row(
                artifact_key="power_query_json",
                artifact_role="sidecar_data",
                title=f"{_coerce_ticker(ticker)} export payload",
                path=json_path,
                mime_type="application/json",
            ),
        ],
    }


def build_html_export_bundle(ticker: str, context: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    html_path = bundle_dir / f"{_coerce_ticker(ticker).lower()}-memo.html"
    context_path = bundle_dir / "context.json"
    manifest_path = bundle_dir / "manifest.json"

    html_path.write_text(_render_html_report(context), encoding="utf-8")
    _json_dump(context_path, context)

    sidecars = _copy_public_artifacts(list(context.get("artifacts") or []), bundle_dir)
    artifacts = [
        _artifact_row(
            artifact_key="html_report",
            artifact_role="primary",
            title=f"{_coerce_ticker(ticker)} memo export",
            path=html_path,
            mime_type="text/html",
            is_primary=True,
        ),
        _artifact_row(
            artifact_key="context_json",
            artifact_role="sidecar_context",
            title="Export context",
            path=context_path,
            mime_type="application/json",
        ),
        *sidecars,
    ]
    _json_dump(
        manifest_path,
        {
            "ticker": _coerce_ticker(ticker),
            "format": "html",
            "artifacts": [
                {
                    "artifact_key": artifact["artifact_key"],
                    "title": artifact["title"],
                    "path": str(Path(artifact["path"]).resolve()),
                }
                for artifact in artifacts
            ],
        },
    )
    return {
        "primary_path": str(html_path),
        "bundle_dir": str(bundle_dir),
        "artifacts": artifacts,
    }


def _export_row_from_db(row: Any) -> dict[str, Any]:
    return {
        "export_id": row["export_id"],
        "scope": row["scope"],
        "ticker": row["ticker"],
        "status": row["status"],
        "export_format": row["export_format"],
        "source_mode": row["source_mode"],
        "template_strategy": row["template_strategy"],
        "title": row["title"],
        "bundle_dir": row["bundle_dir"],
        "primary_artifact_key": row["primary_artifact_key"],
        "created_by": row["created_by"],
        "snapshot_id": row["snapshot_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def register_export_bundle(
    *,
    scope: str,
    export_format: str,
    source_mode: str,
    template_strategy: str,
    bundle_dir: Path,
    primary_artifact_key: str,
    artifacts: list[dict[str, Any]],
    ticker: str | None = None,
    created_by: str = "api",
    title: str | None = None,
    snapshot_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    export_id = uuid4().hex
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    ticker_value = _coerce_ticker(ticker) if ticker else None
    now = _now()

    with get_connection() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO generated_exports (
                export_id, scope, ticker, status, export_format, source_mode,
                template_strategy, title, bundle_dir, primary_artifact_key,
                created_by, snapshot_id, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                export_id,
                scope,
                ticker_value,
                "completed",
                export_format,
                source_mode,
                template_strategy,
                title or f"{scope} {export_format} export",
                str(bundle_dir.resolve()),
                primary_artifact_key,
                created_by,
                snapshot_id,
                now,
                now,
                json.dumps(metadata or {}, sort_keys=True),
            ],
        )
        for artifact in artifacts:
            path = Path(artifact["path"])
            size_bytes = path.stat().st_size if path.exists() and path.is_file() else None
            conn.execute(
                """
                INSERT INTO generated_export_artifacts (
                    export_id, artifact_key, artifact_role, title, path,
                    mime_type, size_bytes, is_primary, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    export_id,
                    artifact["artifact_key"],
                    artifact["artifact_role"],
                    artifact["title"],
                    str(path.resolve()),
                    artifact["mime_type"],
                    size_bytes,
                    1 if artifact.get("is_primary") else 0,
                    now,
                    artifact.get("metadata_json") or "{}",
                ],
            )
        conn.commit()
    return load_export(export_id) or {"export_id": export_id}


def list_exports(*, ticker: str | None = None, scope: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    query = [
        "SELECT * FROM generated_exports",
        "WHERE 1=1",
    ]
    params: list[Any] = []
    if ticker:
        query.append("AND ticker = ?")
        params.append(_coerce_ticker(ticker))
    if scope:
        query.append("AND scope = ?")
        params.append(scope)
    query.append("ORDER BY created_at DESC LIMIT ?")
    params.append(max(int(limit), 1))

    with get_connection() as conn:
        _ensure_schema(conn)
        rows = conn.execute(" ".join(query), params).fetchall()
    return [load_export(row["export_id"]) or _export_row_from_db(row) for row in rows]


def load_export(export_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM generated_exports WHERE export_id = ? LIMIT 1",
            [export_id],
        ).fetchone()
        if row is None:
            return None
        artifacts = conn.execute(
            """
            SELECT * FROM generated_export_artifacts
            WHERE export_id = ?
            ORDER BY is_primary DESC, artifact_key ASC
            """,
            [export_id],
        ).fetchall()
    payload = _export_row_from_db(row)
    payload["artifacts"] = [
        {
            "artifact_key": artifact["artifact_key"],
            "artifact_role": artifact["artifact_role"],
            "title": artifact["title"],
            "path": artifact["path"],
            "mime_type": artifact["mime_type"],
            "size_bytes": artifact["size_bytes"],
            "is_primary": bool(artifact["is_primary"]),
            "metadata": json.loads(artifact["metadata_json"] or "{}"),
        }
        for artifact in artifacts
    ]
    return payload


def resolve_export_artifact_path(export_id: str, artifact_key: str | None = None) -> Path:
    payload = load_export(export_id)
    if payload is None:
        raise FileNotFoundError(f"Unknown export id: {export_id}")
    if artifact_key is None:
        artifact_key = payload.get("primary_artifact_key")
    for artifact in payload.get("artifacts") or []:
        if artifact["artifact_key"] == artifact_key:
            return Path(str(artifact["path"]))
    raise FileNotFoundError(f"Artifact {artifact_key!r} not found for export {export_id}")


def _build_current_ticker_payload(ticker: str) -> dict[str, Any]:
    ticker = _coerce_ticker(ticker)
    workbench = build_override_workbench(ticker)
    dcf = build_dcf_audit_view(ticker)
    comps = build_comps_dashboard_view(ticker)
    wacc = build_wacc_workbench(ticker, apply_overrides=True)
    research = build_research_board_view(ticker)

    assumption_map = {
        row["field"]: row.get("effective_value")
        for row in workbench.get("fields") or []
    }
    source_lineage = {
        row["field"]: row.get("effective_source")
        for row in workbench.get("fields") or []
        if row.get("effective_source")
    }
    scenario_map = {
        str(row.get("scenario") or "").lower(): {
            "probability": row.get("probability"),
            "iv": row.get("intrinsic_value"),
            "upside_pct": row.get("upside_pct"),
        }
        for row in dcf.get("scenario_summary") or []
        if row.get("scenario")
    }
    comps_target = (comps.get("target_vs_peers") or {}).get("target") or {}
    peer_medians = (comps.get("target_vs_peers") or {}).get("peer_medians") or {}
    payload = {
        "$schema_version": "1.0",
        "generated_at": _now(),
        "ticker": ticker,
        "company_name": workbench.get("company_name") or research.get("company_name") or ticker,
        "sector": workbench.get("sector"),
        "market": {
            "price": workbench.get("current_price"),
            "analyst_target": research.get("analyst_target"),
            "analyst_recommendation": research.get("tracker", {}).get("pm_action"),
            "num_analysts": None,
        },
        "assumptions": {
            "growth_near_pct": assumption_map.get("revenue_growth_near"),
            "growth_mid_pct": assumption_map.get("revenue_growth_mid"),
            "ebit_margin_start_pct": assumption_map.get("ebit_margin_start"),
            "ebit_margin_target_pct": assumption_map.get("ebit_margin_target"),
            "tax_rate_start_pct": assumption_map.get("tax_rate_start"),
            "tax_rate_target_pct": assumption_map.get("tax_rate_target"),
            "capex_pct": assumption_map.get("capex_pct_start"),
            "da_pct": assumption_map.get("da_pct_start"),
            "dso_start": assumption_map.get("dso_start"),
            "dio_start": assumption_map.get("dio_start"),
            "dpo_start": assumption_map.get("dpo_start"),
            "exit_multiple": assumption_map.get("exit_multiple"),
            "net_debt_mm": assumption_map.get("net_debt"),
            "non_operating_assets_mm": assumption_map.get("non_operating_assets"),
            "lease_liabilities_mm": assumption_map.get("lease_liabilities"),
            "minority_interest_mm": assumption_map.get("minority_interest"),
            "preferred_equity_mm": assumption_map.get("preferred_equity"),
            "pension_deficit_mm": assumption_map.get("pension_deficit"),
        },
        "wacc": {
            "wacc": wacc.get("effective_preview", {}).get("wacc"),
            "cost_of_equity": wacc.get("effective_preview", {}).get("cost_of_equity"),
            "equity_weight": wacc.get("effective_preview", {}).get("equity_weight"),
            "debt_weight": wacc.get("effective_preview", {}).get("debt_weight"),
            "method": (wacc.get("current_selection") or {}).get("selected_method"),
        },
        "valuation": {
            "iv_bear": scenario_map.get("bear", {}).get("iv"),
            "iv_base": scenario_map.get("base", {}).get("iv"),
            "iv_bull": scenario_map.get("bull", {}).get("iv"),
            "expected_iv": dcf.get("ev_bridge", {}).get("intrinsic_value_per_share"),
            "base_iv": dcf.get("ev_bridge", {}).get("intrinsic_value_per_share"),
            "current_price": workbench.get("current_price"),
        },
        "scenarios": scenario_map,
        "sensitivity": dcf.get("sensitivity") or {},
        "terminal": dcf.get("terminal_bridge") or {},
        "health_flags": dcf.get("health_flags") or {},
        "forecast_bridge": dcf.get("forecast_bridge") or [],
        "source_lineage": source_lineage,
        "ciq_lineage": {
            "snapshot_source_file": (comps.get("source_lineage") or {}).get("source_file"),
            "snapshot_as_of_date": (comps.get("source_lineage") or {}).get("as_of_date"),
            "peer_count": (comps.get("peer_counts") or {}).get("clean"),
        },
        "comps_detail": {
            "target": comps_target,
            "peers": comps.get("peers") or [],
            "medians": peer_medians,
        },
        "comps_analysis": _normalise_comps_analysis(comps),
        "research": research,
    }
    return _attach_ticker_dossier(payload, source_mode="loaded_backend_state")


def _build_snapshot_ticker_payload(ticker: str) -> tuple[dict[str, Any], int]:
    ticker = _coerce_ticker(ticker)
    snapshots = list_report_snapshots(ticker, limit=1)
    if not snapshots:
        raise FileNotFoundError(f"No archived snapshot found for {ticker}")
    snapshot_id = int(snapshots[0]["id"])
    snapshot = load_report_snapshot(snapshot_id) or {}
    memo = snapshot.get("memo") or {}
    dashboard_snapshot = snapshot.get("dashboard_snapshot") or {}
    dcf = dashboard_snapshot.get("dcf_audit") or {}
    comps = dashboard_snapshot.get("comps_view") or {}
    payload = {
            "$schema_version": "1.0",
            "generated_at": _now(),
            "ticker": ticker,
            "company_name": snapshot.get("company_name") or memo.get("company_name") or ticker,
            "sector": snapshot.get("sector") or memo.get("sector"),
            "market": {
                "price": snapshot.get("current_price"),
                "analyst_target": None,
                "analyst_recommendation": snapshot.get("action"),
                "num_analysts": None,
            },
            "assumptions": {},
            "wacc": {},
            "valuation": {
                "iv_bear": memo.get("valuation", {}).get("bear"),
                "iv_base": memo.get("valuation", {}).get("base"),
                "iv_bull": memo.get("valuation", {}).get("bull"),
                "expected_iv": memo.get("valuation", {}).get("base"),
                "base_iv": snapshot.get("base_iv"),
                "current_price": snapshot.get("current_price"),
            },
            "scenarios": {
                str(row.get("scenario") or "").lower(): {
                    "probability": row.get("probability"),
                    "iv": row.get("intrinsic_value"),
                    "upside_pct": row.get("upside_pct"),
                }
                for row in dcf.get("scenario_summary") or []
                if row.get("scenario")
            },
            "sensitivity": dcf.get("sensitivity") or {},
            "terminal": dcf.get("terminal_bridge") or {},
            "health_flags": dcf.get("health_flags") or {},
            "forecast_bridge": dcf.get("forecast_bridge") or [],
            "source_lineage": {},
            "ciq_lineage": {
                "snapshot_source_file": (comps.get("source_lineage") or {}).get("source_file"),
                "snapshot_as_of_date": (comps.get("source_lineage") or {}).get("as_of_date"),
                "peer_count": (comps.get("peer_counts") or {}).get("clean"),
            },
            "comps_detail": {
                "target": (comps.get("target_vs_peers") or {}).get("target") or {},
                "peers": comps.get("peers") or [],
                "medians": (comps.get("target_vs_peers") or {}).get("peer_medians") or {},
            },
            "comps_analysis": _normalise_comps_analysis(comps),
            "snapshot": snapshot,
        }
    return (
        _attach_ticker_dossier(payload, source_mode="latest_snapshot", snapshot_id=snapshot_id),
        snapshot_id,
    )


def _build_html_context(ticker: str, source_mode: str) -> tuple[dict[str, Any], int | None]:
    ticker = _coerce_ticker(ticker)
    if source_mode == "latest_snapshot":
        payload, snapshot_id = _build_snapshot_ticker_payload(ticker)
        memo = payload.get("snapshot", {}).get("memo") or {}
        publishable = build_publishable_memo_context(ticker)
        return (
            {
                "ticker": ticker,
                "company_name": payload.get("company_name"),
                "source_mode": source_mode,
                "current_price": payload.get("valuation", {}).get("current_price"),
                "base_iv": payload.get("valuation", {}).get("iv_base"),
                "expected_iv": payload.get("valuation", {}).get("expected_iv"),
                "summary": publishable.get("memo_content") or memo.get("one_liner") or memo.get("variant_thesis_prompt") or "",
                "valuation": payload.get("valuation") or {},
                "artifacts": publishable.get("artifacts") or [],
                "ticker_dossier": payload.get("ticker_dossier"),
            },
            snapshot_id,
        )
    payload = _build_current_ticker_payload(ticker)
    publishable = build_publishable_memo_context(ticker)
    research = payload.get("research") or {}
    return (
        {
            "ticker": ticker,
            "company_name": payload.get("company_name"),
            "source_mode": source_mode,
            "current_price": payload.get("valuation", {}).get("current_price"),
            "base_iv": payload.get("valuation", {}).get("iv_base"),
            "expected_iv": payload.get("valuation", {}).get("expected_iv"),
            "summary": publishable.get("memo_content") or research.get("publishable_memo_preview") or "",
            "valuation": payload.get("valuation") or {},
            "artifacts": publishable.get("artifacts") or [],
            "ticker_dossier": payload.get("ticker_dossier"),
        },
        None,
    )


def _ticker_bundle_dir(ticker: str, export_format: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return EXPORT_ROOT / "ticker" / _coerce_ticker(ticker) / f"{stamp}-{export_format}-{uuid4().hex[:8]}"


def _watchlist_bundle_dir(export_format: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return EXPORT_ROOT / "watchlist" / f"{stamp}-{export_format}-{uuid4().hex[:8]}"


def run_ticker_export(
    *,
    ticker: str,
    export_format: str,
    source_mode: str,
    template_strategy: str | None = None,
    created_by: str = "api",
) -> dict[str, Any]:
    ticker = _coerce_ticker(ticker)
    if export_format == "xlsx":
        snapshot_id = None
        if source_mode == "latest_snapshot":
            payload, snapshot_id = _build_snapshot_ticker_payload(ticker)
        else:
            payload = _build_current_ticker_payload(ticker)
        _persist_attached_ticker_dossier(payload)
        bundle_dir = _ticker_bundle_dir(ticker, export_format)
        staged = stage_power_query_workbook(ticker, payload, bundle_dir)
        return register_export_bundle(
            scope="ticker",
            export_format="xlsx",
            source_mode=source_mode,
            template_strategy=template_strategy or "power_query",
            ticker=ticker,
            created_by=created_by,
            title=f"{ticker} Excel export",
            bundle_dir=bundle_dir,
            primary_artifact_key="excel_workbook",
            artifacts=staged["artifacts"],
            snapshot_id=snapshot_id,
            metadata={"source_label": source_mode},
        )

    if export_format == "html":
        context, snapshot_id = _build_html_context(ticker, source_mode)
        _persist_attached_ticker_dossier(context)
        bundle_dir = _ticker_bundle_dir(ticker, export_format)
        staged = build_html_export_bundle(ticker, context, bundle_dir)
        return register_export_bundle(
            scope="ticker",
            export_format="html",
            source_mode=source_mode,
            template_strategy=template_strategy or "html_bundle",
            ticker=ticker,
            created_by=created_by,
            title=f"{ticker} HTML export",
            bundle_dir=bundle_dir,
            primary_artifact_key="html_report",
            artifacts=staged["artifacts"],
            snapshot_id=snapshot_id,
            metadata={"source_label": source_mode},
        )

    raise ValueError(f"Unsupported export format: {export_format}")


def _build_watchlist_html_bundle(rows: list[dict[str, Any]], bundle_dir: Path) -> dict[str, Any]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    html_path = bundle_dir / "watchlist-summary.html"
    json_path = bundle_dir / "watchlist.json"
    html_rows = "".join(
        f"<tr><td>{row.get('ticker') or ''}</td><td>{row.get('company_name') or ''}</td><td>{row.get('expected_upside_pct') or row.get('upside_base_pct') or '—'}</td></tr>"
        for row in rows[:25]
    )
    html_path.write_text(
        "<html><body><h1>Watchlist Export</h1><table><tr><th>Ticker</th><th>Company</th><th>Upside</th></tr>"
        + html_rows
        + "</table></body></html>",
        encoding="utf-8",
    )
    _json_dump(json_path, rows)
    return {
        "artifacts": [
            _artifact_row(
                artifact_key="html_report",
                artifact_role="primary",
                title="Watchlist HTML summary",
                path=html_path,
                mime_type="text/html",
                is_primary=True,
            ),
            _artifact_row(
                artifact_key="watchlist_json",
                artifact_role="sidecar_data",
                title="Watchlist rows",
                path=json_path,
                mime_type="application/json",
            ),
        ]
    }


def run_watchlist_export(
    *,
    export_format: str,
    source_mode: str,
    shortlist_size: int = 10,
    created_by: str = "api",
) -> dict[str, Any]:
    if source_mode != "saved_watchlist":
        raise ValueError("Watchlist exports currently support only saved_watchlist source mode")
    view = load_saved_watchlist(shortlist_size=shortlist_size)
    rows = list(view.get("rows") or [])
    bundle_dir = _watchlist_bundle_dir(export_format)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    if export_format == "html":
        staged = _build_watchlist_html_bundle(rows, bundle_dir)
        return register_export_bundle(
            scope="batch",
            export_format="html",
            source_mode=source_mode,
            template_strategy="python_generated",
            created_by=created_by,
            title="Watchlist HTML export",
            bundle_dir=bundle_dir,
            primary_artifact_key="html_report",
            artifacts=staged["artifacts"],
            metadata={"shortlist_size": shortlist_size},
        )

    if export_format == "xlsx":
        from src.stage_02_valuation.batch_runner import export_to_excel

        workbook_path = bundle_dir / "watchlist-export.xlsx"
        export_to_excel(rows, workbook_path)
        staged = {
            "artifacts": [
                _artifact_row(
                    artifact_key="excel_workbook",
                    artifact_role="primary",
                    title="Watchlist workbook",
                    path=workbook_path,
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    is_primary=True,
                )
            ]
        }
        return register_export_bundle(
            scope="batch",
            export_format="xlsx",
            source_mode=source_mode,
            template_strategy="python_generated",
            created_by=created_by,
            title="Watchlist Excel export",
            bundle_dir=bundle_dir,
            primary_artifact_key="excel_workbook",
            artifacts=staged["artifacts"],
            metadata={"shortlist_size": shortlist_size},
        )

    raise ValueError(f"Unsupported export format: {export_format}")


def list_saved_exports(*, ticker: str | None = None, scope: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    return list_exports(ticker=ticker, scope=scope, limit=limit)


def load_saved_export(export_id: str) -> dict[str, Any] | None:
    return load_export(export_id)


def resolve_export_download_path(export_id: str, artifact_key: str | None = None) -> Path:
    return resolve_export_artifact_path(export_id, artifact_key=artifact_key)
