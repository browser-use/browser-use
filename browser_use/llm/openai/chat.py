import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, overload
from uuid import uuid4

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionContentPartTextParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.shared.chat_model import ChatModel
from openai.types.shared_params.reasoning_effort import ReasoningEffort
from openai.types.shared_params.response_format_json_schema import JSONSchema, ResponseFormatJSONSchema
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.responses import build_responses_request, parse_responses_completion
from browser_use.llm.openai.responses_websocket import ResponsesWebSocketTransport
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatOpenAI(BaseChatModel):
	"""
	A wrapper around AsyncOpenAI that implements the BaseLLM protocol.

	This class accepts all AsyncOpenAI parameters and supports Chat Completions,
	HTTP Responses, and persistent Responses WebSocket transports.

	Set ``transport='responses_websocket'`` to send full-context Responses requests
	over a session-scoped persistent socket. ``websocket_base_url`` may be either a
	WebSocket API root or a complete ``/responses`` endpoint; when omitted, it is
	derived from ``base_url`` or the OpenAI API URL.
	"""

	# Model configuration
	model: ChatModel | str
	transport: Literal['chat_completions', 'responses', 'responses_websocket'] = 'chat_completions'
	responses_store: bool = True

	# Model params
	temperature: float | None = 0.2
	frequency_penalty: float | None = 0.3  # this avoids infinite generation of \t for models like 4.1-mini
	reasoning_effort: ReasoningEffort = 'low'
	seed: int | None = None
	service_tier: Literal['auto', 'default', 'flex', 'priority', 'scale'] | None = None
	top_p: float | None = None
	add_schema_to_system_prompt: bool = False  # Add JSON schema to system prompt instead of using response_format
	dont_force_structured_output: bool = False  # If True, the model will not be forced to output a structured output
	remove_min_items_from_schema: bool = (
		False  # If True, remove minItems from JSON schema (for compatibility with some providers)
	)
	remove_defaults_from_schema: bool = (
		False  # If True, remove default values from JSON schema (for compatibility with some providers)
	)

	# Client initialization parameters
	api_key: str | None = None
	organization: str | None = None
	project: str | None = None
	base_url: str | httpx.URL | None = None
	websocket_base_url: str | httpx.URL | None = None
	timeout: float | httpx.Timeout | None = None
	max_retries: int = 5  # Increase default retries for automation reliability
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None
	_strict_response_validation: bool = False
	max_completion_tokens: int | None = 4096
	reasoning_models: list[ChatModel | str] | None = field(
		default_factory=lambda: [
			'o4-mini',
			'o3',
			'o3-mini',
			'o1',
			'o1-pro',
			'o3-pro',
			'gpt-5',
			'gpt-5-mini',
			'gpt-5-nano',
		]
	)
	_responses_websocket_transport: ResponsesWebSocketTransport | None = field(
		default=None, init=False, repr=False, compare=False
	)
	_client: AsyncOpenAI | None = field(default=None, init=False, repr=False, compare=False)

	# Static
	@property
	def provider(self) -> str:
		return 'openai'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Define base client params
		base_params = {
			'api_key': self.api_key,
			'organization': self.organization,
			'project': self.project,
			'base_url': self.base_url,
			'websocket_base_url': self.websocket_base_url,
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
		Returns an AsyncOpenAI client.

		Returns:
			AsyncOpenAI: An instance of the AsyncOpenAI client.
		"""
		if self._client is None:
			self._client = AsyncOpenAI(**self._get_client_params())
		return self._client

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is not None:
			# Note: completion_tokens already includes reasoning_tokens per OpenAI API docs.
			# Unlike Google Gemini where thinking_tokens are reported separately,
			# OpenAI's reasoning_tokens are a subset of completion_tokens.
			usage = ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				prompt_cached_tokens=response.usage.prompt_tokens_details.cached_tokens
				if response.usage.prompt_tokens_details is not None
				else None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
				# Completion
				completion_tokens=response.usage.completion_tokens,
				total_tokens=response.usage.total_tokens,
			)
		else:
			usage = None

		return usage

	def _is_reasoning_model(self) -> bool:
		return bool(
			self.reasoning_models
			and any(str(candidate).lower() in str(self.model).lower() for candidate in self.reasoning_models)
		)

	def _build_responses_request(self, messages: list[BaseMessage], output_format: type[BaseModel] | None) -> dict[str, Any]:
		return build_responses_request(
			model=str(self.model),
			messages=messages,
			output_format=output_format,
			temperature=self.temperature,
			max_output_tokens=self.max_completion_tokens,
			top_p=self.top_p,
			service_tier=self.service_tier,
			reasoning_effort=self.reasoning_effort,
			is_reasoning_model=self._is_reasoning_model(),
			add_schema_to_system_prompt=self.add_schema_to_system_prompt,
			dont_force_structured_output=self.dont_force_structured_output,
			remove_min_items_from_schema=self.remove_min_items_from_schema,
			remove_defaults_from_schema=self.remove_defaults_from_schema,
		)

	def _get_responses_websocket_transport(self) -> ResponsesWebSocketTransport:
		if self._responses_websocket_transport is None:
			self._responses_websocket_transport = ResponsesWebSocketTransport(
				api_key=self.api_key or os.getenv('OPENAI_API_KEY'),
				organization=self.organization or os.getenv('OPENAI_ORG_ID'),
				project=self.project or os.getenv('OPENAI_PROJECT_ID'),
				base_url=self.base_url or os.getenv('OPENAI_BASE_URL'),
				websocket_base_url=self.websocket_base_url,
				timeout=self.timeout,
				default_headers=self.default_headers,
				default_query=self.default_query,
				model=self.name,
			)
		return self._responses_websocket_transport

	async def _invoke_responses(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		request = self._build_responses_request(messages, output_format)
		request['store'] = self.responses_store

		try:
			if self.transport == 'responses':
				response = await self.get_client().responses.create(**request)
			else:
				session_id = kwargs.get('session_id')
				ephemeral = not isinstance(session_id, str) or not session_id
				session_prefix = str(session_id) if not ephemeral else f'ephemeral-{uuid4()}'
				session_key = f'{session_prefix}:{kwargs.get("invocation_scope", "agent")}'
				response = None
				try:
					for attempt in range(2):
						try:
							response = await self._get_responses_websocket_transport().send(
								session_key=session_key, request=request
							)
							break
						except ConnectionError:
							if attempt == 1:
								raise
					if response is None:
						raise ModelProviderError(message='Responses WebSocket retry exhausted', status_code=502, model=self.name)
				finally:
					if ephemeral:
						await self.close_session(session_prefix)

			return parse_responses_completion(
				response,
				output_format,
				model=self.name,
				max_output_tokens=self.max_completion_tokens,
			)
		except ModelProviderError:
			raise
		except RateLimitError as exc:
			raise ModelRateLimitError(message=exc.message, model=self.name) from exc
		except APIStatusError as exc:
			raise ModelProviderError(message=exc.message, status_code=exc.status_code, model=self.name) from exc
		except (APIConnectionError, TimeoutError, ConnectionError) as exc:
			raise ModelProviderError(message=str(exc), status_code=502, model=self.name) from exc
		except Exception as exc:
			raise ModelProviderError(message=str(exc), model=self.name) from exc

	async def close_session(self, session_id: str) -> None:
		"""Close Responses resources owned by one agent session."""
		if self._responses_websocket_transport is not None:
			await self._responses_websocket_transport.close_session(session_id)

	async def aclose(self) -> None:
		"""Close every Responses resource owned by this model instance."""
		if self._responses_websocket_transport is not None:
			await self._responses_websocket_transport.close()
			self._responses_websocket_transport = None
		if self._client is not None:
			await self._client.close()
			self._client = None

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
		Invoke the model with the given messages.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""

		if self.transport == 'responses':
			return await self._invoke_responses(messages, output_format, **kwargs)
		if self.transport == 'responses_websocket':
			return await self._invoke_responses(messages, output_format, **kwargs)
		if self.transport != 'chat_completions':
			raise ModelProviderError(message=f'Unsupported OpenAI transport: {self.transport}', model=self.name)

		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)

		try:
			model_params: dict[str, Any] = {}

			if self.temperature is not None:
				model_params['temperature'] = self.temperature

			if self.frequency_penalty is not None:
				model_params['frequency_penalty'] = self.frequency_penalty

			if self.max_completion_tokens is not None:
				model_params['max_completion_tokens'] = self.max_completion_tokens

			if self.top_p is not None:
				model_params['top_p'] = self.top_p

			if self.seed is not None:
				model_params['seed'] = self.seed

			if self.service_tier is not None:
				model_params['service_tier'] = self.service_tier

			if self.reasoning_models and any(str(m).lower() in str(self.model).lower() for m in self.reasoning_models):
				model_params['reasoning_effort'] = self.reasoning_effort
				model_params.pop('temperature', None)
				model_params.pop('frequency_penalty', None)

			if output_format is None:
				# Return string response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					**model_params,
				)

				choice = response.choices[0] if response.choices else None
				if choice is None:
					base_url = str(self.base_url) if self.base_url is not None else None
					hint = f' (base_url={base_url})' if base_url is not None else ''
					raise ModelProviderError(
						message=(
							'Invalid OpenAI chat completion response: missing or empty `choices`.'
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
					stop_reason=choice.finish_reason,
				)

			else:
				response_format: JSONSchema = {
					'name': 'agent_output',
					'strict': True,
					'schema': SchemaOptimizer.create_optimized_json_schema(
						output_format,
						remove_min_items=self.remove_min_items_from_schema,
						remove_defaults=self.remove_defaults_from_schema,
					),
				}

				# Add JSON schema to system prompt if requested
				if self.add_schema_to_system_prompt and openai_messages and openai_messages[0]['role'] == 'system':
					schema_text = f'\n<json_schema>\n{response_format}\n</json_schema>'
					if isinstance(openai_messages[0]['content'], str):
						openai_messages[0]['content'] += schema_text
					elif isinstance(openai_messages[0]['content'], Iterable):
						openai_messages[0]['content'] = list(openai_messages[0]['content']) + [
							ChatCompletionContentPartTextParam(text=schema_text, type='text')
						]

				if self.dont_force_structured_output:
					response = await self.get_client().chat.completions.create(
						model=self.model,
						messages=openai_messages,
						**model_params,
					)
				else:
					# Return structured response
					response = await self.get_client().chat.completions.create(
						model=self.model,
						messages=openai_messages,
						response_format=ResponseFormatJSONSchema(json_schema=response_format, type='json_schema'),
						**model_params,
					)

				choice = response.choices[0] if response.choices else None
				if choice is None:
					base_url = str(self.base_url) if self.base_url is not None else None
					hint = f' (base_url={base_url})' if base_url is not None else ''
					raise ModelProviderError(
						message=(
							'Invalid OpenAI chat completion response: missing or empty `choices`.'
							' If you are using a proxy via `base_url`, ensure it implements the OpenAI'
							' `/v1/chat/completions` schema and returns `choices` as a non-empty list.'
							f'{hint}'
						),
						status_code=502,
						model=self.name,
					)

				# before the content-None guard: reasoning models can burn the whole budget
				# on hidden reasoning, leaving finish_reason='length' with content=None
				if choice.finish_reason == 'length':
					cap = (
						f'max_completion_tokens={self.max_completion_tokens}'
						if self.max_completion_tokens is not None
						else "the model's output token limit"
					)
					raise ModelOutputTruncatedError(
						message=(
							f'Model output was truncated at {cap};'
							' the structured output is incomplete. Increase max_completion_tokens or request'
							' shorter output.'
						),
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
					stop_reason=choice.finish_reason,
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
