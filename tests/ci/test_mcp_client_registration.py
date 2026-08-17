"""Regression tests for MCPClient tool registration.

Two bugs are pinned here:

1. `_json_schema_to_python_type` returned `str` for any schema containing `enum`,
   so integer/number enums (e.g. {"type": "integer", "enum": [1, 2, 3]}) produced
   a `str` param field — the model rejected an int and the LLM was told to send a
   string, making such MCP tools effectively uncallable.

2. `register_to_tools` deduplicated against a client-global `_registered_actions`
   set, so registering the same connected client to a second `Tools` instance
   skipped every tool and registered nothing (while still logging success).
"""

from mcp.types import Tool as MCPTool

from browser_use.mcp.client import MCPClient
from browser_use.tools.service import Tools


def _make_client(tools: dict[str, MCPTool]) -> MCPClient:
	"""A connected-looking MCPClient backed by real Tool objects (no live server)."""
	client = MCPClient.__new__(MCPClient)
	client.server_name = 'test-server'
	client._connected = True
	client._registered_actions = set()
	client._tools = tools
	return client


async def test_integer_enum_param_keeps_int_type():
	client = _make_client(
		{
			'pick': MCPTool(
				name='pick',
				description='pick a number',
				inputSchema={
					'type': 'object',
					'properties': {'count': {'type': 'integer', 'enum': [1, 2, 3]}},
					'required': ['count'],
				},
			)
		}
	)
	tools = Tools()
	await client.register_to_tools(tools)

	param_model = tools.registry.registry.actions['pick'].param_model
	assert param_model is not None
	# An integer must be accepted (previously raised ValidationError because the
	# field was typed as str).
	assert param_model(count=2).model_dump() == {'count': 2}


async def test_register_to_two_tools_instances():
	client = _make_client(
		{
			'foo': MCPTool(
				name='foo',
				description='foo tool',
				inputSchema={'type': 'object', 'properties': {'x': {'type': 'string'}}},
			)
		}
	)
	tools_a = Tools()
	tools_b = Tools()

	await client.register_to_tools(tools_a)
	await client.register_to_tools(tools_b)

	assert 'foo' in tools_a.registry.registry.actions
	# Previously this registry got nothing because the client-global dedup set
	# already contained 'foo' from the first call.
	assert 'foo' in tools_b.registry.registry.actions


async def test_re_register_same_tools_is_idempotent():
	client = _make_client(
		{
			'foo': MCPTool(
				name='foo',
				description='foo tool',
				inputSchema={'type': 'object', 'properties': {'x': {'type': 'string'}}},
			)
		}
	)
	tools = Tools()
	await client.register_to_tools(tools)
	# Registering the same client to the same registry again must not raise
	# (per-registry dedup skips the already-present action).
	await client.register_to_tools(tools)
	assert 'foo' in tools.registry.registry.actions
