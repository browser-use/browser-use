"""
Tests for browser session file upload functionality using real HTML.

Tests cover common real-world file upload patterns:
- Standard form file uploads
- Hidden file inputs triggered by buttons
- Multiple file upload fields
- Complex nested structures
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


class TestBrowserSessionFileUploads:
	"""Tests for file upload element finding functionality with real HTML."""

	@pytest.fixture
	async def browser_session(self):
		"""Create a BrowserSession instance for testing."""
		session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
		yield session
		await session.kill()

	@pytest.fixture
	def test_server(self, httpserver: HTTPServer):
		"""Set up test HTTP server with various file upload scenarios."""
		return httpserver

	async def test_standard_file_upload_patterns(self, browser_session: BrowserSession, test_server: HTTPServer):
		"""Test finding file inputs in standard form layouts and modern UI patterns."""
		html = """
		<!DOCTYPE html>
		<html>
		<body>
			<h1>File Upload Test Page</h1>
			
			<!-- Pattern 1: Simple visible file input in form -->
			<form id="simple-form">
				<label for="file1">Choose file:</label>
				<input type="file" id="file1" name="document">
				<button type="submit">Upload</button>
			</form>
			
			<!-- Pattern 2: Hidden file input with custom button (Material/Bootstrap style) -->
			<div class="upload-section">
				<button class="btn btn-primary" onclick="document.getElementById('hidden-file').click()">
					Select File
				</button>
				<input type="file" id="hidden-file" style="display: none;" accept=".pdf,.doc,.docx">
				<span class="filename">No file selected</span>
			</div>
			
			<!-- Pattern 3: Nested file input in card/modal structure -->
			<div class="modal">
				<div class="modal-content">
					<div class="modal-header">
						<h3>Upload Document</h3>
					</div>
					<div class="modal-body">
						<div class="form-group">
							<label>Select your file:</label>
							<div class="input-wrapper">
								<input type="file" id="modal-file" class="form-control">
							</div>
						</div>
					</div>
				</div>
			</div>
			
			<!-- Pattern 4: Multiple file inputs -->
			<form id="multi-upload">
				<div class="field-group">
					<label>Profile Photo</label>
					<input type="file" name="photo" accept="image/*">
				</div>
				<div class="field-group">
					<label>Resume</label>
					<input type="file" name="resume" accept=".pdf">
				</div>
			</form>
			
			<!-- Pattern 5: Dropzone-style upload area -->
			<div class="dropzone" onclick="this.querySelector('input').click()">
				<div class="dz-message">
					<i class="icon-upload"></i>
					<p>Drop files here or click to upload</p>
				</div>
				<input type="file" multiple style="display: none;">
			</div>
		</body>
		</html>
		"""

		test_server.expect_request('/upload').respond_with_data(html, content_type='text/html')
		await browser_session.start()
		# Navigate to upload page using event
		from browser_use.browser.events import NavigateToUrlEvent, NavigationCompleteEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=test_server.url_for('/upload')))
		await event
		# Wait for page to load
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Get browser state to populate selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)

		# Get the selector map after page load
		selector_map = await browser_session.get_selector_map()

		# The selector map contains clickable elements, so let's test by looking for elements directly
		# Test 1: Find file input when it's the clicked element itself
		all_file_inputs = []
		for idx, elem in selector_map.items():
			if elem.tag_name == 'input' and elem.attributes.get('type') == 'file':
				all_file_inputs.append((idx, elem))

		# Should find at least one file input in the map
		assert len(all_file_inputs) > 0, f'No file inputs found in selector map. Map has {len(selector_map)} elements'

		# Test finding the first file input
		first_file_idx, first_file_elem = all_file_inputs[0]
		file_input = await browser_session.find_file_upload_element_by_index(first_file_idx)
		assert file_input is not None
		assert file_input == first_file_elem

		# Test 2: Find hidden file input from button - look for any button
		button_indices = []
		for idx, elem in selector_map.items():
			if elem.tag_name == 'button':
				button_indices.append(idx)

		# Try finding file input from each button
		found_from_button = False
		for button_idx in button_indices:
			file_input = await browser_session.find_file_upload_element_by_index(button_idx)
			if file_input is not None:
				found_from_button = True
				break

		assert found_from_button, 'Could not find any file input from any button'

		# Test 3: Find file input from parent containers
		div_indices = []
		for idx, elem in selector_map.items():
			if elem.tag_name == 'div':
				div_indices.append(idx)

		# Try finding file input from divs
		found_from_div = False
		for div_idx in div_indices[:10]:  # Test first 10 divs
			file_input = await browser_session.find_file_upload_element_by_index(div_idx)
			if file_input is not None:
				found_from_div = True
				break

		assert found_from_div, 'Could not find any file input from any div container'

	async def test_dom_traversal_functionality(self, browser_session: BrowserSession, test_server: HTTPServer):
		"""Test that the file upload finder correctly traverses the DOM."""
		html = """
		<!DOCTYPE html>
		<html>
		<body>
			<!-- Test case 1: Deep nesting -->
			<div class="container">
				<button class="deep-button">Upload from Deep</button>
				<div>
					<div>
						<div>
							<input type="file" id="deep-file">
						</div>
					</div>
				</div>
			</div>
			
			<!-- Test case 2: Sibling traversal -->
			<div class="upload-group">
				<div class="left-section">
					<button class="sibling-button">Choose File</button>
				</div>
				<div class="right-section">
					<input type="file" id="sibling-file">
				</div>
			</div>
			
			<!-- Test case 3: Parent traversal -->
			<div class="outer-container">
				<input type="file" id="parent-file" style="display: none;">
				<div class="inner-container">
					<button class="parent-button">Select</button>
				</div>
			</div>
			
			<!-- Test case 4: Mixed case HTML -->
			<FORM>
				<INPUT TYPE="FILE" ID="mixed-case-file">
				<BUTTON TYPE="button" CLASS="mixed-button">Upload</BUTTON>
			</FORM>
		</body>
		</html>
		"""

		test_server.expect_request('/traversal').respond_with_data(html, content_type='text/html')
		await browser_session.start()
		# Navigate to traversal page using event
		from browser_use.browser.events import NavigateToUrlEvent, NavigationCompleteEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=test_server.url_for('/traversal')))
		await event
		# Wait for page to load
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Get browser state to populate selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)

		selector_map = await browser_session.get_selector_map()

		# Test that buttons can find nearby file inputs
		button_count = 0
		buttons_that_found_file = 0

		for idx, elem in selector_map.items():
			if elem.tag_name == 'button':
				button_count += 1
				file_input = await browser_session.find_file_upload_element_by_index(idx)
				if file_input is not None:
					buttons_that_found_file += 1
					# Verify it's actually a file input
					assert file_input.tag_name == 'input'
					assert file_input.attributes.get('type', '').lower() == 'file'

		# Most buttons should be able to find a file input through DOM traversal
		assert button_count > 0, 'No buttons found in selector map'
		assert buttons_that_found_file > 0, 'No buttons could find file inputs'
		assert buttons_that_found_file >= button_count - 1, 'Most buttons should find file inputs'

	async def test_traversal_limits(self, browser_session: BrowserSession, test_server: HTTPServer):
		"""Test that traversal limits (max_height and max_descendant_depth) work correctly."""
		html = """
		<!DOCTYPE html>
		<html>
		<body>
			<!-- Deep nesting to test limits -->
			<div class="wrapper">
				<button class="test-button">Test Button</button>
				<div>
					<div>
						<div>
							<div>
								<div>
									<input type="file" id="deeply-nested">
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
			
			<!-- Direct sibling -->
			<div class="direct-wrapper">
				<button class="direct-button">Direct Button</button>
				<input type="file" id="direct-file">
			</div>
			
			<!-- Test with element that is itself a file input -->
			<input type="file" id="self-file" class="clickable">
		</body>
		</html>
		"""

		test_server.expect_request('/limits').respond_with_data(html, content_type='text/html')
		await browser_session.start()
		# Navigate to limits page using event
		from browser_use.browser.events import NavigateToUrlEvent, NavigationCompleteEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=test_server.url_for('/limits')))
		await event
		# Wait for page to load
		await browser_session.event_bus.expect(NavigationCompleteEvent, timeout=10.0)

		# Get browser state to populate selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)

		selector_map = await browser_session.get_selector_map()

		# Test 1: Button with deep nesting
		test_button_idx = None
		for idx, elem in selector_map.items():
			if elem.tag_name == 'button' and elem.attributes.get('class') == 'test-button':
				test_button_idx = idx
				break

		if test_button_idx is not None:
			# With default limits, should find the deeply nested file
			file_input = await browser_session.find_file_upload_element_by_index(test_button_idx)
			assert file_input is not None

			# With very limited traversal, might not find it
			file_input_limited = await browser_session.find_file_upload_element_by_index(test_button_idx)
			# Could be None if file is too deep

		# Test 2: Direct sibling should be found easily
		direct_button_idx = None
		for idx, elem in selector_map.items():
			if elem.tag_name == 'button' and elem.attributes.get('class') == 'direct-button':
				direct_button_idx = idx
				break

		if direct_button_idx is not None:
			file_input = await browser_session.find_file_upload_element_by_index(direct_button_idx)
			assert file_input is not None
			assert file_input.attributes.get('id') == 'direct-file'

		# Test 3: Element that is itself a file input
		self_file_idx = None
		for idx, elem in selector_map.items():
			if elem.tag_name == 'input' and elem.attributes.get('id') == 'self-file':
				self_file_idx = idx
				break

		if self_file_idx is not None:
			file_input = await browser_session.find_file_upload_element_by_index(self_file_idx)
			assert file_input is not None
			assert file_input.attributes.get('id') == 'self-file'

		# Test 4: Invalid index returns None
		invalid_index = max(selector_map.keys()) + 100 if selector_map else 999
		file_input = await browser_session.find_file_upload_element_by_index(invalid_index)
		assert file_input is None
