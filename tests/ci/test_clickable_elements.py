"""
Tests for clickable element detection, particularly for UI framework components like Ant Design.

Issue #3742: <span> and <label> elements not detected as interactive - breaks Ant Design support
"""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession


@pytest.fixture(scope='module')
async def browser_session():
	"""Create a real browser session for testing"""
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
	await session.event_bus.stop(clear=True, timeout=5)


class TestClickableElementDetection:
	"""Tests for the ClickableElementDetector in dom/serializer/clickable_elements.py"""

	async def test_label_without_for_attribute_is_interactive(self, browser_session, httpserver: HTTPServer):
		"""
		Labels WITHOUT a 'for' attribute that wrap interactive elements (like in Ant Design)
		should be detected as interactive.

		Ant Design radio buttons render like:
		<label class="ant-radio-button-wrapper">
			<span class="ant-radio-button">
				<input type="radio" />
			</span>
			<span>Option Text</span>
		</label>
		"""
		httpserver.expect_request('/ant-design-radio').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Ant Design Radio Test</title>
				<style>
					.ant-radio-button-wrapper {
						cursor: pointer;
						display: inline-block;
						padding: 8px 16px;
						border: 1px solid #d9d9d9;
					}
					.ant-radio-button-input {
						position: absolute;
						opacity: 0;
					}
				</style>
			</head>
			<body>
				<div class="radio-group">
					<label class="ant-radio-button-wrapper">
						<span class="ant-radio-button">
							<input type="radio" class="ant-radio-button-input" name="template" value="dueros" />
						</span>
						<span>DuerOS Template</span>
					</label>
					<label class="ant-radio-button-wrapper">
						<span class="ant-radio-button">
							<input type="radio" class="ant-radio-button-input" name="template" value="custom" />
						</span>
						<span>Custom Template</span>
					</label>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		base_url = f'http://{httpserver.host}:{httpserver.port}'
		await browser_session.navigate_to(f'{base_url}/ant-design-radio')
		await asyncio.sleep(0.5)

		# Get browser state to populate selector map
		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Find all label elements in the selector map
		label_elements = [(idx, elem) for idx, elem in selector_map.items() if elem.tag_name.lower() == 'label']

		# We should find at least the two labels without 'for' attribute
		assert len(label_elements) >= 2, (
			f'Expected at least 2 label elements to be detected as interactive, '
			f'but found {len(label_elements)}. '
			f'Detected elements: {[(idx, elem.tag_name) for idx, elem in selector_map.items()]}'
		)

		# Verify the labels have the expected text content
		label_texts = [elem.get_all_children_text() for idx, elem in label_elements]
		assert any('DuerOS Template' in text for text in label_texts), (
			f'Expected to find label with "DuerOS Template" text, but got: {label_texts}'
		)
		assert any('Custom Template' in text for text in label_texts), (
			f'Expected to find label with "Custom Template" text, but got: {label_texts}'
		)

	async def test_label_with_for_attribute_is_not_interactive(self, browser_session, httpserver: HTTPServer):
		"""
		Labels WITH a 'for' attribute should NOT be detected as interactive
		(to avoid the apartments.com issue where labels with 'for' can interfere with the actual input).
		"""
		httpserver.expect_request('/label-with-for').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Label With For Test</title>
				<style>
					label { cursor: pointer; }
				</style>
			</head>
			<body>
				<form>
					<label for="username">Username:</label>
					<input type="text" id="username" name="username" />

					<label for="password">Password:</label>
					<input type="password" id="password" name="password" />
				</form>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		base_url = f'http://{httpserver.host}:{httpserver.port}'
		await browser_session.navigate_to(f'{base_url}/label-with-for')
		await asyncio.sleep(0.5)

		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Labels with 'for' attribute should NOT be in the selector map
		label_elements = [
			(idx, elem) for idx, elem in selector_map.items() if elem.tag_name.lower() == 'label' and elem.attributes.get('for')
		]

		# The inputs should be detected, but not the labels with 'for'
		assert len(label_elements) == 0, (
			f'Labels with "for" attribute should NOT be detected as interactive, '
			f'but found: {[(idx, elem.attributes) for idx, elem in label_elements]}'
		)

		# Verify inputs ARE detected
		input_elements = [(idx, elem) for idx, elem in selector_map.items() if elem.tag_name.lower() == 'input']
		assert len(input_elements) >= 2, f'Expected at least 2 input elements, found {len(input_elements)}'

	async def test_span_with_cursor_pointer_is_interactive(self, browser_session, httpserver: HTTPServer):
		"""
		Span elements with cursor: pointer style should be detected as interactive.
		This is important for many UI frameworks that use styled spans as buttons.
		"""
		httpserver.expect_request('/clickable-spans').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Clickable Spans Test</title>
				<style>
					.clickable-span {
						cursor: pointer;
						padding: 8px 16px;
						background: #1890ff;
						color: white;
						border-radius: 4px;
						display: inline-block;
					}
					.non-clickable-span {
						padding: 8px 16px;
						background: #f0f0f0;
					}
				</style>
			</head>
			<body>
				<div>
					<span class="clickable-span">Click Me</span>
					<span class="non-clickable-span">Just Text</span>
					<span class="clickable-span">Another Button</span>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		base_url = f'http://{httpserver.host}:{httpserver.port}'
		await browser_session.navigate_to(f'{base_url}/clickable-spans')
		await asyncio.sleep(0.5)

		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Find span elements with 'clickable-span' class
		clickable_spans = [
			(idx, elem)
			for idx, elem in selector_map.items()
			if elem.tag_name.lower() == 'span' and 'clickable-span' in elem.attributes.get('class', '')
		]

		# Should find both clickable spans
		assert len(clickable_spans) >= 2, (
			f'Expected at least 2 clickable span elements, but found {len(clickable_spans)}. '
			f'Detected elements: {[(idx, elem.tag_name, elem.attributes.get("class", "")) for idx, elem in selector_map.items()]}'
		)

		# Verify the text content
		span_texts = [elem.get_all_children_text() for idx, elem in clickable_spans]
		assert any('Click Me' in text for text in span_texts), (
			f'Expected to find span with "Click Me" text, but got: {span_texts}'
		)

	async def test_ant_design_checkbox_detection(self, browser_session, httpserver: HTTPServer):
		"""
		Test detection of Ant Design-style checkbox components where
		the checkbox text is inside a span within a label.
		"""
		httpserver.expect_request('/ant-design-checkbox').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Ant Design Checkbox Test</title>
				<style>
					.ant-checkbox-wrapper {
						cursor: pointer;
						display: inline-flex;
						align-items: center;
						margin-right: 8px;
					}
					.ant-checkbox-input {
						position: absolute;
						opacity: 0;
					}
					.ant-checkbox-inner {
						width: 16px;
						height: 16px;
						border: 1px solid #d9d9d9;
						border-radius: 2px;
					}
				</style>
			</head>
			<body>
				<div class="checkbox-group">
					<label class="ant-checkbox-wrapper">
						<span class="ant-checkbox">
							<input type="checkbox" class="ant-checkbox-input" />
							<span class="ant-checkbox-inner"></span>
						</span>
						<span>Remember me</span>
					</label>
					<label class="ant-checkbox-wrapper">
						<span class="ant-checkbox">
							<input type="checkbox" class="ant-checkbox-input" />
							<span class="ant-checkbox-inner"></span>
						</span>
						<span>Accept terms</span>
					</label>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		base_url = f'http://{httpserver.host}:{httpserver.port}'
		await browser_session.navigate_to(f'{base_url}/ant-design-checkbox')
		await asyncio.sleep(0.5)

		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Find label elements (the main interactive component)
		label_elements = [(idx, elem) for idx, elem in selector_map.items() if elem.tag_name.lower() == 'label']

		# We should find both checkbox wrapper labels
		assert len(label_elements) >= 2, (
			f'Expected at least 2 label elements for checkboxes, but found {len(label_elements)}. '
			f'Detected elements: {[(idx, elem.tag_name) for idx, elem in selector_map.items()]}'
		)

		# Verify the text content is properly extracted
		label_texts = [elem.get_all_children_text() for idx, elem in label_elements]
		assert any('Remember me' in text for text in label_texts), (
			f'Expected to find label with "Remember me" text, but got: {label_texts}'
		)
		assert any('Accept terms' in text for text in label_texts), (
			f'Expected to find label with "Accept terms" text, but got: {label_texts}'
		)
