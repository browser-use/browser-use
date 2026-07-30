from types import SimpleNamespace
from typing import Any

import pytest

from browser_use.agent.views import ActionResult
from browser_use.mcp.client import MCPClient
from browser_use.mcp.controller import MCPToolWrapper
from browser_use.tools.registry.service import Registry


def make_tool(name: str) -> Any:
	return SimpleNamespace(name=name, description=f'External MCP {name}', inputSchema={})


@pytest.mark.asyncio
async def test_mcp_tool_cannot_override_existing_action_name() -> None:
	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	client = MCPClient(server_name='external', command='python')

	with pytest.raises(ValueError, match='already registered'):
		client._register_tool_as_action(registry, 'click', make_tool('click'))

	result = await registry.execute_action('click', {})
	assert result.extracted_content == 'native click'


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_cannot_override_existing_action_name() -> None:
	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	wrapper = MCPToolWrapper(registry=registry, mcp_command='python')

	with pytest.raises(ValueError, match='already registered'):
		wrapper._register_tool_as_action('click', make_tool('click'))

	result = await registry.execute_action('click', {})
	assert result.extracted_content == 'native click'


def test_mcp_tool_wrapper_preflights_collisions_before_registering() -> None:
	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	wrapper = MCPToolWrapper(registry=registry, mcp_command='python')
	wrapper._tools = {'new_tool': make_tool('new_tool'), 'click': make_tool('click')}

	with pytest.raises(ValueError, match='already registered'):
		wrapper._register_discovered_tools()

	assert 'new_tool' not in registry.registry.actions
	assert wrapper._registered_actions == set()


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_restores_state_and_can_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
	from browser_use.mcp import controller as controller_module

	registry = Registry()

	@registry.action('Native click action')
	async def click() -> ActionResult:
		return ActionResult(extracted_content='native click')

	tool_sets = [[make_tool('new_tool'), make_tool('click')], [make_tool('new_tool')]]
	connection_count = 0

	class StdioContext:
		async def __aenter__(self) -> tuple[object, object]:
			return object(), object()

		async def __aexit__(self, *args: object) -> None:
			return None

	class FakeSession:
		def __init__(self, *args: object) -> None:
			pass

		async def __aenter__(self) -> 'FakeSession':
			return self

		async def __aexit__(self, *args: object) -> None:
			return None

		async def initialize(self) -> None:
			return None

		async def list_tools(self) -> SimpleNamespace:
			nonlocal connection_count
			tools = tool_sets[connection_count]
			connection_count += 1
			return SimpleNamespace(tools=tools)

	async def keep_session_alive() -> None:
		return None

	monkeypatch.setattr(controller_module, 'stdio_client', lambda params: StdioContext())
	monkeypatch.setattr(controller_module, 'ClientSession', FakeSession)

	wrapper = MCPToolWrapper(registry=registry, mcp_command='python')
	monkeypatch.setattr(wrapper, '_keep_session_alive', keep_session_alive)

	def register_tool_as_action(tool_name: str, tool: Any) -> None:
		registry.registry.actions[tool_name] = tool
		wrapper._registered_actions.add(tool_name)

	monkeypatch.setattr(wrapper, '_register_tool_as_action', register_tool_as_action)

	with pytest.raises(ValueError, match='already registered'):
		await wrapper.connect()

	assert wrapper.session is None
	assert wrapper._tools == {}
	assert 'new_tool' not in registry.registry.actions
	assert wrapper._registered_actions == set()

	await wrapper.connect()

	assert connection_count == 2
	assert wrapper.session is None
	assert set(wrapper._tools) == {'new_tool'}
	assert wrapper._registered_actions == {'new_tool'}
	assert 'new_tool' in registry.registry.actions
