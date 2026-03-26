import json
import logging

from src.logging_config import configure_logging


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
