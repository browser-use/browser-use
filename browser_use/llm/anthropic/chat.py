import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, get_args, overload

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

T = TypeVar('T', bound=BaseModel)

_MINIMAX_DELIMITER = ']<]minimax[>['
_INVOKE_RE = re.compile(
	r'<invoke\s+name=(?:"(?P<dq>[^"]+)"|\'(?P<sq>[^\']+)\'|(?P<bare>[^\s>]+))\s*>(?P<body>.*?)</invoke>',
	re.DOTALL | re.IGNORECASE,
)
_PARAM_RE = re.compile(
	r'<(?:parameter|arg)\s+name=(?:"(?P<dq>[^"]+)"|\'(?P<sq>[^\']+)\'|(?P<bare>[^\s>]+))\s*>(?P<value>.*?)</(?:parameter|arg)>',
	re.DOTALL | re.IGNORECASE,
)


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
	output_config: dict[str, Any] | None = None
	thinking: dict[str, Any] | None = None
	betas: list[str] | None = None
	fallbacks: list[dict[str, Any]] | None = None
	inference_geo: str | None = None

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

	def _is_adaptive_thinking_only_model(self) -> bool:
		model = self.name.lower()
		return 'claude-fable-5' in model or 'claude-mythos-5' in model

	def _requires_auto_tool_choice(self) -> bool:
		model = self.name.lower()
		if 'claude-fable-5' in model or 'claude-mythos-5' in model:
			return True
		if self.thinking is None:
			return False
		return self.thinking.get('type') != 'disabled'

	def _validate_thinking_config(self) -> None:
		if not self.thinking or not self._is_adaptive_thinking_only_model():
			return

		thinking_type = self.thinking.get('type')
		if thinking_type in {'enabled', 'disabled'} or 'budget_tokens' in self.thinking:
			raise ValueError(
				f'{self.model} only supports adaptive thinking. Omit thinking or use adaptive display options such as '
				'{"type": "adaptive", "display": "summarized"}.'
			)

	def _get_betas_for_invoke(self) -> list[str] | None:
		betas = self.betas

		if self.fallbacks is None:
			return betas

		betas = list(betas or [])
		if not any(beta.startswith('server-side-fallback-') for beta in betas):
			betas.append('server-side-fallback-2026-06-01')
		return betas

	def _get_extra_body_for_invoke(self) -> dict[str, Any] | None:
		extra_body: dict[str, Any] = {}

		if self.output_config is not None:
			extra_body['output_config'] = self.output_config

		if self.fallbacks is not None:
			extra_body['fallbacks'] = self.fallbacks

		if self.inference_geo is not None:
			extra_body['inference_geo'] = self.inference_geo

		return extra_body or None

	def _get_client_params_for_invoke(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary for invoke."""
		self._validate_thinking_config()

		client_params = {}

		if self.temperature is not None:
			client_params['temperature'] = self.temperature

		if self.max_tokens is not None:
			client_params['max_tokens'] = self.max_tokens

		if self.top_p is not None:
			client_params['top_p'] = self.top_p

		if self.seed is not None:
			client_params['seed'] = self.seed

		if self.thinking is not None:
			client_params['thinking'] = self.thinking

		betas = self._get_betas_for_invoke()
		if betas is not None:
			client_params['betas'] = betas

		extra_body = self._get_extra_body_for_invoke()
		if extra_body is not None:
			client_params['extra_body'] = extra_body

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

	async def _create_message(self, **params: Any) -> Any:
		betas = params.pop('betas', None)
		client = self.get_client()
		if betas is not None:
			return await client.beta.messages.create(**params, betas=betas)
		return await client.messages.create(**params)

	def _is_message_like_response(self, response: Any) -> bool:
		return all(hasattr(response, attr) for attr in ('content', 'usage', 'stop_reason'))

	def _get_cache_creation_tokens(self, response: Any) -> tuple[int | None, int | None]:
		cache_creation = getattr(response.usage, 'cache_creation', None)
		if cache_creation is None:
			return None, None
		return (
			getattr(cache_creation, 'ephemeral_5m_input_tokens', None),
			getattr(cache_creation, 'ephemeral_1h_input_tokens', None),
		)

	def _get_pricing_multiplier(self) -> float | None:
		if self.inference_geo == 'us':
			return 1.1
		return None

	def _get_usage(self, response: Any) -> ChatInvokeUsage | None:
		cache_creation_5m_tokens, cache_creation_1h_tokens = self._get_cache_creation_tokens(response)
		usage = ChatInvokeUsage(
			prompt_tokens=response.usage.input_tokens
			+ (
				response.usage.cache_read_input_tokens or 0
			),  # Total tokens in Anthropic are a bit fucked, you have to add cached tokens to the prompt tokens
			completion_tokens=response.usage.output_tokens,
			total_tokens=response.usage.input_tokens + response.usage.output_tokens,
			prompt_cached_tokens=response.usage.cache_read_input_tokens,
			prompt_cache_creation_tokens=response.usage.cache_creation_input_tokens,
			prompt_cache_creation_5m_tokens=cache_creation_5m_tokens,
			prompt_cache_creation_1h_tokens=cache_creation_1h_tokens,
			prompt_image_tokens=None,
			pricing_multiplier=self._get_pricing_multiplier(),
		)
		return usage

	def _get_stop_details(self, response: Any) -> dict[str, Any] | None:
		stop_details = getattr(response, 'stop_details', None)
		if stop_details is None:
			return None
		if hasattr(stop_details, 'model_dump'):
			return stop_details.model_dump()
		if isinstance(stop_details, dict):
			return stop_details
		return {key: getattr(stop_details, key) for key in ('type', 'category', 'explanation') if hasattr(stop_details, key)}

	def _extract_content_blocks(self, response: Any) -> tuple[str, str | None, str | None]:
		text_parts: list[str] = []
		thinking_parts: list[str] = []
		redacted_thinking_parts: list[str] = []

		for content_block in response.content:
			block_type = getattr(content_block, 'type', None)
			if isinstance(content_block, TextBlock) or block_type == 'text':
				text = getattr(content_block, 'text', None)
				if text:
					text_parts.append(text)
			elif block_type == 'thinking':
				thinking_text = getattr(content_block, 'thinking', None)
				if thinking_text:
					thinking_parts.append(thinking_text)
			elif block_type == 'redacted_thinking':
				redacted_text = getattr(content_block, 'data', None) or getattr(content_block, 'redacted_thinking', None)
				if redacted_text:
					redacted_thinking_parts.append(str(redacted_text))

		if text_parts:
			completion = ''.join(text_parts)
		elif response.content:
			completion = str(response.content[0])
		else:
			completion = ''

		thinking = '\n'.join(thinking_parts) if thinking_parts else None
		redacted_thinking = '\n'.join(redacted_thinking_parts) if redacted_thinking_parts else None
		return completion, thinking, redacted_thinking

	def _json_candidates_from_text(self, text: str) -> list[str]:
		candidates: list[str] = []
		stripped = text.strip()
		if stripped:
			candidates.append(stripped)

		if stripped.startswith('```') and stripped.endswith('```'):
			lines = stripped.splitlines()
			if len(lines) >= 3:
				candidates.append('\n'.join(lines[1:-1]).strip())

		for start_char, end_char in (('{', '}'), ('[', ']')):
			start = stripped.find(start_char)
			end = stripped.rfind(end_char)
			if start != -1 and end > start:
				candidates.append(stripped[start : end + 1])

		return list(dict.fromkeys(candidate for candidate in candidates if candidate))

	def _json_values_from_text(self, text: str) -> list[Any]:
		values: list[Any] = []
		for candidate in self._json_candidates_from_text(text):
			try:
				values.append(json.loads(candidate))
			except json.JSONDecodeError:
				continue
		return values

	def _coerce_tool_input(self, tool_input: Any) -> Any:
		if isinstance(tool_input, str):
			return json.loads(tool_input)

		if not isinstance(tool_input, dict):
			return tool_input

		coerced = dict(tool_input)
		for key, value in coerced.items():
			if isinstance(value, str) and value.startswith(('[', '{')):
				try:
					coerced[key] = json.loads(value)
				except json.JSONDecodeError:
					cleaned = value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
					try:
						coerced[key] = json.loads(cleaned)
					except json.JSONDecodeError:
						pass

		return coerced

	def _action_fields_for_output_format(self, output_format: type[T]) -> list[str]:
		action_field = output_format.model_fields.get('action')
		if action_field is None:
			return []

		action_args = get_args(action_field.annotation)
		if not action_args:
			return []

		action_type = action_args[0]
		action_model_fields = getattr(action_type, 'model_fields', {})
		root_field = action_model_fields.get('root')
		if root_field is not None:
			action_types = get_args(root_field.annotation)
		else:
			action_types = (action_type,)

		action_fields: list[str] = []
		for action_model in action_types:
			for field_name in getattr(action_model, 'model_fields', {}):
				if field_name != 'root':
					action_fields.append(field_name)

		return list(dict.fromkeys(action_fields))

	def _completion_from_flat_action_input(self, data: dict[str, Any], output_format: type[T]) -> T | None:
		action_names = self._action_fields_for_output_format(output_format)
		if not action_names:
			return None

		model_field_names = set(output_format.model_fields)
		state = {key: value for key, value in data.items() if key in model_field_names and key != 'action'}
		extra = {key: value for key, value in data.items() if key not in model_field_names}

		if 'action' in data and data['action'] not in ([{}], []):
			return None

		for action_name in action_names:
			if action_name in data:
				try:
					return output_format.model_validate({**state, 'action': [{action_name: data[action_name]}]})
				except Exception:
					pass

		if not extra:
			return None

		for action_name in action_names:
			try:
				return output_format.model_validate({**state, 'action': [{action_name: extra}]})
			except Exception:
				continue

		return None

	def _parse_minimax_value(self, value: str) -> Any:
		value = html.unescape(value.strip())
		for parsed in self._json_values_from_text(value):
			return parsed
		return value

	def _minimax_params_from_body(self, body: str) -> dict[str, Any]:
		params: dict[str, Any] = {}
		for match in _PARAM_RE.finditer(body):
			name = match.group('dq') or match.group('sq') or match.group('bare')
			params[name] = self._parse_minimax_value(match.group('value'))

		if params:
			return params

		for parsed in self._json_values_from_text(body):
			if isinstance(parsed, dict):
				return parsed

		return params

	def _minimax_state_fields_from_text(self, text: str, output_format: type[T]) -> dict[str, Any]:
		state: dict[str, Any] = {}
		for field_name in ('thinking', 'evaluation_previous_goal', 'memory', 'next_goal', 'current_plan_item', 'plan_update'):
			if field_name not in output_format.model_fields:
				continue
			match = re.search(rf'<{field_name}>\s*(.*?)\s*</{field_name}>', text, re.DOTALL | re.IGNORECASE)
			if match:
				state[field_name] = self._parse_minimax_value(match.group(1))
		return state

	def _completion_from_named_action(self, action_name: str, action_input: Any, output_format: type[T], text: str) -> T | None:
		state = self._minimax_state_fields_from_text(text, output_format)
		try:
			return output_format.model_validate({**state, 'action': [{action_name: action_input}]})
		except Exception:
			return None

	def _completion_from_minimax_text_response(
		self, response: Any, output_format: type[T], usage: ChatInvokeUsage | None
	) -> ChatInvokeCompletion[T] | None:
		response_text, thinking, redacted_thinking = self._extract_content_blocks(response)
		cleaned_text = response_text.replace(_MINIMAX_DELIMITER, '')

		for parsed in self._json_values_from_text(cleaned_text):
			if isinstance(parsed, dict):
				tool_name = parsed.get('name') or parsed.get('tool_name')
				tool_input = parsed.get('arguments') or parsed.get('input')
				if tool_name and isinstance(tool_input, dict):
					completion = self._completion_from_named_action(str(tool_name), tool_input, output_format, cleaned_text)
					if completion is not None:
						return ChatInvokeCompletion(
							completion=completion,
							thinking=thinking,
							redacted_thinking=redacted_thinking,
							usage=usage,
							stop_reason=response.stop_reason,
							stop_details=self._get_stop_details(response),
						)

		for match in _INVOKE_RE.finditer(cleaned_text):
			name = match.group('dq') or match.group('sq') or match.group('bare')
			params = self._minimax_params_from_body(match.group('body'))

			if name != output_format.__name__:
				completion = self._completion_from_named_action(name, params, output_format, cleaned_text)
				if completion is not None:
					return ChatInvokeCompletion(
						completion=completion,
						thinking=thinking,
						redacted_thinking=redacted_thinking,
						usage=usage,
						stop_reason=response.stop_reason,
						stop_details=self._get_stop_details(response),
					)

			try:
				return ChatInvokeCompletion(
					completion=output_format.model_validate(params),
					thinking=thinking,
					redacted_thinking=redacted_thinking,
					usage=usage,
					stop_reason=response.stop_reason,
					stop_details=self._get_stop_details(response),
				)
			except Exception:
				continue

		return None

	def _completion_from_text_response(
		self, response: Any, output_format: type[T], usage: ChatInvokeUsage | None
	) -> ChatInvokeCompletion[T] | None:
		response_text, thinking, redacted_thinking = self._extract_content_blocks(response)
		for candidate in self._json_candidates_from_text(response_text):
			try:
				completion = output_format.model_validate_json(candidate)
			except Exception:
				try:
					completion = output_format.model_validate(json.loads(candidate))
				except Exception:
					continue
			return ChatInvokeCompletion(
				completion=completion,
				thinking=thinking,
				redacted_thinking=redacted_thinking,
				usage=usage,
				stop_reason=response.stop_reason,
				stop_details=self._get_stop_details(response),
			)
		return None

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
				response = await self._create_message(
					model=self.model,
					messages=anthropic_messages,
					system=system_prompt or omit,
					**self._get_client_params_for_invoke(),
				)

				# Ensure we have a valid Message object before accessing attributes
				if not isinstance(response, Message) and not self._is_message_like_response(response):
					raise ModelProviderError(
						message=f'Unexpected response type from Anthropic API: {type(response).__name__}. Response: {str(response)[:200]}',
						status_code=502,
						model=self.name,
					)

				usage = self._get_usage(response)

				response_text, thinking, redacted_thinking = self._extract_content_blocks(response)

				return ChatInvokeCompletion(
					completion=response_text,
					thinking=thinking,
					redacted_thinking=redacted_thinking,
					usage=usage,
					stop_reason=response.stop_reason,
					stop_details=self._get_stop_details(response),
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

				if self._requires_auto_tool_choice():
					tool_choice = {'type': 'auto'}
				else:
					# Force the model to use this tool
					tool_choice = ToolChoiceToolParam(type='tool', name=tool_name)

				response = await self._create_message(
					model=self.model,
					messages=anthropic_messages,
					tools=[tool],
					system=system_prompt or omit,
					tool_choice=tool_choice,
					**self._get_client_params_for_invoke(),
				)

				# Ensure we have a valid Message object before accessing attributes
				if not isinstance(response, Message) and not self._is_message_like_response(response):
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
								stop_details=self._get_stop_details(response),
							)
						except Exception as e:
							# If validation fails, try to fix common model output issues
							_input = self._coerce_tool_input(content_block.input)
							try:
								completion = output_format.model_validate(_input)
							except Exception:
								if not isinstance(_input, dict):
									raise e
								completion = self._completion_from_flat_action_input(_input, output_format)
								if completion is None:
									raise e

							return ChatInvokeCompletion(
								completion=completion,
								usage=usage,
								stop_reason=response.stop_reason,
								stop_details=self._get_stop_details(response),
							)

				text_completion = self._completion_from_text_response(response, output_format, usage)
				if text_completion is not None:
					return text_completion

				minimax_text_completion = self._completion_from_minimax_text_response(response, output_format, usage)
				if minimax_text_completion is not None:
					return minimax_text_completion

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
