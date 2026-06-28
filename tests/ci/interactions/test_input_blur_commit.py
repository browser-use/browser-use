"""Test that typing into a field commits the value by moving focus out (issue #5054).

Many UIs only commit/validate a field's value on real focus loss. In particular,
React 17+ implements `onBlur` on top of the native `focusout` event. A dispatched
`Event('blur')` runs `addEventListener('blur')` handlers but does NOT move focus and
does NOT produce `focusout`, so the framework never sees the value — the agent types,
clicks Save, and the value is dropped.

These tests assert:
- A field that commits on `focusout` receives the typed value (the fix calls a real
  `element.blur()`, which fires native blur + focusout).
- After typing, focus actually leaves a plain field.
- Autocomplete/combobox fields are NOT blurred, so their suggestion dropdown stays open
  (the agent needs focus to click a suggestion).
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server with blur-commit test pages."""
	server = HTTPServer()
	server.start()

	# Page 1: value only commits on focusout (mirrors React's onBlur, which listens on
	# the native focusout event). A dispatched Event('blur') would not trigger this.
	server.expect_request('/commit-on-blur').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Commit On Blur Test</title></head>
		<body>
			<input id="field" type="text" />
			<div id="committed">UNCOMMITTED</div>
			<script>
				const field = document.getElementById('field');
				field.addEventListener('focusout', function () {
					document.getElementById('committed').textContent = field.value;
				});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 2: combobox that records whether it ever lost focus.
	server.expect_request('/combobox-keep-focus').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Combobox Keep Focus Test</title></head>
		<body>
			<input id="combo" type="text" role="combobox"
				aria-autocomplete="list" aria-controls="opts" aria-expanded="false" />
			<ul id="opts" role="listbox" style="display:none;">
				<li role="option">Option A</li>
				<li role="option">Option B</li>
			</ul>
			<div id="lostfocus">no</div>
			<script>
				document.getElementById('combo').addEventListener('focusout', function () {
					document.getElementById('lostfocus').textContent = 'yes';
				});
			</script>
		</body>
		</html>
		""",
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


async def _read(browser_session: BrowserSession, expression: str) -> str:
	"""Evaluate a JS expression in the page and return its value."""
	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': expression, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value', '')


class TestInputBlurCommit:
	"""Typing should commit the value by moving focus out of the field (issue #5054)."""

	async def test_value_committed_on_blur(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""A field that commits on focusout should receive the typed value after input()."""
		await tools.navigate(url=f'{base_url}/commit-on-blur', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('field')
		assert idx is not None, 'Could not find input field'

		result = await tools.input(index=idx, text='hello', browser_session=browser_session)
		assert isinstance(result, ActionResult)
		assert result.error is None, f'Input action failed: {result.error}'

		committed = await _read(browser_session, "document.getElementById('committed').textContent")
		assert committed == 'hello', (
			f'Value was not committed on blur — got committed="{committed}". '
			'The field never received a real focusout (issue #5054).'
		)

	async def test_plain_field_loses_focus_after_typing(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""After typing into a plain field, focus should no longer be on that field."""
		await tools.navigate(url=f'{base_url}/commit-on-blur', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('field')
		assert idx is not None, 'Could not find input field'

		await tools.input(index=idx, text='world', browser_session=browser_session)

		active_id = await _read(browser_session, "(document.activeElement && document.activeElement.id) || ''")
		assert active_id != 'field', 'Plain field should have lost focus after typing (real blur did not fire)'

	async def test_autocomplete_field_keeps_focus(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""A combobox/autocomplete field must NOT be blurred, or its suggestion dropdown closes."""
		await tools.navigate(url=f'{base_url}/combobox-keep-focus', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('combo')
		assert idx is not None, 'Could not find combobox input'

		await tools.input(index=idx, text='ab', browser_session=browser_session)

		lost_focus = await _read(browser_session, "document.getElementById('lostfocus').textContent")
		active_id = await _read(browser_session, "(document.activeElement && document.activeElement.id) || ''")
		assert lost_focus == 'no', 'Combobox should not be blurred (dropdown would close before the agent can pick)'
		assert active_id == 'combo', f'Combobox should retain focus, but activeElement is "{active_id}"'
