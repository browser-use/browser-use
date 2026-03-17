import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

from .serializer import LiteLLMMessageSerializer

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatLiteLLM(BaseChatModel):
	model: str
	api_key: str | None = None
	api_base: str | None = None
	temperature: float | None = 0.0
	max_tokens: int | None = 4096
	max_retries: int = 3
	metadata: dict[str, Any] | None = None

	_provider_name: str = field(default='', init=False, repr=False)
	_clean_model: str = field(default='', init=False, repr=False)

	def __post_init__(self) -> None:
		"""Resolve provider info from the model string via litellm."""
		try:
			from litellm import get_llm_provider

			self._clean_model, self._provider_name, _, _ = get_llm_provider(self.model)
		except Exception:
			if '/' in self.model:
				self._provider_name, self._clean_model = self.model.split('/', 1)
			else:
				self._provider_name = 'openai'
				self._clean_model = self.model

		logger.debug(
			'ChatLiteLLM initialized: model=%s, provider=%s, clean=%s, api_base=%s',
			self.model,
			self._provider_name,
			self._clean_model,
			self.api_base or '(default)',
		)

	@property
	def provider(self) -> str:
		return self._provider_name or 'litellm'

	@property
	def name(self) -> str:
		return self._clean_model or self.model

	@staticmethod
	def _parse_usage(response: Any) -> ChatInvokeUsage | None:
		"""Extract token usage from a litellm response."""
		usage = getattr(response, 'usage', None)
		if usage is None:
			return None

		prompt_tokens = getattr(usage, 'prompt_tokens', 0) or 0
		completion_tokens = getattr(usage, 'completion_tokens', 0) or 0

		prompt_cached = getattr(usage, 'cache_read_input_tokens', None)
		cache_creation = getattr(usage, 'cache_creation_input_tokens', None)

		if prompt_cached is None:
			details = getattr(usage, 'prompt_tokens_details', None)
			if details:
				prompt_cached = getattr(details, 'cached_tokens', None)

		return ChatInvokeUsage(
			prompt_tokens=prompt_tokens,
			prompt_cached_tokens=int(prompt_cached) if prompt_cached is not None else None,
			prompt_cache_creation_tokens=int(cache_creation) if cache_creation is not None else None,
			prompt_image_tokens=None,
			completion_tokens=completion_tokens,
			total_tokens=prompt_tokens + completion_tokens,
		)

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T],
		**kwargs: Any,
	) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self,
		messages: list[BaseMessage],
		output_format: type[T] | None = None,
		**kwargs: Any,
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		from litellm import acompletion
		from litellm.exceptions import APIConnectionError, APIError, RateLimitError, Timeout
		from litellm.types.utils import ModelResponse

		litellm_messages = LiteLLMMessageSerializer.serialize(messages)

		params: dict[str, Any] = {
			'model': self.model,
			'messages': litellm_messages,
			'num_retries': self.max_retries,
		}

		if self.temperature is not None:
			params['temperature'] = self.temperature
		if self.max_tokens is not None:
			params['max_tokens'] = self.max_tokens
		if self.api_key:
			params['api_key'] = self.api_key
		if self.api_base:
			params['api_base'] = self.api_base
		if self.metadata:
			params['metadata'] = self.metadata

		if output_format is not None:
			schema = SchemaOptimizer.create_optimized_json_schema(output_format)
			params['response_format'] = {
				'type': 'json_schema',
				'json_schema': {
					'name': 'agent_output',
					'strict': True,
					'schema': schema,
				},
			}

		try:
			raw_response = await acompletion(**params)
		except RateLimitError as e:
			raise ModelRateLimitError(
				message=str(e),
				model=self.name,
			) from e
		except Timeout as e:
			raise ModelProviderError(
				message=f'Request timed out: {e}',
				model=self.name,
			) from e
		except APIConnectionError as e:
			raise ModelProviderError(
				message=str(e),
				model=self.name,
			) from e
		except APIError as e:
			status = getattr(e, 'status_code', 502) or 502
			raise ModelProviderError(
				message=str(e),
				status_code=status,
				model=self.name,
			) from e
		except ModelProviderError:
			raise
		except Exception as e:
			raise ModelProviderError(
				message=str(e),
				model=self.name,
			) from e

		assert isinstance(raw_response, ModelResponse), f'Expected ModelResponse, got {type(raw_response)}'
		response: ModelResponse = raw_response

		choice = response.choices[0] if response.choices else None
		if choice is None:
			raise ModelProviderError(
				message='Empty response: no choices returned by the model',
				status_code=502,
				model=self.name,
			)

		content = choice.message.content or ''
		usage = self._parse_usage(response)
		stop_reason = choice.finish_reason

		thinking: str | None = None
		msg_obj = choice.message
		reasoning = getattr(msg_obj, 'reasoning_content', None)
		if reasoning:
			thinking = str(reasoning)

		if output_format is not None:
			if not content:
				raise ModelProviderError(
					message='Model returned empty content for structured output request',
					status_code=500,
					model=self.name,
				)
			parsed = output_format.model_validate_json(content)
			return ChatInvokeCompletion(
				completion=parsed,
				thinking=thinking,
				usage=usage,
				stop_reason=stop_reason,
			)

		return ChatInvokeCompletion(
			completion=content,
			thinking=thinking,
			usage=usage,
			stop_reason=stop_reason,
		)
