import logging
from dataclasses import dataclass, field
from typing import Literal, TypeVar, overload

from mistralai import Mistral, RetryConfig
from mistralai.models import (
	ChatCompletionResponse,
	HTTPValidationError,
	JSONSchema,
	ResponseFormat,
	SDKError,
	TextChunk,
)
from mistralai.types import UNSET
from mistralai.utils import BackoffStrategy
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.mistral.serializer import MistralMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)
logger = logging.getLogger(__name__)

# Verified Mistral models
MistralVerifiedModels = Literal[
	'mistral-large-latest',
	'mistral-medium-latest',
	'mistral-small-latest',
	'ministral-8b-latest',
	'ministral-3b-latest',
	'pixtral-12b-latest',
	'codestral-latest',
]


@dataclass
class ChatMistral(BaseChatModel):
	"""
	A wrapper around Mistral SDK that implements the BaseLLM protocol.
	"""

	# Model configuration
	model: MistralVerifiedModels | str

	# Model params
	temperature: float | None = 0.2
	top_p: float | None = None
	max_tokens: int | None = 8000
	random_seed: int | None = None
	safe_prompt: bool = False

	# Client initialization parameters
	api_key: str | None = None
	server: Literal['eu'] | None = 'eu'
	server_url: str | None = None
	timeout_ms: int | None = None
	retry_initial_interval: int = 1
	retry_max_interval: int = 50
	retry_exponent: float = 1.1
	retry_max_elapsed_time: int = 100

	# Cached client instance
	_client: Mistral | None = field(default=None, init=False)

	@property
	def provider(self) -> str:
		return 'mistral'

	@property
	def name(self) -> str:
		return str(self.model)

	def get_client(self) -> Mistral:
		"""Get Mistral client instance."""
		if self._client is None:
			self._client = Mistral(
				api_key=self.api_key,
				server=self.server,
				server_url=self.server_url,
				timeout_ms=self.timeout_ms,
				retry_config=RetryConfig(
					strategy='backoff',
					backoff=BackoffStrategy(
						initial_interval=self.retry_initial_interval,
						max_interval=self.retry_max_interval,
						exponent=self.retry_exponent,
						max_elapsed_time=self.retry_max_elapsed_time,
					),
					retry_connection_errors=False,
				),
			)
		return self._client

	def _get_usage(self, response: ChatCompletionResponse) -> ChatInvokeUsage | None:
		"""Extract usage information from Mistral response."""
		if response.usage is not None:
			return ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens or 0,
				completion_tokens=response.usage.completion_tokens or 0,
				total_tokens=response.usage.total_tokens or 0,
				prompt_cached_tokens=None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
			)
		return None

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		"""
		Invoke the Mistral model with the given messages.

		Args:
		    messages: List of chat messages
		    output_format: Optional Pydantic model class for structured output

		Returns:
		    Either a string response or an instance of output_format
		"""
		mistral_messages = MistralMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				return await self._invoke_regular_completion(mistral_messages)
			else:
				return await self._invoke_structured_output(mistral_messages, output_format)

		except HTTPValidationError as e:
			error_details = []
			if e.data and e.data.detail:
				for validation_error in e.data.detail:
					error_details.append(f'{".".join(str(loc) for loc in validation_error.loc)}: {validation_error.msg}')

			error_message = (
				f'Request validation failed: {"; ".join(error_details)}' if error_details else 'Request validation failed'
			)
			raise ModelProviderError(
				message=error_message,
				status_code=422,
				model=self.name,
			) from e

		except SDKError as e:
			if e.status_code == 429:
				raise ModelRateLimitError(
					message=f'Rate limit exceeded: {e.message}',
					model=self.name,
				) from e
			elif e.status_code in [401, 403]:
				raise ModelProviderError(
					message=f'Authentication error: {e.message}',
					status_code=e.status_code,
					model=self.name,
				) from e
			else:
				raise ModelProviderError(
					message=f'Server error: {e.message}',
					status_code=e.status_code,
					model=self.name,
				) from e
		except Exception as e:
			logger.warning(f'Unexpected error in Mistral API call: {type(e).__name__}: {e}')
			raise ModelProviderError(message=str(e), model=self.name) from e

	async def _invoke_regular_completion(self, mistral_messages) -> ChatInvokeCompletion[str]:
		"""Handle regular completion without structured output."""
		request_params = self._prepare_request_params(mistral_messages)

		response: ChatCompletionResponse = await self.get_client().chat.complete_async(**request_params)

		content = self._extract_response_content(response)
		usage = self._get_usage(response)

		return ChatInvokeCompletion(completion=content, usage=usage)

	async def _invoke_structured_output(self, mistral_messages, output_format: type[T]) -> ChatInvokeCompletion[T]:
		"""Handle structured output using JSON schema."""
		request_params = self._prepare_request_params(mistral_messages, output_format)

		response: ChatCompletionResponse = await self.get_client().chat.complete_async(**request_params)

		content = self._extract_response_content(response)
		usage = self._get_usage(response)

		try:
			parsed = output_format.model_validate_json(content)
			return ChatInvokeCompletion(completion=parsed, usage=usage)
		except Exception as e:
			logger.error(f'Failed to parse structured output. Content: {content!r}, Error: {e}')
			raise ModelProviderError(
				message=f'Failed to parse structured output: {e}',
				status_code=500,
				model=self.name,
			) from e

	def _prepare_request_params(self, mistral_messages, output_format: type[T] | None = None) -> dict:
		"""Prepare request parameters for Mistral API call."""
		request_params = {
			'model': self.model,
			'messages': mistral_messages,
			'stream': False,
		}

		if self.temperature is not None:
			request_params['temperature'] = self.temperature
		if self.top_p is not None:
			request_params['top_p'] = self.top_p
		if self.max_tokens is not None:
			request_params['max_tokens'] = self.max_tokens
		if self.random_seed is not None:
			request_params['random_seed'] = self.random_seed
		if self.safe_prompt:
			request_params['safe_prompt'] = self.safe_prompt

		if output_format is not None:
			optimized_schema = SchemaOptimizer.create_optimized_json_schema(output_format)
			json_schema = JSONSchema(
				name=output_format.__name__,
				schema_definition=optimized_schema,
			)
			request_params['response_format'] = ResponseFormat(type='json_schema', json_schema=json_schema)

		return request_params

	def _extract_response_content(self, response: ChatCompletionResponse) -> str:
		"""Extract content from Mistral API response."""
		if not response.choices:
			raise ModelProviderError(
				message='No choices returned from Mistral API',
				status_code=500,
				model=self.name,
			)

		content = response.choices[0].message.content

		if content is None or content is UNSET:
			raise ModelProviderError(
				message='No content in response from Mistral API',
				status_code=500,
				model=self.name,
			)

		if isinstance(content, list):
			text_parts = []
			for chunk in content:
				if isinstance(chunk, TextChunk):
					text_parts.append(chunk.text)
				else:
					text_parts.append(str(chunk))
			result = ''.join(text_parts) if text_parts else ''
			return result

		return str(content)
