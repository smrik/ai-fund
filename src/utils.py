"""Shared utility primitives for Alpha Pod.

Canonical implementations of helpers that were previously duplicated across
12+ modules.  Every module should import from here instead of defining its
own ``_now()``, ``_coerce_ticker()``, or ``_safe_float()``.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision).

    Example: ``'2026-05-05T11:01:03'``
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def coerce_ticker(value: str) -> str:
    """Normalise and validate a ticker string.

    Returns the uppercased, stripped ticker.
    Raises ``ValueError`` if the result is empty.
    """
    ticker = (value or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    return ticker


def safe_float(value: Any) -> float | None:
    """Coerce *value* to ``float`` if possible, else return ``None``.

    Handles ``int``, ``float``, and numeric strings.
    """
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
