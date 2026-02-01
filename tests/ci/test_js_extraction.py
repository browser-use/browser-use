"""Tests for PR 2: JS-codegen extraction via extract_with_script action."""

import pytest
from conftest import create_mock_llm
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.extraction.js_codegen import JSExtractionService
from browser_use.tools.views import ExtractWithScriptAction

PRODUCT_TABLE_HTML = """
<!DOCTYPE html>
<html>
<body>
<table id="products">
  <thead>
    <tr><th>Name</th><th>Price</th><th>SKU</th></tr>
  </thead>
  <tbody>
    <tr><td>Widget A</td><td>$9.99</td><td>W001</td></tr>
    <tr><td>Widget B</td><td>$19.99</td><td>W002</td></tr>
    <tr><td>Widget C</td><td>$29.99</td><td>W003</td></tr>
  </tbody>
</table>
</body>
</html>
"""

LARGE_PAGE_HTML = (
	"""
<!DOCTYPE html>
<html>
<body>
<div id="target">
  <h1>Target Section</h1>
  <p>Important data here</p>
</div>
"""
	+ ('<p>' + 'x' * 1000 + '</p>\n') * 200
	+ """
</body>
</html>
"""
)


# JS that the mock LLM "generates" — a working extraction script
MOCK_JS_EXTRACT_PRODUCTS = """(function(){
  var rows = document.querySelectorAll('#products tbody tr');
  var products = [];
  rows.forEach(function(row) {
    var cells = row.querySelectorAll('td');
    if (cells.length >= 3) {
      products.push({
        name: cells[0].textContent.trim(),
        price: cells[1].textContent.trim(),
        sku: cells[2].textContent.trim()
      });
    }
  });
  return {products: products};
})()"""

MOCK_JS_EXTRACT_TARGET = """(function(){
  var el = document.querySelector('#target');
  return el ? {title: el.querySelector('h1').textContent.trim(), text: el.querySelector('p').textContent.trim()} : null;
})()"""

MOCK_JS_RETURNS_EMPTY = """(function(){ return []; })()"""

MOCK_JS_FAILING = """(function(){ throw new Error('selector not found'); })()"""

MOCK_JS_FIXED = """(function(){
  return {products: [{name: 'Widget A', price: '$9.99', sku: 'W001'}]};
})()"""


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			enable_default_extensions=True,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


class TestJSExtractionService:
	"""Tests for the core JSExtractionService."""

	async def test_extract_product_table(self, browser_session: BrowserSession, httpserver: HTTPServer):
		"""Serve a product table, extract via mock LLM that returns working JS."""
		httpserver.expect_request('/products').respond_with_data(PRODUCT_TABLE_HTML, content_type='text/html')
		url = httpserver.url_for('/products')

		# Navigate to the page
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

		# Create mock LLM that returns our JS script
		llm = create_mock_llm(actions=[MOCK_JS_EXTRACT_PRODUCTS])
		# Override ainvoke to return the script as plain text (not as AgentOutput JSON)
		from browser_use.llm.views import ChatInvokeCompletion

		async def mock_ainvoke(messages, output_format=None, **kwargs):
			return ChatInvokeCompletion(completion=MOCK_JS_EXTRACT_PRODUCTS, usage=None)

		llm.ainvoke.side_effect = mock_ainvoke  # type: ignore[attr-defined]

		service = JSExtractionService()
		result = await service.extract(
			query='Extract all products with name, price, and SKU',
			browser_session=browser_session,
			llm=llm,
		)

		assert result.data is not None
		assert isinstance(result.data, dict)
		assert 'products' in result.data
		assert len(result.data['products']) == 3
		assert result.data['products'][0]['name'] == 'Widget A'
		assert result.data['products'][2]['sku'] == 'W003'

	async def test_extract_with_css_selector(self, browser_session: BrowserSession, httpserver: HTTPServer):
		"""Use css_selector to narrow extraction to a specific section."""
		httpserver.expect_request('/scoped').respond_with_data(LARGE_PAGE_HTML, content_type='text/html')
		url = httpserver.url_for('/scoped')

		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

		from browser_use.llm.views import ChatInvokeCompletion

		# Track what HTML the LLM receives
		received_html = []

		async def mock_ainvoke(messages, output_format=None, **kwargs):
			# The user message contains the HTML structure
			for msg in messages:
				if hasattr(msg, 'content') and '<html_structure>' in str(msg.content):
					received_html.append(str(msg.content))
			return ChatInvokeCompletion(completion=MOCK_JS_EXTRACT_TARGET, usage=None)

		llm = create_mock_llm()
		llm.ainvoke.side_effect = mock_ainvoke  # type: ignore[attr-defined]

		service = JSExtractionService()
		result = await service.extract(
			query='Extract the target section data',
			browser_session=browser_session,
			llm=llm,
			css_selector='#target',
		)

		assert result.data is not None
		assert result.data.get('title') == 'Target Section'
		assert result.data.get('text') == 'Important data here'

		# Verify the LLM received scoped HTML (should be much smaller than full page)
		assert len(received_html) > 0
		# The scoped HTML should NOT contain the bulk filler content
		assert 'x' * 100 not in received_html[0] or len(received_html[0]) < 200_000

	async def test_js_execution_failure_retry(self, browser_session: BrowserSession, httpserver: HTTPServer):
		"""JS execution failure triggers a retry with error feedback."""
		httpserver.expect_request('/retry').respond_with_data(PRODUCT_TABLE_HTML, content_type='text/html')
		url = httpserver.url_for('/retry')

		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

		from browser_use.llm.views import ChatInvokeCompletion

		call_count = 0

		async def mock_ainvoke(messages, output_format=None, **kwargs):
			nonlocal call_count
			call_count += 1
			if call_count == 1:
				# First call returns failing JS
				return ChatInvokeCompletion(completion=MOCK_JS_FAILING, usage=None)
			else:
				# Second call (with error feedback) returns working JS
				# Verify error feedback is present
				msg_text = str(messages[-1].content) if messages else ''
				assert 'previous_error' in msg_text or 'selector not found' in msg_text
				return ChatInvokeCompletion(completion=MOCK_JS_FIXED, usage=None)

		llm = create_mock_llm()
		llm.ainvoke.side_effect = mock_ainvoke  # type: ignore[attr-defined]

		service = JSExtractionService()
		result = await service.extract(
			query='Extract products',
			browser_session=browser_session,
			llm=llm,
		)

		assert call_count == 2, 'Should have retried after first failure'
		assert result.data is not None

	async def test_schema_validation(self, browser_session: BrowserSession, httpserver: HTTPServer):
		"""Result that doesn't match schema is flagged."""
		httpserver.expect_request('/schema').respond_with_data(PRODUCT_TABLE_HTML, content_type='text/html')
		url = httpserver.url_for('/schema')

		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

		from browser_use.llm.views import ChatInvokeCompletion

		# Return data that matches the schema
		async def mock_ainvoke(messages, output_format=None, **kwargs):
			return ChatInvokeCompletion(completion=MOCK_JS_EXTRACT_PRODUCTS, usage=None)

		llm = create_mock_llm()
		llm.ainvoke.side_effect = mock_ainvoke  # type: ignore[attr-defined]

		schema = {
			'type': 'object',
			'properties': {
				'products': {
					'type': 'array',
					'items': {
						'type': 'object',
						'properties': {
							'name': {'type': 'string'},
							'price': {'type': 'string'},
							'sku': {'type': 'string'},
						},
						'required': ['name', 'price', 'sku'],
					},
				},
			},
			'required': ['products'],
		}

		service = JSExtractionService()
		result = await service.extract(
			query='Extract products',
			browser_session=browser_session,
			llm=llm,
			output_schema=schema,
		)

		assert result.data is not None
		assert result.schema_used is True

	async def test_cached_js_script(self, browser_session: BrowserSession, httpserver: HTTPServer):
		"""When cached_js_script is provided, skip LLM call entirely."""
		httpserver.expect_request('/cached').respond_with_data(PRODUCT_TABLE_HTML, content_type='text/html')
		url = httpserver.url_for('/cached')

		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

		# LLM should NOT be called when cached_js_script is provided
		llm = create_mock_llm()
		llm.ainvoke.side_effect = AssertionError('LLM should not be called with cached script')  # type: ignore[attr-defined]

		service = JSExtractionService()
		result = await service.extract(
			query='Extract products',
			browser_session=browser_session,
			llm=llm,
			cached_js_script=MOCK_JS_EXTRACT_PRODUCTS,
		)

		assert result.data is not None
		assert 'products' in result.data
		assert len(result.data['products']) == 3


class TestIsEmptyData:
	"""Tests for the _is_empty_data helper used in auto-fallback."""

	def test_empty_list(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data([]) is True

	def test_empty_dict(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data({}) is True

	def test_dict_with_empty_lists(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data({'products': [], 'items': []}) is True

	def test_non_empty_list(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data([1, 2, 3]) is False

	def test_non_empty_dict(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data({'name': 'Widget'}) is False

	def test_dict_with_non_empty_list(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data({'products': [{'name': 'Widget'}]}) is False

	def test_none(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data(None) is True

	def test_string(self):
		from browser_use.tools.service import _is_empty_data

		assert _is_empty_data('some text') is False


class TestExtractWithScriptAction:
	"""Tests for the ExtractWithScriptAction model."""

	def test_action_model_fields(self):
		action = ExtractWithScriptAction(query='Get products')
		assert action.query == 'Get products'
		assert action.output_schema is None
		assert action.css_selector is None
		assert action.extraction_id is None

	def test_action_model_with_all_fields(self):
		action = ExtractWithScriptAction(
			query='Get products',
			output_schema={'type': 'object', 'properties': {'items': {'type': 'array'}}},
			css_selector='table#products',
			extraction_id='abc123',
		)
		assert action.css_selector == 'table#products'
		assert action.extraction_id == 'abc123'
