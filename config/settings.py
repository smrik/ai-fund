"""
Alpha Pod — Configuration
All paths, constants, and thresholds in one place.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "alpha_pod.db"
CIQ_TEMPLATES_DIR = ROOT_DIR / "ciq" / "templates"
CIQ_EXPORTS_DIR = DATA_DIR / "exports"
OUTPUT_DIR = ROOT_DIR / "output"
SCREENS_DIR = OUTPUT_DIR / "screens"
MEMOS_DIR = OUTPUT_DIR / "memos"
REPORTS_DIR = OUTPUT_DIR / "reports"
UNIVERSE_PATH = ROOT_DIR / "config" / "universe.csv"
SCREENING_RULES_PATH = ROOT_DIR / "config" / "screening_rules.yaml"

# ── IBKR Connection ────────────────────────────────────
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 7497          # 7497=TWS paper, 7496=TWS live, 4002=GW paper, 4001=GW live
IBKR_CLIENT_ID = 1

# ── CIQ Settings ──────────────────────────────────────
CIQ_REFRESH_WAIT_SEC = 5   # Seconds to wait between refresh checks
CIQ_REFRESH_TIMEOUT = 300  # Max seconds to wait for CIQ recalc
CIQ_BATCH_SIZE = 50        # Names per template refresh

# ── Risk Limits ────────────────────────────────────────
MAX_SINGLE_POSITION_PCT = 8.0     # Max weight per name (%)
MAX_SHORT_POSITION_PCT = 4.0
MAX_GROSS_EXPOSURE_PCT = 150.0
MIN_NET_EXPOSURE_PCT = 20.0
MAX_NET_EXPOSURE_PCT = 80.0
MAX_SECTOR_CONCENTRATION_PCT = 30.0
STOP_LOSS_REVIEW_PCT = -15.0      # Triggers forced re-underwrite
MIN_DAYS_TO_EXIT = 5              # Liquidity: must exit in ≤5 days

# ── Screening Defaults ─────────────────────────────────
MIN_MARKET_CAP_MM = 2000
MIN_AVG_DAILY_VOLUME_MM = 5       # $5M dollar volume

# ── Scheduling ─────────────────────────────────────────
DAILY_REFRESH_TIME = "06:00"
WEEKLY_SCREEN_DAY = "sunday"
WEEKLY_SCREEN_TIME = "18:00"
