"""Persist an internally consistent preflight/run identity and evidence handoff."""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from ciq.exact_ingest import _source_fact_digest
from ciq.source_evidence import (
    SOURCE_EVIDENCE_SCHEMA_VERSION,
    build_model_evidence_records,
    build_source_evidence_records,
    summarize_evidence_layers,
)
from ciq.workbook_parser import parse_ciq_workbook
from scripts.manual.professional_model_preflight import build_preflight_manifest


SOURCE_IDENTITY_SCHEMA_VERSION = "professional_source_identity_v1"


class SourceIdentityError(RuntimeError):
    pass


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    source = manifest.get("source") or {}
    parser = manifest.get("parser") or {}
    workbook = manifest.get("workbook") or {}
    return {
        "schema_version": SOURCE_IDENTITY_SCHEMA_VERSION,
        "ticker": manifest.get("ticker"),
        "source_file": source.get("source_file"),
        "source_hash": source.get("sha256"),
        "parser_version": parser.get("parser_version"),
        "run_id": source.get("run_id"),
        "ingest_timestamp": source.get("ingest_ts"),
        "ingest_status": source.get("status"),
        "workbook_as_of_date": source.get("workbook_as_of_date"),
        "workbook_refresh_timestamp": source.get("workbook_refresh_date"),
        "rows_parsed": parser.get("rows_parsed"),
        "template_fingerprint": parser.get("template_fingerprint"),
        "formula_error_count": workbook.get("formula_error_count"),
        "cached_error_count": workbook.get("cached_error_count"),
    }


def attach_preflight_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(manifest)
    payload = _identity_payload(result)
    result["identity"] = {
        **payload,
        "preflight_hash": canonical_hash(payload),
        "preflight_generated_at": result.get("generated_at"),
    }
    return result


def validate_preflight_identity(manifest: Mapping[str, Any], *, require_ready: bool = True) -> None:
    identity = manifest.get("identity") or {}
    expected = _identity_payload(manifest)
    expected_hash = canonical_hash(expected)
    mismatches = [
        key
        for key, value in expected.items()
        if identity.get(key) != value
    ]
    if identity.get("preflight_hash") != expected_hash:
        mismatches.append("preflight_hash")
    if identity.get("preflight_generated_at") != manifest.get("generated_at"):
        mismatches.append("preflight_generated_at")
    if mismatches:
        raise SourceIdentityError(f"stale or inconsistent preflight identity: {sorted(set(mismatches))}")
    if require_ready:
        if manifest.get("status") != "ready":
            raise SourceIdentityError(f"preflight is not ready: {manifest.get('blockers')}")
        if identity.get("run_id") is None or identity.get("ingest_status") != "completed":
            raise SourceIdentityError("ready preflight requires one completed matching ingest run")
        if identity.get("formula_error_count") != 0 or identity.get("cached_error_count") != 0:
            raise SourceIdentityError("ready preflight requires zero source formula and cached errors")


def _load_json(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dependency_index(payload: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    if not payload:
        return {}
    direct = payload.get("downstream_consumers")
    if isinstance(direct, Mapping):
        return {
            str(locator): tuple(sorted({str(item) for item in consumers}))
            for locator, consumers in direct.items()
            if isinstance(consumers, Sequence) and not isinstance(consumers, (str, bytes))
        }
    rows = payload.get("cells") or payload.get("dependencies") or payload.get("entries") or payload.get("repairs") or ()
    result: dict[str, set[str]] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        locator = str(
            item.get("cell_locator")
            or item.get("source_locator")
            or (
                f"{item.get('sheet')}!{item.get('cell')}"
                if item.get("sheet") and item.get("cell")
                else ""
            )
        ).strip()
        explicit = item.get("downstream_consumers") or item.get("consumers") or ()
        consumers = {
            str(value)
            for value in explicit
            if str(value)
        }
        for dependency_key in ("direct_formula_dependents", "transitive_formula_dependents"):
            for dependency in item.get(dependency_key) or ():
                if isinstance(dependency, Mapping) and dependency.get("dependent_cell"):
                    consumers.add(f"cell:{dependency['dependent_cell']}")
        for dependency in item.get("non_cell_consumers") or ():
            if not isinstance(dependency, Mapping):
                continue
            kind = str(dependency.get("kind") or "non_cell")
            name = str(dependency.get("name") or dependency.get("formula") or "unknown")
            consumers.add(f"{kind}:{name}")
        pipeline = item.get("pipeline") or {}
        if isinstance(pipeline, Mapping):
            if pipeline.get("primary_module_scope"):
                consumers.add(f"module:{pipeline['primary_module_scope']}")
            if pipeline.get("persisted_surface"):
                consumers.add(f"persisted:{pipeline['persisted_surface']}")
        if locator:
            result.setdefault(locator, set()).update(consumers)
    return {key: tuple(sorted(values)) for key, values in result.items()}


def _source_facts(db_path: Path, run_id: int) -> list[dict[str, Any]]:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM ciq_source_facts_v2
                WHERE run_id = ?
                ORDER BY sheet_name, row_index, column_index
                """,
                [run_id],
            ).fetchall()
        ]


def _verify_source_fact_integrity(
    *,
    identity: Mapping[str, Any],
    expected_facts: Sequence[Mapping[str, Any]],
    persisted_facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        declared_count = int(identity.get("rows_parsed"))
    except (TypeError, ValueError) as exc:
        raise SourceIdentityError("source identity rows_parsed is missing or invalid") from exc
    expected_count = len(expected_facts)
    persisted_count = len(persisted_facts)
    if expected_count != declared_count:
        raise SourceIdentityError(
            "parsed workbook fact count does not match source identity: "
            f"declared {declared_count}, parsed {expected_count}"
        )
    if persisted_count != declared_count:
        raise SourceIdentityError(
            "persisted source fact count does not match source identity: "
            f"declared {declared_count}, persisted {persisted_count}"
        )
    expected_digest = _source_fact_digest(list(expected_facts))
    persisted_digest = _source_fact_digest(list(persisted_facts))
    if persisted_digest != expected_digest:
        raise SourceIdentityError(
            "persisted source fact content does not match the parsed workbook: "
            f"expected {expected_digest}, persisted {persisted_digest}"
        )
    return {
        "status": "verified",
        "algorithm": "sha256_canonical_source_facts_v1",
        "declared_row_count": declared_count,
        "parsed_row_count": expected_count,
        "persisted_row_count": persisted_count,
        "source_fact_digest": expected_digest,
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return _jsonable(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return _jsonable(enum_value)
    return str(value)


def _lineage_consumers(lineage: Sequence[Any]) -> dict[str, set[str]]:
    output: dict[str, set[str]] = {}
    for item in lineage:
        canonical_key = str(getattr(item, "canonical_key", ""))
        for ref in getattr(item, "source_refs", ()) or ():
            locator = str(getattr(ref, "cell_locator", ""))
            if locator and canonical_key:
                output.setdefault(locator, set()).add(canonical_key)
    return output


def _unit_by_key(historical: Any, currency: str) -> dict[str, str]:
    units: dict[str, str] = {}
    for spec in historical.registry:
        key = str(spec.canonical_key)
        if key in {"wc.dso", "wc.dio", "wc.dpo"}:
            units[key] = "days"
        elif key == "tax.effective_rate":
            units[key] = "%"
        elif key.startswith("shares."):
            units[key] = f"{currency}/share" if key.endswith("eps") or key == "shares.dividend_per_share" else "mm shares"
        else:
            units[key] = f"{currency} mm"
    return units


def build_source_handoff(
    *,
    ticker: str,
    workbook_path: str | Path,
    db_path: str | Path,
    output_root: str | Path,
    repair_ledger_path: str | Path | None = None,
    dependency_map_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest = attach_preflight_identity(
        build_preflight_manifest(
            ticker=ticker,
            workbook_path=workbook_path,
            db_path=db_path,
            require_ingested=True,
        )
    )
    validate_preflight_identity(manifest, require_ready=True)
    identity = manifest["identity"]
    output_dir = Path(output_root) / ticker.upper() / str(identity["source_hash"])[:12]
    output_dir.mkdir(parents=True, exist_ok=True)

    repair_ledger = _load_json(repair_ledger_path)
    dependency_payload = _load_json(dependency_map_path)
    dependency_index = _dependency_index(dependency_payload)
    facts = _source_facts(Path(db_path), int(identity["run_id"]))
    parsed_workbook = parse_ciq_workbook(Path(workbook_path))
    if parsed_workbook.file_hash != identity["source_hash"]:
        raise SourceIdentityError(
            "parsed workbook hash does not match the validated preflight identity"
        )
    source_fact_integrity = _verify_source_fact_integrity(
        identity=identity,
        expected_facts=parsed_workbook.long_form_records,
        persisted_facts=facts,
    )

    historical = None
    historical_error = None
    try:
        from src.stage_02_valuation.integrated_financial_model import (
            build_historical_financial_model_from_sqlite,
        )

        historical = build_historical_financial_model_from_sqlite(
            db_path,
            ticker=ticker,
            run_id=int(identity["run_id"]),
        )
    except Exception as exc:  # fail closed while retaining the raw evidence packet
        historical_error = f"{type(exc).__name__}: {exc}"

    if historical is not None:
        for locator, consumers in _lineage_consumers(historical.lineage).items():
            dependency_index[locator] = tuple(
                sorted(set(dependency_index.get(locator, ())) | consumers)
            )

    refresh_timestamp = manifest["source"].get("workbook_refresh_date")
    source_records = build_source_evidence_records(
        facts,
        source_hash=str(identity["source_hash"]),
        run_id=int(identity["run_id"]),
        source_refresh_timestamp=refresh_timestamp,
        repair_ledger=repair_ledger,
        downstream_consumers=dependency_index,
    )
    model_records = (
        build_model_evidence_records(
            historical.lineage,
            source_evidence=source_records,
            unit_by_canonical_key=_unit_by_key(
                historical,
                str(manifest["source"].get("currency") or "USD"),
            ),
            source_refresh_timestamp=refresh_timestamp,
        )
        if historical is not None
        else []
    )
    evidence = {
        "schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "identity": identity,
        "source_fact_integrity": source_fact_integrity,
        "summary": summarize_evidence_layers(source_records, model_records),
        "historical_status": (
            {
                "status": "built",
                "engine_version": historical.engine_version,
                "registry_version": historical.registry_version,
                "state": _jsonable(historical.result.state),
                "coverage": _jsonable(historical.coverage),
                "checks": _jsonable(historical.result.check_results),
                "limitations": list(historical.limitations),
            }
            if historical is not None
            else {"status": "unavailable", "error": historical_error}
        ),
        "source_cells": source_records,
        "normalized_model_lines": model_records,
    }
    handoff_status = "ready" if historical is not None else "partial"
    evidence["status"] = handoff_status

    preflight_path = output_dir / "preflight_fingerprint.json"
    evidence_path = output_dir / "source_evidence_layers.json"
    preflight_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": SOURCE_IDENTITY_SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "status": handoff_status,
        "identity": identity,
        "source_fact_integrity": source_fact_integrity,
        "artifacts": {
            "preflight_fingerprint": {
                "path": str(preflight_path.resolve()),
                "sha256": _file_hash(preflight_path),
            },
            "source_evidence_layers": {
                "path": str(evidence_path.resolve()),
                "sha256": _file_hash(evidence_path),
            },
            "repair_ledger": {
                "path": str(Path(repair_ledger_path).resolve()) if repair_ledger_path else None,
                "sha256": _file_hash(Path(repair_ledger_path)) if repair_ledger_path else None,
            },
            "dependency_map": {
                "path": str(Path(dependency_map_path).resolve()) if dependency_map_path else None,
                "sha256": _file_hash(Path(dependency_map_path)) if dependency_map_path else None,
            },
        },
    }
    receipt_path = output_dir / "source_run_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {
        "status": handoff_status,
        "identity": identity,
        "preflight": str(preflight_path.resolve()),
        "evidence": str(evidence_path.resolve()),
        "receipt": str(receipt_path.resolve()),
        "summary": evidence["summary"],
        "historical_status": evidence["historical_status"]["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist one exact source-run identity and evidence handoff.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--workbook-path", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repair-ledger")
    parser.add_argument("--dependency-map")
    args = parser.parse_args(argv)
    try:
        result = build_source_handoff(
            ticker=args.ticker,
            workbook_path=args.workbook_path,
            db_path=args.db_path,
            output_root=args.output_root,
            repair_ledger_path=args.repair_ledger,
            dependency_map_path=args.dependency_map,
        )
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SOURCE_IDENTITY_SCHEMA_VERSION",
    "SourceIdentityError",
    "_verify_source_fact_integrity",
    "attach_preflight_identity",
    "build_source_handoff",
    "canonical_hash",
    "validate_preflight_identity",
]
