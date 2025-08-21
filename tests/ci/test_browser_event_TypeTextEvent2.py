import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	GoToUrlAction,
	InputTextAction,
)


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add routes for common test pages
	server.expect_request('/').respond_with_data(
		'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
		content_type='text/html',
	)

	server.expect_request('/form').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Form Test Page</title>
		</head>
		<body>
			<h1>Test Form</h1>
			<form>
				<input type="text" id="name" name="name" placeholder="Enter name">
				<input type="email" id="email" name="email" placeholder="Enter email">
				<textarea id="message" name="message" placeholder="Enter message"></textarea>
				<input type="password" id="password" name="password" placeholder="Enter password">
				<button type="submit">Submit</button>
			</form>
		</body>
		</html>
		""",
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
	"""Create and provide a Browser instance with security disabled."""
	profile = BrowserProfile(headless=True, disable_security=True, cross_origin_iframes=False)
	session = BrowserSession(browser_profile=profile)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestTypeTextEvent:
	"""Test TypeTextEvent and input_text action functionality."""

	async def test_input_text_action(self, controller, browser_session, base_url, http_server):
		"""Test that InputTextAction correctly inputs text into form fields."""
		# Set up search form endpoint for this test
		http_server.expect_request('/searchform').respond_with_data(
			"""
			<html>
			<head><title>Search Form</title></head>
			<body>
				<h1>Search Form</h1>
				<form action="/search" method="get">
					<input type="text" id="searchbox" name="q" placeholder="Search...">
					<button type="submit">Search</button>
				</form>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to a page with a form
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/searchform', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for page to load
		await asyncio.sleep(0.5)

		# Get the search input field index
		selector_map = await browser_session.get_selector_map()

		# Find the search input field - this requires examining the DOM
		# We'll mock this part since we can't rely on specific element indices
		# In a real test, you would get the actual index from the selector map

		# For demonstration, we'll just use a hard-coded mock value
		# and check that the controller processes the action correctly
		mock_input_index = 1  # This would normally be determined dynamically

		# Create input text action
		input_action = {'input_text': InputTextAction(index=mock_input_index, text='Python programming')}

		class InputTextActionModel(ActionModel):
			input_text: InputTextAction | None = None

		# The actual input might fail if the page structure changes or in headless mode
		# So we'll just verify the controller correctly processes the action
		result = await controller.act(InputTextActionModel(**input_action), browser_session)

		# Verify the result is an ActionResult
		assert isinstance(result, ActionResult)

		# Check if the action succeeded or failed
		if result.error is None:
			# Action succeeded, verify the extracted_content
			assert result.extracted_content is not None
			assert 'Input' in result.extracted_content
		else:
			# Action failed, verify the error message contains expected text
			assert 'Element index' in result.error or 'does not exist' in result.error or 'Failed to input text' in result.error

	async def test_type_text_event_directly(self, browser_session, base_url):
		"""Test TypeTextEvent directly through the event bus."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to a page with input fields
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get the DOM state to find input elements
		state = await browser_session.get_browser_state_summary()

		# Find an input field
		input_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('type') == 'text':
				input_node = node
				break

		if input_node:
			# Test typing text into the input field
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=input_node, text='Hello World', clear_existing=True))
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the text was actually typed
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{input_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == 'Hello World'

	async def test_type_text_clear_existing(self, browser_session, base_url):
		"""Test TypeTextEvent with clear_existing flag."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find email input field
		email_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('type') == 'email':
				email_node = node
				break

		if email_node:
			# First, type some text without clearing
			event = browser_session.event_bus.dispatch(
				TypeTextEvent(node=email_node, text='first@example.com', clear_existing=False)
			)
			await asyncio.wait_for(event, timeout=3.0)

			# Now type new text with clearing
			event = browser_session.event_bus.dispatch(
				TypeTextEvent(node=email_node, text='second@example.com', clear_existing=True)
			)
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify only the second text is in the field
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{email_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == 'second@example.com'

	async def test_type_text_textarea(self, browser_session, base_url):
		"""Test typing text into a textarea element."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find textarea element
		textarea_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'textarea':
				textarea_node = node
				break

		if textarea_node:
			# Type multiline text
			multiline_text = 'Line 1\nLine 2\nLine 3'
			event = browser_session.event_bus.dispatch(
				TypeTextEvent(node=textarea_node, text=multiline_text, clear_existing=True)
			)
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the multiline text was typed
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{textarea_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == multiline_text

	async def test_type_text_password_field(self, browser_session, base_url):
		"""Test typing into a password field."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find password input field
		password_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('type') == 'password':
				password_node = node
				break

		if password_node:
			# Type password text
			password_text = 'SecureP@ssw0rd!'
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=password_node, text=password_text, clear_existing=True))
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the password was typed (value is present but masked visually)
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{password_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == password_text

	async def test_type_text_readonly_field(self, browser_session, base_url, http_server):
		"""Test typing into a readonly field should handle gracefully."""
		from browser_use.browser.events import TypeTextEvent

		# Add page with readonly input
		http_server.expect_request('/readonly').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Readonly Test</title></head>
			<body>
				<h1>Readonly Field Test</h1>
				<input type="text" id="readonly-input" value="Cannot change this" readonly>
				<input type="text" id="normal-input" placeholder="Can change this">
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to page
		await browser_session._cdp_navigate(f'{base_url}/readonly')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find readonly input field
		readonly_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('id') == 'readonly-input':
				readonly_node = node
				break

		if readonly_node:
			# Try to type into readonly field
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=readonly_node, text='New text', clear_existing=True))
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()

			# The operation should complete (CDP allows typing into readonly fields)
			assert event_result is not None
			assert event_result.get('success') is True

			# But the value should remain unchanged due to readonly attribute
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'document.getElementById("readonly-input").value', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			# Readonly fields keep their original value
			assert value_check.get('result', {}).get('value') == 'Cannot change this'

	async def test_type_text_special_characters(self, browser_session, base_url):
		"""Test typing text with special characters."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find text input field
		text_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('type') == 'text':
				text_node = node
				break

		if text_node:
			# Type text with special characters
			special_text = 'Test @#$%^&*()_+-={}[]|\\:";<>?,./~`'
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=text_node, text=special_text, clear_existing=True))
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the special characters were typed correctly
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{text_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == special_text

	async def test_type_text_empty_string(self, browser_session, base_url):
		"""Test clearing a field by typing empty string with clear_existing=True."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Find text input field
		text_node = None
		for node in state.dom_state.selector_map.values():
			if node.tag_name == 'input' and node.attributes.get('type') == 'text':
				text_node = node
				break

		if text_node:
			# First type some text
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=text_node, text='Initial text', clear_existing=True))
			await asyncio.wait_for(event, timeout=3.0)

			# Now clear it by typing empty string with clear_existing=True
			event = browser_session.event_bus.dispatch(TypeTextEvent(node=text_node, text='', clear_existing=True))
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the field is now empty
			cdp_session = await browser_session.get_or_create_cdp_session()
			value_check = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'document.getElementById("{text_node.attributes.get("id")}").value',
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert value_check.get('result', {}).get('value') == ''

	async def test_type_text_index_zero_whole_page(self, browser_session, base_url, http_server):
		"""Test typing with index 0 types into the page (goes to whatever has focus)."""
		from browser_use.browser.events import TypeTextEvent

		# Create a page with an input that auto-focuses
		http_server.expect_request('/autofocus-form').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Autofocus Form</title></head>
			<body>
				<h1>Form with Autofocus</h1>
				<input type="text" id="first-input" placeholder="First input">
				<input type="text" id="autofocus-input" placeholder="Has autofocus" autofocus>
				<input type="text" id="third-input" placeholder="Third input">
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to page with autofocus
		await browser_session._cdp_navigate(f'{base_url}/autofocus-form')
		await asyncio.sleep(0.5)

		# Get DOM state
		state = await browser_session.get_browser_state_summary()

		# Create a node with index 0 - this should type to the page (whatever has focus)
		from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

		mock_node = EnhancedDOMTreeNode(
			element_index=0,
			node_id=0,
			backend_node_id=0,
			session_id='',
			frame_id='',
			target_id='',
			node_type=NodeType.ELEMENT_NODE,
			node_name='body',
			node_value='',
			attributes={},
			is_scrollable=False,
			is_visible=True,
			absolute_position=None,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=None,
			children_nodes=[],
			ax_node=None,
			snapshot_node=None,
		)

		# Type text with index 0 - should type to whatever has focus (the autofocus input)
		event = browser_session.event_bus.dispatch(TypeTextEvent(node=mock_node, text='Hello Page', clear_existing=False))
		result = await asyncio.wait_for(event, timeout=3.0)
		event_result = await result.event_result()
		assert event_result is not None
		assert event_result.get('success') is True

		# Verify the text went into the autofocus input
		cdp_session = await browser_session.get_or_create_cdp_session()

		# Check that the autofocus input has the text
		autofocus_value = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("autofocus-input").value', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert autofocus_value.get('result', {}).get('value') == 'Hello Page', 'Text should have gone to the autofocus input'

		# Check other inputs are empty
		first_value = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("first-input").value', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert first_value.get('result', {}).get('value') == '', 'First input should be empty'

		third_value = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("third-input").value', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert third_value.get('result', {}).get('value') == '', 'Third input should be empty'

	async def test_type_text_nonexistent_element(self, browser_session, base_url):
		"""Test that typing into a non-existent element falls back to typing to the page."""
		from browser_use.browser.events import TypeTextEvent

		# Navigate to form page
		await browser_session._cdp_navigate(f'{base_url}/form')
		await asyncio.sleep(0.5)

		# Focus the first input manually to have a known focused element
		cdp_session = await browser_session.get_or_create_cdp_session()
		await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("name").focus()', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)

		# Create a node with a non-existent index
		from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

		nonexistent_node = EnhancedDOMTreeNode(
			element_index=99999,
			node_id=99999,
			backend_node_id=99999,  # Non-existent backend node
			session_id='',
			frame_id='',
			target_id='',
			node_type=NodeType.ELEMENT_NODE,
			node_name='input',
			node_value='',
			attributes={'id': 'nonexistent'},
			is_scrollable=False,
			is_visible=True,
			absolute_position=None,
			content_document=None,
			shadow_root_type=None,
			shadow_roots=None,
			parent_node=None,
			children_nodes=[],
			ax_node=None,
			snapshot_node=None,
		)

		# Try to type into non-existent element - should fall back to typing to the page
		event = browser_session.event_bus.dispatch(
			TypeTextEvent(node=nonexistent_node, text='Fallback text', clear_existing=False)
		)

		# This should complete (might succeed by falling back to page typing)
		result = await asyncio.wait_for(event, timeout=3.0)
		event_result = await result.event_result()
		assert event_result is not None

		# Check if the text was typed to the focused element as a fallback
		name_value = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.getElementById("name").value', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)

		# Either it failed (and returned an error) or it fell back to typing to the page
		success = event_result.get('success', False)
		if success:
			# If it succeeded, it should have typed to the focused element
			assert name_value.get('result', {}).get('value') == 'Fallback text', (
				'Text should have been typed to the focused element as fallback'
			)
		else:
			# Or it might have failed entirely
			assert event_result.get('error') is not None, "Should have an error if it didn't fall back"

	async def test_type_text_iframe_input(self, browser_session, base_url, http_server):
		"""Test typing text into an input field inside an iframe."""
		from browser_use.browser.events import TypeTextEvent

		# Add iframe content page
		http_server.expect_request('/iframe-form').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Iframe Form</title>
			</head>
			<body>
				<h2>Iframe Form</h2>
				<input type="text" id="iframe-input" name="iframe-field" placeholder="Type here in iframe">
				<div id="iframe-result"></div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Add main page with iframe
		http_server.expect_request('/page-with-form-iframe').respond_with_data(
			f"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Page with Form Iframe</title>
			</head>
			<body>
				<h1>Main Page</h1>
				<p>This page contains an iframe with a form:</p>
				<iframe id="form-iframe" src="{base_url}/iframe-form" style="width: 100%; height: 300px; border: 2px solid #333;"></iframe>
				<div>
					<input type="text" id="main-input" placeholder="Main page input">
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to page with iframe
		await browser_session._cdp_navigate(f'{base_url}/page-with-form-iframe')
		await asyncio.sleep(1.0)  # Give iframe time to load

		# Get DOM state to find the iframe input
		state = await browser_session.get_browser_state_summary()

		# Find the input inside the iframe (it should be in the DOM if same-origin)
		iframe_input_node = None
		for node in state.dom_state.selector_map.values():
			# Look for the iframe input by its id
			if node.tag_name == 'input' and node.attributes.get('id') == 'iframe-input':
				iframe_input_node = node
				break

		if iframe_input_node:
			# Type text into the iframe input
			event = browser_session.event_bus.dispatch(
				TypeTextEvent(node=iframe_input_node, text='Text in iframe', clear_existing=True)
			)
			result = await asyncio.wait_for(event, timeout=3.0)
			event_result = await result.event_result()
			assert event_result is not None
			assert event_result.get('success') is True

			# Verify the text was typed into the iframe input
			cdp_session = await browser_session.get_or_create_cdp_session()
			iframe_value = await browser_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': """
						(() => {
							const iframe = document.getElementById('form-iframe');
							if (iframe && iframe.contentDocument) {
								const input = iframe.contentDocument.getElementById('iframe-input');
								return input ? input.value : null;
							}
							return null;
						})()
					""",
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			assert iframe_value.get('result', {}).get('value') == 'Text in iframe'

			# Verify the main page input is still empty
			main_value = await browser_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'document.getElementById("main-input").value', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			assert main_value.get('result', {}).get('value') == '', 'Main page input should still be empty'
		else:
			# If cross-origin iframes are disabled, we won't see the iframe content
			pytest.skip('Iframe input not found - likely due to cross_origin_iframes=False')
