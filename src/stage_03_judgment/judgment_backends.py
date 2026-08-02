"""Explicit provider transports for the provider-neutral judgment gateway."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from pydantic import BaseModel

from src.stage_03_judgment.judgment_gateway import (
    JudgmentBackendRequest,
    JudgmentBackendResponse,
)

_CODEX_STRUCTURED_PREAMBLE = (
    "Complete one structured judgment request using only the conversation "
    "messages below. Do not use tools. Do not read or write files. Do not "
    "run commands. Return exactly one JSON object matching the supplied "
    "output schema, with no Markdown fence, prose, or extra keys."
)
_UNSAFE_LAUNCHER_SUFFIXES = {".bat", ".cmd", ".ps1"}
_CODEX_ISOLATION_OVERRIDES = (
    "features.artifact=false",
    "features.shell_tool=false",
    "features.apps=false",
    "features.browser_use=false",
    "features.browser_use_external=false",
    "features.browser_use_full_cdp_access=false",
    "features.code_mode=false",
    "features.code_mode_host=false",
    "features.computer_use=false",
    "features.goals=false",
    "features.image_generation=false",
    "features.multi_agent=false",
    "features.plugin_sharing=false",
    "features.plugins=false",
    "features.remote_plugin=false",
    "features.hooks=false",
    "features.request_permissions_tool=false",
    "features.skill_mcp_dependency_install=false",
    "features.skill_search=false",
    "features.tool_suggest=false",
    "features.unified_exec=false",
    "features.workspace_dependencies=false",
    'web_search="disabled"',
    "mcp_servers={}",
    "shell_environment_policy.inherit=none",
)
_CODEX_ENV_PASSTHROUGH = (
    "ALL_PROXY",
    "CODEX_API_KEY",
    "CODEX_HOME",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SystemRoot",
    "WINDIR",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
_TRANSIENT_CODEX_FAILURE_MARKERS = (
    "429 too many requests",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
    "bad gateway",
    "connection aborted",
    "connection refused",
    "connection reset",
    "dns",
    "failed to send request",
    "gateway timeout",
    "network error",
    "rate limit",
    "service unavailable",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "too many requests",
)
_SAFE_CODEX_EVENT_ITEMS = {
    "agent_message",
    "error",
    "reasoning",
    "todo_list",
}


def _native_codex_executable(launcher: str) -> str:
    """Resolve npm script shims to the packaged native Codex executable.

    Windows launches ``.cmd`` wrappers through ``cmd.exe`` even when
    ``shell=False``. Provider-controlled route values would therefore cross a
    command-string boundary, and killing the wrapper on timeout would not
    reliably kill its child. Run the packaged native executable directly.
    """

    launcher_path = Path(launcher)
    if launcher_path.suffix.lower() not in _UNSAFE_LAUNCHER_SUFFIXES:
        return launcher

    package_root = (
        launcher_path.parent
        / "node_modules"
        / "@openai"
        / "codex"
    )
    executable_name = "codex.exe" if os.name == "nt" else "codex"
    candidates = sorted(
        {
            *package_root.glob(
                f"node_modules/@openai/codex-*/vendor/*/bin/{executable_name}"
            ),
            *package_root.glob(f"vendor/*/bin/{executable_name}"),
        }
    )
    if len(candidates) != 1:
        raise RuntimeError(
            "Codex launcher is a script shim and a unique packaged native "
            "executable could not be resolved"
        )
    return str(candidates[0])


def _is_transient_codex_failure(detail: str) -> bool:
    normalized = detail.casefold()
    return any(
        marker in normalized
        for marker in _TRANSIENT_CODEX_FAILURE_MARKERS
    )


def _codex_token_count(
    usage: dict[str, Any],
    field_name: str,
) -> int | None:
    value = usage.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(
            f"codex exec emitted invalid {field_name} metadata"
        )
    return value


def _parse_codex_trace(stdout: str) -> dict[str, Any]:
    provider_request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "codex exec emitted invalid JSON event metadata"
            ) from exc
        if not isinstance(event, dict):
            raise RuntimeError(
                "codex exec emitted a non-object JSON event"
            )
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id.strip():
                raise RuntimeError(
                    "codex exec emitted an invalid thread identifier"
                )
            if (
                provider_request_id is not None
                and provider_request_id != thread_id
            ):
                raise RuntimeError(
                    "codex exec emitted conflicting thread identifiers"
                )
            provider_request_id = thread_id
        elif event_type == "turn.completed":
            usage = event.get("usage")
            if not isinstance(usage, dict):
                raise RuntimeError(
                    "codex exec emitted invalid turn usage metadata"
                )
            prompt_tokens = _codex_token_count(
                usage,
                "input_tokens",
            )
            completion_tokens = _codex_token_count(
                usage,
                "output_tokens",
            )
        elif event_type in {
            "item.started",
            "item.updated",
            "item.completed",
        }:
            item = event.get("item")
            item_type = (
                item.get("type") if isinstance(item, dict) else None
            )
            if item_type not in _SAFE_CODEX_EVENT_ITEMS:
                raise RuntimeError(
                    f"prohibited Codex tool event: {item_type}"
                )
    total_tokens = (
        prompt_tokens + completion_tokens
        if prompt_tokens is not None and completion_tokens is not None
        else None
    )
    return {
        "provider_request_id": provider_request_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _repair_message(errors: tuple[str, ...]) -> dict[str, str]:
    details = "\n".join(f"- {error}" for error in errors)
    return {
        "role": "user",
        "content": (
            "The previous response failed the required schema. Return a complete "
            "JSON object only and correct these validator errors:\n"
            f"{details}"
        ),
    }


def _normalized_output(message: Any) -> Any:
    parsed = getattr(message, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump(mode="json")
    if parsed is not None:
        return parsed
    return getattr(message, "content", None)


class CodexCLIJudgmentBackend:
    """Isolated Codex CLI transport for the shared structured contract."""

    def __init__(
        self,
        *,
        runner: Any = None,
        executable: str | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._executable = _native_codex_executable(
            executable or shutil.which("codex") or "codex"
        )

    @staticmethod
    def _environment(temp_dir: str) -> dict[str, str]:
        env = {
            key: value
            for key in _CODEX_ENV_PASSTHROUGH
            if (value := os.environ.get(key)) is not None
        }
        env.setdefault(
            "CODEX_HOME",
            str(Path.home() / ".codex"),
        )
        env["TEMP"] = temp_dir
        env["TMP"] = temp_dir
        env["TMPDIR"] = temp_dir
        agents_home = Path(temp_dir) / "agents-home"
        (agents_home / "skills").mkdir(parents=True, exist_ok=True)
        env["AGENTS_HOME"] = str(agents_home)
        return env

    @staticmethod
    def _prompt(request: JudgmentBackendRequest) -> str:
        messages = [
            message.model_dump(mode="json")
            for message in request.task.messages
        ]
        if request.validation_errors:
            messages.append(_repair_message(request.validation_errors))
        serialized_messages = json.dumps(
            messages,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            f"{_CODEX_STRUCTURED_PREAMBLE}\n\n"
            f"Ordered conversation messages (JSON):\n"
            f"{serialized_messages}"
        )

    @staticmethod
    def _validate_route(request: JudgmentBackendRequest) -> None:
        if request.route.provider.strip().lower() != "codex":
            raise ValueError("Codex backend requires provider='codex'")
        if request.route.adapter_id.strip().lower() != "codex-exec":
            raise ValueError(
                "Codex backend requires adapter_id='codex-exec'"
            )
        if (
            request.route.endpoint_capability.strip().lower()
            != "exec:json-schema"
        ):
            raise ValueError(
                "Codex backend requires "
                "endpoint_capability='exec:json-schema'"
            )
        sampling = request.route.sampling
        unsupported = tuple(
            name
            for name in (
                "temperature",
                "top_p",
                "max_output_tokens",
                "seed",
                "stop",
            )
            if getattr(sampling, name) not in (None, ())
        )
        if unsupported:
            raise ValueError(
                "Codex backend does not support sampling controls: "
                f"{', '.join(unsupported)}"
            )

    def generate(
        self,
        request: JudgmentBackendRequest,
    ) -> JudgmentBackendResponse:
        self._validate_route(request)
        with tempfile.TemporaryDirectory(
            prefix="alpha-pod-codex-structured-"
        ) as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "output-schema.json"
            output_path = temp_path / "last-message.json"
            schema_path.write_text(
                json.dumps(
                    request.output_schema,
                    allow_nan=False,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            command = [
                self._executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--strict-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "-C",
                temp_dir,
                "-m",
                request.route.requested_model,
            ]
            for override in _CODEX_ISOLATION_OVERRIDES:
                command.extend(["-c", override])
            reasoning_effort = request.route.sampling.reasoning_effort
            if reasoning_effort is not None:
                command.extend(
                    ["-c", f"model_reasoning_effort={reasoning_effort}"]
                )
            command.extend(
                [
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "--json",
                    "-",
                ]
            )
            try:
                completed = self._runner(
                    command,
                    input=self._prompt(request),
                    text=True,
                    capture_output=True,
                    timeout=request.transport_timeout_seconds,
                    check=False,
                    cwd=temp_dir,
                    env=self._environment(temp_dir),
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(
                    "codex exec exceeded the transport timeout"
                ) from exc
            if completed.returncode != 0:
                stderr = str(
                    getattr(completed, "stderr", "") or ""
                ).strip()
                stdout = str(
                    getattr(completed, "stdout", "") or ""
                ).strip()
                failure_text = stderr or stdout
                detail = (
                    f": {failure_text[:500]}" if failure_text else ""
                )
                message = (
                    "codex exec exited with status "
                    f"{completed.returncode}{detail}"
                )
                if _is_transient_codex_failure(failure_text):
                    raise ConnectionError(message)
                raise RuntimeError(
                    message
                )
            try:
                output = output_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise RuntimeError(
                    "codex exec did not produce its output file"
                ) from exc
            if not output:
                raise RuntimeError("codex exec produced empty output")
            trace = _parse_codex_trace(
                str(getattr(completed, "stdout", "") or "")
            )

        return JudgmentBackendResponse(
            output=output,
            actual_model=(
                "requested-unattested:"
                f"{request.route.requested_model}"
            ),
            provider_request_id=trace["provider_request_id"],
            prompt_tokens=trace["prompt_tokens"],
            completion_tokens=trace["completion_tokens"],
            total_tokens=trace["total_tokens"],
        )


class OpenAICompatibleJudgmentBackend:
    """Chat-completions transport with no process-global routing decisions."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def generate(
        self,
        request: JudgmentBackendRequest,
    ) -> JudgmentBackendResponse:
        route = request.route
        sampling = route.sampling
        messages = [
            message.model_dump(mode="json")
            for message in request.task.messages
        ]
        if request.validation_errors:
            messages.append(_repair_message(request.validation_errors))

        kwargs: dict[str, Any] = {
            "model": route.requested_model,
            "messages": messages,
            "timeout": request.transport_timeout_seconds,
        }
        for field_name, api_name in (
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("max_output_tokens", "max_tokens"),
            ("seed", "seed"),
        ):
            value = getattr(sampling, field_name)
            if value is not None:
                kwargs[api_name] = value
        if sampling.reasoning_effort is not None:
            kwargs["extra_body"] = {
                "reasoning": {"effort": sampling.reasoning_effort}
            }
        if sampling.stop:
            kwargs["stop"] = list(sampling.stop)

        capability = route.endpoint_capability.lower()
        if "json-schema" in capability or capability in {
            "structured",
            "native",
        }:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_schema.get("title")
                    or request.task.schema_id,
                    "strict": True,
                    "schema": request.output_schema,
                },
            }

        response = self._client.chat.completions.create(**kwargs)
        choices = getattr(response, "choices", ())
        if not choices:
            raise ValueError("provider response contains no choices")
        choice = choices[0]
        usage = getattr(response, "usage", None)
        return JudgmentBackendResponse(
            output=_normalized_output(choice.message),
            actual_model=getattr(response, "model", None)
            or route.requested_model,
            provider_request_id=getattr(response, "id", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            finish_reason=getattr(choice, "finish_reason", None),
        )
