import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, overload

from anthropic import (
	NOT_GIVEN,
	APIConnectionError,
	APIStatusError,
	AsyncAnthropicBedrock,
	RateLimitError,
)
from anthropic.types import CacheControlEphemeralParam, Message, ToolParam
from anthropic.types.text_block import TextBlock
from anthropic.types.tool_choice_tool_param import ToolChoiceToolParam
from pydantic import BaseModel

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.aws.chat_bedrock import ChatAWSBedrock
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

if TYPE_CHECKING:
	from boto3.session import Session  # pyright: ignore


T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAnthropicBedrock(ChatAWSBedrock):
	"""
	AWS Bedrock Anthropic Claude chat model.

	This is a convenience class that provides Claude-specific defaults
	for the AWS Bedrock service. It inherits all functionality from
	ChatAWSBedrock but sets Anthropic Claude as the default model.
	"""

	# Anthropic Claude specific defaults
	model: str = 'anthropic.claude-3-5-sonnet-20240620-v1:0'
	max_tokens: int = 8192
	temperature: float | None = None
	top_p: float | None = None
	top_k: int | None = None
	stop_sequences: list[str] | None = None

	# AWS credentials and configuration
	aws_access_key: str | None = None
	aws_secret_key: str | None = None
	aws_session_token: str | None = None
	aws_region: str | None = None
	session: 'Session | None' = None

	# Client initialization parameters
	max_retries: int = 10
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None

	@property
	def provider(self) -> str:
		return 'anthropic_bedrock'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary for Bedrock."""
		client_params: dict[str, Any] = {}

		if self.session:
			credentials = self.session.get_credentials()
			client_params.update(
				{
					'aws_access_key': credentials.access_key,
					'aws_secret_key': credentials.secret_key,
					'aws_session_token': credentials.token,
					'aws_region': self.session.region_name,
				}
			)
		else:
			# Use individual credentials
			if self.aws_access_key:
				client_params['aws_access_key'] = self.aws_access_key
			if self.aws_secret_key:
				client_params['aws_secret_key'] = self.aws_secret_key
			if self.aws_region:
				client_params['aws_region'] = self.aws_region
			if self.aws_session_token:
				client_params['aws_session_token'] = self.aws_session_token

		# Add optional parameters
		if self.max_retries:
			client_params['max_retries'] = self.max_retries
		if self.default_headers:
			client_params['default_headers'] = self.default_headers
		if self.default_query:
			client_params['default_query'] = self.default_query

		return client_params

	def _get_client_params_for_invoke(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary for invoke."""
		client_params = {}

		if self.temperature is not None:
			client_params['temperature'] = self.temperature
		if self.max_tokens is not None:
			client_params['max_tokens'] = self.max_tokens
		if self.top_p is not None:
			client_params['top_p'] = self.top_p
		if self.top_k is not None:
			client_params['top_k'] = self.top_k
		if self.stop_sequences is not None:
			client_params['stop_sequences'] = self.stop_sequences

		return client_params

	def get_client(self) -> AsyncAnthropicBedrock:
		"""
		Returns an AsyncAnthropicBedrock client.

		Returns:
			AsyncAnthropicBedrock: An instance of the AsyncAnthropicBedrock client.
		"""
		client_params = self._get_client_params()
		return AsyncAnthropicBedrock(**client_params)

	@property
	def name(self) -> str:
		return str(self.model)

	def _get_usage(self, response: Message) -> ChatInvokeUsage | None:
		"""Extract usage information from the response."""
		usage = ChatInvokeUsage(
			prompt_tokens=response.usage.input_tokens
			+ (
				response.usage.cache_read_input_tokens or 0
			),  # Total tokens in Anthropic are a bit fucked, you have to add cached tokens to the prompt tokens
			completion_tokens=response.usage.output_tokens,
			total_tokens=response.usage.input_tokens + response.usage.output_tokens,
			prompt_cached_tokens=response.usage.cache_read_input_tokens,
			prompt_cache_creation_tokens=response.usage.cache_creation_input_tokens,
			prompt_image_tokens=None,
		)
		return usage

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		anthropic_messages, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

		try:
			if output_format is None:
				# Normal completion without structured output
				response = await self.get_client().messages.create(
					model=self.model,
					messages=anthropic_messages,
					system=system_prompt or NOT_GIVEN,
					**self._get_client_params_for_invoke(),
				)

				usage = self._get_usage(response)

				# Extract text from the first content block
				first_content = response.content[0]
				if isinstance(first_content, TextBlock):
					response_text = first_content.text
				else:
					# If it's not a text block, convert to string
					response_text = str(first_content)

				return ChatInvokeCompletion(
					completion=response_text,
					usage=usage,
				)

			else:
				# Use tool calling for structured output
				# Create a tool that represents the output format
				tool_name = output_format.__name__
				schema = output_format.model_json_schema()

				# Remove title from schema if present (Anthropic doesn't like it in parameters)
				if 'title' in schema:
					del schema['title']

				tool = ToolParam(
					name=tool_name,
					description=f'Extract information in the format of {tool_name}',
					input_schema=schema,
					cache_control=CacheControlEphemeralParam(type='ephemeral'),
				)

				# Force the model to use this tool
				tool_choice = ToolChoiceToolParam(type='tool', name=tool_name)

				response = await self.get_client().messages.create(
					model=self.model,
					messages=anthropic_messages,
					tools=[tool],
					system=system_prompt or NOT_GIVEN,
					tool_choice=tool_choice,
					**self._get_client_params_for_invoke(),
				)

				usage = self._get_usage(response)

				# Extract the tool use block
				for content_block in response.content:
					if hasattr(content_block, 'type') and content_block.type == 'tool_use':
						# Parse the tool input as the structured output
						try:
							return ChatInvokeCompletion(completion=output_format.model_validate(content_block.input), usage=usage)
						except Exception as e:
							# If validation fails, try to parse it as JSON first
							if isinstance(content_block.input, str):
								data = json.loads(content_block.input)
								return ChatInvokeCompletion(
									completion=output_format.model_validate(data),
									usage=usage,
								)
							raise e

				# If no tool use block found, raise an error
				raise ValueError('Expected tool use in response but none found')

		except APIConnectionError as e:
			raise ModelProviderError(message=e.message, model=self.name) from e
		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e
		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
