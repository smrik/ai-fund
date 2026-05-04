from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook, load_workbook

from db.schema import create_tables


def _workspace_tempdir(name: str) -> Path:
    root = Path.cwd() / ".tmp-tests" / "export-service"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _temp_conn_factory(db_path: Path):
    def _factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        create_tables(conn)
        return conn

    return _factory


def test_stage_power_query_workbook_copies_template_and_points_json_path(monkeypatch):
    from src.stage_04_pipeline import export_service

    tmp_path = _workspace_tempdir("export-workbook")
    template_path = tmp_path / "ticker_review.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Config"
    ws["A1"] = "Setting"
    ws["B1"] = "Value"
    ws["A2"] = "json_path"
    ws["B2"] = "C:\\placeholder.json"
    wb.create_named_range("json_path", ws, "$B$2")
    wb.save(template_path)

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    monkeypatch.setattr(export_service, "TICKER_EXPORT_TEMPLATE", template_path)

    payload = {"ticker": "IBM", "valuation": {"iv_base": 123.0}}
    result = export_service.stage_power_query_workbook("IBM", payload, bundle_dir)

    workbook_path = Path(result["primary_path"])
    json_path = bundle_dir / "IBM_latest.json"

    assert workbook_path.exists()
    assert json_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["ticker"] == "IBM"

    staged = load_workbook(workbook_path)
    assert staged["Config"]["B2"].value == str(json_path.resolve())
    assert list(staged.defined_names["json_path"].destinations) == [("Config", "$B$2")]
    assert result["artifacts"][0]["artifact_key"] == "excel_workbook"


def test_stage_power_query_workbook_populates_comps_tabs(monkeypatch):
    from src.stage_04_pipeline import export_service

    tmp_path = _workspace_tempdir("export-workbook-comps")
    template_path = tmp_path / "ticker_review.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Config"
    ws["A2"] = "json_path"
    ws["B2"] = "C:\\placeholder.json"
    wb.create_named_range("json_path", ws, "$B$2")
    wb.create_sheet("Comps")
    wb.save(template_path)

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    monkeypatch.setattr(export_service, "TICKER_EXPORT_TEMPLATE", template_path)

    payload = {
        "ticker": "IBM",
        "company_name": "International Business Machines",
        "market": {"price": 260.0},
        "comps_analysis": {
            "primary_metric": "tev_ebitda_ltm",
            "peer_counts": {"raw": 5, "clean": 4},
            "valuation_range": {"bear": 190.0, "base": 202.0, "bull": 216.0, "blended_base": 205.0},
            "valuation_by_metric_rows": [
                {
                    "metric": "tev_ebitda_ltm",
                    "label": "TEV / EBITDA LTM",
                    "target_multiple": 3.0,
                    "peer_median_multiple": 17.0,
                    "bear_multiple": 15.0,
                    "base_multiple": 17.0,
                    "bull_multiple": 19.0,
                    "bear_iv": 190.0,
                    "base_iv": 202.0,
                    "bull_iv": 216.0,
                    "n_raw": 5,
                    "n_clean": 4,
                    "is_primary": True,
                }
            ],
            "comparison_summary": [
                {"metric": "revenue_growth", "label": "Revenue Growth", "target": 0.03, "peer_median": 0.05, "delta": -0.02}
            ],
            "peer_table": [
                {"ticker": "ACN", "display_name": "Accenture", "similarity_score": 0.8, "model_weight": 0.4, "tev_ebitda_ltm": 17.0}
            ],
            "metric_status_rows": [
                {"ticker": "ACN", "metric": "tev_ebitda_ltm", "label": "TEV / EBITDA LTM", "raw_multiple": 17.0, "status": "included"}
            ],
            "football_field": {
                "ranges": [{"label": "TEV / EBITDA LTM", "bear": 190.0, "base": 202.0, "bull": 216.0}],
                "markers": [{"label": "Current Price", "value": 260.0, "type": "spot"}],
            },
            "historical_multiples_summary": {
                "metrics": {"pe_trailing": {"current": 20.0, "summary": {"median": 18.0, "current_percentile": 0.65}}}
            },
            "audit_flags": ["Outliers removed from tev_ebitda_ltm: MSFT"],
            "notes": "primary=tev_ebitda_ltm",
            "source_lineage": {"as_of_date": "2026-03-01", "source_file": "IBM_comps.xlsx"},
        },
    }

    result = export_service.stage_power_query_workbook("IBM", payload, bundle_dir)
    staged = load_workbook(Path(result["primary_path"]))

    assert "Comps Diagnostics" in staged.sheetnames
    assert "IBM" in str(staged["Comps"]["A1"].value)
    assert staged["Comps"]["B5"].value == "tev_ebitda_ltm"
    assert staged["Comps"]["A20"].value == "Peer Table"
    assert staged["Comps Diagnostics"]["A4"].value == "Audit Flags"
    assert staged["Comps Diagnostics"]["A10"].value == "Ticker"


def test_build_html_export_bundle_writes_primary_and_sidecar_assets():
    from src.stage_04_pipeline import export_service

    tmp_path = _workspace_tempdir("export-html")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    public_asset = tmp_path / "chart.png"
    public_asset.write_bytes(b"png")

    context = {
        "ticker": "IBM",
        "company_name": "International Business Machines",
        "source_mode": "latest_snapshot",
        "summary": "Public thesis summary.",
        "artifacts": [
            {
                "artifact_key": "public_chart",
                "title": "DCF Chart",
                "path_mode": "absolute",
                "path_value": str(public_asset),
                "artifact_type": "export_png",
            }
        ],
    }

    result = export_service.build_html_export_bundle("IBM", context, bundle_dir)

    primary_path = Path(result["primary_path"])
    manifest_path = bundle_dir / "manifest.json"
    context_path = bundle_dir / "context.json"
    copied_asset = bundle_dir / "assets" / public_asset.name

    assert primary_path.exists()
    assert "Public thesis summary." in primary_path.read_text(encoding="utf-8")
    assert manifest_path.exists()
    assert context_path.exists()
    assert copied_asset.exists()
    assert {artifact["artifact_key"] for artifact in result["artifacts"]} == {"html_report", "context_json", "public_chart"}


def test_register_export_bundle_persists_export_and_artifacts(monkeypatch):
    from src.stage_04_pipeline import export_service

    tmp_path = _workspace_tempdir("export-registry")
    db_path = tmp_path / "exports.db"
    monkeypatch.setattr(export_service, "get_connection", _temp_conn_factory(db_path))

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    primary = bundle_dir / "report.html"
    primary.write_text("<html>ok</html>", encoding="utf-8")
    sidecar = bundle_dir / "context.json"
    sidecar.write_text("{}", encoding="utf-8")

    export_row = export_service.register_export_bundle(
        scope="ticker",
        export_format="html",
        source_mode="latest_snapshot",
        template_strategy="html_bundle",
        ticker="IBM",
        created_by="api",
        title="IBM Memo Export",
        bundle_dir=bundle_dir,
        primary_artifact_key="html_report",
        artifacts=[
            {
                "artifact_key": "html_report",
                "artifact_role": "primary",
                "title": "IBM Memo",
                "path": primary,
                "mime_type": "text/html",
                "is_primary": True,
            },
            {
                "artifact_key": "context_json",
                "artifact_role": "sidecar",
                "title": "Context",
                "path": sidecar,
                "mime_type": "application/json",
                "is_primary": False,
            },
        ],
        metadata={"source_label": "Latest snapshot"},
    )

    assert export_row["ticker"] == "IBM"
    assert export_row["primary_artifact_key"] == "html_report"

    listed = export_service.list_exports(ticker="IBM")
    loaded = export_service.load_export(export_row["export_id"])

    assert len(listed) == 1
    assert listed[0]["export_id"] == export_row["export_id"]
    assert loaded is not None
    assert loaded["artifacts"][0]["artifact_key"] == "html_report"
    assert Path(export_service.resolve_export_artifact_path(export_row["export_id"])).name == "report.html"
    assert Path(export_service.resolve_export_artifact_path(export_row["export_id"], "context_json")).name == "context.json"


def test_ticker_exports_persist_current_and_snapshot_dossiers(monkeypatch):
    from src.stage_04_pipeline import export_service
    from src.stage_04_pipeline.ticker_dossier import build_ticker_dossier_from_export_payload, ticker_dossier_to_payload

    tmp_path = _workspace_tempdir("export-dossier")
    db_path = tmp_path / "exports.db"
    monkeypatch.setattr(export_service, "get_connection", _temp_conn_factory(db_path))
    monkeypatch.setattr(export_service, "_ticker_bundle_dir", lambda ticker, export_format: tmp_path / f"{ticker}-{export_format}")

    def _payload(source_mode: str, snapshot_id: int | None = None) -> dict:
        payload = {
            "ticker": "IBM",
            "company_name": "International Business Machines",
            "generated_at": "2026-04-30T12:00:00+00:00",
            "market": {"price": 260.0},
            "valuation": {"iv_base": 202.0, "expected_iv": 205.0},
            "ciq_lineage": {"snapshot_as_of_date": "2026-04-30"},
        }
        dossier = build_ticker_dossier_from_export_payload(payload, source_mode=source_mode, snapshot_id=snapshot_id)
        payload["ticker_dossier"] = ticker_dossier_to_payload(dossier)
        return payload

    def _stage_workbook(ticker, payload, bundle_dir):
        bundle_dir.mkdir(parents=True, exist_ok=True)
        primary = bundle_dir / "workbook.xlsx"
        primary.write_bytes(b"xlsx")
        return {
            "artifacts": [
                {
                    "artifact_key": "excel_workbook",
                    "artifact_role": "primary",
                    "title": "Workbook",
                    "path": primary,
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "is_primary": True,
                }
            ]
        }

    def _stage_html(ticker, context, bundle_dir):
        bundle_dir.mkdir(parents=True, exist_ok=True)
        primary = bundle_dir / "report.html"
        primary.write_text("<html>ok</html>", encoding="utf-8")
        return {
            "artifacts": [
                {
                    "artifact_key": "html_report",
                    "artifact_role": "primary",
                    "title": "Report",
                    "path": primary,
                    "mime_type": "text/html",
                    "is_primary": True,
                }
            ]
        }

    monkeypatch.setattr(export_service, "_build_snapshot_ticker_payload", lambda ticker: (_payload("latest_snapshot", 7), 7))
    monkeypatch.setattr(export_service, "_build_html_context", lambda ticker, source_mode: (_payload("loaded_backend_state"), None))
    monkeypatch.setattr(export_service, "stage_power_query_workbook", _stage_workbook)
    monkeypatch.setattr(export_service, "build_html_export_bundle", _stage_html)

    export_service.run_ticker_export(ticker="IBM", export_format="xlsx", source_mode="latest_snapshot")
    export_service.run_ticker_export(ticker="IBM", export_format="html", source_mode="loaded_backend_state")

    conn = _temp_conn_factory(db_path)()
    rows = conn.execute(
        """
        SELECT source_mode, source_key
        FROM ticker_dossier_snapshots
        ORDER BY source_mode
        """
    ).fetchall()

    assert [(row["source_mode"], row["source_key"]) for row in rows] == [
        ("latest_snapshot", "snapshot:7"),
        ("loaded_backend_state", "asof:2026-04-30"),
    ]
