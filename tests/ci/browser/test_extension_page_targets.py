"""Keep Chrome extension pages out of agent-facing tab selection."""

from unittest.mock import AsyncMock, patch

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def _session_with_targets() -> BrowserSession:
	"""Create a session with ordinary tabs and an extension options page in CDP discovery order."""
	session = BrowserSession(enable_default_extensions=False, user_data_dir=None)
	manager = SessionManager(session)
	manager._targets = {
		'page': Target(target_id='page', target_type='page', url='https://example.com/'),
		'blank': Target(target_id='blank', target_type='tab', url='about:blank'),
		'extension': Target(target_id='extension', target_type='page', url='chrome-extension://abcdef/options.html'),
		'worker': Target(target_id='worker', target_type='service_worker', url='https://example.com/worker.js'),
	}
	session.session_manager = manager
	return session


async def test_extension_is_not_offered_as_a_recent_tab():
	"""An extension side panel discovered last cannot become the most recent page."""
	session = _session_with_targets()
	assert [target.target_id for target in session.get_page_targets()] == ['page', 'blank']
	assert await session.get_most_recently_opened_target_id() == 'blank'
	assert 'extension' in session.session_manager.get_all_targets()


def test_explicit_extension_filter_retains_extension_pages():
	"""Internal callers that manage extensions can explicitly include extension targets."""
	session = _session_with_targets()
	targets = session.session_manager.get_all_page_targets(include_extensions=True)
	assert [target.target_id for target in targets] == ['page', 'blank', 'extension']


async def test_extension_options_cleanup_still_sees_extension_pages():
	"""Filtering agent-facing tabs must not disable the extension-options cleanup path."""
	session = _session_with_targets()
	with patch.object(BrowserSession, '_cdp_close_page', new_callable=AsyncMock) as close_page:
		await session._close_extension_options_pages()
	close_page.assert_awaited_once_with('extension')


async def test_reconnect_restores_focus_on_an_extension_page(monkeypatch):
	"""An agent working on an extension page keeps that tab focused after a CDP reconnect."""
	from browser_use.browser._cdp_timeout import TimeoutWrappedCDPClient
	from browser_use.browser.profile import BrowserProfile

	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, cdp_url='ws://127.0.0.1:9222'))
	session.agent_focus_target_id = 'extension'
	focused = []

	async def start_monitoring(manager):
		manager._targets = _session_with_targets().session_manager._targets

	async def start(client):
		client._message_handler_task = None

	async def send_raw(client, method, params=None, session_id=None):
		return {}

	async def get_or_create_cdp_session(self, target_id=None, focus=True):
		if focus:
			focused.append(target_id)

	async def noop(self):
		return None

	monkeypatch.setattr(SessionManager, 'start_monitoring', start_monitoring)
	monkeypatch.setattr(TimeoutWrappedCDPClient, 'start', start)
	monkeypatch.setattr(TimeoutWrappedCDPClient, 'send_raw', send_raw)
	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', get_or_create_cdp_session)
	monkeypatch.setattr(BrowserSession, '_setup_proxy_auth', noop)
	monkeypatch.setattr(BrowserSession, '_attach_ws_drop_callback', lambda self: None)

	try:
		await session.reconnect()
		assert focused == ['extension']
	finally:
		await session.event_bus.stop(clear=True, timeout=5)
