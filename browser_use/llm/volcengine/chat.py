import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.shared_params.response_format_json_schema import (
	JSONSchema,
	ResponseFormatJSONSchema,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from browser_use.llm.volcengine.serializer import VolcengineMessageSerializer

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatVolcengine(BaseChatModel):
	"""
	A wrapper around Volcengine Ark's chat API, which serves ByteDance's Doubao
	models over an OpenAI-compatible interface.

	Model IDs must carry their full version suffix — the console's short names
	(e.g. `doubao-seed-2-1-pro`) return 404; `doubao-seed-evolving` is the only
	unversioned ID that resolves.

	This class implements the BaseChatModel protocol for Ark's API.
	"""

	# Model configuration
	model: str = 'doubao-seed-2-1-pro-260628'

	# Model params
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None
	max_tokens: int | None = None
	# Ark grades reasoning depth via `reasoning_effort`; passed through as-is.
	reasoning_effort: str | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = 'https://ark.cn-beijing.volces.com/api/v3'
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 10
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None
	_strict_response_validation: bool = False
	extra_body: dict[str, Any] | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'volcengine'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Resolve the key explicitly: without this, AsyncOpenAI would fall back to
		# OPENAI_API_KEY and send an unrelated credential to Ark.
		api_key = self.api_key or os.getenv('ARK_API_KEY')

		base_params = {
			'api_key': api_key,
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': self.default_headers,
			'default_query': self.default_query,
			'_strict_response_validation': self._strict_response_validation,
		}

		# Create client_params dict with non-None values
		client_params = {k: v for k, v in base_params.items() if v is not None}

		# Add http_client if provided
		if self.http_client is not None:
			client_params['http_client'] = self.http_client

		return client_params

	def get_client(self) -> AsyncOpenAI:
		"""
		Returns an AsyncOpenAI client configured for Volcengine Ark.

		Returns:
		    AsyncOpenAI: An instance of the AsyncOpenAI client with Ark's base URL.
		"""
		if not hasattr(self, '_client'):
			client_params = self._get_client_params()
			self._client = AsyncOpenAI(**client_params)
		return self._client

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_request_params(self) -> dict[str, Any]:
		"""Only send generation params the caller actually set."""
		params: dict[str, Any] = {}
		if self.temperature is not None:
			params['temperature'] = self.temperature
		if self.top_p is not None:
			params['top_p'] = self.top_p
		if self.seed is not None:
			params['seed'] = self.seed
		if self.max_tokens is not None:
			params['max_tokens'] = self.max_tokens
		if self.reasoning_effort is not None:
			params['reasoning_effort'] = self.reasoning_effort
		return params

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		"""Extract usage information from the Ark response."""
		if response.usage is None:
			return None

		prompt_details = getattr(response.usage, 'prompt_tokens_details', None)
		cached_tokens = prompt_details.cached_tokens if prompt_details else None

		return ChatInvokeUsage(
			prompt_tokens=response.usage.prompt_tokens,
			prompt_cached_tokens=cached_tokens,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			# Completion
			completion_tokens=response.usage.completion_tokens,
			total_tokens=response.usage.total_tokens,
		)

	@overload
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the model with the given messages through Volcengine Ark.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		ark_messages = VolcengineMessageSerializer.serialize_messages(messages)
		request_params = self._get_request_params()

		try:
			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=ark_messages,
					**request_params,
					**(self.extra_body or {}),
				)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
				)

			else:
				# Ark supports strict json_schema response formats.
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)

				response_format_schema: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': schema,
				}

				# Return structured response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=ark_messages,
					response_format=ResponseFormatJSONSchema(
						json_schema=response_format_schema,
						type='json_schema',
					),
					**request_params,
					**(self.extra_body or {}),
				)

				if response.choices[0].message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)
				usage = self._get_usage(response)

				parsed = output_format.model_validate_json(response.choices[0].message.content)

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
				)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
