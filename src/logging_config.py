"""Shared logging helpers for Alpha Pod command-line entry points."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record for file-based logs."""

    _EXTRA_FIELDS = ("ticker", "step", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(*, force: bool = False, level: str | None = None) -> logging.Logger:
    """Configure root logging for CLI execution."""

    root_logger = logging.getLogger()
    if getattr(root_logger, "_alpha_pod_configured", False) and not force:
        return root_logger

    if force:
        root_logger.handlers.clear()

    resolved_level = (level or os.getenv("ALPHA_POD_LOG_LEVEL", "INFO")).upper()
    root_logger.setLevel(resolved_level)

    handlers: list[logging.Handler] = []
    try:
        if sys.stdout.isatty():
            from rich.console import Console
            from rich.logging import RichHandler

            console = Console(file=sys.stdout)
            console_handler: logging.Handler = RichHandler(
                console=console,
                show_time=False,
                show_level=False,
                show_path=False,
                markup=False,
                rich_tracebacks=True,
            )
        else:
            console_handler = logging.StreamHandler(sys.stdout)
    except Exception:
        console_handler = logging.StreamHandler(sys.stdout)

    console_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(console_handler)

    log_file = os.getenv("ALPHA_POD_LOG_FILE")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    root_logger._alpha_pod_configured = True  # type: ignore[attr-defined]
    return root_logger
