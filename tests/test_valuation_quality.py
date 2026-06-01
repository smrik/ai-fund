from src.stage_04_pipeline.valuation_quality import build_professional_finance_review


def test_professional_finance_review_flags_banking_quality_risks():
    review = build_professional_finance_review(
        summary={"base_iv": 343.42, "bull_iv": 1050.98},
        dcf={
            "model_integrity": {
                "tv_pct_of_ev": 77.0,
                "revenue_data_quality_flag": "needs_review",
                "roic_consistency_flag": False,
            }
        },
        assumptions={
            "fields": [
                {
                    "field": "revenue_growth_near",
                    "effective_value": 0.07,
                    "baseline_value": 0.0045,
                    "agent_value": 0.037,
                    "effective_source": "approved_assumption_register",
                }
            ]
        },
        comps={},
        batch_row={"comps_model_blended_base": 118.0},
    )

    codes = {flag["code"] for flag in review["flags"]}

    assert review["status"] == "review_required"
    assert "terminal_value_dominance" in codes
    assert "bull_case_asymmetry" in codes
    assert "dcf_comps_divergence" in codes
    assert "growth_override_gap" in codes
    assert "revenue_data_quality" in codes


def test_professional_finance_review_can_be_clean():
    review = build_professional_finance_review(
        summary={"base_iv": 100.0, "bull_iv": 135.0},
        dcf={"model_integrity": {"tv_pct_of_ev": 55.0, "revenue_data_quality_flag": "clean", "roic_consistency_flag": True}},
        assumptions={"fields": [{"field": "revenue_growth_near", "effective_value": 0.04, "baseline_value": 0.035}]},
        comps={},
        batch_row={"comps_model_blended_base": 95.0},
    )

    assert review == {"status": "clean", "high_count": 0, "medium_count": 0, "flags": []}
