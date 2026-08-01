"""Command-line entry point for the reconciled valuation workup service."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
import os
import sys
from typing import Any, Callable, Mapping, Sequence, TextIO

from src.contracts.ticker_runs import TerminalStatus
from src.stage_04_pipeline.valuation_provider_bindings import (
    ProviderBindingSettings,
    build_driver_family_bindings,
)
from config.llm_routing import format_llm_resolution, resolve_llm_route
from src.stage_04_pipeline.valuation_workup_service import (
    run_persisted_valuation_workups,
)

_logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the same reconciled, no-drop valuation path for one "
            "or more tickers."
        )
    )
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--analysis-as-of", required=True)
    parser.add_argument("--execution-run-id", required=True)
    parser.add_argument("--captured-at")
    parser.add_argument("--batch-run-id")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument(
        "--transport-timeout-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--batch-timeout-seconds",
        type=float,
        default=900.0,
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--primary-model")
    parser.add_argument("--critic-model")
    parser.add_argument("--base-url")
    parser.add_argument("--endpoint-capability")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--codex-executable")
    return parser


def _settings_environment(
    arguments: argparse.Namespace,
    environment: Mapping[str, str],
) -> dict[str, str]:
    resolved = dict(environment)
    overrides = {
        "ALPHA_POD_JUDGMENT_BACKEND": arguments.provider,
        "ALPHA_POD_JUDGMENT_PRIMARY_MODEL": (
            arguments.primary_model
        ),
        "ALPHA_POD_JUDGMENT_CRITIC_MODEL": arguments.critic_model,
        "ALPHA_POD_JUDGMENT_BASE_URL": arguments.base_url,
        "ALPHA_POD_JUDGMENT_ENDPOINT_CAPABILITY": (
            arguments.endpoint_capability
        ),
        "ALPHA_POD_JUDGMENT_REASONING_EFFORT": (
            arguments.reasoning_effort
        ),
        "ALPHA_POD_CODEX_EXECUTABLE": arguments.codex_executable,
    }
    for name, value in overrides.items():
        if value is not None:
            resolved[name] = str(value)
    return resolved


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    binding_builder: Callable[..., Any] = (
        build_driver_family_bindings
    ),
    workup_runner: Callable[..., Any] = (
        run_persisted_valuation_workups
    ),
    stdout: TextIO | None = None,
) -> int:
    """Run a valuation batch and emit its complete terminal manifest."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        analysis_as_of = date.fromisoformat(
            arguments.analysis_as_of
        )
    except ValueError as exc:
        parser.error(f"invalid --analysis-as-of: {exc}")

    source_environment = (
        os.environ if environment is None else environment
    )
    settings_environment = _settings_environment(
        arguments, source_environment
    )
    llm_routing = resolve_llm_route(
        "valuation",
        cli_provider=arguments.provider,
        cli_model=arguments.primary_model,
        cli_effort=arguments.reasoning_effort,
        env=settings_environment,
        model_env_names=("ALPHA_POD_JUDGMENT_PRIMARY_MODEL",),
    )
    settings_environment.setdefault(
        "ALPHA_POD_JUDGMENT_BACKEND", str(llm_routing["provider"])
    )
    settings_environment.setdefault(
        "ALPHA_POD_JUDGMENT_PRIMARY_MODEL", str(llm_routing["model"])
    )
    if llm_routing.get("effort"):
        settings_environment.setdefault(
            "ALPHA_POD_JUDGMENT_REASONING_EFFORT",
            str(llm_routing["effort"]),
        )
    _logger.info(format_llm_resolution(llm_routing))
    try:
        settings = ProviderBindingSettings.from_environment(
            settings_environment
        )
    except ValueError as exc:
        parser.error(str(exc))

    captured_at = arguments.captured_at or datetime.now(
        timezone.utc
    ).isoformat()
    bindings = binding_builder(settings)
    manifest = workup_runner(
        arguments.tickers,
        execution_run_id=arguments.execution_run_id,
        analysis_as_of=analysis_as_of,
        captured_at=captured_at,
        bindings=bindings,
        max_workers=arguments.max_workers,
        batch_run_id=arguments.batch_run_id,
        transport_timeout_seconds=(
            arguments.transport_timeout_seconds
        ),
        batch_timeout_seconds=arguments.batch_timeout_seconds,
        max_in_flight=arguments.max_in_flight,
        force_refresh=arguments.force_refresh,
    )
    payload = {
        "execution_run_id": arguments.execution_run_id,
        "provider": settings.backend,
        "primary_model": settings.primary_model,
        "critic_model": settings.critic_model,
        "llm_routing": llm_routing,
        "analysis_as_of": analysis_as_of.isoformat(),
        "captured_at": captured_at,
        "manifest": manifest.model_dump(mode="json"),
    }
    destination = stdout or sys.stdout
    json.dump(payload, destination, indent=2, sort_keys=True)
    destination.write("\n")

    has_blocker = any(
        (
            getattr(record.status, "value", record.status)
            == TerminalStatus.blocked.value
        )
        for record in manifest.records
    )
    return 2 if has_blocker else 0


if __name__ == "__main__":
    raise SystemExit(main())
