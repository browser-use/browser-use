import logging
from dataclasses import dataclass
from typing import Any, Literal, TypeVar, overload

from groq import (
	APIError,
	APIResponseValidationError,
	APIStatusError,
	AsyncGroq,
	NotGiven,
	RateLimitError,
	Timeout,
)
from groq.types.chat import ChatCompletion, ChatCompletionToolChoiceOptionParam, ChatCompletionToolParam
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
	'meta-llama/llama-4-maverick-17b-128e-instruct',
	'meta-llama/llama-4-scout-17b-16e-instruct',
	'qwen/qwen3-32b',
	'moonshotai/kimi-k2-instruct',
	'openai/gpt-oss-20b',
	'openai/gpt-oss-120b',
]

JsonSchemaModels = [
	'meta-llama/llama-4-maverick-17b-128e-instruct',
	'meta-llama/llama-4-scout-17b-16e-instruct',
	'openai/gpt-oss-20b',
	'openai/gpt-oss-120b',
]

ToolCallingModels = [
	'moonshotai/kimi-k2-instruct',
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
	top_p: float | None = None
	seed: int | None = None
	include_action_descriptions: bool = True  # Add action descriptions to system prompt for weaker models

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
				return await self._invoke_regular_completion(groq_messages)
			else:
				return await self._invoke_structured_output(groq_messages, output_format)

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

	async def _invoke_regular_completion(self, groq_messages) -> ChatInvokeCompletion[str]:
		"""Handle regular completion without structured output."""
		chat_completion = await self.get_client().chat.completions.create(
			messages=groq_messages,
			model=self.model,
			service_tier=self.service_tier,
			temperature=self.temperature,
			top_p=self.top_p,
			seed=self.seed,
		)
		usage = self._get_usage(chat_completion)
		return ChatInvokeCompletion(
			completion=chat_completion.choices[0].message.content or '',
			usage=usage,
		)

	async def _invoke_structured_output(self, groq_messages, output_format: type[T]) -> ChatInvokeCompletion[T]:
		"""Handle structured output using either tool calling or JSON schema."""
		schema = SchemaOptimizer.create_optimized_json_schema(output_format)

		# Add action descriptions to system prompt for weaker models
		if self.include_action_descriptions and groq_messages and groq_messages[0].get('role') == 'system':
			original_schema = output_format.model_json_schema()
			action_descriptions = self._generate_action_descriptions(original_schema)
			if action_descriptions:
				desc_text = f'\n\n<available_actions>\nThe `action` field is a list. Each element is an object with one action name as key and parameters dict as value.\n\n{action_descriptions}\n</available_actions>'
				groq_messages[0]['content'] += desc_text

		if self.model in ToolCallingModels:
			response = await self._invoke_with_tool_calling(groq_messages, output_format, schema)
		else:
			response = await self._invoke_with_json_schema(groq_messages, output_format, schema)

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

	async def _invoke_with_tool_calling(self, groq_messages, output_format: type[T], schema) -> ChatCompletion:
		"""Handle structured output using tool calling."""
		tool = ChatCompletionToolParam(
			function={
				'name': output_format.__name__,
				'description': f'Extract information in the format of {output_format.__name__}',
				'parameters': schema,
			},
			type='function',
		)
		tool_choice: ChatCompletionToolChoiceOptionParam = 'required'

		return await self.get_client().chat.completions.create(
			model=self.model,
			messages=groq_messages,
			temperature=self.temperature,
			top_p=self.top_p,
			seed=self.seed,
			tools=[tool],
			tool_choice=tool_choice,
			service_tier=self.service_tier,
		)

	async def _invoke_with_json_schema(self, groq_messages, output_format: type[T], schema) -> ChatCompletion:
		"""Handle structured output using JSON schema."""
		return await self.get_client().chat.completions.create(
			model=self.model,
			messages=groq_messages,
			temperature=self.temperature,
			top_p=self.top_p,
			seed=self.seed,
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
