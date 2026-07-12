from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the focused accounting agent on a fictional, non-workspace fixture."
    )
    parser.add_argument("--codex-executable", required=True, type=Path)
    parser.add_argument("--codex-home", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--effort", default="high")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "agent_evaluations" / "synthetic_accounting.json",
    )
    args = parser.parse_args()

    executable = args.codex_executable.resolve()
    codex_home = args.codex_home.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    if not (codex_home / "auth.json").is_file():
        raise FileNotFoundError(f"Codex home must contain auth.json: {codex_home}")

    os.environ["CODEX_HOME"] = str(codex_home)
    os.environ["ALPHA_POD_AGENT_BACKEND"] = "codex"
    os.environ["ALPHA_POD_CODEX_EXECUTABLE"] = str(executable)
    os.environ["ALPHA_POD_CODEX_MODEL"] = str(args.model)
    os.environ["ALPHA_POD_CODEX_EFFORT"] = str(args.effort)
    os.environ["ALPHA_POD_CODEX_ALLOW_FALLBACK"] = "0"
    os.environ["ALPHA_POD_CODEX_TIMEOUT_SECONDS"] = "300"

    from src.contracts.accounting_evidence import (
        AccountingFocusKey,
        AccountingPacketStatus,
        AccountingTopic,
    )
    from src.contracts.evidence_packet import EvidencePacketFact, TextEvidenceSnippet
    from src.stage_03_judgment.focused_accounting_agent import FocusedAccountingAgent
    from src.stage_04_pipeline.accounting_focus import AccountingFocusContext

    context = AccountingFocusContext(
        focus_key=AccountingFocusKey.qoe_nonrecurring,
        parent_topic=AccountingTopic.qoe,
        ticker="SYNTH",
        period_vintage_metadata={
            "periods": ["2025-12-31"],
            "vintages": [{"filing_date": "2026-02-15", "form_type": "10-K"}],
        },
        selected_facts=[
            EvidencePacketFact(
                fact_id="fact:synthetic:reported_ebit",
                fact_name="reported_ebit",
                value=2000.0,
                unit="USD mm",
                metadata={"period": "2025-12-31", "fact_role": "reported_historical_anchor"},
            ),
            EvidencePacketFact(
                fact_id="fact:synthetic:restructuring",
                fact_name="restructuring_charge",
                value=120.0,
                unit="USD mm",
                metadata={"period": "2025-12-31", "fact_role": "xbrl_structured_fact"},
            ),
            EvidencePacketFact(
                fact_id="fact:synthetic:margin_target",
                fact_name="ebit_margin_target",
                value=0.30,
                unit=None,
                metadata={"fact_role": "current_model_driver", "driver_field": "ebit_margin_target"},
            ),
        ],
        selected_snippets=[
            TextEvidenceSnippet(
                snippet_id="snippet:synthetic:restructuring",
                source_ref_id="filing:synthetic:2025-10-k",
                text=(
                    "The company recorded a $120 million restructuring charge in 2025. "
                    "Management expects another $80 million of related charges in 2026."
                ),
                metadata={"filing_date": "2026-02-15", "section_key": "note_restructuring"},
            )
        ],
        selected_driver_fields={"ebit_margin_target": 0.30},
        packet_status=AccountingPacketStatus.partial,
        missing_data_status="partial_coverage",
        coverage_notes=[
            "The fixture has no program history before 2025 and no cash-payment schedule."
        ],
    )

    agent = FocusedAccountingAgent(model=str(args.model))
    result = agent.analyze_focus(context)
    payload = {
        "fixture": "fictional_non_workspace_data",
        "result": asdict(result),
        "artifact": agent.last_focused_accounting_artifact,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(output)
    print(f"status={result.status}")
    print(f"accepted_findings={len((result.response or {}).get('findings') or [])}")
    return 0 if result.response is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

