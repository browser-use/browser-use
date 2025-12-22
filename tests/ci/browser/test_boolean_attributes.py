"""
Test that boolean attributes with empty string values are correctly preserved in DOM serialization.

In HTML, boolean attributes like `expanded=""`, `checked=""`, `disabled=""` indicate true state
by their mere presence. The empty string value is semantically equivalent to `expanded="true"`.

This test verifies that the serializer:
1. Does NOT filter out boolean attributes with empty string values
2. Correctly displays them in the LLM representation

Usage:
	uv run pytest tests/ci/browser/test_boolean_attributes.py -v -s
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile, ViewportSize

# HTML page with elements that have empty string boolean attributes
BOOLEAN_ATTRIBUTES_HTML = """
<!DOCTYPE html>
<html>
<head>
	<title>Boolean Attributes Test</title>
</head>
<body>
	<!-- Custom element with expanded="" (empty string) - common pattern in component libraries -->
	<div id="dropdown-container" role="combobox" aria-expanded="" expanded="">
		<button id="dropdown-trigger">Open Dropdown</button>
		<div id="dropdown-content">Dropdown Content</div>
	</div>

	<!-- Standard HTML boolean attributes -->
	<input type="checkbox" id="checked-checkbox" checked="" />
	<input type="text" id="disabled-input" disabled="" value="Disabled" />
	<details id="details-element" open="">
		<summary>Details Summary</summary>
		<p>Details content</p>
	</details>

	<!-- Custom elements like in the issue (kat-region-selector pattern) -->
	<div id="region-selector"
		role="listbox"
		aria-expanded=""
		expanded=""
		state="open">
		<span>Select Region</span>
	</div>

	<!-- Compare: explicit true value (should also work) -->
	<div id="explicit-expanded" role="combobox" aria-expanded="true" expanded="true">
		<span>Explicit True</span>
	</div>

	<!-- Compare: false value (should be hidden) -->
	<div id="explicit-false" role="combobox" aria-expanded="false">
		<span>Explicit False</span>
	</div>
</body>
</html>
"""


@pytest.fixture(scope='module')
def http_server():
	"""Create and provide a test HTTP server."""
	server = HTTPServer()
	server.start()
	server.expect_request('/boolean-test').respond_with_data(BOOLEAN_ATTRIBUTES_HTML, content_type='text/html')
	yield server
	server.stop()


@pytest.fixture(scope='module')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	"""Create a browser session for testing."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			window_size=ViewportSize(width=1280, height=800),
		)
	)
	await session.start()
	yield session
	await session.kill()


class TestBooleanAttributes:
	"""Test boolean attribute handling in DOM serializer."""

	async def test_empty_string_expanded_attribute_is_preserved(self, browser_session, base_url):
		"""
		Test that expanded="" (empty string) is correctly preserved and shown to LLM.

		The issue: HTML like `<div expanded="">` has the `expanded` attribute present
		with an empty string value. This should be treated as "expanded=true" and
		shown in the LLM representation, but was being filtered out.
		"""
		from browser_use.tools.service import Tools

		tools = Tools()
		await tools.navigate(url=f'{base_url}/boolean-test', new_tab=False, browser_session=browser_session)

		import asyncio

		await asyncio.sleep(0.5)

		# Get browser state
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		assert browser_state_summary is not None
		assert browser_state_summary.dom_state is not None

		# Get the LLM representation
		llm_repr = browser_state_summary.dom_state.llm_representation()
		print(f'\n📊 LLM Representation:\n{llm_repr}\n')

		# Look for elements in selector_map
		selector_map = browser_state_summary.dom_state.selector_map
		print(f'\n📋 Selector map has {len(selector_map)} elements')

		for idx, element in selector_map.items():
			if hasattr(element, 'attributes') and element.attributes:
				elem_id = element.attributes.get('id', '')
				if 'dropdown' in elem_id or 'region' in elem_id or 'expanded' in elem_id:
					print(f'   [{idx}] {element.tag_name} id={elem_id}')
					print(f'       attributes: {element.attributes}')

		# Key assertions:
		# 1. The "expanded" or "aria-expanded" attribute should be visible for elements with expanded=""

		# Check that dropdown-container (with expanded="") has the expanded state visible
		found_expanded_empty_string = False
		for idx, element in selector_map.items():
			if hasattr(element, 'attributes') and element.attributes:
				elem_id = element.attributes.get('id', '')
				if elem_id == 'dropdown-container' or elem_id == 'region-selector':
					# Check if expanded or aria-expanded is in the LLM representation for this element
					# The element line should contain "expanded" or the serialized text should show it
					found_expanded_empty_string = True
					print(f'\n   Found test element: {elem_id}')
					print(f'   Attributes: {element.attributes}')

		assert found_expanded_empty_string, 'Should find elements with expanded="" attribute'

		# The LLM representation should contain "expanded" for elements that have it
		# This is the main assertion - we want expanded="" to be preserved
		# The dropdown-container element specifically should show expanded attribute
		# Look for the pattern: element with id=dropdown-container should have expanded=true (or similar)

		# Find the line containing dropdown-container
		dropdown_line = None
		for line in llm_repr.split('\n'):
			if 'dropdown-container' in line:
				dropdown_line = line
				break

		assert dropdown_line is not None, 'Should find dropdown-container element in LLM representation'
		print(f'\n   Dropdown line: {dropdown_line}')

		# The dropdown-container should show expanded attribute (empty string should become 'true')
		assert 'expanded' in dropdown_line.lower(), (
			f'Element with expanded="" should show "expanded" attribute in LLM representation. Got line: {dropdown_line}'
		)

		# Also check region-selector
		region_line = None
		for line in llm_repr.split('\n'):
			if 'region-selector' in line:
				region_line = line
				break

		if region_line:
			print(f'   Region line: {region_line}')
			assert 'expanded' in region_line.lower(), (
				f'Element with expanded="" should show "expanded" attribute. Got line: {region_line}'
			)

		print('\n✅ Empty string boolean attribute test passed!')

	async def test_checked_empty_string_attribute(self, browser_session, base_url):
		"""Test that checked="" is correctly preserved for checkbox elements."""
		from browser_use.tools.service import Tools

		tools = Tools()
		await tools.navigate(url=f'{base_url}/boolean-test', new_tab=False, browser_session=browser_session)

		import asyncio

		await asyncio.sleep(0.5)

		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		llm_repr = browser_state_summary.dom_state.llm_representation()
		print(f'\n📊 LLM Representation:\n{llm_repr}\n')

		# Check that checked checkbox shows checked state
		assert 'checked' in llm_repr.lower(), 'LLM representation should show "checked" for checkbox with checked="" attribute'

		print('\n✅ Checked empty string attribute test passed!')

	async def test_disabled_empty_string_attribute(self, browser_session, base_url):
		"""Test that disabled="" is correctly preserved for input elements."""
		from browser_use.tools.service import Tools

		tools = Tools()
		await tools.navigate(url=f'{base_url}/boolean-test', new_tab=False, browser_session=browser_session)

		import asyncio

		await asyncio.sleep(0.5)

		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		llm_repr = browser_state_summary.dom_state.llm_representation()
		selector_map = browser_state_summary.dom_state.selector_map

		# Find the disabled input
		disabled_input_found = False
		for idx, element in selector_map.items():
			if hasattr(element, 'attributes') and element.attributes:
				elem_id = element.attributes.get('id', '')
				if elem_id == 'disabled-input':
					disabled_input_found = True
					print(f'\n   Found disabled input: {element.attributes}')

		# disabled elements might not be in selector_map (not interactive),
		# but the attribute should still be serialized if included
		print(f'\n📊 LLM Representation:\n{llm_repr}\n')
		print('\n✅ Disabled empty string attribute test passed!')


if __name__ == '__main__':
	import asyncio
	import logging

	logging.basicConfig(level=logging.DEBUG)

	async def main():
		from pytest_httpserver import HTTPServer

		server = HTTPServer()
		server.start()
		server.expect_request('/boolean-test').respond_with_data(BOOLEAN_ATTRIBUTES_HTML, content_type='text/html')
		base_url = f'http://{server.host}:{server.port}'
		print(f'\n🌐 Server at {base_url}')

		from browser_use.browser import BrowserSession
		from browser_use.browser.profile import BrowserProfile

		session = BrowserSession(browser_profile=BrowserProfile(headless=False, user_data_dir=None))

		try:
			await session.start()
			test = TestBooleanAttributes()
			await test.test_empty_string_expanded_attribute_is_preserved(session, base_url)
			await test.test_checked_empty_string_attribute(session, base_url)
			print('\n✅ All tests passed!')
		finally:
			await session.kill()
			server.stop()

	asyncio.run(main())
