"""Test to verify download detection timing issue"""

import os
import time

import pytest

from browser_use.browser import BrowserSession


@pytest.fixture(scope='function')
async def test_server(httpserver):
	"""Setup test HTTP server with a simple page."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Test Page</title>
	</head>
	<body>
		<h1>Test Page</h1>
		<button id="test-button" onclick="document.getElementById('result').innerText = 'Clicked!'">
			Click Me
		</button>
		<p id="result"></p>
		<a href="/download/test.pdf" download>Download PDF</a>
	</body>
	</html>
	"""
	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	httpserver.expect_request('/download/test.pdf').respond_with_data(b'PDF content', content_type='application/pdf')
	return httpserver


async def test_download_detection_timing(test_server, tmp_path):
	"""Test that download detection adds 5 second delay to clicks when downloads_dir is set."""

	# Test 1: With downloads_dir set (default behavior)
	browser_with_downloads = BrowserSession(
		headless=True,
		downloads_dir=str(tmp_path / 'downloads'),
		user_data_dir=None,
	)

	await browser_with_downloads.start()
	page = await browser_with_downloads.get_current_page()
	await page.goto(test_server.url_for('/'))

	# Get the actual DOM state to find the button
	state = await browser_with_downloads.get_state_summary(cache_clickable_elements_hashes=False)

	# Find the button element
	button_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'button' and elem.attributes.get('id') == 'test-button':
			button_node = elem
			break

	assert button_node is not None, 'Could not find button element'

	# Time the click
	start_time = time.time()
	result = await browser_with_downloads._click_element_node(button_node)
	duration_with_downloads = time.time() - start_time

	# Verify click worked
	result_text = await page.locator('#result').text_content()
	assert result_text == 'Clicked!'
	assert result is None  # No download happened

	await browser_with_downloads.close()

	# Test 2: With downloads_dir set to empty string (disables download detection)
	browser_no_downloads = BrowserSession(
		headless=True,
		downloads_dir=None,
		user_data_dir=None,
	)

	await browser_no_downloads.start()
	page = await browser_no_downloads.get_current_page()
	await page.goto(test_server.url_for('/'))

	# Clear previous result
	await page.evaluate('document.getElementById("result").innerText = ""')

	# Get the DOM state again for the new browser session
	state = await browser_no_downloads.get_state_summary(cache_clickable_elements_hashes=False)

	# Find the button element again
	button_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'button' and elem.attributes.get('id') == 'test-button':
			button_node = elem
			break

	assert button_node is not None, 'Could not find button element'

	# Time the click
	start_time = time.time()
	result = await browser_no_downloads._click_element_node(button_node)
	duration_no_downloads = time.time() - start_time

	# Verify click worked
	result_text = await page.locator('#result').text_content()
	assert result_text == 'Clicked!'

	await browser_no_downloads.close()

	# Check timing differences
	print(f'Click with downloads_dir: {duration_with_downloads:.2f}s')
	print(f'Click without downloads_dir: {duration_no_downloads:.2f}s')
	print(f'Difference: {duration_with_downloads - duration_no_downloads:.2f}s')

	# Both should be fast now since we're clicking a button (not a download link)
	assert duration_with_downloads < 8, f'Expected <8s with downloads_dir, got {duration_with_downloads:.2f}s'
	assert duration_no_downloads < 3, f'Expected <3s without downloads_dir, got {duration_no_downloads:.2f}s'


async def test_actual_download_detection(test_server, tmp_path):
	"""Test that actual downloads are detected correctly."""

	downloads_path = tmp_path / 'downloads'
	downloads_path.mkdir()

	browser_session = BrowserSession(
		headless=True,
		downloads_path=str(downloads_path),
		user_data_dir=None,
	)

	await browser_session.start()
	page = await browser_session.get_current_page()
	await page.goto(test_server.url_for('/'))

	# Get the DOM state to find the download link
	state = await browser_session.get_state_summary(cache_clickable_elements_hashes=False)

	# Find the download link element
	download_node = None
	for elem in state.selector_map.values():
		if elem.tag_name == 'a' and 'download' in elem.attributes:
			download_node = elem
			break

	assert download_node is not None, 'Could not find download link element'

	# Click the download link
	start_time = time.time()
	download_path = await browser_session._click_element_node(download_node)
	duration = time.time() - start_time

	# Should return the download path
	assert download_path is not None
	assert 'test.pdf' in download_path
	assert os.path.exists(download_path)

	# Should be relatively fast since download is detected
	assert duration < 2.0, f'Download detection took {duration:.2f}s, expected <2s'

	await browser_session.close()
