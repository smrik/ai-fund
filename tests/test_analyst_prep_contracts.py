from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.contracts.analyst_prep_pack import ModelDriverBridgeCard, ThesisBridgeCard


def test_thesis_card_rejects_unanchored_claim() -> None:
    with pytest.raises(ValidationError):
        ThesisBridgeCard(
            card_id="IBM:test",
            title="Unanchored",
            claim="Margins should improve.",
            business_evidence_summary="No evidence.",
            model_implication="Review margin.",
            linked_assumption_fields=["ebit_margin_target"],
            evidence_anchor_ids=[],
            source_quality="partial",
        )


def test_numeric_thesis_claim_requires_fact_refs() -> None:
    with pytest.raises(ValidationError):
        ThesisBridgeCard(
            card_id="IBM:test",
            title="Numeric",
            claim="Base IV is 150.",
            business_evidence_summary="DCF has a number.",
            model_implication="Review valuation.",
            linked_assumption_fields=["wacc"],
            evidence_anchor_ids=["deterministic:dcf:base_iv"],
            source_quality="partial",
        )


def test_model_driver_card_rejects_unapproved_assumption_field() -> None:
    with pytest.raises(ValidationError):
        ModelDriverBridgeCard(
            assumption_name="made_up_driver",
            label="Made Up",
            rationale="Nope.",
        )
