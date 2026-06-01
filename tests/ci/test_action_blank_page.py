"""Tests for AGI-497: SPA/JS-heavy page renders blank.

Covers:
1. Skeleton screen detection — many elements but near-zero text triggers a warning in page_stats.
2. Navigate reload fallback — empty-body page triggers retry cycle but ultimately succeeds
   (no error) because the DOM root exists. Error is only returned when _root is None.
"""

import asyncio
import tempfile

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	"""Session-scoped HTTP server for blank-page tests."""
	server = HTTPServer()
	server.start()

	# --- skeleton page: 30 empty divs, essentially no text ---
	skeleton_html = '<!DOCTYPE html><html><head><title>Loading...</title></head><body>'
	skeleton_html += ''.join(f'<div class="skeleton-item skeleton-{i}"></div>' for i in range(30))
	skeleton_html += '</body></html>'
	server.expect_request('/skeleton').respond_with_data(skeleton_html, content_type='text/html')

	# --- rich page: real text content (should NOT be flagged as skeleton) ---
	server.expect_request('/products').respond_with_data(
		"""<!DOCTYPE html>
<html><head><title>Products</title></head>
<body>
	<h1>Product Catalog</h1>
	<div class="product"><h2>Widget A</h2><p>Price: $29.99 - A sturdy widget for everyday use.</p></div>
	<div class="product"><h2>Widget B</h2><p>Price: $49.99 - Premium widget with extended warranty.</p></div>
	<div class="product"><h2>Gadget C</h2><p>Price: $19.50 - Compact gadget, fits in your pocket.</p></div>
	<div class="product"><h2>Gadget D</h2><p>Price: $99.00 - Professional-grade gadget for power users.</p></div>
</body>
</html>""",
		content_type='text/html',
	)

	# --- empty body page: body is always empty ---
	# Used to test the navigate retry cycle. _root is NOT None (body element exists),
	# so navigate retries but ultimately succeeds (no error).
	server.expect_request('/always-empty').respond_with_data(
		'<html><body></body></html>',
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
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


@pytest.fixture(scope='function')
def tools():
	return Tools()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _navigate(tools, browser_session, url):
	"""Navigate to url and give the page a moment to settle."""
	await tools.navigate(url=url, new_tab=False, browser_session=browser_session)
	await asyncio.sleep(0.5)


def _make_prompt(state):
	"""Build an AgentMessagePrompt from a BrowserStateSummary using a temp dir for FileSystem."""
	from browser_use.agent.prompts import AgentMessagePrompt
	from browser_use.filesystem.file_system import FileSystem

	tmp_dir = tempfile.mkdtemp(prefix='browseruse_test_')
	file_system = FileSystem(base_dir=tmp_dir, create_default_files=False)
	return AgentMessagePrompt(
		browser_state_summary=state,
		file_system=file_system,
	)


# ---------------------------------------------------------------------------
# Test 1: Skeleton screen detection in _extract_page_statistics()
# ---------------------------------------------------------------------------


class TestSkeletonScreenDetection:
	"""_extract_page_statistics() should flag pages with many elements but very little text."""

	async def test_skeleton_page_low_text_chars(self, tools, browser_session, base_url):
		"""Skeleton page: total_elements > 20 but text_chars < total_elements * 5."""
		await _navigate(tools, browser_session, f'{base_url}/skeleton')

		state = await browser_session.get_browser_state_summary(include_screenshot=False)
		prompt = _make_prompt(state)
		page_stats = prompt._extract_page_statistics()

		assert page_stats['total_elements'] > 20, f'Expected >20 elements for skeleton page, got {page_stats["total_elements"]}'
		assert page_stats['text_chars'] < page_stats['total_elements'] * 5, (
			f'Expected text_chars ({page_stats["text_chars"]}) < total_elements*5 '
			f'({page_stats["total_elements"] * 5}) for skeleton page'
		)

	async def test_skeleton_page_description_contains_warning(self, tools, browser_session, base_url):
		"""_get_browser_state_description() includes skeleton warning for placeholder pages."""
		await _navigate(tools, browser_session, f'{base_url}/skeleton')

		state = await browser_session.get_browser_state_summary(include_screenshot=False)
		prompt = _make_prompt(state)
		description = prompt._get_browser_state_description()

		assert 'skeleton' in description.lower() or 'placeholder' in description.lower(), (
			f'Expected skeleton/placeholder warning in description, got:\n{description[:500]}'
		)

	async def test_rich_page_not_flagged_as_skeleton(self, tools, browser_session, base_url):
		"""A page with real text content should NOT be flagged as skeleton."""
		await _navigate(tools, browser_session, f'{base_url}/products')

		state = await browser_session.get_browser_state_summary(include_screenshot=False)
		prompt = _make_prompt(state)
		page_stats = prompt._extract_page_statistics()
		description = prompt._get_browser_state_description()

		# Rich page should have substantial text relative to element count
		assert page_stats['text_chars'] >= page_stats['total_elements'] * 5, (
			f'Rich page should have text_chars ({page_stats["text_chars"]}) >= total_elements*5 '
			f'({page_stats["total_elements"] * 5})'
		)
		# No skeleton warning in description
		assert 'skeleton' not in description.lower() and 'placeholder' not in description.lower(), (
			'Rich page should NOT produce a skeleton warning'
		)


# ---------------------------------------------------------------------------
# Test 2: Navigate reload fallback — empty-body page triggers retry but succeeds
# ---------------------------------------------------------------------------


class TestNavigateReloadFallback:
	"""Navigate retries when llm_representation() is empty, but only errors when _root is None."""

	async def test_empty_body_page_retries_then_succeeds(self, tools, browser_session, base_url):
		"""
		Navigating to a page with an empty body triggers the health-check retry cycle
		(empty llm_representation) but ultimately succeeds (no error) because the page
		HAS a DOM root (_root is not None — the body element exists and is visible).

		The error path only fires when _root is None (truly unloadable pages like those
		blocked by anti-bot or returning empty HTTP responses), which avoids false positives
		on image-only or other non-interactive-but-valid pages.
		"""
		empty_url = f'{base_url}/always-empty'

		# Triggers: health check -> 3s wait -> reload -> 5s wait -> check _root -> not None -> success
		result = await tools.navigate(url=empty_url, new_tab=False, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		# No error — the body IS a valid DOM root, just visually empty.
		# Skeleton detection (in AgentMessagePrompt._get_browser_state_description) warns the LLM.
		assert result.error is None, f'Expected no error for empty-body page, got: {result.error}'
