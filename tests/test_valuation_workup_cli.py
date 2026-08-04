from __future__ import annotations

from io import StringIO
import json
from types import SimpleNamespace

from src.contracts.ticker_runs import TerminalStatus
from src.stage_04_pipeline.valuation_workup_cli import main


class _Manifest:
    def __init__(self, statuses: tuple[TerminalStatus, ...]) -> None:
        self.records = tuple(
            SimpleNamespace(status=status) for status in statuses
        )

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "records": [
                {"status": record.status.value}
                for record in self.records
            ],
            "requested_count": len(self.records),
        }


def test_cli_uses_same_provider_bindings_and_batch_service() -> None:
    output = StringIO()
    observed: dict[str, object] = {}
    bindings = object()

    def binding_builder(settings):
        observed["settings"] = settings
        return bindings

    def runner(requests, **kwargs):
        observed["requests"] = tuple(requests)
        observed["kwargs"] = kwargs
        return _Manifest(
            (
                TerminalStatus.decision_grade,
                TerminalStatus.provisional,
            )
        )

    exit_code = main(
        [
            "MSFT",
            "calm",
            "--analysis-as-of",
            "2026-07-26",
            "--captured-at",
            "2026-07-26T20:00:00Z",
            "--execution-run-id",
            "trace-run",
            "--max-workers",
            "4",
            "--max-in-flight",
            "2",
        ],
        environment={
            "ALPHA_POD_JUDGMENT_BACKEND": "codex",
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "primary-model",
            "ALPHA_POD_JUDGMENT_CRITIC_MODEL": "critic-model",
        },
        binding_builder=binding_builder,
        workup_runner=runner,
        stdout=output,
    )

    assert exit_code == 0
    assert observed["requests"] == ("MSFT", "calm")
    kwargs = observed["kwargs"]
    assert kwargs["execution_run_id"] == "trace-run"
    assert kwargs["captured_at"] == "2026-07-26T20:00:00Z"
    assert kwargs["bindings"] is bindings
    assert kwargs["max_workers"] == 4
    assert kwargs["max_in_flight"] == 2
    payload = json.loads(output.getvalue())
    assert payload["execution_run_id"] == "trace-run"
    assert payload["manifest"]["requested_count"] == 2


def test_cli_returns_nonzero_without_dropping_blocked_records() -> None:
    output = StringIO()

    exit_code = main(
        [
            "MSFT",
            "--analysis-as-of",
            "2026-07-26",
            "--execution-run-id",
            "blocked-run",
        ],
        environment={
            "ALPHA_POD_JUDGMENT_BACKEND": "codex",
            "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": "model",
        },
        binding_builder=lambda _settings: {},
        workup_runner=lambda _requests, **_kwargs: _Manifest(
            (TerminalStatus.blocked,)
        ),
        stdout=output,
    )

    assert exit_code == 2
    payload = json.loads(output.getvalue())
    assert payload["manifest"]["records"] == [
        {"status": "blocked"}
    ]
