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
	_extract_js_from_response,
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
