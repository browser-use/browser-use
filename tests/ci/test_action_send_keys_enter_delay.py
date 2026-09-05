"""Non-regression test for https://github.com/browser-use/browser-use/issues/5573

send_keys previously used substring matching to detect Enter/Return, so text
containing those substrings (e.g. "center", "enterprise") incorrectly triggered
the 100ms post-Enter navigation delay. The fix tracks whether an actual Enter
key was dispatched instead.
"""

import asyncio
import time

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/send-keys-test').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Send Keys Test</title></head>
		<body>
			<input id="target" type="text" />
		</body>
		</html>
		""",
		content_type='text/html',
	)

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


class TestSendKeysEnterDelay:
	async def test_text_containing_enter_substring_no_extra_delay(
		self, tools: Tools, browser_session: BrowserSession, base_url: str
	):
		"""Typing 'center' must not trigger the Enter-specific 100ms delay."""
		await tools.navigate(url=f'{base_url}/send-keys-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)

		input_index = await browser_session.get_index_by_id('target')
		assert input_index is not None, 'Could not find target input'

		# Focus the input first
		await tools.click(index=input_index, browser_session=browser_session)

		start = time.monotonic()
		await tools.send_keys(keys='center', browser_session=browser_session)
		elapsed = time.monotonic() - start

		# 6 chars * 10ms each = 60ms base, plus overhead. Without the bug fix
		# this would add an extra 100ms from the false Enter detection.
		# Allow generous margin for CI but catch the 100ms penalty.
		assert elapsed < 0.5, f'send_keys("center") took {elapsed:.3f}s, suspected false Enter delay'

	async def test_actual_enter_key_still_waits(self, tools: Tools, browser_session: BrowserSession, base_url: str):
		"""Sending 'Enter' must still trigger the post-Enter delay."""
		await tools.navigate(url=f'{base_url}/send-keys-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.3)

		input_index = await browser_session.get_index_by_id('target')
		assert input_index is not None, 'Could not find target input'

		await tools.click(index=input_index, browser_session=browser_session)

		start = time.monotonic()
		await tools.send_keys(keys='Enter', browser_session=browser_session)
		elapsed = time.monotonic() - start

		assert elapsed >= 0.1, f'send_keys("Enter") took {elapsed:.3f}s, Enter delay was not applied'
