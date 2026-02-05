"""Tests for search_page and find_elements actions."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools

# --- Fixtures ---


@pytest.fixture(scope='session')
def http_server():
	"""Test HTTP server serving pages for search/find tests."""
	server = HTTPServer()
	server.start()

	server.expect_request('/products').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Products</title></head>
		<body>
			<h1>Product Catalog</h1>
			<div id="main">
				<table class="products">
					<thead>
						<tr><th>Name</th><th>Price</th><th>Rating</th></tr>
					</thead>
					<tbody>
						<tr class="product-row"><td>Widget A</td><td>$29.99</td><td>4.5 stars</td></tr>
						<tr class="product-row"><td>Widget B</td><td>$49.99</td><td>4.2 stars</td></tr>
						<tr class="product-row"><td>Gadget C</td><td>$19.50</td><td>3.8 stars</td></tr>
						<tr class="product-row"><td>Gadget D</td><td>$99.00</td><td>4.9 stars</td></tr>
					</tbody>
				</table>
				<div class="pagination">
					<a href="/products?page=1" class="page-link active">1</a>
					<a href="/products?page=2" class="page-link">2</a>
					<a href="/products?page=3" class="page-link">3</a>
				</div>
			</div>
			<footer id="footer">
				<p>Best price guarantee on all items.</p>
				<p>Contact us at support@example.com</p>
			</footer>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/articles').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Articles</title></head>
		<body>
			<article id="post-1">
				<h2>Introduction to Python</h2>
				<p>Python is a versatile programming language used in web development, data science, and automation.</p>
				<a href="/articles/python" class="read-more">Read more</a>
			</article>
			<article id="post-2">
				<h2>JavaScript for Beginners</h2>
				<p>JavaScript powers the interactive web. Learn about DOM manipulation and event handling.</p>
				<a href="/articles/javascript" class="read-more">Read more</a>
			</article>
			<article id="post-3">
				<h2>Advanced CSS Techniques</h2>
				<p>Master CSS Grid, Flexbox, and custom properties for modern web layouts.</p>
				<a href="/articles/css" class="read-more">Read more</a>
			</article>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/empty').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Empty</title></head>
		<body>
			<div id="content"></div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/case-test').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Case Test</title></head>
		<body>
			<p>The Quick Brown Fox jumps over the lazy dog.</p>
			<p>QUICK BROWN FOX is an uppercase variant.</p>
			<p>quick brown fox is a lowercase variant.</p>
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


# --- Helper ---


async def _navigate_and_wait(tools, browser_session, url):
	"""Navigate to URL and wait for page load."""
	await tools.navigate(url=url, new_tab=False, browser_session=browser_session)
	await asyncio.sleep(0.5)


# --- search_page tests ---


class TestSearchPage:
	"""Tests for the search_page action."""

	async def test_literal_text_search(self, tools, browser_session, base_url):
		"""Literal text search finds matches with context."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern='Widget A', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert 'Widget A' in result.extracted_content
		assert '1 match' in result.extracted_content

	async def test_regex_search_prices(self, tools, browser_session, base_url):
		"""Regex search finds all price patterns on the page."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern=r'\$\d+\.\d{2}', regex=True, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		# Should find $29.99, $49.99, $19.50, $99.00
		assert '4 matches' in result.extracted_content
		assert '$29.99' in result.extracted_content
		assert '$49.99' in result.extracted_content

	async def test_css_scope_limits_search(self, tools, browser_session, base_url):
		"""css_scope limits search to elements within the selector."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		# Search only in footer
		result = await tools.search_page(pattern='price', css_scope='#footer', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		# "Best price guarantee" is in footer
		assert '1 match' in result.extracted_content
		assert 'guarantee' in result.extracted_content

	async def test_case_insensitive_default(self, tools, browser_session, base_url):
		"""Search is case-insensitive by default."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/case-test')

		result = await tools.search_page(pattern='quick brown fox', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		# Should match all three variants (Quick, QUICK, quick)
		assert '3 matches' in result.extracted_content

	async def test_case_sensitive(self, tools, browser_session, base_url):
		"""case_sensitive=True restricts to exact case."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/case-test')

		result = await tools.search_page(pattern='QUICK BROWN FOX', case_sensitive=True, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '1 match' in result.extracted_content

	async def test_max_results(self, tools, browser_session, base_url):
		"""max_results limits the number of returned matches."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern=r'\$\d+\.\d{2}', regex=True, max_results=2, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		# Total should still show 4, but only 2 are displayed
		assert '4 matches' in result.extracted_content
		assert 'Increase max_results' in result.extracted_content

	async def test_no_matches(self, tools, browser_session, base_url):
		"""No matches returns a clean message, not an error."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern='xyznonexistent', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert 'No matches found' in result.extracted_content

	async def test_element_path_in_results(self, tools, browser_session, base_url):
		"""Matches include the element path for context."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern='guarantee', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		# Should show element path containing footer
		assert '(in' in result.extracted_content

	async def test_invalid_css_scope(self, tools, browser_session, base_url):
		"""Invalid css_scope returns a clear error."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern='test', css_scope='#nonexistent-scope', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'scope' in result.error.lower() or 'not found' in result.error.lower()

	async def test_memory_set(self, tools, browser_session, base_url):
		"""long_term_memory is set with match count summary."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.search_page(pattern='Widget', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.long_term_memory is not None
		assert 'Widget' in result.long_term_memory
		assert 'match' in result.long_term_memory


# --- find_elements tests ---


class TestFindElements:
	"""Tests for the find_elements action."""

	async def test_basic_selector(self, tools, browser_session, base_url):
		"""Basic CSS selector returns correct elements."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='tr.product-row', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '4 elements' in result.extracted_content
		assert 'Widget A' in result.extracted_content
		assert 'Gadget D' in result.extracted_content

	async def test_attribute_extraction(self, tools, browser_session, base_url):
		"""attributes parameter extracts specific attributes from elements."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(
			selector='a.page-link',
			attributes=['href', 'class'],
			browser_session=browser_session,
		)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '3 elements' in result.extracted_content
		assert 'href=' in result.extracted_content
		assert '/products?page=' in result.extracted_content

	async def test_max_results_limiting(self, tools, browser_session, base_url):
		"""max_results limits displayed elements while showing total count."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='tr.product-row', max_results=2, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '4 elements' in result.extracted_content
		assert 'Showing 2 of 4' in result.extracted_content

	async def test_no_matching_elements(self, tools, browser_session, base_url):
		"""No matches returns a clean message, not an error."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='div.nonexistent', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert 'No elements found' in result.extracted_content

	async def test_invalid_selector(self, tools, browser_session, base_url):
		"""Invalid CSS selector returns a clear error, not a crash."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='[[[invalid', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'selector' in result.error.lower() or 'invalid' in result.error.lower()

	async def test_include_text_false(self, tools, browser_session, base_url):
		"""include_text=False omits text content from results."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/articles')

		result = await tools.find_elements(selector='article', include_text=False, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '3 elements' in result.extracted_content
		# Text content should not appear (no article body text)
		# But the tag and children count should still be present
		assert '<article>' in result.extracted_content

	async def test_nested_selectors(self, tools, browser_session, base_url):
		"""Nested CSS selectors (child combinator) work correctly."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/articles')

		result = await tools.find_elements(
			selector='article a.read-more',
			attributes=['href'],
			browser_session=browser_session,
		)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '3 elements' in result.extracted_content
		assert '/articles/python' in result.extracted_content
		assert '/articles/javascript' in result.extracted_content
		assert '/articles/css' in result.extracted_content

	async def test_children_count(self, tools, browser_session, base_url):
		"""Elements show children count."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='table.products thead tr', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert '1 element' in result.extracted_content
		# The header row has 3 <th> children
		assert '3 children' in result.extracted_content

	async def test_memory_set(self, tools, browser_session, base_url):
		"""long_term_memory is set with element count summary."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/products')

		result = await tools.find_elements(selector='tr.product-row', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.long_term_memory is not None
		assert '4 element' in result.long_term_memory

	async def test_empty_page(self, tools, browser_session, base_url):
		"""Works on a nearly empty page without errors."""
		await _navigate_and_wait(tools, browser_session, f'{base_url}/empty')

		result = await tools.find_elements(selector='p', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None
		assert result.extracted_content is not None
		assert 'No elements found' in result.extracted_content


# --- Registration tests ---


class TestRegistration:
	"""Test that new actions are properly registered."""

	async def test_search_page_registered(self, tools):
		"""search_page is in the default action registry."""
		assert 'search_page' in tools.registry.registry.actions

	async def test_find_elements_registered(self, tools):
		"""find_elements is in the default action registry."""
		assert 'find_elements' in tools.registry.registry.actions

	async def test_excluded_actions(self):
		"""New actions can be excluded via exclude_actions."""
		excluded_tools = Tools(exclude_actions=['search_page', 'find_elements'])
		assert 'search_page' not in excluded_tools.registry.registry.actions
		assert 'find_elements' not in excluded_tools.registry.registry.actions
		# Other actions still present
		assert 'navigate' in excluded_tools.registry.registry.actions
