from __future__ import annotations

import importlib
import sys


def test_stage00_package_import_is_lazy():
    package_name = "src.stage_00_data"
    root_package = importlib.import_module("src")
    original_package_attr = getattr(root_package, "stage_00_data", None)
    eager_modules = [
        "src.stage_00_data.company_descriptions",
        "src.stage_00_data.filing_retrieval",
        "src.stage_00_data.peer_similarity",
        "src.stage_00_data.sec_filing_metrics",
    ]

    module_names = [package_name, *eager_modules]
    original_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in module_names
    }
    try:
        for module_name in module_names:
            sys.modules.pop(module_name, None)

        package = importlib.import_module(package_name)

        assert package.__name__ == package_name
        assert [
            module_name
            for module_name in eager_modules
            if module_name in sys.modules
        ] == []
    finally:
        for module_name in module_names:
            sys.modules.pop(module_name, None)
        for module_name, module in original_modules.items():
            if module is not None:
                sys.modules[module_name] = module
        if original_package_attr is not None:
            root_package.stage_00_data = original_package_attr
