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
