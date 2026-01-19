import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from anthropic import (
	APIConnectionError,
	APIStatusError,
	AsyncAnthropic,
	NotGiven,
	RateLimitError,
	omit,
)
from anthropic.types import CacheControlEphemeralParam, Message, ToolParam
from anthropic.types.model_param import ModelParam
from anthropic.types.text_block import TextBlock
from anthropic.types.tool_choice_tool_param import ToolChoiceToolParam
from httpx import Timeout
from pydantic import BaseModel

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAnthropic(BaseChatModel):
	"""
	A wrapper around Anthropic's chat model.
	"""

	# Model configuration
	model: str | ModelParam
	max_tokens: int = 8192
	temperature: float | None = None
	top_p: float | None = None
	seed: int | None = None

	# Client initialization parameters
	api_key: str | None = None
	auth_token: str | None = None
	base_url: str | httpx.URL | None = None
	timeout: float | Timeout | None | NotGiven = NotGiven()
	max_retries: int = 10
	default_headers: Mapping[str, str] | None = None
	default_query: Mapping[str, object] | None = None
	http_client: httpx.AsyncClient | None = None

	# Static
	@property
	def provider(self) -> str:
		return 'anthropic'

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary."""
		# Define base client params
		base_params = {
			'api_key': self.api_key,
			'auth_token': self.auth_token,
			'base_url': self.base_url,
			'timeout': self.timeout,
			'max_retries': self.max_retries,
			'default_headers': self.default_headers,
			'default_query': self.default_query,
			'http_client': self.http_client,
		}

		# Create client_params dict with non-None values and non-NotGiven values
		client_params = {}
		for k, v in base_params.items():
			if v is not None and v is not NotGiven():
				client_params[k] = v

		return client_params

	def _get_client_params_for_invoke(self):
		"""Prepare client parameters dictionary for invoke."""

		client_params = {}

		if self.temperature is not None:
			client_params['temperature'] = self.temperature

		if self.max_tokens is not None:
			client_params['max_tokens'] = self.max_tokens

		if self.top_p is not None:
			client_params['top_p'] = self.top_p

		if self.seed is not None:
			client_params['seed'] = self.seed

		return client_params

	def get_client(self) -> AsyncAnthropic:
		"""
		Returns an AsyncAnthropic client.

		Returns:
			AsyncAnthropic: An instance of the AsyncAnthropic client.
		"""
		client_params = self._get_client_params()
		return AsyncAnthropic(**client_params)

	@property
	def name(self) -> str:
		return str(self.model)

	def _log_cache_debug(self, system_prompt, anthropic_messages) -> None:
		"""Log debug info about cache_control markers in the request."""
		# Check system prompt for cache_control and log actual structure
		system_has_cache = False
		if isinstance(system_prompt, list) and len(system_prompt) > 0:
			first_block = system_prompt[0]
			# Log the actual keys present in the first block
			if isinstance(first_block, dict):
				block_keys = list(first_block.keys())
				logger.info(f'📦 [Anthropic Cache] First system block keys: {block_keys}')
				# Log truncated block content to see actual structure
				try:
					block_dict = dict(first_block)
					# Truncate text field for logging
					if 'text' in block_dict and len(str(block_dict.get('text', ''))) > 100:
						block_dict['text'] = str(block_dict['text'])[:100] + '...[truncated]'
					logger.info(f'📦 [Anthropic Cache] First system block structure: {block_dict}')
				except Exception as e:
					logger.info(f'📦 [Anthropic Cache] Could not serialize block: {e}')

				if first_block.get('cache_control'):
					system_has_cache = True
					logger.info(f'📦 [Anthropic Cache] cache_control value: {first_block.get("cache_control")}')
			else:
				logger.info(f'📦 [Anthropic Cache] First block is not a dict, type: {type(first_block).__name__}')

		# Check messages for cache_control
		messages_with_cache = 0
		total_messages = len(anthropic_messages) if anthropic_messages else 0
		for msg in anthropic_messages or []:
			content = msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', None)
			if isinstance(content, list):
				for block in content:
					if isinstance(block, dict) and block.get('cache_control'):
						messages_with_cache += 1
						break

		logger.info(
			f'📦 [Anthropic Cache] system_has_cache_control={system_has_cache}, '
			f'messages_with_cache={messages_with_cache}/{total_messages}, '
			f'system_prompt_type={type(system_prompt).__name__}'
		)

	def _log_cache_response(self, response: Message) -> None:
		"""Log the cache-related fields from Anthropic's response."""
		cache_creation = response.usage.cache_creation_input_tokens or 0
		cache_read = response.usage.cache_read_input_tokens or 0
		input_tokens = response.usage.input_tokens

		if cache_creation > 0:
			logger.info(f'📦 [Anthropic Cache] CACHE CREATED: {cache_creation} tokens written to cache')
		elif cache_read > 0:
			logger.info(f'📦 [Anthropic Cache] CACHE HIT: {cache_read} tokens read from cache')
		else:
			logger.info(f'📦 [Anthropic Cache] NO CACHING: input_tokens={input_tokens}, cache_creation=0, cache_read=0')

	def _get_usage(self, response: Message) -> ChatInvokeUsage | None:
		# Log cache response info
		self._log_cache_response(response)

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
	async def ainvoke(
		self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
	) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
	) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
		anthropic_messages, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)

		# Debug logging for cache_control verification
		self._log_cache_debug(system_prompt, anthropic_messages)

		try:
			if output_format is None:
				# Normal completion without structured output
				response = await self.get_client().messages.create(
					model=self.model,
					messages=anthropic_messages,
					system=system_prompt or omit,
					**self._get_client_params_for_invoke(),
				)

				# Ensure we have a valid Message object before accessing attributes
				if not isinstance(response, Message):
					raise ModelProviderError(
						message=f'Unexpected response type from Anthropic API: {type(response).__name__}. Response: {str(response)[:200]}',
						status_code=502,
						model=self.name,
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
					stop_reason=response.stop_reason,
				)

			else:
				# Use tool calling for structured output
				# Create a tool that represents the output format
				tool_name = output_format.__name__
				schema = SchemaOptimizer.create_optimized_json_schema(output_format)

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
					system=system_prompt or omit,
					tool_choice=tool_choice,
					**self._get_client_params_for_invoke(),
				)

				# Ensure we have a valid Message object before accessing attributes
				if not isinstance(response, Message):
					raise ModelProviderError(
						message=f'Unexpected response type from Anthropic API: {type(response).__name__}. Response: {str(response)[:200]}',
						status_code=502,
						model=self.name,
					)

				usage = self._get_usage(response)

				# Extract the tool use block
				for content_block in response.content:
					if hasattr(content_block, 'type') and content_block.type == 'tool_use':
						# Parse the tool input as the structured output
						try:
							return ChatInvokeCompletion(
								completion=output_format.model_validate(content_block.input),
								usage=usage,
								stop_reason=response.stop_reason,
							)
						except Exception as e:
							# If validation fails, try to parse it as JSON first
							if isinstance(content_block.input, str):
								data = json.loads(content_block.input)
								return ChatInvokeCompletion(
									completion=output_format.model_validate(data),
									usage=usage,
									stop_reason=response.stop_reason,
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
