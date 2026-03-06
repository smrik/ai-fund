"""
Alpha Pod — Configuration
Centralizes LLM model, portfolio, and EDGAR settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM model — Claude Haiku for fast/cheap tasks, override via LLM_MODEL env var
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "claude-haiku-4-5-20251001")

# Portfolio parameters
PORTFOLIO_SIZE_USD = float(os.getenv("PORTFOLIO_SIZE_USD", 100_000))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.08))

# SEC EDGAR (used as fallback when CIQ data unavailable)
EDGAR_BASE_URL = "https://data.sec.gov"
EDGAR_HEADERS = {"User-Agent": "AI-Fund research@example.com"}
EDGAR_RATE_LIMIT_DELAY = 0.15

# Conviction tiers → position sizing
CONVICTION_SIZING = {
    "high":   MAX_POSITION_PCT,           # ~8% of portfolio
    "medium": MAX_POSITION_PCT * 0.5,     # ~4%
    "low":    MAX_POSITION_PCT * 0.25,    # ~2%
}
