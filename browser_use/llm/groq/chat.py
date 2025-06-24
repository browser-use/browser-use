from dataclasses import dataclass
from typing import Literal, TypeVar, overload

from groq import (
	DEFAULT_MAX_RETRIES,
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
from browser_use.llm.groq.serializer import GroqMessageSerializer
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeUsage

GroqVerifiedModels = Literal[
	'meta-llama/llama-4-maverick-17b-128e-instruct', 'meta-llama/llama-4-scout-17b-16e-instruct', 'qwen/qwen3-32b'
]

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatGroq(BaseChatModel):
	"""
	A wrapper around AsyncGroq that implements the BaseLLM protocol.
	"""

	# Model configuration
	model: GroqVerifiedModels | str

	# Model params
	temperature: float | None = None

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | URL | None = None
	timeout: float | Timeout | NotGiven | None = None
	max_retries: int = DEFAULT_MAX_RETRIES

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
				)
				usage = self._get_usage(chat_completion)
				return ChatInvokeCompletion(
					completion=chat_completion.choices[0].message.content or '',
					usage=usage,
				)

			else:
				schema = output_format.model_json_schema()
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
							strict=True,
						),
						type='json_schema',
					),
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

		except (APIResponseValidationError, APIStatusError) as e:
			raise ModelProviderError(message=e.response.text, status_code=e.response.status_code, model=self.name) from e
		except APIError as e:
			raise ModelProviderError(message=e.message, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
