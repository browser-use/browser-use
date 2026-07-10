from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionContentPartTextParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.responses import Response
from openai.types.shared.chat_model import ChatModel
from openai.types.shared_params.reasoning_effort import ReasoningEffort
from openai.types.shared_params.response_format_json_schema import JSONSchema, ResponseFormatJSONSchema
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel, ToolChoice, ToolDefinition
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage, Function, ToolCall
from browser_use.llm.openai.responses_serializer import ResponsesAPIMessageSerializer
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage, ModelCapabilities

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatOpenAI(BaseChatModel):
	"""
	A wrapper around AsyncOpenAI that implements the BaseLLM protocol.

	This class accepts all AsyncOpenAI parameters while adding model
	and temperature parameters for the LLM interface (if temperature it not `None`).
	"""

	# Model configuration
	model: ChatModel | str

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
	use_responses_api_for_tools: bool | Literal['auto'] = 'auto'

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

	# Static
	@property
	def provider(self) -> str:
		return 'openai'

	@property
	def model_capabilities(self) -> ModelCapabilities:
		return ModelCapabilities(
			native_tool_calling=True,
			forced_tool_calling=not self.dont_force_structured_output,
			strict_tool_arguments=True,
			parallel_tool_call_control=True,
		)

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
		client_params = self._get_client_params()
		return AsyncOpenAI(**client_params)

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

	def _get_responses_usage(self, response: Response) -> ChatInvokeUsage | None:
		if response.usage is None:
			return None
		cached_tokens = (
			response.usage.input_tokens_details.cached_tokens if response.usage.input_tokens_details is not None else None
		)
		return ChatInvokeUsage(
			prompt_tokens=response.usage.input_tokens,
			prompt_cached_tokens=cached_tokens,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=response.usage.output_tokens,
			total_tokens=response.usage.total_tokens,
		)

	def _uses_reasoning_controls(self) -> bool:
		if self.reasoning_models is None:
			return False
		model_name = str(self.model).lower()
		return any(model_name.startswith(str(candidate).lower()) for candidate in self.reasoning_models)

	def _should_use_responses_for_tools(self) -> bool:
		if isinstance(self.use_responses_api_for_tools, bool):
			return self.use_responses_api_for_tools
		# OpenAI-compatible providers frequently expose only Chat Completions.
		return type(self) is ChatOpenAI and self._uses_reasoning_controls()

	async def _invoke_tools_with_responses(
		self,
		messages: list[BaseMessage],
		tools: list[ToolDefinition],
		tool_choice: ToolChoice | None,
	) -> ChatInvokeCompletion[str]:
		input_messages = ResponsesAPIMessageSerializer.serialize_messages(messages)
		model_params: dict[str, Any] = {
			'model': self.model,
			'input': input_messages,
			'tools': [
				{
					'type': 'function',
					'name': tool.name,
					'description': tool.description,
					'parameters': tool.parameters,
					'strict': tool.strict,
				}
				for tool in tools
			],
			'parallel_tool_calls': False,
			'store': False,
		}
		if self.max_completion_tokens is not None:
			model_params['max_output_tokens'] = self.max_completion_tokens
		if self.service_tier is not None:
			model_params['service_tier'] = self.service_tier
		if self._uses_reasoning_controls():
			model_params['reasoning'] = {'effort': self.reasoning_effort}
		else:
			if self.temperature is not None:
				model_params['temperature'] = self.temperature
			if self.top_p is not None:
				model_params['top_p'] = self.top_p

		if tool_choice in {None, 'auto', 'required', 'none'}:
			openai_tool_choice: Any = tool_choice
		else:
			openai_tool_choice = {'type': 'function', 'name': tool_choice}
		if openai_tool_choice is not None:
			model_params['tool_choice'] = openai_tool_choice

		response = await self.get_client().responses.create(**model_params)
		if response.error is not None:
			raise ModelProviderError(message=response.error.message, model=self.name)
		if response.incomplete_details is not None and response.incomplete_details.reason == 'max_output_tokens':
			raise ModelOutputTruncatedError(
				message=f'Model output was truncated at max_output_tokens={self.max_completion_tokens}.',
				model=self.name,
			)
		tool_calls = [
			ToolCall(
				id=item.call_id,
				function=Function(name=item.name, arguments=item.arguments),
			)
			for item in response.output
			if getattr(item, 'type', None) == 'function_call'
		]
		return ChatInvokeCompletion(
			completion=response.output_text or '',
			tool_calls=tool_calls,
			response_id=response.id,
			usage=self._get_responses_usage(response),
			stop_reason='tool_calls' if tool_calls else response.status,
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
		Invoke the model with the given messages.

		Args:
			messages: List of chat messages
			output_format: Optional Pydantic model class for structured output

		Returns:
			Either a string response or an instance of output_format
		"""

		openai_messages = OpenAIMessageSerializer.serialize_messages(messages)
		tools: list[ToolDefinition] | None = kwargs.pop('tools', None)
		tool_choice: ToolChoice | None = kwargs.pop('tool_choice', None)
		if tools and output_format is not None:
			raise ValueError('Use either output_format or tools, not both.')

		try:
			if tools and self._should_use_responses_for_tools():
				return await self._invoke_tools_with_responses(messages, tools, tool_choice)

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

			if tools:
				serialized_tools = [
					{
						'type': 'function',
						'function': {
							'name': tool.name,
							'description': tool.description,
							'parameters': tool.parameters,
							'strict': tool.strict,
						},
					}
					for tool in tools
				]
				if tool_choice in {None, 'auto', 'required', 'none'}:
					openai_tool_choice: Any = tool_choice
				else:
					openai_tool_choice = {'type': 'function', 'function': {'name': tool_choice}}

				response = await self.get_client().chat.completions.create(
					model=self.model,
					messages=openai_messages,
					tools=serialized_tools,  # type: ignore[arg-type]
					tool_choice=openai_tool_choice,
					parallel_tool_calls=False,
					**model_params,
				)
				choice = response.choices[0] if response.choices else None
				if choice is None:
					raise ModelProviderError(
						message='Invalid OpenAI tool response: missing choices.',
						status_code=502,
						model=self.name,
					)
				if choice.finish_reason == 'length':
					raise ModelOutputTruncatedError(
						message='Model output was truncated before tool arguments completed.',
						model=self.name,
					)
				tool_calls = [
					ToolCall(
						id=item.id,
						function=Function(name=item.function.name, arguments=item.function.arguments),
					)
					for item in (choice.message.tool_calls or [])
				]
				return ChatInvokeCompletion(
					completion=choice.message.content or '',
					tool_calls=tool_calls,
					response_id=response.id,
					usage=self._get_usage(response),
					stop_reason='tool_calls' if tool_calls else choice.finish_reason,
				)

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
