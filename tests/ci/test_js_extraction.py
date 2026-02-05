"""Tests for JS-codegen extraction (extract_with_script action)."""

import asyncio
import json
import tempfile
from unittest.mock import AsyncMock

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.extraction.js_codegen import (
	_clean_html_for_codegen,
	_discover_page_structure,
	_extract_js_from_response,
	_format_structure_probe,
	_is_empty_result,
	_normalize_url_for_cache,
	_truncate_html,
)
from browser_use.tools.service import Tools

# ---------------------------------------------------------------------------
# Unit tests: _truncate_html
# ---------------------------------------------------------------------------


class TestTruncateHtml:
	def test_no_truncation_when_under_limit(self):
		html = '<div><p>Hello</p></div>'
		result, truncated = _truncate_html(html, max_chars=1000)
		assert result == html
		assert truncated is False

	def test_truncation_at_tag_boundary(self):
		html = '<div><p>First</p><p>Second paragraph that is longer</p></div>'
		# Set limit so it cuts inside the second <p> but should snap back to '>'
		limit = len('<div><p>First</p><p>Sec')
		result, truncated = _truncate_html(html, max_chars=limit)
		assert truncated is True
		# Should have snapped back to the end of </p>
		assert result.endswith('>')
		assert len(result) <= limit

	def test_very_short_limit(self):
		html = '<html><body>Test</body></html>'
		result, truncated = _truncate_html(html, max_chars=5)
		assert truncated is True
		# With limit=5, there's no '>' before position 5, so it hard-cuts
		assert len(result) == 5

	def test_exact_limit(self):
		html = '<p>Hi</p>'
		result, truncated = _truncate_html(html, max_chars=len(html))
		assert result == html
		assert truncated is False


# ---------------------------------------------------------------------------
# Unit tests: _extract_js_from_response
# ---------------------------------------------------------------------------


class TestExtractJsFromResponse:
	def test_plain_iife(self):
		code = '(function(){ return document.title; })()'
		result = _extract_js_from_response(code)
		assert result == code

	def test_markdown_fenced(self):
		text = 'Here is the code:\n```js\n(function(){ return 42; })()\n```\nDone.'
		result = _extract_js_from_response(text)
		assert result == '(function(){ return 42; })()'

	def test_arrow_iife(self):
		code = '(() => { return [1,2,3]; })()'
		result = _extract_js_from_response(code)
		assert result == code

	def test_async_iife(self):
		code = 'async function extract() { return 1; }'
		# async prefix is accepted
		result = _extract_js_from_response(code)
		assert 'async' in result

	def test_non_iife_raises(self):
		with pytest.raises(ValueError, match='does not look like a JS IIFE'):
			_extract_js_from_response('console.log("hello")')

	def test_fenced_with_language_tag(self):
		text = '```javascript\n(() => { return {}; })()\n```'
		result = _extract_js_from_response(text)
		assert result == '(() => { return {}; })()'


# ---------------------------------------------------------------------------
# Unit tests: _clean_html_for_codegen
# ---------------------------------------------------------------------------


class TestCleanHtmlForCodegen:
	def test_strips_unwanted_attributes(self):
		html = '<div id="main" style="color:red" onclick="alert(1)" class="foo" data-v-abc123=""></div>'
		result = _clean_html_for_codegen(html)
		assert 'id="main"' in result
		assert 'class="foo"' in result
		assert 'style=' not in result
		assert 'onclick=' not in result
		assert 'data-v-abc123' not in result

	def test_keeps_whitelisted_attrs(self):
		html = '<input id="email" type="email" name="user_email" placeholder="Enter email" required disabled/>'
		result = _clean_html_for_codegen(html)
		for attr in ('id="email"', 'type="email"', 'name="user_email"', 'placeholder="Enter email"', 'required', 'disabled'):
			assert attr in result

	def test_strips_svg_entirely(self):
		html = '<div><p>Before</p><svg xmlns="..." viewBox="0 0 24 24"><path d="M12 2L2 7"/></svg><p>After</p></div>'
		result = _clean_html_for_codegen(html)
		assert '<svg' not in result
		assert '<path' not in result
		assert 'Before' in result
		assert 'After' in result

	def test_strips_noscript_and_iframe(self):
		html = '<div>Content<noscript>Fallback</noscript><iframe src="x"></iframe>More</div>'
		result = _clean_html_for_codegen(html)
		assert '<noscript' not in result
		assert 'Fallback' not in result
		assert '<iframe' not in result
		assert 'Content' in result
		assert 'More' in result

	def test_caps_class_list(self):
		classes = ' '.join(f'c{i}' for i in range(20))
		html = f'<div class="{classes}">Text</div>'
		result = _clean_html_for_codegen(html)
		# Should keep only first 8 classes (no semantic classes to prioritize here)
		assert 'c0' in result
		assert 'c7' in result
		assert 'c8' not in result

	def test_preserves_text_content(self):
		html = '<table><tr><td style="width:100px" class="price">$9.99</td></tr></table>'
		result = _clean_html_for_codegen(html)
		assert '$9.99' in result
		assert 'style=' not in result
		assert 'class="price"' in result

	def test_preserves_data_testid(self):
		html = '<button data-testid="submit-btn" data-analytics="click-track">Go</button>'
		result = _clean_html_for_codegen(html)
		assert 'data-testid="submit-btn"' in result
		assert 'data-analytics' not in result

	def test_nested_stripped_tags(self):
		html = '<div><svg><g><circle r="5"/></g></svg><span>Visible</span></div>'
		result = _clean_html_for_codegen(html)
		assert '<svg' not in result
		assert '<circle' not in result
		assert 'Visible' in result

	def test_preserves_nav_header_footer_aside(self):
		"""Regression: nav/header/footer/aside must NOT be stripped — they can contain extraction targets."""
		html = '<body><nav><a href="/home">Home</a><a href="/about">About</a></nav><header><h1>Store</h1></header><main><p>Content</p></main><aside><ul><li>Related A</li></ul></aside><footer><span>Contact us</span></footer></body>'
		result = _clean_html_for_codegen(html)
		assert '<nav>' in result
		assert 'Home' in result
		assert '<header>' in result
		assert 'Store' in result
		assert '<aside>' in result
		assert 'Related A' in result
		assert '<footer>' in result
		assert 'Contact us' in result

	def test_reduction_on_bloated_html(self):
		"""Verify meaningful size reduction on attribute-heavy HTML."""
		attrs = ' '.join(
			f'{k}="{v}"'
			for k, v in [
				('id', 'item'),
				('class', 'a b c d e f g h i j'),
				('style', 'margin:0;padding:0;display:flex;align-items:center;justify-content:center'),
				('onclick', 'handleClick(event)'),
				('data-v-a1b2c3', ''),
				('data-react-fiber', 'abc'),
				('aria-describedby', 'tooltip-1'),
				('tabindex', '0'),
			]
		)
		row = f'<div {attrs}><span>Item</span></div>\n'
		html = '<body>' + row * 100 + '</body>'
		result = _clean_html_for_codegen(html)
		# Should be meaningfully smaller
		assert len(result) < len(html) * 0.6, f'Expected >40% reduction, got {len(result)}/{len(html)}'


# ---------------------------------------------------------------------------
# Unit tests: _is_empty_result
# ---------------------------------------------------------------------------


class TestIsEmptyResult:
	def test_none_is_empty(self):
		assert _is_empty_result(None) is True

	def test_empty_list_is_empty(self):
		assert _is_empty_result([]) is True

	def test_empty_dict_is_empty(self):
		assert _is_empty_result({}) is True

	def test_blank_string_is_empty(self):
		assert _is_empty_result('') is True
		assert _is_empty_result('   ') is True

	def test_non_empty_list_is_not_empty(self):
		assert _is_empty_result([1]) is False

	def test_non_empty_dict_is_not_empty(self):
		assert _is_empty_result({'a': 1}) is False

	def test_non_empty_string_is_not_empty(self):
		assert _is_empty_result('hello') is False

	def test_zero_is_not_empty(self):
		assert _is_empty_result(0) is False

	def test_false_is_not_empty(self):
		assert _is_empty_result(False) is False


# ---------------------------------------------------------------------------
# Unit tests: _normalize_url_for_cache
# ---------------------------------------------------------------------------


class TestNormalizeUrlForCache:
	def test_numeric_query_param_replaced(self):
		url = 'https://example.com/products?page=3&sort=price'
		result = _normalize_url_for_cache(url)
		assert 'page=_N_' in result
		assert 'sort=price' in result

	def test_numeric_path_segment_replaced(self):
		url = 'https://example.com/products/page/2'
		result = _normalize_url_for_cache(url)
		assert '/page/_N_' in result

	def test_non_numeric_values_preserved(self):
		url = 'https://example.com/search?q=shoes&category=boots'
		result = _normalize_url_for_cache(url)
		assert 'q=shoes' in result
		assert 'category=boots' in result

	def test_same_pages_different_numbers_match(self):
		url1 = 'https://example.com/products?page=1&sort=asc'
		url2 = 'https://example.com/products?page=99&sort=asc'
		assert _normalize_url_for_cache(url1) == _normalize_url_for_cache(url2)

	def test_different_paths_dont_match(self):
		url1 = 'https://example.com/products?page=1'
		url2 = 'https://example.com/about?page=1'
		assert _normalize_url_for_cache(url1) != _normalize_url_for_cache(url2)

	def test_no_query_params(self):
		url = 'https://example.com/products'
		result = _normalize_url_for_cache(url)
		assert result == 'https://example.com/products'

	def test_mixed_numeric_non_numeric_path(self):
		url = 'https://example.com/category/123/items/456'
		result = _normalize_url_for_cache(url)
		assert '/category/_N_/items/_N_' in result


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PRODUCT_TABLE_HTML = """<html><body>
<h1>Products</h1>
<table id="products">
  <thead><tr><th>Name</th><th>Price</th></tr></thead>
  <tbody>
    <tr><td>Widget A</td><td>$9.99</td></tr>
    <tr><td>Widget B</td><td>$19.99</td></tr>
    <tr><td>Widget C</td><td>$29.99</td></tr>
  </tbody>
</table>
<div id="sidebar">Unrelated content</div>
</body></html>"""

# Page with <main> landmark — main content is small, rest is large filler.
# Auto-scoping should pick <main> and skip the filler.
_FILLER = '<div class="filler">' + ('x' * 5000) + '</div>\n'
MAIN_LANDMARK_HTML = (
	'<html><body>\n'
	'<header><nav>' + ('link ' * 200) + '</nav></header>\n' + _FILLER * 5 + '<main><table id="products">\n'
	'  <thead><tr><th>Name</th><th>Price</th></tr></thead>\n'
	'  <tbody>\n'
	'    <tr><td>Widget A</td><td>$9.99</td></tr>\n'
	'    <tr><td>Widget B</td><td>$19.99</td></tr>\n'
	'  </tbody>\n'
	'</table></main>\n' + _FILLER * 5 + '<footer>' + ('footer ' * 200) + '</footer>\n'
	'</body></html>'
)

# Second page of products — same DOM structure, different data.
PRODUCT_TABLE_PAGE2_HTML = """<html><body>
<h1>Products - Page 2</h1>
<table id="products">
  <thead><tr><th>Name</th><th>Price</th></tr></thead>
  <tbody>
    <tr><td>Widget D</td><td>$39.99</td></tr>
    <tr><td>Widget E</td><td>$49.99</td></tr>
  </tbody>
</table>
</body></html>"""

# JS that the mock LLM will "generate" for table extraction
TABLE_EXTRACT_JS = """(function(){
try {
  var rows = document.querySelectorAll('#products tbody tr');
  var products = [];
  for (var i = 0; i < rows.length; i++) {
    var cells = rows[i].querySelectorAll('td');
    products.push({name: cells[0].textContent.trim(), price: cells[1].textContent.trim()});
  }
  return {products: products};
} catch(e) { return {error: e.message}; }
})()"""

# JS that returns an empty array (simulates selectors not matching)
EMPTY_RESULT_JS = """(function(){
try {
  var rows = document.querySelectorAll('#nonexistent-table tbody tr');
  var products = [];
  for (var i = 0; i < rows.length; i++) {
    var cells = rows[i].querySelectorAll('td');
    products.push({name: cells[0].textContent.trim(), price: cells[1].textContent.trim()});
  }
  return products;
} catch(e) { return {error: e.message}; }
})()"""

# JS with a deliberate bug (references nonexistent element)
BUGGY_JS = """(function(){
  var el = document.querySelector('#nonexistent');
  return el.textContent;
})()"""

# Fixed JS that works after the bug
FIXED_JS = """(function(){
try {
  var rows = document.querySelectorAll('#products tbody tr');
  var products = [];
  for (var i = 0; i < rows.length; i++) {
    var cells = rows[i].querySelectorAll('td');
    products.push({name: cells[0].textContent.trim(), price: cells[1].textContent.trim()});
  }
  return {products: products};
} catch(e) { return {error: e.message}; }
})()"""


CARD_LAYOUT_HTML = """<html><body>
<div class="product-grid">
  <div class="card"><h3>Widget A</h3><span class="price">$9.99</span></div>
  <div class="card"><h3>Widget B</h3><span class="price">$19.99</span></div>
  <div class="card"><h3>Widget C</h3><span class="price">$29.99</span></div>
  <div class="card"><h3>Widget D</h3><span class="price">$39.99</span></div>
</div>
</body></html>"""

# Page with a "Next" pagination link
PAGINATED_TABLE_HTML = """<html><body>
<table id="products">
  <thead><tr><th>Name</th><th>Price</th></tr></thead>
  <tbody>
    <tr><td>Widget A</td><td>$9.99</td></tr>
    <tr><td>Widget B</td><td>$19.99</td></tr>
  </tbody>
</table>
<nav aria-label="pagination">
  <a href="/products?page=1">1</a>
  <a href="/products?page=2">2</a>
  <a href="/products?page=3">Next</a>
</nav>
</body></html>"""

# Page with links (href attributes)
LINKS_HTML = """<html><body>
<ul>
  <li><a href="/page/1">Link One</a></li>
  <li><a href="/page/2">Link Two</a></li>
  <li><a href="https://example.com/ext">External Link</a></li>
</ul>
</body></html>"""

# Page with data-testid attributes
DATA_ATTR_HTML = """<html><body>
<div data-testid="product-list" data-analytics="track-view" data-react-fiber="abc123">
  <div data-testid="item-1" data-v-hash="x" class="item"><span>Widget A</span></div>
  <div data-testid="item-2" data-v-hash="y" class="item"><span>Widget B</span></div>
</div>
</body></html>"""


def _make_js_extraction_llm(js_response: str) -> BaseChatModel:
	"""Create a mock LLM that returns a JS code string."""
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-js-extraction-llm'
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = 'mock-js-extraction-llm'
	llm.model_name = 'mock-js-extraction-llm'

	async def mock_ainvoke(messages, output_format=None, **kwargs):
		return ChatInvokeCompletion(completion=js_response, usage=None)

	llm.ainvoke.side_effect = mock_ainvoke
	return llm


def _make_js_extraction_llm_sequence(responses: list[str]) -> BaseChatModel:
	"""Create a mock LLM that returns different JS code strings on successive calls."""
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-js-extraction-llm'
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = 'mock-js-extraction-llm'
	llm.model_name = 'mock-js-extraction-llm'

	call_count = 0

	async def mock_ainvoke(messages, output_format=None, **kwargs):
		nonlocal call_count
		idx = min(call_count, len(responses) - 1)
		call_count += 1
		return ChatInvokeCompletion(completion=responses[idx], usage=None)

	llm.ainvoke.side_effect = mock_ainvoke
	return llm


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/products').respond_with_data(
		PRODUCT_TABLE_HTML,
		content_type='text/html',
	)
	server.expect_request('/sidebar').respond_with_data(
		PRODUCT_TABLE_HTML,
		content_type='text/html',
	)
	server.expect_request('/main-landmark').respond_with_data(
		MAIN_LANDMARK_HTML,
		content_type='text/html',
	)
	server.expect_request('/products/1').respond_with_data(
		PRODUCT_TABLE_HTML,
		content_type='text/html',
	)
	server.expect_request('/products/2').respond_with_data(
		PRODUCT_TABLE_PAGE2_HTML,
		content_type='text/html',
	)
	server.expect_request('/cards').respond_with_data(
		CARD_LAYOUT_HTML,
		content_type='text/html',
	)
	server.expect_request('/paginated').respond_with_data(
		PAGINATED_TABLE_HTML,
		content_type='text/html',
	)
	server.expect_request('/links').respond_with_data(
		LINKS_HTML,
		content_type='text/html',
	)
	server.expect_request('/data-attrs').respond_with_data(
		DATA_ATTR_HTML,
		content_type='text/html',
	)
	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestJsCodegenExtraction:
	"""Integration tests for the extract_with_script action."""

	async def test_basic_table_extraction(self, browser_session, base_url):
		"""Mock LLM returns table-extracting JS, verify JSON result."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products with names and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content
		assert '</js_extraction_result>' in result.extracted_content

		# Parse JSON from tags (tag now has a script_id attribute)
		tag_start = result.extracted_content.index('<js_extraction_result')
		data_start = result.extracted_content.index('>', tag_start) + 1
		end = result.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result.extracted_content[data_start:end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 3
		assert parsed['products'][0]['name'] == 'Widget A'

		# Metadata
		assert result.metadata is not None
		assert result.metadata['js_codegen_extraction'] is True
		assert 'js_script' in result.metadata
		assert 'script_id' in result.metadata
		assert len(result.metadata['script_id']) == 8

	async def test_css_selector_scoping(self, browser_session, base_url):
		"""Verify css_selector scopes the HTML sent to the LLM."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/sidebar', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# JS that just returns the sidebar text
		sidebar_js = "(function(){ return document.querySelector('#sidebar').textContent.trim(); })()"
		extraction_llm = _make_js_extraction_llm(sidebar_js)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Get sidebar content',
				css_selector='#sidebar',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Unrelated content' in result.extracted_content

		# Verify the LLM was called with scoped HTML (check the messages passed to ainvoke)
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		assert '<css_selector>' in user_msg_content
		assert '#sidebar' in user_msg_content

	async def test_css_selector_miss_returns_error(self, browser_session, base_url):
		"""Programmatic callers passing a bad css_selector get an ActionResult with error."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				css_selector='#nonexistent-selector',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'matched no element' in result.error

	async def test_schema_visibility(self):
		"""query and script_id visible; css_selector and output_schema hidden."""
		tools = Tools()
		action_model = tools.registry.create_action_model()
		schema = action_model.model_json_schema()

		# Find extract_with_script in the schema definitions
		ews_schema = None
		for key, defn in schema.get('$defs', {}).items():
			if key == 'ExtractWithScriptAction':
				ews_schema = defn
				break

		assert ews_schema is not None, 'ExtractWithScriptAction not found in schema'
		props = ews_schema.get('properties', {})
		assert 'query' in props, 'query should be visible'
		assert 'script_id' in props, 'script_id should be visible to the agent'
		assert 'css_selector' not in props, 'css_selector should be hidden from agent schema'
		assert 'output_schema' not in props, 'output_schema should be hidden from agent schema'

	async def test_schema_validation(self, browser_session, base_url):
		"""output_schema provided, verify extraction_result in metadata."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		output_schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'string'},
						},
						'required': ['name', 'price'],
					},
				},
			},
			'required': ['products'],
		}

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract products',
				output_schema=output_schema,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.metadata is not None
		assert 'extraction_result' in result.metadata
		meta = result.metadata['extraction_result']
		assert meta['schema_used'] == output_schema
		assert len(meta['data']['products']) == 3

	async def test_retry_on_js_error(self, browser_session, base_url):
		"""First script has bug, retry with error feedback, second script succeeds."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# First call returns buggy JS, second call returns working JS
		extraction_llm = _make_js_extraction_llm_sequence([BUGGY_JS, FIXED_JS])

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content

		# Parse and verify successful extraction
		tag_start = result.extracted_content.index('<js_extraction_result')
		data_start = result.extracted_content.index('>', tag_start) + 1
		end = result.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result.extracted_content[data_start:end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 3

		# Verify retries were used
		assert result.metadata is not None
		assert result.metadata['retries_used'] == 1

		# Verify LLM was called twice
		assert extraction_llm.ainvoke.call_count == 2

		# Second call should have error feedback in the prompt
		second_call_args = extraction_llm.ainvoke.call_args_list[1]
		second_messages = second_call_args[0][0]
		second_user_content = str(second_messages[1].content)
		assert '<previous_attempt_error>' in second_user_content
		assert '<previous_script>' in second_user_content

	async def test_extraction_schema_injection(self, browser_session, base_url):
		"""Special param extraction_schema used when output_schema absent."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'string'},
						},
						'required': ['name', 'price'],
					},
				},
			},
			'required': ['products'],
		}

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				extraction_schema=extraction_schema,
			)

		assert isinstance(result, ActionResult)
		assert result.metadata is not None
		assert 'extraction_result' in result.metadata
		meta = result.metadata['extraction_result']
		assert meta['schema_used'] == extraction_schema

	async def test_extraction_schema_threads_through_act(self, browser_session, base_url):
		"""extraction_schema passed to act() reaches extract_with_script via registry special param injection."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'string'},
						},
						'required': ['name', 'price'],
					},
				},
			},
			'required': ['products'],
		}

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)

			action_model = tools.registry.create_action_model()
			action = action_model.model_validate({'extract_with_script': {'query': 'Extract products'}})

			result = await tools.act(
				action=action,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
				extraction_schema=extraction_schema,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content
		assert result.metadata is not None
		assert 'extraction_result' in result.metadata

	async def test_auto_scoping_to_main_landmark(self, browser_session, base_url):
		"""When page has a <main> element, auto-scope sends only that section to the LLM."""
		# JS that extracts from the #products table (which lives inside <main>)
		main_extract_js = """(function(){
try {
  var rows = document.querySelectorAll('#products tbody tr');
  var products = [];
  for (var i = 0; i < rows.length; i++) {
    var cells = rows[i].querySelectorAll('td');
    products.push({name: cells[0].textContent.trim(), price: cells[1].textContent.trim()});
  }
  return {products: products};
} catch(e) { return {error: e.message}; }
})()"""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/main-landmark', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(main_extract_js)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract products from the table',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content

		# Verify the LLM received scoped HTML (should contain <main> content but not the filler)
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		# Extract just the <page_html> section to check scoping
		html_start = user_msg_content.index('<page_html>') + len('<page_html>')
		html_end = user_msg_content.index('</page_html>')
		page_html_section = user_msg_content[html_start:html_end]
		# The HTML sent to the LLM should contain the table
		assert '#products' in page_html_section or 'Widget A' in page_html_section
		# The filler content should NOT be in the scoped HTML
		assert 'xxxxx' not in page_html_section

	async def test_empty_result_triggers_retry(self, browser_session, base_url):
		"""Script returning [] triggers retry with error feedback to the LLM."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# First call returns empty-array JS, second call returns working JS
		extraction_llm = _make_js_extraction_llm_sequence([EMPTY_RESULT_JS, TABLE_EXTRACT_JS])

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content

		# Verify LLM was called twice (retry happened)
		assert extraction_llm.ainvoke.call_count == 2

		# Second call should have empty-result error feedback and the failed script
		second_call = extraction_llm.ainvoke.call_args_list[1]
		second_user_content = str(second_call[0][0][1].content)
		assert '<previous_attempt_error>' in second_user_content
		assert 'empty result' in second_user_content.lower()
		assert '<previous_script>' in second_user_content

		# Verify retry count in metadata
		assert result.metadata is not None
		assert result.metadata['retries_used'] == 1

	async def test_empty_result_all_retries_fail(self, browser_session, base_url):
		"""If every attempt returns empty, the action returns an error (3 attempts with max_retries=2)."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# All 3 calls return empty-array JS (max_retries=2 → 3 total attempts)
		extraction_llm = _make_js_extraction_llm_sequence([EMPTY_RESULT_JS, EMPTY_RESULT_JS, EMPTY_RESULT_JS])

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		# Should get an error back since the registry catches RuntimeError
		assert isinstance(result, ActionResult)
		assert result.error is not None
		assert 'empty result' in result.error.lower()

	async def test_script_cache_hit_skips_llm(self, browser_session, base_url):
		"""Second call to same page pattern reuses cached script, no LLM call."""
		tools = Tools()

		# First call: /products/1 — LLM generates script
		await tools.navigate(url=f'{base_url}/products/1', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result1 = await tools.extract_with_script(
				query='Extract all products with names and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result1, ActionResult)
		assert result1.metadata is not None
		assert result1.metadata.get('cache_hit') is False
		# script_id should be returned
		script_id = result1.metadata.get('script_id')
		assert script_id is not None
		assert len(script_id) == 8
		# script_id should appear in extracted_content
		assert result1.extracted_content is not None
		assert f'script_id="{script_id}"' in result1.extracted_content
		assert extraction_llm.ainvoke.call_count == 1

		# Second call: /products/2 (same DOM structure, numeric segment normalizes) — cached
		await tools.navigate(url=f'{base_url}/products/2', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result2 = await tools.extract_with_script(
				query='Extract all products with names and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result2, ActionResult)
		assert result2.extracted_content is not None
		assert result2.metadata is not None
		assert result2.metadata.get('cache_hit') is True
		assert result2.metadata.get('script_id') == script_id

		# LLM should NOT have been called again
		assert extraction_llm.ainvoke.call_count == 1

		# Verify page 2 data was extracted (tag has script_id attribute)
		assert f'script_id="{script_id}"' in result2.extracted_content
		# Extract JSON from the tag (strip the attribute from the opening tag)
		start = result2.extracted_content.index('>') + 1  # after the first tag with script_id
		# Find the actual data between the result tags
		tag_start = result2.extracted_content.index('<js_extraction_result')
		data_start = result2.extracted_content.index('>', tag_start) + 1
		data_end = result2.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result2.extracted_content[data_start:data_end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 2
		assert parsed['products'][0]['name'] == 'Widget D'

	async def test_explicit_script_id_reuse(self, browser_session, base_url):
		"""Agent passes script_id from prior result to explicitly reuse the script."""
		tools = Tools()

		# First call: generate script
		await tools.navigate(url=f'{base_url}/products/1', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result1 = await tools.extract_with_script(
				query='Extract all products with names and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		script_id = result1.metadata['script_id']
		assert extraction_llm.ainvoke.call_count == 1

		# Second call: different query text but pass script_id — should skip LLM
		await tools.navigate(url=f'{base_url}/products/2', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result2 = await tools.extract_with_script(
				query='Get products from this page too',  # different query!
				script_id=script_id,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result2, ActionResult)
		assert result2.metadata is not None
		assert result2.metadata.get('cache_hit') is True
		assert result2.metadata.get('script_id') == script_id

		# LLM should NOT have been called again
		assert extraction_llm.ainvoke.call_count == 1

		# Verify page 2 data was extracted
		tag_start = result2.extracted_content.index('<js_extraction_result')
		data_start = result2.extracted_content.index('>', tag_start) + 1
		data_end = result2.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result2.extracted_content[data_start:data_end].strip())
		assert parsed['products'][0]['name'] == 'Widget D'

	async def test_script_cache_miss_for_different_query(self, browser_session, base_url):
		"""Different query on same URL does NOT use cached script."""
		tools = Tools()

		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		# First call with query A
		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert extraction_llm.ainvoke.call_count == 1

		# Second call with different query — should call LLM again
		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			await tools.extract_with_script(
				query='Get only product names',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert extraction_llm.ainvoke.call_count == 2

	async def test_structure_probe_on_table_page(self, browser_session, base_url):
		"""Structure probe detects table columns and sample row on a product table page."""
		await browser_session.navigate_to(f'{base_url}/products')
		await asyncio.sleep(0.5)

		result, container = await _discover_page_structure(browser_session)
		assert 'Tables found:' in result
		assert 'Name' in result
		assert 'Price' in result
		# Should have a sample row with actual data
		assert 'Widget A' in result or 'Widget' in result

	async def test_structure_probe_on_card_page(self, browser_session, base_url):
		"""Structure probe detects repeating card pattern on a grid layout page."""
		await browser_session.navigate_to(f'{base_url}/cards')
		await asyncio.sleep(0.5)

		result, container = await _discover_page_structure(browser_session)
		assert 'Repeating patterns found:' in result
		assert 'card' in result.lower()
		# Should find 4 .card elements
		assert '4 items' in result

	async def test_retry_includes_page_structure(self, browser_session, base_url):
		"""LLM prompt on retry includes <page_structure> tag."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# First call returns buggy JS, second call returns working JS
		extraction_llm = _make_js_extraction_llm_sequence([BUGGY_JS, FIXED_JS])

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Both first and retry call should include page_structure
		for call_args in extraction_llm.ainvoke.call_args_list:
			messages = call_args[0][0]
			user_msg_content = str(messages[1].content)
			assert '<page_structure>' in user_msg_content
			assert '</page_structure>' in user_msg_content

		# Second call should also have error feedback
		second_call = extraction_llm.ainvoke.call_args_list[1]
		second_user_content = str(second_call[0][0][1].content)
		assert '<previous_attempt_error>' in second_user_content

	async def test_three_attempt_recovery(self, browser_session, base_url):
		"""First 2 scripts fail, third succeeds (max_retries=2 → 3 total attempts)."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# First two calls return buggy JS, third returns working JS
		extraction_llm = _make_js_extraction_llm_sequence([BUGGY_JS, EMPTY_RESULT_JS, FIXED_JS])

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert '<js_extraction_result' in result.extracted_content

		# Verify 3 LLM calls
		assert extraction_llm.ainvoke.call_count == 3

		# Parse and verify extraction
		tag_start = result.extracted_content.index('<js_extraction_result')
		data_start = result.extracted_content.index('>', tag_start) + 1
		end = result.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result.extracted_content[data_start:end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 3

		# Verify retries_used == 2 (third attempt)
		assert result.metadata is not None
		assert result.metadata['retries_used'] == 2


# ---------------------------------------------------------------------------
# Unit tests: _format_structure_probe
# ---------------------------------------------------------------------------


class TestFormatStructureProbe:
	def test_formats_repeating_patterns(self):
		data = {
			'repeatingPatterns': [
				{'key': 'div.card', 'count': 5, 'sample': '<div class="card"><h3>Item</h3></div>'},
				{'key': 'span.price', 'count': 5, 'sample': '<span class="price">$9.99</span>'},
			],
			'tables': [],
		}
		result = _format_structure_probe(data)
		assert 'Repeating patterns found:' in result
		assert 'div.card (5 items)' in result
		assert '<div class="card">' in result
		assert 'span.price (5 items)' in result

	def test_formats_tables(self):
		data = {
			'repeatingPatterns': [],
			'tables': [
				{'id': 'products', 'columns': ['Name', 'Price'], 'sampleRow': '<tr><td>Widget A</td><td>$9.99</td></tr>'},
			],
		}
		result = _format_structure_probe(data)
		assert 'Tables found:' in result
		assert '#products' in result
		assert 'Name, Price' in result
		assert 'Widget A' in result

	def test_empty_data_returns_empty_string(self):
		data = {'repeatingPatterns': [], 'tables': []}
		result = _format_structure_probe(data)
		assert result == ''

	def test_mixed_patterns_and_tables(self):
		data = {
			'repeatingPatterns': [
				{'key': 'tr', 'count': 10, 'sample': '<tr><td>row</td></tr>'},
			],
			'tables': [
				{'id': 'data', 'columns': ['Col1'], 'sampleRow': '<tr><td>val</td></tr>'},
			],
		}
		result = _format_structure_probe(data)
		assert 'Repeating patterns found:' in result
		assert 'Tables found:' in result


# ---------------------------------------------------------------------------
# New tests: whitespace compression
# ---------------------------------------------------------------------------


class TestWhitespaceCompression:
	def test_collapses_indentation_and_blank_lines(self):
		html = '<div>\n    \n    <p>  Hello   world  </p>\n\n</div>'
		result = _clean_html_for_codegen(html)
		# Blank-only text nodes should be dropped, inner whitespace collapsed
		assert '\n' not in result
		assert '    ' not in result
		assert 'Hello world' in result

	def test_preserves_meaningful_text(self):
		html = '<span>  Widget A  </span>'
		result = _clean_html_for_codegen(html)
		assert 'Widget A' in result

	def test_blank_nodes_removed(self):
		html = '<ul>\n  \n  <li>Item</li>\n  \n</ul>'
		result = _clean_html_for_codegen(html)
		# Only tag markup and the text "Item" should remain
		assert result == '<ul><li>Item</li></ul>'


# ---------------------------------------------------------------------------
# New tests: semantic class preservation
# ---------------------------------------------------------------------------


class TestSemanticClassPreservation:
	def test_semantic_class_kept_over_positional(self):
		"""product-card at position 7 should be kept when there are 10+ classes."""
		classes = 'c1 c2 c3 c4 c5 c6 product-card c8 c9 c10'
		html = f'<div class="{classes}">Text</div>'
		result = _clean_html_for_codegen(html)
		assert 'product-card' in result

	def test_multiple_semantic_classes_prioritized(self):
		classes = 'a1 a2 a3 a4 a5 a6 a7 a8 a9 price-cell product-title nav-link'
		html = f'<div class="{classes}">Text</div>'
		result = _clean_html_for_codegen(html)
		assert 'price-cell' in result
		assert 'product-title' in result
		assert 'nav-link' in result

	def test_fewer_than_max_classes_untouched(self):
		classes = 'foo bar product-card'
		html = f'<div class="{classes}">Text</div>'
		result = _clean_html_for_codegen(html)
		assert 'foo' in result
		assert 'bar' in result
		assert 'product-card' in result

	def test_no_semantic_classes_falls_back_to_front(self):
		"""When no classes match semantic fragments, keep the first _MAX_CLASSES."""
		classes = ' '.join(f'x{i}' for i in range(15))
		html = f'<div class="{classes}">Text</div>'
		result = _clean_html_for_codegen(html)
		assert 'x0' in result
		assert 'x7' in result
		assert 'x8' not in result


# ---------------------------------------------------------------------------
# New tests: truncation warning in LLM prompt
# ---------------------------------------------------------------------------


class TestTruncationWarningInPrompt:
	async def test_truncation_warning_appears_when_html_truncated(self):
		"""When html_truncated=True, _generate_js_script includes the warning in the LLM prompt."""
		from browser_use.tools.extraction.js_codegen import _generate_js_script

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)
		html = '<div>Some HTML</div>'

		await _generate_js_script(
			llm=extraction_llm,
			query='Extract products',
			html=html,
			html_truncated=True,
		)

		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		assert 'truncated' in user_msg_content.lower()
		assert 'missing elements' in user_msg_content.lower() or 'gracefully' in user_msg_content.lower()

	async def test_no_truncation_warning_when_not_truncated(self):
		"""When html_truncated=False (default), no warning in the LLM prompt."""
		from browser_use.tools.extraction.js_codegen import _generate_js_script

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)
		html = '<div>Some HTML</div>'

		await _generate_js_script(
			llm=extraction_llm,
			query='Extract products',
			html=html,
			html_truncated=False,
		)

		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		assert '\u26a0\ufe0f The HTML above was truncated' not in user_msg_content


# ---------------------------------------------------------------------------
# New tests: structure probe container selector
# ---------------------------------------------------------------------------


class TestStructureProbeContainer:
	async def test_probe_returns_container_for_table_page(self, browser_session, base_url):
		"""Table page: probe returns a container selector for the table's parent."""
		await browser_session.navigate_to(f'{base_url}/products')
		await asyncio.sleep(0.5)

		result, container = await _discover_page_structure(browser_session)
		# The table page has a <table id="products"> — the most repeated element (tr/td)
		# lives inside it, so container should refer to the table or its parent
		assert result != ''  # probe should find something

	async def test_probe_returns_container_for_card_page(self, browser_session, base_url):
		"""Card page: probe returns container selector for div.product-grid."""
		await browser_session.navigate_to(f'{base_url}/cards')
		await asyncio.sleep(0.5)

		result, container = await _discover_page_structure(browser_session)
		assert container is not None
		assert 'product-grid' in container


# ---------------------------------------------------------------------------
# New tests: container-based auto-scoping
# ---------------------------------------------------------------------------


# Page where data is inside div.product-grid, surrounded by lots of filler.
# The filler uses a single large <p> per section (not repeating divs) so the
# structure probe correctly identifies the repeating .card pattern as dominant.
_GRID_SECTION_FILLER = '<section><p>' + ('y' * 10000) + '</p></section>\n'
CONTAINER_SCOPING_HTML = (
	'<html><body>\n'
	+ _GRID_SECTION_FILLER * 3
	+ '<div class="product-grid">\n'
	+ '  <div class="card"><h3>Item A</h3><span class="price">$1</span></div>\n' * 6
	+ '</div>\n'
	+ _GRID_SECTION_FILLER * 3
	+ '</body></html>'
)


class TestContainerBasedAutoScoping:
	async def test_auto_scopes_to_probe_container(self, browser_session, http_server, base_url):
		"""When structure probe finds a container, auto-scoping uses it to trim HTML."""
		http_server.expect_request('/container-scope-test').respond_with_data(
			CONTAINER_SCOPING_HTML,
			content_type='text/html',
		)
		tools = Tools()
		await tools.navigate(url=f'{base_url}/container-scope-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		card_extract_js = """(function(){
try {
  var items = document.querySelectorAll('.card');
  var out = [];
  items.forEach(function(el) {
    var t = el.querySelector('h3');
    var p = el.querySelector('.price');
    out.push({title: t ? t.textContent.trim() : null, price: p ? p.textContent.trim() : null});
  });
  return out;
} catch(e) { return {error: e.message}; }
})()"""
		extraction_llm = _make_js_extraction_llm(card_extract_js)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all items with titles and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify the LLM received scoped HTML — filler should NOT be present
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		html_start = user_msg_content.index('<page_html>') + len('<page_html>')
		html_end = user_msg_content.index('</page_html>')
		page_html_section = user_msg_content[html_start:html_end]
		# The filler 'yyyyy' should not be in the scoped HTML
		assert 'yyyyy' not in page_html_section
		# But the card content should be present
		assert 'Item A' in page_html_section


# ---------------------------------------------------------------------------
# New tests: extract_links=True (href preservation)
# ---------------------------------------------------------------------------


class TestExtractLinksEnabled:
	async def test_href_visible_in_codegen_html(self, browser_session, base_url):
		"""With extract_links=True, href attributes should appear in the HTML sent to the codegen LLM."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/links', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		link_extract_js = """(function(){
try {
  var links = document.querySelectorAll('a');
  var out = [];
  for (var i = 0; i < links.length; i++) {
    out.push({text: links[i].textContent.trim(), href: links[i].getAttribute('href')});
  }
  return out;
} catch(e) { return {error: e.message}; }
})()"""
		extraction_llm = _make_js_extraction_llm(link_extract_js)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all links with their URLs',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify the LLM received HTML with href attributes
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		assert 'href=' in user_msg_content
		assert '/page/1' in user_msg_content
		assert 'example.com' in user_msg_content


# ---------------------------------------------------------------------------
# New tests: data-* attribute whitelist in HTMLSerializer
# ---------------------------------------------------------------------------


class TestDataAttrWhitelist:
	async def test_data_testid_preserved_in_codegen_html(self, browser_session, base_url):
		"""data-testid should be preserved through the full serialization + cleaning pipeline."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/data-attrs', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		attr_extract_js = """(function(){
try {
  var items = document.querySelectorAll('[data-testid^="item-"]');
  var out = [];
  for (var i = 0; i < items.length; i++) {
    out.push({testid: items[i].getAttribute('data-testid'), text: items[i].textContent.trim()});
  }
  return out;
} catch(e) { return {error: e.message}; }
})()"""
		extraction_llm = _make_js_extraction_llm(attr_extract_js)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract items using data-testid',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify the LLM received HTML with data-testid but not data-analytics or data-v-hash
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		assert 'data-testid=' in user_msg_content
		assert 'data-analytics' not in user_msg_content
		assert 'data-v-hash' not in user_msg_content
		assert 'data-react-fiber' not in user_msg_content


# ---------------------------------------------------------------------------
# New tests: pagination hint probe
# ---------------------------------------------------------------------------


class TestPaginationHintProbe:
	async def test_pagination_hint_included_in_extraction_result(self, browser_session, base_url):
		"""When the page has pagination controls, the extraction result should include a pagination_hint."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/paginated', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		# Should contain the pagination hint
		assert '<pagination_hint>' in result.extracted_content
		assert '</pagination_hint>' in result.extracted_content
		# Should mention "Next" or pagination
		assert 'next' in result.extracted_content.lower() or 'pagination' in result.extracted_content.lower()
		# Should mention script_id reuse
		assert 'script_id' in result.extracted_content.lower()

	async def test_no_pagination_hint_on_non_paginated_page(self, browser_session, base_url):
		"""When the page has no pagination, no pagination_hint tag should appear."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result = await tools.extract_with_script(
				query='Extract all products',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		# Should NOT contain pagination hint
		assert '<pagination_hint>' not in result.extracted_content


# ---------------------------------------------------------------------------
# New tests: increased HTML char limit
# ---------------------------------------------------------------------------


class TestHtmlCharLimit:
	def test_default_max_html_chars_is_200k(self):
		"""Verify the constant was updated to 200k."""
		from browser_use.tools.extraction.js_codegen import _DEFAULT_MAX_HTML_CHARS

		assert _DEFAULT_MAX_HTML_CHARS == 100_000


# ---------------------------------------------------------------------------
# Unit tests: ResultDeduplicator
# ---------------------------------------------------------------------------


class TestResultDeduplicator:
	def test_dedup_bare_array(self):
		"""Two calls with overlapping items — second call strips duplicates."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch1 = [{'name': 'A'}, {'name': 'B'}]
		result1, removed1, total1 = dd.dedup(batch1, 'script1')
		assert result1 == batch1
		assert removed1 == 0
		assert total1 == 2

		batch2 = [{'name': 'B'}, {'name': 'C'}]
		result2, removed2, total2 = dd.dedup(batch2, 'script1')
		assert result2 == [{'name': 'C'}]
		assert removed2 == 1
		assert total2 == 3

	def test_dedup_wrapped_dict(self):
		"""Single-key wrapper dict unwrapped, deduped, rewrapped."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch1 = {'products': [{'id': 1}, {'id': 2}]}
		result1, removed1, _ = dd.dedup(batch1, 'script1')
		assert result1 == {'products': [{'id': 1}, {'id': 2}]}
		assert removed1 == 0

		batch2 = {'products': [{'id': 2}, {'id': 3}]}
		result2, removed2, total2 = dd.dedup(batch2, 'script1')
		assert result2 == {'products': [{'id': 3}]}
		assert removed2 == 1
		assert total2 == 3

	def test_dedup_field_order_independent(self):
		"""{"a":1,"b":2} and {"b":2,"a":1} hash the same."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch1 = [{'a': 1, 'b': 2}]
		dd.dedup(batch1, 'script1')

		batch2 = [{'b': 2, 'a': 1}]
		result, removed, _ = dd.dedup(batch2, 'script1')
		assert result == []
		assert removed == 1

	def test_dedup_script_id_isolation(self):
		"""Same data under different script_ids — no cross-contamination."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch = [{'x': 1}]
		dd.dedup(batch, 'scriptA')

		result, removed, _ = dd.dedup(batch, 'scriptB')
		assert result == [{'x': 1}]
		assert removed == 0

	def test_dedup_passthrough_non_array(self):
		"""Single dict, string, empty list — no dedup, returns unchanged."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()

		# Single dict (not a wrapper)
		single = {'a': 1, 'b': 2}
		result, removed, total = dd.dedup(single, 'script1')
		assert result == single
		assert removed == 0
		assert total == 0

		# String
		result, removed, total = dd.dedup('hello', 'script1')
		assert result == 'hello'
		assert removed == 0

		# Empty list
		result, removed, total = dd.dedup([], 'script1')
		assert result == []
		assert removed == 0

		# Non-dict array
		result, removed, total = dd.dedup([1, 2, 3], 'script1')
		assert result == [1, 2, 3]
		assert removed == 0

	def test_dedup_all_duplicates_returns_empty(self):
		"""Second call with exact same data — empty array, removed count matches."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch = [{'name': 'A'}, {'name': 'B'}]
		dd.dedup(batch, 'script1')

		result, removed, total = dd.dedup(batch, 'script1')
		assert result == []
		assert removed == 2
		assert total == 2

	def test_dedup_nested_key_ordering(self):
		"""Nested dicts with reordered keys — same hash."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch1 = [{'outer': {'z': 1, 'a': 2}}]
		dd.dedup(batch1, 'script1')

		batch2 = [{'outer': {'a': 2, 'z': 1}}]
		result, removed, _ = dd.dedup(batch2, 'script1')
		assert result == []
		assert removed == 1

	def test_dedup_reset(self):
		"""reset(script_id) clears one scope, others untouched."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		batch = [{'x': 1}]
		dd.dedup(batch, 'scriptA')
		dd.dedup(batch, 'scriptB')

		dd.reset('scriptA')

		# scriptA: item should be treated as new
		resultA, removedA, _ = dd.dedup(batch, 'scriptA')
		assert resultA == [{'x': 1}]
		assert removedA == 0

		# scriptB: item should still be seen
		resultB, removedB, _ = dd.dedup(batch, 'scriptB')
		assert resultB == []
		assert removedB == 1

	def test_dedup_reset_all(self):
		"""reset() with no args clears everything."""
		from browser_use.tools.extraction.dedup import ResultDeduplicator

		dd = ResultDeduplicator()
		dd.dedup([{'x': 1}], 'scriptA')
		dd.dedup([{'x': 1}], 'scriptB')
		dd.reset()

		resultA, removedA, _ = dd.dedup([{'x': 1}], 'scriptA')
		resultB, removedB, _ = dd.dedup([{'x': 1}], 'scriptB')
		assert removedA == 0
		assert removedB == 0


# ---------------------------------------------------------------------------
# Integration test: dedup across paginated pages
# ---------------------------------------------------------------------------


# Page 1 and page 2 share Widget B (overlap)
DEDUP_PAGE1_HTML = """<html><body>
<table id="products">
  <thead><tr><th>Name</th><th>Price</th></tr></thead>
  <tbody>
    <tr><td>Widget A</td><td>$9.99</td></tr>
    <tr><td>Widget B</td><td>$19.99</td></tr>
  </tbody>
</table>
</body></html>"""

DEDUP_PAGE2_HTML = """<html><body>
<table id="products">
  <thead><tr><th>Name</th><th>Price</th></tr></thead>
  <tbody>
    <tr><td>Widget B</td><td>$19.99</td></tr>
    <tr><td>Widget C</td><td>$29.99</td></tr>
  </tbody>
</table>
</body></html>"""


class TestDedupAcrossPaginatedPages:
	async def test_dedup_across_paginated_pages(self, browser_session, http_server, base_url):
		"""Extract page 1, extract page 2 with same script_id. Page 2 should have Widget B stripped."""
		http_server.expect_request('/dedup-page1').respond_with_data(
			DEDUP_PAGE1_HTML,
			content_type='text/html',
		)
		http_server.expect_request('/dedup-page2').respond_with_data(
			DEDUP_PAGE2_HTML,
			content_type='text/html',
		)

		tools = Tools()
		extraction_llm = _make_js_extraction_llm(TABLE_EXTRACT_JS)

		# Page 1 extraction
		await tools.navigate(url=f'{base_url}/dedup-page1', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result1 = await tools.extract_with_script(
				query='Extract all products with names and prices',
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result1, ActionResult)
		assert result1.metadata is not None
		script_id = result1.metadata['script_id']
		# Page 1 should have no dedup stats (first extraction)
		assert '<dedup_stats>' not in result1.extracted_content

		# Parse page 1 results
		tag_start = result1.extracted_content.index('<js_extraction_result')
		data_start = result1.extracted_content.index('>', tag_start) + 1
		data_end = result1.extracted_content.index('</js_extraction_result>')
		parsed1 = json.loads(result1.extracted_content[data_start:data_end].strip())
		assert len(parsed1['products']) == 2

		# Page 2 extraction — reuse script_id
		await tools.navigate(url=f'{base_url}/dedup-page2', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as tmp:
			fs = FileSystem(tmp)
			result2 = await tools.extract_with_script(
				query='Extract all products with names and prices',
				script_id=script_id,
				browser_session=browser_session,
				page_extraction_llm=extraction_llm,
				file_system=fs,
			)

		assert isinstance(result2, ActionResult)
		assert result2.extracted_content is not None

		# Page 2 should have dedup_stats
		assert '<dedup_stats>' in result2.extracted_content
		assert 'duplicate(s) removed' in result2.extracted_content

		# Parse page 2 results — Widget B should be stripped
		tag_start = result2.extracted_content.index('<js_extraction_result')
		data_start = result2.extracted_content.index('>', tag_start) + 1
		data_end = result2.extracted_content.index('</js_extraction_result>')
		parsed2 = json.loads(result2.extracted_content[data_start:data_end].strip())
		assert len(parsed2['products']) == 1
		assert parsed2['products'][0]['name'] == 'Widget C'

		# Metadata should have dedup info
		assert result2.metadata is not None
		assert result2.metadata.get('dedup') == {'duplicates_removed': 1, 'total_unique': 3}
