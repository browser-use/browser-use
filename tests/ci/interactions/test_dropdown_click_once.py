"""Test that select_dropdown activates the chosen ARIA/custom option exactly once and lets the page own its state.

Option click handlers often toggle (checkbox-style listboxes, multi-select chips). A second synthetic click undoes
the selection, and pre-writing aria-selected / classes before the click makes DOM-state toggles flip it back off.
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools

# Page reports {clicks, picked, selected, classes} through window.readState(); `picked` is app-side state,
# `selected` / `classes` are the DOM state of the option with id="remote".
STATE_SCRIPT = """
<script>
	window.clicks = 0;
	window.picked = new Set();
	window.readState = () => {
		const remote = document.getElementById('remote');
		return {
			clicks: window.clicks,
			picked: [...window.picked],
			selected: remote.getAttribute('aria-selected'),
			classes: remote.className,
			peerSelected: document.getElementById('hybrid').getAttribute('aria-selected'),
		};
	};
</script>
"""

PAGES = {
	# App keeps selection in its own state, like React/Vue components
	'/aria-app-state': """
		<div id="dropdown" role="listbox" aria-multiselectable="true" tabindex="0">
			<div role="option" id="remote">Remote</div>
			<div role="option" id="hybrid">Hybrid</div>
		</div>
		<script>
			document.querySelectorAll('[role=option]').forEach(item => item.addEventListener('click', () => {
				window.clicks++;
				if (window.picked.has(item.id)) window.picked.delete(item.id); else window.picked.add(item.id);
			}));
		</script>
	""",
	'/custom-app-state': """
		<div id="dropdown" class="ui dropdown" tabindex="0">
			<div class="text">Choose</div>
			<div class="menu">
				<div class="item" id="remote" data-value="remote">Remote</div>
				<div class="item" id="hybrid" data-value="hybrid">Hybrid</div>
			</div>
		</div>
		<script>
			document.querySelectorAll('.item').forEach(item => item.addEventListener('click', () => {
				window.clicks++;
				if (window.picked.has(item.id)) window.picked.delete(item.id); else window.picked.add(item.id);
			}));
		</script>
	""",
	# Widget keeps selection in the DOM itself; Hybrid is already selected and must stay selected
	'/aria-dom-state': """
		<div id="dropdown" role="listbox" aria-multiselectable="true" tabindex="0">
			<div role="option" id="remote" aria-selected="false">Remote</div>
			<div role="option" id="hybrid" aria-selected="true">Hybrid</div>
		</div>
		<script>
			document.querySelectorAll('[role=option]').forEach(item => item.addEventListener('click', () => {
				window.clicks++;
				item.setAttribute('aria-selected', String(item.getAttribute('aria-selected') !== 'true'));
			}));
		</script>
	""",
	'/custom-dom-state': """
		<div id="dropdown" class="ui dropdown" tabindex="0">
			<div class="text">Choose</div>
			<div class="menu">
				<div class="item" id="remote" data-value="remote">Remote</div>
				<div class="item" id="hybrid" data-value="hybrid">Hybrid</div>
			</div>
		</div>
		<script>
			document.querySelectorAll('.item').forEach(item => item.addEventListener('click', () => {
				window.clicks++;
				item.classList.toggle('selected');
			}));
		</script>
	""",
	'/aria-disabled': """
		<div id="dropdown" role="listbox" tabindex="0">
			<div role="option" id="remote" aria-disabled="true" aria-selected="false">Remote</div>
			<div role="option" id="hybrid" aria-selected="false">Hybrid</div>
		</div>
		<script>
			document.querySelectorAll('[role=option]').forEach(item => item.addEventListener('click', () => { window.clicks++; }));
		</script>
	""",
}


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server with toggling dropdown pages."""
	server = HTTPServer()
	server.start()
	for path, body in PAGES.items():
		server.expect_request(path).respond_with_data(
			f'<!DOCTYPE html><html><head><title>Dropdown</title>{STATE_SCRIPT}</head><body>{body}</body></html>',
			content_type='text/html',
		)
	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance for testing."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			chromium_sandbox=False,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


@pytest.fixture(scope='function')
def tools():
	"""Create and provide a Tools instance."""
	return Tools()


async def _select_remote(tools: Tools, browser_session: BrowserSession, url: str):
	await tools.navigate(url=url, new_tab=False, browser_session=browser_session)
	await asyncio.sleep(0.3)
	await browser_session.get_browser_state_summary()

	dropdown_index = await browser_session.get_index_by_id('dropdown')
	assert dropdown_index is not None, 'Could not find #dropdown'
	result = await tools.select_dropdown(index=dropdown_index, text='Remote', browser_session=browser_session)

	cdp_session = await browser_session.get_or_create_cdp_session()
	state = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'window.readState()', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result, state.get('result', {}).get('value', {})


class TestDropdownClickOnce:
	"""select_dropdown must click the option once and must not fake its selected state."""

	@pytest.mark.parametrize('path', ['/aria-app-state', '/custom-app-state'])
	async def test_app_state_toggle_stays_selected(self, tools: Tools, browser_session: BrowserSession, base_url: str, path: str):
		"""An option whose handler toggles app state runs once and stays selected."""
		result, state = await _select_remote(tools, browser_session, f'{base_url}{path}')

		assert result.error is None, f'select_dropdown failed: {result.error}'
		assert state['clicks'] == 1, f'Expected the option click handler to run once, ran {state["clicks"]} times'
		assert state['picked'] == ['remote'], f'Expected Remote to stay selected, app state is {state["picked"]}'

	async def test_aria_dom_state_toggle_stays_selected(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""An option that toggles its own aria-selected ends selected, and an already-selected peer is left alone."""
		result, state = await _select_remote(tools, browser_session, f'{base_url}/aria-dom-state')

		assert result.error is None, f'select_dropdown failed: {result.error}'
		assert state['clicks'] == 1, f'Expected the option click handler to run once, ran {state["clicks"]} times'
		assert state['selected'] == 'true', f'Expected Remote aria-selected="true", got {state["selected"]!r}'
		assert state['peerSelected'] == 'true', f'Multi-select peer Hybrid was deselected: {state["peerSelected"]!r}'

	async def test_custom_dom_state_toggle_stays_selected(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""A custom dropdown item that toggles its own class ends selected."""
		result, state = await _select_remote(tools, browser_session, f'{base_url}/custom-dom-state')

		assert result.error is None, f'select_dropdown failed: {result.error}'
		assert state['clicks'] == 1, f'Expected the option click handler to run once, ran {state["clicks"]} times'
		assert 'selected' in state['classes'].split(), f'Expected Remote to keep class "selected", got {state["classes"]!r}'

	async def test_disabled_option_is_refused(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""A disabled option is not activated and not reported as selected."""
		result, state = await _select_remote(tools, browser_session, f'{base_url}/aria-disabled')

		assert result.error is not None or 'disabled' in (result.extracted_content or '').lower(), (
			f'Expected select_dropdown to refuse a disabled option, got: {result.extracted_content!r}'
		)
		assert state['clicks'] == 0, f'Disabled option handler ran {state["clicks"]} times'
		assert state['selected'] == 'false', f'Disabled option was marked selected: {state["selected"]!r}'
