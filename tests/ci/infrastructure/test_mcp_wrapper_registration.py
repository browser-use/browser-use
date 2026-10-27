"""MCP tool wrappers must register through the Registry's signature rules."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from browser_use.mcp.controller import MCPToolWrapper
from browser_use.tools.registry.service import Registry


def _tool(schema):
	return SimpleNamespace(description='test tool', input_schema=schema)


def _wrapper() -> tuple[Registry, MCPToolWrapper]:
	reg = Registry()
	return reg, MCPToolWrapper(registry=reg, mcp_command='npx')


def test_register_tool_with_parameters():
	"""The Registry rejects **kwargs action signatures, so the wrapper must be
	typed with the tool's param model. Registering any parameterful MCP tool
	used to raise ValueError immediately."""
	reg, wrapper = _wrapper()
	wrapper._register_tool_as_action(
		'echo_tool',
		_tool({'properties': {'msg': {'type': 'string'}}, 'required': ['msg']}),
	)
	assert 'echo_tool' in reg.registry.actions


def test_register_parameterless_tool():
	reg, wrapper = _wrapper()
	wrapper._register_tool_as_action('ping_tool', _tool({}))
	assert 'ping_tool' in reg.registry.actions


async def test_wrapper_forwards_validated_params_to_session():
	reg, wrapper = _wrapper()
	session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(content='pong')))
	wrapper.session = session
	wrapper._register_tool_as_action(
		'echo_tool',
		_tool({'properties': {'msg': {'type': 'string'}}, 'required': ['msg']}),
	)

	result = await reg.execute_action('echo_tool', {'msg': 'hi'})

	session.call_tool.assert_awaited_once_with('echo_tool', {'msg': 'hi'})
	assert result.extracted_content == 'pong'
