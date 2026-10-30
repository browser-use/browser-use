import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.shared_params.response_format_json_schema import (
	JSONSchema,
	ResponseFormatJSONSchema,
)
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)

GMI_BASE_URL = 'https://api.gmi-serving.com/v1'


def _strip_additional_properties(node: Any, in_properties_map: bool = False) -> Any:
	"""Return a copy of a JSON schema without `additionalProperties` keywords.

	GMI forwards Gemini requests to Google's `response_schema`, which rejects `additionalProperties`
	(`Unknown name "additionalProperties" ... Cannot find field`), most visibly inside `anyOf` branches.
	`in_properties_map` is True for the value of a `properties` keyword: its keys are field names, so a field
	that is itself named `additionalProperties` (or `properties`) is kept and only its schema is cleaned.
	"""
	if isinstance(node, dict):
		return {
			key: _strip_additional_properties(value, key == 'properties' and not in_properties_map)
			for key, value in node.items()
			if in_properties_map or key != 'additionalProperties'
		}
	if isinstance(node, list):
		return [_strip_additional_properties(item) for item in node]
	return node


def _gmi_error_detail(body: object) -> str | None:
	"""Extract the real failure reason from a GMI error body.

	GMI wraps upstream failures as `Backend request failed with status 400` and keeps the actionable
	reason (e.g. `Penalty is not enabled for this model`) in `error.details`, usually as a nested JSON
	string. The OpenAI SDK's `APIStatusError.message` drops it, so we recover it here.
	"""
	if not isinstance(body, dict):
		return None
	# The SDK passes the unwrapped error dict; also accept a body that is still wrapped in `error`.
	error = body['error'] if 'details' not in body and isinstance(body.get('error'), dict) else body
	details = error.get('details')
	if not isinstance(details, str) or not details.strip():
		return None
	try:
		inner = json.loads(details)
	except ValueError:
		return details.strip()[:500]
	if isinstance(inner, dict):
		error = inner.get('error', inner)
		if isinstance(error, dict) and isinstance(error.get('message'), str) and error['message'].strip():
			return error['message'].strip()[:500]
	return details.strip()[:500]


def _describe_status_error(error: APIStatusError) -> str:
	"""The SDK message plus GMI's real reason, when GMI provides one."""
	detail = _gmi_error_detail(error.body)
	if detail and detail not in error.message:
		return f'{error.message}: {detail}'
	return error.message


@dataclass
class ChatGMI(BaseChatModel):
	"""
	A wrapper around GMI Cloud's OpenAI-compatible inference API (https://api.gmi-serving.com/v1).

	This class implements the BaseChatModel protocol for GMI Cloud. The API key is read from the
	`api_key` argument or the `GMI_API_KEY` environment variable; it never falls back to
	`OPENAI_API_KEY`.
	"""

	# Model configuration
	model: str

	# Model params (only sent when set)
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None
	max_completion_tokens: int | None = None
	# Strip `additionalProperties` from the structured-output schema. None = automatic: on for Gemini models,
	# which GMI cannot serve it for. Set True/False to override.
	remove_additional_properties_from_schema: bool | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL = GMI_BASE_URL
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 5
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None
	_strict_response_validation: bool = False
	extra_body: dict[str, Any] | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'gmi'

	@property
	def name(self) -> str:
		return str(self.model)

	def _should_remove_additional_properties(self) -> bool:
		if self.remove_additional_properties_from_schema is not None:
			return self.remove_additional_properties_from_schema
		return 'gemini' in self.name.lower()

	def _get_api_key(self) -> str:
		# AsyncOpenAI falls back to OPENAI_API_KEY when api_key is unset, which would send an
		# unrelated provider's key to the GMI endpoint. Resolve the key explicitly instead.
		key = self.api_key or os.getenv('GMI_API_KEY')
		if not key:
			raise ModelProviderError(
				message='Missing GMI API key. Set GMI_API_KEY or pass api_key.',
				status_code=401,
				model=self.name,
			)
		return key

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		base_params = {
			'api_key': self._get_api_key(),
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
		Returns an AsyncOpenAI client configured for GMI Cloud.

		Returns:
		    AsyncOpenAI: An instance of the AsyncOpenAI client with the GMI base URL.
		"""
		if not hasattr(self, '_client'):
			self._client = AsyncOpenAI(**self._get_client_params())
		return self._client

	def _get_request_params(self) -> dict[str, Any]:
		"""Request-level params. None values are omitted: the SDK would otherwise send them as JSON null."""
		params: dict[str, Any] = {
			'temperature': self.temperature,
			'top_p': self.top_p,
			'seed': self.seed,
			'max_completion_tokens': self.max_completion_tokens,
		}
		return {k: v for k, v in params.items() if v is not None}

	def _get_first_choice(self, response: ChatCompletion) -> Choice:
		if response.choices:
			return response.choices[0]
		base_url = str(self.base_url)
		raise ModelProviderError(
			message=(
				'Invalid GMI chat completion response: missing or empty `choices`.'
				' If you are using a proxy via `base_url`, ensure it implements the OpenAI'
				' `/v1/chat/completions` schema and returns `choices` as a non-empty list.'
				f' (base_url={base_url})'
			),
			status_code=502,
			model=self.name,
		)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		"""Extract usage information from the GMI response."""
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
		Invoke the model with the given messages through GMI Cloud.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		gmi_messages = OpenAIMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=gmi_messages,
					extra_body=self.extra_body,
					**self._get_request_params(),
				)

				choice = self._get_first_choice(response)
				return ChatInvokeCompletion(
					completion=choice.message.content or '',
					usage=self._get_usage(response),
					stop_reason=choice.finish_reason,
				)

			# Create a JSON schema for structured output
			schema = SchemaOptimizer.create_optimized_json_schema(output_format)
			if self._should_remove_additional_properties():
				schema = _strip_additional_properties(schema)

			response_format: JSONSchema = {'name': 'agent_output', 'strict': True, 'schema': schema}

			response = await self.get_client().chat.completions.create(
				model=self.model,
				messages=gmi_messages,
				response_format=ResponseFormatJSONSchema(json_schema=response_format, type='json_schema'),
				extra_body=self.extra_body,
				**self._get_request_params(),
			)

			choice = self._get_first_choice(response)

			# before the empty-content guard: reasoning models can burn the whole budget on
			# hidden reasoning, leaving finish_reason='length' with no content
			if choice.finish_reason == 'length':
				cap = (
					f'max_completion_tokens={self.max_completion_tokens}'
					if self.max_completion_tokens is not None
					else "the model's output token limit"
				)
				raise ModelOutputTruncatedError(
					message=(
						f'Model output was truncated at {cap}; the structured output is incomplete.'
						' Increase max_completion_tokens or request shorter output.'
					),
					model=self.name,
				)

			if not choice.message.content:
				raise ModelProviderError(
					message=f'Failed to parse structured output from model response (finish_reason={choice.finish_reason}).',
					status_code=500,
					model=self.name,
				)

			parsed = output_format.model_validate_json(choice.message.content)

			return ChatInvokeCompletion(
				completion=parsed,
				usage=self._get_usage(response),
				stop_reason=choice.finish_reason,
			)

		except ModelProviderError:
			# Preserve status_code and message from validation errors
			raise

		except RateLimitError as e:
			raise ModelRateLimitError(message=_describe_status_error(e), model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=_describe_status_error(e), status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
