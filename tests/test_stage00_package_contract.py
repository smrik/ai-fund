from __future__ import annotations

import importlib
import sys


def test_stage00_package_import_is_lazy():
    package_name = "src.stage_00_data"
    eager_modules = [
        "src.stage_00_data.company_descriptions",
        "src.stage_00_data.filing_retrieval",
        "src.stage_00_data.peer_similarity",
        "src.stage_00_data.sec_filing_metrics",
    ]

    for module_name in [package_name, *eager_modules]:
        sys.modules.pop(module_name, None)

    package = importlib.import_module(package_name)

    assert package.__name__ == package_name
    assert [module_name for module_name in eager_modules if module_name in sys.modules] == []
