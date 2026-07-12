"""
Test navigation on heavy/slow-loading pages (e.g. e-commerce PDPs).

Reproduces the issue where navigating to heavy pages like stevemadden.com PDPs
fails due to NavigateToUrlEvent timing out.

Usage:
	uv run pytest tests/ci/browser/test_navigation_slow_pages.py -v -s
"""

import asyncio
import time

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Response

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from tests.ci.conftest import create_mock_llm

HEAVY_PDP_HTML = """
<!DOCTYPE html>
<html>
<head><title>Frosting Black Velvet - Steve Madden</title></head>
<body>
	<h1>FROSTING</h1>
	<p class="price">$129.95</p>
	<button id="add-to-cart">ADD TO BAG</button>
</body>
</html>
"""


@pytest.fixture(scope='session')
def heavy_page_server():
	server = HTTPServer()
	server.start()

	def slow_initial_response(request):
		time.sleep(6)
		return Response(HEAVY_PDP_HTML, content_type='text/html')

	server.expect_request('/slow-server-pdp').respond_with_handler(slow_initial_response)

	def redirect_step1(request):
		return Response('', status=302, headers={'Location': f'http://{server.host}:{server.port}/redirect-step2'})

	def redirect_step2(request):
		return Response('', status=302, headers={'Location': f'http://{server.host}:{server.port}/redirect-final'})

	def redirect_final(request):
		time.sleep(3)
		return Response(HEAVY_PDP_HTML, content_type='text/html')

	server.expect_request('/redirect-step1').respond_with_handler(redirect_step1)
	server.expect_request('/redirect-step2').respond_with_handler(redirect_step2)
	server.expect_request('/redirect-final').respond_with_handler(redirect_final)

	server.expect_request('/fast-dom-slow-load').respond_with_data(HEAVY_PDP_HTML, content_type='text/html')
	server.expect_request('/quick-page').respond_with_data(
		'<html><body><h1>Quick Page</h1></body></html>', content_type='text/html'
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def heavy_base_url(heavy_page_server):
	return f'http://{heavy_page_server.host}:{heavy_page_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()


def _nav_actions(url: str, msg: str = 'Done') -> list[str]:
	"""Helper to build a navigate-then-done action sequence."""
	return [
		f"""
		{{
			"thinking": "Navigate to the page",
			"evaluation_previous_goal": "Starting task",
			"memory": "Navigating",
			"next_goal": "Navigate",
			"action": [{{"navigate": {{"url": "{url}"}}}}]
		}}
		""",
		f"""
		{{
			"thinking": "Page loaded",
			"evaluation_previous_goal": "Navigation completed",
			"memory": "Page loaded",
			"next_goal": "Done",
			"action": [{{"done": {{"text": "{msg}", "success": true}}}}]
		}}
		""",
	]


class TestHeavyPageNavigation:
	async def test_slow_server_response_completes(self, browser_session, heavy_base_url):
		"""Navigation succeeds even when server takes 6s to respond."""
		url = f'{heavy_base_url}/slow-server-pdp'
		agent = Agent(
			task=f'Navigate to {url}',
			llm=create_mock_llm(actions=_nav_actions(url)),
			browser_session=browser_session,
		)
		start = time.time()
		history = await asyncio.wait_for(agent.run(max_steps=3), timeout=60)
		assert len(history) > 0
		assert history.final_result() is not None
		assert time.time() - start >= 5, 'Should have waited for slow server'

	async def test_redirect_chain_completes(self, browser_session, heavy_base_url):
		"""Navigation handles multi-step redirects + slow final response."""
		url = f'{heavy_base_url}/redirect-step1'
		agent = Agent(
			task=f'Navigate to {url}',
			llm=create_mock_llm(actions=_nav_actions(url)),
			browser_session=browser_session,
		)
		history = await asyncio.wait_for(agent.run(max_steps=3), timeout=60)
		assert len(history) > 0
		assert history.final_result() is not None

	async def test_navigate_event_accepts_domcontentloaded(self, browser_session, heavy_base_url):
		"""NavigateToUrlEvent with fast page should complete quickly via DOMContentLoaded/load."""
		url = f'{heavy_base_url}/fast-dom-slow-load'
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await asyncio.wait_for(event, timeout=15)
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def test_recovery_after_slow_navigation(self, browser_session, heavy_base_url):
		"""Agent recovers and navigates to a fast page after a slow one."""
		slow_url = f'{heavy_base_url}/slow-server-pdp'
		quick_url = f'{heavy_base_url}/quick-page'
		actions = [
			f"""
			{{
				"thinking": "Navigate to slow page",
				"evaluation_previous_goal": "Starting",
				"memory": "Going to slow page",
				"next_goal": "Navigate",
				"action": [{{"navigate": {{"url": "{slow_url}"}}}}]
			}}
			""",
			f"""
			{{
				"thinking": "Now navigate to quick page",
				"evaluation_previous_goal": "Slow page loaded",
				"memory": "Trying quick page",
				"next_goal": "Navigate",
				"action": [{{"navigate": {{"url": "{quick_url}"}}}}]
			}}
			""",
			"""
			{
				"thinking": "Both done",
				"evaluation_previous_goal": "Quick page loaded",
				"memory": "Recovery successful",
				"next_goal": "Done",
				"action": [{"done": {"text": "Recovery succeeded", "success": true}}]
			}
			""",
		]
		agent = Agent(
			task='Navigate to slow then quick page',
			llm=create_mock_llm(actions=actions),
			browser_session=browser_session,
		)
		history = await asyncio.wait_for(agent.run(max_steps=4), timeout=90)
		assert len(history) >= 2
		assert history.final_result() is not None

	async def test_event_timeout_sufficient_for_heavy_pages(self, browser_session):
		"""event_timeout should be >= 30s to handle slow servers + redirect chains."""
		event = NavigateToUrlEvent(url='http://example.com')
		assert event.event_timeout is not None
		assert event.event_timeout >= 30.0, f'event_timeout={event.event_timeout}s is too low for heavy pages (need >= 30s)'
