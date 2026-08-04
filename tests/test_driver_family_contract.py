from __future__ import annotations

from copy import deepcopy

import pytest

from src.contracts.driver_families import (
    DriverFamilyCritique,
    DriverFamilyProposal,
)


def _revenue_payload() -> dict[str, object]:
    return {
        "family": "revenue",
        "horizon_years": 10,
        "assumptions": [
            {
                "assumption_name": "revenue_growth_near",
                "unit": "decimal",
                "applicability": "applicable",
                "low": 0.04,
                "base": 0.07,
                "high": 0.10,
                "conditions": {
                    "low": "Demand softens.",
                    "base": "Current pipeline converts.",
                    "high": "Share gains accelerate.",
                },
                "rationale": "Recent disclosed growth and backlog support the range.",
                "evidence_anchor_ids": ["fact:revenue:2026q2"],
                "what_would_change_view": "A material guidance revision.",
            },
            {
                "assumption_name": "revenue_growth_mid",
                "unit": "decimal",
                "applicability": "applicable",
                "low": 0.03,
                "base": 0.05,
                "high": 0.08,
                "conditions": {
                    "low": "Competition intensifies.",
                    "base": "Market growth normalizes.",
                    "high": "New products sustain share gains.",
                },
                "rationale": "The disclosed addressable market and history support a fade.",
                "evidence_anchor_ids": ["fact:industry:growth"],
                "what_would_change_view": "Loss of a major distribution channel.",
            },
            {
                "assumption_name": "revenue_growth_terminal",
                "unit": "decimal",
                "applicability": "applicable",
                "low": 0.015,
                "base": 0.025,
                "high": 0.03,
                "conditions": {
                    "low": "Mature end markets stagnate.",
                    "base": "Growth converges to nominal demand.",
                    "high": "Durable category growth persists.",
                },
                "rationale": "Terminal growth reflects mature nominal end-market demand.",
                "evidence_anchor_ids": ["fact:industry:terminal-demand"],
                "what_would_change_view": "A structural change in category growth.",
            },
        ],
        "family_rationale": "The cases reflect disclosed demand and competitive evidence.",
    }


def test_revenue_family_accepts_one_complete_evidence_linked_scenario_pack() -> None:
    proposal = DriverFamilyProposal.model_validate(_revenue_payload())

    assert proposal.family.value == "revenue"
    assert [item.assumption_name for item in proposal.assumptions] == [
        "revenue_growth_near",
        "revenue_growth_mid",
        "revenue_growth_terminal",
    ]


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "atomic and complete"),
        ("alias", "canonical assumption name"),
        ("numeric_string", "JSON numbers"),
        ("inverted", "must ascend"),
    ],
)
def test_family_pack_fails_closed_on_malformed_driver_sets(
    mutation: str,
    error: str,
) -> None:
    payload = deepcopy(_revenue_payload())
    assumptions = payload["assumptions"]
    assert isinstance(assumptions, list)
    if mutation == "missing":
        assumptions.pop()
    elif mutation == "alias":
        assumptions[2]["assumption_name"] = "terminal_growth"
    elif mutation == "numeric_string":
        assumptions[0]["base"] = "0.07"
    elif mutation == "inverted":
        assumptions[0]["low"] = 0.12

    with pytest.raises(ValueError, match=error):
        DriverFamilyProposal.model_validate(payload)


def test_conditional_inventory_driver_can_be_explicitly_not_applicable() -> None:
    common = {
        "unit": "decimal",
        "applicability": "applicable",
        "conditions": {
            "low": "Downside operating case.",
            "base": "Base operating case.",
            "high": "Upside operating case.",
        },
        "rationale": "The values follow the reconciled history and disclosed plans.",
        "evidence_anchor_ids": ["fact:cash-flow:history"],
        "what_would_change_view": "A new capital allocation plan.",
    }
    proposal = DriverFamilyProposal.model_validate(
        {
            "family": "reinvestment_working_capital",
            "horizon_years": 10,
            "assumptions": [
                {
                    **common,
                    "assumption_name": "capex_pct_target",
                    "low": 0.07,
                    "base": 0.06,
                    "high": 0.05,
                },
                {
                    **common,
                    "assumption_name": "da_pct_target",
                    "low": 0.04,
                    "base": 0.04,
                    "high": 0.04,
                },
                {
                    **common,
                    "assumption_name": "dso_target",
                    "unit": "days",
                    "low": 55.0,
                    "base": 50.0,
                    "high": 45.0,
                },
                {
                    "assumption_name": "dio_target",
                    "unit": "days",
                    "applicability": "not_applicable",
                    "rationale": "The issuer has no material inventory balance.",
                    "evidence_anchor_ids": ["fact:balance-sheet:inventory-zero"],
                    "what_would_change_view": "A business-model change creating inventory.",
                },
                {
                    **common,
                    "assumption_name": "dpo_target",
                    "unit": "days",
                    "low": 30.0,
                    "base": 35.0,
                    "high": 40.0,
                },
            ],
            "family_rationale": "Reinvestment is based on the reconciled operating record.",
        }
    )

    inventory = next(
        item
        for item in proposal.assumptions
        if item.assumption_name == "dio_target"
    )
    assert inventory.applicability == "not_applicable"


def test_critic_challenges_a_pack_without_replacing_or_averaging_its_values() -> None:
    critique = DriverFamilyCritique.model_validate(
        {
            "family": "revenue",
            "verdict": "revise",
            "issues": [
                {
                    "code": "terminal_growth_anchor_gap",
                    "severity": "blocking",
                    "assumption_names": ["revenue_growth_terminal"],
                    "detail": "The terminal case is not linked to mature-market evidence.",
                    "evidence_anchor_ids": ["fact:industry:terminal-demand"],
                    "required_revision": "Tie all three cases to the disclosed market outlook.",
                }
            ],
            "summary": "The near and mid cases are grounded; terminal support is incomplete.",
        }
    )

    assert critique.verdict == "revise"
    with pytest.raises(ValueError, match="Extra inputs"):
        DriverFamilyCritique.model_validate(
            {
                **critique.model_dump(mode="json"),
                "replacement_values": {"revenue_growth_terminal": 0.02},
            }
        )


def test_critic_can_raise_a_wacc_methodology_change_without_numeric_proxy() -> None:
    payload = {
        "family": "terminal_capital_comps",
        "verdict": "accept",
        "issues": [],
        "methodology_challenges": [
            {
                "code": "wacc_peer_method_not_representative",
                "severity": "warning",
                "category": "methodology",
                "required_capability": "issuer_specific_wacc_methodology",
                "rationale": (
                    "The deterministic peer beta set excludes the issuer's "
                    "regulated capital structure."
                ),
                "evidence_anchor_ids": ["fact:wacc:peer-set"],
            }
        ],
        "summary": "The family values are coherent, but WACC method needs PM review.",
    }

    critique = DriverFamilyCritique.model_validate(payload)

    assert critique.methodology_challenges[0].required_capability == (
        "issuer_specific_wacc_methodology"
    )
    with pytest.raises(ValueError, match="Extra inputs"):
        DriverFamilyCritique.model_validate(
            {
                **payload,
                "methodology_challenges": [
                    {
                        **payload["methodology_challenges"][0],
                        "numeric_proxy": 0.08,
                    }
                ],
            }
        )
