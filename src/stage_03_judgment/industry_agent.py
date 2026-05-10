"""
IndustryAgent -- company-centered industry investigation.

Deep interface:
  research_company(context) -> structured advisory report

Compatibility wrappers:
  research(sector, industry)        -> cached weekly benchmark row
  get_recent_events(ticker, sector) -> recent-events slice from research_company()
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from db.schema import create_tables, get_connection
from src.stage_03_judgment.base_agent import BaseAgent
from src.utils import utc_now_iso

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_SKILL_DIR = ROOT_DIR / "skills" / "industries"
_MACRO_PATH = ROOT_DIR / "data" / "macro_context.md"
DEFAULT_INDUSTRY_MODEL = "gemini-3-flash-preview"

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

SYSTEM_PROMPT = """You are a buy-side industry analyst for a solo fundamental PM.

Job:
- investigate company industry context using provided company facts and, when available, Google Search grounding
- separate current cycle facts from structural industry economics
- translate findings into advisory valuation drivers

Rules:
- output valid JSON only
- rates and margins are decimals, e.g. 0.08 for 8%
- cite web-grounded evidence in source_notes when available
- do not invent exact numbers when evidence is weak; use ranges and lower confidence
- all driver suggestions are advisory only; never say they should directly overwrite the model
"""

COMPANY_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "company_name": {"type": "string"},
        "sector": {"type": "string"},
        "industry": {"type": "string"},
        "industry_structure": {"type": "string"},
        "current_cycle": {"type": "string"},
        "company_positioning": {"type": "string"},
        "valuation_framework": {"type": "string"},
        "consensus_growth_near": {"type": "number"},
        "consensus_growth_mid": {"type": "number"},
        "margin_benchmark": {"type": "number"},
        "sector_tailwinds": {"type": "array", "items": {"type": "string"}},
        "sector_headwinds": {"type": "array", "items": {"type": "string"}},
        "recent_events": {"type": "array", "items": {"type": "string"}},
        "macro_relevance": {"type": "string"},
        "key_catalyst_watch": {"type": "string"},
        "driver_assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "proposed_value": {"type": "number"},
                    "range_low": {"type": "number"},
                    "range_high": {"type": "number"},
                    "confidence": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence_reference": {"type": "string"},
                },
                "required": ["field", "confidence", "rationale"],
            },
        },
        "source_notes": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string"},
    },
    "required": [
        "ticker",
        "company_name",
        "sector",
        "industry",
        "industry_structure",
        "current_cycle",
        "company_positioning",
        "valuation_framework",
        "consensus_growth_near",
        "consensus_growth_mid",
        "margin_benchmark",
        "confidence",
    ],
}


@dataclass(slots=True)
class IndustryResearchContext:
    ticker: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    business_description: str = ""
    current_drivers: dict[str, Any] = field(default_factory=dict)
    filing_context: str = ""
    earnings_context: str = ""
    macro_context: str = ""


class IndustryResearchClient(Protocol):
    model: str

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        ...


class GeminiGroundedResearchClient:
    """Tiny Gemini adapter. Google Search grounding enabled when SDK/model supports it."""

    def __init__(
        self,
        *,
        model: str | None = None,
        use_google_search: bool = True,
    ) -> None:
        self.model = model or os.getenv("INDUSTRY_AGENT_MODEL", DEFAULT_INDUSTRY_MODEL)
        self.use_google_search = use_google_search

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore
        except Exception as exc:
            raise RuntimeError("google-genai package required for IndustryAgent Gemini research") from exc

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key) if api_key else genai.Client()

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "response_json_schema": COMPANY_RESEARCH_SCHEMA,
        }
        if self.use_google_search:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        parsed = _extract_json(getattr(response, "text", "") or "")
        metadata = _grounding_metadata(response)
        metadata["model"] = self.model
        metadata["google_search_requested"] = self.use_google_search
        return parsed, metadata


def _load_skill(sector: str) -> str:
    key = sector.lower().strip()
    filename = _SECTOR_SKILL_MAP.get(key)
    if not filename:
        for candidate, mapped in _SECTOR_SKILL_MAP.items():
            if candidate in key or key in candidate:
                filename = mapped
                break
    if not filename:
        return ""
    path = _SKILL_DIR / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_macro_context() -> str:
    return _MACRO_PATH.read_text(encoding="utf-8") if _MACRO_PATH.exists() else ""


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


def _grounding_metadata(response: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {"search_queries": [], "sources": []}
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return metadata
    grounding = getattr(candidates[0], "grounding_metadata", None)
    if grounding is None:
        return metadata
    metadata["search_queries"] = list(getattr(grounding, "web_search_queries", None) or [])
    chunks = getattr(grounding, "grounding_chunks", None) or []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web is not None:
            metadata["sources"].append(
                {
                    "title": getattr(web, "title", ""),
                    "uri": getattr(web, "uri", ""),
                }
            )
    return metadata


def _as_decimal(value: Any, default: float | None = 0.0) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed / 100.0 if abs(parsed) > 1.5 else parsed


def _as_text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


_VALID_CONFIDENCE = {"low", "medium", "high"}


def _normalize_confidence(value: Any, default: str = "medium") -> str:
    text = str(value).strip().lower() if value else ""
    if text in _VALID_CONFIDENCE:
        return text
    if "high" in text:
        return "high"
    if "low" in text:
        return "low"
    return default


def _context_from_any(context: IndustryResearchContext | dict[str, Any]) -> IndustryResearchContext:
    if isinstance(context, IndustryResearchContext):
        return context
    return IndustryResearchContext(
        ticker=str(context.get("ticker") or ""),
        company_name=str(context.get("company_name") or ""),
        sector=str(context.get("sector") or ""),
        industry=str(context.get("industry") or ""),
        business_description=str(context.get("business_description") or ""),
        current_drivers=dict(context.get("current_drivers") or {}),
        filing_context=str(context.get("filing_context") or ""),
        earnings_context=str(context.get("earnings_context") or ""),
        macro_context=str(context.get("macro_context") or ""),
    )


class IndustryAgent(BaseAgent):
    def __init__(self, client: IndustryResearchClient | None = None):
        super().__init__(model=os.getenv("INDUSTRY_AGENT_MODEL", DEFAULT_INDUSTRY_MODEL))
        self.name = "IndustryAgent"
        self.system_prompt = SYSTEM_PROMPT
        self.tools = []
        self.tool_handlers = {}
        self.client_adapter = client or GeminiGroundedResearchClient()
        create_tables()

    @staticmethod
    def _current_week_key(now: datetime | None = None) -> str:
        ts = now or datetime.now(timezone.utc)
        iso = ts.isocalendar()
        return f"{iso.year}-{iso.week:02d}"

    @staticmethod
    def _now() -> str:
        return utc_now_iso()

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        return _extract_json(raw)

    @staticmethod
    def _as_decimal(value: Any, default: float = 0.0) -> float:
        return _as_decimal(value, default)

    @staticmethod
    def _as_text(value: Any, default: str) -> str:
        return _as_text(value, default)

    def _build_company_prompt(self, context: IndustryResearchContext) -> str:
        macro_ctx = context.macro_context or _load_macro_context()
        skill_ctx = _load_skill(context.sector)
        payload = {
            "ticker": context.ticker.upper(),
            "company_name": context.company_name,
            "sector": context.sector,
            "industry": context.industry,
            "business_description": context.business_description,
            "current_drivers": context.current_drivers,
            "filing_context": context.filing_context[:12_000],
            "earnings_context": context.earnings_context[:8_000],
            "macro_context": macro_ctx[:8_000],
            "industry_reference": skill_ctx[:8_000],
        }
        return (
            "Investigate industry context for this company. Use Google Search grounding if available. "
            "Return JSON matching schema exactly.\n\n"
            f"{json.dumps(payload, indent=2, default=str)}"
        )

    def research_company(self, context: IndustryResearchContext | dict[str, Any]) -> dict[str, Any]:
        ctx = _context_from_any(context)
        prompt = self._build_company_prompt(ctx)
        parsed, metadata = self.client_adapter.generate_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        payload = self._normalize_company_report(parsed, ctx)
        payload["grounding"] = metadata
        payload["model"] = getattr(self.client_adapter, "model", DEFAULT_INDUSTRY_MODEL)
        return payload

    def _normalize_company_report(
        self,
        parsed: dict[str, Any],
        context: IndustryResearchContext,
    ) -> dict[str, Any]:
        assessments = parsed.get("driver_assessments")
        if not isinstance(assessments, list):
            assessments = []

        clean_assessments = []
        for item in assessments:
            if not isinstance(item, dict) or not item.get("field"):
                continue
            clean_assessments.append(
                {
                    "source": "industry_agent",
                    "field": _as_text(item.get("field"), ""),
                    "proposed_value": _as_decimal(item.get("proposed_value"), None),  # type: ignore[arg-type]
                    "range_low": _as_decimal(item.get("range_low"), None),  # type: ignore[arg-type]
                    "range_high": _as_decimal(item.get("range_high"), None),  # type: ignore[arg-type]
                    "confidence": _normalize_confidence(item.get("confidence"), "medium"),
                    "rationale": _as_text(item.get("rationale"), ""),
                    "evidence_reference": _as_text(item.get("evidence_reference"), ""),
                    "approval_status": "advisory",
                }
            )

        return {
            "ticker": _as_text(parsed.get("ticker"), context.ticker.upper()).upper(),
            "company_name": _as_text(parsed.get("company_name"), context.company_name),
            "sector": _as_text(parsed.get("sector"), context.sector),
            "industry": _as_text(parsed.get("industry"), context.industry or context.sector),
            "industry_structure": _as_text(parsed.get("industry_structure"), ""),
            "current_cycle": _as_text(parsed.get("current_cycle"), ""),
            "company_positioning": _as_text(parsed.get("company_positioning"), ""),
            "valuation_framework": _as_text(parsed.get("valuation_framework"), "baseline_dcf"),
            "consensus_growth_near": _as_decimal(parsed.get("consensus_growth_near"), 0.0),
            "consensus_growth_mid": _as_decimal(parsed.get("consensus_growth_mid"), 0.0),
            "margin_benchmark": _as_decimal(parsed.get("margin_benchmark"), 0.0),
            "sector_tailwinds": parsed.get("sector_tailwinds") if isinstance(parsed.get("sector_tailwinds"), list) else [],
            "sector_headwinds": parsed.get("sector_headwinds") if isinstance(parsed.get("sector_headwinds"), list) else [],
            "recent_events": parsed.get("recent_events") if isinstance(parsed.get("recent_events"), list) else [],
            "macro_relevance": _as_text(parsed.get("macro_relevance"), ""),
            "key_catalyst_watch": _as_text(parsed.get("key_catalyst_watch"), ""),
            "driver_assessments": clean_assessments,
            "source_notes": parsed.get("source_notes") if isinstance(parsed.get("source_notes"), list) else [],
            "confidence": _normalize_confidence(parsed.get("confidence"), "low"),
        }

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
            "consensus_growth_near": _as_decimal(parsed.get("consensus_growth_near"), 0.0),
            "consensus_growth_mid": _as_decimal(parsed.get("consensus_growth_mid"), 0.0),
            "margin_benchmark": _as_decimal(parsed.get("margin_benchmark"), 0.0),
            "valuation_framework": _as_text(parsed.get("valuation_framework"), "baseline_dcf"),
            "source": _as_text(parsed.get("source"), "industry_agent_fallback"),
            "notes": _as_text(parsed.get("notes"), "Model output missing fields; defaults applied."),
            "created_at": now,
            "updated_at": now,
        }
        if invalid_output:
            payload["source"] = "industry_agent_fallback"
            payload["notes"] = "Model output invalid; full fallback defaults applied."
        return payload

    def _build_prompt(self, sector: str, industry: str, week_key: str) -> str:
        context = IndustryResearchContext(
            ticker=f"{sector}:{industry}",
            sector=sector,
            industry=industry,
            macro_context=_load_macro_context(),
        )
        return self._build_company_prompt(context)

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
            parsed = _extract_json(raw)
            payload = self._normalize_payload(parsed, sector_clean, industry_clean, week_key)

            existing = self._fetch_cached(conn, sector_clean, industry_clean, week_key)
            if existing is not None:
                payload["created_at"] = existing["created_at"]

            self._upsert(conn, payload)
            refreshed = self._fetch_cached(conn, sector_clean, industry_clean, week_key)
            return refreshed if refreshed is not None else payload

    def get_recent_events(self, ticker: str, sector: str) -> dict[str, Any]:
        _empty: dict[str, Any] = {
            "ticker": ticker.upper(),
            "sector": sector,
            "recent_events": [],
            "sector_tailwinds": [],
            "sector_headwinds": [],
            "macro_relevance": "",
            "key_catalyst_watch": "",
            "confidence": "low",
            "search_available": False,
        }
        try:
            report = self.research_company(
                {
                    "ticker": ticker,
                    "sector": sector,
                    "industry": sector,
                    "macro_context": _load_macro_context(),
                }
            )
        except Exception:
            return _empty
        return {
            **_empty,
            "recent_events": report.get("recent_events") or [],
            "sector_tailwinds": report.get("sector_tailwinds") or [],
            "sector_headwinds": report.get("sector_headwinds") or [],
            "macro_relevance": report.get("macro_relevance") or "",
            "key_catalyst_watch": report.get("key_catalyst_watch") or "",
            "confidence": _normalize_confidence(report.get("confidence"), "low"),
            "search_available": bool((report.get("grounding") or {}).get("sources")),
        }
