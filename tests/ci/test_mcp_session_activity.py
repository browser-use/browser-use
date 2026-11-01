"""Regression tests for MCP server session-activity tracking.

The idle-timeout cleanup (`_cleanup_expired_sessions`, default 10 minutes)
kills sessions whose `last_activity` is stale. `_update_session_activity` was
only called inside four tool implementations (`browser_navigate`,
`browser_click`, `browser_get_html`, `browser_screenshot`), so a client whose
workflow only used the other browser tools (polling `browser_get_state`,
typing, scrolling, extracting content, tab management) had its session
reaped mid-use and silently rebuilt — losing page state and logins.

Activity is now recorded once in the `_execute_tool` dispatch layer for every
`browser_*` tool.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import Any

from browser_use.mcp.server import BrowserUseServer

SESSION_ID = 'sess-1'


def _make_server_with_stale_session(monkeypatch) -> tuple[BrowserUseServer, dict[str, Any]]:
	server = BrowserUseServer()
	fake_session = SimpleNamespace(id=SESSION_ID)
	monkeypatch.setattr(server, 'browser_session', fake_session)
	stale = time.time() - 9999
	server.active_sessions[SESSION_ID] = {
		'session': fake_session,
		'created_at': stale,
		'last_activity': stale,
		'url': None,
	}
	return server, server.active_sessions[SESSION_ID]


async def test_any_browser_tool_refreshes_session_activity(monkeypatch):
	server, session_data = _make_server_with_stale_session(monkeypatch)

	async def fake_list_tabs():
		return '[]'

	monkeypatch.setattr(server, '_list_tabs', fake_list_tabs)

	before = session_data['last_activity']
	await server._execute_tool('browser_list_tabs', {})

	assert session_data['last_activity'] > before, (
		'browser_list_tabs must refresh last_activity — before the fix only '
		'navigate/click/get_html/screenshot did, so polling clients had their '
		'session reaped by the idle-timeout cleanup'
	)


async def test_read_and_input_tools_refresh_session_activity(monkeypatch):
	"""get_state / type / scroll / extract — the typical polling & form workflows."""
	server, session_data = _make_server_with_stale_session(monkeypatch)

	stubs = {
		'_get_browser_state': lambda include_screenshot=False: ('{}', None),
		'_type_text': lambda index, text: 'typed',
		'_scroll': lambda direction='down': 'scrolled',
		'_extract_content': lambda query, extract_links=False: 'extracted',
	}

	async def _async_wrap(fn):
		async def wrapper(*args, **kwargs):
			return fn(*args, **kwargs)

		return wrapper

	for name, impl in stubs.items():
		monkeypatch.setattr(server, name, await _async_wrap(impl))

	for tool, args in [
		('browser_get_state', {}),
		('browser_type', {'index': 1, 'text': 'hello'}),
		('browser_scroll', {}),
		('browser_extract_content', {'query': 'q'}),
	]:
		before = session_data['last_activity']
		await asyncio.sleep(0.01)
		await server._execute_tool(tool, args)
		assert session_data['last_activity'] > before, f'{tool} must refresh last_activity'
