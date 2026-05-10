# Assumption Register Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Build a typed `AssumptionRegister` that attaches to every valuation run, records each DCF driver with its source, accepted range, and flag level, and surfaces that register through the batch runner, JSON exporter, and override workbench.

**Architecture:** A new `assumption_register.py` module defines the Pydantic contracts (`AssumptionRegisterEntry`, `AssumptionRegister`) and the range-rule table. `build_assumption_register()` takes a completed `ValuationInputsWithLineage` and produces a register. The batch runner populates it after `build_valuation_inputs()` and passes it to the JSON exporter. The override workbench reads it so the dashboard can surface flags. No LLM touches this path — it is entirely deterministic.

**Tech Stack:** Python 3.13, Pydantic v2 (already a dep via FastAPI), existing `valuation_types.py` dataclass pattern, pytest.

---

## Task 1: Define the contracts in `assumption_register.py`

**Files:**
- Create: `src/stage_02_valuation/assumption_register.py`
- Test: `tests/test_assumption_register.py`

**Step 1: Write the failing test**

```python
# tests/test_assumption_register.py
from src.stage_02_valuation.assumption_register import (
    AssumptionOwner,
    FlagLevel,
    AssumptionRegisterEntry,
    AssumptionRegister,
)

def test_entry_in_range_has_no_flag():
    e = AssumptionRegisterEntry(
        assumption_name="revenue_growth_near",
        proposed_value=0.08,
        accepted_low=0.02,
        accepted_high=0.20,
        range_rule_id="revenue_growth_default",
        source="yfinance_cagr_3yr",
        flag_level=FlagLevel.none,
        owner=AssumptionOwner.deterministic,
    )
    assert e.flag_level == FlagLevel.none
    assert e.out_of_range is False

def test_entry_out_of_range_detected():
    e = AssumptionRegisterEntry(
        assumption_name="ebit_margin_start",
        proposed_value=0.55,
        accepted_low=0.05,
        accepted_high=0.40,
        range_rule_id="ebit_margin_default",
        source="yfinance",
        flag_level=FlagLevel.review_required,
        owner=AssumptionOwner.deterministic,
    )
    assert e.out_of_range is True

def test_register_holds_entries_and_counts_flags():
    entries = [
        AssumptionRegisterEntry(
            assumption_name="revenue_growth_near",
            proposed_value=0.08,
            accepted_low=0.02,
            accepted_high=0.20,
            range_rule_id="revenue_growth_default",
            source="yfinance_cagr_3yr",
            flag_level=FlagLevel.none,
            owner=AssumptionOwner.deterministic,
        ),
        AssumptionRegisterEntry(
            assumption_name="ebit_margin_start",
            proposed_value=0.55,
            accepted_low=0.05,
            accepted_high=0.40,
            range_rule_id="ebit_margin_default",
            source="yfinance",
            flag_level=FlagLevel.review_required,
            owner=AssumptionOwner.deterministic,
        ),
    ]
    reg = AssumptionRegister(ticker="AAPL", entries=entries)
    assert reg.flag_count(FlagLevel.review_required) == 1
    assert reg.flag_count(FlagLevel.none) == 1
    assert reg.has_critical is False
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_assumption_register.py -x -q
```
Expected: ImportError — module does not exist yet.

**Step 3: Implement the contracts**

Create `src/stage_02_valuation/assumption_register.py`:

```python
"""Typed assumption register contract for deterministic valuation runs."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AssumptionOwner(str, Enum):
    deterministic = "deterministic"
    pm_override = "pm_override"
    blocked = "blocked"


class FlagLevel(str, Enum):
    none = "none"
    watch = "watch"
    review_required = "review_required"
    critical = "critical"


_FLAG_RANK = {
    FlagLevel.none: 0,
    FlagLevel.watch: 1,
    FlagLevel.review_required: 2,
    FlagLevel.critical: 3,
}


class AssumptionRegisterEntry(BaseModel):
    assumption_name: str
    proposed_value: float
    accepted_low: float
    accepted_high: float
    range_rule_id: str
    source: str
    flag_level: FlagLevel
    owner: AssumptionOwner
    notes: str = ""

    @property
    def out_of_range(self) -> bool:
        return not (self.accepted_low <= self.proposed_value <= self.accepted_high)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_name": self.assumption_name,
            "proposed_value": self.proposed_value,
            "accepted_low": self.accepted_low,
            "accepted_high": self.accepted_high,
            "range_rule_id": self.range_rule_id,
            "source": self.source,
            "flag_level": self.flag_level.value,
            "owner": self.owner.value,
            "out_of_range": self.out_of_range,
            "notes": self.notes,
        }


class AssumptionRegister(BaseModel):
    ticker: str
    entries: list[AssumptionRegisterEntry] = Field(default_factory=list)

    def flag_count(self, level: FlagLevel) -> int:
        return sum(1 for e in self.entries if e.flag_level == level)

    @property
    def has_critical(self) -> bool:
        return any(e.flag_level == FlagLevel.critical for e in self.entries)

    @property
    def max_flag_level(self) -> FlagLevel:
        if not self.entries:
            return FlagLevel.none
        return max(self.entries, key=lambda e: _FLAG_RANK[e.flag_level]).flag_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "max_flag_level": self.max_flag_level.value,
            "has_critical": self.has_critical,
            "flag_counts": {lvl.value: self.flag_count(lvl) for lvl in FlagLevel},
            "entries": [e.to_dict() for e in self.entries],
        }
```

**Step 4: Run tests**

```
pytest tests/test_assumption_register.py -x -q
```
Expected: 3 passed.

**Step 5: Commit**

```bash
git add src/stage_02_valuation/assumption_register.py tests/test_assumption_register.py
git commit -m "feat: add AssumptionRegister and AssumptionRegisterEntry contracts"
```

---

## Task 2: Add the range-rule table and flag computation

**Files:**
- Modify: `src/stage_02_valuation/assumption_register.py`
- Modify: `tests/test_assumption_register.py`

The range-rule table encodes the P0 #2 defaults from the action plan. Each rule maps a metric name to `(accepted_low, accepted_high, rule_id)`. Ranges are expressed as fractions (not percent) for margin/growth; raw values for multiples and days.

**Step 1: Add tests for range-rule lookup and `_flag_for_value()`**

Add to `tests/test_assumption_register.py`:

```python
from src.stage_02_valuation.assumption_register import flag_for_value, RANGE_RULES

def test_flag_for_value_in_range():
    assert flag_for_value(0.08, 0.02, 0.20) == FlagLevel.none

def test_flag_for_value_watch_boundary():
    # Just outside — watch, not review_required
    assert flag_for_value(0.21, 0.02, 0.20) == FlagLevel.watch

def test_flag_for_value_far_out_of_range():
    # >2× the width outside → review_required
    assert flag_for_value(0.60, 0.02, 0.20) == FlagLevel.review_required

def test_range_rules_covers_core_drivers():
    for key in ("revenue_growth_near", "ebit_margin_start", "tax_rate_start",
                "capex_pct_start", "da_pct_start", "wacc", "exit_multiple"):
        assert key in RANGE_RULES, f"Missing range rule for {key}"
```

**Step 2: Run tests to verify they fail**

```
pytest tests/test_assumption_register.py -x -q
```
Expected: ImportError on `flag_for_value, RANGE_RULES`.

**Step 3: Implement range rules and flag logic**

Add to `src/stage_02_valuation/assumption_register.py` (before the `AssumptionRegisterEntry` class):

```python
# (low, high, rule_id)
RANGE_RULES: dict[str, tuple[float, float, str]] = {
    "revenue_growth_near":   (0.00,  0.30, "revenue_growth_default"),
    "revenue_growth_mid":    (-0.02, 0.20, "revenue_growth_mid_default"),
    "ebit_margin_start":     (0.00,  0.45, "ebit_margin_default"),
    "ebit_margin_target":    (0.00,  0.50, "ebit_margin_target_default"),
    "tax_rate_start":        (0.10,  0.35, "tax_rate_default"),
    "tax_rate_target":       (0.10,  0.35, "tax_rate_default"),
    "capex_pct_start":       (0.01,  0.20, "capex_pct_default"),
    "capex_pct_target":      (0.01,  0.15, "capex_pct_target_default"),
    "da_pct_start":          (0.01,  0.15, "da_pct_default"),
    "da_pct_target":         (0.01,  0.12, "da_pct_target_default"),
    "dso_start":             (10.0, 120.0, "dso_default"),
    "dio_start":             (0.0,  180.0, "dio_default"),
    "dpo_start":             (10.0, 120.0, "dpo_default"),
    "wacc":                  (0.05,  0.18, "wacc_default"),
    "exit_multiple":         (4.0,   25.0, "exit_multiple_default"),
    "ronic_terminal":        (0.04,  0.20, "ronic_terminal_default"),
    "terminal_blend_gordon_weight": (0.0, 1.0, "blend_weight_default"),
}


def flag_for_value(value: float, low: float, high: float) -> FlagLevel:
    """Deterministic flag from range bounds. Watch = just outside, review_required = far outside."""
    if low <= value <= high:
        return FlagLevel.none
    width = high - low
    distance = min(abs(value - low), abs(value - high))
    if distance <= 0.10 * width + 1e-9:
        return FlagLevel.watch
    return FlagLevel.review_required
```

**Step 4: Run tests**

```
pytest tests/test_assumption_register.py -x -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/stage_02_valuation/assumption_register.py tests/test_assumption_register.py
git commit -m "feat: add RANGE_RULES table and flag_for_value() logic"
```

---

## Task 3: `build_assumption_register()` — assembles a register from valuation inputs

**Files:**
- Modify: `src/stage_02_valuation/assumption_register.py`
- Modify: `tests/test_assumption_register.py`

**Step 1: Write failing test**

Add to `tests/test_assumption_register.py`:

```python
from src.stage_02_valuation.assumption_register import build_assumption_register
from src.stage_02_valuation.valuation_types import ForecastDrivers

def _minimal_drivers() -> ForecastDrivers:
    return ForecastDrivers(
        revenue_base=10_000.0,
        revenue_growth_near=0.08,
        revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025,
        ebit_margin_start=0.18,
        ebit_margin_target=0.22,
        tax_rate_start=0.21,
        tax_rate_target=0.21,
        capex_pct_start=0.05,
        capex_pct_target=0.04,
        da_pct_start=0.04,
        da_pct_target=0.04,
        dso_start=45.0,
        dso_target=45.0,
        dio_start=30.0,
        dio_target=30.0,
        dpo_start=35.0,
        dpo_target=35.0,
        wacc=0.09,
        exit_multiple=12.0,
        exit_metric="ev_ebitda",
        net_debt=500.0,
        shares_outstanding=100.0,
    )

def test_build_assumption_register_returns_register():
    drivers = _minimal_drivers()
    lineage = {"revenue_growth_near": "yfinance_cagr_3yr", "ebit_margin_start": "ciq"}
    reg = build_assumption_register("AAPL", drivers, lineage)
    assert reg.ticker == "AAPL"
    assert len(reg.entries) > 0

def test_build_assumption_register_in_range_drivers_have_no_flag():
    drivers = _minimal_drivers()
    reg = build_assumption_register("AAPL", drivers, {})
    flagged = [e for e in reg.entries if e.flag_level != FlagLevel.none]
    assert len(flagged) == 0

def test_build_assumption_register_out_of_range_driver_is_flagged():
    drivers = _minimal_drivers()
    drivers = ForecastDrivers(**{**drivers.__dict__, "ebit_margin_start": 0.80})
    reg = build_assumption_register("AAPL", drivers, {})
    flagged = [e for e in reg.entries if e.assumption_name == "ebit_margin_start"]
    assert flagged[0].flag_level != FlagLevel.none

def test_build_assumption_register_lineage_flows_to_source():
    drivers = _minimal_drivers()
    lineage = {"ebit_margin_start": "ciq"}
    reg = build_assumption_register("AAPL", drivers, lineage)
    entry = next(e for e in reg.entries if e.assumption_name == "ebit_margin_start")
    assert entry.source == "ciq"
```

**Step 2: Run tests to verify they fail**

```
pytest tests/test_assumption_register.py::test_build_assumption_register_returns_register -x -q
```
Expected: ImportError on `build_assumption_register`.

**Step 3: Implement `build_assumption_register()`**

Add to `src/stage_02_valuation/assumption_register.py`:

```python
from src.stage_02_valuation.valuation_types import ForecastDrivers


def build_assumption_register(
    ticker: str,
    drivers: ForecastDrivers,
    source_lineage: dict[str, str],
) -> AssumptionRegister:
    """Build a fully-flagged assumption register from a completed ForecastDrivers."""
    driver_values: dict[str, float] = {
        "revenue_growth_near":          drivers.revenue_growth_near,
        "revenue_growth_mid":           drivers.revenue_growth_mid,
        "ebit_margin_start":            drivers.ebit_margin_start,
        "ebit_margin_target":           drivers.ebit_margin_target,
        "tax_rate_start":               drivers.tax_rate_start,
        "tax_rate_target":              drivers.tax_rate_target,
        "capex_pct_start":              drivers.capex_pct_start,
        "capex_pct_target":             drivers.capex_pct_target,
        "da_pct_start":                 drivers.da_pct_start,
        "da_pct_target":                drivers.da_pct_target,
        "dso_start":                    drivers.dso_start,
        "dio_start":                    drivers.dio_start,
        "dpo_start":                    drivers.dpo_start,
        "wacc":                         drivers.wacc,
        "exit_multiple":                drivers.exit_multiple,
        "ronic_terminal":               drivers.ronic_terminal,
        "terminal_blend_gordon_weight": drivers.terminal_blend_gordon_weight,
    }

    entries: list[AssumptionRegisterEntry] = []
    for name, value in driver_values.items():
        if name not in RANGE_RULES:
            continue
        low, high, rule_id = RANGE_RULES[name]
        flag = flag_for_value(value, low, high)
        owner = AssumptionOwner.deterministic
        if source_lineage.get(name) == "pm_override":
            owner = AssumptionOwner.pm_override
        entries.append(AssumptionRegisterEntry(
            assumption_name=name,
            proposed_value=value,
            accepted_low=low,
            accepted_high=high,
            range_rule_id=rule_id,
            source=source_lineage.get(name, "derived"),
            flag_level=flag,
            owner=owner,
        ))

    return AssumptionRegister(ticker=ticker, entries=entries)
```

**Step 4: Run tests**

```
pytest tests/test_assumption_register.py -x -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/stage_02_valuation/assumption_register.py tests/test_assumption_register.py
git commit -m "feat: implement build_assumption_register() from ForecastDrivers + lineage"
```

---

## Task 4: Wire into `batch_runner.py`

**Files:**
- Modify: `src/stage_02_valuation/batch_runner.py` (around `value_single_ticker`)
- Modify: `tests/test_batch_runner_professional.py`

The batch runner already calls `build_valuation_inputs()` and has access to `drivers` and `source_lineage`. Wire `build_assumption_register()` after that call and attach the result to the output row as `assumption_register_json`.

**Step 1: Write failing test**

Find the test that exercises `value_single_ticker` in `tests/test_batch_runner_professional.py`. Add:

```python
def test_value_single_ticker_result_has_assumption_register(monkeypatch):
    """assumption_register_json is present and has entries."""
    import json
    from tests.test_batch_runner_professional import _make_minimal_mkt  # reuse existing helper

    # Use existing monkeypatch fixture from nearby test if available,
    # or replicate the minimal mock pattern already in the file.
    # The key assertion is on the result dict key.
    result = _run_minimal_ticker(monkeypatch)  # helper defined in next step
    assert "assumption_register_json" in result
    reg = json.loads(result["assumption_register_json"])
    assert "entries" in reg
    assert len(reg["entries"]) > 0
```

Check the existing test file first to understand existing helper patterns before writing `_run_minimal_ticker`. Match the existing mock style exactly.

**Step 2: Run test to verify it fails**

```
pytest tests/test_batch_runner_professional.py::test_value_single_ticker_result_has_assumption_register -x -q
```
Expected: either KeyError or the helper doesn't exist yet.

**Step 3: Wire `build_assumption_register()` into `value_single_ticker()`**

In `src/stage_02_valuation/batch_runner.py`, find where `valuation_inputs` is built:

```python
# existing pattern (approximately):
valuation_inputs = build_valuation_inputs(ticker, ...)
if valuation_inputs is None:
    ...
drivers = valuation_inputs.drivers
```

After that block, add:

```python
from src.stage_02_valuation.assumption_register import build_assumption_register
import json as _json

assumption_register = build_assumption_register(
    ticker,
    drivers,
    valuation_inputs.source_lineage,
)
```

Then in the result dict assembly, add:

```python
"assumption_register_json": _json.dumps(assumption_register.to_dict()),
```

**Step 4: Run tests**

```
pytest tests/test_batch_runner_professional.py -x -q
```
Expected: all pass including the new test.

**Step 5: Commit**

```bash
git add src/stage_02_valuation/batch_runner.py tests/test_batch_runner_professional.py
git commit -m "feat: wire assumption_register into batch_runner result row"
```

---

## Task 5: Wire into `json_exporter.py`

**Files:**
- Modify: `src/stage_02_valuation/json_exporter.py`
- Modify: `tests/test_json_exporter.py`

The JSON exporter builds the nested ticker payload. The assumption register should appear as a top-level `assumption_register` section — same pattern as `scenarios`, `wacc`, etc.

**Step 1: Write failing test**

In `tests/test_json_exporter.py`, add `assumption_register_json` to `MINIMAL_RESULT` (the test fixture dict) and assert the exported section exists:

```python
# Add to MINIMAL_RESULT dict (already defined at top of test file):
# "assumption_register_json": json.dumps({"ticker": "IBM", "entries": [], "max_flag_level": "none", ...})

def test_json_contains_assumption_register_section(tmp_dir):
    import json as _json
    result_with_reg = dict(MINIMAL_RESULT)
    result_with_reg["assumption_register_json"] = _json.dumps({
        "ticker": "IBM",
        "max_flag_level": "none",
        "has_critical": False,
        "flag_counts": {"none": 1, "watch": 0, "review_required": 0, "critical": 0},
        "entries": [{"assumption_name": "wacc", "proposed_value": 0.09,
                     "accepted_low": 0.05, "accepted_high": 0.18,
                     "range_rule_id": "wacc_default", "source": "derived",
                     "flag_level": "none", "owner": "deterministic",
                     "out_of_range": False, "notes": ""}],
    })
    dated = export_ticker_json(result_with_reg, output_dir=tmp_dir, date_str="2026-01-01")
    content = _json.loads(dated.read_text())
    assert "assumption_register" in content
    assert content["assumption_register"]["max_flag_level"] == "none"
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_json_exporter.py::test_json_contains_assumption_register_section -x -q
```
Expected: AssertionError — section missing.

**Step 3: Add `assumption_register` to `build_nested_structure()`**

In `src/stage_02_valuation/json_exporter.py`, find `build_nested_structure()`. Add:

```python
# near the other _safe_json_loads() calls:
"assumption_register": _safe_json_loads(result.get("assumption_register_json")) or {},
```

**Step 4: Run tests**

```
pytest tests/test_json_exporter.py -x -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add src/stage_02_valuation/json_exporter.py tests/test_json_exporter.py
git commit -m "feat: add assumption_register section to json_exporter nested output"
```

---

## Task 6: Surface flags in `override_workbench.py`

**Files:**
- Modify: `src/stage_04_pipeline/override_workbench.py`
- Test: no new test file — extend existing workbench test if one exists, or assert on the dict key in a minimal inline test

The override workbench returns a dict from `build_override_workbench(ticker)`. Add an `assumption_register` key to that dict so the dashboard can surface flag counts and per-assumption detail without a separate API call.

**Step 1: Write failing test**

```python
# tests/test_override_workbench_assumption_register.py
import pytest
from unittest.mock import patch, MagicMock
from src.stage_04_pipeline.override_workbench import build_override_workbench

def _fake_valuation_inputs(apply_overrides=True):
    from src.stage_02_valuation.valuation_types import ForecastDrivers
    from src.stage_02_valuation.input_assembler import ValuationInputsWithLineage
    drivers = ForecastDrivers(
        revenue_base=10_000.0, revenue_growth_near=0.08, revenue_growth_mid=0.05,
        revenue_growth_terminal=0.025, ebit_margin_start=0.18, ebit_margin_target=0.22,
        tax_rate_start=0.21, tax_rate_target=0.21, capex_pct_start=0.05,
        capex_pct_target=0.04, da_pct_start=0.04, da_pct_target=0.04,
        dso_start=45.0, dso_target=45.0, dio_start=30.0, dio_target=30.0,
        dpo_start=35.0, dpo_target=35.0, wacc=0.09, exit_multiple=12.0,
        exit_metric="ev_ebitda", net_debt=500.0, shares_outstanding=100.0,
    )
    return ValuationInputsWithLineage(
        ticker="FAKE", company_name="Fake Co", sector="Technology", industry="Software",
        current_price=100.0, as_of_date=None, model_applicability_status="dcf_applicable",
        drivers=drivers, source_lineage={}, ciq_lineage={}, wacc_inputs={},
    )

def test_build_override_workbench_includes_assumption_register(monkeypatch):
    monkeypatch.setattr(
        "src.stage_04_pipeline.override_workbench.build_valuation_inputs",
        _fake_valuation_inputs,
    )
    result = build_override_workbench("FAKE")
    assert "assumption_register" in result
    assert "entries" in result["assumption_register"]
    assert "max_flag_level" in result["assumption_register"]
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_override_workbench_assumption_register.py -x -q
```
Expected: KeyError — key not present.

**Step 3: Add assumption register to `build_override_workbench()`**

In `src/stage_04_pipeline/override_workbench.py`, find `build_override_workbench()`. After building `effective_inputs`, add:

```python
from src.stage_02_valuation.assumption_register import build_assumption_register

assumption_register = build_assumption_register(
    ticker,
    effective_inputs.drivers,
    effective_inputs.source_lineage,
)
```

Then add to the returned dict:

```python
"assumption_register": assumption_register.to_dict(),
```

**Step 4: Run tests**

```
pytest tests/test_override_workbench_assumption_register.py -x -q
```
Expected: pass.

**Step 5: Commit**

```bash
git add src/stage_04_pipeline/override_workbench.py tests/test_override_workbench_assumption_register.py
git commit -m "feat: surface assumption_register in override_workbench payload"
```

---

## Task 7: Full suite check and doc update

**Step 1: Run the full test bundle for this branch**

```
pytest tests/test_assumption_register.py tests/test_json_exporter.py tests/test_batch_runner_professional.py tests/test_override_workbench_assumption_register.py -q
```
Expected: all pass, no errors.

**Step 2: Update the action plan doc**

In `docs/design-docs/valuation-methodology-critical-review-and-action-plan.md`, mark P0 #1 ("Define the assumption register as an executable contract") and P0 #2 ("Make accepted ranges deterministic by default") as implemented. Add a one-line note: "Implemented in `src/stage_02_valuation/assumption_register.py` — range rules are in `RANGE_RULES`, flags computed by `flag_for_value()`."

**Step 3: Commit docs**

```bash
git add docs/design-docs/valuation-methodology-critical-review-and-action-plan.md
git commit -m "docs: mark P0 #1 and P0 #2 implemented in action plan"
```

---

## Notes for the implementer

- `ForecastDrivers` is a `dataclass(slots=True)` — you cannot do `drivers.__dict__`. Use `dataclasses.asdict(drivers)` or access fields directly.
- The test file `tests/test_batch_runner_professional.py` already has a detailed mock pattern for `value_single_ticker`. Read it before writing Task 4's test — match the existing helper style exactly rather than inventing a new one.
- `_safe_json_loads()` is already defined in `json_exporter.py` — use it as-is for Task 5.
- Keep `assumption_register.py` import-safe: the `from src.stage_02_valuation.valuation_types import ForecastDrivers` import inside `build_assumption_register()` avoids any circular import risk.
