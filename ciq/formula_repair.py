"""Deterministic, cache-preserving repair for proven CIQ workbook formulas.

Only OOXML ``<f>`` text is changed. Cached ``<v>`` values are retained and
native CIQ/Excel refresh verification is always reported separately.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile


REPAIR_SCHEMA_VERSION = "ciq_formula_repair_ledger_v1"
DEPENDENCY_SCHEMA_VERSION = "ciq_formula_dependency_map_v1"
REPAIR_ALGORITHM_VERSION = "detailed_comps_final_argument_v1"
TARGET_SHEET = "Detailed Comps"
TARGET_COLUMNS = ("AC", "AG", "AK")
TARGET_ROWS = tuple(range(3, 11))
TARGET_CELLS = tuple(f"{column}{row}" for column in TARGET_COLUMNS for row in TARGET_ROWS)
ANCHOR_ROW = 2

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_ERROR_TOKENS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!")
_COORD_RE = re.compile(r"^(?P<column>[A-Z]{1,3})(?P<row>[1-9]\d*)$")
_FINAL_REF_RE = re.compile(r"#REF!(?=\s*\)+\s*$)", re.IGNORECASE)
_TRAILING_ARGUMENT_RE = re.compile(r",\s*(?P<arg>\$?[A-Z]{1,3}\$?[1-9]\d*)\s*\)+\s*$")
_A1_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(?P<col_abs>\$?)(?P<col>[A-Z]{1,3})(?P<row_abs>\$?)(?P<row>[1-9]\d*)"
    r"(?![A-Za-z0-9_!])"
)
_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(?P<start>\$?[A-Z]{1,3}\$?[1-9]\d*)"
    r"(?::(?P<end>\$?[A-Z]{1,3}\$?[1-9]\d*))?"
    r"(?![A-Za-z0-9_!])"
)


class FormulaRepairError(RuntimeError):
    """Raised when the requested repair cannot be proven safe."""


@dataclass(frozen=True, slots=True)
class CellSnapshot:
    sheet: str
    coordinate: str
    formula: str | None
    cached_value: Any
    cached_raw: str | None
    cached_type: str | None
    formula_error: str | None
    cached_error: str | None

    @property
    def locator(self) -> str:
        return f"{self.sheet}!{self.coordinate}"


@dataclass(frozen=True, slots=True)
class FormulaCell:
    sheet: str
    coordinate: str
    formula: str

    @property
    def locator(self) -> str:
        return f"{self.sheet}!{self.coordinate}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(value: Any, *, embedded: bool) -> str | None:
    if value is None:
        return None
    text = str(value).upper()
    return next((token for token in _ERROR_TOKENS if token in text), None) if embedded else next(
        (token for token in _ERROR_TOKENS if token == text), None
    )


def _col_index(column: str) -> int:
    value = 0
    for char in column.upper():
        value = value * 26 + ord(char) - 64
    return value


def _col_name(index: int) -> str:
    if not 1 <= index <= 16384:
        raise FormulaRepairError(f"Excel column out of range: {index}")
    chars: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        chars.append(chr(65 + remainder))
    return "".join(reversed(chars))


def _coord_indexes(coordinate: str) -> tuple[int, int]:
    match = _COORD_RE.fullmatch(coordinate.replace("$", "").upper())
    if match is None:
        raise FormulaRepairError(f"Unsupported A1 coordinate: {coordinate}")
    return _col_index(match.group("column")), int(match.group("row"))


def _formula_segments(formula: str) -> list[tuple[bool, str]]:
    """Split formula into outside/inside-double-quoted-string segments."""
    segments: list[tuple[bool, str]] = []
    start = 0
    outside = True
    index = 0
    while index < len(formula):
        if formula[index] != '"':
            index += 1
            continue
        if not outside and index + 1 < len(formula) and formula[index + 1] == '"':
            index += 2
            continue
        index += 1
        segments.append((outside, formula[start:index]))
        start = index
        outside = not outside
    if start < len(formula):
        segments.append((outside, formula[start:]))
    return segments


def _translate_formula(formula: str, row_delta: int, column_delta: int = 0) -> str:
    def translate(match: re.Match[str]) -> str:
        col = _col_index(match.group("col"))
        row = int(match.group("row"))
        if col > 16384:
            return match.group(0)
        if not match.group("col_abs"):
            col += column_delta
        if not match.group("row_abs"):
            row += row_delta
        sheet = f"{match.group('sheet')}!" if match.group("sheet") else ""
        return f"{sheet}{match.group('col_abs')}{_col_name(col)}{match.group('row_abs')}{row}"

    return "".join(_A1_RE.sub(translate, text) if outside else text for outside, text in _formula_segments(formula))


def _sheet_parts(archive: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        node.attrib["Id"]: node.attrib["Target"]
        for node in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
        if node.attrib.get("Type", "").endswith("/worksheet")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(f"{{{_MAIN_NS}}}sheets/{{{_MAIN_NS}}}sheet"):
        target = targets[sheet.attrib[f"{{{_DOC_REL_NS}}}id"]].replace("\\", "/")
        result[sheet.attrib["name"]] = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        )
    return result


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")) for item in root]


def _decode_value(cell: ET.Element, shared: list[str]) -> tuple[Any, str | None, str | None]:
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    raw = value_node.text if value_node is not None else None
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        value = "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
        return value, value, kind
    if raw is None:
        return None, None, kind
    if kind == "s":
        try:
            return shared[int(raw)], raw, kind
        except (IndexError, ValueError):
            return raw, raw, kind
    if kind in {"str", "e"}:
        return raw, raw, kind
    if kind == "b":
        return raw == "1", raw, kind
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number, raw, kind
    except ValueError:
        return raw, raw, kind


def _formula(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text if node.text.startswith("=") else f"={node.text}"


def _read_sheet(archive: ZipFile, sheet: str, part: str, shared: list[str]) -> tuple[dict[str, CellSnapshot], list[FormulaCell]]:
    root = ET.fromstring(archive.read(part))
    snapshots: dict[str, CellSnapshot] = {}
    formulas: list[FormulaCell] = []
    shared_anchors: dict[str, tuple[str, str]] = {}
    cells = root.findall(f".//{{{_MAIN_NS}}}c")
    for cell in cells:
        coordinate = cell.attrib.get("r")
        if not coordinate:
            continue
        formula_node = cell.find(f"{{{_MAIN_NS}}}f")
        formula = _formula(formula_node)
        if formula_node is not None and formula_node.attrib.get("t") == "shared" and formula is not None:
            shared_anchors[formula_node.attrib.get("si", "")] = (coordinate, formula)
        value, raw, kind = _decode_value(cell, shared)
        snapshots[coordinate] = CellSnapshot(sheet, coordinate, formula, value, raw, kind, _error(formula, embedded=True), _error(value, embedded=False))
    for cell in cells:
        coordinate = cell.attrib.get("r")
        formula_node = cell.find(f"{{{_MAIN_NS}}}f")
        if not coordinate or formula_node is None:
            continue
        formula = _formula(formula_node)
        if formula is None and formula_node.attrib.get("t") == "shared":
            anchor_coord, anchor_formula = shared_anchors[formula_node.attrib.get("si", "")]
            anchor_col, anchor_row = _coord_indexes(anchor_coord)
            cell_col, cell_row = _coord_indexes(coordinate)
            formula = _translate_formula(anchor_formula, cell_row - anchor_row, cell_col - anchor_col)
            old = snapshots[coordinate]
            snapshots[coordinate] = CellSnapshot(sheet, coordinate, formula, old.cached_value, old.cached_raw, old.cached_type, _error(formula, embedded=True), old.cached_error)
        if formula is not None:
            formulas.append(FormulaCell(sheet, coordinate, formula))
    return snapshots, formulas


def inspect_workbook(path: str | Path) -> dict[str, Any]:
    workbook_path = Path(path)
    try:
        with ZipFile(workbook_path) as archive:
            parts = _sheet_parts(archive)
            shared = _shared_strings(archive)
            snapshots: dict[str, dict[str, CellSnapshot]] = {}
            formulas: list[FormulaCell] = []
            for sheet, part in parts.items():
                sheet_snapshots, sheet_formulas = _read_sheet(archive, sheet, part, shared)
                snapshots[sheet] = sheet_snapshots
                formulas.extend(sheet_formulas)
            bad_member = archive.testzip()
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise FormulaRepairError(f"Invalid workbook package: {workbook_path}") from exc
    formula_errors = [item for item in formulas if _error(item.formula, embedded=True)]
    cached_errors = [cell for sheet in snapshots.values() for cell in sheet.values() if cell.cached_error]
    return {
        "path": workbook_path,
        "sha256": sha256_file(workbook_path),
        "size_bytes": workbook_path.stat().st_size,
        "sheet_parts": parts,
        "snapshots": snapshots,
        "formula_cells": formulas,
        "formula_count": len(formulas),
        "formula_error_count": len(formula_errors),
        "formula_error_cells": [item.locator for item in formula_errors],
        "cached_error_count": len(cached_errors),
        "cached_error_cells": [item.locator for item in cached_errors],
        "zip_test_bad_member": bad_member,
    }


def _derive_repairs(inspection: Mapping[str, Any]) -> list[dict[str, Any]]:
    snapshots = inspection["snapshots"].get(TARGET_SHEET)
    if snapshots is None:
        raise FormulaRepairError(f"Workbook is missing {TARGET_SHEET!r}")
    repairs: list[dict[str, Any]] = []
    for coordinate in TARGET_CELLS:
        match = _COORD_RE.fullmatch(coordinate)
        assert match is not None
        column, row = match.group("column"), int(match.group("row"))
        anchor_coordinate = f"{column}{ANCHOR_ROW}"
        target = snapshots.get(coordinate)
        anchor = snapshots.get(anchor_coordinate)
        if target is None or target.formula is None:
            raise FormulaRepairError(f"Target formula is missing: {TARGET_SHEET}!{coordinate}")
        if anchor is None or anchor.formula is None or anchor.formula_error:
            raise FormulaRepairError(f"Valid pattern anchor is missing: {TARGET_SHEET}!{anchor_coordinate}")
        if target.formula.upper().count("#REF!") != 1 or not _FINAL_REF_RE.search(target.formula):
            raise FormulaRepairError(f"Target lacks a sole final-argument #REF!: {target.locator}")
        anchor_arg = _TRAILING_ARGUMENT_RE.search(anchor.formula)
        if anchor_arg is None or anchor_arg.group("arg") != f"$C{ANCHOR_ROW}":
            raise FormulaRepairError(f"Anchor final argument is not $C{ANCHOR_ROW}: {anchor.locator}")
        translated = _translate_formula(anchor.formula, row - ANCHOR_ROW)
        translated_arg = _TRAILING_ARGUMENT_RE.search(translated)
        expected_arg = translated_arg.group("arg") if translated_arg else None
        if expected_arg != f"$C{row}":
            raise FormulaRepairError(f"Translated anchor argument mismatch: {target.locator}")
        repaired = _FINAL_REF_RE.sub(expected_arg, target.formula, count=1)
        if repaired != translated:
            raise FormulaRepairError(f"Target does not match its translated row-2 anchor: {target.locator}")
        repairs.append(
            {
                "sheet_name": TARGET_SHEET,
                "a1_locator": coordinate,
                "cell_locator": target.locator,
                "row_index": row,
                "column_index": _col_index(column),
                "original_formula": target.formula,
                "cached_value": target.cached_value,
                "cached_value_raw": target.cached_raw,
                "cached_value_type": target.cached_type,
                "original_formula_error": target.formula_error,
                "original_cached_error": target.cached_error,
                "repaired_formula": repaired,
                "repaired_formula_error": _error(repaired, embedded=True),
                "rationale": (
                    f"{anchor_coordinate} is error-free; translating it to row {row} matches the target exactly "
                    f"when the sole final-argument #REF! is restored to $C{row}."
                ),
                "pattern_evidence": {
                    "anchor_cell": anchor.locator,
                    "anchor_formula": anchor.formula,
                    "anchor_final_argument": anchor_arg.group("arg"),
                    "row_delta": row - ANCHOR_ROW,
                    "translated_anchor_formula": translated,
                    "expected_final_argument": expected_arg,
                    "broken_token_count": 1,
                    "broken_token_is_final_argument": True,
                    "candidate_matches_translated_anchor": True,
                },
                "refresh_verification_status": "unresolved",
            }
        )
    return repairs


def _patch_sheet_xml(sheet_xml: bytes, repairs: Iterable[Mapping[str, Any]]) -> bytes:
    patched = sheet_xml
    for repair in repairs:
        coordinate = re.escape(str(repair["a1_locator"]).encode("ascii"))
        cell_pattern = re.compile(
            rb"<c\b(?=[^>]*\br=\"" + coordinate + rb"\")[^>]*>.*?</c>", re.DOTALL
        )
        cell_match = cell_pattern.search(patched)
        if cell_match is None:
            raise FormulaRepairError(f"OOXML cell not found: {repair['cell_locator']}")
        cell_xml = cell_match.group(0)
        formula_pattern = re.compile(
            rb"(<(?:[A-Za-z_][\w.-]*:)?f\b[^>]*>)(.*?)(</(?:[A-Za-z_][\w.-]*:)?f>)",
            re.DOTALL,
        )
        formula_match = formula_pattern.search(cell_xml)
        if formula_match is None:
            raise FormulaRepairError(f"OOXML formula not found: {repair['cell_locator']}")
        existing = "=" + unescape(formula_match.group(2).decode("utf-8"))
        if existing != repair["original_formula"]:
            raise FormulaRepairError(f"Formula changed during repair preparation: {repair['cell_locator']}")
        replacement = escape(str(repair["repaired_formula"])[1:]).encode("utf-8")
        new_formula = formula_match.group(1) + replacement + formula_match.group(3)
        new_cell = cell_xml[: formula_match.start()] + new_formula + cell_xml[formula_match.end() :]
        patched = patched[: cell_match.start()] + new_cell + patched[cell_match.end() :]
    return patched


def _write_repaired_package(
    source: Path,
    derived: Path,
    sheet_part: str,
    repairs: list[dict[str, Any]],
    *,
    overwrite: bool,
) -> None:
    if source.resolve() == derived.resolve():
        raise FormulaRepairError("Derived workbook must not overwrite the source workbook")
    if derived.exists() and not overwrite:
        raise FormulaRepairError(f"Derived workbook already exists: {derived}")
    derived.parent.mkdir(parents=True, exist_ok=True)
    temp = derived.with_name(f".{derived.name}.tmp")
    if temp.exists():
        temp.unlink()
    try:
        with ZipFile(source) as source_zip, ZipFile(temp, "w", ZIP_DEFLATED, allowZip64=True) as output_zip:
            output_zip.comment = source_zip.comment
            for member in source_zip.infolist():
                payload = source_zip.read(member.filename)
                if member.filename == sheet_part:
                    payload = _patch_sheet_xml(payload, repairs)
                output_zip.writestr(member, payload)
        temp.replace(derived)
    finally:
        if temp.exists():
            temp.unlink()


def _formula_references(formula: str, current_sheet: str) -> list[tuple[str, str, str]]:
    references: list[tuple[str, str, str]] = []
    for outside, text in _formula_segments(formula):
        if not outside:
            continue
        for match in _RANGE_RE.finditer(text):
            sheet_token = match.group("sheet")
            if sheet_token is None:
                sheet = current_sheet
            elif sheet_token.startswith("'"):
                sheet = sheet_token[1:-1].replace("''", "'")
            else:
                sheet = sheet_token
            start = match.group("start").replace("$", "").upper()
            end = (match.group("end") or match.group("start")).replace("$", "").upper()
            try:
                _coord_indexes(start)
                _coord_indexes(end)
            except FormulaRepairError:
                continue
            references.append((sheet, start, end))
    return references


def _range_contains(reference: tuple[str, str, str], sheet: str, coordinate: str) -> bool:
    if reference[0] != sheet:
        return False
    start_col, start_row = _coord_indexes(reference[1])
    end_col, end_row = _coord_indexes(reference[2])
    col, row = _coord_indexes(coordinate)
    return (
        min(start_col, end_col) <= col <= max(start_col, end_col)
        and min(start_row, end_row) <= row <= max(start_row, end_row)
    )


def _dependency_paths(
    formulas: Iterable[FormulaCell], source_sheet: str, source_coordinate: str
) -> list[dict[str, Any]]:
    indexed = [(formula, _formula_references(formula.formula, formula.sheet)) for formula in formulas]
    discovered: dict[str, dict[str, Any]] = {}
    frontier = [(source_sheet, source_coordinate, f"{source_sheet}!{source_coordinate}")]
    depth = 0
    while frontier:
        depth += 1
        next_frontier: list[tuple[str, str, str]] = []
        for formula, references in indexed:
            if formula.locator in discovered:
                continue
            via = next(
                (
                    locator
                    for sheet, coordinate, locator in frontier
                    if any(_range_contains(reference, sheet, coordinate) for reference in references)
                ),
                None,
            )
            if via is None:
                continue
            discovered[formula.locator] = {
                "dependent_cell": formula.locator,
                "dependent_sheet": formula.sheet,
                "dependent_a1_locator": formula.coordinate,
                "formula": formula.formula,
                "depth": depth,
                "via": via,
            }
            next_frontier.append((formula.sheet, formula.coordinate, formula.locator))
        frontier = next_frontier
    return sorted(
        discovered.values(),
        key=lambda item: (item["depth"], item["dependent_sheet"], item["dependent_a1_locator"]),
    )


def _non_cell_dependencies(archive: ZipFile, coordinate: str) -> list[dict[str, Any]]:
    dependencies: list[dict[str, Any]] = []
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    for node in workbook.findall(f"{{{_MAIN_NS}}}definedNames/{{{_MAIN_NS}}}definedName"):
        formula = node.text or ""
        if any(_range_contains(ref, TARGET_SHEET, coordinate) for ref in _formula_references(f"={formula}", TARGET_SHEET)):
            name = node.attrib.get("name")
            dependencies.append(
                {
                    "kind": "defined_name",
                    "name": name,
                    "formula": formula,
                    "dependency_semantics": (
                        "layout_only" if name in {"_xlnm.Print_Area", "_xlnm.Print_Titles"} else "named_formula"
                    ),
                }
            )
    chart_parts = sorted(
        name for name in archive.namelist() if name.startswith("xl/charts/") and name.endswith(".xml")
    )
    for part in chart_parts:
        root = ET.fromstring(archive.read(part))
        for index, node in enumerate(root.findall(f".//{{{_CHART_NS}}}f"), start=1):
            formula = node.text or ""
            if any(_range_contains(ref, TARGET_SHEET, coordinate) for ref in _formula_references(f"={formula}", TARGET_SHEET)):
                dependencies.append(
                    {
                        "kind": "chart_series",
                        "part": part,
                        "formula_index": index,
                        "formula": formula,
                        "dependency_semantics": "visualization_consumer",
                    }
                )
    return dependencies


def _metric_slug(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or None


def _cell_context(snapshots: Mapping[str, CellSnapshot], coordinate: str) -> dict[str, Any]:
    target_col, target_row = _coord_indexes(coordinate)
    ticker_header = next(
        (cell for cell in snapshots.values() if str(cell.cached_value or "").strip().lower() == "ticker"),
        None,
    )
    name_header = next(
        (cell for cell in snapshots.values() if str(cell.cached_value or "").strip().lower() == "name"),
        None,
    )
    header_row = _coord_indexes(ticker_header.coordinate)[1] if ticker_header else 1
    ticker_col = _coord_indexes(ticker_header.coordinate)[0] if ticker_header else 1
    name_col = _coord_indexes(name_header.coordinate)[0] if name_header else None
    header = snapshots.get(f"{_col_name(target_col)}{header_row}")
    ticker = snapshots.get(f"{_col_name(ticker_col)}{target_row}")
    name = snapshots.get(f"{_col_name(name_col)}{target_row}") if name_col else None
    return {
        "header_row": header_row,
        "column_label": header.cached_value if header else None,
        "metric_key": _metric_slug(header.cached_value if header else None),
        "peer_ticker": ticker.cached_value if ticker else None,
        "peer_name": name.cached_value if name else None,
    }


def _pipeline_classification(metric_key: str | None) -> dict[str, Any]:
    consensus_keys = {
        "total_revenue_cy_1", "revenue_cy_1", "revenue_fy1",
        "total_revenue_cy_2", "revenue_cy_2", "revenue_fy2",
    }
    exit_keys = {
        "tev_ebitda_ltm", "tev_ebitda", "tev_ebit_ltm", "tev_ebit",
        "tev_ebitda_cy_1", "tev_ebitda_cy1", "tev_ebit_cy_1", "tev_ebit_cy1",
        "pe_ltm", "pe",
    }
    active_comps_keys = consensus_keys | exit_keys | {
        "market_cap",
        "market_capitalization",
        "tev",
        "enterprise_value",
        "total_enterprise_value",
        "shares_out",
        "shares_outstanding",
        "cash",
        "cash_and_equivalents",
        "total_debt",
        "debt",
        "total_revenue_ltm",
        "revenue_ltm",
        "ebitda_ltm",
        "ebit_ltm",
        "diluted_eps_ltm",
    }
    affects_dcf = metric_key in consensus_keys or metric_key in exit_keys
    active_consumer = metric_key in active_comps_keys
    return {
        "source_parser_route": "ciq.workbook_parser._parse_comps_sheet(Detailed Comps)",
        "persisted_surface": "ciq_comps_snapshot",
        "primary_module_scope": "comps",
        "affects_comps": True,
        "active_computation_consumer": active_consumer,
        "active_consumer_routes": (
            [
                "src.stage_00_data.ciq_adapter.get_ciq_comps_valuation",
                "src.stage_00_data.ciq_adapter.get_ciq_comps_detail",
            ]
            if active_consumer else []
        ),
        "unmapped_by_current_ciq_adapter": not active_consumer,
        "module_gate_scope": "comps_and_dcf" if affects_dcf else "comps_source_integrity_only",
        "affects_dcf": affects_dcf,
        "dcf_role": (
            "near_term_revenue_consensus" if metric_key in consensus_keys else
            "comps_exit_multiple_or_cross_check" if metric_key in exit_keys else None
        ),
        "affects_wacc": False,
        "wacc_evidence": (
            "src.stage_02_valuation.wacc builds PeerData from market data; "
            "CIQ Detailed Comps is not a WACC input route."
        ),
        "historical_financials_evidence": (
            "ciq.workbook_parser._build_valuation_snapshot filters historical series "
            "to Financial Statements."
        ),
    }


def build_dependency_map(path: str | Path) -> dict[str, Any]:
    inspection = inspect_workbook(path)
    snapshots = inspection["snapshots"].get(TARGET_SHEET)
    if snapshots is None:
        raise FormulaRepairError(f"Workbook is missing {TARGET_SHEET!r}")
    cells: list[dict[str, Any]] = []
    with ZipFile(Path(path)) as archive:
        for coordinate in TARGET_CELLS:
            context = _cell_context(snapshots, coordinate)
            paths = _dependency_paths(inspection["formula_cells"], TARGET_SHEET, coordinate)
            non_cell = _non_cell_dependencies(archive, coordinate)
            layout_consumers = [
                item for item in non_cell if item.get("dependency_semantics") == "layout_only"
            ]
            computational_non_cell = [
                item for item in non_cell if item.get("dependency_semantics") != "layout_only"
            ]
            pipeline = _pipeline_classification(context["metric_key"])
            affected_sheets = sorted({item["dependent_sheet"] for item in paths})
            cells.append(
                {
                    "sheet_name": TARGET_SHEET,
                    "a1_locator": coordinate,
                    "cell_locator": f"{TARGET_SHEET}!{coordinate}",
                    "context": context,
                    "direct_formula_dependents": [item for item in paths if item["depth"] == 1],
                    "transitive_formula_dependents": [item for item in paths if item["depth"] > 1],
                    "non_cell_consumers": non_cell,
                    "layout_consumers": layout_consumers,
                    "computational_non_cell_consumers": computational_non_cell,
                    "affected_workbook_sheets": affected_sheets,
                    "workbook_scope": (
                        "comps_only"
                        if all(sheet in {TARGET_SHEET, "Summary Comps"} for sheet in affected_sheets)
                        else "cross_module_workbook_dependency"
                    ),
                    "pipeline": pipeline,
                }
            )
    affects_dcf = any(cell["pipeline"]["affects_dcf"] for cell in cells)
    affects_wacc = any(cell["pipeline"]["affects_wacc"] for cell in cells)
    return {
        "schema_version": DEPENDENCY_SCHEMA_VERSION,
        "source_workbook": {"path": str(Path(path).resolve()), "sha256": inspection["sha256"]},
        "target_sheet": TARGET_SHEET,
        "target_cells": list(TARGET_CELLS),
        "summary": {
            "target_cell_count": len(TARGET_CELLS),
            "cells_with_direct_formula_dependents": sum(bool(cell["direct_formula_dependents"]) for cell in cells),
            "cells_with_transitive_formula_dependents": sum(bool(cell["transitive_formula_dependents"]) for cell in cells),
            "cells_with_non_cell_consumers": sum(bool(cell["non_cell_consumers"]) for cell in cells),
            "cells_with_layout_consumers": sum(bool(cell["layout_consumers"]) for cell in cells),
            "cells_with_computational_non_cell_consumers": sum(
                bool(cell["computational_non_cell_consumers"]) for cell in cells
            ),
            "active_computation_consumer_count": sum(
                bool(cell["pipeline"]["active_computation_consumer"]) for cell in cells
            ),
            "affects_comps": True,
            "affects_dcf": affects_dcf,
            "affects_wacc": affects_wacc,
            "classification": "comps_and_dcf" if affects_dcf else "comps_only",
        },
        "cells": cells,
    }


def _verify_preservation(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    repairs: list[dict[str, Any]],
) -> dict[str, Any]:
    repaired_by_locator = {item["cell_locator"]: item for item in repairs}
    failures: list[str] = []
    cell_count = 0
    for sheet, source_cells in before["snapshots"].items():
        derived_cells = after["snapshots"].get(sheet, {})
        if set(source_cells) != set(derived_cells):
            failures.append(f"cell_set_changed:{sheet}")
            continue
        for coordinate, source_cell in source_cells.items():
            cell_count += 1
            derived_cell = derived_cells[coordinate]
            if (source_cell.cached_raw, source_cell.cached_type) != (
                derived_cell.cached_raw,
                derived_cell.cached_type,
            ):
                failures.append(f"cache_changed:{source_cell.locator}")
            repair = repaired_by_locator.get(source_cell.locator)
            expected_formula = repair["repaired_formula"] if repair else source_cell.formula
            if derived_cell.formula != expected_formula:
                failures.append(f"formula_mismatch:{source_cell.locator}")
    if before["formula_count"] != after["formula_count"]:
        failures.append("formula_count_changed")
    if failures:
        raise FormulaRepairError("Derived workbook preservation check failed: " + ", ".join(failures[:20]))
    return {
        "all_formula_cache_pairs_checked": cell_count,
        "all_cached_values_byte_preserved": True,
        "all_untouched_formulas_logically_preserved": True,
        "only_target_formula_text_changed": True,
    }


def _verify_package_parts(source: Path, derived: Path, changed_part: str) -> dict[str, Any]:
    with ZipFile(source) as source_zip, ZipFile(derived) as derived_zip:
        source_names = source_zip.namelist()
        derived_names = derived_zip.namelist()
        if source_names != derived_names:
            raise FormulaRepairError("Derived workbook ZIP member order/set changed")
        changed = [
            name
            for name in source_names
            if source_zip.read(name) != derived_zip.read(name)
        ]
    if changed != [changed_part]:
        raise FormulaRepairError(f"Unexpected OOXML parts changed: {changed}")
    return {
        "zip_member_order_and_set_preserved": True,
        "changed_ooxml_parts": changed,
        "all_other_ooxml_parts_byte_identical": True,
    }


def repair_workbook(
    source_path: str | Path,
    derived_path: str | Path,
    *,
    ledger_path: str | Path | None = None,
    dependency_map_path: str | Path | None = None,
    generated_at: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    source, derived = Path(source_path), Path(derived_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    source_hash = sha256_file(source)
    before = inspect_workbook(source)
    repairs = _derive_repairs(before)
    dependency_map = build_dependency_map(source)
    dependency_by_cell = {cell["cell_locator"]: cell for cell in dependency_map["cells"]}
    for repair in repairs:
        repair["downstream_dependency_classification"] = dependency_by_cell[repair["cell_locator"]]
    changed_part = before["sheet_parts"][TARGET_SHEET]
    _write_repaired_package(source, derived, changed_part, repairs, overwrite=overwrite)
    if sha256_file(source) != source_hash:
        raise FormulaRepairError("Original workbook hash changed during repair")
    after = inspect_workbook(derived)
    preservation = _verify_preservation(before, after, repairs)
    package_parts = _verify_package_parts(source, derived, changed_part)
    if after["zip_test_bad_member"] is not None:
        raise FormulaRepairError(f"Derived ZIP CRC failure: {after['zip_test_bad_member']}")
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target_locators = {f"{TARGET_SHEET}!{cell}" for cell in TARGET_CELLS}
    ledger = {
        "schema_version": REPAIR_SCHEMA_VERSION,
        "algorithm_version": REPAIR_ALGORITHM_VERSION,
        "generated_at": generated,
        "source_workbook": {
            "path": str(source.resolve()),
            "sha256": source_hash,
            "size_bytes": source.stat().st_size,
            "original_remained_byte_identical": True,
        },
        "derived_workbook": {
            "path": str(derived.resolve()),
            "sha256": after["sha256"],
            "size_bytes": derived.stat().st_size,
        },
        "repair_scope": {
            "sheet_name": TARGET_SHEET,
            "target_cells": list(TARGET_CELLS),
            "repair_count": len(repairs),
        },
        "source_formula_state": {
            "formula_count": before["formula_count"],
            "formula_error_count": before["formula_error_count"],
            "formula_error_cells": before["formula_error_cells"],
            "cached_error_count": before["cached_error_count"],
            "cached_error_cells": before["cached_error_cells"],
        },
        "derived_formula_state": {
            "formula_count": after["formula_count"],
            "formula_error_count": after["formula_error_count"],
            "formula_error_cells": after["formula_error_cells"],
            "cached_error_count": after["cached_error_count"],
            "cached_error_cells": after["cached_error_cells"],
        },
        "refresh_verification": {
            "status": "unresolved",
            "method": "not_attempted",
            "native_ciq_refresh_performed": False,
            "native_excel_recalculation_performed": False,
            "reason": (
                "The utility never launches or controls Excel. Formula/cache structure is verified, "
                "but refreshed CIQ results require a later attended native CIQ/Excel refresh."
            ),
        },
        "structural_verification": {
            "status": "passed",
            "zip_crc_test": "passed",
            "source_hash_unchanged": True,
            "target_formula_errors_remaining": [
                locator for locator in after["formula_error_cells"] if locator in target_locators
            ],
            **preservation,
            **package_parts,
        },
        "repairs": repairs,
        "dependency_map": dependency_map,
    }
    if ledger_path is not None:
        destination = Path(ledger_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if dependency_map_path is not None:
        destination = Path(dependency_map_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        export = {
            **dependency_map,
            "generated_at": generated,
            "derived_workbook": {"path": str(derived.resolve()), "sha256": after["sha256"]},
        }
        destination.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ledger


def load_repair_ledger(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != REPAIR_SCHEMA_VERSION or not isinstance(payload.get("repairs"), list):
        raise FormulaRepairError("Unsupported or incomplete repair ledger")
    return payload


def query_repair_ledger(
    ledger: Mapping[str, Any], *, sheet_name: str, a1_locator: str
) -> dict[str, Any] | None:
    locator = f"{sheet_name}!{a1_locator.upper()}"
    return next((dict(item) for item in ledger.get("repairs", []) if item.get("cell_locator") == locator), None)


def repaired_formula_for(
    ledger: Mapping[str, Any], *, sheet_name: str, a1_locator: str
) -> str | None:
    record = query_repair_ledger(ledger, sheet_name=sheet_name, a1_locator=a1_locator)
    return str(record["repaired_formula"]) if record else None


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("source", type=Path)
    dependency_parser = commands.add_parser("dependencies")
    dependency_parser.add_argument("source", type=Path)
    dependency_parser.add_argument("--output", type=Path)
    repair_parser = commands.add_parser("repair")
    repair_parser.add_argument("source", type=Path)
    repair_parser.add_argument("derived", type=Path)
    repair_parser.add_argument("--ledger", type=Path, required=True)
    repair_parser.add_argument("--dependency-map", type=Path, required=True)
    repair_parser.add_argument("--generated-at")
    repair_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    if args.command == "inspect":
        inspection = inspect_workbook(args.source)
        output = {
            "source": str(args.source.resolve()),
            "sha256": inspection["sha256"],
            "formula_count": inspection["formula_count"],
            "formula_error_count": inspection["formula_error_count"],
            "formula_error_cells": inspection["formula_error_cells"],
            "repair_candidates": _derive_repairs(inspection),
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    if args.command == "dependencies":
        output = build_dependency_map(args.source)
        rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    ledger = repair_workbook(
        args.source,
        args.derived,
        ledger_path=args.ledger,
        dependency_map_path=args.dependency_map,
        generated_at=args.generated_at,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "source_sha256": ledger["source_workbook"]["sha256"],
                "derived_sha256": ledger["derived_workbook"]["sha256"],
                "repair_count": ledger["repair_scope"]["repair_count"],
                "refresh_verification_status": ledger["refresh_verification"]["status"],
                "ledger": str(args.ledger.resolve()),
                "dependency_map": str(args.dependency_map.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
