"""Tests for custom JavaScript dialog handling in BrowserSession."""

import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.views import DialogEvent, DialogHandlerResult


class TestDialogEvent:
	"""Tests for the DialogEvent model."""

	def test_dialog_event_basic(self):
		"""Test basic DialogEvent creation."""
		event = DialogEvent(type='alert', message='Hello World')
		assert event.type == 'alert'
		assert event.message == 'Hello World'
		assert event.default_prompt is None
		assert event.url is None

	def test_dialog_event_with_all_fields(self):
		"""Test DialogEvent with all fields."""
		event = DialogEvent(
			type='prompt',
			message='Enter your name:',
			default_prompt='John',
			url='https://example.com',
		)
		assert event.type == 'prompt'
		assert event.message == 'Enter your name:'
		assert event.default_prompt == 'John'
		assert event.url == 'https://example.com'

	def test_dialog_event_types(self):
		"""Test all dialog types."""
		for dialog_type in ['alert', 'confirm', 'prompt', 'beforeunload']:
			event = DialogEvent(type=dialog_type, message='Test')
			assert event.type == dialog_type


class TestDialogHandlerResult:
	"""Tests for the DialogHandlerResult model."""

	def test_accept_result(self):
		"""Test accept result."""
		result = DialogHandlerResult(accept=True)
		assert result.accept is True
		assert result.prompt_text is None

	def test_dismiss_result(self):
		"""Test dismiss result."""
		result = DialogHandlerResult(accept=False)
		assert result.accept is False
		assert result.prompt_text is None

	def test_result_with_prompt_text(self):
		"""Test result with prompt text."""
		result = DialogHandlerResult(accept=True, prompt_text='my input')
		assert result.accept is True
		assert result.prompt_text == 'my input'


class TestBrowserSessionDialogHandler:
	"""Tests for BrowserSession dialog handler configuration."""

	async def test_default_dialog_handler_behavior(self):
		"""Test that default handler accepts alert, confirm, beforeunload and dismisses prompt."""
		session = BrowserSession(headless=True)

		# Test alert - should accept
		result = await session.handle_dialog(DialogEvent(type='alert', message='Test'))
		assert result.accept is True

		# Test confirm - should accept
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Are you sure?'))
		assert result.accept is True

		# Test beforeunload - should accept
		result = await session.handle_dialog(DialogEvent(type='beforeunload', message='Leave page?'))
		assert result.accept is True

		# Test prompt - should dismiss
		result = await session.handle_dialog(DialogEvent(type='prompt', message='Enter value:'))
		assert result.accept is False

	async def test_custom_sync_handler_returning_bool(self):
		"""Test custom sync handler that returns bool."""

		def my_handler(event: DialogEvent) -> bool:
			# Reject dialogs containing 'delete'
			if 'delete' in event.message.lower():
				return False
			return True

		session = BrowserSession(headless=True, dialog_handler=my_handler)

		# Should accept normal dialog
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Continue?'))
		assert result.accept is True

		# Should reject dialog containing 'delete'
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Delete this item?'))
		assert result.accept is False

	async def test_custom_sync_handler_returning_result(self):
		"""Test custom sync handler that returns DialogHandlerResult."""

		def my_handler(event: DialogEvent) -> DialogHandlerResult:
			if event.type == 'prompt':
				return DialogHandlerResult(accept=True, prompt_text='custom input')
			return DialogHandlerResult(accept=False)

		session = BrowserSession(headless=True, dialog_handler=my_handler)

		# Test prompt - should accept with custom text
		result = await session.handle_dialog(DialogEvent(type='prompt', message='Enter value:'))
		assert result.accept is True
		assert result.prompt_text == 'custom input'

		# Test confirm - should dismiss
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Are you sure?'))
		assert result.accept is False

	async def test_custom_async_handler_returning_bool(self):
		"""Test custom async handler that returns bool."""

		async def my_async_handler(event: DialogEvent) -> bool:
			# Simulate some async operation
			await asyncio.sleep(0.01)
			return event.type == 'alert'

		session = BrowserSession(headless=True, dialog_handler=my_async_handler)

		# Alert should be accepted
		result = await session.handle_dialog(DialogEvent(type='alert', message='Info'))
		assert result.accept is True

		# Confirm should be rejected
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Continue?'))
		assert result.accept is False

	async def test_custom_async_handler_returning_result(self):
		"""Test custom async handler that returns DialogHandlerResult."""

		async def my_async_handler(event: DialogEvent) -> DialogHandlerResult:
			await asyncio.sleep(0.01)
			if event.type == 'prompt' and event.default_prompt:
				return DialogHandlerResult(accept=True, prompt_text=event.default_prompt.upper())
			return DialogHandlerResult(accept=True)

		session = BrowserSession(headless=True, dialog_handler=my_async_handler)

		# Prompt with default should use uppercase default
		result = await session.handle_dialog(DialogEvent(type='prompt', message='Enter name:', default_prompt='john'))
		assert result.accept is True
		assert result.prompt_text == 'JOHN'

	async def test_handler_based_on_url(self):
		"""Test handler that makes decisions based on URL."""

		def url_aware_handler(event: DialogEvent) -> bool:
			# Reject all dialogs from untrusted domains
			if event.url and 'untrusted.com' in event.url:
				return False
			return True

		session = BrowserSession(headless=True, dialog_handler=url_aware_handler)

		# Trusted URL should accept
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Proceed?', url='https://trusted.com/page'))
		assert result.accept is True

		# Untrusted URL should reject
		result = await session.handle_dialog(DialogEvent(type='confirm', message='Proceed?', url='https://untrusted.com/page'))
		assert result.accept is False


@pytest.fixture(scope='module')
async def browser_session_for_dialogs():
	"""Create a browser session for dialog tests."""
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


class TestDialogHandlerIntegration:
	"""Integration tests for dialog handling with real browser."""

	async def test_alert_dialog_default_handling(self, browser_session_for_dialogs, httpserver: HTTPServer):
		"""Test that alert dialogs are handled by default."""
		# Set up a page with an alert
		httpserver.expect_request('/alert').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Alert Test</title></head>
			<body>
				<h1>Alert Test</h1>
				<button id="show-alert" onclick="alert('Hello from alert!')">Show Alert</button>
				<p id="after-alert">Alert was handled</p>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		session = browser_session_for_dialogs
		base_url = f'http://{httpserver.host}:{httpserver.port}'

		# Navigate to the page
		await session.navigate_to(f'{base_url}/alert')
		await asyncio.sleep(0.5)

		# Get browser state to trigger DOM processing
		await session.get_browser_state_summary()

		# Click the button that shows an alert (find by tag_name)
		selector_map = await session.get_selector_map()
		button_index = None
		for idx, element in selector_map.items():
			# Find button by id attribute or ax_node name
			if element.tag_name.lower() == 'button':
				is_show_alert = element.attributes.get('id') == 'show-alert' or (
					element.ax_node and element.ax_node.name == 'Show Alert'
				)
				if is_show_alert:
					button_index = idx
					break

		if button_index is not None:
			from browser_use.tools.service import Tools

			tools = Tools()
			await tools.click(index=button_index, browser_session=session)
			await asyncio.sleep(0.5)

			# If the alert was handled, it should be in closed_popup_messages
			state = await session.get_browser_state_summary()
			assert any('Hello from alert!' in msg for msg in state.closed_popup_messages), (
				f'Expected alert message in closed_popup_messages, got: {state.closed_popup_messages}'
			)
			# Page should still be accessible
			assert f'{base_url}/alert' in state.url

	async def test_confirm_dialog_default_handling(self, browser_session_for_dialogs, httpserver: HTTPServer):
		"""Test that confirm dialogs are accepted by default."""
		# Set up a page with a confirm dialog
		httpserver.expect_request('/confirm').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Confirm Test</title></head>
			<body>
				<h1>Confirm Test</h1>
				<button id="show-confirm" onclick="
					var result = confirm('Do you want to proceed?');
					document.getElementById('result').textContent = result ? 'Confirmed' : 'Cancelled';
				">Show Confirm</button>
				<p id="result">Waiting...</p>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		session = browser_session_for_dialogs
		base_url = f'http://{httpserver.host}:{httpserver.port}'

		# Navigate to the page
		await session.navigate_to(f'{base_url}/confirm')
		await asyncio.sleep(0.5)

		# Get browser state
		await session.get_browser_state_summary()

		# Click the button that shows a confirm dialog
		selector_map = await session.get_selector_map()
		button_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'button':
				is_show_confirm = element.attributes.get('id') == 'show-confirm' or (
					element.ax_node and element.ax_node.name == 'Show Confirm'
				)
				if is_show_confirm:
					button_index = idx
					break

		if button_index is not None:
			from browser_use.tools.service import Tools

			tools = Tools()
			await tools.click(index=button_index, browser_session=session)
			await asyncio.sleep(0.5)

			# Check that confirm was accepted (default behavior)
			cdp_session = await session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			# The result should be 'Confirmed' since default handler accepts confirm dialogs
			result_text = result.get('result', {}).get('value', '')
			assert result_text == 'Confirmed', f"Expected 'Confirmed' but got '{result_text}'"

	async def test_custom_dialog_handler_with_session(self, httpserver: HTTPServer):
		"""Test custom dialog handler with a real browser session."""
		# Track which dialogs were seen
		dialogs_seen: list[DialogEvent] = []

		def tracking_handler(event: DialogEvent) -> bool:
			dialogs_seen.append(event)
			# Reject confirm dialogs
			return event.type != 'confirm'

		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			),
			dialog_handler=tracking_handler,
		)

		try:
			await session.start()

			# Set up a page with a confirm dialog
			httpserver.expect_request('/custom-handler').respond_with_data(
				"""
				<!DOCTYPE html>
				<html>
				<head><title>Custom Handler Test</title></head>
				<body>
					<h1>Custom Handler Test</h1>
					<button id="show-confirm" onclick="
						var result = confirm('Custom handler test');
						document.getElementById('result').textContent = result ? 'Confirmed' : 'Cancelled';
					">Show Confirm</button>
					<p id="result">Waiting...</p>
				</body>
				</html>
				""",
				content_type='text/html',
			)

			base_url = f'http://{httpserver.host}:{httpserver.port}'
			await session.navigate_to(f'{base_url}/custom-handler')
			await asyncio.sleep(0.5)

			# Get browser state
			await session.get_browser_state_summary()

			# Click the button
			selector_map = await session.get_selector_map()
			button_index = None
			for idx, element in selector_map.items():
				if element.tag_name.lower() == 'button':
					is_show_confirm = element.attributes.get('id') == 'show-confirm' or (
						element.ax_node and element.ax_node.name == 'Show Confirm'
					)
					if is_show_confirm:
						button_index = idx
						break

			if button_index is not None:
				from browser_use.tools.service import Tools

				tools = Tools()
				await tools.click(index=button_index, browser_session=session)
				await asyncio.sleep(0.5)

				# Check that confirm was rejected by custom handler
				cdp_session = await session.get_or_create_cdp_session()
				result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
					session_id=cdp_session.session_id,
				)
				result_text = result.get('result', {}).get('value', '')
				assert result_text == 'Cancelled', f"Expected 'Cancelled' but got '{result_text}'"

				# Verify the dialog was tracked (may be called multiple times due to CDP registration)
				assert len(dialogs_seen) >= 1, 'Expected at least one dialog to be tracked'
				assert dialogs_seen[0].type == 'confirm'
				assert dialogs_seen[0].message == 'Custom handler test'
		finally:
			await session.kill()
			await session.event_bus.stop(clear=True, timeout=5)
