"""Tests for story driver pending YAML approval flow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
import pytest

from src.stage_03_judgment.thesis_agent import write_story_driver_pending
from src.stage_02_valuation.story_drivers import (
    _load_approved_pending,
    _normalize_profile,
    resolve_story_driver_profile,
    load_story_driver_overrides,
)


# ── write_story_driver_pending ────────────────────────────────────────────────

def test_write_creates_pending_yaml(tmp_path):
    profile = {
        "moat_strength": 4,
        "pricing_power": 4,
        "cyclicality": "low",
        "capital_intensity": "medium",
        "governance_risk": "low",
        "competitive_advantage_years": 10,
        "rationale": "Strong software IP moats and recurring revenue.",
    }
    out = tmp_path / "story_drivers_pending.yaml"
    path = write_story_driver_pending("IBM", profile, path=out)
    assert path.exists()
    data = yaml.safe_load(out.read_text())
    assert "IBM" in data
    entry = data["IBM"]
    assert entry["status"] == "pending"
    assert entry["profile"]["moat_strength"] == 4
    assert entry["profile"]["cyclicality"] == "low"
    assert entry["rationale"] == "Strong software IP moats and recurring revenue."


def test_write_preserves_existing_entries(tmp_path):
    out = tmp_path / "story_drivers_pending.yaml"
    existing = {"AAPL": {"status": "approved", "profile": {"moat_strength": 5}}}
    out.write_text(yaml.dump(existing))

    write_story_driver_pending("IBM", {"moat_strength": 3}, path=out)
    data = yaml.safe_load(out.read_text())
    assert "AAPL" in data
    assert "IBM" in data


def test_write_updates_existing_ticker_entry(tmp_path):
    out = tmp_path / "story_drivers_pending.yaml"
    write_story_driver_pending("IBM", {"moat_strength": 3}, path=out)
    write_story_driver_pending("IBM", {"moat_strength": 5}, path=out)
    data = yaml.safe_load(out.read_text())
    assert data["IBM"]["profile"]["moat_strength"] == 5


def test_write_defaults_missing_fields(tmp_path):
    out = tmp_path / "story_drivers_pending.yaml"
    write_story_driver_pending("IBM", {}, path=out)
    data = yaml.safe_load(out.read_text())
    profile = data["IBM"]["profile"]
    assert profile["moat_strength"] == 3
    assert profile["competitive_advantage_years"] == 7


# ── _load_approved_pending ────────────────────────────────────────────────────

def test_load_approved_pending_returns_profile_when_approved(tmp_path, monkeypatch):
    import src.stage_02_valuation.story_drivers as module
    pending_path = tmp_path / "story_drivers_pending.yaml"
    content = {
        "IBM": {
            "status": "approved",
            "profile": {
                "moat_strength": 4,
                "pricing_power": 4,
                "cyclicality": "low",
                "capital_intensity": "medium",
                "governance_risk": "low",
                "competitive_advantage_years": 10,
            },
        }
    }
    pending_path.write_text(yaml.dump(content))
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", pending_path)

    result = _load_approved_pending("IBM")
    assert result is not None
    assert result["moat_strength"] == 4


def test_load_approved_pending_returns_none_when_pending(tmp_path, monkeypatch):
    import src.stage_02_valuation.story_drivers as module
    pending_path = tmp_path / "story_drivers_pending.yaml"
    content = {"IBM": {"status": "pending", "profile": {"moat_strength": 4}}}
    pending_path.write_text(yaml.dump(content))
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", pending_path)

    result = _load_approved_pending("IBM")
    assert result is None


def test_load_approved_pending_missing_file_returns_none(tmp_path, monkeypatch):
    import src.stage_02_valuation.story_drivers as module
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", tmp_path / "nonexistent.yaml")
    assert _load_approved_pending("IBM") is None


def test_load_approved_pending_unknown_ticker_returns_none(tmp_path, monkeypatch):
    import src.stage_02_valuation.story_drivers as module
    pending_path = tmp_path / "story_drivers_pending.yaml"
    pending_path.write_text(yaml.dump({"IBM": {"status": "approved", "profile": {}}}))
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", pending_path)
    assert _load_approved_pending("MSFT") is None


# ── resolve_story_driver_profile with pending approval ───────────────────────

def test_resolve_uses_approved_pending_over_static_yaml(tmp_path, monkeypatch):
    """Approved pending entry should override sector defaults."""
    import src.stage_02_valuation.story_drivers as module

    pending_path = tmp_path / "story_drivers_pending.yaml"
    content = {
        "IBM": {
            "status": "approved",
            "profile": {
                "moat_strength": 5,
                "pricing_power": 5,
                "cyclicality": "low",
                "capital_intensity": "low",
                "governance_risk": "low",
                "competitive_advantage_years": 15,
            },
        }
    }
    pending_path.write_text(yaml.dump(content))
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", pending_path)

    profile, source = resolve_story_driver_profile("IBM", "Technology")
    assert source == "story_ticker_pending_approved"
    assert profile.moat_strength == 5
    assert profile.competitive_advantage_years == 15


def test_resolve_ignores_pending_entry_when_not_approved(tmp_path, monkeypatch):
    import src.stage_02_valuation.story_drivers as module

    pending_path = tmp_path / "story_drivers_pending.yaml"
    content = {"IBM": {"status": "pending", "profile": {"moat_strength": 5}}}
    pending_path.write_text(yaml.dump(content))
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", pending_path)

    # Should fall back to sector or global
    profile, source = resolve_story_driver_profile("IBM", "Technology")
    assert source in ("story_sector", "story_global", "story_ticker")
    assert source != "story_ticker_pending_approved"


def test_resolve_sector_used_when_no_ticker_override(monkeypatch, tmp_path):
    import src.stage_02_valuation.story_drivers as module
    monkeypatch.setattr(module, "STORY_DRIVERS_PENDING_PATH", tmp_path / "nonexistent.yaml")

    profile, source = resolve_story_driver_profile("ZZZUNKNOWN", "Technology")
    # Technology sector has moat_strength=4 in story_drivers.yaml
    assert profile.moat_strength == 4
    assert source == "story_sector"
