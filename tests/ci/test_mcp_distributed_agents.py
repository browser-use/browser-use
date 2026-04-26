"""Distributed agents test for the MCP server.

Tests multiple BrowserUseServer instances operating concurrently:
- Each server manages its own browser session independently
- Concurrent navigation, content extraction, and session lifecycle
- Session tracking and cleanup across parallel agents
"""

import asyncio
import json

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.mcp.server import BrowserUseServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def test_server():
	"""Shared HTTP server serving pages for distributed agent tests."""
	server = HTTPServer()
	server.start()

	server.expect_request('/').respond_with_data(
		'<html><body><h1>Home</h1><p id="content">Welcome</p></body></html>',
		content_type='text/html',
	)
	server.expect_request('/task-a').respond_with_data(
		'<html><body><h1>Task A</h1><p id="result">Result: alpha</p></body></html>',
		content_type='text/html',
	)
	server.expect_request('/task-b').respond_with_data(
		'<html><body><h1>Task B</h1><p id="result">Result: beta</p></body></html>',
		content_type='text/html',
	)
	server.expect_request('/task-c').respond_with_data(
		'<html><body><h1>Task C</h1><p id="result">Result: gamma</p></body></html>',
		content_type='text/html',
	)
	server.expect_request('/form').respond_with_data(
		"""<html><body>
		<form>
			<input id="q" type="text" name="q" />
			<select id="sel" name="sel">
				<option value="1">Option 1</option>
				<option value="2">Option 2</option>
			</select>
		</form>
		</body></html>""",
		content_type='text/html',
	)

	yield server
	server.stop()


async def _make_server_with_session(profile: BrowserProfile) -> BrowserUseServer:
	"""Create a BrowserUseServer and inject a pre-started session directly."""
	server = BrowserUseServer(session_timeout_minutes=5)

	session = BrowserSession(browser_profile=profile)
	await session.start()

	server.browser_session = session
	server._track_session(session)

	return server


async def _cleanup_server(server: BrowserUseServer) -> None:
	"""Kill all tracked sessions inside a server."""
	for session_data in list(server.active_sessions.values()):
		s = session_data['session']
		try:
			await s.kill()
		except Exception:
			pass
	server.active_sessions.clear()
	server.browser_session = None


def _headless_profile() -> BrowserProfile:
	return BrowserProfile(
		headless=True,
		keep_alive=False,
		user_data_dir=None,
		disable_security=True,
	)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_single_agent_navigate_and_get_text(test_server: HTTPServer):
	"""Sanity check: one server can navigate and read page text."""
	server = await _make_server_with_session(_headless_profile())
	try:
		url = test_server.url_for('/task-a')
		nav_result = await server._navigate(url)
		assert 'navigated' in nav_result.lower() or 'http' in nav_result.lower()

		text = await server._get_text()
		assert 'Task A' in text
		assert 'alpha' in text
	finally:
		await _cleanup_server(server)


async def test_three_agents_concurrent_navigation(test_server: HTTPServer):
	"""Three independent servers navigate to different pages simultaneously."""
	paths = ['/task-a', '/task-b', '/task-c']
	expected_texts = ['alpha', 'beta', 'gamma']

	servers = await asyncio.gather(*[_make_server_with_session(_headless_profile()) for _ in paths])

	async def agent_task(srv: BrowserUseServer, path: str) -> str:
		url = test_server.url_for(path)
		await srv._navigate(url)
		return await srv._get_text()

	try:
		results = await asyncio.gather(*[agent_task(srv, path) for srv, path in zip(servers, paths)])

		for result, expected in zip(results, expected_texts):
			assert expected in result, f'Expected "{expected}" in page text, got: {result!r}'
	finally:
		await asyncio.gather(*[_cleanup_server(srv) for srv in servers])


async def test_concurrent_session_tracking(test_server: HTTPServer):
	"""Multiple servers each track their own session independently."""
	n = 3
	servers = await asyncio.gather(*[_make_server_with_session(_headless_profile()) for _ in range(n)])

	try:
		# Each server should track exactly one session
		for srv in servers:
			assert len(srv.active_sessions) == 1

		# Each server's session ID should be unique across all servers
		all_ids = [list(srv.active_sessions.keys())[0] for srv in servers]
		assert len(set(all_ids)) == n, 'Session IDs must be unique across agents'

		# _list_sessions returns valid JSON with the tracked session
		for srv in servers:
			listing = await srv._list_sessions()
			sessions = json.loads(listing)
			assert len(sessions) == 1
			assert sessions[0]['session_id'] in srv.active_sessions
	finally:
		await asyncio.gather(*[_cleanup_server(srv) for srv in servers])


async def test_concurrent_html_extraction(test_server: HTTPServer):
	"""Multiple agents extract HTML from different pages simultaneously."""
	pages = [('/task-a', 'alpha'), ('/task-b', 'beta'), ('/task-c', 'gamma')]

	servers = await asyncio.gather(*[_make_server_with_session(_headless_profile()) for _ in pages])

	async def navigate_and_extract(srv: BrowserUseServer, path: str) -> str:
		await srv._navigate(test_server.url_for(path))
		return await srv._get_html()

	try:
		htmls = await asyncio.gather(*[navigate_and_extract(srv, path) for srv, (path, _) in zip(servers, pages)])

		for html, (_, keyword) in zip(htmls, pages):
			assert keyword in html
	finally:
		await asyncio.gather(*[_cleanup_server(srv) for srv in servers])


async def test_agent_back_forward_navigation(test_server: HTTPServer):
	"""Single agent navigates forward/back between pages."""
	server = await _make_server_with_session(_headless_profile())
	try:
		await server._navigate(test_server.url_for('/task-a'))
		await server._navigate(test_server.url_for('/task-b'))

		back_result = await server._go_back()
		assert 'Error' not in back_result

		text_after_back = await server._get_text()
		assert 'Task A' in text_after_back

		fwd_result = await server._go_forward()
		assert 'Error' not in fwd_result

		text_after_fwd = await server._get_text()
		assert 'Task B' in text_after_fwd
	finally:
		await _cleanup_server(server)


async def test_session_close_and_list(test_server: HTTPServer):
	"""Closing a session removes it from tracking."""
	server = await _make_server_with_session(_headless_profile())
	try:
		session_id = list(server.active_sessions.keys())[0]

		# Verify it's listed
		listing_before = await server._list_sessions()
		data = json.loads(listing_before)
		assert any(s['session_id'] == session_id for s in data)

		# Close it
		close_result = await server._close_session(session_id)
		assert 'Successfully closed' in close_result

		# Should no longer appear
		listing_after = await server._list_sessions()
		assert 'No active' in listing_after or session_id not in listing_after

		# current session ref cleared
		assert server.browser_session is None
	except Exception:
		# Already cleaned by close_session, avoid double-kill
		server.active_sessions.clear()
		server.browser_session = None
		raise


async def test_close_all_sessions(test_server: HTTPServer):
	"""_close_all_sessions closes every tracked session at once."""
	# One server, but inject two sessions manually
	server = BrowserUseServer(session_timeout_minutes=5)

	sessions = []
	for _ in range(2):
		s = BrowserSession(browser_profile=_headless_profile())
		await s.start()
		sessions.append(s)
		server._track_session(s)

	server.browser_session = sessions[0]

	try:
		assert len(server.active_sessions) == 2
		result = await server._close_all_sessions()
		assert 'Closed 2 sessions' in result
		assert len(server.active_sessions) == 0
		assert server.browser_session is None
	except Exception:
		for s in sessions:
			try:
				await s.kill()
			except Exception:
				pass
		raise


async def test_expired_session_cleanup():
	"""Sessions past the timeout are cleaned up by _cleanup_expired_sessions."""
	import time

	server = BrowserUseServer(session_timeout_minutes=1)

	s = BrowserSession(browser_profile=_headless_profile())
	await s.start()
	server._track_session(s)
	server.browser_session = s

	session_id = s.id

	# Wind the clock back so the session looks expired
	server.active_sessions[session_id]['last_activity'] -= 120  # 2 minutes ago

	try:
		await server._cleanup_expired_sessions()
		assert session_id not in server.active_sessions, 'Expired session should be removed'
	except Exception:
		try:
			await s.kill()
		except Exception:
			pass
		raise
