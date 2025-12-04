# @file purpose: Test audio interpretation action in browser-use
"""
Test file for verifying interpret_audio action functionality.

This test creates a simple HTML page with an audio element and verifies
that the interpret_audio action can find and process it.

Usage:
	uv run pytest tests/ci/interactions/test_action_interpret_audio.py -v -s
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Simple HTML page with audio element
	html_content = """
	<html>
	<head><title>Audio Test Page</title></head>
	<body>
		<h1>Audio Test</h1>
		<audio controls>
			<source src="/test-audio.mp3" type="audio/mpeg">
		</audio>
	</body>
	</html>
	"""

	server.expect_request('/audio-test').respond_with_data(
		html_content,
		content_type='text/html',
	)

	# Mock MP3 file (minimal valid MP3 header)
	server.expect_request('/test-audio.mp3').respond_with_data(
		b'\xff\xfb\x90\x00' + b'\x00' * 100,  # Minimal MP3 header + padding
		content_type='audio/mpeg',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance."""
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


@pytest.fixture(scope='function')
def tools():
	"""Create and provide a Tools instance."""
	return Tools()


class TestInterpretAudio:
	"""Test cases for interpret_audio action."""

	async def test_registry_contains_interpret_audio(self, tools):
		"""Test that interpret_audio is registered in the action registry."""
		# Check that interpret_audio is in the registry
		assert 'interpret_audio' in tools.registry.registry.actions, (
			f'interpret_audio should be registered. Found actions: {list(tools.registry.registry.actions.keys())}'
		)

		# Verify it has the required properties
		interpret_audio_action = tools.registry.registry.actions['interpret_audio']
		assert interpret_audio_action.function is not None
		assert interpret_audio_action.description is not None

	async def test_action_has_correct_parameters(self, tools):
		"""Test that interpret_audio action has expected parameters."""
		interpret_audio_action = tools.registry.registry.actions['interpret_audio']

		# Check parameter model has expected fields
		param_fields = interpret_audio_action.param_model.model_fields
		assert 'index' in param_fields, 'Should have index parameter'
		assert 'summarize' in param_fields, 'Should have summarize parameter'

		# Check default values
		assert param_fields['summarize'].default is True, 'summarize should default to True'
