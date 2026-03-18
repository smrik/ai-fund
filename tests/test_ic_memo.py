from __future__ import annotations

from src.stage_02_valuation.templates.ic_memo import ICMemo


def test_ic_memo_backward_compatible_without_structured_thesis_fields():
    memo = ICMemo(
        ticker="IBM",
        company_name="IBM",
        action="WATCH",
        conviction="medium",
        key_catalysts=["Margin recovery"],
    )

    assert memo.ticker == "IBM"
    assert memo.key_catalysts == ["Margin recovery"]
    assert memo.thesis_pillars == []
    assert memo.structured_catalysts == []


def test_ic_memo_accepts_structured_thesis_fields():
    memo = ICMemo(
        ticker="IBM",
        company_name="IBM",
        action="BUY",
        conviction="high",
        thesis_pillars=[
            {
                "pillar_id": "pillar-1",
                "title": "Consulting stabilization",
                "description": "Services growth stops contracting.",
                "falsifier": "Another two quarters of decline.",
                "evidence_basis": "Management commentary and bookings.",
            }
        ],
        structured_catalysts=[
            {
                "catalyst_key": "cat-1",
                "title": "Mainframe cycle",
                "description": "Hardware refresh lifts revenue mix.",
                "expected_window": "next 12 months",
                "importance": "high",
            }
        ],
    )

    assert memo.thesis_pillars[0].title == "Consulting stabilization"
    assert memo.structured_catalysts[0].title == "Mainframe cycle"

