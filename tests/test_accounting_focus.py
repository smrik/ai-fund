from copy import deepcopy

import pytest

from src.contracts.accounting_evidence import AccountingFocusKey, AccountingPacketStatus
from src.stage_04_pipeline.accounting_focus import ACCOUNTING_FOCUS_REGISTRY, select_accounting_focus


KEYS = tuple(AccountingFocusKey)


def _packet() -> dict:
    facts = []
    for index in range(30):
        facts.append({
            "fact_id": f"fact:{index}",
            "fact_name": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" if index % 2 == 0 else "us-gaap:OperatingIncomeLoss",
            "value": 1000 + index,
            "unit": "USD",
            "metadata": {
                "fact_role": "xbrl_structured_fact",
                "xbrl_fact_name": "RevenueFromContractWithCustomerExcludingAssessedTax" if index % 2 == 0 else "OperatingIncomeLoss",
                "accession": "000-msft-2026",
                "filing_date": "2026-07-01",
                "period": "2026-06-30" if index < 15 else "2025-06-30",
                "period_end": "2026-06-30" if index < 15 else "2025-06-30",
                "dimensions": {"us-gaap:ProductOrServiceAxis": "msft:CloudMember"} if index == 0 else {},
            },
        })
    facts.extend([
        {"fact_id": "fact:driver", "fact_name": "revenue_growth_near", "value": 0.12, "metadata": {"fact_role": "current_model_driver", "driver_field": "revenue_growth_near"}},
        {"fact_id": "fact:prior-driver", "fact_name": "ebit_margin_target", "value": 0.33, "metadata": {"fact_role": "current_model_driver", "driver_field": "ebit_margin_target"}},
    ])
    snippets = [
        {"snippet_id": f"snippet:{i}", "source_ref_id": "filing:000-msft-2026", "text": f"Revenue and operating disclosure {i}.", "metadata": {"section_key": "note_revenue", "filing_date": "2026-07-01"}}
        for i in range(6)
    ]
    return {
        "packet_id": 42,
        "ticker": "MSFT",
        "profile_name": "accounting_qoe",
        "packet_kind": "accounting",
        "generated_at": "2026-07-02T00:00:00+00:00",
        "source_refs": [{"source_ref_id": "filing:000-msft-2026", "source_kind": "10-K", "source_label": "MSFT 10-K", "source_locator": "edgar://msft/2026", "metadata": {"accession": "000-msft-2026", "filing_date": "2026-07-01", "form_type": "10-K"}}],
        "facts": facts,
        "snippets": snippets,
        "run_metadata": {"accounting_topic": "qoe", "source_quality": "real"},
    }


@pytest.mark.parametrize("focus_key", KEYS)
def test_all_registry_keys_are_selectable(focus_key):
    packet = _packet()
    packet["run_metadata"]["accounting_topic"] = ACCOUNTING_FOCUS_REGISTRY[focus_key].parent_topic.value
    context = select_accounting_focus(packet, focus_key)
    assert context.focus_key == focus_key
    assert context.parent_topic == ACCOUNTING_FOCUS_REGISTRY[focus_key].parent_topic
    assert context.ticker == "MSFT"


def test_caps_and_no_mutation_and_dimension_preservation():
    packet = _packet()
    before = deepcopy(packet)
    context = select_accounting_focus(packet, AccountingFocusKey.qoe_revenue)
    assert packet == before
    assert len(context.selected_facts) <= 25
    assert len(context.selected_snippets) <= 5
    dimensional_fact = next(fact for fact in context.selected_facts if fact.fact_id == "fact:0")
    assert dimensional_fact.metadata["dimensions"] == {"us-gaap:ProductOrServiceAxis": "msft:CloudMember"}
    assert context.period_vintage_metadata["selected_accessions"] == ["000-msft-2026"]
    assert [source.source_ref_id for source in context.selected_source_refs] == ["filing:000-msft-2026"]


def test_current_and_comparative_periods_are_retained():
    context = select_accounting_focus(_packet(), AccountingFocusKey.qoe_revenue)
    periods = context.period_vintage_metadata["periods"]
    assert "2026-06-30" in periods
    assert "2025-06-30" in periods


def test_missing_focus_returns_valid_context_and_unsupported_parent_is_clear():
    packet = _packet()
    packet["facts"] = []
    packet["snippets"] = []
    context = select_accounting_focus(packet, AccountingFocusKey.qoe_revenue)
    assert context.packet_status == AccountingPacketStatus.missing_evidence
    assert context.coverage_notes
    with pytest.raises(ValueError, match="belongs to"):
        select_accounting_focus(packet, AccountingFocusKey.qoe_revenue, parent_topic="ev_equity_bridge")


def test_nonrecurring_selector_preserves_explicit_restructuring_under_generic_loss_crowding():
    packet = _packet()
    packet["facts"] = [
        {
            "fact_id": f"fact:generic:{index}",
            "fact_name": "us-gaap:OperatingIncomeLoss",
            "value": 1000 + index,
            "unit": "USD",
            "metadata": {
                "fact_role": "xbrl_structured_fact",
                "xbrl_fact_name": "OperatingIncomeLoss",
                "period": "2025-06-30",
            },
        }
        for index in range(30)
    ] + [
        {
            "fact_id": "fact:restructuring",
            "fact_name": "msft:RestructuringCharges",
            "value": 120.0,
            "unit": "USD mm",
            "metadata": {
                "fact_role": "xbrl_structured_fact",
                "xbrl_fact_name": "RestructuringCharges",
                "period": "2025-06-30",
            },
        }
    ]
    packet["snippets"] = []

    context = select_accounting_focus(packet, AccountingFocusKey.qoe_nonrecurring)

    assert "fact:restructuring" in {fact.fact_id for fact in context.selected_facts}
    assert len([fact for fact in context.selected_facts if fact.fact_name.endswith("OperatingIncomeLoss")]) <= 5
