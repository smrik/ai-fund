"""Capital IQ ingestion package."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CIQWorkbookPayload",
    "CIQTemplateContractError",
    "IngestReport",
    "ingest_ciq_folder",
    "parse_ciq_workbook",
]


def __getattr__(name: str):
    if name in {"IngestReport", "ingest_ciq_folder"}:
        module = import_module("ciq.ingest")
        return getattr(module, name)
    if name in {"CIQWorkbookPayload", "CIQTemplateContractError", "parse_ciq_workbook"}:
        module = import_module("ciq.workbook_parser")
        return getattr(module, name)
    raise AttributeError(name)
