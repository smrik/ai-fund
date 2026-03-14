"""
IndustryAgent — weekly sector and industry benchmark synthesis.
Caches one benchmark record per (sector, industry, week_key).

Two public methods:
  research(sector, industry)          — cached weekly benchmarks (DB-backed)
  get_recent_events(ticker, sector)   — latest news search, not cached
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from db.schema import create_tables, get_connection
from src.stage_03_judgment.base_agent import BaseAgent

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_SKILL_DIR = ROOT_DIR / "skills" / "industries"
_MACRO_PATH = ROOT_DIR / "data" / "macro_context.md"

# Sector name → skill file name mapping (case-insensitive lookup via _load_skill)
_SECTOR_SKILL_MAP: dict[str, str] = {
    "technology": "technology.md",
    "information technology": "technology.md",
    "healthcare": "healthcare.md",
    "health care": "healthcare.md",
    "consumer discretionary": "consumer-discretionary.md",
    "consumer staples": "consumer-staples.md",
    "industrials": "industrials.md",
    "energy": "energy.md",
    "materials": "materials.md",
    "communication services": "communication-services.md",
    "telecom": "communication-services.md",
}

SYSTEM_PROMPT = """You are a buy-side industry strategist.
Produce concise, numeric weekly benchmarks for a given sector + industry.
Return only JSON and avoid markdown."""

EVENTS_SYSTEM_PROMPT = """You are a buy-side equity research analyst.
Given a company ticker, its sector, an industry skill reference, recent macro context,
and web search results, produce a concise recent-events summary.

Focus only on information from the last 1-2 weeks that is material to this company's valuation:
- Sector-level demand signals, pricing moves, regulatory changes
- Company-specific news: earnings, guidance updates, management changes, M&A
- Any macro factor specifically relevant to this sector/company

Return a JSON object with these fields:
{
  "ticker": "<string>",
  "sector": "<string>",
  "recent_events": ["<1-sentence event>", ...],   // up to 8 items, most material first
  "sector_tailwinds": ["<string>", ...],           // current, 1-2 weeks
  "sector_headwinds": ["<string>", ...],
  "macro_relevance": "<1-2 sentences on how current macro affects this ticker>",
  "key_catalyst_watch": "<next known catalyst or event to monitor>",
  "confidence": "high" | "medium" | "low"
}
Return only valid JSON. No markdown."""


def _perplexity_search(query: str, recency: str = "week") -> str:
    """Perplexity sonar search. Returns result text or '' on failure / no key."""
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


def _load_skill(sector: str) -> str:
    """Load industry skill file for the given sector name. Returns '' if not found."""
    key = sector.lower().strip()
    filename = _SECTOR_SKILL_MAP.get(key)
    if not filename:
        # Partial match fallback
        for k, v in _SECTOR_SKILL_MAP.items():
            if k in key or key in k:
                filename = v
                break
    if not filename:
        return ""
    path = _SKILL_DIR / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_macro_context() -> str:
    """Load data/macro_context.md if it exists. Returns '' otherwise."""
    if _MACRO_PATH.exists():
        return _MACRO_PATH.read_text(encoding="utf-8")
    return ""


class IndustryAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.name = "IndustryAgent"
        self.system_prompt = SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}
        create_tables()

    @staticmethod
    def _current_week_key(now: datetime | None = None) -> str:
        ts = now or datetime.now(timezone.utc)
        iso = ts.isocalendar()
        return f"{iso.year}-{iso.week:02d}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end <= start:
            return {}

        try:
            parsed = json.loads(raw[start:end])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _as_text(value: Any, default: str) -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_decimal(value: Any, default: float = 0.0) -> float:
        """Parse float and ensure it's in decimal form (0-1), not percentage (0-100)."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        # LLMs often return 8.5 meaning 8.5% — normalise to 0.085
        if abs(v) > 1.5:
            v = v / 100.0
        return v

    @staticmethod
    def _fetch_cached(
        conn: sqlite3.Connection,
        sector: str,
        industry: str,
        week_key: str,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT sector, industry, week_key,
                   consensus_growth_near, consensus_growth_mid,
                   margin_benchmark, valuation_framework,
                   source, notes, created_at, updated_at
            FROM industry_benchmarks
            WHERE sector = ? AND industry = ? AND week_key = ?
            """,
            (sector, industry, week_key),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _upsert(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO industry_benchmarks (
                sector, industry, week_key, consensus_growth_near, consensus_growth_mid,
                margin_benchmark, valuation_framework, source, notes, created_at, updated_at
            ) VALUES (
                :sector, :industry, :week_key, :consensus_growth_near, :consensus_growth_mid,
                :margin_benchmark, :valuation_framework, :source, :notes, :created_at, :updated_at
            )
            ON CONFLICT(sector, industry, week_key) DO UPDATE SET
                consensus_growth_near = excluded.consensus_growth_near,
                consensus_growth_mid = excluded.consensus_growth_mid,
                margin_benchmark = excluded.margin_benchmark,
                valuation_framework = excluded.valuation_framework,
                source = excluded.source,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            payload,
        )
        conn.commit()

    def _normalize_payload(
        self,
        parsed: dict[str, Any],
        sector: str,
        industry: str,
        week_key: str,
    ) -> dict[str, Any]:
        invalid_output = not parsed
        now = self._now()

        payload = {
            "sector": sector,
            "industry": industry,
            "week_key": week_key,
            "consensus_growth_near": self._as_decimal(parsed.get("consensus_growth_near"), 0.0),
            "consensus_growth_mid": self._as_decimal(parsed.get("consensus_growth_mid"), 0.0),
            "margin_benchmark": self._as_decimal(parsed.get("margin_benchmark"), 0.0),
            "valuation_framework": self._as_text(parsed.get("valuation_framework"), "baseline_dcf"),
            "source": self._as_text(parsed.get("source"), "industry_agent_fallback"),
            "notes": self._as_text(
                parsed.get("notes"),
                "Model output missing fields; defaults applied.",
            ),
            "created_at": now,
            "updated_at": now,
        }

        if invalid_output:
            payload["source"] = "industry_agent_fallback"
            payload["notes"] = "Model output invalid; full fallback defaults applied."

        return payload

    def _build_prompt(self, sector: str, industry: str, week_key: str) -> str:
        skill_ctx = _load_skill(sector)
        skill_block = (
            f"\n\n=== INDUSTRY SKILL REFERENCE ===\n{skill_ctx}"
            if skill_ctx else ""
        )
        return (
            f"Generate weekly industry benchmarks for:\n"
            f"- Sector: {sector}\n"
            f"- Industry: {industry}\n"
            f"- Week key: {week_key}"
            f"{skill_block}\n\n"
            f"Return JSON with EXACTLY these fields:\n"
            f"All rate/margin fields must be decimals (e.g. 0.08 for 8%, NOT 8.0).\n"
            f'{{\n'
            f'  "sector": "{sector}",\n'
            f'  "industry": "{industry}",\n'
            f'  "week_key": "{week_key}",\n'
            f'  "consensus_growth_near": <decimal, e.g. 0.08 for 8% growth>,\n'
            f'  "consensus_growth_mid": <decimal>,\n'
            f'  "margin_benchmark": <decimal, e.g. 0.22 for 22% EBIT margin>,\n'
            f'  "valuation_framework": "<short framework description>",\n'
            f'  "source": "<source basis>",\n'
            f'  "notes": "<short rationale>"\n'
            f'}}\n\nOnly output JSON.'
        )

    def research(self, sector: str, industry: str, force_refresh: bool = False) -> dict[str, Any]:
        sector_clean = sector.strip()
        industry_clean = industry.strip()
        week_key = self._current_week_key()

        with get_connection() as conn:
            if not force_refresh:
                cached = self._fetch_cached(conn, sector_clean, industry_clean, week_key)
                if cached is not None:
                    return cached

            prompt = self._build_prompt(sector_clean, industry_clean, week_key)
            raw = self.run(prompt)
            parsed = self._extract_json(raw)
            payload = self._normalize_payload(parsed, sector_clean, industry_clean, week_key)

            existing = self._fetch_cached(conn, sector_clean, industry_clean, week_key)
            if existing is not None:
                payload["created_at"] = existing["created_at"]

            self._upsert(conn, payload)
            refreshed = self._fetch_cached(conn, sector_clean, industry_clean, week_key)
            return refreshed if refreshed is not None else payload

    # ── Recent events (not cached — always live) ──────────────────────────────

    def get_recent_events(self, ticker: str, sector: str) -> dict[str, Any]:
        """
        Search for latest sector + company news and return a structured events dict.
        Not cached — always runs a fresh search. Safe to call even without PERPLEXITY_API_KEY
        (falls back to LLM knowledge only).
        """
        today = datetime.now(timezone.utc).strftime("%B %Y")
        skill_ctx = _load_skill(sector)
        macro_ctx = _load_macro_context()

        # Run two targeted searches: sector-wide + ticker-specific
        sector_search = _perplexity_search(
            f"{sector} sector industry news analyst updates {today}", recency="week"
        )
        ticker_search = _perplexity_search(
            f"{ticker.upper()} stock news earnings guidance analyst {today}", recency="week"
        )

        search_block = ""
        if sector_search:
            search_block += f"### Sector search ({sector})\n{sector_search}\n\n"
        if ticker_search:
            search_block += f"### Ticker search ({ticker.upper()})\n{ticker_search}\n\n"
        if not search_block:
            search_block = "(No search results — PERPLEXITY_API_KEY not set or search failed. Use knowledge cutoff.)\n"

        macro_block = (
            f"\n\n=== CURRENT MACRO CONTEXT ===\n{macro_ctx}"
            if macro_ctx else ""
        )
        skill_block = (
            f"\n\n=== INDUSTRY SKILL REFERENCE ===\n{skill_ctx}"
            if skill_ctx else ""
        )

        old_system = self.system_prompt
        self.system_prompt = EVENTS_SYSTEM_PROMPT
        try:
            prompt = (
                f"Ticker: {ticker.upper()}\n"
                f"Sector: {sector}\n"
                f"Today: {today}"
                f"{skill_block}"
                f"{macro_block}\n\n"
                f"=== SEARCH RESULTS (latest 1-2 weeks) ===\n{search_block}"
                "Return only valid JSON per the required schema."
            )
            raw = self.run(prompt)
            parsed = self._extract_json(raw)
        except Exception:
            parsed = {}
        finally:
            self.system_prompt = old_system

        # Normalise output
        return {
            "ticker": ticker.upper(),
            "sector": sector,
            "recent_events": parsed.get("recent_events") or [],
            "sector_tailwinds": parsed.get("sector_tailwinds") or [],
            "sector_headwinds": parsed.get("sector_headwinds") or [],
            "macro_relevance": parsed.get("macro_relevance") or "",
            "key_catalyst_watch": parsed.get("key_catalyst_watch") or "",
            "confidence": parsed.get("confidence") or "low",
            "search_available": bool(os.getenv("PERPLEXITY_API_KEY", "")),
        }
