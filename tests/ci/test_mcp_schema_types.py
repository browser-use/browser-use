"""Unit tests for MCPClient JSON Schema type array support (#6278)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import types

from browser_use.mcp.client import MCPClient
from browser_use.tools.registry.service import Registry


def _make_connected_client() -> tuple[MCPClient, AsyncMock]:
	client = MCPClient(server_name='test-server', command='test-command')
	client._telemetry = MagicMock()
	client._connected = True
	call_tool = AsyncMock(
		return_value=types.CallToolResult(
			content=[types.TextContent(type='text', text='success')],
			is_error=False,
		)
	)
	session = MagicMock()
	session.call_tool = call_tool
	client.session = session
	return client, call_tool


@pytest.mark.asyncio
async def test_register_tool_with_nullable_string_type_array():
	"""Test registration and execution of a tool with {"type": ["string", "null"]}."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_str',
		description='Echo a nullable string',
		input_schema={
			'type': 'object',
			'properties': {
				'value': {'type': ['string', 'null']},
			},
			'required': ['value'],
		},
	)

	client._register_tool_as_action(registry, 'echo_str', tool)
	assert 'echo_str' in registry.registry.actions

	# Accepts valid string
	res_str = await registry.execute_action('echo_str', {'value': 'hello'})
	assert res_str.error is None
	assert res_str.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_str', {'value': 'hello'})

	# Accepts None and transmits explicit None for nullable field
	res_none = await registry.execute_action('echo_str', {'value': None})
	assert res_none.error is None
	assert res_none.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_str', {'value': None})


@pytest.mark.asyncio
async def test_register_tool_with_nullable_integer_type_array():
	"""Test registration and execution of a tool with {"type": ["integer", "null"]}."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_int',
		description='Echo a nullable integer',
		input_schema={
			'type': 'object',
			'properties': {
				'count': {'type': ['integer', 'null']},
			},
			'required': ['count'],
		},
	)

	client._register_tool_as_action(registry, 'echo_int', tool)
	assert 'echo_int' in registry.registry.actions

	# Accepts valid integer
	res_int = await registry.execute_action('echo_int', {'count': 42})
	assert res_int.error is None
	assert res_int.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_int', {'count': 42})

	# Accepts None and transmits explicit None
	res_none = await registry.execute_action('echo_int', {'count': None})
	assert res_none.error is None
	assert res_none.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_int', {'count': None})


@pytest.mark.asyncio
async def test_register_tool_with_multi_type_union_array():
	"""Test registration and execution of a tool with {"type": ["string", "number"]}."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_union',
		description='Echo string or number',
		input_schema={
			'type': 'object',
			'properties': {
				'val': {'type': ['string', 'number']},
			},
			'required': ['val'],
		},
	)

	client._register_tool_as_action(registry, 'echo_union', tool)
	assert 'echo_union' in registry.registry.actions

	# Accepts valid string
	res_str = await registry.execute_action('echo_union', {'val': 'example'})
	assert res_str.error is None
	assert res_str.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_union', {'val': 'example'})

	# Accepts valid number (float)
	res_float = await registry.execute_action('echo_union', {'val': 3.14})
	assert res_float.error is None
	assert res_float.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_union', {'val': 3.14})

	# Accepts valid integer (coerces to number)
	res_int = await registry.execute_action('echo_union', {'val': 100})
	assert res_int.error is None
	assert res_int.extracted_content == 'success'


@pytest.mark.asyncio
async def test_register_tool_with_multi_type_union_including_null():
	"""Test registration with multi-type union including null: ["string", "number", "null"]."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_multi_null',
		description='Echo string, number, or null',
		input_schema={
			'type': 'object',
			'properties': {
				'val': {'type': ['string', 'number', 'null']},
			},
			'required': ['val'],
		},
	)

	client._register_tool_as_action(registry, 'echo_multi_null', tool)
	assert 'echo_multi_null' in registry.registry.actions

	# Accepts string
	res_str = await registry.execute_action('echo_multi_null', {'val': 'hello'})
	assert res_str.error is None

	# Accepts float
	res_num = await registry.execute_action('echo_multi_null', {'val': 1.23})
	assert res_num.error is None

	# Accepts None
	res_none = await registry.execute_action('echo_multi_null', {'val': None})
	assert res_none.error is None
	call_tool.assert_awaited_with('echo_multi_null', {'val': None})


@pytest.mark.asyncio
async def test_register_tool_with_nullable_array_items():
	"""Test registration and execution of nullable array with item types: ["array", "null"]."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_tags',
		description='Echo tags list or null',
		input_schema={
			'type': 'object',
			'properties': {
				'tags': {
					'type': ['array', 'null'],
					'items': {'type': 'string'},
				},
			},
			'required': ['tags'],
		},
	)

	client._register_tool_as_action(registry, 'echo_tags', tool)
	assert 'echo_tags' in registry.registry.actions

	# Accepts list of strings
	res_list = await registry.execute_action('echo_tags', {'tags': ['tag1', 'tag2']})
	assert res_list.error is None
	assert res_list.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_tags', {'tags': ['tag1', 'tag2']})

	# Accepts None
	res_none = await registry.execute_action('echo_tags', {'tags': None})
	assert res_none.error is None
	assert res_none.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_tags', {'tags': None})


@pytest.mark.asyncio
async def test_register_tool_with_nullable_nested_object():
	"""Test registration and execution of nullable object with nested properties: ["object", "null"]."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_meta',
		description='Echo metadata object or null',
		input_schema={
			'type': 'object',
			'properties': {
				'metadata': {
					'type': ['object', 'null'],
					'properties': {
						'author': {'type': 'string'},
						'revision': {'type': 'integer'},
					},
					'required': ['author'],
				},
			},
			'required': ['metadata'],
		},
	)

	client._register_tool_as_action(registry, 'echo_meta', tool)
	assert 'echo_meta' in registry.registry.actions

	# Accepts nested dict
	res_obj = await registry.execute_action('echo_meta', {'metadata': {'author': 'alice', 'revision': 1}})
	assert res_obj.error is None
	assert res_obj.extracted_content == 'success'

	# Accepts None
	res_none = await registry.execute_action('echo_meta', {'metadata': None})
	assert res_none.error is None
	assert res_none.extracted_content == 'success'
	call_tool.assert_awaited_with('echo_meta', {'metadata': None})


@pytest.mark.asyncio
async def test_reversed_null_type_array():
	"""Test registration when 'null' is first: ["null", "string"]."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_rev',
		description='Echo reversed nullable string',
		input_schema={
			'type': 'object',
			'properties': {
				'note': {'type': ['null', 'string']},
			},
			'required': ['note'],
		},
	)

	client._register_tool_as_action(registry, 'echo_rev', tool)
	assert 'echo_rev' in registry.registry.actions

	res_str = await registry.execute_action('echo_rev', {'note': 'testing'})
	assert res_str.error is None

	res_none = await registry.execute_action('echo_rev', {'note': None})
	assert res_none.error is None
	call_tool.assert_awaited_with('echo_rev', {'note': None})


@pytest.mark.asyncio
async def test_register_tool_with_nullable_numeric_enum():
	"""Test registration and execution of nullable numeric enum schemas."""
	client, call_tool = _make_connected_client()
	registry = Registry()
	tool = types.Tool(
		name='echo_level',
		description='Echo numeric level or null',
		input_schema={
			'type': 'object',
			'properties': {
				'level': {'type': ['integer', 'null'], 'enum': [1, 2, None]},
			},
			'required': ['level'],
		},
	)

	client._register_tool_as_action(registry, 'echo_level', tool)
	assert 'echo_level' in registry.registry.actions

	res_num = await registry.execute_action('echo_level', {'level': 2})
	assert res_num.error is None
	call_tool.assert_awaited_with('echo_level', {'level': 2})

	res_none = await registry.execute_action('echo_level', {'level': None})
	assert res_none.error is None
	call_tool.assert_awaited_with('echo_level', {'level': None})
