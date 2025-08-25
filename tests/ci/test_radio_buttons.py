# @file purpose: Test radio button interactions and serialization in browser-use
"""
Test file for verifying radio button clicking functionality and DOM serialization.

This test creates a simple HTML page with radio buttons, sends an agent to click them,
and logs the final agent message to show how radio buttons are represented in the serializer.

The serialization shows radio buttons as:
[index]<input type=radio name=groupname value=optionvalue checked=true/false />

Usage:
    uv run pytest tests/ci/test_radio_buttons.py -v -s
"""

from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Read the HTML file content
	html_file = Path(__file__).parent / 'test_radio_buttons.html'
	with open(html_file, 'r') as f:
		html_content = f.read()

	# Add route for radio buttons test page
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
	"""Create and provide a Browser instance with security disabled."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


class TestRadioButtons:
	"""Test cases for radio button interactions."""

	async def test_radio_button_clicking(self, browser_session, base_url):
		"""Test that agent can click radio buttons by checking for secret message."""

		task = f"Go to {base_url}/radio-test and click on the 'Blue' radio button and the 'Dog' radio button. After clicking both buttons, look for any text message that appears on the page and report exactly what you see."

		agent = Agent(
			task=task,
			browser_session=browser_session,
			max_actions_per_step=5,
			flash_mode=True,
		)

		# Run the agent
		history = await agent.run(max_steps=8)

		# Check if the secret message appears in the final response
		secret_found = False
		final_response = history.final_result()

		if final_response and 'SECRET_SUCCESS_12345' in final_response:
			secret_found = True
			print('\n✅ SUCCESS: Secret message found! Radio buttons were clicked correctly.')

		assert secret_found, (
			"Secret message 'SECRET_SUCCESS_12345' should be present, indicating both Blue and Dog radio buttons were clicked. Actual response: "
			+ str(final_response)
		)

		print(f'\n🎉 Test completed successfully! Agent completed {len(history)} steps and found the secret message.')
