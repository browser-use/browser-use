import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types

from browser_use.mcp.client import MCPClient
from browser_use.mcp.controller import MCPToolWrapper, register_mcp_tools
from browser_use.tools.registry.service import Registry


@pytest.fixture
def echo_tool() -> types.Tool:
	return types.Tool(
		name='echo',
		description='Echo a message',
		inputSchema={
			'type': 'object',
			'properties': {'message': {'type': 'string'}},
			'required': ['message'],
		},
	)


@pytest.fixture
def connected_mcp_client(monkeypatch: pytest.MonkeyPatch, echo_tool: types.Tool) -> AsyncMock:
	session = AsyncMock()
	session.call_tool.return_value = SimpleNamespace(content=[types.TextContent(type='text', text='hello')])

	async def connect(client: MCPClient) -> None:
		client.session = session
		client._tools = {echo_tool.name: echo_tool}
		client._connected = True

	monkeypatch.setattr(MCPClient, 'connect', connect)
	return session


async def test_legacy_wrapper_registers_typed_actions_without_blocking(
	connected_mcp_client: AsyncMock,
) -> None:
	registry = Registry()

	with pytest.warns(DeprecationWarning, match='MCPToolWrapper is deprecated'):
		wrapper = MCPToolWrapper(registry, 'test-mcp-server')

	await wrapper.connect()

	action = registry.registry.actions['echo']
	assert set(action.param_model.model_fields) == {'message'}

	result = await registry.execute_action('echo', {'message': 'hello'})
	assert result.extracted_content == 'hello'
	connected_mcp_client.call_tool.assert_awaited_once_with('echo', {'message': 'hello'})


async def test_register_mcp_tools_returns_connected_wrapper(
	connected_mcp_client: AsyncMock,
) -> None:
	registry = Registry()

	with pytest.warns(DeprecationWarning, match='MCPToolWrapper is deprecated'):
		wrapper = await asyncio.wait_for(register_mcp_tools(registry, 'test-mcp-server'), timeout=1)

	assert isinstance(wrapper, MCPToolWrapper)
	assert wrapper._connected is True
	assert 'echo' in registry.registry.actions
