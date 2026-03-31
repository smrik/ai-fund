import importlib
import sys
from pathlib import Path


CONFIG_MODULES = ["config.settings", "config"]
ROOT_DIR = Path(__file__).resolve().parent.parent
EXPECTED_CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"


def _reload_config_modules():
    for name in CONFIG_MODULES:
        sys.modules.pop(name, None)
    config_module = importlib.import_module("config")
    settings_module = importlib.import_module("config.settings")
    return config_module, settings_module


def test_config_uses_single_yaml_source(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("PORTFOLIO_SIZE_USD", raising=False)
    monkeypatch.delenv("MAX_POSITION_PCT", raising=False)
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)

    config_module, settings_module = _reload_config_modules()

    assert config_module.CONFIG_PATH == EXPECTED_CONFIG_PATH
    assert config_module.SCREENING_RULES_PATH == EXPECTED_CONFIG_PATH
    assert settings_module.SCREENING_RULES_PATH == EXPECTED_CONFIG_PATH
    assert config_module.LLM_MODEL == "gemini-3-flash-preview"
    assert config_module.SCREENING_RULES["long_screen"]["filters"]["min_market_cap_mm"] == 2000
    assert config_module.APP_CONFIG["screening"]["short_screen"]["filters"]["revenue_decelerating"] is True


def test_default_fast_and_synthesis_models_match_repo_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL_FAST", raising=False)
    monkeypatch.delenv("LLM_SYNTHESIS_MODEL", raising=False)

    config_module, _ = _reload_config_modules()

    assert config_module.LLM_MODEL == "gemini-3-flash-preview"
    assert config_module.LLM_MODEL_FAST == "gemini-3-flash-preview"
    assert config_module.LLM_SYNTHESIS_MODEL == "gemini-3-flash-preview"


def test_env_overrides_runtime_values(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("PORTFOLIO_SIZE_USD", "250000")
    monkeypatch.setenv("MAX_POSITION_PCT", "0.10")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Unit Test Agent")

    config_module, _ = _reload_config_modules()

    assert config_module.LLM_MODEL == "test-model"
    assert config_module.PORTFOLIO_SIZE_USD == 250000.0
    assert config_module.MAX_POSITION_PCT == 0.10
    assert config_module.EDGAR_HEADERS == {"User-Agent": "Unit Test Agent"}
    assert config_module.CONVICTION_SIZING == {
        "high": 0.10,
        "medium": 0.05,
        "low": 0.025,
    }


def test_settings_shim_matches_package_exports(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("PORTFOLIO_SIZE_USD", raising=False)
    monkeypatch.delenv("MAX_POSITION_PCT", raising=False)

    config_module, settings_module = _reload_config_modules()

    assert settings_module.ROOT_DIR == config_module.ROOT_DIR
    assert settings_module.DATA_DIR == config_module.DATA_DIR
    assert settings_module.DB_PATH == config_module.DB_PATH
    assert settings_module.UNIVERSE_PATH == config_module.UNIVERSE_PATH
    assert settings_module.SCREENING_RULES_PATH == config_module.SCREENING_RULES_PATH
    assert settings_module.CIQ_BATCH_SIZE == config_module.CIQ_BATCH_SIZE


def test_ciq_drop_folder_defaults_to_exports_not_templates(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config_module, _ = _reload_config_modules()

    assert config_module.CIQ_DROP_FOLDER == config_module.CIQ_EXPORTS_DIR
    assert config_module.CIQ_DROP_FOLDER != config_module.CIQ_TEMPLATES_DIR


def test_ciq_archive_dir_is_configured_separately_from_exports(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config_module, _ = _reload_config_modules()

    assert config_module.CIQ_ARCHIVE_DIR == config_module.ROOT_DIR / "data" / "ciq_archive"
    assert config_module.CIQ_ARCHIVE_DIR != config_module.CIQ_EXPORTS_DIR
