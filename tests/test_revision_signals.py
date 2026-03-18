"""Tests for earnings revision tracker and revision signal integration."""
import importlib
import sqlite3
import sys
from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy optional dependencies that live in stage_00_data's __init__.py
# chain (edgar, etc.) so pytest can collect this file without network packages.
# We stub at the sys.modules level before any imports from src.stage_00_data.
# ---------------------------------------------------------------------------

for _mod in [
    "edgar",
    "src.stage_00_data.edgar_client",
    "src.stage_00_data.company_descriptions",
    "src.stage_00_data.filing_retrieval",
    "src.stage_00_data.peer_similarity",
    "src.stage_00_data.sec_filing_metrics",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from src.stage_02_valuation.revision_signals import get_revision_growth_bias, REVISION_GROWTH_BIAS
from src.stage_00_data.estimate_tracker import RevisionSignals, get_revision_signals


# ---------------------------------------------------------------------------
# REVISION_GROWTH_BIAS mapping tests
# ---------------------------------------------------------------------------

def test_revision_momentum_bias_mapping():
    """REVISION_GROWTH_BIAS must contain all 6 expected momentum keys."""
    expected_keys = {
        "strong_positive",
        "positive",
        "neutral",
        "negative",
        "strong_negative",
        "unavailable",
    }
    assert expected_keys == set(REVISION_GROWTH_BIAS.keys())


def test_get_revision_growth_bias_unavailable_returns_zero():
    """When estimate_tracker returns unavailable RevisionSignals, bias must be 0.0."""
    unavailable_sigs = RevisionSignals(
        ticker="TEST",
        revision_breadth_30d=None,
        eps_revision_30d_pct=None,
        revenue_revision_30d_pct=None,
        eps_revision_90d_pct=None,
        revenue_revision_90d_pct=None,
        estimate_dispersion=None,
        revision_momentum="unavailable",
        num_analysts=None,
        as_of_date="2026-01-01",
        available=False,
        error=None,
    )

    # The function imports get_revision_signals at call time from estimate_tracker,
    # so we patch it at its definition site.
    with patch(
        "src.stage_00_data.estimate_tracker.get_revision_signals",
        return_value=unavailable_sigs,
    ):
        bias, source = get_revision_growth_bias("TEST")

    assert bias == 0.0
    assert "unavailable" in source


def test_revision_momentum_strong_positive_bias():
    """strong_positive momentum must yield +0.015 additive growth bias."""
    positive_sigs = RevisionSignals(
        ticker="TEST",
        revision_breadth_30d=None,
        eps_revision_30d_pct=0.08,
        revenue_revision_30d_pct=None,
        eps_revision_90d_pct=None,
        revenue_revision_90d_pct=None,
        estimate_dispersion=None,
        revision_momentum="strong_positive",
        num_analysts=10,
        as_of_date="2026-01-01",
        available=True,
        error=None,
    )

    with patch(
        "src.stage_00_data.estimate_tracker.get_revision_signals",
        return_value=positive_sigs,
    ):
        bias, source = get_revision_growth_bias("TEST")

    assert bias == pytest.approx(0.015)
    assert "strong_positive" in source


def test_revision_momentum_strong_negative_bias():
    """strong_negative momentum must yield -0.015 additive growth bias."""
    negative_sigs = RevisionSignals(
        ticker="TEST",
        revision_breadth_30d=None,
        eps_revision_30d_pct=-0.08,
        revenue_revision_30d_pct=None,
        eps_revision_90d_pct=None,
        revenue_revision_90d_pct=None,
        estimate_dispersion=None,
        revision_momentum="strong_negative",
        num_analysts=10,
        as_of_date="2026-01-01",
        available=True,
        error=None,
    )

    with patch(
        "src.stage_00_data.estimate_tracker.get_revision_signals",
        return_value=negative_sigs,
    ):
        bias, source = get_revision_growth_bias("TEST")

    assert bias == pytest.approx(-0.015)
    assert "strong_negative" in source


def test_get_revision_growth_bias_exception_safe():
    """If get_revision_signals raises, returns (0.0, 'revision_unavailable') without raising."""
    with patch(
        "src.stage_00_data.estimate_tracker.get_revision_signals",
        side_effect=RuntimeError("DB exploded"),
    ):
        bias, source = get_revision_growth_bias("BOOM")

    assert bias == 0.0
    assert source == "revision_unavailable"


# ---------------------------------------------------------------------------
# estimate_tracker tests
# ---------------------------------------------------------------------------

def test_get_revision_signals_no_data_returns_unavailable():
    """With an empty DB (fewer than 2 rows), RevisionSignals.available must be False."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.commit.return_value = None

    with patch("src.stage_00_data.estimate_tracker.get_connection", return_value=mock_conn):
        sigs = get_revision_signals("EMPTY")

    assert sigs.available is False
    assert sigs.ticker == "EMPTY"


def test_revision_signals_dataclass_fields():
    """RevisionSignals must expose all required fields as a dataclass."""
    field_names = {f.name for f in fields(RevisionSignals)}
    required = {
        "ticker",
        "revision_breadth_30d",
        "eps_revision_30d_pct",
        "revenue_revision_30d_pct",
        "eps_revision_90d_pct",
        "revenue_revision_90d_pct",
        "estimate_dispersion",
        "revision_momentum",
        "num_analysts",
        "as_of_date",
        "available",
        "error",
    }
    assert required.issubset(field_names)
