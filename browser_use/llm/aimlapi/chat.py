import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeVar, overload
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.shared_params.response_format_json_schema import (
	JSONSchema,
	ResponseFormatJSONSchema,
)
from pydantic import BaseModel

from browser_use.llm.aimlapi.serializer import AIMLAPIMessageSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)

AIMLAPI_BASE_URL = 'https://api.aimlapi.com/v1'

# Identifies Browser Use as the calling application. HTTP-Referer / X-Title follow the
# same convention ChatOpenRouter already uses and name the *host* project, not the
# gateway. Immutable on purpose: _get_attribution_headers() copies it per request.
_ATTRIBUTION_HEADERS: Mapping[str, str] = MappingProxyType(
	{
		'HTTP-Referer': 'https://github.com/browser-use/browser-use',
		'X-Title': 'Browser Use',
		'X-AIMLAPI-Source': 'agent/browser-use',
		'X-AIMLAPI-Partner-ID': 'part_DtfcGF9FcEYD50B1yIkFL8a6',
	}
)


def _is_aimlapi_origin(base_url: str | httpx.URL) -> bool:
	"""Whether base_url points at aimlapi.com itself rather than a user-supplied proxy."""
	parts = urlsplit(str(base_url))
	return parts.scheme == 'https' and parts.hostname == 'api.aimlapi.com'


@dataclass
class ChatAIMLAPI(BaseChatModel):
	"""
	A wrapper around the aimlapi.com OpenAI-compatible chat API, which routes to 350+ chat
	models from OpenAI, Anthropic, Google, DeepSeek, Qwen, xAI and others behind one endpoint.

	This class implements the BaseChatModel protocol for the aimlapi.com API.
	"""

	# Model configuration
	model: str

	# Model params
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = AIMLAPI_BASE_URL
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
		return 'aimlapi'

	def _get_api_key(self) -> str:
		# AsyncOpenAI falls back to OPENAI_API_KEY when api_key is unset, which would send an
		# unrelated provider's key to the aimlapi.com endpoint.
		key = self.api_key or os.getenv('AIMLAPI_API_KEY')
		if not key:
			raise ModelProviderError('Missing aimlapi.com API key', status_code=401, model=self.name)
		return key

	def _get_attribution_headers(self) -> dict[str, str]:
		"""Attribution headers, scoped to the aimlapi.com origin.

		Returns a fresh dict so the module-level constant can never be mutated, and returns
		nothing when base_url was pointed elsewhere - attribution must not ride a request to
		someone else's API, including a proxy that merely fronts this one.
		"""
		if not _is_aimlapi_origin(self.base_url):
			return {}
		return dict(_ATTRIBUTION_HEADERS)

	def _get_request_params(self) -> dict[str, Any]:
		"""Model params for a completion request, with unset ones omitted.

		The gateway validates optional fields strictly and rejects an explicit
		`"top_p": null` / `"seed": null` with a 400, which is what the OpenAI SDK puts on
		the wire for a `None` argument. Leaving the key out entirely is the portable form.
		"""
		params = {'temperature': self.temperature, 'top_p': self.top_p, 'seed': self.seed}
		return {k: v for k, v in params.items() if v is not None}

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Merge rather than assign: a caller who set their own default_headers keeps them.
		default_headers = {**self._get_attribution_headers(), **(self.default_headers or {})}

		# Define base client params
		base_params = {
			'api_key': self._get_api_key(),
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': default_headers or None,
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
		Returns an AsyncOpenAI client configured for aimlapi.com.

		Returns:
		    AsyncOpenAI: An instance of the AsyncOpenAI client with the aimlapi.com base URL.
		"""
		if not hasattr(self, '_client'):
			client_params = self._get_client_params()
			self._client = AsyncOpenAI(**client_params)
		return self._client

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		"""Extract usage information from the aimlapi.com response."""
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

	def _get_first_choice(self, response: ChatCompletion):
		"""Return the first choice, or raise with a hint about proxied base URLs."""
		choice = response.choices[0] if response.choices else None
		if choice is not None:
			return choice

		base_url = str(self.base_url) if self.base_url is not None else None
		hint = f' (base_url={base_url})' if base_url is not None else ''
		raise ModelProviderError(
			message=(
				'Invalid aimlapi.com chat completion response: missing or empty `choices`.'
				' If you are using a proxy via `base_url`, ensure it implements the OpenAI'
				' `/v1/chat/completions` schema and returns `choices` as a non-empty list.'
				f'{hint}'
			),
			status_code=502,
			model=self.name,
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
		Invoke the model with the given messages through aimlapi.com.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		aimlapi_messages = AIMLAPIMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=aimlapi_messages,
					**self._get_request_params(),
					**(self.extra_body or {}),
				)

				choice = self._get_first_choice(response)
				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=choice.message.content or '',
					usage=usage,
				)

			else:
				# Create a JSON schema for structured output
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)

				response_format_schema: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': schema,
				}

				# Return structured response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=aimlapi_messages,
					**self._get_request_params(),
					response_format=ResponseFormatJSONSchema(
						json_schema=response_format_schema,
						type='json_schema',
					),
					**(self.extra_body or {}),
				)

				choice = self._get_first_choice(response)

				if choice.message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)
				usage = self._get_usage(response)

				parsed = output_format.model_validate_json(choice.message.content)

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
				)

		except ModelProviderError:
			# Preserve status_code and message from validation errors
			raise

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
