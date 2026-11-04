"""Fortytwo's named OpenAI-compatible Browser Use provider."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from pydantic import BaseModel, ValidationError

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.fortytwo.serializer import FortytwoMessageSerializer
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)
ReasoningEffort = Literal['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
FORTYTWO_ATTRIBUTION_HEADERS = {'X-Title': 'browser-use'}
_REASONING_EFFORTS = frozenset({'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'})
_OWNED_FIELDS = frozenset({'model', 'messages', 'stream', 'response_format', 'temperature', 'top_p', 'seed', 'reasoning_effort'})


@dataclass
class ChatFortytwo(BaseChatModel):
	"""Use Fortytwo Chat Completions with text, strict typed output and images.

	Set api_key or FORTYTWO_API_KEY. OPENAI_API_KEY is never used implicitly.
	Configure connection options before first use; a client is cached per instance.
	"""

	model: str = 'qwen/qwen3.8-27b'
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None
	reasoning_effort: ReasoningEffort | None = None
	api_key: str | None = field(default=None, repr=False)
	base_url: str | httpx.URL = 'https://api.fortytwo.network/v1'
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 10
	default_headers: Mapping[str, str] | None = field(default=None, repr=False)
	default_query: Mapping[str, object] | None = field(default=None, repr=False)
	http_client: httpx.AsyncClient | None = field(default=None, repr=False)
	_strict_response_validation: bool = False
	extra_body: dict[str, Any] | None = field(default=None, repr=False)
	_client: AsyncOpenAI | None = field(default=None, init=False, repr=False, compare=False)

	@property
	def provider(self) -> str:
		return 'fortytwo'

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_api_key(self) -> str:
		key = self.api_key or os.getenv('FORTYTWO_API_KEY')
		if not key:
			raise ModelProviderError('Missing Fortytwo API key', status_code=401, model=self.name)
		return key

	def _get_client_params(self) -> dict[str, Any]:
		"""Build guarded client options with effective caller header precedence."""
		headers = {name.lower(): (name, value) for name, value in FORTYTWO_ATTRIBUTION_HEADERS.items()}
		for name, value in (self.default_headers or {}).items():
			headers[name.lower()] = (name, value)
		params: dict[str, Any] = {
			'api_key': self._get_api_key(),
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': dict(headers.values()),
			'default_query': self.default_query,
			'http_client': self.http_client,
			'_strict_response_validation': self._strict_response_validation,
		}
		return {key: value for key, value in params.items() if value is not None}

	def get_client(self) -> AsyncOpenAI:
		"""Return this instance's lazily constructed Fortytwo client."""
		if self._client is None:
			self._client = AsyncOpenAI(**self._get_client_params())
		return self._client

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is None:
			return None
		details = getattr(response.usage, 'prompt_tokens_details', None)
		return ChatInvokeUsage(
			prompt_tokens=response.usage.prompt_tokens,
			prompt_cached_tokens=details.cached_tokens if details else None,
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
		"""Invoke Fortytwo without changing the Browser Use completion contract."""
		try:
			client = self.get_client()
			if output_format is not None and (not isinstance(output_format, type) or not issubclass(output_format, BaseModel)):
				raise ModelProviderError('Expected a Pydantic v2 BaseModel output type', status_code=400, model=self.name)
			if self.reasoning_effort is not None and self.reasoning_effort not in _REASONING_EFFORTS:
				raise ModelProviderError('Unsupported Fortytwo reasoning effort', status_code=400, model=self.name)
			if self.extra_body and _OWNED_FIELDS.intersection(self.extra_body):
				raise ModelProviderError('Extra body conflicts with Fortytwo request controls', status_code=400, model=self.name)

			params: dict[str, Any] = {
				name: value
				for name, value in {
					'temperature': self.temperature,
					'top_p': self.top_p,
					'seed': self.seed,
					'reasoning_effort': self.reasoning_effort,
				}.items()
				if value is not None
			}
			if output_format is not None:
				params['response_format'] = {
					'type': 'json_schema',
					'json_schema': {
						'name': 'agent_output',
						'strict': True,
						'schema': SchemaOptimizer.create_optimized_json_schema(output_format),
					},
				}
			response = await client.chat.completions.create(
				model=self.model,
				messages=FortytwoMessageSerializer.serialize_messages(messages),
				extra_body=self.extra_body,
				**params,
			)
			choices = getattr(response, 'choices', None)
			if not choices:
				raise ModelProviderError('Invalid Fortytwo response: missing or empty choices', status_code=502, model=self.name)
			choice = choices[0]
			content = choice.message.content
			usage = self._get_usage(response)
			if output_format is None:
				return ChatInvokeCompletion(completion=content or '', usage=usage, stop_reason=choice.finish_reason)
			if choice.finish_reason == 'length':
				raise ModelOutputTruncatedError(
					'Model output was truncated at the output token limit; request shorter structured output or increase the output limit',
					model=self.name,
				)
			if content is None:
				raise ModelProviderError('Missing Fortytwo structured output', status_code=500, model=self.name)
			try:
				parsed = output_format.model_validate_json(content)
			except (ValidationError, ValueError):
				raise ModelProviderError('Invalid Fortytwo structured output', status_code=502, model=self.name) from None
			return ChatInvokeCompletion(completion=parsed, usage=usage, stop_reason=choice.finish_reason)
		except ModelProviderError:
			raise
		except RateLimitError:
			raise ModelRateLimitError('Fortytwo request was rate limited', model=self.name) from None
		except APIStatusError as error:
			raise ModelProviderError(
				f'Fortytwo request failed with HTTP {error.status_code}', status_code=error.status_code, model=self.name
			) from None
		except APIConnectionError:
			raise ModelProviderError('Could not connect to Fortytwo', model=self.name) from None
		except Exception:
			raise ModelProviderError('Fortytwo request failed', model=self.name) from None
