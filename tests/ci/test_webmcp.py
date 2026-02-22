"""Tests for WebMCP tool discovery and invocation via the W3C navigator.modelContext API."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.tools.service import Tools
from browser_use.webmcp.service import WebMCPService, _sanitize_tool_name
from browser_use.webmcp.views import WebMCPToolDescriptor, WebMCPToolResult

# HTML pages implementing navigator.modelContext (W3C WebMCP spec)

PAGE_WITH_WEBMCP_TOOLS = """
<html>
<head><title>WebMCP Test Page</title></head>
<body>
<h1>WebMCP Test Page</h1>
<script>
// Minimal navigator.modelContext polyfill
(function() {
  var tools = {};
  navigator.modelContext = {
    provideContext: function(ctx) {
      tools = {};
      var ts = (ctx && ctx.tools) || [];
      for (var i = 0; i < ts.length; i++) tools[ts[i].name] = ts[i];
    },
    registerTool: function(tool) {
      tools[tool.name] = tool;
      return { unregister: function() { delete tools[tool.name]; } };
    },
    unregisterTool: function(name) { delete tools[name]; }
  };
})();

// Register tools via provideContext (W3C spec pattern)
navigator.modelContext.provideContext({
  tools: [
    {
      name: "add-todo",
      description: "Add a new todo item",
      inputSchema: {
        type: "object",
        properties: {
          text: { type: "string", description: "The todo text" }
        },
        required: ["text"]
      },
      execute: function(args) {
        return { content: [{ type: "text", text: "Added: " + args.text }] };
      }
    },
    {
      name: "get-count",
      description: "Get the current item count",
      inputSchema: { type: "object", properties: {} },
      execute: function() {
        return { content: [{ type: "text", text: "Count: 42" }] };
      }
    }
  ]
});
</script>
</body>
</html>
"""

PAGE_WITH_DYNAMIC_TOOL = """
<html>
<head><title>Dynamic WebMCP Page</title></head>
<body>
<h1>Dynamic Tool Page</h1>
<script>
(function() {
  var tools = {};
  navigator.modelContext = {
    provideContext: function(ctx) {
      tools = {};
      var ts = (ctx && ctx.tools) || [];
      for (var i = 0; i < ts.length; i++) tools[ts[i].name] = ts[i];
    },
    registerTool: function(tool) {
      tools[tool.name] = tool;
      return { unregister: function() { delete tools[tool.name]; } };
    },
    unregisterTool: function(name) { delete tools[name]; }
  };
})();

// Register a tool dynamically after a short delay (via registerTool)
setTimeout(function() {
  navigator.modelContext.registerTool({
    name: "delayed-tool",
    description: "A tool registered after page load",
    inputSchema: {
      type: "object",
      properties: {
        value: { type: "number", description: "A numeric value" }
      },
      required: ["value"]
    },
    execute: function(args) {
      return { content: [{ type: "text", text: "Received: " + args.value }] };
    }
  });
}, 100);
</script>
</body>
</html>
"""

PAGE_WITH_ERROR_TOOL = """
<html>
<head><title>Error Tool Page</title></head>
<body>
<h1>Error Tool Page</h1>
<script>
(function() {
  var tools = {};
  navigator.modelContext = {
    provideContext: function(ctx) {
      tools = {};
      var ts = (ctx && ctx.tools) || [];
      for (var i = 0; i < ts.length; i++) tools[ts[i].name] = ts[i];
    },
    registerTool: function(tool) {
      tools[tool.name] = tool;
      return { unregister: function() { delete tools[tool.name]; } };
    },
    unregisterTool: function(name) { delete tools[name]; }
  };
})();

navigator.modelContext.provideContext({
  tools: [
    {
      name: "failing-tool",
      description: "A tool that always throws",
      inputSchema: { type: "object", properties: {} },
      execute: function() {
        throw new Error("Something went wrong");
      }
    }
  ]
});
</script>
</body>
</html>
"""

PAGE_NO_WEBMCP = """
<html>
<head><title>Plain Page</title></head>
<body><h1>No WebMCP here</h1></body>
</html>
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/webmcp-tools').respond_with_data(PAGE_WITH_WEBMCP_TOOLS, content_type='text/html')
	server.expect_request('/webmcp-dynamic').respond_with_data(PAGE_WITH_DYNAMIC_TOOL, content_type='text/html')
	server.expect_request('/webmcp-error').respond_with_data(PAGE_WITH_ERROR_TOOL, content_type='text/html')
	server.expect_request('/no-webmcp').respond_with_data(PAGE_NO_WEBMCP, content_type='text/html')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			webmcp_enabled=True,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


# ---------------------------------------------------------------------------
# Unit tests: views + service helpers
# ---------------------------------------------------------------------------


class TestWebMCPViews:
	def test_tool_descriptor_creation(self):
		desc = WebMCPToolDescriptor(
			name='test-tool',
			description='A test tool',
			input_schema={
				'type': 'object',
				'properties': {'text': {'type': 'string'}},
				'required': ['text'],
			},
		)
		assert desc.name == 'test-tool'
		assert desc.description == 'A test tool'
		assert 'text' in desc.input_schema['properties']

	def test_tool_result_with_content(self):
		result = WebMCPToolResult.model_validate(
			{
				'content': [{'type': 'text', 'text': 'hello'}],
			}
		)
		assert len(result.content) == 1
		assert result.content[0].text == 'hello'
		assert result.error is None

	def test_tool_result_with_error(self):
		result = WebMCPToolResult(error='something broke')
		assert result.error == 'something broke'
		assert len(result.content) == 0

	def test_sanitize_tool_name(self):
		assert _sanitize_tool_name('add-todo') == 'webmcp_add_todo'
		assert _sanitize_tool_name('getDresses') == 'webmcp_getDresses'
		assert _sanitize_tool_name('my.tool.name') == 'webmcp_my_tool_name'
		assert _sanitize_tool_name('simple') == 'webmcp_simple'


# ---------------------------------------------------------------------------
# Integration tests: discovery and invocation via real browser
# ---------------------------------------------------------------------------


class TestWebMCPDiscovery:
	async def test_discover_tools_on_webmcp_page(self, browser_session: BrowserSession, base_url: str):
		"""Navigate to a page with WebMCP tools and verify discovery."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		tools = await service.discover_tools(browser_session)

		tool_names = {t.name for t in tools}
		assert 'add-todo' in tool_names, f'Expected add-todo in {tool_names}'
		assert 'get-count' in tool_names, f'Expected get-count in {tool_names}'

	async def test_discover_no_tools_on_plain_page(self, browser_session: BrowserSession, base_url: str):
		"""Navigate to a page without WebMCP and verify empty discovery."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/no-webmcp'))
		await event
		await asyncio.sleep(0.3)

		service = WebMCPService()
		tools = await service.discover_tools(browser_session)
		assert len(tools) == 0

	async def test_discover_dynamic_tool(self, browser_session: BrowserSession, base_url: str):
		"""Navigate to a page with a dynamically registered tool."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-dynamic'))
		await event
		# Wait for the setTimeout(100ms) + bridge processing
		await asyncio.sleep(0.8)

		service = WebMCPService()
		tools = await service.discover_tools(browser_session)

		tool_names = {t.name for t in tools}
		assert 'delayed-tool' in tool_names, f'Expected delayed-tool in {tool_names}'


class TestWebMCPToolCall:
	async def test_call_tool_with_params(self, browser_session: BrowserSession, base_url: str):
		"""Call a WebMCP tool that takes parameters."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		result = await service.call_tool(browser_session, 'add-todo', {'text': 'Buy milk'})

		assert result.error is None, f'Unexpected error: {result.error}'
		texts = [item.text for item in result.content]
		assert any('Buy milk' in t for t in texts), f'Expected "Buy milk" in result content: {texts}'

	async def test_call_tool_without_params(self, browser_session: BrowserSession, base_url: str):
		"""Call a WebMCP tool that takes no parameters."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		result = await service.call_tool(browser_session, 'get-count', {})

		assert result.error is None, f'Unexpected error: {result.error}'
		texts = [item.text for item in result.content]
		assert any('42' in t for t in texts), f'Expected "42" in result content: {texts}'

	async def test_call_tool_error_handling(self, browser_session: BrowserSession, base_url: str):
		"""Call a WebMCP tool that throws an error."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-error'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		result = await service.call_tool(browser_session, 'failing-tool', {})

		assert result.error is not None, 'Expected an error from failing tool'

	async def test_call_nonexistent_tool(self, browser_session: BrowserSession, base_url: str):
		"""Call a tool that doesn't exist."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		result = await service.call_tool(browser_session, 'nonexistent', {})

		assert result.error is not None, 'Expected an error for nonexistent tool'


class TestWebMCPRegistrySync:
	async def test_sync_registers_actions(self, browser_session: BrowserSession, base_url: str):
		"""Verify that discovered tools get registered as actions."""
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		service = WebMCPService()
		tools_obj = Tools()
		discovered = await service.discover_tools(browser_session)
		service.sync_actions_to_registry(tools_obj.registry, discovered, f'{base_url}/webmcp-tools', browser_session)

		action_names = set(tools_obj.registry.registry.actions.keys())
		assert 'webmcp_add_todo' in action_names, f'Expected webmcp_add_todo in {action_names}'
		assert 'webmcp_get_count' in action_names, f'Expected webmcp_get_count in {action_names}'

	async def test_sync_clears_stale_actions(self, browser_session: BrowserSession, base_url: str):
		"""Verify stale actions are removed when tools change."""
		service = WebMCPService()
		tools_obj = Tools()

		# First sync with tools
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		discovered = await service.discover_tools(browser_session)
		service.sync_actions_to_registry(tools_obj.registry, discovered, f'{base_url}/webmcp-tools', browser_session)
		assert 'webmcp_add_todo' in tools_obj.registry.registry.actions

		# Second sync with no tools (navigated away)
		service.sync_actions_to_registry(tools_obj.registry, [], f'{base_url}/no-webmcp', browser_session)
		assert 'webmcp_add_todo' not in tools_obj.registry.registry.actions

	async def test_clear_all_actions(self, browser_session: BrowserSession, base_url: str):
		"""Verify clear_all_actions removes everything."""
		service = WebMCPService()
		tools_obj = Tools()

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		discovered = await service.discover_tools(browser_session)
		service.sync_actions_to_registry(tools_obj.registry, discovered, f'{base_url}/webmcp-tools', browser_session)
		assert len(service._registered_actions) > 0

		service.clear_all_actions(tools_obj.registry)
		assert len(service._registered_actions) == 0

	async def test_actions_have_domain_filter(self, browser_session: BrowserSession, base_url: str):
		"""Verify registered actions have domain filters set."""
		service = WebMCPService()
		tools_obj = Tools()

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/webmcp-tools'))
		await event
		await asyncio.sleep(0.5)

		discovered = await service.discover_tools(browser_session)
		service.sync_actions_to_registry(tools_obj.registry, discovered, f'{base_url}/webmcp-tools', browser_session)

		action = tools_obj.registry.registry.actions.get('webmcp_add_todo')
		assert action is not None
		assert action.domains is not None
		assert len(action.domains) > 0


class TestWebMCPDisabled:
	async def test_webmcp_disabled_no_watchdog(self):
		"""When webmcp_enabled=False, no WebMCPWatchdog should be attached."""
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				webmcp_enabled=False,
			)
		)
		await session.start()
		try:
			assert not hasattr(session, '_webmcp_watchdog') or session._webmcp_watchdog is None
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)
