"""
BaseAgent — shared infrastructure for all agents.
Handles OpenAI client, tool-call loop, and error recovery.
"""

import json
import logging
import os
import re
import time
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from typing import Any, Callable

from config import LLM_MODEL, LLM_BASE_URL

# Retry config for transient API errors
_MAX_RETRIES = 3
_RETRY_BACKOFF = [5, 15, 30]  # seconds to wait before each retry attempt

_logger = logging.getLogger(__name__)


ToolDefinition = dict[str, Any]
ToolHandler = Callable[[str, dict], str]


class BaseAgent:
	"""
	Base class for all research agents.

	Subclasses define:
	- self.name: display name
	- self.system_prompt: agent-specific instructions
	- self.tools: list of OpenAI tool definitions
	- self.tool_handlers: dict mapping tool name → callable(input_dict) → str
	"""

	def __init__(self, model: str | None = None):
		resolved_base_url = os.getenv("LLM_BASE_URL") or LLM_BASE_URL
		resolved_model = model or os.getenv("LLM_MODEL") or LLM_MODEL
		openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
		if openrouter_key and "openrouter.ai" in (resolved_base_url or ""):
			api_key = openrouter_key
		else:
			api_key = (
				os.getenv("GEMINI_API_KEY")
				or os.getenv("GOOGLE_API_KEY")
				or os.getenv("OPENAI_API_KEY")
				or openrouter_key
				or ""
			)
		# Keep construction offline-safe for deterministic tests and blocked runs.
		# A real request with this placeholder still fails closed at the provider.
		kwargs: dict = {"api_key": api_key or "offline-placeholder"}
		if resolved_base_url:
			kwargs["base_url"] = resolved_base_url
		self.client = OpenAI(**kwargs)
		self.model = resolved_model
		self.last_used_model = self.model
		self._skip_structured_parse = "openrouter.ai" in (resolved_base_url or "")
		self.name = "BaseAgent"
		self.prompt_version = "v1"
		self.system_prompt = "You are a financial research assistant."
		self.tools: list[ToolDefinition] = []
		self.tool_handlers: dict[str, ToolHandler] = {}
		self.last_run_artifact: dict[str, Any] = {}

	@staticmethod
	def _dedupe_models(models: list[str]) -> list[str]:
		ordered: list[str] = []
		seen: set[str] = set()
		for raw in models:
			value = str(raw or "").strip()
			if not value or value in seen:
				continue
			seen.add(value)
			ordered.append(value)
		return ordered

	@staticmethod
	def _split_models(raw: str | None) -> list[str]:
		if not raw:
			return []
		return [part.strip() for part in str(raw).split(",") if part.strip()]

	def _agent_fallback_env_name(self) -> str:
		class_name = self.__class__.__name__
		parts = re.findall(r"[A-Z][a-z0-9]*", class_name) or [class_name]
		return "_".join(part.upper() for part in parts) + "_FALLBACK_MODELS"

	def candidate_models(self, primary_model: str | None = None) -> list[str]:
		primary = str(primary_model or self.model or "").strip()
		models = [primary] if primary else []
		models.extend(self._split_models(os.getenv(self._agent_fallback_env_name())))
		models.extend(self._split_models(os.getenv("LLM_FALLBACK_MODELS")))
		return self._dedupe_models(models)

	def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
		"""Dispatch a tool call to the registered handler."""
		handler = self.tool_handlers.get(tool_name)
		if handler is None:
			return f"Error: unknown tool '{tool_name}'"
		try:
			result = handler(tool_input)
			if isinstance(result, str):
				return result
			return json.dumps(result, default=str)
		except Exception as e:
			return f"Tool error ({tool_name}): {e}"

	def _create_with_retry(self, **kwargs) -> Any:
		"""Call the OpenAI API with exponential backoff on transient errors."""
		last_exc: Exception | None = None
		primary_model = str(kwargs.pop("model", self.model) or self.model)
		candidates = self.candidate_models(primary_model)
		if not candidates:
			candidates = [self.model]
		for idx, model_name in enumerate(candidates):
			for attempt in range(_MAX_RETRIES + 1):
				try:
					response = self.client.chat.completions.create(model=model_name, **kwargs)
					self.last_used_model = model_name
					return response
				except RateLimitError as e:
					last_exc = e
					if attempt < _MAX_RETRIES:
						_logger.warning(
							f"{self.name} rate limited on {model_name} — retry {attempt + 1}/{_MAX_RETRIES}, sleeping {_RETRY_BACKOFF[attempt]}s"
						)
						time.sleep(_RETRY_BACKOFF[attempt])
					else:
						if idx < len(candidates) - 1:
							_logger.warning(f"{self.name} exhausted retries on {model_name}; trying fallback model")
						else:
							_logger.error(f"{self.name} failed after {_MAX_RETRIES} retries: RateLimitError")
				except (APITimeoutError, APIConnectionError) as e:
					last_exc = e
					if attempt < _MAX_RETRIES:
						_logger.warning(
							f"{self.name} {type(e).__name__} on {model_name} — retry {attempt + 1}/{_MAX_RETRIES}, sleeping {_RETRY_BACKOFF[attempt]}s"
						)
						time.sleep(_RETRY_BACKOFF[attempt])
					else:
						if idx < len(candidates) - 1:
							_logger.warning(f"{self.name} exhausted retries on {model_name}; trying fallback model")
						else:
							_logger.error(f"{self.name} failed after {_MAX_RETRIES} retries: {type(e).__name__}")
				except Exception as e:
					last_exc = e
					if idx < len(candidates) - 1:
						_logger.warning(
							f"{self.name} non-retryable error on {model_name} ({type(e).__name__}); trying fallback model"
						)
						break
					raise
		raise last_exc  # unreachable, satisfies type checkers

	def run_structured_payload(self, user_message: str, response_format: Any, max_tokens: int = 8192) -> tuple[dict[str, Any] | None, str | None]:
		"""
		Try strict structured output via chat.completions.parse.
		Returns (payload_dict_or_none, model_used_or_none).
		"""
		if self._skip_structured_parse:
			return None, None
		parser = getattr(self.client.chat.completions, "parse", None)
		if parser is None:
			return None, None
		messages = [
			{"role": "system", "content": self.system_prompt},
			{"role": "user", "content": user_message},
		]
		last_exc: Exception | None = None
		for model_name in self.candidate_models(self.model):
			try:
				completion = parser(
					model=model_name,
					messages=messages,
					max_tokens=max_tokens,
					response_format=response_format,
				)
				message = completion.choices[0].message
				parsed = getattr(message, "parsed", None)
				if parsed is None:
					continue
				self.last_used_model = model_name
				if hasattr(parsed, "model_dump"):
					return parsed.model_dump(), model_name
				if isinstance(parsed, dict):
					return parsed, model_name
				return None, model_name
			except Exception as exc:
				last_exc = exc
				continue
		if last_exc is not None:
			_logger.warning(f"{self.name} structured parse unavailable: {last_exc}")
		return None, None

	@staticmethod
	def _serialize_tool_call(tool_call: Any) -> dict[str, Any]:
		"""
		Serialize a tool call while preserving provider-specific metadata.

		Gemini's OpenAI-compatible tool-calling path returns
		`extra_content.google.thought_signature` on each tool call. That field
		must be sent back unchanged on the assistant tool-call turn.
		"""
		if hasattr(tool_call, "model_dump"):
			dumped = tool_call.model_dump(exclude_none=True)
			if isinstance(dumped, dict):
				return dumped

		return {
			"id": tool_call.id,
			"type": "function",
			"function": {
				"name": tool_call.function.name,
				"arguments": tool_call.function.arguments,
			},
		}

	@classmethod
	def _serialize_assistant_message(cls, message: Any) -> dict[str, Any]:
		"""
		Serialize an assistant message while preserving tool-call metadata.
		"""
		if hasattr(message, "model_dump"):
			dumped = message.model_dump(exclude_none=True)
			if isinstance(dumped, dict):
				return dumped

		payload: dict[str, Any] = {
			"role": "assistant",
			"content": message.content,
		}
		tool_calls = getattr(message, "tool_calls", None)
		if tool_calls:
			payload["tool_calls"] = [cls._serialize_tool_call(tc) for tc in tool_calls]
		return payload

	def run(self, user_message: str, max_iterations: int = 10) -> str:
		"""
		Run the agent with tool-call loop.
		Returns the final text response.
		"""
		messages = [
			{"role": "system", "content": self.system_prompt},
			{"role": "user", "content": user_message},
		]
		tools_param = self.tools if self.tools else None
		artifact: dict[str, Any] = {
			"system_prompt": self.system_prompt,
			"user_prompt": user_message,
			"requested_model": self.model,
			"candidate_models": self.candidate_models(self.model),
			"tool_schema": self.tools,
			"api_trace": [],
			"raw_final_output": "",
			"parsed_output": None,
			"prompt_tokens": None,
			"completion_tokens": None,
			"total_tokens": None,
		}
		self.last_run_artifact = artifact

		for _ in range(max_iterations):
			kwargs = {
				"model": self.model,
				"max_tokens": 8192,
				"messages": messages,
			}
			if tools_param:
				kwargs["tools"] = tools_param

			response = self._create_with_retry(**kwargs)
			if not response.choices:
				_logger.warning(f"{self.name} received empty choices from API (model may have refused or returned a null response)")
				artifact["raw_final_output"] = ""
				self.last_run_artifact = artifact
				return ""
			choice = response.choices[0]
			usage = getattr(response, "usage", None)
			if usage is not None:
				artifact["prompt_tokens"] = getattr(usage, "prompt_tokens", artifact["prompt_tokens"])
				artifact["completion_tokens"] = getattr(usage, "completion_tokens", artifact["completion_tokens"])
				artifact["total_tokens"] = getattr(usage, "total_tokens", artifact["total_tokens"])
			trace_row: dict[str, Any] = {
				"request_messages": json.loads(json.dumps(messages)),
				"finish_reason": choice.finish_reason,
				"model": getattr(response, "model", self.last_used_model),
				"assistant_message": self._serialize_assistant_message(choice.message),
			}

			# Model wants to use tools
			if choice.finish_reason == "tool_calls":
				# Preserve provider-specific tool-call metadata such as Gemini
				# thought signatures when passing the assistant turn back.
				messages.append(self._serialize_assistant_message(choice.message))
				trace_row["tool_results"] = []

				# Execute each tool call and append results
				for tc in choice.message.tool_calls:
					try:
						tool_input = json.loads(tc.function.arguments)
					except Exception:
						tool_input = {}
					result_text = self._execute_tool(tc.function.name, tool_input)
					trace_row["tool_results"].append(
						{
							"tool_call_id": tc.id,
							"tool_name": tc.function.name,
							"tool_input": tool_input,
							"tool_output": result_text,
						}
					)
					messages.append({
						"role": "tool",
						"tool_call_id": tc.id,
						"content": result_text,
					})
				artifact["api_trace"].append(trace_row)
				continue

			# Model finished — return text
			final_text = choice.message.content or ""
			artifact["api_trace"].append(trace_row)
			artifact["raw_final_output"] = final_text
			artifact["parsed_output"] = final_text
			self.last_run_artifact = artifact
			return final_text

		artifact["raw_final_output"] = "Max iterations reached without a final response."
		artifact["parsed_output"] = artifact["raw_final_output"]
		self.last_run_artifact = artifact
		return artifact["raw_final_output"]

	@staticmethod
	def extract_json(raw: str) -> dict:
		"""Extract JSON dict from LLM response, handling markdown code fences."""
		if not raw:
			raise ValueError("empty response")
		fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
		if fence:
			return json.loads(fence.group(1))
		start = raw.find("{")
		end = raw.rfind("}") + 1
		if start == -1 or end <= start:
			raise ValueError("no JSON found")
		return json.loads(raw[start:end])

	@staticmethod
	def _tool(name: str, description: str, properties: dict, required: list[str]) -> ToolDefinition:
		"""Helper to build an OpenAI tool definition."""
		return {
			"type": "function",
			"function": {
				"name": name,
				"description": description,
				"parameters": {
					"type": "object",
					"properties": properties,
					"required": required,
				},
			},
		}
