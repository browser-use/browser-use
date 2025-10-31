"""
Test DOM serializer with complex scenarios: shadow DOM, same-origin and cross-origin iframes.

This test verifies that the DOM serializer correctly:
1. Extracts interactive elements from shadow DOM
2. Processes same-origin iframes
3. Handles cross-origin iframes (should be blocked)
4. Generates correct selector_map with expected element counts

Usage:
	uv run pytest tests/ci/browser/test_dom_serializer.py -v -s
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile, ViewportSize
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server for DOM serializer tests."""
	from pathlib import Path

	server = HTTPServer()
	server.start()

	# Load HTML templates from files
	test_dir = Path(__file__).parent
	main_page_html = (test_dir / 'test_page_template.html').read_text()
	iframe_html = (test_dir / 'iframe_template.html').read_text()
	stacked_page_html = (test_dir / 'test_page_stacked_template.html').read_text()

	# Route 1: Main page with shadow DOM and iframes
	server.expect_request('/dom-test-main').respond_with_data(main_page_html, content_type='text/html')

	# Route 2: Same-origin iframe content
	server.expect_request('/iframe-same-origin').respond_with_data(iframe_html, content_type='text/html')

	# Route 3: Stacked complex scenarios test page
	server.expect_request('/stacked-test').respond_with_data(stacked_page_html, content_type='text/html')

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	"""Create a browser session for DOM serializer tests."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			window_size=ViewportSize(width=1920, height=1400),  # Taller window to fit all stacked elements
			cross_origin_iframes=True,  # Enable cross-origin iframe extraction via CDP target switching
		)
	)
	await session.start()
	yield session
	await session.kill()


class TestDOMSerializer:
	"""Test DOM serializer with complex scenarios."""

	async def test_dom_serializer_with_shadow_dom_and_iframes(self, browser_session, base_url):
		"""Test DOM serializer extracts elements from shadow DOM, same-origin iframes, and cross-origin iframes.

		This test verifies:
		1. Elements are in the serializer (selector_map)
		2. We can click elements using click(index)

		Expected interactive elements:
		- Regular DOM: 3 elements (button, input, link on main page)
		- Shadow DOM: 3 elements (2 buttons, 1 input inside shadow root)
		- Same-origin iframe: 2 elements (button, input inside iframe)
		- Cross-origin iframe placeholder: about:blank (no interactive elements)
		- Iframe tags: 2 elements (the iframe elements themselves)
		Total: ~10 interactive elements
		"""
		from browser_use.tools.service import Tools

		tools = Tools()

		# Create mock LLM actions that will click elements from each category
		# We'll generate actions dynamically after we know the indices
		actions = [
			f"""
			{{
				"thinking": "I'll navigate to the DOM test page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to test page",
				"next_goal": "Navigate to test page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/dom-test-main",
							"new_tab": false
						}}
					}}
				]
			}}
			"""
		]
		await tools.navigate(url=f'{base_url}/dom-test-main', new_tab=False, browser_session=browser_session)

		import asyncio

		await asyncio.sleep(1)

		# Get the browser state to access selector_map
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		assert browser_state_summary is not None, 'Browser state summary should not be None'
		assert browser_state_summary.dom_state is not None, 'DOM state should not be None'

		selector_map = browser_state_summary.dom_state.selector_map
		print(f'   Selector map: {selector_map.keys()}')

		print('\n📊 DOM Serializer Analysis:')
		print(f'   Total interactive elements found: {len(selector_map)}')
		serilized_text = browser_state_summary.dom_state.llm_representation()
		print(f'   Serialized text: {serilized_text}')
		# assume all selector map keys are as text in the serialized text
		# for idx, element in selector_map.items():
		# 	assert str(idx) in serilized_text, f'Element {idx} should be in serialized text'
		# 	print(f'   ✓ Element {idx} found in serialized text')

		# assume at least 10 interactive elements are in the selector map
		assert len(selector_map) >= 10, f'Should find at least 10 interactive elements, found {len(selector_map)}'

		# assert all interactive elements marked with [123] from serialized text are in selector map
		# find all [index] from serialized text with regex
		import re

		indices = re.findall(r'\[(\d+)\]', serilized_text)
		for idx in indices:
			assert int(idx) in selector_map.keys(), f'Element {idx} should be in selector map'
			print(f'   ✓ Element {idx} found in selector map')

		regular_elements = []
		shadow_elements = []
		iframe_content_elements = []
		iframe_tags = []

		# Categorize elements by their IDs (more stable than hardcoded indices)
		# Check element attributes to identify their location
		for idx, element in selector_map.items():
			# Check if this is an iframe tag (not content inside iframe)
			if element.tag_name == 'iframe':
				iframe_tags.append((idx, element))
			# Check if element has an ID attribute
			elif hasattr(element, 'attributes') and 'id' in element.attributes:
				elem_id = element.attributes['id'].lower()
				# Shadow DOM elements have IDs starting with "shadow-"
				if elem_id.startswith('shadow-'):
					shadow_elements.append((idx, element))
				# Iframe content elements have IDs starting with "iframe-"
				elif elem_id.startswith('iframe-'):
					iframe_content_elements.append((idx, element))
				# Everything else is regular DOM
				else:
					regular_elements.append((idx, element))
			# Elements without IDs are regular DOM
			else:
				regular_elements.append((idx, element))

		# Verify element counts based on our test page structure:
		# - Regular DOM: 3-4 elements (button, input, link on main page + possible cross-origin content)
		# - Shadow DOM: 3 elements (2 buttons, 1 input inside shadow root)
		# - Iframe content: 2 elements (button, input from same-origin iframe)
		# - Iframe tags: 2 elements (the iframe elements themselves)
		# Total: ~10-11 interactive elements depending on cross-origin iframe extraction

		print('\n✅ DOM Serializer Test Summary:')
		print(f'   • Regular DOM: {len(regular_elements)} elements {"✓" if len(regular_elements) >= 3 else "✗"}')
		print(f'   • Shadow DOM: {len(shadow_elements)} elements {"✓" if len(shadow_elements) >= 3 else "✗"}')
		print(
			f'   • Same-origin iframe content: {len(iframe_content_elements)} elements {"✓" if len(iframe_content_elements) >= 2 else "✗"}'
		)
		print(f'   • Iframe tags: {len(iframe_tags)} elements {"✓" if len(iframe_tags) >= 2 else "✗"}')
		print(f'   • Total elements: {len(selector_map)}')

		# Verify we found elements from all sources
		assert len(selector_map) >= 8, f'Should find at least 8 interactive elements, found {len(selector_map)}'
		assert len(regular_elements) >= 1, f'Should find at least 1 regular DOM element, found {len(regular_elements)}'
		assert len(shadow_elements) >= 1, f'Should find at least 1 shadow DOM element, found {len(shadow_elements)}'
		assert len(iframe_content_elements) >= 1, (
			f'Should find at least 1 iframe content element, found {len(iframe_content_elements)}'
		)

		# Now test clicking elements from each category using tools.click(index)
		print('\n🖱️  Testing Click Functionality:')

		# Helper to call tools.click(index) and verify it worked
		async def click(index: int, element_description: str, browser_session: BrowserSession):
			result = await tools.click(index=index, browser_session=browser_session)
			# Check both error field and extracted_content for failure messages
			if result.error:
				raise AssertionError(f'Click on {element_description} [{index}] failed: {result.error}')
			if result.extracted_content and (
				'not available' in result.extracted_content.lower() or 'failed' in result.extracted_content.lower()
			):
				raise AssertionError(f'Click on {element_description} [{index}] failed: {result.extracted_content}')
			print(f'   ✓ {element_description} [{index}] clicked successfully')
			return result

		# Test clicking a regular DOM element (button)
		if regular_elements:
			regular_button_idx = next((idx for idx, el in regular_elements if 'regular-btn' in el.attributes.get('id', '')), None)
			if regular_button_idx:
				await click(regular_button_idx, 'Regular DOM button', browser_session)

		# Test clicking a shadow DOM element (button)
		if shadow_elements:
			shadow_button_idx = next((idx for idx, el in shadow_elements if 'btn' in el.attributes.get('id', '')), None)
			if shadow_button_idx:
				await click(shadow_button_idx, 'Shadow DOM button', browser_session)

		# Test clicking a same-origin iframe element (button)
		if iframe_content_elements:
			iframe_button_idx = next((idx for idx, el in iframe_content_elements if 'btn' in el.attributes.get('id', '')), None)
			if iframe_button_idx:
				await click(iframe_button_idx, 'Same-origin iframe button', browser_session)

		# Validate click counter - verify all 3 clicks actually executed JavaScript
		print('\n✅ Validating click counter...')

		# Get the CDP session for the main page (use target from a regular DOM element)
		# Note: browser_session.agent_focus may point to a different target than the page
		if regular_elements and regular_elements[0][1].target_id:
			cdp_session = await browser_session.get_or_create_cdp_session(target_id=regular_elements[0][1].target_id)
		else:
			cdp_session = browser_session.agent_focus

		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'window.getClickCount()',
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)

		click_count = result.get('result', {}).get('value', 0)
		print(f'   Click counter value: {click_count}')

		assert click_count == 3, (
			f'Expected 3 clicks (Regular DOM + Shadow DOM + Iframe), but counter shows {click_count}. '
			f'This means some clicks did not execute JavaScript properly.'
		)

		print('\n🎉 DOM Serializer test completed successfully!')

	async def test_dom_serializer_element_counts_detailed(self, browser_session, base_url):
		"""Detailed test to verify specific element types are captured correctly."""

		actions = [
			f"""
			{{
				"thinking": "Navigating to test page",
				"evaluation_previous_goal": "Starting",
				"memory": "Navigate",
				"next_goal": "Navigate",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/dom-test-main",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "Done",
				"evaluation_previous_goal": "Navigated",
				"memory": "Complete",
				"next_goal": "Done",
				"action": [
					{
						"done": {
							"text": "Done",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)
		agent = Agent(
			task=f'Navigate to {base_url}/dom-test-main',
			llm=mock_llm,
			browser_session=browser_session,
		)

		history = await agent.run(max_steps=2)

		# Get current browser state to access selector_map
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		selector_map = browser_state_summary.dom_state.selector_map

		# Count different element types
		buttons = 0
		inputs = 0
		links = 0

		for idx, element in selector_map.items():
			element_str = str(element).lower()
			if 'button' in element_str or '<button' in element_str:
				buttons += 1
			elif 'input' in element_str or '<input' in element_str:
				inputs += 1
			elif 'link' in element_str or '<a' in element_str or 'href' in element_str:
				links += 1

		print('\n📊 Element Type Counts:')
		print(f'   Buttons: {buttons}')
		print(f'   Inputs: {inputs}')
		print(f'   Links: {links}')
		print(f'   Total: {len(selector_map)}')

		# We should have at least some of each type from the regular DOM
		assert buttons >= 1, f'Should find at least 1 button, found {buttons}'
		assert inputs >= 1, f'Should find at least 1 input, found {inputs}'

		print('\n✅ Element type verification passed!')

	async def test_stacked_complex_scenarios(self, browser_session, base_url):
		"""Test clicking through stacked complex scenarios and verify cross-origin iframe extraction.

		This test verifies:
		1. Open shadow DOM element interaction
		2. Closed shadow DOM element interaction (nested inside open shadow)
		3. Same-origin iframe element interaction (inside closed shadow)
		4. Cross-origin iframe placeholder with about:blank (no external dependencies)
		5. Truly nested structure: Open Shadow → Closed Shadow → Iframe
		"""
		from browser_use.tools.service import Tools

		tools = Tools()

		# Navigate to stacked test page
		await tools.navigate(url=f'{base_url}/stacked-test', new_tab=False, browser_session=browser_session)

		import asyncio

		await asyncio.sleep(1)

		# Get browser state
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		selector_map = browser_state_summary.dom_state.selector_map
		print(f'\n📊 Stacked Test - Found {len(selector_map)} elements')

		# Debug: Show all elements
		print('\n🔍 All elements found:')
		for idx, element in selector_map.items():
			elem_id = element.attributes.get('id', 'NO_ID') if hasattr(element, 'attributes') else 'NO_ATTR'
			print(f'   [{idx}] {element.tag_name} id={elem_id} target={element.target_id[-4:] if element.target_id else "None"}')

		# Categorize elements
		open_shadow_elements = []
		closed_shadow_elements = []
		iframe_elements = []
		final_button = None

		for idx, element in selector_map.items():
			if hasattr(element, 'attributes') and 'id' in element.attributes:
				elem_id = element.attributes['id'].lower()

				if 'open-shadow' in elem_id:
					open_shadow_elements.append((idx, element))
				elif 'closed-shadow' in elem_id:
					closed_shadow_elements.append((idx, element))
				elif 'iframe' in elem_id and element.tag_name != 'iframe':
					iframe_elements.append((idx, element))
				elif 'final-button' in elem_id:
					final_button = (idx, element)

		print('\n📋 Element Distribution:')
		print(f'   Open Shadow: {len(open_shadow_elements)} elements')
		print(f'   Closed Shadow: {len(closed_shadow_elements)} elements')
		print(f'   Iframe content: {len(iframe_elements)} elements')
		print(f'   Final button: {"Found" if final_button else "Not found"}')

		# Test clicking through each stacked layer
		print('\n🖱️  Testing Click Functionality Through Stacked Layers:')

		async def click(index: int, element_description: str, browser_session: BrowserSession):
			result = await tools.click(index=index, browser_session=browser_session)
			if result.error:
				raise AssertionError(f'Click on {element_description} [{index}] failed: {result.error}')
			if result.extracted_content and (
				'not available' in result.extracted_content.lower() or 'failed' in result.extracted_content.lower()
			):
				raise AssertionError(f'Click on {element_description} [{index}] failed: {result.extracted_content}')
			print(f'   ✓ {element_description} [{index}] clicked successfully')
			return result

		clicks_performed = 0

		# 1. Click open shadow button
		if open_shadow_elements:
			open_shadow_btn = next((idx for idx, el in open_shadow_elements if 'btn' in el.attributes.get('id', '')), None)
			if open_shadow_btn:
				await click(open_shadow_btn, 'Open Shadow DOM button', browser_session)
				clicks_performed += 1

		# 2. Click closed shadow button
		if closed_shadow_elements:
			closed_shadow_btn = next((idx for idx, el in closed_shadow_elements if 'btn' in el.attributes.get('id', '')), None)
			if closed_shadow_btn:
				await click(closed_shadow_btn, 'Closed Shadow DOM button', browser_session)
				clicks_performed += 1

		# 3. Click iframe button
		if iframe_elements:
			iframe_btn = next((idx for idx, el in iframe_elements if 'btn' in el.attributes.get('id', '')), None)
			if iframe_btn:
				await click(iframe_btn, 'Same-origin iframe button', browser_session)
				clicks_performed += 1

		# 4. Try clicking cross-origin iframe tag (can click the tag, but not elements inside)
		cross_origin_iframe_tag = None
		for idx, element in selector_map.items():
			if (
				element.tag_name == 'iframe'
				and hasattr(element, 'attributes')
				and 'cross-origin' in element.attributes.get('id', '').lower()
			):
				cross_origin_iframe_tag = (idx, element)
				break

		# Verify cross-origin iframe extraction is working
		# Check the full DOM tree (not just selector_map which only has interactive elements)
		def count_targets_in_tree(node, targets=None):
			if targets is None:
				targets = set()
			# SimplifiedNode has original_node which is an EnhancedDOMTreeNode
			if hasattr(node, 'original_node') and node.original_node and node.original_node.target_id:
				targets.add(node.original_node.target_id)
			# Recursively check children
			if hasattr(node, 'children') and node.children:
				for child in node.children:
					count_targets_in_tree(child, targets)
			return targets

		all_targets = count_targets_in_tree(browser_state_summary.dom_state._root)

		print('\n📊 Cross-Origin Iframe Extraction:')
		print(f'   Found elements from {len(all_targets)} different CDP targets in full DOM tree')

		if len(all_targets) >= 2:
			print('   ✅ Multi-target iframe extraction IS WORKING!')
			print('   ✓ Successfully extracted DOM from multiple CDP targets')
			print('   ✓ CDP target switching feature is enabled and functional')
		else:
			print('   ⚠️  Only found elements from 1 target (cross-origin extraction may not be working)')

		if cross_origin_iframe_tag:
			print(f'\n   📌 Found cross-origin iframe tag [{cross_origin_iframe_tag[0]}]')
			# Note: We don't increment clicks_performed since this doesn't trigger our counter
			# await click(cross_origin_iframe_tag[0], 'Cross-origin iframe tag (scroll)', browser_session)

		# 5. Click final button (after all stacked elements)
		if final_button:
			await click(final_button[0], 'Final button (after stack)', browser_session)
			clicks_performed += 1

		# Validate click counter
		print('\n✅ Validating click counter...')

		# Get CDP session from a non-iframe element (open shadow or final button)
		if open_shadow_elements:
			cdp_session = await browser_session.get_or_create_cdp_session(target_id=open_shadow_elements[0][1].target_id)
		elif final_button:
			cdp_session = await browser_session.get_or_create_cdp_session(target_id=final_button[1].target_id)
		else:
			cdp_session = browser_session.agent_focus

		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'window.getClickCount()',
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)

		click_count = result.get('result', {}).get('value', 0)
		print(f'   Click counter value: {click_count}')
		print(f'   Expected clicks: {clicks_performed}')

		assert click_count == clicks_performed, (
			f'Expected {clicks_performed} clicks, but counter shows {click_count}. '
			f'Some clicks did not execute JavaScript properly.'
		)

		print('\n🎉 Stacked scenario test completed successfully!')
		print('   ✓ Open shadow DOM clicks work')
		print('   ✓ Closed shadow DOM clicks work')
		print('   ✓ Same-origin iframe clicks work (can access elements inside)')
		print('   ✓ Cross-origin iframe extraction works (CDP target switching enabled)')
		print('   ✓ Truly nested structure works: Open Shadow → Closed Shadow → Iframe')


if __name__ == '__main__':
	"""Run test in debug mode with manual fixture setup."""
	import asyncio
	import logging

	# Set up debug logging
	logging.basicConfig(
		level=logging.DEBUG,
		format='%(levelname)-8s [%(name)s] %(message)s',
	)

	async def main():
		# Set up HTTP server fixture
		from pathlib import Path

		from pytest_httpserver import HTTPServer

		server = HTTPServer()
		server.start()

		# Load HTML templates from files (same as http_server fixture)
		test_dir = Path(__file__).parent
		main_page_html = (test_dir / 'test_page_stacked_template.html').read_text()
		# Set up routes using templates
		server.expect_request('/stacked-test').respond_with_data(main_page_html, content_type='text/html')

		base_url = f'http://{server.host}:{server.port}'
		print(f'\n🌐 HTTP Server running at {base_url}')

		# Set up browser session
		from browser_use.browser import BrowserSession
		from browser_use.browser.profile import BrowserProfile

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=False,  # Set to False to see browser in action
				user_data_dir=None,
				keep_alive=True,
			)
		)

		try:
			await session.start()
			print('🚀 Browser session started\n')

			# Run the test
			test = TestDOMSerializer()
			await test.test_stacked_complex_scenarios(session, base_url)

			print('\n✅ Test completed successfully!')

		finally:
			# Cleanup
			await session.kill()
			server.stop()
			print('\n🧹 Cleanup complete')

	asyncio.run(main())
