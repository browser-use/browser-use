"""Regression tests for legacy BrowserSession convenience methods."""

import socketserver

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession

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
