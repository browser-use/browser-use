# @file purpose: Test radio button interactions and serialization in browser-use
"""
Test file for verifying radio button clicking functionality and DOM serialization.

This test creates a simple HTML page with radio buttons, sends an agent to click them,
and logs the final agent message to show how radio buttons are represented in the serializer.

The serialization shows radio buttons as:
[index]<input type=radio name=groupname value=optionvalue checked=true/false />

Usage:
    uv run pytest tests/ci/test_radio_buttons.py -v -s

Notes:
- This test requires a real LLM API key (BROWSER_USE_API_KEY).
- It is automatically skipped in CI environments or if the key is not set.
"""

import os
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile

# ======================================================================
# FIXTURE SETUP
# ======================================================================


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	html_file = Path(__file__).parent / 'test_radio_buttons.html'
	with open(html_file, encoding='utf-8') as f:
		html_content = f.read()

	server.expect_request('/radio-test').respond_with_data(
		html_content,
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
	"""Create and provide a headless Browser session."""
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


# ======================================================================
# TEST CLASS
# ======================================================================


@pytest.mark.skipif(
	os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true' or not os.getenv('BROWSER_USE_API_KEY'),
	reason='Requires a real BROWSER_USE_API_KEY, skipped in CI or missing key.',
)
class TestRadioButtons:
	"""Test cases for radio button interactions."""

	async def test_radio_button_clicking(self, browser_session, base_url):
		"""
		Test that the agent can click radio buttons by verifying the secret message.
		"""

		task = (
			f"Go to {base_url}/radio-test and click on the 'Blue' radio button and "
			f"the 'Dog' radio button. After clicking both, find any text message "
			f'that appears and report exactly what you see.'
		)

		# Initialize the Agent with the current browser session
		agent = Agent(
			task=task,
			browser_session=browser_session,
			max_actions_per_step=5,
			flash_mode=True,
		)

		# Run the agent
		history = await agent.run(max_steps=8)
		final_response = history.final_result()

		# Validate the expected success message
		if final_response and 'SECRET_SUCCESS_12345' in final_response:
			print('\n✅ SUCCESS: Secret message found! Radio buttons were clicked correctly.')
			success = True
		else:
			success = False

		assert success, f"Expected secret message 'SECRET_SUCCESS_12345' was not found. Actual final response: {final_response}"

		print(f'\n🎉 Test completed successfully! Agent took {len(history)} steps and found the secret message.')
