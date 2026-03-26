"""
MacroAgent — refreshes data/macro_context.md with latest macro conditions.

Triggered by: python -m src.stage_02_valuation.batch_runner --macro

Reads:  skills/industries/macro.md   (search query guide + output format)
Writes: data/macro_context.md        (overwrites; single latest snapshot)

Uses Perplexity API for web-grounded searches (PERPLEXITY_API_KEY env var).
Falls back to LLM knowledge-only if key is absent.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.stage_03_judgment.base_agent import BaseAgent

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MACRO_SKILL_PATH = ROOT_DIR / "skills" / "industries" / "macro.md"
MACRO_OUTPUT_PATH = ROOT_DIR / "data" / "macro_context.md"

SYSTEM_PROMPT = """You are a macro strategist at a long/short equity hedge fund.
Your job is to produce a concise, factual macro context snapshot for use by equity analysts.

You will be given:
- A macro skill file specifying what to monitor and the output format
- Web search results for recent macro data (if available)

Rules:
- Use only the search results and your knowledge; do not fabricate specific numbers
- If a data point is not in the search results, write "[unavailable]"
- Follow the exact output format specified in the skill file
- Keep the "Market Implications" section focused on what matters for equity L/S investors
- Write today's date in the header
"""


def _perplexity_search(query: str, recency: str = "week") -> str:
    """Call Perplexity sonar API. Returns result text or empty string on failure."""
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    if not api_key:
        return ""
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
                "search_recency_filter": recency,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""


class MacroAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__()
        self.name = "MacroAgent"
        self.system_prompt = SYSTEM_PROMPT

    def _load_skill(self) -> str:
        if MACRO_SKILL_PATH.exists():
            return MACRO_SKILL_PATH.read_text(encoding="utf-8")
        return ""

    def _gather_search_context(self) -> str:
        """Run 6 targeted searches and concatenate results."""
        today = datetime.now(timezone.utc).strftime("%B %Y")
        queries = [
            f"Federal Reserve interest rates current {today}",
            f"CPI PCE inflation latest {today}",
            f"NFP jobs report GDP growth {today}",
            f"IG HY credit spreads VIX risk appetite {today}",
            f"crude oil copper gold commodity prices {today}",
            f"geopolitical risk trade tariffs equity market {today}",
        ]

        has_key = bool(os.getenv("PERPLEXITY_API_KEY", ""))
        if not has_key:
            return "(No PERPLEXITY_API_KEY — LLM will use knowledge cutoff only)"

        parts: list[str] = []
        for q in queries:
            result = _perplexity_search(q, recency="week")
            if result:
                parts.append(f"### Search: {q}\n{result}")

        return "\n\n".join(parts) if parts else "(Search returned no results)"

    def refresh(self) -> str:
        """Run searches, call LLM, write macro_context.md. Returns written content."""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        skill = self._load_skill()
        search_ctx = self._gather_search_context()

        prompt = (
            f"Today's date: {today_str}\n\n"
            f"=== MACRO SKILL (output format and variables to monitor) ===\n{skill}\n\n"
            f"=== SEARCH RESULTS (latest data) ===\n{search_ctx}\n\n"
            "Using the search results and your knowledge, produce the macro_context.md "
            "content in exactly the format specified in the skill file."
        )

        content = self.run(prompt)

        # Ensure output directory exists
        MACRO_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        MACRO_OUTPUT_PATH.write_text(content, encoding="utf-8")

        return content
