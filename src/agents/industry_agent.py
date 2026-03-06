"""
IndustryAgent — weekly sector and industry benchmark synthesis.
Caches one benchmark record per (sector, industry, week_key).
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from db.schema import create_tables, get_connection
from src.agents.base_agent import BaseAgent


SYSTEM_PROMPT = """You are a buy-side industry strategist.
Produce concise, numeric weekly benchmarks for a given sector + industry.
Return only JSON and avoid markdown."""


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
            "consensus_growth_near": self._as_float(parsed.get("consensus_growth_near"), 0.0),
            "consensus_growth_mid": self._as_float(parsed.get("consensus_growth_mid"), 0.0),
            "margin_benchmark": self._as_float(parsed.get("margin_benchmark"), 0.0),
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
        return f"""Generate weekly industry benchmarks for:
- Sector: {sector}
- Industry: {industry}
- Week key: {week_key}

Return JSON with EXACTLY these fields:
{{
  \"sector\": \"{sector}\",
  \"industry\": \"{industry}\",
  \"week_key\": \"{week_key}\",
  \"consensus_growth_near\": <float>,
  \"consensus_growth_mid\": <float>,
  \"margin_benchmark\": <float>,
  \"valuation_framework\": \"<short framework description>\",
  \"source\": \"<source basis>\",
  \"notes\": \"<short rationale>\"
}}

Only output JSON."""

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
