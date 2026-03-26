"""Tests for BaseAgent._create_with_retry exponential backoff logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from unittest.mock import MagicMock, patch, call
import pytest

from openai import RateLimitError, APITimeoutError, APIConnectionError
from src.stage_03_judgment.base_agent import BaseAgent, _MAX_RETRIES, _RETRY_BACKOFF


def _make_agent() -> BaseAgent:
    with patch("src.stage_03_judgment.base_agent.OpenAI"):
        agent = BaseAgent()
    agent.client = MagicMock()
    return agent


def _make_rate_limit_error() -> RateLimitError:
    """Build a RateLimitError compatible with the OpenAI SDK."""
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_response.text = "rate limit"
    return RateLimitError(message="rate limited", response=mock_response, body={})


def _make_timeout_error() -> APITimeoutError:
    mock_request = MagicMock()
    return APITimeoutError(request=mock_request)


def _make_connection_error() -> APIConnectionError:
    mock_request = MagicMock()
    return APIConnectionError(request=mock_request)


# ── Success on first try ──────────────────────────────────────────────────────

def test_create_with_retry_succeeds_first_try():
    agent = _make_agent()
    mock_response = MagicMock()
    agent.client.chat.completions.create.return_value = mock_response

    with patch("src.stage_03_judgment.base_agent.time.sleep") as mock_sleep:
        result = agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert result is mock_response
    mock_sleep.assert_not_called()
    agent.client.chat.completions.create.assert_called_once()


# ── Rate limit retry ──────────────────────────────────────────────────────────

def test_create_with_retry_on_rate_limit_retries_and_succeeds():
    agent = _make_agent()
    mock_response = MagicMock()
    agent.client.chat.completions.create.side_effect = [
        _make_rate_limit_error(),
        mock_response,
    ]

    with patch("src.stage_03_judgment.base_agent.time.sleep") as mock_sleep:
        result = agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert result is mock_response
    assert agent.client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once_with(_RETRY_BACKOFF[0])


def test_create_with_retry_raises_after_max_retries():
    agent = _make_agent()
    err = _make_rate_limit_error()
    agent.client.chat.completions.create.side_effect = err

    with patch("src.stage_03_judgment.base_agent.time.sleep"):
        with pytest.raises(RateLimitError):
            agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert agent.client.chat.completions.create.call_count == _MAX_RETRIES + 1


def test_create_with_retry_uses_increasing_backoff():
    agent = _make_agent()
    mock_response = MagicMock()
    # Fail twice then succeed
    agent.client.chat.completions.create.side_effect = [
        _make_rate_limit_error(),
        _make_rate_limit_error(),
        mock_response,
    ]

    sleep_calls = []
    with patch("src.stage_03_judgment.base_agent.time.sleep", side_effect=sleep_calls.append):
        agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert sleep_calls == [_RETRY_BACKOFF[0], _RETRY_BACKOFF[1]]


# ── Timeout retry ─────────────────────────────────────────────────────────────

def test_create_with_retry_on_timeout_retries():
    agent = _make_agent()
    mock_response = MagicMock()
    agent.client.chat.completions.create.side_effect = [
        _make_timeout_error(),
        mock_response,
    ]

    with patch("src.stage_03_judgment.base_agent.time.sleep") as mock_sleep:
        result = agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert result is mock_response
    assert agent.client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once()


# ── Connection error retry ────────────────────────────────────────────────────

def test_create_with_retry_on_connection_error_retries():
    agent = _make_agent()
    mock_response = MagicMock()
    agent.client.chat.completions.create.side_effect = [
        _make_connection_error(),
        mock_response,
    ]

    with patch("src.stage_03_judgment.base_agent.time.sleep"):
        result = agent._create_with_retry(model="m", messages=[], max_tokens=100)

    assert result is mock_response


# ── Non-retryable error propagates immediately ────────────────────────────────

def test_create_with_retry_does_not_retry_non_transient_errors():
    agent = _make_agent()
    agent.client.chat.completions.create.side_effect = ValueError("bad input")

    with patch("src.stage_03_judgment.base_agent.time.sleep") as mock_sleep:
        with pytest.raises(ValueError):
            agent._create_with_retry(model="m", messages=[], max_tokens=100)

    # Should not retry on non-transient errors
    assert agent.client.chat.completions.create.call_count == 1
    mock_sleep.assert_not_called()
