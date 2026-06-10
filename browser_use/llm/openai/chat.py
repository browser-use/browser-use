from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, overload

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionContentPartTextParam
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.shared.chat_model import ChatModel
from openai.types.shared_params.reasoning_effort import ReasoningEffort
from openai.types.shared_params.response_format_json_schema import JSONSchema, ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar('T', bound=BaseModel)


def _extract_json_object(text: str) -> str | None:
	"""Best-effort local repair of near-JSON model output.

	Handles the two most common OpenAI-compatible gateway defects that don't require
	another model round-trip:
	  - markdown code fences (```json ... ```)
	  - leading/trailing prose around the JSON object ("trailing characters" decode errors)

	Returns the substring spanning the outermost balanced {...} object, or None if no
	plausible object is found. Brace counting is string-literal aware so braces inside
	JSON string values don't throw off the balance.
	"""
	if not text:
		return None
	s = text.strip()
	# Strip markdown fences
	if s.startswith('```'):
		s = s.split('\n', 1)[1] if '\n' in s else s
		if s.endswith('```'):
			s = s[: -3]
		s = s.strip()
		# Drop a leading "json" language tag if it survived
		if s[:4].lower() == 'json':
			s = s[4:].lstrip()

	start = s.find('{')
	if start == -1:
		return None

	depth = 0
	in_string = False
	escape = False
	for i in range(start, len(s)):
		ch = s[i]
		if in_string:
			if escape:
				escape = False
			elif ch == '\\':
				escape = True
			elif ch == '"':
				in_string = False
			continue
		if ch == '"':
			in_string = True
		elif ch == '{':
			depth += 1
		elif ch == '}':
			depth -= 1
			if depth == 0:
				candidate = s[start : i + 1]
				return candidate if candidate != text.strip() else candidate
	return None


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
	repair_structured_output: bool = True  # Retry once in plain JSON mode when OpenAI-compatible proxies return invalid schema output
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
			'gpt-5.4',
			'gpt-5.4-pro',
			'gpt-5-mini',
			'gpt-5-nano',
		]
	)

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

	async def _repair_structured_output(
		self,
		raw_content: str,
		output_format: type[T],
		response_format: JSONSchema,
		model_params: dict[str, Any],
		validation_error: Exception,
	) -> ChatInvokeCompletion[T]:
		"""Repair malformed structured output from OpenAI-compatible proxies.

		Some proxy endpoints accept `response_format=json_schema` but return JSON
		with wrong field names when schemas contain enum/anyOf/nested objects. A
		single plain-chat repair keeps strict Pydantic validation as the final gate.
		"""
		repair_messages: list[dict[str, Any]] = [
			{
				'role': 'system',
				'content': (
					'You repair malformed structured-output JSON. Return only one valid JSON object. '
					'Do not wrap it in markdown. The object must validate against the JSON schema exactly.'
				),
			},
			{
				'role': 'user',
				'content': (
					'JSON schema:\n'
					f'{response_format.get("schema", "")}\n\n'
					'Validation error:\n'
					f'{validation_error}\n\n'
					'Malformed model output:\n'
					f'{raw_content}\n\n'
					'Return the corrected JSON object only.'
				),
			},
		]
		response = await self.get_client().chat.completions.create(
			model=self.model,
			messages=repair_messages,  # type: ignore[arg-type]
			**model_params,
		)
		choice = response.choices[0] if response.choices else None
		if choice is None or choice.message.content is None:
			raise ModelProviderError(
				message='Failed to repair structured output from model response',
				status_code=500,
				model=self.name,
			)

		try:
			parsed = output_format.model_validate_json(choice.message.content)
		except (ValidationError, ValueError):
			# Last-resort local extraction if the repair model still wrapped/append-ed prose.
			local_fixed = _extract_json_object(choice.message.content or '')
			if local_fixed is None:
				raise
			parsed = output_format.model_validate_json(local_fixed)
		return ChatInvokeCompletion(
			completion=parsed,
			usage=self._get_usage(response),
			stop_reason=choice.finish_reason,
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

				if choice.message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)

				usage = self._get_usage(response)

				try:
					parsed = output_format.model_validate_json(choice.message.content)
				except (ValidationError, ValueError) as e:
					# 1) Cheap local repair first: strip code fences / trailing prose and
					#    re-extract the outermost JSON object. Avoids an extra LLM round-trip
					#    for the common "trailing characters" / fenced-output gateway defects.
					local_fixed = _extract_json_object(choice.message.content or '')
					if local_fixed is not None:
						try:
							parsed = output_format.model_validate_json(local_fixed)
							return ChatInvokeCompletion(
								completion=parsed,
								usage=usage,
								stop_reason=choice.finish_reason,
							)
						except (ValidationError, ValueError):
							pass
					# 2) Fall back to an LLM-based repair round if enabled.
					if self.repair_structured_output:
						return await self._repair_structured_output(
							raw_content=choice.message.content,
							output_format=output_format,
							response_format=response_format,
							model_params=model_params,
							validation_error=e,
						)
					raise

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
