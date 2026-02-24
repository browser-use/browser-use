"""Test radio button click interactions with various label association patterns.

Verifies that the occlusion check correctly identifies label-input associations
so that CDP click dispatch works for radio buttons whose labels visually overlap them.
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools

# -- HTML fixtures --

RADIO_SIBLING_HTML = """
<!DOCTYPE html>
<html>
<head><title>Radio Sibling Label Test</title>
<style>
	.radio-group { display: flex; flex-direction: column; gap: 8px; }
	.radio-group input[type="radio"] { width: 16px; height: 16px; }
	.radio-group label { cursor: pointer; padding: 4px 8px; }
</style>
</head>
<body>
	<div class="radio-group">
		<div>
			<input type="radio" name="color" value="red" id="radio-red">
			<label for="radio-red">Red</label>
		</div>
		<div>
			<input type="radio" name="color" value="blue" id="radio-blue">
			<label for="radio-blue">Blue</label>
		</div>
		<div>
			<input type="radio" name="color" value="green" id="radio-green">
			<label for="radio-green">Green</label>
		</div>
	</div>
	<div id="result"></div>
	<script>
		document.querySelectorAll('input[name="color"]').forEach(r => {
			r.addEventListener('change', () => {
				document.getElementById('result').textContent = 'selected:' + r.value;
			});
		});
	</script>
</body>
</html>
"""

RADIO_WRAPPED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Radio Wrapped Label Test</title>
<style>
	.radio-group label { display: block; cursor: pointer; padding: 8px; }
</style>
</head>
<body>
	<div class="radio-group">
		<label><input type="radio" name="fruit" value="apple" id="radio-apple"> Apple</label>
		<label><input type="radio" name="fruit" value="banana" id="radio-banana"> Banana</label>
		<label><input type="radio" name="fruit" value="cherry" id="radio-cherry"> Cherry</label>
	</div>
	<div id="result"></div>
	<script>
		document.querySelectorAll('input[name="fruit"]').forEach(r => {
			r.addEventListener('change', () => {
				document.getElementById('result').textContent = 'selected:' + r.value;
			});
		});
	</script>
</body>
</html>
"""

RADIO_CUSTOM_HTML = """
<!DOCTYPE html>
<html>
<head><title>Radio Custom Styled Test</title>
<style>
	.radio-group { display: flex; flex-direction: column; gap: 8px; }
	.radio-group input[type="radio"] {
		appearance: none;
		-webkit-appearance: none;
		width: 20px;
		height: 20px;
		border: 2px solid #999;
		border-radius: 50%;
		position: relative;
	}
	.radio-group input[type="radio"]:checked {
		border-color: #007bff;
		background: #007bff;
	}
	.radio-group label {
		cursor: pointer;
		padding: 4px 8px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
</style>
</head>
<body>
	<div class="radio-group">
		<div>
			<input type="radio" name="size" value="small" id="radio-small">
			<label for="radio-small">Small</label>
		</div>
		<div>
			<input type="radio" name="size" value="medium" id="radio-medium">
			<label for="radio-medium">Medium</label>
		</div>
		<div>
			<input type="radio" name="size" value="large" id="radio-large">
			<label for="radio-large">Large</label>
		</div>
	</div>
	<div id="result"></div>
	<script>
		document.querySelectorAll('input[name="size"]').forEach(r => {
			r.addEventListener('change', () => {
				document.getElementById('result').textContent = 'selected:' + r.value;
			});
		});
	</script>
</body>
</html>
"""


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/radio-sibling').respond_with_data(RADIO_SIBLING_HTML, content_type='text/html')
	server.expect_request('/radio-wrapped').respond_with_data(RADIO_WRAPPED_HTML, content_type='text/html')
	server.expect_request('/radio-custom').respond_with_data(RADIO_CUSTOM_HTML, content_type='text/html')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
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
	return Tools()


async def _get_checked_and_result(browser_session: BrowserSession, input_id: str) -> tuple[bool, str]:
	"""Helper: returns (is_checked, result_div_text) via CDP."""
	cdp_session = await browser_session.get_or_create_cdp_session()
	sid = cdp_session.session_id

	checked_result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': f"document.getElementById('{input_id}').checked",
			'returnByValue': True,
		},
		session_id=sid,
	)
	is_checked = checked_result.get('result', {}).get('value', False)

	text_result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': "document.getElementById('result').textContent",
			'returnByValue': True,
		},
		session_id=sid,
	)
	result_text = text_result.get('result', {}).get('value', '')

	return is_checked, result_text


class TestRadioButtons:
	"""Test radio button clicks across label association patterns."""

	async def test_sibling_label_radio_click(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Click a radio whose sibling <label for=...> may occlude it."""
		await tools.navigate(url=f'{base_url}/radio-sibling', new_tab=False, browser_session=browser_session)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('radio-blue')
		assert idx is not None, 'Could not find radio-blue in selector map'

		result = await tools.click(index=idx, browser_session=browser_session)
		assert result.error is None, f'Click failed: {result.error}'

		is_checked, result_text = await _get_checked_and_result(browser_session, 'radio-blue')
		assert is_checked, 'radio-blue should be checked after click'
		assert 'selected:blue' in result_text, f'Change event not fired, result: {result_text}'

	async def test_wrapped_label_radio_click(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Click a radio wrapped inside its <label>."""
		await tools.navigate(url=f'{base_url}/radio-wrapped', new_tab=False, browser_session=browser_session)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('radio-banana')
		assert idx is not None, 'Could not find radio-banana in selector map'

		result = await tools.click(index=idx, browser_session=browser_session)
		assert result.error is None, f'Click failed: {result.error}'

		is_checked, result_text = await _get_checked_and_result(browser_session, 'radio-banana')
		assert is_checked, 'radio-banana should be checked after click'
		assert 'selected:banana' in result_text, f'Change event not fired, result: {result_text}'

	async def test_custom_styled_radio_click(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Click a CSS-customized radio (appearance:none) with sibling label."""
		await tools.navigate(url=f'{base_url}/radio-custom', new_tab=False, browser_session=browser_session)
		await browser_session.get_browser_state_summary()

		idx = await browser_session.get_index_by_id('radio-large')
		assert idx is not None, 'Could not find radio-large in selector map'

		result = await tools.click(index=idx, browser_session=browser_session)
		assert result.error is None, f'Click failed: {result.error}'

		is_checked, result_text = await _get_checked_and_result(browser_session, 'radio-large')
		assert is_checked, 'radio-large should be checked after click'
		assert 'selected:large' in result_text, f'Change event not fired, result: {result_text}'

	async def test_radio_group_switching(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Click one radio then another in the same group; first should uncheck."""
		await tools.navigate(url=f'{base_url}/radio-sibling', new_tab=False, browser_session=browser_session)
		await browser_session.get_browser_state_summary()

		# Click red first
		red_idx = await browser_session.get_index_by_id('radio-red')
		assert red_idx is not None
		result = await tools.click(index=red_idx, browser_session=browser_session)
		assert result.error is None, f'Click red failed: {result.error}'

		is_red_checked, _ = await _get_checked_and_result(browser_session, 'radio-red')
		assert is_red_checked, 'radio-red should be checked'

		# Re-fetch state so indices are current, then click green
		await browser_session.get_browser_state_summary()
		green_idx = await browser_session.get_index_by_id('radio-green')
		assert green_idx is not None
		result = await tools.click(index=green_idx, browser_session=browser_session)
		assert result.error is None, f'Click green failed: {result.error}'

		is_green_checked, result_text = await _get_checked_and_result(browser_session, 'radio-green')
		assert is_green_checked, 'radio-green should be checked'
		assert 'selected:green' in result_text

		# Verify red is now unchecked
		is_red_checked, _ = await _get_checked_and_result(browser_session, 'radio-red')
		assert not is_red_checked, 'radio-red should be unchecked after selecting green'
