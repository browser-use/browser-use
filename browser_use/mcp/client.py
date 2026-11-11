"""Connect to MCP servers and expose their tools as browser-use actions."""

from __future__ import annotations

import asyncio
import json
import keyword
import logging
import math
import re
from contextlib import AsyncExitStack
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Union

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, create_model, model_validator

from browser_use.tools import ActionResult, Tools

logger = logging.getLogger(__name__)


def _json_values_equal(left: Any, right: Any) -> bool:
	"""Compare JSON values without treating booleans as numbers."""
	if isinstance(left, bool) or isinstance(right, bool):
		return isinstance(left, bool) and isinstance(right, bool) and left is right
	if isinstance(left, (int, float)) and isinstance(right, (int, float)):
		return left == right
	if left is None or right is None:
		return left is None and right is None
	if isinstance(left, str) or isinstance(right, str):
		return isinstance(left, str) and isinstance(right, str) and left == right
	if isinstance(left, list) or isinstance(right, list):
		return (
			isinstance(left, list)
			and isinstance(right, list)
			and len(left) == len(right)
			and all(_json_values_equal(a, b) for a, b in zip(left, right))
		)
	if isinstance(left, dict) or isinstance(right, dict):
		return (
			isinstance(left, dict)
			and isinstance(right, dict)
			and left.keys() == right.keys()
			and all(_json_values_equal(left[key], right[key]) for key in left)
		)
	return type(left) is type(right) and left == right


def _schema_accepts_value(value: Any, schema: dict[str, Any] | bool) -> bool:
	if isinstance(schema, bool):
		return schema

	json_type = schema.get('type')
	if json_type is not None:
		json_types = json_type if isinstance(json_type, list) else [json_type]
		type_matches = any(
			(type_name == 'null' and value is None)
			or (value is None and schema.get('nullable', False))
			or (type_name == 'string' and isinstance(value, str))
			or (type_name == 'boolean' and isinstance(value, bool))
			or (type_name == 'integer' and isinstance(value, int) and not isinstance(value, bool))
			or (type_name == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool))
			or (type_name == 'array' and isinstance(value, list))
			or (type_name == 'object' and isinstance(value, dict))
			for type_name in json_types
		)
		enum_allows_null = (
			value is None and 'enum' in schema and any(_json_values_equal(value, enum_value) for enum_value in schema['enum'])
		)
		if not type_matches and not enum_allows_null:
			return False

	if 'enum' in schema and not any(_json_values_equal(value, enum_value) for enum_value in schema['enum']):
		return False
	if 'const' in schema and not _json_values_equal(value, schema['const']):
		return False
	if 'anyOf' in schema and not any(_schema_accepts_value(value, variant) for variant in schema['anyOf']):
		return False
	if 'oneOf' in schema and sum(_schema_accepts_value(value, variant) for variant in schema['oneOf']) != 1:
		return False
	if 'allOf' in schema and not all(_schema_accepts_value(value, variant) for variant in schema['allOf']):
		return False

	if isinstance(value, str):
		if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', math.inf):
			return False
		if 'pattern' in schema and re.search(schema['pattern'], value) is None:
			return False

	if isinstance(value, (int, float)) and not isinstance(value, bool):
		if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
			return False
		if value <= schema.get('exclusiveMinimum', -math.inf) or value >= schema.get('exclusiveMaximum', math.inf):
			return False
		if 'multipleOf' in schema and not _is_multiple_of(value, schema['multipleOf']):
			return False

	if isinstance(value, dict):
		if len(value) < schema.get('minProperties', 0) or len(value) > schema.get('maxProperties', math.inf):
			return False
		if not set(schema.get('required', [])).issubset(value):
			return False
		properties = schema.get('properties', {})
		if any(key in value and not _schema_accepts_value(value[key], child) for key, child in properties.items()):
			return False
		extra_properties = set(value) - set(properties)
		additional_properties = schema.get('additionalProperties', True)
		if additional_properties is False and extra_properties:
			return False
		if isinstance(additional_properties, (dict, bool)) and any(
			not _schema_accepts_value(value[key], additional_properties) for key in extra_properties
		):
			return False

	if isinstance(value, list):
		if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', math.inf):
			return False
		if schema.get('uniqueItems', False) and any(
			_json_values_equal(value[left], value[right]) for left in range(len(value)) for right in range(left + 1, len(value))
		):
			return False
		prefix_items = schema.get('prefixItems', [])
		if any(
			index < len(value) and not _schema_accepts_value(value[index], item_schema)
			for index, item_schema in enumerate(prefix_items)
		):
			return False
		items_schema = schema.get('items')
		if isinstance(items_schema, (dict, bool)) and any(
			not _schema_accepts_value(item, items_schema) for index, item in enumerate(value) if index >= len(prefix_items)
		):
			return False
		if 'contains' in schema:
			match_count = sum(_schema_accepts_value(item, schema['contains']) for item in value)
			if match_count < schema.get('minContains', 1) or match_count > schema.get('maxContains', math.inf):
				return False

	return True


def _schema_allows_null(schema: dict[str, Any] | bool) -> bool:
	return _schema_accepts_value(None, schema)


def _is_multiple_of(value: int | float, multiple: int | float) -> bool:
	"""Check JSON-number divisibility using their decimal representations."""
	value_decimal = Decimal(str(value))
	multiple_decimal = Decimal(str(multiple))
	if not value_decimal.is_finite() or not multiple_decimal.is_finite() or multiple_decimal <= 0:
		return False

	def coefficient_and_exponent(number: Decimal) -> tuple[int, int]:
		sign, digits, exponent = number.as_tuple()
		assert isinstance(exponent, int)
		coefficient = int(''.join(str(digit) for digit in digits) or '0')
		return (-coefficient if sign else coefficient), exponent

	value_coefficient, value_exponent = coefficient_and_exponent(value_decimal)
	multiple_coefficient, multiple_exponent = coefficient_and_exponent(multiple_decimal)
	common_exponent = min(value_exponent, multiple_exponent)
	scaled_value = value_coefficient * 10 ** (value_exponent - common_exponent)
	scaled_multiple = multiple_coefficient * 10 ** (multiple_exponent - common_exponent)
	return scaled_value % scaled_multiple == 0


def _schema_for_composed_object(schema: dict[str, Any]) -> dict[str, Any]:
	"""Expose intersected allOf fields at the top level for action schemas."""
	json_schema = dict(schema)
	properties = dict(json_schema.get('properties', {}))
	required = set(json_schema.get('required', []))

	for branch in schema.get('allOf', []):
		if not isinstance(branch, dict):
			continue
		for name, property_schema in branch.get('properties', {}).items():
			if name in properties and properties[name] != property_schema:
				existing_schema = properties[name]
				existing_branches = (
					existing_schema.get('allOf')
					if isinstance(existing_schema, dict) and set(existing_schema) == {'allOf'}
					else None
				)
				properties[name] = {'allOf': [*(existing_branches or [existing_schema]), property_schema]}
			else:
				properties[name] = property_schema
		required.update(branch.get('required', []))

	if properties:
		json_schema['type'] = 'object'
		json_schema['properties'] = properties
	if required:
		json_schema['required'] = sorted(required)
	return json_schema


def _with_input_schema(python_type: Any, schema: dict[str, Any] | bool) -> Any:
	if isinstance(schema, bool):
		return python_type
	json_schema = _normalize_schema_for_action(schema)
	if 'allOf' in json_schema:
		json_schema = _schema_for_composed_object(json_schema)
	return Annotated[python_type, WithJsonSchema(json_schema)]


def _normalize_schema_for_action(schema: dict[str, Any]) -> dict[str, Any]:
	"""Translate JSON Schema type arrays to unions accepted by model tool providers."""
	result = dict(schema)
	for key in ('properties', 'patternProperties'):
		if isinstance(result.get(key), dict):
			result[key] = {name: _normalize_schema_for_action(child) for name, child in result[key].items()}
	for key in ('items', 'additionalProperties', 'contains', 'propertyNames', 'not', 'if', 'then', 'else'):
		if isinstance(result.get(key), dict):
			result[key] = _normalize_schema_for_action(result[key])
	for key in ('prefixItems', 'allOf', 'anyOf', 'oneOf'):
		if isinstance(result.get(key), list):
			result[key] = [_normalize_schema_for_action(child) if isinstance(child, dict) else child for child in result[key]]

	json_type = result.get('type')
	if isinstance(json_type, list):
		if not json_type:
			raise ValueError('JSON Schema type arrays must contain at least one type')
		if len(json_type) == 1:
			result['type'] = json_type[0]
		else:
			siblings = {key: value for key, value in result.items() if key != 'type'}
			alternatives = {'anyOf': [{'type': type_name} for type_name in json_type]}
			if any(key in siblings for key in ('allOf', 'anyOf', 'oneOf')):
				return {'allOf': [alternatives, siblings]}
			return {**siblings, **alternatives}
	return result


def _resolve_schema_references(
	schema: dict[str, Any] | bool,
	root_schema: dict[str, Any],
	resolving: frozenset[str] = frozenset(),
) -> dict[str, Any] | bool:
	if isinstance(schema, bool):
		return schema

	if '$ref' in schema:
		reference = schema['$ref']
		if not isinstance(reference, str) or not reference.startswith('#/'):
			raise ValueError(f'Unsupported external JSON Schema reference: {reference!r}')
		if reference in resolving:
			raise ValueError(f'Recursive JSON Schema reference is not supported: {reference}')

		target: Any = root_schema
		for part in reference[2:].split('/'):
			part = part.replace('~1', '/').replace('~0', '~')
			if not isinstance(target, dict) or part not in target:
				raise ValueError(f'Unresolved JSON Schema reference: {reference}')
			target = target[part]
		if not isinstance(target, (dict, bool)):
			raise ValueError(f'Invalid JSON Schema reference target: {reference}')
		siblings = {key: value for key, value in schema.items() if key != '$ref'}
		return _resolve_schema_references(
			{**target, **siblings} if isinstance(target, dict) else target,
			root_schema,
			resolving | {reference},
		)

	result = dict(schema)
	for key in ('properties', 'patternProperties'):
		if isinstance(result.get(key), dict):
			result[key] = {name: _resolve_schema_references(child, root_schema, resolving) for name, child in result[key].items()}
	for key in ('items', 'additionalProperties', 'contains', 'propertyNames', 'not', 'if', 'then', 'else'):
		child = result.get(key)
		if isinstance(child, (dict, bool)):
			result[key] = _resolve_schema_references(child, root_schema, resolving)
	for key in ('prefixItems', 'allOf', 'anyOf', 'oneOf'):
		children = result.get(key)
		if isinstance(children, list):
			result[key] = [_resolve_schema_references(child, root_schema, resolving) for child in children]
	return result


def _nullable_python_type(python_type: Any) -> Any:
	return python_type if python_type is type(None) else python_type | None


def _python_type_for_json_value(value: Any) -> Any:
	if value is None:
		return type(None)
	if isinstance(value, bool):
		return bool
	if isinstance(value, str):
		return str
	if isinstance(value, int):
		return int
	if isinstance(value, float):
		return float
	if isinstance(value, list):
		return list
	if isinstance(value, dict):
		return dict
	return Any


def _serialize_mcp_params(value: Any) -> Any:
	"""Serialize MCP parameters without dropping explicit nullable values."""
	if isinstance(value, BaseModel):
		serialized = value.model_dump(exclude_none=True, by_alias=True)
		nullable_fields = getattr(value.__class__, '__mcp_nullable_fields__', frozenset())

		for field_name, field_info in value.__class__.model_fields.items():
			alias = field_info.alias or field_name
			field_value = getattr(value, field_name)
			if field_value is None:
				if alias in nullable_fields and field_name in value.model_fields_set:
					serialized[alias] = None
			elif alias in serialized:
				serialized[alias] = _serialize_mcp_params(field_value)

		return serialized
	if isinstance(value, dict):
		return {key: _serialize_mcp_params(item) for key, item in value.items()}
	if isinstance(value, list):
		return [_serialize_mcp_params(item) for item in value]
	return value


class MCPToolParameters(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)

	__mcp_nullable_fields__: ClassVar[frozenset[str]] = frozenset()
	__mcp_schema__: ClassVar[dict[str, Any] | bool | None] = None

	@model_validator(mode='before')
	@classmethod
	def _validate_json_schema(cls, value: Any) -> Any:
		schema = cls.__mcp_schema__
		if schema is not None and not _schema_accepts_value(value, schema):
			raise ValueError('Parameters do not satisfy the MCP tool JSON Schema')
		return value


class MCPClient:
	"""Connect to an MCP server over stdio and register its tools as browser-use actions.

	Use it as an async context manager so the subprocess is closed after the agent run:

		client = MCPClient('filesystem', 'npx', ['-y', '@modelcontextprotocol/server-filesystem', '.'])
		async with client:
			await client.register_to_tools(tools)
			await Agent('...', tools=tools).run()
	"""

	def __init__(
		self,
		server_name: str,
		command: str,
		args: list[str] | None = None,
		env: dict[str, str] | None = None,
		cwd: str | None = None,
	):
		self.server_name = server_name
		self.command = command
		self.args = args or []
		self.env = env
		self.cwd = cwd
		self.session: ClientSession | None = None
		self._exit_stack: AsyncExitStack | None = None
		self._tools: dict[str, types.Tool] = {}
		self._registered_actions: set[str] = set()
		self._connection_lock = asyncio.Lock()

	async def connect(self) -> None:
		"""Start the MCP server over stdio and discover its tools."""
		async with self._connection_lock:
			if self.session is not None:
				return

			stack = AsyncExitStack()
			await stack.__aenter__()
			try:
				server_params = StdioServerParameters(
					command=self.command,
					args=self.args,
					env=self.env,
					cwd=self.cwd,
				)
				read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
				session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
				await session.initialize()
				response = await session.list_tools()
			except BaseException:
				await stack.aclose()
				raise

			self._exit_stack = stack
			self.session = session
			self._tools = {tool.name: tool for tool in response.tools}
			logger.info("Connected to MCP server '%s' with %d tools", self.server_name, len(self._tools))

	async def disconnect(self) -> None:
		"""Close the MCP session and its stdio subprocess."""
		async with self._connection_lock:
			stack, self._exit_stack = self._exit_stack, None
			if stack is None:
				return
			try:
				await stack.aclose()
			finally:
				self.session = None
				self._tools.clear()
				self._registered_actions.clear()

	async def register_to_tools(
		self,
		tools: Tools,
		tool_filter: list[str] | None = None,
		prefix: str | None = None,
	) -> None:
		"""Register discovered MCP tools as actions in a browser-use Tools collection."""
		if self.session is None:
			await self.connect()

		for tool_name, tool in self._tools.items():
			if tool_filter is not None and tool_name not in tool_filter:
				continue
			action_name = f'{prefix}{tool_name}' if prefix else tool_name
			if action_name in self._registered_actions:
				continue
			self._register_tool_as_action(tools, action_name, tool)
			self._registered_actions.add(action_name)

	def _register_tool_as_action(self, tools: Tools, action_name: str, tool: types.Tool) -> None:
		param_model = self._create_parameters_model(action_name, tool)

		if param_model is None:

			async def wrapper_without_params() -> ActionResult:
				return await self._call_tool(tool.name, {})

			mcp_action_wrapper = wrapper_without_params
		else:

			async def wrapper_with_params(params: Any) -> ActionResult:
				return await self._call_tool(tool.name, _serialize_mcp_params(params))

			mcp_action_wrapper = wrapper_with_params
		mcp_action_wrapper.__name__ = action_name
		mcp_action_wrapper.__qualname__ = f'mcp.{self.server_name}.{action_name}'
		tools.action(
			description=tool.description or f'MCP tool from {self.server_name}: {tool.name}',
			param_model=param_model,
		)(mcp_action_wrapper)

	def _create_parameters_model(self, action_name: str, tool: types.Tool) -> type[MCPToolParameters] | None:
		root_schema = tool.input_schema
		schema = _resolve_schema_references(root_schema, root_schema)
		if isinstance(schema, bool):
			if schema:
				return None
			raise ValueError(f'MCP tool {tool.name!r} has a schema that rejects every input')
		properties = schema.get('properties', {})
		if not isinstance(properties, dict):
			raise ValueError(f'MCP tool {tool.name!r} input schema properties must be an object')
		if not properties:
			return None

		required = set(schema.get('required', []))
		fields: dict[str, Any] = {}
		nullable_fields: set[str] = set()
		for index, (property_name, property_schema) in enumerate(properties.items()):
			if not isinstance(property_schema, (dict, bool)):
				raise ValueError(f'MCP tool {tool.name!r} has an invalid schema for {property_name!r}')
			field_type = self._json_schema_to_python_type(property_schema, f'{action_name}_{property_name}')
			if _schema_allows_null(property_schema):
				nullable_fields.add(property_name)

			if property_name in required:
				default = ...
			else:
				field_type = _nullable_python_type(field_type)
				default = property_schema.get('default') if isinstance(property_schema, dict) else None
			description = property_schema.get('description') if isinstance(property_schema, dict) else None
			field_kwargs: dict[str, Any] = {'alias': property_name}
			if description is not None:
				field_kwargs['description'] = description
			field_type = _with_input_schema(field_type, property_schema)
			python_name = property_name
			if (
				not python_name.isidentifier()
				or keyword.iskeyword(python_name)
				or python_name in BaseModel.__dict__
				or python_name in fields
			):
				python_name = f'field_{index}'
			fields[python_name] = (field_type, Field(default, **field_kwargs))

		model_name = re.sub(r'\W', '_', f'{action_name}_Params')
		if not model_name or model_name[0].isdigit():
			model_name = f'MCP_{model_name}'
		param_model = create_model(model_name, __base__=MCPToolParameters, **fields)
		param_model.__mcp_nullable_fields__ = frozenset(nullable_fields)
		param_model.__mcp_schema__ = schema
		return param_model

	def _json_schema_to_python_type(self, schema: dict[str, Any] | bool, model_name: str = 'NestedModel') -> Any:
		if isinstance(schema, bool):
			return Any

		compositions = {composition: schema[composition] for composition in ('allOf', 'anyOf', 'oneOf') if composition in schema}
		if compositions:
			if any(not isinstance(variants, list) for variants in compositions.values()):
				raise ValueError('JSON Schema allOf, anyOf, and oneOf values must be lists')

			base_schema = {key: value for key, value in schema.items() if key not in compositions}
			if base_schema.get('type') == 'object':
				python_type = dict
			elif 'type' in base_schema:
				python_type = self._json_schema_to_python_type(base_schema, model_name)
			elif 'allOf' in compositions:
				variant_types = []
				for variant in compositions['allOf']:
					if isinstance(variant, bool):
						continue
					if not isinstance(variant, dict):
						raise ValueError('JSON Schema allOf entries must be objects or booleans')
					if variant.get('type') == 'object':
						variant_types.append(dict)
					elif 'type' in variant:
						variant_types.append(self._json_schema_to_python_type(variant, model_name))
				python_types = list(dict.fromkeys(variant_types))
				python_type = python_types[0] if len(python_types) == 1 else Any
			else:
				python_types = []
				for variants in compositions.values():
					for variant in variants:
						if isinstance(variant, bool):
							variant_type = Any
						elif isinstance(variant, dict):
							variant_type = self._json_schema_to_python_type(variant, model_name)
						else:
							raise ValueError('JSON Schema composition entries must be objects or booleans')
						if variant_type not in python_types:
							python_types.append(variant_type)
				if not python_types:
					raise ValueError('JSON Schema compositions must contain at least one schema')
				python_type = python_types[0] if len(python_types) == 1 else Union[tuple(python_types)]

			def validate_composition(value: Any) -> Any:
				if not _schema_accepts_value(value, schema):
					raise ValueError('Value does not satisfy its JSON Schema composition')
				return value

			if 'allOf' in compositions:
				return Annotated[
					python_type,
					BeforeValidator(validate_composition),
					WithJsonSchema(_schema_for_composed_object(schema)),
				]
			return Annotated[python_type, BeforeValidator(validate_composition)]

		if 'type' not in schema and ('enum' in schema or 'const' in schema):
			values = schema.get('enum', [schema['const']] if 'const' in schema else [])
			python_types = list(dict.fromkeys(_python_type_for_json_value(value) for value in values))
			if python_types:
				return python_types[0] if len(python_types) == 1 else Union[tuple(python_types)]

		json_type = schema.get('type', 'string')
		if isinstance(json_type, list):
			python_types = [
				self._json_schema_to_python_type({**schema, 'type': single_type}, model_name)
				for single_type in dict.fromkeys(json_type)
				if single_type != 'null'
			]
			if _schema_allows_null(schema):
				python_types.append(type(None))
			if not python_types:
				return type(None)
			return python_types[0] if len(python_types) == 1 else Union[tuple(python_types)]

		type_mapping = {
			'string': str,
			'number': float,
			'integer': int,
			'boolean': bool,
			'array': list,
			'object': dict,
			'null': type(None),
		}
		if json_type not in type_mapping:
			raise ValueError(f'Unsupported JSON Schema type: {json_type!r}')

		if json_type == 'object':
			properties = schema.get('properties', {})
			if properties:
				required_fields = set(schema.get('required', []))
				nested_fields: dict[str, Any] = {}
				nullable_fields: set[str] = set()
				for index, (property_name, property_schema) in enumerate(properties.items()):
					if not isinstance(property_schema, (dict, bool)):
						raise ValueError(f'Invalid JSON Schema for nested property {property_name!r}')
					property_type = self._json_schema_to_python_type(property_schema, f'{model_name}_{property_name}')
					if _schema_allows_null(property_schema):
						nullable_fields.add(property_name)
					if property_name in required_fields:
						default = ...
					else:
						property_type = _nullable_python_type(property_type)
						default = property_schema.get('default') if isinstance(property_schema, dict) else None
					field_kwargs: dict[str, Any] = {'alias': property_name}
					description = property_schema.get('description') if isinstance(property_schema, dict) else None
					if description is not None:
						field_kwargs['description'] = description
					property_type = _with_input_schema(property_type, property_schema)
					python_name = property_name
					if (
						not python_name.isidentifier()
						or keyword.iskeyword(python_name)
						or python_name in BaseModel.__dict__
						or python_name in nested_fields
					):
						python_name = f'field_{index}'
					nested_fields[python_name] = (property_type, Field(default, **field_kwargs))

				nested_name = re.sub(r'\W', '_', model_name)
				nested_model = create_model(nested_name, __base__=MCPToolParameters, **nested_fields)
				nested_model.__mcp_schema__ = schema
				nested_model.__mcp_nullable_fields__ = frozenset(nullable_fields)
				return _nullable_python_type(nested_model) if _schema_allows_null(schema) else nested_model
			return _nullable_python_type(dict) if _schema_allows_null(schema) else dict

		if json_type == 'array':
			array_type = (
				list[self._json_schema_to_python_type(schema['items'], f'{model_name}_item')] if 'items' in schema else list
			)
			return _nullable_python_type(array_type) if _schema_allows_null(schema) else array_type

		base_type = type_mapping[json_type]
		return _nullable_python_type(base_type) if _schema_allows_null(schema) else base_type

	async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ActionResult:
		if self.session is None:
			raise RuntimeError(f"MCP server '{self.server_name}' is not connected")
		result = await self.session.call_tool(tool_name, arguments)
		content = self._format_mcp_result(result)
		if result.is_error:
			return ActionResult(error=f"MCP tool '{tool_name}' reported an error: {content}")
		return ActionResult(extracted_content=content)

	def _format_mcp_result(self, result: types.CallToolResult) -> str:
		text_parts = [item.text for item in result.content if isinstance(item, types.TextContent)]
		if text_parts:
			return '\n'.join(text_parts)
		if result.structured_content is not None:
			return json.dumps(result.structured_content, ensure_ascii=False)
		return '\n'.join(str(item) for item in result.content)

	async def __aenter__(self) -> MCPClient:
		await self.connect()
		return self

	async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
		await self.disconnect()
