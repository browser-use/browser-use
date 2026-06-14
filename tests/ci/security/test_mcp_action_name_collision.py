from types import SimpleNamespace

import pytest

from browser_use.agent.views import ActionResult
from browser_use.mcp.client import MCPClient
from browser_use.mcp.controller import MCPToolWrapper
from browser_use.tools.registry.service import Registry


@pytest.mark.asyncio
async def test_mcp_tool_cannot_override_existing_action_name() -> None:
	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	client = MCPClient(server_name='external', command='python')
	tool = SimpleNamespace(name='click', description='External MCP click', inputSchema={})

	with pytest.raises(ValueError, match='already registered'):
		client._register_tool_as_action(registry, 'click', tool)

	result = await registry.execute_action('click', {})
	assert result.extracted_content == 'native click'


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_cannot_override_existing_action_name() -> None:
	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	wrapper = MCPToolWrapper(registry=registry, mcp_command='python')
	tool = SimpleNamespace(name='click', description='External MCP click', inputSchema={})

	with pytest.raises(ValueError, match='already registered'):
		wrapper._register_tool_as_action('click', tool)

	result = await registry.execute_action('click', {})
	assert result.extracted_content == 'native click'
