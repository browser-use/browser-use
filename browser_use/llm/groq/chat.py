import logging
from dataclasses import dataclass
from typing import Literal, TypeVar, overload

from groq import (
	APIError,
	APIResponseValidationError,
	APIStatusError,
	AsyncGroq,
	NotGiven,
	RateLimitError,
	Timeout,
)
from groq.types.chat import ChatCompletion
from groq.types.chat.completion_create_params import (
	ResponseFormatResponseFormatJsonSchema,
	ResponseFormatResponseFormatJsonSchemaJsonSchema,
)
from httpx import URL
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel, ChatInvokeCompletion
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.groq.parser import try_parse_groq_failed_generation
from browser_use.llm.groq.serializer import GroqMessageSerializer
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeUsage

GroqVerifiedModels = Literal[
	'meta-llama/llama-4-maverick-17b-128e-instruct', 'meta-llama/llama-4-scout-17b-16e-instruct', 'qwen/qwen3-32b'
]

T = TypeVar('T', bound=BaseModel)

logger = logging.getLogger(__name__)


@dataclass
class ChatGroq(BaseChatModel):
	"""
	A wrapper around AsyncGroq that implements the BaseLLM protocol.
	"""

	# Model configuration
	model: GroqVerifiedModels | str

	# Model params
	temperature: float | None = None
	service_tier: Literal['auto', 'on_demand', 'flex'] | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | URL | None = None
	timeout: float | Timeout | NotGiven | None = None
	max_retries: int = 10  # Increase default retries for automation reliability

	def get_client(self) -> AsyncGroq:
		return AsyncGroq(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, max_retries=self.max_retries)

	@property
	def provider(self) -> str:
		return 'groq'

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		usage = (
			ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				completion_tokens=response.usage.completion_tokens,
				total_tokens=response.usage.total_tokens,
				prompt_cached_tokens=None,  # Groq doesn't support cached tokens
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
			)
			if response.usage is not None
			else None
		)
		return usage

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		groq_messages = GroqMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				chat_completion = await self.get_client().chat.completions.create(
					messages=groq_messages,
					model=self.model,
					temperature=self.temperature,
					service_tier=self.service_tier,
				)
				usage = self._get_usage(chat_completion)
				return ChatInvokeCompletion(
					completion=chat_completion.choices[0].message.content or '',
					usage=usage,
				)

			else:
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)

				schema['additionalProperties'] = False

				# Return structured response
				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=groq_messages,
					temperature=self.temperature,
					response_format=ResponseFormatResponseFormatJsonSchema(
						json_schema=ResponseFormatResponseFormatJsonSchemaJsonSchema(
							name=output_format.__name__,
							description='Model output schema',
							schema=schema,
						),
						type='json_schema',
					),
					service_tier=self.service_tier,
				)

				if not response.choices[0].message.content:
					raise ModelProviderError(
						message='No content in response',
						status_code=500,
						model=self.name,
					)

				parsed_response = output_format.model_validate_json(response.choices[0].message.content)

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=parsed_response,
					usage=usage,
				)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e

		except APIResponseValidationError as e:
			raise ModelProviderError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e

		except APIStatusError as e:
			if output_format is None:
				raise ModelProviderError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e
			else:
				try:
					logger.debug(f'Groq failed generation: {e.response.text}; fallback to manual parsing')

					parsed_response = try_parse_groq_failed_generation(e, output_format)

					logger.debug('Manual error parsing successful ✅')

					return ChatInvokeCompletion(
						completion=parsed_response,
						usage=None,  # because this is a hacky way to get the outputs
						# TODO: @groq needs to fix their parsers and validators
					)
				except Exception as _:
					raise ModelProviderError(message=str(e), status_code=e.response.status_code, model=self.name) from e

		except APIError as e:
			raise ModelProviderError(message=e.message, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
