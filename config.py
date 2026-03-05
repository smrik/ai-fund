import os
from dotenv import load_dotenv

load_dotenv()

# Claude model — Opus for deep analysis
CLAUDE_MODEL = "claude-opus-4-6"

# Portfolio parameters
PORTFOLIO_SIZE_USD = float(os.getenv("PORTFOLIO_SIZE_USD", 100_000))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", 0.08))

# SEC EDGAR
EDGAR_BASE_URL = "https://data.sec.gov"
EDGAR_HEADERS = {"User-Agent": "AI-Fund research@example.com"}

# Rate limiting (SEC allows 10 req/sec)
EDGAR_RATE_LIMIT_DELAY = 0.15

# Conviction tiers → position sizing
CONVICTION_SIZING = {
    "high":   MAX_POSITION_PCT,           # ~8% of portfolio
    "medium": MAX_POSITION_PCT * 0.5,     # ~4%
    "low":    MAX_POSITION_PCT * 0.25,    # ~2%
}
