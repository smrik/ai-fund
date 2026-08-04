"""Pure compilation and replay of PM-approved valuation cases.

The module deliberately has no data-access, provider, clock, environment, or
judgment-layer dependencies.  A case contains complete frozen inputs; replay
only executes deterministic DCF and comps math.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Any, Literal, Mapping

from src.contracts.assumption_registry import DriverFamily
from src.contracts.driver_families import (
    ApplicableDriverAssumption,
    DriverFamilyProposal,
)
from src.contracts.judgment_runs import canonical_semantic_hash
from src.contracts.valuation_readiness import ValuationReadinessEvidence
from src.stage_02_valuation.claim_ledger import (
    EV_BRIDGE_COMPONENTS,
    ReconciledEVBridge,
)
from src.stage_02_valuation.comps_model import run_comps_model
from src.stage_02_valuation.professional_dcf import (
    FORECAST_YEARS,
    default_scenario_specs,
    run_dcf_professional,
)
from src.stage_02_valuation.valuation_types import ForecastDrivers


ScenarioName = Literal["low", "base", "high"]
SCENARIO_NAMES: tuple[ScenarioName, ...] = ("low", "base", "high")
DCF_SCENARIO_FOR_APPROVED_CASE: dict[ScenarioName, str] = {
    "low": "bear",
    "base": "base",
    "high": "bull",
}


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("approved valuation cases require finite JSON inputs") from exc


def _require_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


@dataclass(frozen=True, slots=True)
class FrozenScenarioDrivers:
    scenario: ScenarioName
    payload_json: str

    def thaw(self) -> ForecastDrivers:
        payload = json.loads(self.payload_json)
        return ForecastDrivers(**payload)


@dataclass(frozen=True, slots=True)
class ApprovedValuationCase:
    ticker: str
    analysis_snapshot_hash: str
    approved_pack_hashes: tuple[str, ...]
    approval_fingerprints: tuple[str, ...]
    approved_treatment_hashes: tuple[str, ...]
    scenario_drivers: tuple[FrozenScenarioDrivers, ...]
    frozen_comps_json: str
    similarity_scores_json: str
    valuation_policy_json: str
    engine_fingerprint: str
    readiness_json: str
    readiness_fingerprint: str
    replay_key: str

    def drivers_for(self, scenario: ScenarioName) -> ForecastDrivers:
        for frozen in self.scenario_drivers:
            if frozen.scenario == scenario:
                return frozen.thaw()
        raise KeyError(f"unknown scenario: {scenario}")

    def comps_detail(self) -> dict[str, Any]:
        value = json.loads(self.frozen_comps_json)
        if not isinstance(value, dict):
            raise ValueError("frozen comps input must be an object")
        return value

    def similarity_scores(self) -> dict[str, float]:
        value = json.loads(self.similarity_scores_json)
        if not isinstance(value, dict):
            raise ValueError("frozen similarity scores must be an object")
        return {str(key): float(score) for key, score in value.items()}

    def valuation_policy(self) -> dict[str, Any]:
        value = json.loads(self.valuation_policy_json)
        if not isinstance(value, dict):
            raise ValueError("valuation policy must be an object")
        return value

    def readiness(self) -> ValuationReadinessEvidence:
        return ValuationReadinessEvidence.model_validate_json(
            self.readiness_json
        )


@dataclass(frozen=True, slots=True)
class ApprovedValuationReplayResult:
    replay_key: str
    output_hash: str
    canonical_output: str
    dcf_results: dict[str, dict[str, Any]]
    comps_result: dict[str, Any] | None
    expected_intrinsic_value: float
    trust_status: str
    ev_to_equity_bridge: dict[str, Any]


def _reconciled_bridge_from_drivers(
    drivers: ForecastDrivers,
) -> ReconciledEVBridge:
    return ReconciledEVBridge(
        **{
            component: float(getattr(drivers, component))
            for component in EV_BRIDGE_COMPONENTS
        }
    )


def _bridge_payload(
    bridge: ReconciledEVBridge,
) -> dict[str, Any]:
    return {
        "unit": "USD",
        "components_usd": {
            component: float(getattr(bridge, component))
            for component in sorted(EV_BRIDGE_COMPONENTS)
        },
        "ev_to_equity_adjustment_usd": (
            bridge.ev_to_equity_adjustment
        ),
        "ev_to_equity_adjustment_mm": (
            bridge.ev_to_equity_adjustment / 1_000_000.0
        ),
    }


def _scenario_probabilities(policy: Mapping[str, Any]) -> dict[ScenarioName, float]:
    raw = policy.get("scenario_probabilities")
    if not isinstance(raw, Mapping):
        raise ValueError("valuation policy requires scenario_probabilities")
    if set(raw) != set(SCENARIO_NAMES):
        raise ValueError(
            "scenario_probabilities must contain exactly low, base, and high"
        )
    probabilities: dict[ScenarioName, float] = {}
    for scenario in SCENARIO_NAMES:
        value = raw[scenario]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("scenario probabilities must be JSON numbers")
        probability = float(value)
        if probability < 0:
            raise ValueError("scenario probabilities must be non-negative")
        probabilities[scenario] = probability
    total = sum(probabilities.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError("scenario probabilities must sum to 1")
    return probabilities


def _ordered_packs(
    approved_packs: tuple[DriverFamilyProposal, ...],
) -> tuple[DriverFamilyProposal, ...]:
    by_family: dict[DriverFamily, DriverFamilyProposal] = {}
    for pack in approved_packs:
        if pack.family in by_family:
            raise ValueError(f"duplicate approved family pack: {pack.family.value}")
        by_family[pack.family] = pack
    expected = set(DriverFamily)
    if set(by_family) != expected:
        missing = sorted(family.value for family in expected - set(by_family))
        raise ValueError(f"approved case is missing driver families: {missing}")
    ordered = tuple(by_family[family] for family in DriverFamily)
    horizons = {pack.horizon_years for pack in ordered}
    if len(horizons) != 1:
        raise ValueError(
            "approved driver-family packs must use one common horizon; "
            f"received {sorted(horizons)}"
        )
    authored_horizon = next(iter(horizons))
    if authored_horizon != FORECAST_YEARS:
        raise ValueError(
            "approved driver-family horizon must match the DCF engine: "
            f"authored={authored_horizon}, engine={FORECAST_YEARS}"
        )
    return ordered


def compile_approved_valuation_case(
    *,
    ticker: str,
    analysis_snapshot_hash: str,
    base_drivers: ForecastDrivers,
    approved_packs: tuple[DriverFamilyProposal, ...],
    approval_fingerprints: tuple[str, ...],
    approved_treatment_hashes: tuple[str, ...],
    frozen_comps_detail: Mapping[str, Any],
    valuation_policy: Mapping[str, Any],
    engine_fingerprint: str,
    readiness: ValuationReadinessEvidence,
    comps_similarity_scores: Mapping[str, float] | None = None,
) -> ApprovedValuationCase:
    """Compile approved family packs into a complete immutable replay case."""

    normalized_ticker = _require_text(ticker, "ticker").upper()
    snapshot_hash = _require_text(
        analysis_snapshot_hash, "analysis_snapshot_hash"
    )
    engine = _require_text(engine_fingerprint, "engine_fingerprint")
    packs = _ordered_packs(approved_packs)
    _scenario_probabilities(valuation_policy)
    if not frozen_comps_detail:
        raise ValueError("decision-grade replay requires frozen comps inputs")
    readiness.require_decision_grade()

    base_payload = asdict(base_drivers)
    frozen_scenarios: list[FrozenScenarioDrivers] = []
    for scenario in SCENARIO_NAMES:
        payload = dict(base_payload)
        for pack in packs:
            for assumption in pack.assumptions:
                if isinstance(assumption, ApplicableDriverAssumption):
                    payload[assumption.assumption_name] = float(
                        getattr(assumption, scenario)
                    )
                else:
                    payload[assumption.assumption_name] = 0.0
        # Constructor coverage is part of compilation: a stale registry or pack
        # cannot produce a replay artifact.
        resolved = ForecastDrivers(**payload)
        frozen_scenarios.append(
            FrozenScenarioDrivers(
                scenario=scenario,
                payload_json=_canonical_json(asdict(resolved)),
            )
        )

    pack_hashes = tuple(
        canonical_semantic_hash(pack) for pack in packs
    )
    pack_hashes_by_family = {
        pack.family: fingerprint
        for pack, fingerprint in zip(packs, pack_hashes, strict=True)
    }
    if readiness.approved_family_hashes != pack_hashes_by_family:
        raise ValueError(
            "approved family fingerprints changed after readiness review"
        )
    approval_fingerprints = tuple(
        _require_text(value, "approval_fingerprint")
        for value in approval_fingerprints
    )
    if len(approval_fingerprints) != len(DriverFamily):
        raise ValueError(
            "approved replay requires one approval fingerprint per "
            "driver family"
        )
    treatment_hashes = tuple(
        sorted(
            _require_text(value, "approved_treatment_hash")
            for value in approved_treatment_hashes
        )
    )
    comps_json = _canonical_json(dict(frozen_comps_detail))
    if (
        readiness.peer_set_fingerprint
        != canonical_semantic_hash(dict(frozen_comps_detail))
    ):
        raise ValueError(
            "peer-set fingerprint changed after readiness review"
        )
    if (
        readiness.treatment_set_fingerprint
        != canonical_semantic_hash(list(treatment_hashes))
    ):
        raise ValueError(
            "treatment-set fingerprint changed after readiness review"
        )
    expected_engine_fingerprint = canonical_semantic_hash(
        {
            "dcf": readiness.dcf_engine_fingerprint,
            "comps": readiness.comps_engine_fingerprint,
            "bridge": readiness.bridge_engine_fingerprint,
        }
    )
    if engine != expected_engine_fingerprint:
        raise ValueError(
            "valuation engine fingerprint changed after readiness review"
        )
    scores_json = _canonical_json(dict(comps_similarity_scores or {}))
    policy_json = _canonical_json(dict(valuation_policy))
    readiness_json = _canonical_json(
        readiness.model_dump(mode="json", exclude_computed_fields=True)
    )
    identity_payload = {
        "ticker": normalized_ticker,
        "analysis_snapshot_hash": snapshot_hash,
        "approved_pack_hashes": pack_hashes,
        "approval_fingerprints": approval_fingerprints,
        "approved_treatment_hashes": treatment_hashes,
        "scenario_drivers": [
            {
                "scenario": frozen.scenario,
                "payload": json.loads(frozen.payload_json),
            }
            for frozen in frozen_scenarios
        ],
        "frozen_comps": json.loads(comps_json),
        "similarity_scores": json.loads(scores_json),
        "valuation_policy": json.loads(policy_json),
        "engine_fingerprint": engine,
        "readiness": json.loads(readiness_json),
        "readiness_fingerprint": readiness.readiness_fingerprint,
    }
    replay_key = canonical_semantic_hash(identity_payload)
    return ApprovedValuationCase(
        ticker=normalized_ticker,
        analysis_snapshot_hash=snapshot_hash,
        approved_pack_hashes=pack_hashes,
        approval_fingerprints=approval_fingerprints,
        approved_treatment_hashes=treatment_hashes,
        scenario_drivers=tuple(frozen_scenarios),
        frozen_comps_json=comps_json,
        similarity_scores_json=scores_json,
        valuation_policy_json=policy_json,
        engine_fingerprint=engine,
        readiness_json=readiness_json,
        readiness_fingerprint=readiness.readiness_fingerprint,
        replay_key=replay_key,
    )


def replay_approved_valuation_case(
    case: ApprovedValuationCase,
) -> ApprovedValuationReplayResult:
    """Execute a frozen approved case without providers or mutable data sources."""

    policy = case.valuation_policy()
    probabilities = _scenario_probabilities(policy)
    dcf_specs = {spec.name: spec for spec in default_scenario_specs()}
    dcf_results: dict[str, dict[str, Any]] = {}
    expected_iv = 0.0
    for scenario in SCENARIO_NAMES:
        drivers = case.drivers_for(scenario)
        dcf_scenario = DCF_SCENARIO_FOR_APPROVED_CASE[scenario]
        if dcf_scenario not in dcf_specs:
            raise ValueError(f"missing official DCF scenario {dcf_scenario}")
        result = run_dcf_professional(
            drivers,
            replace(
                dcf_specs[dcf_scenario],
                probability=probabilities[scenario],
            ),
        )
        result_payload = asdict(result)
        dcf_results[scenario] = result_payload
        expected_iv += (
            result.intrinsic_value_per_share * probabilities[scenario]
        )

    base_drivers = case.drivers_for("base")
    bridge = _reconciled_bridge_from_drivers(base_drivers)
    comps = run_comps_model(
        case.comps_detail(),
        shares_mm=base_drivers.shares_outstanding / 1_000_000.0,
        similarity_scores=case.similarity_scores(),
        ev_to_equity_adjustment_mm=(
            bridge.ev_to_equity_adjustment / 1_000_000.0
        ),
    )
    if comps is None:
        raise ValueError("frozen comps inputs did not produce a valuation")
    comps_payload = asdict(comps)
    bridge_payload = _bridge_payload(bridge)

    trust_status = case.readiness().trust_status.value
    output_payload = {
        "ticker": case.ticker,
        "replay_key": case.replay_key,
        "engine_fingerprint": case.engine_fingerprint,
        "dcf_results": dcf_results,
        "expected_intrinsic_value": expected_iv,
        "comps_result": comps_payload,
        "ev_to_equity_bridge": bridge_payload,
        "readiness_fingerprint": case.readiness_fingerprint,
        "trust_status": trust_status,
    }
    canonical_output = _canonical_json(output_payload)
    output_hash = hashlib.sha256(canonical_output.encode("utf-8")).hexdigest()
    return ApprovedValuationReplayResult(
        replay_key=case.replay_key,
        output_hash=output_hash,
        canonical_output=canonical_output,
        dcf_results=dcf_results,
        comps_result=comps_payload,
        expected_intrinsic_value=expected_iv,
        trust_status=trust_status,
        ev_to_equity_bridge=bridge_payload,
    )
