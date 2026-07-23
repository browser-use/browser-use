"""Tests for the CLI 3.0 MCP server (browser-use --cli-mcp).

Exercises the exec namespace, output capture, and tool/instruction surface with
real objects. Code that needs the browser daemon is not run here (CI has no
Chrome); daemon connection is covered by the `connect` seam being off.
"""

import mcp.types as types

from browser_use.mcp.cli_mcp import CLIMCPServer


def test_execute_captures_stdout():
	server = CLIMCPServer()
	assert server._execute('print(2 + 2)', connect=False) == '4\n'


def test_execute_namespace_persists_across_calls():
	server = CLIMCPServer()
	assert server._execute('x = 41', connect=False) == ''
	assert server._execute('print(x + 1)', connect=False) == '42\n'


def test_execute_returns_traceback_on_error():
	server = CLIMCPServer()
	output = server._execute('1 / 0', connect=False)
	assert 'ZeroDivisionError' in output
	assert 'Traceback' in output


def test_execute_isolated_between_servers():
	a = CLIMCPServer()
	b = CLIMCPServer()
	a._execute('secret = 1', connect=False)
	output = b._execute('print(secret)', connect=False)
	assert 'NameError' in output


def test_harness_helpers_preimported():
	server = CLIMCPServer()
	ns = server._ensure_namespace()
	for helper in ('new_tab', 'goto_url', 'page_info', 'click_at_xy', 'js', 'cdp', 'wait_for_load', 'capture_screenshot'):
		assert callable(ns[helper]), f'missing harness helper: {helper}'
	for admin in ('ensure_daemon', 'start_remote_daemon', 'stop_remote_daemon'):
		assert callable(ns[admin]), f'missing admin helper: {admin}'


def test_tool_definitions():
	server = CLIMCPServer()
	tools = server._tool_definitions()
	names = {tool.name for tool in tools}
	assert names == {'browser_exec', 'browser_screenshot'}
	exec_tool = next(tool for tool in tools if tool.name == 'browser_exec')
	assert exec_tool.inputSchema['required'] == ['code']
	assert isinstance(exec_tool, types.Tool)


async def test_screenshot_rejects_invalid_max_dim():
	"""Bad max_dim must come back as a clean tool error (SDK schema validation or handler guard), never an image or a crash."""
	server = CLIMCPServer()
	handler = server.server.request_handlers[types.CallToolRequest]
	for bad in (-5, 0, True, 'big'):
		request = types.CallToolRequest(
			method='tools/call',
			params=types.CallToolRequestParams(name='browser_screenshot', arguments={'max_dim': bad}),
		)
		result = (await handler(request)).root
		assert isinstance(result, types.CallToolResult)
		assert result.content[0].type == 'text', f'max_dim={bad!r} not rejected'
		text = result.content[0].text
		assert 'validation error' in text.lower() or 'positive integer' in text, f'max_dim={bad!r}: {text}'


def test_cli_routes_mcp_harness_flag():
	from browser_use.cli import _command_name

	assert _command_name(['--cli-mcp']) == 'cli-mcp'
	assert _command_name(['--mcp']) == 'mcp'


def test_instructions_are_skill_text():
	from browser_use.skills.browser_use import skill_text

	server = CLIMCPServer()
	instructions = server._instructions()
	assert instructions == skill_text()
	assert 'new_tab' in instructions
	assert 'page_info' in instructions
	# Instructions use the browser-use identity; harness branding only survives in repo URLs
	for line in instructions.splitlines():
		if 'browser-harness' in line:
			assert '/browser-harness' in line, f'unrebranded harness mention: {line!r}'
