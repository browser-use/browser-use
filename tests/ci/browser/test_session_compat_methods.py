"""Regression tests for legacy BrowserSession convenience methods."""

import socketserver
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import AgentFocusChangedEvent, SwitchTabEvent

# Prevent pytest-httpserver shutdown hangs in local runs.
socketserver.ThreadingMixIn.block_on_close = False
socketserver.ThreadingMixIn.daemon_threads = True


@pytest.fixture(scope='session')
def compat_http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/').respond_with_data(
		'<html><head><title>Compat Home</title></head><body><h1>Compat Home</h1></body></html>',
		content_type='text/html',
	)
	server.expect_request('/page2').respond_with_data(
		'<html><head><title>Compat Page 2</title></head><body><h1>Compat Page 2</h1></body></html>',
		content_type='text/html',
	)
	server.expect_request('/favicon.ico').respond_with_data('', status=204, content_type='image/x-icon')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def compat_base_url(compat_http_server):
	return f'http://{compat_http_server.host}:{compat_http_server.port}'


@pytest.fixture(scope='function')
async def compat_browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


@pytest.mark.asyncio
async def test_execute_javascript_alias_uses_current_page(compat_browser_session: BrowserSession, compat_base_url: str):
	await compat_browser_session.navigate_to(f'{compat_base_url}/')

	assert await compat_browser_session.execute_javascript('document.title') == 'Compat Home'

	await compat_browser_session.execute_javascript("document.body.dataset.compat = 'ok'")

	assert await compat_browser_session.execute_javascript('document.body.dataset.compat') == 'ok'


@pytest.mark.asyncio
async def test_refresh_alias_reloads_current_page(compat_browser_session: BrowserSession, compat_base_url: str):
	await compat_browser_session.navigate_to(f'{compat_base_url}/')
	await compat_browser_session.execute_javascript("document.title = 'Mutated Title'")

	assert await compat_browser_session.execute_javascript('document.title') == 'Mutated Title'

	await compat_browser_session.refresh()

	assert await compat_browser_session.get_current_page_url() == f'{compat_base_url}/'
	assert await compat_browser_session.execute_javascript('document.title') == 'Compat Home'


@pytest.mark.asyncio
async def test_legacy_tab_methods_support_index_and_suffix_refs(compat_browser_session: BrowserSession, compat_base_url: str):
	await compat_browser_session.navigate_to(f'{compat_base_url}/')

	new_target_id = await compat_browser_session.create_new_tab(f'{compat_base_url}/page2')
	assert new_target_id is not None
	assert await compat_browser_session.get_current_page_url() == f'{compat_base_url}/page2'

	tabs = await compat_browser_session.get_tabs_info()
	assert len(tabs) == 2
	second_tab_suffix = tabs[1].target_id[-4:]

	await compat_browser_session.switch_to_tab(0)
	assert await compat_browser_session.get_current_page_url() == f'{compat_base_url}/'

	await compat_browser_session.switch_to_tab(second_tab_suffix)
	assert await compat_browser_session.get_current_page_url() == f'{compat_base_url}/page2'

	await compat_browser_session.close_tab(second_tab_suffix)

	remaining_tabs = await compat_browser_session.get_tabs_info()
	non_blank_tabs = [tab for tab in remaining_tabs if tab.url != 'about:blank']
	assert len(non_blank_tabs) == 1
	assert non_blank_tabs[0].url == f'{compat_base_url}/'


@pytest.mark.asyncio
async def test_get_current_page_url_returns_about_blank_for_stale_focus_target():
	session = BrowserSession(headless=True)
	object.__setattr__(session, 'agent_focus_target_id', 'stale-target')
	session_manager = MagicMock()
	session_manager.get_target.return_value = None
	object.__setattr__(session, 'session_manager', session_manager)

	assert await session.get_current_page_url() == 'about:blank'


@pytest.mark.asyncio
async def test_get_current_target_info_returns_none_for_stale_focus_target():
	session = BrowserSession(headless=True)
	object.__setattr__(session, 'agent_focus_target_id', 'stale-target')
	session_manager = MagicMock()
	session_manager.get_target.return_value = None
	object.__setattr__(session, 'session_manager', session_manager)

	assert await session.get_current_target_info() is None


@pytest.mark.asyncio
async def test_current_accessors_handle_missing_session_manager():
	session = BrowserSession(headless=True)
	object.__setattr__(session, 'agent_focus_target_id', 'stale-target')
	object.__setattr__(session, 'session_manager', None)

	assert await session.get_current_target_info() is None
	assert await session.get_current_page() is None
	assert await session.get_current_page_url() == 'about:blank'
	assert await session.get_current_page_title() == 'Unknown page title'


@pytest.mark.asyncio
async def test_cdp_client_for_node_uses_session_lookup_even_if_target_detached():
	session = BrowserSession(headless=True)
	cdp_session = MagicMock(target_id='stale-target')

	session_manager = MagicMock()
	session_manager.get_session.return_value = cdp_session
	session_manager.get_target.return_value = None
	object.__setattr__(session, 'session_manager', session_manager)

	node = SimpleNamespace(session_id='session-1', frame_id=None, target_id=None, backend_node_id=42)

	assert await session.cdp_client_for_node(cast(Any, node)) is cdp_session


@pytest.mark.asyncio
async def test_switch_tab_event_handles_stale_target_after_activation():
	session = BrowserSession(headless=True)
	object.__setattr__(session, 'agent_focus_target_id', 'current-target')

	cdp_client = MagicMock()
	cdp_client.send = MagicMock()
	cdp_client.send.Target = MagicMock()
	cdp_client.send.Target.activateTarget = AsyncMock()
	cdp_session = MagicMock(session_id='session-1', cdp_client=cdp_client)

	object.__setattr__(session, 'get_or_create_cdp_session', AsyncMock(return_value=cdp_session))

	session_manager = MagicMock()
	session_manager.get_target.return_value = None
	object.__setattr__(session, 'session_manager', session_manager)

	event_bus = MagicMock()
	event_bus.dispatch = AsyncMock()
	object.__setattr__(session, 'event_bus', event_bus)

	target_id = await session.on_SwitchTabEvent(SwitchTabEvent(target_id='stale-target'))

	assert target_id == 'stale-target'
	cdp_client.send.Target.activateTarget.assert_awaited_once_with(params={'targetId': 'stale-target'})
	event_bus.dispatch.assert_awaited_once()
	dispatched_event = event_bus.dispatch.await_args.args[0]
	assert isinstance(dispatched_event, AgentFocusChangedEvent)
	assert dispatched_event.target_id == 'stale-target'
	assert dispatched_event.url == 'about:blank'


@pytest.mark.asyncio
async def test_navigate_and_wait_handles_stale_target_when_computing_default_timeout():
	session = BrowserSession(headless=True)

	cdp_client = MagicMock()
	cdp_client.send = MagicMock()
	cdp_client.send.Page = MagicMock()
	cdp_client.send.Page.navigate = AsyncMock(return_value={})
	cdp_session = MagicMock(session_id='session-1', target_id='stale-target', cdp_client=cdp_client)
	cdp_session._lifecycle_events = []

	object.__setattr__(session, 'get_or_create_cdp_session', AsyncMock(return_value=cdp_session))

	session_manager = MagicMock()
	session_manager.get_target.return_value = None
	object.__setattr__(session, 'session_manager', session_manager)

	await session._navigate_and_wait('https://example.com', 'stale-target', timeout=None, wait_until='commit')

	cdp_client.send.Page.navigate.assert_awaited_once_with(
		params={'url': 'https://example.com', 'transitionType': 'address_bar'},
		session_id='session-1',
	)


@pytest.mark.asyncio
async def test_navigate_to_url_event_handles_stale_focus_target_when_opening_new_tab():
	from browser_use.browser.events import NavigateToUrlEvent

	session = BrowserSession(headless=True)
	object.__setattr__(session, 'agent_focus_target_id', 'stale-target')

	session_manager = MagicMock()
	session_manager.get_target.return_value = None
	session_manager.get_all_page_targets.return_value = []
	object.__setattr__(session, 'session_manager', session_manager)

	create_new_page = AsyncMock(return_value='fresh-target')
	navigate_and_wait = AsyncMock()
	close_extension_options_pages = AsyncMock()
	object.__setattr__(session, '_cdp_create_new_page', create_new_page)
	object.__setattr__(session, '_navigate_and_wait', navigate_and_wait)
	object.__setattr__(session, '_close_extension_options_pages', close_extension_options_pages)

	async def dispatch_side_effect(event):
		if isinstance(event, SwitchTabEvent):
			object.__setattr__(session, 'agent_focus_target_id', event.target_id)
		return None

	event_bus = MagicMock()
	event_bus.dispatch = AsyncMock(side_effect=dispatch_side_effect)
	object.__setattr__(session, 'event_bus', event_bus)

	await session.on_NavigateToUrlEvent(NavigateToUrlEvent(url='https://example.com', new_tab=True))

	create_new_page.assert_awaited_once_with('about:blank')
	navigate_and_wait.assert_awaited_once_with('https://example.com', 'fresh-target', wait_until='load')
	close_extension_options_pages.assert_awaited_once()
