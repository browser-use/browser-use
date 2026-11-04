"""Regression tests for preserving explicit nulls in nested MCP parameters."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import types

from browser_use.mcp.client import MCPClient
from browser_use.tools.registry.service import Registry


@pytest.mark.asyncio
async def test_nested_nullable_fields_and_array_items_are_preserved():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='save_payload',
		description='Save a payload',
		input_schema={
			'type': 'object',
			'properties': {
				'payload': {
					'type': 'object',
					'properties': {
						'note': {'type': 'string', 'nullable': True},
						'values': {
							'type': 'array',
							'items': {'type': 'string', 'nullable': True},
						},
					},
					'required': ['note', 'values'],
				},
				'label': {'type': 'string', 'default': 'fallback'},
			},
			'required': ['payload'],
		},
	)
	client._register_tool_as_action(registry, 'save_payload', tool)

	result = await registry.execute_action(
		'save_payload',
		{'payload': {'note': None, 'values': ['first', None]}},
	)

	assert result.error is None
	client.session.call_tool.assert_awaited_once_with(
		'save_payload',
		{'payload': {'note': None, 'values': ['first', None]}, 'label': 'fallback'},
	)


@pytest.mark.asyncio
@pytest.mark.parametrize(
	('name', 'parameter_schema'),
	[
		(
			'nullable_object',
			{'type': 'object', 'nullable': True, 'properties': {'name': {'type': 'string'}}},
		),
		('nullable_array', {'type': 'array', 'nullable': True, 'items': {'type': 'string'}}),
		('nullable_enum', {'type': 'string', 'enum': ['ready', None]}),
		('nullable_type', {'type': 'null'}),
		('nullable_type_array', {'type': ['string', 'null']}),
		('nullable_any_of', {'anyOf': [{'type': 'string'}, {'type': 'null'}]}),
		('nullable_one_of', {'oneOf': [{'type': 'string'}, {'type': 'null'}]}),
	],
)
async def test_nullable_schema_forms_accept_and_transmit_null(name, parameter_schema):
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name=name,
		description='Accept a nullable value',
		input_schema={
			'type': 'object',
			'properties': {'value': parameter_schema},
			'required': ['value'],
		},
	)
	client._register_tool_as_action(registry, name, tool)

	result = await registry.execute_action(name, {'value': None})

	assert result.error is None
	client.session.call_tool.assert_awaited_once_with(name, {'value': None})


@pytest.mark.asyncio
async def test_composition_respects_sibling_type_and_object_constraints():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='validate_composition_siblings',
		description='Validate sibling JSON Schema constraints',
		input_schema={
			'type': 'object',
			'properties': {
				'text': {
					'type': 'string',
					'anyOf': [{'type': 'string'}, {'type': 'null'}],
				},
				'payload': {
					'type': 'object',
					'properties': {'name': {'type': 'string'}},
					'required': ['name'],
					'anyOf': [{'type': 'object'}],
				},
			},
			'required': ['text', 'payload'],
		},
	)
	client._register_tool_as_action(registry, 'validate_composition_siblings', tool)

	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action(
			'validate_composition_siblings',
			{'text': None, 'payload': {'name': 'member'}},
		)
	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action(
			'validate_composition_siblings',
			{'text': 'hello', 'payload': {}},
		)
	client.session.call_tool.assert_not_awaited()

	valid = await registry.execute_action(
		'validate_composition_siblings',
		{'text': 'hello', 'payload': {'name': 'member'}},
	)

	assert valid.error is None
	client.session.call_tool.assert_awaited_once_with(
		'validate_composition_siblings',
		{'text': 'hello', 'payload': {'name': 'member'}},
	)


@pytest.mark.asyncio
async def test_one_of_rejects_values_matching_multiple_alternatives():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='validate_one_of',
		description='Require exactly one matching alternative',
		input_schema={
			'type': 'object',
			'properties': {
				'value': {
					'oneOf': [
						{'type': 'string'},
						{'type': 'string', 'enum': ['duplicate']},
					]
				}
			},
			'required': ['value'],
		},
	)
	client._register_tool_as_action(registry, 'validate_one_of', tool)

	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action('validate_one_of', {'value': 'duplicate'})
	client.session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_of_object_intersections_and_boolean_alternatives():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='validate_all_of_and_boolean_schemas',
		description='Validate allOf object intersections and boolean alternatives',
		input_schema={
			'type': 'object',
			'properties': {
				'payload': {
					'allOf': [
						{
							'type': 'object',
							'properties': {'name': {'type': 'string'}},
							'required': ['name'],
						},
						{
							'type': 'object',
							'properties': {'age': {'type': 'integer', 'minimum': 18}},
							'required': ['age'],
						},
					]
				},
				'text': {'anyOf': [False, {'type': 'string'}]},
				'open': {'anyOf': [True, {'type': 'string'}]},
			},
			'required': ['payload', 'text', 'open'],
		},
	)
	client._register_tool_as_action(registry, 'validate_all_of_and_boolean_schemas', tool)

	action_schema = registry.create_action_model().model_json_schema()
	payload_schemas = [node for node in _walk_schema(action_schema) if {'name', 'age'}.issubset(node.get('properties', {}))]
	assert payload_schemas
	assert {'name', 'age'}.issubset(payload_schemas[0].get('required', []))

	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action(
			'validate_all_of_and_boolean_schemas',
			{'payload': {'name': 'member'}, 'text': 'ok', 'open': 42},
		)
	client.session.call_tool.assert_not_awaited()

	result = await registry.execute_action(
		'validate_all_of_and_boolean_schemas',
		{'payload': {'name': 'member', 'age': 18}, 'text': 'ok', 'open': 42},
	)

	assert result.error is None
	client.session.call_tool.assert_awaited_once_with(
		'validate_all_of_and_boolean_schemas',
		{'payload': {'name': 'member', 'age': 18}, 'text': 'ok', 'open': 42},
	)


def _walk_schema(value):
	if isinstance(value, dict):
		yield value
		for child in value.values():
			yield from _walk_schema(child)
	elif isinstance(value, list):
		for child in value:
			yield from _walk_schema(child)


@pytest.mark.asyncio
async def test_false_boolean_schema_alternative_rejects_values():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='reject_false_schema',
		description='Reject values for a false JSON Schema',
		input_schema={
			'type': 'object',
			'properties': {'value': {'anyOf': [False]}},
			'required': ['value'],
		},
	)
	client._register_tool_as_action(registry, 'reject_false_schema', tool)

	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action('reject_false_schema', {'value': 'not allowed'})
	client.session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
	('schema', 'invalid_value'),
	[
		({'type': 'string', 'minLength': 3}, 'ab'),
		({'type': 'string', 'pattern': '^[A-Z]+$'}, 'lower'),
		({'type': 'number', 'minimum': 5}, 4),
		({'type': 'number', 'multipleOf': 1}, 1_000_000_000.5),
		({'type': 'array', 'maxItems': 1, 'items': {'type': 'integer'}}, [1, 2]),
		({'type': 'array', 'uniqueItems': True}, ['same', 'same']),
	],
)
async def test_composition_validator_enforces_scalar_and_collection_constraints(schema, invalid_value):
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='validate_constrained_value',
		description='Validate constrained value',
		input_schema={
			'type': 'object',
			'properties': {'value': {'anyOf': [schema]}},
			'required': ['value'],
		},
	)
	client._register_tool_as_action(registry, 'validate_constrained_value', tool)

	with pytest.raises(RuntimeError, match='Invalid parameters'):
		await registry.execute_action('validate_constrained_value', {'value': invalid_value})
	client.session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_omitted_nullable_fields_stay_omitted_with_sensitive_data():
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	client.session = MagicMock()
	client.session.call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	registry = Registry()
	tool = types.Tool(
		name='save_optional',
		description='Save an optional value',
		input_schema={
			'type': 'object',
			'properties': {
				'value': {'type': 'string', 'nullable': True},
				'union_value': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
				'payload': {
					'type': 'object',
					'properties': {'note': {'type': 'string', 'nullable': True}},
				},
				'omitted': {'type': 'string', 'nullable': True},
				'credential': {'type': 'string', 'default': '<secret>api_key</secret>'},
			},
		},
	)
	client._register_tool_as_action(registry, 'save_optional', tool)

	result = await registry.execute_action(
		'save_optional',
		{'value': None, 'union_value': None, 'payload': {}},
		sensitive_data={'api_key': 'secret'},
	)

	assert result.error is None
	client.session.call_tool.assert_awaited_once_with(
		'save_optional',
		{'value': None, 'union_value': None, 'payload': {}, 'credential': 'secret'},
	)
