from __future__ import annotations

import json
import os
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
	Timeout,
)
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import (
	ModelOutputTruncatedError,
	ModelProviderError,
	ModelRateLimitError,
)
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from browser_use.llm.zhipuai.serializer import ZhipuAIMessageSerializer

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatZhipuAI(BaseChatModel):
	"""ZhipuAI / BigModel inference wrapper (OpenAI-compatible)."""

	model: str = 'glm-5.3-flash'

	# Generation parameters
	max_tokens: int | None = 4096
	temperature: float | None = 0.2
	top_p: float | None = None
	seed: int | None = None

	# Connection parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://open.bigmodel.cn/api/paas/v4/'
	timeout: float | httpx.Timeout | None = None
	client_params: dict[str, Any] | None = None

	thinking: bool = False

	@property
	def provider(self) -> str:
		return 'zhipuai'

	@property
	def name(self) -> str:
		return self.model

	def _resolve_api_key(self) -> str | None:
		return self.api_key or os.getenv('ZHIPUAI_API_KEY') or os.getenv('BIGMODEL_API_KEY') or os.getenv('ZAI_API_KEY')

	def _client(self) -> AsyncOpenAI:
		api_key = self._resolve_api_key()
		if not api_key:
			name = 'ZhipuAI' if self.provider == 'zhipuai' else 'Z.ai'
			keys = (
				'ZHIPUAI_API_KEY, BIGMODEL_API_KEY, or ZAI_API_KEY'
				if self.provider == 'zhipuai'
				else 'ZAI_API_KEY, BIGMODEL_API_KEY, or ZHIPUAI_API_KEY'
			)
			raise ModelProviderError(
				message=f'Missing {name} API key. Set {keys} or pass api_key.',
				status_code=401,
				model=self.name,
			)

		client_kwargs: dict[str, Any] = {
			'api_key': api_key,
			**(self.client_params or {}),
		}
		if self.base_url is not None:
			client_kwargs['base_url'] = str(self.base_url)
		if self.timeout is not None:
			client_kwargs['timeout'] = (
				Timeout(**self.timeout.as_dict()) if isinstance(self.timeout, httpx.Timeout) else self.timeout
			)

		return AsyncOpenAI(**client_kwargs)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is not None:
			usage = ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				prompt_cached_tokens=None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
				completion_tokens=response.usage.completion_tokens,
				total_tokens=response.usage.total_tokens,
			)
		else:
			usage = None
		return usage

	def _request_kwargs(self) -> dict[str, Any]:
		common: dict[str, Any] = {}

		if self.temperature is not None:
			common['temperature'] = self.temperature
		if self.max_tokens is not None:
			common['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			common['top_p'] = self.top_p
		if self.seed is not None:
			common['seed'] = self.seed

		if self.thinking:
			common['extra_body'] = {
				'thinking': {'type': 'enabled'},
			}
		return common

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
		ZhipuAI ainvoke supports:
		1. Regular text / multi-turn conversation
		2. Function Calling (tools)
		3. JSON Structured Output
		"""
		client = self._client()
		serialized_messages = ZhipuAIMessageSerializer.serialize_messages(messages)
		common = self._request_kwargs()
		if stop:
			common['stop'] = stop

		# 1. Regular multi-turn conversation / text output
		if output_format is None and not tools:
			try:
				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=serialized_messages,  # type: ignore
					**common,
				)
				choice = resp.choices[0] if resp.choices else None
				if choice is None:
					raise ModelProviderError(
						message='Invalid ZhipuAI chat completion response: missing choices.',
						status_code=502,
						model=self.name,
					)
				if choice.finish_reason == 'length':
					cap = f'max_tokens={self.max_tokens}' if self.max_tokens is not None else "the model's output token limit"
					raise ModelOutputTruncatedError(
						message=f'Model output was truncated at {cap}; the output is incomplete.',
						model=self.name,
					)
				usage = self._get_usage(resp)
				return ChatInvokeCompletion(
					completion=choice.message.content or '',
					usage=usage,
					stop_reason=choice.finish_reason,
				)
			except (ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError):
				raise
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		# 2. Function Calling path (with tools or output_format)
		if tools or (output_format is not None and hasattr(output_format, 'model_json_schema')):
			try:
				call_tools = tools
				tool_choice: str | None = None
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
					tool_choice = 'auto'

				resp = await client.chat.completions.create(  # type: ignore
					model=self.model,
					messages=serialized_messages,  # type: ignore
					tools=call_tools,  # type: ignore
					tool_choice=tool_choice,  # type: ignore
					**common,
				)
				choice = resp.choices[0] if resp.choices else None
				if choice is None:
					raise ModelProviderError(
						message='Invalid ZhipuAI chat completion response: missing choices.',
						status_code=502,
						model=self.name,
					)
				if choice.finish_reason == 'length':
					cap = f'max_tokens={self.max_tokens}' if self.max_tokens is not None else "the model's output token limit"
					raise ModelOutputTruncatedError(
						message=f'Model output was truncated at {cap}; the output is incomplete.',
						model=self.name,
					)

				msg = choice.message
				usage = self._get_usage(resp)

				if msg.tool_calls:
					raw_args = msg.tool_calls[0].function.arguments
					if isinstance(raw_args, str):
						parsed = json.loads(raw_args)
					else:
						parsed = raw_args

					if output_format is not None:
						return ChatInvokeCompletion(
							completion=output_format.model_validate(parsed),
							usage=usage,
							stop_reason=choice.finish_reason,
						)
					else:
						return ChatInvokeCompletion(
							completion=parsed,
							usage=usage,
							stop_reason=choice.finish_reason,
						)

				# Fallback if no tool_calls but content has JSON
				if msg.content:
					if output_format is not None:
						import re

						json_match = re.search(r'\{.*\}', msg.content, re.DOTALL)
						json_str = json_match.group(0) if json_match else msg.content
						parsed = output_format.model_validate_json(json_str)
						return ChatInvokeCompletion(
							completion=parsed,
							usage=usage,
							stop_reason=choice.finish_reason,
						)
					else:
						return ChatInvokeCompletion(
							completion=msg.content,
							usage=usage,
							stop_reason=choice.finish_reason,
						)

				if output_format is None:
					return ChatInvokeCompletion(
						completion='',
						usage=usage,
						stop_reason=choice.finish_reason,
					)

				raise ModelProviderError('Expected structured content in response but got none', status_code=500, model=self.name)
			except (ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError):
				raise
			except RateLimitError as e:
				raise ModelRateLimitError(str(e), model=self.name) from e
			except (APIError, APIConnectionError, APITimeoutError, APIStatusError) as e:
				raise ModelProviderError(str(e), model=self.name) from e
			except Exception as e:
				raise ModelProviderError(str(e), model=self.name) from e

		raise ModelProviderError('No valid ainvoke execution path for ZhipuAI LLM', model=self.name)


@dataclass
class ChatZai(ChatZhipuAI):
	"""Z.ai inference wrapper (OpenAI-compatible)."""

	base_url: str | httpx.URL | None = 'https://api.z.ai/api/paas/v4/'

	@property
	def provider(self) -> str:
		return 'zai'

	def _resolve_api_key(self) -> str | None:
		return self.api_key or os.getenv('ZAI_API_KEY') or os.getenv('BIGMODEL_API_KEY') or os.getenv('ZHIPUAI_API_KEY')
