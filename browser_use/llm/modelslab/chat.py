from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, overload

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
from browser_use.llm.openrouter.serializer import OpenRouterMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)

# ModelsLab verified models (OpenAI-compatible chat endpoint)
ModelsLabVerifiedModels = Literal[
	'llama-3-8b-chat',
	'llama-3-70b-chat',
	'mistral-7b-v0.1',
	'mixtral-8x7b',
	'zephyr-7b-beta',
	'falcon-7b-instruct',
	'gemma-7b-it',
	'codellama-7b-instruct',
]

MODELSLAB_API_BASE = 'https://modelslab.com/api/v6/llm'


@dataclass
class ChatModelsLab(BaseChatModel):
	"""
	A wrapper around ModelsLab's OpenAI-compatible chat API.

	ModelsLab provides access to open-source LLMs (Llama, Mistral, Mixtral, etc.)
	through a unified OpenAI-compatible interface, including uncensored models.

	API docs: https://docs.modelslab.com

	Set MODELSLAB_API_KEY in your environment, or pass api_key directly.
	"""

	# Model configuration
	model: ModelsLabVerifiedModels | str = 'llama-3-70b-chat'

	# Model params
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = MODELSLAB_API_BASE
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 10
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None
	_strict_response_validation: bool = False
	extra_body: dict[str, Any] | None = None

	@property
	def provider(self) -> str:
		return 'modelslab'

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_client_params(self) -> dict[str, Any]:
		base_params = {
			'api_key': self.api_key,
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': self.default_headers,
			'default_query': self.default_query,
			'_strict_response_validation': self._strict_response_validation,
		}
		client_params = {k: v for k, v in base_params.items() if v is not None}
		if self.http_client is not None:
			client_params['http_client'] = self.http_client
		return client_params

	def get_client(self) -> AsyncOpenAI:
		"""Returns an AsyncOpenAI client configured for ModelsLab's API."""
		if not hasattr(self, '_client'):
			client_params = self._get_client_params()
			self._client = AsyncOpenAI(**client_params)
		return self._client

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is None:
			return None
		prompt_details = getattr(response.usage, 'prompt_tokens_details', None)
		cached_tokens = prompt_details.cached_tokens if prompt_details else None
		return ChatInvokeUsage(
			prompt_tokens=response.usage.prompt_tokens,
			prompt_cached_tokens=cached_tokens,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
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
		Invoke the model with the given messages through ModelsLab.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		modelslab_messages = OpenRouterMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=modelslab_messages,
					temperature=self.temperature,
					top_p=self.top_p,
					seed=self.seed,
					**(self.extra_body or {}),
				)
				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
				)
			else:
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)
				response_format_schema: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': schema,
				}
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=modelslab_messages,
					temperature=self.temperature,
					top_p=self.top_p,
					seed=self.seed,
					response_format=ResponseFormatJSONSchema(
						json_schema=response_format_schema,
						type='json_schema',
					),
					**(self.extra_body or {}),
				)
				if response.choices[0].message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from ModelsLab response',
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
