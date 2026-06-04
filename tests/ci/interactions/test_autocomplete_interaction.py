"""Test autocomplete/combobox field detection, value readback, and input clearing.

Tests cover:
- Value mismatch detection when JS rewrites input value
- Combobox field detection (role=combobox + aria-autocomplete)
- Datalist field detection (input with list attribute)
- No false positives on plain inputs
- Sensitive data skips value verification
- Pre-filled input clearing (clear=True default)
- Pre-filled input appending (clear=False)
- Concatenation auto-retry when clear fails
- Autocomplete delay before next action
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
	"""Create and provide a test HTTP server with autocomplete test pages."""
	server = HTTPServer()
	server.start()

	# Page 1: Input with JS that rewrites value on change (simulates autocomplete replacing text)
	server.expect_request('/autocomplete-rewrite').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Autocomplete Rewrite Test</title></head>
		<body>
			<input id="search" type="text" />
			<script>
				const input = document.getElementById('search');
				input.addEventListener('change', function() {
					// Simulate autocomplete rewriting the value
					this.value = 'REWRITTEN_' + this.value;
				});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 2: Input with role=combobox + aria-autocomplete=list + aria-controls + listbox
	server.expect_request('/combobox-field').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Combobox Field Test</title></head>
		<body>
			<div>
				<input id="combo" type="text" role="combobox"
					aria-autocomplete="list" aria-controls="suggestions-list"
					aria-expanded="false" />
				<ul id="suggestions-list" role="listbox" style="display:none;">
					<li role="option">Option A</li>
					<li role="option">Option B</li>
				</ul>
			</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 3: Input with list attribute pointing to a datalist
	server.expect_request('/datalist-field').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Datalist Field Test</title></head>
		<body>
			<input id="city" type="text" list="suggestions" />
			<datalist id="suggestions">
				<option value="New York">
				<option value="Los Angeles">
				<option value="Chicago">
			</datalist>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 4: Plain input with no autocomplete attributes
	server.expect_request('/normal-input').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Normal Input Test</title></head>
		<body>
			<input id="plain" type="text" placeholder="Just a normal input" />
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 5: Pre-filled input to test clear=True behavior
	server.expect_request('/prefilled-input').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Pre-filled Input Test</title></head>
		<body>
			<input id="prefilled" type="text" value="old value" />
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Page 6: Input where clear fails — input event listener restores old text
	# Simulates a framework-controlled input where clearing triggers re-render with old state
	server.expect_request('/sticky-input').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Sticky Input Test</title></head>
		<body>
			<input id="sticky" type="text" value="prefix_" />
			<script>
				var el = document.getElementById('sticky');
				var clearAttempts = 0;
				// Intercept value clears: restore old value on first two clears
				// (simulates framework re-rendering with stale state)
				el.addEventListener('input', function() {
					if (el.value === '' && clearAttempts < 2) {
						clearAttempts++;
						el.value = 'prefix_';
					}
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


class TestAutocompleteInteraction:
	"""Test autocomplete/combobox detection and value readback."""

	async def test_value_mismatch_detected(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a field whose JS rewrites the value on change. Assert the ActionResult notes the mismatch."""
		await tools.navigate(url=f'{base_url}/autocomplete-rewrite', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		input_index = await browser_session.get_index_by_id('search')
		assert input_index is not None, 'Could not find search input'

		result = await tools.input(index=input_index, text='hello', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'differs from typed text' in result.extracted_content, (
			f'Expected mismatch note in extracted_content, got: {result.extracted_content}'
		)

	async def test_combobox_field_detected(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a combobox field. Assert the ActionResult includes autocomplete guidance."""
		await tools.navigate(url=f'{base_url}/combobox-field', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		combo_index = await browser_session.get_index_by_id('combo')
		assert combo_index is not None, 'Could not find combobox input'

		result = await tools.input(index=combo_index, text='test', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'autocomplete field' in result.extracted_content, (
			f'Expected autocomplete guidance in extracted_content, got: {result.extracted_content}'
		)

	async def test_datalist_field_detected(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a datalist-backed field. Assert the ActionResult includes autocomplete guidance."""
		await tools.navigate(url=f'{base_url}/datalist-field', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		city_index = await browser_session.get_index_by_id('city')
		assert city_index is not None, 'Could not find datalist input'

		result = await tools.input(index=city_index, text='New', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'autocomplete field' in result.extracted_content, (
			f'Expected autocomplete guidance in extracted_content, got: {result.extracted_content}'
		)

	async def test_normal_input_no_false_positive(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a plain input. Assert the ActionResult does NOT contain autocomplete guidance."""
		await tools.navigate(url=f'{base_url}/normal-input', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		plain_index = await browser_session.get_index_by_id('plain')
		assert plain_index is not None, 'Could not find plain input'

		result = await tools.input(index=plain_index, text='hello', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'autocomplete field' not in result.extracted_content, (
			f'Got false positive autocomplete guidance on plain input: {result.extracted_content}'
		)

	async def test_sensitive_data_skips_value_verification(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type sensitive data into the rewrite field. Assert no 'differs from typed text' note appears."""
		await tools.navigate(url=f'{base_url}/autocomplete-rewrite', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		input_index = await browser_session.get_index_by_id('search')
		assert input_index is not None, 'Could not find search input'

		# Use tools.act() with sensitive_data to trigger the sensitive code path
		result = await tools.input(
			index=input_index,
			text='secret123',
			browser_session=browser_session,
			sensitive_data={'password': 'secret123'},
		)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'differs from typed text' not in result.extracted_content, (
			f'Sensitive data should not show value mismatch: {result.extracted_content}'
		)

	async def test_prefilled_input_cleared_by_default(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a pre-filled input with clear=True (default). Field should contain only the new text."""
		await tools.navigate(url=f'{base_url}/prefilled-input', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('prefilled')
		assert idx is not None, 'Could not find prefilled input'

		result = await tools.input(index=idx, text='new value', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None, f'Input action failed: {result.error}'

		# Read back the actual DOM value via CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		readback = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('prefilled').value"},
			session_id=cdp_session.session_id,
		)
		actual = readback.get('result', {}).get('value', '')
		assert actual == 'new value', f'Expected "new value", got "{actual}" — clear=True did not remove old text'

	async def test_prefilled_input_append_with_clear_false(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a pre-filled input with clear=False. Field should contain old + new text."""
		await tools.navigate(url=f'{base_url}/prefilled-input', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('prefilled')
		assert idx is not None, 'Could not find prefilled input'

		result = await tools.input(index=idx, text=' appended', clear=False, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None, f'Input action failed: {result.error}'

		# Read back the actual DOM value via CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		readback = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('prefilled').value"},
			session_id=cdp_session.session_id,
		)
		actual = readback.get('result', {}).get('value', '')
		assert 'old value' in actual and 'appended' in actual, f'Expected old text + appended text, got "{actual}"'

	async def test_concatenation_retry_on_sticky_field(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Type into a field where clearing is resisted by JS. The retry should fix the value."""
		await tools.navigate(url=f'{base_url}/sticky-input', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('sticky')
		assert idx is not None, 'Could not find sticky input'

		result = await tools.input(index=idx, text='typed_text', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None, f'Input action failed: {result.error}'

		# The retry mechanism uses a native setter to bypass the event listener.
		# Read back the final DOM value.
		cdp_session = await browser_session.get_or_create_cdp_session()
		readback = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('sticky').value"},
			session_id=cdp_session.session_id,
		)
		actual = readback.get('result', {}).get('value', '')
		# The retry should have set the value to just "typed_text" via the native setter.
		# Even if the event listener fires on the retry's dispatched events, the native setter
		# bypasses instance-level interception. The value may or may not be perfect depending
		# on how the JS listener interacts, but it should not be "prefix_typed_text" (raw concatenation).
		assert actual != 'prefix_typed_text', f'Got raw concatenation "{actual}" — retry should have prevented this'

	async def test_combobox_field_adds_delay(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Typing into a combobox (role=combobox) field should take >= 400ms due to the mechanical delay."""
		import time

		await tools.navigate(url=f'{base_url}/combobox-field', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()
		combo_idx = await browser_session.get_index_by_id('combo')
		assert combo_idx is not None

		t0 = time.monotonic()
		await tools.input(index=combo_idx, text='hi', browser_session=browser_session)
		duration = time.monotonic() - t0

		# The 400ms sleep is a hard floor — total duration must exceed it
		assert duration >= 0.4, f'Combobox delay not present: input took only {duration:.3f}s (expected >= 0.4s)'

	async def test_datalist_field_no_delay(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Native datalist fields should NOT get the 400ms delay — browser handles them instantly."""
		import time

		await tools.navigate(url=f'{base_url}/datalist-field', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)
		await browser_session.get_browser_state_summary()
		city_idx = await browser_session.get_index_by_id('city')
		assert city_idx is not None

		t0 = time.monotonic()
		await tools.input(index=city_idx, text='Chi', browser_session=browser_session)
		duration = time.monotonic() - t0

		# Datalist fields should complete without the 400ms tax.
		# Normal typing for 3 chars takes well under 400ms.
		assert duration < 0.4, f'Datalist field got unexpected delay: {duration:.3f}s (should be < 0.4s)'
