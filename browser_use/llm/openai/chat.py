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
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

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
	include_action_descriptions: bool = False  # Add action descriptions to system prompt for weaker models
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

	def _generate_action_descriptions(self, schema: dict[str, Any]) -> str:
		"""Generate JSON-style action descriptions from AgentOutput schema."""
		if '$defs' not in schema:
			return ''

		descriptions = []

		for def_name, def_schema in schema['$defs'].items():
			if not def_name.endswith('ActionModel') or 'properties' not in def_schema:
				continue

			for action_name, action_schema in def_schema['properties'].items():
				action_desc = action_schema.get('description', '').rstrip('.')
				params_obj = self._get_action_params(action_schema, schema['$defs'])

				# Format: {"action_name": {params}} - description
				if params_obj:
					action_text = f'{{"{action_name}": {params_obj}}}'
				else:
					action_text = f'{{"{action_name}": {{}}}}'

				if action_desc:
					action_text += f' - {action_desc}'

				descriptions.append(action_text)

		return '\n'.join(descriptions)

	def _get_action_params(self, action_schema: dict[str, Any], defs: dict[str, Any]) -> str:
		"""Get JSON representation of action parameters."""
		param_ref = None

		if '$ref' in action_schema:
			param_ref = action_schema['$ref'].split('/')[-1]
		elif 'anyOf' in action_schema:
			for variant in action_schema['anyOf']:
				if '$ref' in variant:
					param_ref = variant['$ref'].split('/')[-1]
					break

		if not param_ref or param_ref not in defs:
			return ''

		param_schema = defs[param_ref]
		if 'properties' not in param_schema:
			return ''

		required_fields = set(param_schema.get('required', []))
		params = []

		for param_name, param_info in param_schema['properties'].items():
			# Handle nested object references
			if '$ref' in param_info:
				nested_ref = param_info['$ref'].split('/')[-1]
				if nested_ref in defs:
					nested_type = self._expand_schema_type(defs[nested_ref], defs)
					params.append(f'"{param_name}": {nested_type}')
					continue

			param_type = self._get_property_type(param_info, defs)
			constraints = self._get_constraints(param_info)
			default_value = param_info.get('default')
			is_optional = param_name not in required_fields

			# Build type string with constraints
			type_str = param_type
			if constraints:
				type_str += f' [{constraints}]'

			# Add optional marker and default
			if is_optional:
				if default_value is not None:
					default_str = self._format_default(default_value)
					type_str += f' (optional, default: {default_str})'
				else:
					type_str += ' (optional)'

			# Add description if present
			desc = param_info.get('description', '')
			if desc:
				type_str += f' // {desc}'

			params.append(f'"{param_name}": {type_str}')

		return '{' + ', '.join(params) + '}'

	def _expand_schema_type(self, schema: dict[str, Any], defs: dict[str, Any]) -> str:
		"""Expand a schema type to show structure in JSON syntax."""
		if 'type' not in schema:
			return 'any'

		schema_type = schema['type']

		if schema_type == 'object' and 'properties' in schema:
			fields = []
			required_fields = set(schema.get('required', []))
			for prop_name, prop_info in schema['properties'].items():
				prop_type = self._get_property_type(prop_info, defs)
				if prop_name in required_fields:
					fields.append(f'"{prop_name}": {prop_type}')
				else:
					fields.append(f'"{prop_name}": {prop_type} (optional)')
			return '{' + ', '.join(fields) + '}'

		elif schema_type == 'array' and 'items' in schema:
			item_type = self._get_property_type(schema['items'], defs)
			return f'[{item_type}]'

		return schema_type

	def _get_property_type(self, prop_info: dict[str, Any], defs: dict[str, Any]) -> str:
		"""Get the type of a property."""
		if '$ref' in prop_info:
			ref_name = prop_info['$ref'].split('/')[-1]
			if ref_name in defs:
				return self._expand_schema_type(defs[ref_name], defs)
			return 'object'

		if 'type' in prop_info:
			prop_type = prop_info['type']
			if prop_type == 'array' and 'items' in prop_info:
				item_type = self._get_property_type(prop_info['items'], defs)
				return f'[{item_type}]'
			if prop_type == 'object':
				if 'properties' in prop_info:
					return self._expand_schema_type(prop_info, defs)
				if 'additionalProperties' in prop_info:
					additional = prop_info['additionalProperties']
					if isinstance(additional, dict):
						value_type = self._get_property_type(additional, defs)
						return f'dict[string, {value_type}]'
					return 'dict[string, any]'
				return 'object'
			if prop_type == 'string' and 'enum' in prop_info:
				vals = prop_info['enum']
				if len(vals) <= 4:
					return ' | '.join(f'"{v}"' for v in vals)
				return f'string (enum: {len(vals)} options)'
			return prop_type

		if 'enum' in prop_info:
			vals = prop_info['enum']
			if len(vals) <= 4:
				return ' | '.join(f'"{v}"' for v in vals)
			return f'string (enum: {len(vals)} options)'

		if 'anyOf' in prop_info:
			for option in prop_info['anyOf']:
				if option.get('type') and option['type'] != 'null':
					return self._get_property_type(option, defs)

		return 'any'

	def _get_constraints(self, param_info: dict[str, Any]) -> str:
		"""Extract constraints from parameter info."""
		constraints = []
		if 'minimum' in param_info:
			constraints.append(f'≥{param_info["minimum"]}')
		elif 'ge' in param_info:
			constraints.append(f'≥{param_info["ge"]}')
		if 'exclusiveMinimum' in param_info:
			constraints.append(f'>{param_info["exclusiveMinimum"]}')
		elif 'gt' in param_info:
			constraints.append(f'>{param_info["gt"]}')
		if 'maximum' in param_info:
			constraints.append(f'≤{param_info["maximum"]}')
		elif 'le' in param_info:
			constraints.append(f'≤{param_info["le"]}')
		if 'exclusiveMaximum' in param_info:
			constraints.append(f'<{param_info["exclusiveMaximum"]}')
		elif 'lt' in param_info:
			constraints.append(f'<{param_info["lt"]}')
		if 'minLength' in param_info:
			constraints.append(f'len≥{param_info["minLength"]}')
		elif 'min_length' in param_info:
			constraints.append(f'len≥{param_info["min_length"]}')
		if 'maxLength' in param_info:
			constraints.append(f'len≤{param_info["maxLength"]}')
		elif 'max_length' in param_info:
			constraints.append(f'len≤{param_info["max_length"]}')
		return ', '.join(constraints)

	def _format_default(self, value: Any) -> str:
		"""Format a default value for display."""
		if isinstance(value, str):
			return f'"{value}"'
		if isinstance(value, bool):
			return str(value).lower()
		return str(value)

	def _get_usage(self, response: ChatCompletion) -> ChatInvokeUsage | None:
		if response.usage is not None:
			completion_tokens = response.usage.completion_tokens
			completion_token_details = response.usage.completion_tokens_details
			if completion_token_details is not None:
				reasoning_tokens = completion_token_details.reasoning_tokens
				if reasoning_tokens is not None:
					completion_tokens += reasoning_tokens

			usage = ChatInvokeUsage(
				prompt_tokens=response.usage.prompt_tokens,
				prompt_cached_tokens=response.usage.prompt_tokens_details.cached_tokens
				if response.usage.prompt_tokens_details is not None
				else None,
				prompt_cache_creation_tokens=None,
				prompt_image_tokens=None,
				# Completion
				completion_tokens=completion_tokens,
				total_tokens=response.usage.total_tokens,
			)
		else:
			usage = None

		return usage

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

	@overload
	async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

	async def ainvoke(
		self, messages: list[BaseMessage], output_format: type[T] | None = None
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

				usage = self._get_usage(response)
				return ChatInvokeCompletion(
					completion=response.choices[0].message.content or '',
					usage=usage,
					stop_reason=response.choices[0].finish_reason if response.choices else None,
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

				# Add action descriptions to system prompt for weaker models
				if self.include_action_descriptions and openai_messages and openai_messages[0]['role'] == 'system':
					# Use original schema with $defs to generate descriptions
					original_schema = output_format.model_json_schema()
					action_descriptions = self._generate_action_descriptions(original_schema)
					if action_descriptions:
						desc_text = f'\n\n<available_actions>\nThe `action` field is a list. Each element is an object with one action name as key and parameters dict as value.\n\n{action_descriptions}\n</available_actions>'
						if isinstance(openai_messages[0]['content'], str):
							openai_messages[0]['content'] += desc_text
						elif isinstance(openai_messages[0]['content'], Iterable):
							openai_messages[0]['content'] = list(openai_messages[0]['content']) + [
								ChatCompletionContentPartTextParam(text=desc_text, type='text')
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

				if response.choices[0].message.content is None:
					raise ModelProviderError(
						message='Failed to parse structured output from model response',
						status_code=500,
						model=self.name,
					)

				usage = self._get_usage(response)

				parsed = output_format.model_validate_json(response.choices[0].message.content)

				return ChatInvokeCompletion(
					completion=parsed,
					usage=usage,
					stop_reason=response.choices[0].finish_reason if response.choices else None,
				)

		except RateLimitError as e:
			raise ModelRateLimitError(message=e.message, model=self.name) from e

		except APIConnectionError as e:
			raise ModelProviderError(message=str(e), model=self.name) from e

		except APIStatusError as e:
			raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e

		except Exception as e:
			raise ModelProviderError(message=str(e), model=self.name) from e
