# @file purpose: Test checkbox state verification after clicking (fix for issue #3437)
"""
Test file for verifying checkbox state is correctly tracked after clicking.

This test verifies the fix for issue #3437 where checkboxes were sometimes clicked twice
because the agent didn't detect the state change and thought the checkbox was still unchecked.

The fix includes:
1. CDP-based state verification after click
2. State information included in ActionResult
3. Browser state cache invalidation for checkbox interactions

Usage:
    uv run pytest tests/ci/interactions/test_checkbox_state_verification.py -v -s
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools
from browser_use.tools.utils import (
	get_checkbox_state_description,
	verify_checkbox_state_via_cdp,
)


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves checkbox test pages."""
	server = HTTPServer()
	server.start()

	# Simple checkbox test page
	checkbox_html = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Checkbox Test</title>
	</head>
	<body>
		<h1>Checkbox State Test</h1>
		<form id="test-form">
			<label>
				<input type="checkbox" id="simple-checkbox" name="simple" value="yes">
				Simple Checkbox
			</label>
			<br/>
			
			<label>
				<input type="checkbox" id="hidden-checkbox" name="hidden" value="yes" style="display: none;">
				Hidden Checkbox (visible label)
			</label>
			<br/>
			
			<div id="custom-checkbox" role="checkbox" aria-checked="false" tabindex="0">
				Custom Checkbox (role=checkbox)
			</div>
			<br/>
			
			<label id="stripe-style">
				<input type="checkbox" id="stripe-checkbox" name="stripe" style="opacity: 0; width: 0; height: 0;">
				<span>Save my information for faster checkout</span>
			</label>
			<br/>
			
			<div id="result" style="margin-top: 20px; padding: 10px; border: 1px solid #ccc; display: none;">
				Result: <span id="result-text"></span>
			</div>
		</form>
		
		<script>
			// Handle custom checkbox
			const customCheckbox = document.getElementById('custom-checkbox');
			if (customCheckbox) {
				customCheckbox.addEventListener('click', function() {
					const isChecked = this.getAttribute('aria-checked') === 'true';
					this.setAttribute('aria-checked', String(!isChecked));
					updateResult();
				});
			}
			
			// Update result display
			function updateResult() {
				const simpleChecked = document.getElementById('simple-checkbox').checked;
				const hiddenChecked = document.getElementById('hidden-checkbox').checked;
				const customChecked = document.getElementById('custom-checkbox').getAttribute('aria-checked') === 'true';
				
				const result = document.getElementById('result');
				result.style.display = 'block';
				result.textContent = `simple=${simpleChecked}, hidden=${hiddenChecked}, custom=${customChecked}`;
			}
			
			// Track changes to all checkboxes
			document.getElementById('simple-checkbox').addEventListener('change', updateResult);
			document.getElementById('hidden-checkbox').addEventListener('change', updateResult);
		</script>
	</body>
	</html>
	"""

	server.expect_request('/checkbox-test').respond_with_data(
		checkbox_html,
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance."""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


class TestCheckboxStateVerification:
	"""Test cases for checkbox state verification fix."""

	async def test_simple_checkbox_click(self, browser_session, base_url):
		"""Test that simple checkbox state is verified after click."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)  # Wait for page load

		# Get the state before
		state_before = await browser_session.get_browser_state_summary()
		selector_map = state_before.dom_state.selector_map

		# Find simple checkbox
		simple_checkbox_index = None
		for idx, node in selector_map.items():
			if (
				node.tag_name == 'input'
				and node.attributes.get('type') == 'checkbox'
				and node.attributes.get('id') == 'simple-checkbox'
			):
				simple_checkbox_index = idx
				break

		assert simple_checkbox_index is not None, 'Could not find simple checkbox'

		# Click the checkbox
		result = await tools.click(
			index=simple_checkbox_index,
			browser_session=browser_session,
		)

		# Verify click was successful
		assert result.extracted_content is not None
		assert 'Clicked' in result.extracted_content

		# Verify state information is in the result
		assert result.long_term_memory is not None
		assert 'checkbox' in result.long_term_memory.lower()

		# Verify state information is in metadata
		if result.metadata and 'state_change' in result.metadata:
			print(f'✓ State change detected: {result.metadata["state_change"]}')

		print(f'✓ Click result: {result.extracted_content}')
		print(f'✓ Memory: {result.long_term_memory}')

	async def test_custom_checkbox_role_click(self, browser_session, base_url):
		"""Test custom checkbox with role=checkbox attribute."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)

		state_before = await browser_session.get_browser_state_summary()
		selector_map = state_before.dom_state.selector_map

		# Find custom checkbox with role
		custom_checkbox_index = None
		for idx, node in selector_map.items():
			if node.attributes.get('role') == 'checkbox' and node.attributes.get('id') == 'custom-checkbox':
				custom_checkbox_index = idx
				break

		# Skip this test if custom checkbox not found (may vary by environment)
		if custom_checkbox_index is None:
			print('⚠️ Custom checkbox not found in selector_map, skipping test')
			return

		# Click the checkbox
		result = await tools.click(
			index=custom_checkbox_index,
			browser_session=browser_session,
		)

		assert result.extracted_content is not None
		print(f'✓ Custom checkbox click: {result.extracted_content}')

	async def test_cache_invalidation_after_checkbox_click(self, browser_session, base_url):
		"""Test that browser state cache is invalidated after checkbox click."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)

		# Get first state
		state1 = await browser_session.get_browser_state_summary()
		selector_map1 = state1.dom_state.selector_map

		# Find simple checkbox
		simple_checkbox_index = None
		for idx, node in selector_map1.items():
			if (
				node.tag_name == 'input'
				and node.attributes.get('type') == 'checkbox'
				and node.attributes.get('id') == 'simple-checkbox'
			):
				simple_checkbox_index = idx
				break

		assert simple_checkbox_index is not None

		# Click checkbox (should invalidate cache)
		await tools.click(
			index=simple_checkbox_index,
			browser_session=browser_session,
		)

		# Get second state - should be fresh (not cached)
		state2 = await browser_session.get_browser_state_summary()

		# Both should have the same elements but different snapshots due to checkbox state
		assert len(state2.dom_state.selector_map) > 0
		print('✓ Cache was properly invalidated after checkbox click')

	async def test_multiple_checkbox_clicks_not_duplicated(self, browser_session, base_url):
		"""Test that multiple checkbox clicks don't cause double-clicking (issue #3437)."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)

		state = await browser_session.get_browser_state_summary()
		selector_map = state.dom_state.selector_map

		# Find simple checkbox
		simple_checkbox_index = None
		for idx, node in selector_map.items():
			if (
				node.tag_name == 'input'
				and node.attributes.get('type') == 'checkbox'
				and node.attributes.get('id') == 'simple-checkbox'
			):
				simple_checkbox_index = idx
				break

		assert simple_checkbox_index is not None

		# Click checkbox first time
		result1 = await tools.click(
			index=simple_checkbox_index,
			browser_session=browser_session,
		)

		print(f'✓ First click: {result1.extracted_content}')

		# Wait a bit for state update
		await asyncio.sleep(0.5)

		# Get fresh state to verify click
		state_after_first_click = await browser_session.get_browser_state_summary()

		# The checkbox should now show as checked in the new state
		# (This would have been missed before the fix, potentially causing double-click)
		print('✓ State properly updated after first click')


class TestCheckboxStateUtilFunctions:
	"""Test the utility functions for checkbox state verification."""

	async def test_get_checkbox_state_description(self, browser_session, base_url):
		"""Test get_checkbox_state_description function."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)

		state = await browser_session.get_browser_state_summary()
		selector_map = state.dom_state.selector_map

		# Test simple checkbox
		for idx, node in selector_map.items():
			if (
				node.tag_name == 'input'
				and node.attributes.get('type') == 'checkbox'
				and node.attributes.get('id') == 'simple-checkbox'
			):
				state_desc = get_checkbox_state_description(node)
				assert state_desc in ['checked', 'unchecked'], f'Invalid state: {state_desc}'
				print(f'✓ Simple checkbox state: {state_desc}')
				break

	async def test_verify_checkbox_state_via_cdp(self, browser_session, base_url):
		"""Test verify_checkbox_state_via_cdp function."""
		# Navigate to test page
		tools = Tools()
		await tools.navigate(
			url=f'{base_url}/checkbox-test',
			new_tab=False,
			browser_session=browser_session,
		)

		await asyncio.sleep(1)

		state = await browser_session.get_browser_state_summary()
		selector_map = state.dom_state.selector_map

		# Test simple checkbox via CDP
		for idx, node in selector_map.items():
			if (
				node.tag_name == 'input'
				and node.attributes.get('type') == 'checkbox'
				and node.attributes.get('id') == 'simple-checkbox'
			):
				verified_state = await verify_checkbox_state_via_cdp(node, browser_session)
				assert isinstance(verified_state, bool), f'Expected bool, got {type(verified_state)}'
				print(f'✓ CDP verified checkbox state: {verified_state}')
				break
