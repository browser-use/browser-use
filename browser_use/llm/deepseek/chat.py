from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import (
	APIConnectionError,
	APIError,
	APIStatusError,
	APITimeoutError,
	AsyncOpenAI,
	RateLimitError,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.deepseek.serializer import DeepSeekMessageSerializer
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatDeepSeek(BaseChatModel):
	"""DeepSeek /chat/completions wrapper (OpenAI-compatible)."""

	model: str = 'deepseek-v4-flash'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Thinking / reasoning controls (DeepSeek V4 family + `deepseek-reasoner`).
	# `thinking` maps directly onto DeepSeek's request field, e.g. {'type': 'disabled'}
	# or {'type': 'enabled'}. Leave as None to use the sensible per-model default
	# (see `_resolved_thinking`): V4 models default to non-thinking for reliable
	# structured output, the `deepseek-reasoner` alias stays thinking.
	thinking: dict[str, Any] | None = None
	reasoning_effort: str | None = None
	# Escape hatch for any additional request-body params not modelled above.
	extra_body: dict[str, Any] | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.deepseek.com/v1'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	@property
	def provider(self) -> str:
		return 'deepseek'

	def _resolved_thinking(self) -> dict[str, Any] | None:
		"""The `thinking` value to actually send (None = omit and keep server default).

		DeepSeek deprecated `deepseek-chat` (non-thinking v4-flash) and `deepseek-reasoner`
		(thinking v4-flash). Raw `deepseek-v4-*` server-defaults to thinking, but thinking
		rejects forced `tool_choice`, so we explicitly pin V4 to non-thinking unless the
		caller opts in — this mirrors the old `deepseek-chat` default and keeps structured
		output reliable. The `reasoner` alias stays thinking (its whole point).
		"""
		if self.thinking is not None:
			return self.thinking
		model = self.name.lower()
		if 'reasoner' in model:
			return None
		if 'deepseek-v4' in model:
			return {'type': 'disabled'}
		return None

	def _thinking_enabled(self) -> bool:
		"""Whether thinking is active for this call.

		Thinking Mode rejects forced/named `tool_choice`, so this decides whether we may
		force a named tool (non-thinking) or must fall back to `tool_choice='auto'` (thinking).
		"""
		resolved = self._resolved_thinking()
		if resolved is not None:
			return resolved.get('type') != 'disabled'
		# resolved is None only for the reasoner alias (thinking) or unknown legacy models.
		return 'reasoner' in self.name.lower()

	def _build_extra_body(self) -> dict[str, Any] | None:
		"""Merge caller-provided extra_body with the modelled thinking/reasoning knobs."""
		extra_body: dict[str, Any] = dict(self.extra_body or {})
		resolved_thinking = self._resolved_thinking()
		if resolved_thinking is not None:
			extra_body['thinking'] = resolved_thinking
		if self.reasoning_effort is not None:
			extra_body['reasoning_effort'] = self.reasoning_effort
		return extra_body or None

	@staticmethod
	def _json_candidates_from_text(text: str) -> list[str]:
		"""Best-effort extraction of JSON payloads from free-form assistant content.

		Used when Thinking Mode returns the structured answer as message content (auto
		tool_choice) instead of a tool call.
		"""
		candidates: list[str] = []
		stripped = text.strip()
		if stripped:
			candidates.append(stripped)

		if stripped.startswith('```') and stripped.endswith('```'):
			lines = stripped.splitlines()
			if len(lines) >= 3:
				candidates.append('\n'.join(lines[1:-1]).strip())

		for start_char, end_char in (('{', '}'), ('[', ']')):
			start = stripped.find(start_char)
			end = stripped.rfind(end_char)
			if start != -1 and end > start:
				candidates.append(stripped[start : end + 1])

		return list(dict.fromkeys(candidate for candidate in candidates if candidate))

	def _client(self) -> AsyncOpenAI:
		return AsyncOpenAI(
			api_key=self.api_key,
			base_url=self.base_url,
			timeout=self.timeout,
			**(self.client_params or {}),
		)

	@property
	def name(self) -> str:
		return self.model

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: None = None,
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T],
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
		tools: list[dict[str, Any]] | None = None,
		stop: list[str] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		DeepSeek ainvoke supports:
		1. Regular text/multi-turn conversation
		2. Function Calling
		3. JSON Output (response_format)
		4. Conversation prefix continuation (beta, prefix, stop)
		"""
		client = self._client()
		ds_messages = DeepSeekMessageSerializer.serialize_messages(messages)
		common: dict[str, Any] = {}

		if self.temperature is not None:
			common['temperature'] = self.temperature
		if self.max_tokens is not None:
			common['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			common['top_p'] = self.top_p
		if self.seed is not None:
			common['seed'] = self.seed

		extra_body = self._build_extra_body()
		if extra_body is not None:
			common['extra_body'] = extra_body

		# Beta conversation prefix continuation (see official documentation)
		if self.base_url and str(self.base_url).endswith('/beta'):
			# The last assistant message must have prefix
			if ds_messages and isinstance(ds_messages[-1], dict) and ds_messages[-1].get('role') == 'assistant':
				ds_messages[-1]['prefix'] = True
			if stop:
				common['stop'] = stop

		# ① Regular multi-turn conversation/text output
		if output_format is None and not tools:
			try:
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					**common,
				)
				msg = resp.choices[0].message
				return ChatInvokeCompletion(
					completion=msg.content or '',
					thinking=getattr(msg, 'reasoning_content', None),
					usage=None,
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		# ② Function Calling path (with tools or output_format)
		if tools or (output_format is not None and hasattr(output_format, 'model_json_schema')):
			try:
				call_tools = tools
				tool_choice: Any = None
				if output_format is not None and hasattr(output_format, 'model_json_schema'):
					tool_name = output_format.__name__
					schema = SchemaOptimizer.create_optimized_json_schema(output_format)
					schema.pop('title', None)
					call_tools = [
						{
							'type': 'function',
							'function': {
								'name': tool_name,
								'description': f'Return a JSON object of type {tool_name}',
								'parameters': schema,
							},
						}
					]
					# Thinking Mode rejects forced/named tool_choice (HTTP 400). Only force a
					# named tool when thinking is off; otherwise let the model choose (auto)
					# and recover the structured payload from the tool call or message content.
					if self._thinking_enabled():
						tool_choice = 'auto'
					else:
						tool_choice = {'type': 'function', 'function': {'name': tool_name}}
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					tools=call_tools,  # type: ignore
					tool_choice=tool_choice,  # type: ignore
					**common,
				)
				msg = resp.choices[0].message
				thinking = getattr(msg, 'reasoning_content', None)

				if msg.tool_calls:
					raw_args = msg.tool_calls[0].function.arguments
					parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
					if output_format is not None:
						return ChatInvokeCompletion(
							completion=output_format.model_validate(parsed),
							thinking=thinking,
							usage=None,
						)
					return ChatInvokeCompletion(completion=parsed, thinking=thinking, usage=None)

				# No tool call: with auto tool_choice the model may return the JSON in content.
				if output_format is not None and msg.content:
					for candidate in self._json_candidates_from_text(msg.content):
						try:
							completion = output_format.model_validate_json(candidate)
						except Exception:
							try:
								completion = output_format.model_validate(json.loads(candidate))
							except Exception:
								continue
						return ChatInvokeCompletion(completion=completion, thinking=thinking, usage=None)

				raise ValueError('Expected tool_calls in response but got none')
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		# ③ JSON Output path (official response_format)
		if output_format is not None and hasattr(output_format, 'model_json_schema'):
			try:
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					response_format={'type': 'json_object'},
					**common,
				)
				content = resp.choices[0].message.content
				if not content:
					raise ModelProviderError('Empty JSON content in DeepSeek response', model=self.name)
				parsed = output_format.model_validate_json(content)
				return ChatInvokeCompletion(
					completion=parsed,
					usage=None,
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		raise ModelProviderError('No valid ainvoke execution path for DeepSeek LLM', model=self.name)
