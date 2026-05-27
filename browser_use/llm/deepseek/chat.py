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
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


def _extract_usage(resp: Any) -> ChatInvokeUsage | None:
	"""Map an OpenAI-compatible ``response.usage`` to ``ChatInvokeUsage``.

	DeepSeek goes through ``AsyncOpenAI`` so ``resp.usage`` is the same shape as the
	OpenAI provider (``CompletionUsage``). Some legacy proxies may omit it; in that
	case we keep ``None`` to stay backwards-compatible.
	"""
	usage = getattr(resp, 'usage', None)
	if usage is None:
		return None
	prompt_details = getattr(usage, 'prompt_tokens_details', None)
	cached = getattr(prompt_details, 'cached_tokens', None) if prompt_details is not None else None
	return ChatInvokeUsage(
		prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
		prompt_cached_tokens=cached,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
		total_tokens=getattr(usage, 'total_tokens', 0) or 0,
	)


@dataclass
class ChatDeepSeek(BaseChatModel):
	"""DeepSeek /chat/completions wrapper (OpenAI-compatible)."""

	model: str = 'deepseek-chat'

	# Generation parameters
	max_tokens: int | None = None
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.deepseek.com/v1'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	@property
	def provider(self) -> str:
		return 'deepseek'

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
				return ChatInvokeCompletion(
					completion=resp.choices[0].message.content or '',
					usage=_extract_usage(resp),
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
				tool_choice = None
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
					tool_choice = {'type': 'function', 'function': {'name': tool_name}}
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=ds_messages,  # type: ignore
					tools=call_tools,  # type: ignore
					tool_choice=tool_choice,  # type: ignore
					**common,
				)
				msg = resp.choices[0].message
				if not msg.tool_calls:
					raise ValueError('Expected tool_calls in response but got none')
				raw_args = msg.tool_calls[0].function.arguments
				if isinstance(raw_args, str):
					parsed = json.loads(raw_args)
				else:
					parsed = raw_args
				# --------- Fix: only use model_validate when output_format is not None ----------
				if output_format is not None:
					return ChatInvokeCompletion(
						completion=output_format.model_validate(parsed),
						usage=_extract_usage(resp),
					)
				else:
					# If no output_format, return dict directly
					return ChatInvokeCompletion(
						completion=parsed,
						usage=_extract_usage(resp),
					)
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
					usage=_extract_usage(resp),
				)
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		raise ModelProviderError('No valid ainvoke execution path for DeepSeek LLM', model=self.name)
