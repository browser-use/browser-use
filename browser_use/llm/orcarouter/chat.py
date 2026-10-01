import os
from collections.abc import Mapping
from dataclasses import dataclass, field
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
from browser_use.llm.orcarouter.auth import (
	OrcaRouterAuthError,
	OrcaRouterCredentialStore,
	resolve_orcarouter_api_base_url,
	validate_orcarouter_api_base_url,
)
from browser_use.llm.orcarouter.serializer import OrcaRouterMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


def _default_api_base_url() -> str:
	return resolve_orcarouter_api_base_url()


@dataclass
class ChatOrcaRouter(BaseChatModel):
	"""
	A wrapper around OrcaRouter's OpenAI-compatible chat API, which routes to 190+ LLM models
	through a single unified gateway.

	This class implements the BaseChatModel protocol for OrcaRouter's API.
	"""

	# Model configuration
	model: str

	# Model params
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = field(default_factory=_default_api_base_url)
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
		return 'orcarouter'

	def _get_api_key(self) -> str:
		# AsyncOpenAI falls back to OPENAI_API_KEY when api_key is unset, which would send an
		# unrelated provider's key to the OrcaRouter endpoint.
		self._pkce_credential_generation = None
		if self.api_key:
			return self.api_key
		if env_key := os.getenv('ORCAROUTER_API_KEY'):
			return env_key

		try:
			credential = OrcaRouterCredentialStore().load()
		except OrcaRouterAuthError as exc:
			raise ModelProviderError(str(exc), status_code=401, model=self.name) from exc
		if credential is not None:
			if credential.needs_reauth:
				raise ModelProviderError(
					'OrcaRouter login needs to be renewed; run `browser-use orcarouter login`',
					status_code=401,
					model=self.name,
				)
			self._pkce_credential_generation = credential.generation
			return credential.api_key

		raise ModelProviderError(
			'Missing OrcaRouter API key; set ORCAROUTER_API_KEY or run `browser-use orcarouter login`',
			status_code=401,
			model=self.name,
		)

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Define base client params
		base_params = {
			'api_key': self._get_api_key(),
			'base_url': validate_orcarouter_api_base_url(self.base_url),
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
		Returns an AsyncOpenAI client configured for OrcaRouter.

		Returns:
		    AsyncOpenAI: An instance of the AsyncOpenAI client with OrcaRouter base URL.
		"""
		if not hasattr(self, '_client'):
			client_params = self._get_client_params()
			self._client = AsyncOpenAI(**client_params)
		return self._client

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		"""Extract usage information from the OrcaRouter response."""
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
		Invoke the model with the given messages through OrcaRouter.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		if getattr(self, '_pkce_needs_reauth', False):
			raise ModelProviderError(
				'OrcaRouter login needs to be renewed; run `browser-use orcarouter login`',
				status_code=401,
				model=self.name,
			)

		orcarouter_messages = OrcaRouterMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=orcarouter_messages,
					temperature=self.temperature,
					top_p=self.top_p,
					seed=self.seed,
					**(self.extra_body or {}),
				)

				choice = response.choices[0] if response.choices else None
				if choice is None:
					base_url = str(self.base_url) if self.base_url is not None else None
					hint = f' (base_url={base_url})' if base_url is not None else ''
					raise ModelProviderError(
						message=(
							'Invalid OrcaRouter chat completion response: missing or empty `choices`.'
							' If you are using a proxy via `base_url`, ensure it implements the OpenAI'
							' `/v1/chat/completions` schema and returns `choices` as a non-empty list.'
							f'{hint}'
						),
						status_code=502,
						model=self.name,
					)

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
					messages=orcarouter_messages,
					temperature=self.temperature,
					top_p=self.top_p,
					seed=self.seed,
					response_format=ResponseFormatJSONSchema(
						json_schema=response_format_schema,
						type='json_schema',
					),
					**(self.extra_body or {}),
				)

				choice = response.choices[0] if response.choices else None
				if choice is None:
					base_url = str(self.base_url) if self.base_url is not None else None
					hint = f' (base_url={base_url})' if base_url is not None else ''
					raise ModelProviderError(
						message=(
							'Invalid OrcaRouter chat completion response: missing or empty `choices`.'
							' If you are using a proxy via `base_url`, ensure it implements the OpenAI'
							' `/v1/chat/completions` schema and returns `choices` as a non-empty list.'
							f'{hint}'
						),
						status_code=502,
						model=self.name,
					)

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
			credential_generation = getattr(self, '_pkce_credential_generation', None)
			if e.status_code == 401 and isinstance(credential_generation, str):
				self._pkce_needs_reauth = True
				try:
					OrcaRouterCredentialStore().mark_needs_reauth(credential_generation)
				except OrcaRouterAuthError:
					# Preserve the upstream authentication error if local status persistence fails.
					pass
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
