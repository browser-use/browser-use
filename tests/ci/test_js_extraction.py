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
	_extract_js_from_response,
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
		# Should keep only first 5 classes
		assert 'c0' in result
		assert 'c4' in result
		assert 'c5' not in result

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
	'<header><nav>' + ('link ' * 200) + '</nav></header>\n'
	+ _FILLER * 5
	+ '<main><table id="products">\n'
	'  <thead><tr><th>Name</th><th>Price</th></tr></thead>\n'
	'  <tbody>\n'
	'    <tr><td>Widget A</td><td>$9.99</td></tr>\n'
	'    <tr><td>Widget B</td><td>$19.99</td></tr>\n'
	'  </tbody>\n'
	'</table></main>\n'
	+ _FILLER * 5
	+ '<footer>' + ('footer ' * 200) + '</footer>\n'
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
		assert '<js_extraction_result>' in result.extracted_content
		assert '</js_extraction_result>' in result.extracted_content

		# Parse JSON from tags
		start = result.extracted_content.index('<js_extraction_result>') + len('<js_extraction_result>')
		end = result.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result.extracted_content[start:end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 3
		assert parsed['products'][0]['name'] == 'Widget A'

		# Metadata
		assert result.metadata is not None
		assert result.metadata['js_codegen_extraction'] is True
		assert 'js_script' in result.metadata

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

	async def test_css_selector_hidden_from_schema(self):
		"""css_selector should not appear in the agent-facing tool schema."""
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
		assert '<js_extraction_result>' in result.extracted_content

		# Parse and verify successful extraction
		start = result.extracted_content.index('<js_extraction_result>') + len('<js_extraction_result>')
		end = result.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result.extracted_content[start:end].strip())
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
		assert '<js_extraction_result>' in result.extracted_content
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
		assert '<js_extraction_result>' in result.extracted_content

		# Verify the LLM received scoped HTML (should contain <main> content but not the filler)
		call_args = extraction_llm.ainvoke.call_args
		messages = call_args[0][0]
		user_msg_content = str(messages[1].content)
		# The HTML sent to the LLM should contain the table
		assert '#products' in user_msg_content or 'Widget A' in user_msg_content
		# The filler content should NOT be in the scoped HTML
		assert 'xxxxx' not in user_msg_content

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
		assert '<js_extraction_result>' in result.extracted_content

		# Verify LLM was called twice (retry happened)
		assert extraction_llm.ainvoke.call_count == 2

		# Second call should have empty-result error feedback
		second_call = extraction_llm.ainvoke.call_args_list[1]
		second_user_content = str(second_call[0][0][1].content)
		assert '<previous_attempt_error>' in second_user_content
		assert 'empty result' in second_user_content.lower()

		# Verify retry count in metadata
		assert result.metadata is not None
		assert result.metadata['retries_used'] == 1

	async def test_empty_result_all_retries_fail(self, browser_session, base_url):
		"""If every attempt returns empty, the action returns an error."""
		tools = Tools()
		await tools.navigate(url=f'{base_url}/products', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		# Both calls return empty-array JS
		extraction_llm = _make_js_extraction_llm_sequence([EMPTY_RESULT_JS, EMPTY_RESULT_JS])

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

		# LLM should NOT have been called again
		assert extraction_llm.ainvoke.call_count == 1

		# Verify page 2 data was extracted
		start = result2.extracted_content.index('<js_extraction_result>') + len('<js_extraction_result>')
		end = result2.extracted_content.index('</js_extraction_result>')
		parsed = json.loads(result2.extracted_content[start:end].strip())
		assert 'products' in parsed
		assert len(parsed['products']) == 2
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
