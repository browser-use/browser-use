import json
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
from browser_use.llm.messages import BaseMessage, Function, ToolCall
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatAnthropic(BaseChatModel):
	"""
	A wrapper around Anthropic's chat model.
	"""

	# Model configuration
	model: str | ModelParam
	supports_native_tool_calling: bool = True
	supports_parallel_tool_calls: bool = True
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

	def _get_usage(self, response: Message) -> ChatInvokeUsage | None:
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

	def _get_native_tool_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
		"""Convert OpenAI-compatible function tools into Anthropic tool params."""
		raw_tools = kwargs.get('tools')
		if not raw_tools:
			return {}

		tools: list[ToolParam] = []
		for raw_tool in raw_tools:
			if not isinstance(raw_tool, dict):
				continue
			function = raw_tool.get('function', raw_tool)
			if not isinstance(function, dict):
				continue
			name = function.get('name')
			if not name:
				continue
			input_schema = function.get('parameters') or {'type': 'object', 'properties': {}}
			if isinstance(input_schema, dict):
				input_schema = dict(input_schema)
				input_schema.pop('title', None)
			tools.append(
				ToolParam(
					name=str(name),
					description=str(function.get('description') or ''),
					input_schema=input_schema,
				)
			)

		if not tools:
			return {}

		native_params: dict[str, Any] = {'tools': tools}
		tool_choice = kwargs.get('tool_choice')
		if tool_choice == 'required':
			native_params['tool_choice'] = {'type': 'any'}
		elif tool_choice == 'auto':
			native_params['tool_choice'] = {'type': 'auto'}
		elif tool_choice == 'none':
			native_params['tool_choice'] = {'type': 'none'}
		elif isinstance(tool_choice, dict):
			function = tool_choice.get('function')
			name = function.get('name') if isinstance(function, dict) else None
			if tool_choice.get('type') == 'function' and name:
				native_params['tool_choice'] = ToolChoiceToolParam(type='tool', name=str(name))
			elif tool_choice.get('type') in {'auto', 'any', 'none'}:
				native_params['tool_choice'] = {'type': tool_choice['type']}

		return native_params

	def _get_tool_calls(self, response: Message) -> list[ToolCall]:
		tool_calls: list[ToolCall] = []
		for index, content_block in enumerate(response.content):
			if getattr(content_block, 'type', None) != 'tool_use':
				continue
			raw_input = getattr(content_block, 'input', {})
			if isinstance(raw_input, str):
				arguments = raw_input
			else:
				arguments = json.dumps(raw_input)
			tool_calls.append(
				ToolCall(
					id=str(getattr(content_block, 'id', None) or f'toolu_{index}'),
					function=Function(
						name=str(getattr(content_block, 'name', '')),
						arguments=arguments,
					),
					type='function',
				)
			)
		return tool_calls

	def _get_text_response(self, response: Message) -> str:
		text_parts: list[str] = []
		for content_block in response.content:
			if isinstance(content_block, TextBlock):
				text_parts.append(content_block.text)
		return '\n'.join(text_parts)

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

		try:
			if output_format is None:
				# Normal completion without structured output
				response = await self.get_client().messages.create(
					model=self.model,
					messages=anthropic_messages,
					system=system_prompt or omit,
					**self._get_native_tool_params(kwargs),
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

				return ChatInvokeCompletion(
					completion=self._get_text_response(response),
					usage=usage,
					stop_reason=response.stop_reason,
					tool_calls=self._get_tool_calls(response),
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
							# If validation fails, try to fix common model output issues
							_input = content_block.input
							if isinstance(_input, str):
								_input = json.loads(_input)
							elif isinstance(_input, dict):
								# Model sometimes double-serializes fields
								for key, value in _input.items():
									if isinstance(value, str) and value.startswith(('[', '{')):
										try:
											_input[key] = json.loads(value)
										except json.JSONDecodeError:
											cleaned = value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
											try:
												_input[key] = json.loads(cleaned)
											except json.JSONDecodeError:
												pass
							else:
								raise
							return ChatInvokeCompletion(
								completion=output_format.model_validate(_input),
								usage=usage,
								stop_reason=response.stop_reason,
							)

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
