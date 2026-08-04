from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_importing_xbrl_statement_evidence_configures_edgar_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("EDGAR_IDENTITY", None)
    env.pop("EDGAR_LOCAL_DATA_DIR", None)
    script = """
import json
import os

from src.stage_00_data import xbrl_evidence  # noqa: F401
from edgar import get_identity

print(json.dumps({
    "identity": get_identity(),
    "data_dir": os.environ.get("EDGAR_LOCAL_DATA_DIR"),
}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    runtime = json.loads(completed.stdout.strip())
    assert runtime["identity"]
    assert Path(runtime["data_dir"]) == repo_root / "data" / "cache" / "edgar_tools"
