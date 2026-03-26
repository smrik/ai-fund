from __future__ import annotations

from .audit import render as render_audit
from .market import render as render_market
from .overview import render as render_overview
from .research import render as render_research
from .valuation import render as render_valuation

SECTION_REGISTRY = {
    "Overview": render_overview,
    "Valuation": render_valuation,
    "Market": render_market,
    "Research": render_research,
    "Audit": render_audit,
}

SECTION_ORDER = tuple(SECTION_REGISTRY)


def render_section(section_name: str, memo, session_state) -> None:
    renderer = SECTION_REGISTRY.get(section_name)
    if renderer is None:
        raise KeyError(f"Unknown dashboard section: {section_name}")
    renderer(memo, session_state)


__all__ = ["SECTION_ORDER", "SECTION_REGISTRY", "render_section"]
