"""
Test navigation edge cases: broken pages, slow loading, non-existing pages.

Tests verify that:
1. Agent can handle navigation to broken/malformed HTML pages
2. Agent can handle slow-loading pages without hanging
3. Agent can handle non-existing pages (404, connection refused, etc.)
4. Agent can recover and continue making LLM calls after encountering these issues

All tests use:
- max_steps=3 to limit agent actions
- 120s timeout to fail if test takes too long
- Mock LLM to verify agent can still make decisions after navigation errors

Usage:
	uv run pytest tests/ci/browser/test_navigation.py -v -s
"""

import asyncio
import time

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Response

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server for navigation tests."""
	server = HTTPServer()
	server.start()

	# Route 1: Broken/malformed HTML page
	server.expect_request('/broken').respond_with_data(
		'<html><head><title>Broken Page</title></head><body><h1>Incomplete HTML',
		content_type='text/html',
	)

	# Route 2: Valid page for testing navigation after error recovery
	server.expect_request('/valid').respond_with_data(
		'<html><head><title>Valid Page</title></head><body><h1>Valid Page</h1><p>This page loaded successfully</p></body></html>',
		content_type='text/html',
	)

	# Route 3: Slow loading page - delays 10 seconds before responding
	def slow_handler(request):
		time.sleep(10)
		return Response(
			'<html><head><title>Slow Page</title></head><body><h1>Slow Loading Page</h1><p>This page took 10 seconds to load</p></body></html>',
			content_type='text/html',
		)

	server.expect_request('/slow').respond_with_handler(slow_handler)

	# Route 4: 404 page
	server.expect_request('/notfound').respond_with_data(
		'<html><head><title>404 Not Found</title></head><body><h1>404 - Page Not Found</h1></body></html>',
		status=404,
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	"""Create a browser session for navigation tests."""
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


class TestNavigationEdgeCases:
	"""Test navigation error handling and recovery."""

	async def test_broken_page_navigation(self, browser_session, base_url):
		"""Test that agent can handle broken/malformed HTML and still make LLM calls."""

		# Create actions for the agent:
		# 1. Navigate to broken page
		# 2. Check if page exists
		# 3. Done
		actions = [
			f"""
			{{
				"thinking": "I need to navigate to the broken page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to broken page",
				"next_goal": "Navigate to broken page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/broken"
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "I should check if the page loaded",
				"evaluation_previous_goal": "Navigated to page",
				"memory": "Checking page state",
				"next_goal": "Verify page exists",
				"action": [
					{
						"done": {
							"text": "Page exists despite broken HTML",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/broken and check if page exists',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			assert len(history) > 0, 'Agent should have completed at least one step'
			# If agent completes successfully, it means LLM was called and functioning
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung on broken page')

	async def test_slow_loading_page(self, browser_session, base_url):
		"""Test that agent can handle slow-loading pages without hanging."""

		actions = [
			f"""
			{{
				"thinking": "I need to navigate to the slow page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to slow page",
				"next_goal": "Navigate to slow page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/slow"
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "The page loaded, even though it was slow",
				"evaluation_previous_goal": "Successfully navigated",
				"memory": "Page loaded after delay",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Slow page loaded successfully",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/slow and wait for it to load',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		start_time = time.time()
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			elapsed = time.time() - start_time

			assert len(history) > 0, 'Agent should have completed at least one step'
			assert elapsed >= 10, f'Agent should have waited for slow page (10s delay), but only took {elapsed:.1f}s'
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung on slow page')

	async def test_nonexisting_page_404(self, browser_session, base_url):
		"""Test that agent can handle 404 pages and still make LLM calls."""

		actions = [
			f"""
			{{
				"thinking": "I need to navigate to the non-existing page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to 404 page",
				"next_goal": "Navigate to non-existing page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/notfound"
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "I got a 404 error but the browser still works",
				"evaluation_previous_goal": "Navigated to 404 page",
				"memory": "Page not found",
				"next_goal": "Report that page does not exist",
				"action": [
					{
						"done": {
							"text": "Page does not exist (404 error)",
							"success": false
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {base_url}/notfound and check if page exists',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			assert len(history) > 0, 'Agent should have completed at least one step'
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung on 404 page')

	async def test_nonexisting_domain(self, browser_session):
		"""Test that agent can handle completely non-existing domains (connection refused)."""

		# Use a localhost port that's not listening
		nonexisting_url = 'http://localhost:59999/page'

		actions = [
			f"""
			{{
				"thinking": "I need to navigate to a non-existing domain",
				"evaluation_previous_goal": "Starting task",
				"memory": "Attempting to navigate",
				"next_goal": "Navigate to non-existing domain",
				"action": [
					{{
						"navigate": {{
							"url": "{nonexisting_url}"
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "The connection failed but I can still proceed",
				"evaluation_previous_goal": "Connection failed",
				"memory": "Domain does not exist",
				"next_goal": "Report failure",
				"action": [
					{
						"done": {
							"text": "Domain does not exist (connection refused)",
							"success": false
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'Navigate to {nonexisting_url} and check if it exists',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			assert len(history) > 0, 'Agent should have completed at least one step'
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent hung on non-existing domain')

	async def test_recovery_after_navigation_error(self, browser_session, base_url):
		"""Test that agent can recover and navigate to valid page after encountering error."""

		actions = [
			f"""
			{{
				"thinking": "First, I'll try the broken page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to broken page",
				"next_goal": "Navigate to broken page first",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/broken"
						}}
					}}
				]
			}}
			""",
			f"""
			{{
				"thinking": "That page was broken, let me try a valid page now",
				"evaluation_previous_goal": "Broken page loaded",
				"memory": "Now navigating to valid page",
				"next_goal": "Navigate to valid page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/valid"
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "The valid page loaded successfully after the broken one",
				"evaluation_previous_goal": "Valid page loaded",
				"memory": "Successfully recovered from error",
				"next_goal": "Complete task",
				"action": [
					{
						"done": {
							"text": "Successfully navigated to valid page after broken page",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)

		agent = Agent(
			task=f'First navigate to {base_url}/broken, then navigate to {base_url}/valid',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Run with timeout - should complete within 2 minutes
		try:
			history = await asyncio.wait_for(agent.run(max_steps=3), timeout=120)
			assert len(history) >= 2, 'Agent should have completed at least 2 steps (broken -> valid)'

			# Verify final page is the valid one
			final_url = await browser_session.get_current_page_url()
			assert final_url.endswith('/valid'), f'Final URL should be /valid, got {final_url}'

			# Verify agent completed successfully
			final_result = history.final_result()
			assert final_result is not None, 'Agent should return a final result'
		except TimeoutError:
			pytest.fail('Test timed out after 2 minutes - agent could not recover from broken page')
