# Grill Fixes — MVP Cut

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Close the actionable P0 items from the valuation methodology critical review that make the pipeline trustworthy for PM testing. Three focused commits — no forecast scoping (deferred), no duplicate plumbing.

**Architecture:** Additive changes to `src/contracts/`, `src/stage_02_valuation/`, and `src/stage_02_valuation/wacc.py`. No new LLM calls, no broad refactors. Each task adds one or two files and tests, then a GitHub issue is opened for any deferred V2 work.

**Tech Stack:** Python 3.13, Pydantic V2, pytest, existing `src/contracts/assumption_register.py`, `src/stage_02_valuation/assumption_register.py`, `src/stage_02_valuation/wacc.py`, `src/stage_02_valuation/batch_runner.py`.

---

## Pre-Flight — Read These Before Touching Anything

```
src/contracts/assumption_register.py          — DEFAULT_ACCEPTED_RANGES, FlagLevel, AssumptionRegister
src/stage_02_valuation/assumption_register.py — CRITICAL_DIAGNOSTICS, REVIEW_DIAGNOSTICS,
                                                 _apply_diagnostic_rollup (uses object.__setattr__)
src/stage_02_valuation/wacc.py:478-500        — compute_wacc_methodology_set_for_ticker()
src/stage_02_valuation/batch_runner.py:598-612 — register_diagnostics assembly
src/stage_02_valuation/professional_dcf.py:501 — terminal_ronic_guardrail_flag already computed
src/stage_03_judgment/forensic_scores.py:381  — forensic_flag values: "red", "amber", "green"
src/contracts/peer_universe.py                — does NOT exist yet
tests/test_assumption_register.py             — prior art for test style
tests/conftest.py                             — tmp_path override (use if test needs temp dirs)
```

**Key facts confirmed before writing this plan:**

- `terminal_ronic_guardrail_flag` is already computed in `professional_dcf.py:501` as
  `bool(d.ronic_terminal <= terminal_growth + 0.005)` (uses raw `d.ronic_terminal`). It flows
  through as `health_terminal_ronic_guardrail_flag` in `register_diagnostics`. It is NOT in
  `CRITICAL_DIAGNOSTICS`. Adding it there is 1 line.
- `forensic_flag` lives at `row.get("forensic_flag")` (top-level flat key in the batch row
  from `qoe_signals`). Values: `"red"` (manipulator zone), `"amber"` (caution), `"green"`.
- `revenue_growth_terminal` accepted high is `0.05` — must be `0.04`.
- `AssumptionRegister.notes` is a `dict`, not a string.
- `_apply_diagnostic_rollup` mutates the register with `object.__setattr__` — safe for dicts.
- `PeerCandidate.composite_score` weight breakdown: biz=0.35, metric=0.35, sector=0.15, size=0.15.
  `sector_score = 1.0` only when both `sector_match AND industry_match`. With only
  `sector_match=True`, `sector_score = 0.6` → composite ≈ 0.72 → `peripheral`, not `core`.

---

## Task A: `peer_universe.py` Contract

The grill session named this as the second contract after assumption_register. It is foundational for the comps workbench (TD-03 replacement path).

**Files:**
- Create: `src/contracts/peer_universe.py`
- Create: `tests/test_peer_universe_contract.py`

### Step 1: Write the failing tests

```python
# tests/test_peer_universe_contract.py
import pytest
from src.contracts.peer_universe import PeerCandidate, PeerUniverse, InclusionState


def test_peer_candidate_core_when_both_sector_and_industry_match():
    """Both sector + industry match → sector_score=1.0 → should reach core threshold."""
    c = PeerCandidate(
        target_ticker="AAPL",
        peer_ticker="MSFT",
        sources=["ciq"],
        sector_match=True,
        industry_match=True,
        business_description_similarity=0.80,
        metric_similarity=0.72,
        size_similarity=0.65,
        growth_similarity=0.60,
        margin_similarity=0.70,
        capital_intensity_similarity=0.55,
    )
    # composite = 0.80*0.35 + 0.72*0.35 + 1.0*0.15 + 0.65*0.15 = 0.28+0.252+0.15+0.0975 = 0.7795
    assert c.composite_score == pytest.approx(0.7795, abs=0.01)
    assert c.inclusion_state == InclusionState.core


def test_peer_candidate_peripheral_when_sector_only():
    """sector_match only (no industry) → sector_score=0.6 → peripheral range."""
    c = PeerCandidate(
        target_ticker="AAPL",
        peer_ticker="GOOG",
        sources=["ciq"],
        sector_match=True,
        industry_match=False,
        business_description_similarity=0.70,
        metric_similarity=0.65,
        size_similarity=0.60,
        growth_similarity=0.55,
        margin_similarity=0.60,
        capital_intensity_similarity=0.50,
    )
    # composite = 0.70*0.35 + 0.65*0.35 + 0.6*0.15 + 0.60*0.15 = 0.245+0.2275+0.09+0.09 = 0.6525
    assert c.composite_score == pytest.approx(0.6525, abs=0.01)
    assert c.inclusion_state == InclusionState.peripheral


def test_peer_candidate_excluded_below_threshold():
    c = PeerCandidate(
        target_ticker="X", peer_ticker="Y", sources=["test"],
        sector_match=False, industry_match=False,
        business_description_similarity=0.30, metric_similarity=0.30,
        size_similarity=0.30, growth_similarity=0.30,
        margin_similarity=0.30, capital_intensity_similarity=0.30,
    )
    assert c.inclusion_state == InclusionState.excluded


def test_peer_universe_core_peers_list():
    c = PeerCandidate(
        target_ticker="AAPL", peer_ticker="MSFT", sources=["ciq"],
        sector_match=True, industry_match=True,
        business_description_similarity=0.90, metric_similarity=0.85,
        size_similarity=0.80, growth_similarity=0.75,
        margin_similarity=0.80, capital_intensity_similarity=0.70,
    )
    u = PeerUniverse(target_ticker="AAPL", candidates=[c])
    assert "MSFT" in u.core_peers
    assert u.peripheral_peers == []


def test_peer_universe_round_trip():
    c = PeerCandidate(
        target_ticker="AAPL", peer_ticker="MSFT", sources=["ciq"],
        sector_match=True, industry_match=True,
        business_description_similarity=0.9, metric_similarity=0.8,
        size_similarity=0.7, growth_similarity=0.7,
        margin_similarity=0.8, capital_intensity_similarity=0.6,
    )
    u = PeerUniverse(target_ticker="AAPL", candidates=[c])
    dumped = u.model_dump(mode="json")
    restored = PeerUniverse.model_validate(dumped)
    assert restored.target_ticker == "AAPL"
    assert restored.core_peers == ["MSFT"]


def test_pm_override_promotes_excluded_peer():
    c = PeerCandidate(
        target_ticker="X", peer_ticker="Y", sources=["pm"],
        sector_match=False, industry_match=False,
        business_description_similarity=0.20, metric_similarity=0.20,
        size_similarity=0.20, growth_similarity=0.20,
        margin_similarity=0.20, capital_intensity_similarity=0.20,
        pm_override_state="included",
        pm_override_reason="Closest proxy available",
    )
    assert c.inclusion_state == InclusionState.excluded    # raw score still low
    assert c.effective_inclusion == InclusionState.core    # PM override wins


def test_tickers_uppercased():
    c = PeerCandidate(
        target_ticker="aapl", peer_ticker="msft", sources=[],
        sector_match=True, industry_match=True,
        business_description_similarity=0.8, metric_similarity=0.8,
        size_similarity=0.8, growth_similarity=0.8,
        margin_similarity=0.8, capital_intensity_similarity=0.8,
    )
    assert c.target_ticker == "AAPL"
    assert c.peer_ticker == "MSFT"
```

Run: `pytest tests/test_peer_universe_contract.py -v`
Expected: ImportError (module not yet created)

### Step 2: Implement `src/contracts/peer_universe.py`

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

PEER_UNIVERSE_CONTRACT_VERSION = "1.0"

W_BIZ = 0.35       # business description similarity
W_METRIC = 0.35    # metric similarity
W_SECTOR = 0.15    # sector/industry match
W_SIZE = 0.15      # size similarity

CORE_THRESHOLD = 0.75
PERIPHERAL_THRESHOLD = 0.55


class InclusionState(str, Enum):
    core = "core"
    peripheral = "peripheral"
    excluded = "excluded"


class ContractModel(BaseModel):
    model_config = {"extra": "ignore", "populate_by_name": True}


class PeerCandidate(ContractModel):
    contract_version: str = PEER_UNIVERSE_CONTRACT_VERSION
    target_ticker: str
    peer_ticker: str
    sources: list[str] = Field(default_factory=list)

    sector_match: bool = False
    industry_match: bool = False

    business_description_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    metric_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    size_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    growth_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    margin_similarity: float = Field(ge=0.0, le=1.0, default=0.0)
    capital_intensity_similarity: float = Field(ge=0.0, le=1.0, default=0.0)

    pm_override_state: Literal["included", "excluded", None] = None
    pm_override_reason: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def composite_score(self) -> float:
        sector_score = (
            1.0 if (self.sector_match and self.industry_match)
            else 0.6 if self.sector_match
            else 0.0
        )
        return (
            W_BIZ * self.business_description_similarity
            + W_METRIC * self.metric_similarity
            + W_SECTOR * sector_score
            + W_SIZE * self.size_similarity
        )

    @computed_field  # type: ignore[misc]
    @property
    def inclusion_state(self) -> InclusionState:
        if self.composite_score >= CORE_THRESHOLD:
            return InclusionState.core
        if self.composite_score >= PERIPHERAL_THRESHOLD:
            return InclusionState.peripheral
        return InclusionState.excluded

    @computed_field  # type: ignore[misc]
    @property
    def effective_inclusion(self) -> InclusionState:
        if self.pm_override_state == "included":
            return InclusionState.core
        if self.pm_override_state == "excluded":
            return InclusionState.excluded
        return self.inclusion_state

    @model_validator(mode="after")
    def _uppercase_tickers(self) -> "PeerCandidate":
        object.__setattr__(self, "target_ticker", self.target_ticker.upper().strip())
        object.__setattr__(self, "peer_ticker", self.peer_ticker.upper().strip())
        return self


class PeerUniverse(ContractModel):
    contract_version: str = PEER_UNIVERSE_CONTRACT_VERSION
    target_ticker: str
    candidates: list[PeerCandidate] = Field(default_factory=list)
    build_source: str = "system"
    notes: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def core_peers(self) -> list[str]:
        return [c.peer_ticker for c in self.candidates
                if c.effective_inclusion == InclusionState.core]

    @computed_field  # type: ignore[misc]
    @property
    def peripheral_peers(self) -> list[str]:
        return [c.peer_ticker for c in self.candidates
                if c.effective_inclusion == InclusionState.peripheral]

    @model_validator(mode="after")
    def _uppercase_ticker(self) -> "PeerUniverse":
        object.__setattr__(self, "target_ticker", self.target_ticker.upper().strip())
        return self
```

### Step 3: Run tests

`pytest tests/test_peer_universe_contract.py -v`
Expected: 7 passed

### Step 4: Commit

```
git add src/contracts/peer_universe.py tests/test_peer_universe_contract.py
git commit -m "feat: add PeerUniverse and PeerCandidate contracts with composite scoring (#53-followup)"
```

**Open GitHub issue now:**
```bash
gh issue create \
  --title "V2: wire PeerUniverse into comps workbench and batch runner (replaces TD-03)" \
  --label "area:valuation,priority:p2,type:feature" \
  --body "PeerCandidate/PeerUniverse contracts in src/contracts/peer_universe.py. Next: wire composite scoring into batch runner peer selection, replace get_peer_multiples() returning self with real ranked candidates. Relates to TD-03 in tech-debt-tracker."
```

---

## Task B: Extend Diagnostic Rollup (All Four Diagnostics, One Commit)

Four small wires into the same diagnostic machinery. Do them together to avoid merge conflicts on `CRITICAL_DIAGNOSTICS`, `REVIEW_DIAGNOSTICS`, and `_apply_diagnostic_rollup`.

**Files:**
- Modify: `src/stage_02_valuation/assumption_register.py` (CRITICAL_DIAGNOSTICS, REVIEW_DIAGNOSTICS, _apply_diagnostic_rollup)
- Modify: `src/stage_02_valuation/wacc.py` (add method-spread computation)
- Modify: `src/stage_02_valuation/input_assembler.py` (pass wacc_method_spread_high)
- Modify: `src/stage_02_valuation/batch_runner.py` (add forensic_flag_severe + regime_label to register_diagnostics)
- Modify: `tests/test_assumption_register.py` (four new tests)

### Step 1: Write four failing tests

```python
# Add to tests/test_assumption_register.py

# ── helpers reused across tests ────────────────────────────────────────────

def _base_inputs(**driver_overrides):
    """Minimal FakeInputs for assumption_register tests."""
    base_drivers = dict(
        revenue_growth_near=0.08, revenue_growth_mid=0.05,
        ebit_margin_start=0.20, ebit_margin_target=0.22,
        tax_rate_start=0.21, tax_rate_target=0.21,
        capex_pct_start=0.05, capex_pct_target=0.05,
        da_pct_start=0.04, da_pct_target=0.04,
        dso_start=45.0, dso_target=45.0,
        dio_start=0.0, dio_target=0.0,
        dpo_start=30.0, dpo_target=30.0,
        wacc=0.09, exit_multiple=15.0,
        ronic_terminal=0.12, revenue_growth_terminal=0.025,
    )
    base_drivers.update(driver_overrides)

    class FakeInputs:
        wacc_inputs = {
            "wacc": 0.09, "risk_free_rate": 0.045, "equity_risk_premium": 0.05,
            "beta_relevered": 1.0, "size_premium": 0.01, "cost_of_debt": 0.05,
            "equity_weight": 0.8, "debt_weight": 0.2, "cost_of_equity": 0.11,
        }
        drivers = type("D", (), base_drivers)()
        source_lineage = {}
        model_applicability_status = "dcf_applicable"

    return FakeInputs()


def test_ronic_guardrail_flag_critical():
    """health_terminal_ronic_guardrail_flag=True must produce critical trust state."""
    from src.stage_02_valuation.assumption_register import build_assumption_register
    from src.contracts.assumption_register import ModelTrustState

    reg = build_assumption_register(
        "TEST", _base_inputs(),
        diagnostics={"health_terminal_ronic_guardrail_flag": True},
    )
    assert reg.model_trust_state in (
        ModelTrustState.critical_review_required.value,
        ModelTrustState.critical_review_required,
    )


def test_wacc_method_spread_flags_review():
    """wacc_method_spread_high=True must produce at least review_required trust state."""
    from src.stage_02_valuation.assumption_register import build_assumption_register
    from src.contracts.assumption_register import ModelTrustState, FlagLevel

    reg = build_assumption_register(
        "TEST", _base_inputs(),
        diagnostics={"wacc_method_spread_high": True},
    )
    assert reg.model_trust_state not in (
        ModelTrustState.clean.value, ModelTrustState.watch.value,
        ModelTrustState.clean, ModelTrustState.watch,
    )


def test_forensic_red_flag_critical():
    """forensic_flag_severe=True must degrade trust state to critical or degraded."""
    from src.stage_02_valuation.assumption_register import build_assumption_register
    from src.contracts.assumption_register import ModelTrustState

    reg = build_assumption_register(
        "TEST", _base_inputs(),
        diagnostics={"forensic_flag_severe": True},
    )
    assert reg.model_trust_state in (
        ModelTrustState.critical_review_required.value,
        ModelTrustState.critical_review_required,
    )


def test_regime_label_in_register_notes():
    """regime_weights_applied=True must store regime label in register.notes dict."""
    from src.stage_02_valuation.assumption_register import build_assumption_register

    reg = build_assumption_register(
        "TEST", _base_inputs(),
        diagnostics={"regime_label": "Risk-Off", "regime_weights_applied": True},
    )
    assert "regime_label" in reg.notes
    assert reg.notes["regime_label"] == "Risk-Off"
```

Run: `pytest tests/test_assumption_register.py::test_ronic_guardrail_flag_critical tests/test_assumption_register.py::test_wacc_method_spread_flags_review tests/test_assumption_register.py::test_forensic_red_flag_critical tests/test_assumption_register.py::test_regime_label_in_register_notes -v`
Expected: all FAIL (diagnostics not wired yet)

### Step 2: Wire B1 — add ronic guardrail to CRITICAL_DIAGNOSTICS

In `src/stage_02_valuation/assumption_register.py`, find:

```python
CRITICAL_DIAGNOSTICS = {
    "health_terminal_denominator_guardrail_flag",
    "terminal_denominator_guardrail_flag",
    "health_terminal_growth_guardrail_flag",
    "terminal_growth_guardrail_flag",
}
```

Add `"health_terminal_ronic_guardrail_flag"` to this set.

### Step 3: Wire B2 — WACC method-spread

**In `src/stage_02_valuation/wacc.py`**, at the end of `compute_wacc_methodology_set_for_ticker()`, after the three method results are collected into `results`:

```python
WACC_DISAGREEMENT_THRESHOLD = 0.015  # 150bps

method_waccs = {
    k: getattr(v, "wacc", None)
    for k, v in results.items()
    if getattr(v, "wacc", None) is not None
}
if len(method_waccs) >= 2:
    spread = max(method_waccs.values()) - min(method_waccs.values())
    results["_meta"] = {
        "wacc_method_spread": round(spread, 4),
        "wacc_method_spread_high": spread >= WACC_DISAGREEMENT_THRESHOLD,
        "method_waccs": method_waccs,
    }
return results
```

**In `src/stage_02_valuation/input_assembler.py`**, after computing `wacc_method_results`, add:

```python
wacc_meta = wacc_method_results.get("_meta") or {}
wacc_method_spread_high = bool(wacc_meta.get("wacc_method_spread_high", False))
```

Then store it — add a field `wacc_method_spread_high: bool = False` to `ValuationInputsWithLineage` (check what dataclass/model that is) or pass it through the existing `drivers` struct. If neither is easy, just store in a module-level thread-local or return it alongside inputs. **Check what `ValuationInputsWithLineage` is before modifying it** (`grep -n "class ValuationInputsWithLineage" src/stage_02_valuation/input_assembler.py`).

**In `src/stage_02_valuation/batch_runner.py`**, add to `register_diagnostics`:

```python
"wacc_method_spread_high": getattr(inputs, "wacc_method_spread_high", False),
```

**In `src/stage_02_valuation/assumption_register.py`**, add `"wacc_method_spread_high"` to `REVIEW_DIAGNOSTICS`.

### Step 4: Wire B3 — forensic_flag_severe

**In `src/stage_02_valuation/batch_runner.py`**, in the `register_diagnostics` dict assembly:

```python
"forensic_flag_severe": row.get("forensic_flag") == "red",
```

**In `src/stage_02_valuation/assumption_register.py`**, add `"forensic_flag_severe"` to `CRITICAL_DIAGNOSTICS`.

### Step 5: Wire B4 — regime label in notes

**In `src/stage_02_valuation/batch_runner.py`**, in the `register_diagnostics` dict assembly:

```python
"regime_label": regime.label if regime_weights else None,
"regime_weights_applied": regime_weights is not None,
```

(Check the exact variable name for the regime object — look at lines 492–508 of `batch_runner.py`.)

**In `src/stage_02_valuation/assumption_register.py`**, in `_apply_diagnostic_rollup`, at the end of the function (after the trust state logic), add:

```python
if diagnostics.get("regime_weights_applied"):
    current_notes = dict(register.notes or {})
    current_notes["regime_label"] = diagnostics.get("regime_label") or "unknown"
    current_notes["regime_weights_applied"] = True
    object.__setattr__(register, "notes", current_notes)
```

This is safe — `notes` is a plain `dict` field with no validators.

### Step 6: Run tests

`pytest tests/test_assumption_register.py -v`
Expected: all pass (existing 9 + 4 new = 13 total)

### Step 7: Commit

```
git add src/stage_02_valuation/assumption_register.py src/stage_02_valuation/wacc.py \
        src/stage_02_valuation/input_assembler.py src/stage_02_valuation/batch_runner.py \
        tests/test_assumption_register.py
git commit -m "feat: extend diagnostic rollup — ronic guardrail critical, WACC spread review, forensic red critical, regime label in notes"
```

**Open GitHub issues now:**
```bash
gh issue create \
  --title "V2: expose WACC method comparison table in React WACC workbench" \
  --label "area:frontend,priority:p2,type:feature" \
  --body "WACC methodology set (peer_bottom_up, industry_proxy, self_hamada) already computed. Method spread diagnostic (wacc_method_spread_high) now wires into assumption register. Surface as a comparison table in React WACC tab."

gh issue create \
  --title "V2: forensic score detail panel in PM review (M-Score breakdown, Z-Score distress)" \
  --label "area:frontend,priority:p2,type:feature" \
  --body "Beneish M-Score and Altman Z-Score are deterministic and canon-blessed. Severe forensic_flag=red now degrades model trust state. Surface M-Score component breakdown and Z-Score distress zone in React PM review panel."

gh issue create \
  --title "V2: forecast scoping scorecard — tier badge in React valuation card" \
  --label "area:frontend,priority:p2,type:feature" \
  --body "Deferred from grill-fixes MVP. Implement assess_forecast_complexity() scorecard that returns full/moderate/light/blocked tier from observable inputs (data coverage, history depth, profitability, revenue volatility). Surface as badge in React valuation card and dossier."

gh issue create \
  --title "V2: deterministic accepted ranges from trailing 5Y p25-p75 per metric" \
  --label "area:valuation,priority:p2,type:feature" \
  --body "Current DEFAULT_ACCEPTED_RANGES are static. Grill session specified ranges should derive from trailing 5-year p25-p75 per metric cross-checked against peers. Requires historical data pipeline investment."
```

---

## Task C: Terminal Growth Cap

**Files:**
- Modify: `src/contracts/assumption_register.py` (change `revenue_growth_terminal` high from 0.05 → 0.04)
- Modify: `tests/test_assumption_register.py` (pin the rule with a test)

### Step 1: Write the failing test

```python
# Add to tests/test_assumption_register.py

def test_terminal_growth_accepted_high_capped_at_four_percent():
    from src.contracts.assumption_register import DEFAULT_ACCEPTED_RANGES
    r = DEFAULT_ACCEPTED_RANGES.get("revenue_growth_terminal")
    assert r is not None, "revenue_growth_terminal must have a range rule"
    assert r["high"] <= 0.04, (
        f"Terminal growth cap must be ≤ 4% (long-run nominal), got {r['high']}"
    )
```

Run: `pytest tests/test_assumption_register.py::test_terminal_growth_accepted_high_capped_at_four_percent -v`
Expected: FAIL (current value is 0.05)

### Step 2: Fix the range

In `src/contracts/assumption_register.py`, find:

```python
"revenue_growth_terminal": {"low": 0.00, "high": 0.05, "description": "Terminal growth should stay within mature nominal growth guardrails."},
```

Change `"high": 0.05` → `"high": 0.04` and update description:

```python
"revenue_growth_terminal": {"low": 0.00, "high": 0.04, "description": "Terminal growth capped at long-run nominal GDP growth (4%)."},
```

### Step 3: Run tests

`pytest tests/test_assumption_register.py -v`
Expected: all pass

### Step 4: Commit

```
git add src/contracts/assumption_register.py tests/test_assumption_register.py
git commit -m "fix: cap terminal growth accepted range high at 4% per long-run nominal GDP rule"
```

---

## Final Verification

```bash
python -m pytest tests/test_assumption_register.py tests/test_peer_universe_contract.py \
  tests/test_assumption_policy.py tests/test_api_contracts.py \
  tests/test_batch_runner_professional.py tests/test_json_exporter.py \
  tests/test_override_workbench.py tests/test_recommendations.py \
  tests/test_ticker_dossier_contract_runtime.py tests/test_valuation_input_assembler.py -q
```

Expected: 130+ passed, 0 errors.

Then: `npm --prefix frontend run build` — must be clean.

Open PR targeting `main`, title: `feat: grill fixes MVP — peer universe contract, diagnostic rollup extension, terminal growth cap`

---

## GitHub Issues Opened During This Plan

All opened inline above. Summary:
1. V2: wire PeerUniverse into comps workbench (TD-03 replacement)
2. V2: WACC method comparison table in React
3. V2: forensic score detail panel in React PM review
4. V2: forecast scoping scorecard + React badge
5. V2: deterministic accepted ranges from trailing 5Y p25-p75
