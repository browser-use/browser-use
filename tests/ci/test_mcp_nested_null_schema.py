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
