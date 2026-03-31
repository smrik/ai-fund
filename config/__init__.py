"""Alpha Pod configuration loader backed by a single YAML file."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"

load_dotenv()


def _load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_RAW_CONFIG = _load_config()
APP_CONFIG = copy.deepcopy(_RAW_CONFIG)


def _resolve_path(relative_path: str) -> Path:
    return ROOT_DIR / relative_path


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else float(default)


_paths = _RAW_CONFIG["paths"]
_research_workspace = _RAW_CONFIG.get("research_workspace", {})
_llm = _RAW_CONFIG["llm"]
_portfolio = _RAW_CONFIG["portfolio"]
_edgar = _RAW_CONFIG["edgar"]
_filings_cache = _RAW_CONFIG.get("filings_cache", {})
_ibkr = _RAW_CONFIG["ibkr"]
_ciq = _RAW_CONFIG["ciq"]
_peer_similarity = _RAW_CONFIG.get("peer_similarity", {})
_risk_limits = _RAW_CONFIG["risk_limits"]
_screening_defaults = _RAW_CONFIG["screening_defaults"]
_schedule = _RAW_CONFIG["schedule"]

DATA_DIR = _resolve_path(_paths["data_dir"])
DB_PATH = _resolve_path(_paths["db_path"])
CIQ_TEMPLATES_DIR = _resolve_path(_paths["ciq_templates_dir"])
CIQ_EXPORTS_DIR = _resolve_path(_paths["ciq_exports_dir"])
CIQ_ARCHIVE_DIR = _resolve_path(_paths.get("ciq_archive_dir", "data/ciq_archive"))
OUTPUT_DIR = _resolve_path(_paths["output_dir"])
SCREENS_DIR = _resolve_path(_paths["screens_dir"])
MEMOS_DIR = _resolve_path(_paths["memos_dir"])
REPORTS_DIR = _resolve_path(_paths["reports_dir"])
UNIVERSE_PATH = _resolve_path(_paths["universe_path"])
DOSSIER_ROOT = _resolve_path(_research_workspace.get("dossier_root", "data/dossiers"))
USE_COMPANY_NAME_IN_FOLDER = bool(_research_workspace.get("use_company_name_in_folder", True))
DOSSIER_NOTE_EXTENSION = str(_research_workspace.get("note_extension", ".md"))
SCREENING_RULES_PATH = CONFIG_PATH
SCREENING_RULES = copy.deepcopy(_RAW_CONFIG["screening"])

LLM_MODEL = _env_str("LLM_MODEL", _llm["model"])
LLM_MODEL_FAST = _env_str("LLM_MODEL_FAST", _llm["fast_model"])
LLM_SYNTHESIS_MODEL = _env_str("LLM_SYNTHESIS_MODEL", _llm.get("synthesis_model", _llm["model"]))
LLM_BASE_URL = _env_str("LLM_BASE_URL", _llm.get("base_url", ""))

PORTFOLIO_SIZE_USD = _env_float("PORTFOLIO_SIZE_USD", _portfolio["size_usd"])
MAX_POSITION_PCT = _env_float("MAX_POSITION_PCT", _portfolio["max_position_pct"])

EDGAR_BASE_URL = _env_str("EDGAR_BASE_URL", _edgar["base_url"])
EDGAR_HEADERS = {"User-Agent": _env_str("EDGAR_USER_AGENT", _edgar["user_agent"])}
EDGAR_RATE_LIMIT_DELAY = _env_float("EDGAR_RATE_LIMIT_DELAY", _edgar["rate_limit_delay"])
EDGAR_CACHE_RAW_DIR = _resolve_path(_filings_cache.get("raw_dir", "data/cache/edgar/raw"))
EDGAR_CACHE_CLEAN_DIR = _resolve_path(_filings_cache.get("clean_dir", "data/cache/edgar/clean"))
EDGAR_PARSER_VERSION = str(_filings_cache.get("parser_version", "v1"))

CONVICTION_SIZING = {
    tier: MAX_POSITION_PCT * float(multiplier)
    for tier, multiplier in _portfolio["conviction_multipliers"].items()
}

IBKR_HOST = _ibkr["host"]
IBKR_PORT = int(_ibkr["port"])
IBKR_CLIENT_ID = int(_ibkr["client_id"])

CIQ_REFRESH_WAIT_SEC = int(_ciq["refresh_wait_sec"])
CIQ_REFRESH_TIMEOUT = int(_ciq["refresh_timeout_sec"])
CIQ_BATCH_SIZE = int(_ciq["batch_size"])
CIQ_DROP_FOLDER = _resolve_path(_ciq.get("drop_folder", _paths["ciq_templates_dir"]))
CIQ_WORKBOOK_GLOB = str(_ciq.get("workbook_glob", "*.xlsx"))
CIQ_PARSER_VERSION = str(_ciq.get("parser_version", "ibm_standard_v1"))
CIQ_ENFORCE_TEMPLATE_LOCK = bool(_ciq.get("enforce_template_lock", True))
PEER_SIMILARITY_ENABLED = bool(_peer_similarity.get("enabled", True))
PEER_SIMILARITY_MODEL = str(_peer_similarity.get("embedding_model", "all-MiniLM-L6-v2"))
PEER_SIMILARITY_DESCRIPTION_SOURCES = list(
    _peer_similarity.get(
        "description_source_precedence",
        ["yfinance_longBusinessSummary", "edgar_item1_business"],
    )
)
_peer_blend = _peer_similarity.get("similarity_blend", {})
PEER_SIMILARITY_DESCRIPTION_WEIGHT = float(_peer_blend.get("description_weight", 0.60))
PEER_SIMILARITY_MARKET_CAP_WEIGHT = float(_peer_blend.get("market_cap_weight", 0.40))

MAX_SINGLE_POSITION_PCT = float(_risk_limits["max_single_position_pct"])
MAX_SHORT_POSITION_PCT = float(_risk_limits["max_short_position_pct"])
MAX_GROSS_EXPOSURE_PCT = float(_risk_limits["max_gross_exposure_pct"])
MIN_NET_EXPOSURE_PCT = float(_risk_limits["min_net_exposure_pct"])
MAX_NET_EXPOSURE_PCT = float(_risk_limits["max_net_exposure_pct"])
MAX_SECTOR_CONCENTRATION_PCT = float(_risk_limits["max_sector_concentration_pct"])
STOP_LOSS_REVIEW_PCT = float(_risk_limits["stop_loss_review_pct"])
MIN_DAYS_TO_EXIT = int(_risk_limits["min_days_to_exit"])

MIN_MARKET_CAP_MM = float(_screening_defaults["min_market_cap_mm"])
MIN_AVG_DAILY_VOLUME_MM = float(_screening_defaults["min_avg_daily_volume_mm"])

DAILY_REFRESH_TIME = _schedule["daily_refresh_time"]
WEEKLY_SCREEN_DAY = _schedule["weekly_screen_day"]
WEEKLY_SCREEN_TIME = _schedule["weekly_screen_time"]


def get_config() -> dict:
    return copy.deepcopy(_RAW_CONFIG)


def get_screening_rules() -> dict:
    return copy.deepcopy(SCREENING_RULES)


__all__ = [
    "APP_CONFIG",
    "CIQ_BATCH_SIZE",
    "CIQ_ARCHIVE_DIR",
    "CIQ_DROP_FOLDER",
    "CIQ_ENFORCE_TEMPLATE_LOCK",
    "CIQ_EXPORTS_DIR",
    "CIQ_PARSER_VERSION",
    "CIQ_REFRESH_TIMEOUT",
    "CIQ_REFRESH_WAIT_SEC",
    "CIQ_TEMPLATES_DIR",
    "CIQ_WORKBOOK_GLOB",
    "CONFIG_PATH",
    "CONVICTION_SIZING",
    "DAILY_REFRESH_TIME",
    "DATA_DIR",
    "DB_PATH",
    "DOSSIER_NOTE_EXTENSION",
    "DOSSIER_ROOT",
    "EDGAR_BASE_URL",
    "EDGAR_CACHE_CLEAN_DIR",
    "EDGAR_CACHE_RAW_DIR",
    "EDGAR_HEADERS",
    "EDGAR_PARSER_VERSION",
    "EDGAR_RATE_LIMIT_DELAY",
    "IBKR_CLIENT_ID",
    "IBKR_HOST",
    "IBKR_PORT",
    "LLM_MODEL",
    "LLM_MODEL_FAST",
    "MAX_GROSS_EXPOSURE_PCT",
    "MAX_NET_EXPOSURE_PCT",
    "MAX_POSITION_PCT",
    "MAX_SECTOR_CONCENTRATION_PCT",
    "MAX_SHORT_POSITION_PCT",
    "MAX_SINGLE_POSITION_PCT",
    "MEMOS_DIR",
    "MIN_AVG_DAILY_VOLUME_MM",
    "MIN_DAYS_TO_EXIT",
    "MIN_MARKET_CAP_MM",
    "MIN_NET_EXPOSURE_PCT",
    "OUTPUT_DIR",
    "PEER_SIMILARITY_DESCRIPTION_SOURCES",
    "PEER_SIMILARITY_DESCRIPTION_WEIGHT",
    "PEER_SIMILARITY_ENABLED",
    "PEER_SIMILARITY_MARKET_CAP_WEIGHT",
    "PEER_SIMILARITY_MODEL",
    "PORTFOLIO_SIZE_USD",
    "REPORTS_DIR",
    "ROOT_DIR",
    "SCREENS_DIR",
    "SCREENING_RULES",
    "SCREENING_RULES_PATH",
    "STOP_LOSS_REVIEW_PCT",
    "UNIVERSE_PATH",
    "USE_COMPANY_NAME_IN_FOLDER",
    "WEEKLY_SCREEN_DAY",
    "WEEKLY_SCREEN_TIME",
    "get_config",
    "get_screening_rules",
]
