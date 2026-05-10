import json
import logging
import unittest.mock as mock

from openai import RateLimitError

from src.logging_config import configure_logging
from src.stage_03_judgment.base_agent import BaseAgent
from src.stage_04_pipeline.refresh import refresh_market_data


def test_configure_logging_writes_json_file(tmp_path, monkeypatch):
    log_path = tmp_path / "alpha-pod.jsonl"

    monkeypatch.setenv("ALPHA_POD_LOG_FILE", str(log_path))
    monkeypatch.setenv("ALPHA_POD_LOG_LEVEL", "INFO")

    configure_logging(force=True)

    logger = logging.getLogger("tests.logging")
    logger.info("structured hello", extra={"ticker": "AAA", "step": "smoke", "duration_ms": 42})

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["message"] == "structured hello"
    assert record["ticker"] == "AAA"
    assert record["step"] == "smoke"
    assert record["duration_ms"] == 42


def test_base_agent_retry_emits_warning(caplog):
    agent = BaseAgent()
    agent.name = "TestAgent"

    fake_response = mock.MagicMock()
    fake_response.choices = [mock.MagicMock(finish_reason="stop", message=mock.MagicMock(content="ok", tool_calls=None))]
    fake_response.usage = None

    rate_err = RateLimitError.__new__(RateLimitError)
    side_effects = [rate_err, rate_err, fake_response]

    with mock.patch.object(agent.client.chat.completions, "create", side_effect=side_effects), \
         mock.patch("time.sleep"), \
         caplog.at_level(logging.WARNING, logger="src.stage_03_judgment.base_agent"):
        agent.run("ping")

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 2
    assert all("TestAgent" in r.message for r in warning_records)
    assert all("retry" in r.message for r in warning_records)


def test_refresh_market_data_emits_ticker_and_step(caplog):
    with mock.patch("src.stage_00_data.market_data.get_market_data", return_value={}), \
         mock.patch("src.stage_00_data.market_data.get_historical_financials", return_value={}), \
         mock.patch("src.stage_00_data.market_data._TICKER_CACHE", {}), \
         caplog.at_level(logging.INFO, logger="src.stage_04_pipeline.refresh"):
        refresh_market_data(["AAPL"], verbose=True)

    ticker_records = [r for r in caplog.records if getattr(r, "ticker", None) == "AAPL"]
    assert ticker_records, "expected at least one log record with ticker=AAPL"
    assert all(getattr(r, "step", None) == "market_data" for r in ticker_records)
