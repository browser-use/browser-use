import pytest
from pydantic import BaseModel, Field

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo, MessageManagerState
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage, UserMessage
from browser_use.llm.messages import ContentPartTextParam
from browser_use.tools.registry.service import Registry
from browser_use.utils import is_new_tab_page, match_url_with_domain_pattern


class SensitiveParams(BaseModel):
	"""Test parameter model for sensitive data testing."""

	text: str = Field(description='Text with sensitive data placeholders')


@pytest.fixture
def registry():
	return Registry()


@pytest.fixture
def message_manager():
	import os
	import tempfile
	import uuid

	base_tmp = tempfile.gettempdir()  # e.g., /tmp on Unix
	file_system_path = os.path.join(base_tmp, str(uuid.uuid4()))
	return MessageManager(
		task='Test task',
		system_message=SystemMessage(content='System message'),
		state=MessageManagerState(),
		file_system=FileSystem(file_system_path),
	)


def test_replace_sensitive_data_with_missing_keys(registry, caplog):
	"""Test that _replace_sensitive_data handles missing keys gracefully"""
	# Create a simple Pydantic model with sensitive data placeholders
	params = SensitiveParams(text='Please enter <secret>username</secret> and <secret>password</secret>')

	# Case 1: All keys present - both placeholders should be replaced
	sensitive_data = {'username': 'user123', 'password': 'pass456'}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert result.text == 'Please enter user123 and pass456'
	assert '<secret>' not in result.text  # No secret tags should remain

	# Case 2: One key missing - only available key should be replaced
	sensitive_data = {'username': 'user123'}  # password is missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert result.text == 'Please enter user123 and <secret>password</secret>'
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text  # Missing key's tag remains

	# Case 3: Multiple keys missing - all tags should be preserved
	sensitive_data = {}  # both keys missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert result.text == 'Please enter <secret>username</secret> and <secret>password</secret>'
	assert '<secret>username</secret>' in result.text
	assert '<secret>password</secret>' in result.text

	# Case 4: One key empty - empty values are treated as missing
	sensitive_data = {'username': 'user123', 'password': ''}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert result.text == 'Please enter user123 and <secret>password</secret>'
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text  # Empty value's tag remains


def test_simple_domain_specific_sensitive_data(registry, caplog):
	"""Test the basic functionality of domain-specific sensitive data replacement"""
	# Create a simple Pydantic model with sensitive data placeholders
	params = SensitiveParams(text='Please enter <secret>username</secret> and <secret>password</secret>')

	# Simple test with directly instantiable values
	sensitive_data = {
		'example.com': {'username': 'example_user'},
		'other_data': 'non_secret_value',  # Old format mixed with new
	}

	# Without a URL, domain-specific secrets should NOT be exposed
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert result.text == 'Please enter <secret>username</secret> and <secret>password</secret>'
	assert '<secret>username</secret>' in result.text  # Should NOT be replaced without URL
	assert '<secret>password</secret>' in result.text  # Password is missing in sensitive_data
	assert 'example_user' not in result.text  # Domain-specific value should not appear

	# Test with a matching URL - domain-specific secrets should be exposed
	result = registry._replace_sensitive_data(params, sensitive_data, 'https://example.com/login')
	assert result.text == 'Please enter example_user and <secret>password</secret>'
	assert 'example_user' in result.text  # Should be replaced with matching URL
	assert '<secret>password</secret>' in result.text  # Password is still missing
	assert '<secret>username</secret>' not in result.text  # Username tag should be replaced


def test_match_url_with_domain_pattern():
	"""Test that the domain pattern matching utility works correctly"""

	# Test exact domain matches
	assert match_url_with_domain_pattern('https://example.com', 'example.com') is True
	assert match_url_with_domain_pattern('http://example.com', 'example.com') is False  # Default scheme is now https
	assert match_url_with_domain_pattern('https://google.com', 'example.com') is False

	# Test subdomain pattern matches
	assert match_url_with_domain_pattern('https://sub.example.com', '*.example.com') is True
	assert match_url_with_domain_pattern('https://example.com', '*.example.com') is True  # Base domain should match too
	assert match_url_with_domain_pattern('https://sub.sub.example.com', '*.example.com') is True
	assert match_url_with_domain_pattern('https://example.org', '*.example.com') is False

	# Test protocol pattern matches
	assert match_url_with_domain_pattern('https://example.com', 'http*://example.com') is True
	assert match_url_with_domain_pattern('http://example.com', 'http*://example.com') is True
	assert match_url_with_domain_pattern('ftp://example.com', 'http*://example.com') is False

	# Test explicit http protocol
	assert match_url_with_domain_pattern('http://example.com', 'http://example.com') is True
	assert match_url_with_domain_pattern('https://example.com', 'http://example.com') is False

	# Test Chrome extension pattern
	assert match_url_with_domain_pattern('chrome-extension://abcdefghijkl', 'chrome-extension://*') is True
	assert match_url_with_domain_pattern('chrome-extension://mnopqrstuvwx', 'chrome-extension://abcdefghijkl') is False

	# Test new tab page handling
	assert match_url_with_domain_pattern('about:blank', 'example.com') is False
	assert match_url_with_domain_pattern('about:blank', '*://*') is False
	assert match_url_with_domain_pattern('chrome://new-tab-page/', 'example.com') is False
	assert match_url_with_domain_pattern('chrome://new-tab-page/', '*://*') is False
	assert match_url_with_domain_pattern('chrome://new-tab-page', 'example.com') is False
	assert match_url_with_domain_pattern('chrome://new-tab-page', '*://*') is False


def test_unsafe_domain_patterns():
	"""Test that unsafe domain patterns are rejected"""

	# These are unsafe patterns that could match too many domains
	assert match_url_with_domain_pattern('https://evil.com', '*google.com') is False
	assert match_url_with_domain_pattern('https://google.com.evil.com', '*.*.com') is False
	assert match_url_with_domain_pattern('https://google.com', '**google.com') is False
	assert match_url_with_domain_pattern('https://google.com', 'g*e.com') is False
	assert match_url_with_domain_pattern('https://google.com', '*com*') is False

	# Test with patterns that have multiple asterisks in different positions
	assert match_url_with_domain_pattern('https://subdomain.example.com', '*domain*example*') is False
	assert match_url_with_domain_pattern('https://sub.domain.example.com', '*.*.example.com') is False

	# Test patterns with wildcards in TLD part
	assert match_url_with_domain_pattern('https://example.com', 'example.*') is False
	assert match_url_with_domain_pattern('https://example.org', 'example.*') is False


def test_malformed_urls_and_patterns():
	"""Test handling of malformed URLs or patterns"""

	# Malformed URLs
	assert match_url_with_domain_pattern('not-a-url', 'example.com') is False
	assert match_url_with_domain_pattern('http://', 'example.com') is False
	assert match_url_with_domain_pattern('https://', 'example.com') is False
	assert match_url_with_domain_pattern('ftp:/example.com', 'example.com') is False  # Missing slash

	# Empty URLs or patterns
	assert match_url_with_domain_pattern('', 'example.com') is False
	assert match_url_with_domain_pattern('https://example.com', '') is False

	# URLs with no hostname
	assert match_url_with_domain_pattern('file:///path/to/file.txt', 'example.com') is False

	# Invalid pattern formats
	assert match_url_with_domain_pattern('https://example.com', '..example.com') is False
	assert match_url_with_domain_pattern('https://example.com', '.*.example.com') is False
	assert match_url_with_domain_pattern('https://example.com', '**') is False

	# Nested URL attacks in path, query or fragments
	assert match_url_with_domain_pattern('https://example.com/redirect?url=https://evil.com', 'example.com') is True
	assert match_url_with_domain_pattern('https://example.com/path/https://evil.com', 'example.com') is True
	assert match_url_with_domain_pattern('https://example.com#https://evil.com', 'example.com') is True
	# These should match example.com, not evil.com since urlparse extracts the hostname correctly

	# Complex URL obfuscation attempts
	assert match_url_with_domain_pattern('https://example.com/path?next=//evil.com/attack', 'example.com') is True
	assert match_url_with_domain_pattern('https://example.com@evil.com', 'example.com') is False
	assert match_url_with_domain_pattern('https://evil.com?example.com', 'example.com') is False
	assert match_url_with_domain_pattern('https://user:example.com@evil.com', 'example.com') is False
	# urlparse correctly identifies evil.com as the hostname in these cases


def test_url_components():
	"""Test handling of URL components like credentials, ports, fragments, etc."""

	# URLs with credentials (username:password@)
	assert match_url_with_domain_pattern('https://user:pass@example.com', 'example.com') is True
	assert match_url_with_domain_pattern('https://user:pass@example.com', '*.example.com') is True

	# URLs with ports
	assert match_url_with_domain_pattern('https://example.com:8080', 'example.com') is True
	assert match_url_with_domain_pattern('https://example.com:8080', 'example.com:8080') is True  # Port is stripped from pattern

	# URLs with paths
	assert match_url_with_domain_pattern('https://example.com/path/to/page', 'example.com') is True
	assert (
		match_url_with_domain_pattern('https://example.com/path/to/page', 'example.com/path') is False
	)  # Paths in patterns are not supported

	# URLs with query parameters
	assert match_url_with_domain_pattern('https://example.com?param=value', 'example.com') is True

	# URLs with fragments
	assert match_url_with_domain_pattern('https://example.com#section', 'example.com') is True

	# URLs with all components
	assert match_url_with_domain_pattern('https://user:pass@example.com:8080/path?query=val#fragment', 'example.com') is True


def test_filter_sensitive_data(message_manager):
	"""Test that _filter_sensitive_data handles all sensitive data scenarios correctly"""
	# Set up a message with sensitive information
	message = UserMessage(content='My username is admin and password is secret123')

	# Case 1: No sensitive data provided
	message_manager.sensitive_data = None
	result = message_manager._filter_sensitive_data(message)
	assert result.content == 'My username is admin and password is secret123'

	# Case 2: All sensitive data is properly replaced
	message_manager.sensitive_data = {'username': 'admin', 'password': 'secret123'}
	result = message_manager._filter_sensitive_data(message)
	assert '<secret>username</secret>' in result.content
	assert '<secret>password</secret>' in result.content

	# Case 3: Make sure it works with nested content
	nested_message = UserMessage(content=[ContentPartTextParam(text='My username is admin and password is secret123')])
	result = message_manager._filter_sensitive_data(nested_message)
	assert '<secret>username</secret>' in result.content[0].text
	assert '<secret>password</secret>' in result.content[0].text

	# Case 4: Test with empty values
	message_manager.sensitive_data = {'username': 'admin', 'password': ''}
	result = message_manager._filter_sensitive_data(message)
	assert '<secret>username</secret>' in result.content
	# Only username should be replaced since password is empty

	# Case 5: Test with domain-specific sensitive data format
	message_manager.sensitive_data = {
		'example.com': {'username': 'admin', 'password': 'secret123'},
		'google.com': {'email': 'user@example.com', 'password': 'google_pass'},
	}
	# Update the message to include the values we're going to test
	message = UserMessage(content='My username is admin, email is user@example.com and password is secret123 or google_pass')
	result = message_manager._filter_sensitive_data(message)
	# All sensitive values should be replaced regardless of domain
	assert '<secret>username</secret>' in result.content
	assert '<secret>password</secret>' in result.content
	assert '<secret>email</secret>' in result.content


def test_is_new_tab_page():
	"""Test is_new_tab_page function"""
	# Test about:blank
	assert is_new_tab_page('about:blank') is True

	# Test chrome://new-tab-page variations
	assert is_new_tab_page('chrome://new-tab-page/') is True
	assert is_new_tab_page('chrome://new-tab-page') is True

	# Test regular URLs
	assert is_new_tab_page('https://example.com') is False
	assert is_new_tab_page('http://google.com') is False
	assert is_new_tab_page('') is False
	assert is_new_tab_page('chrome://settings') is False


def test_sensitive_data_filtered_from_action_results():
	"""
	Test that sensitive data in action results is filtered before being sent to the LLM.

	This tests the full flow:
	1. Agent outputs actions with <secret>password</secret> placeholder
	2. Placeholder gets replaced with real value 'secret_pass123' during action execution
	3. Action result contains: "Typed 'secret_pass123' into password field"
	4. When state messages are created, the real value should be replaced back to placeholder
	5. The LLM should never see the real password value
	"""
	import os
	import tempfile
	import uuid

	base_tmp = tempfile.gettempdir()
	file_system_path = os.path.join(base_tmp, str(uuid.uuid4()))

	sensitive_data: dict[str, str | dict[str, str]] = {'username': 'admin_user', 'password': 'secret_pass123'}

	message_manager = MessageManager(
		task='Login to the website',
		system_message=SystemMessage(content='You are a browser automation agent'),
		state=MessageManagerState(),
		file_system=FileSystem(file_system_path),
		sensitive_data=sensitive_data,
	)

	# Create browser state
	dom_state = SerializedDOMState(_root=None, selector_map={})
	browser_state = BrowserStateSummary(
		dom_state=dom_state,
		url='https://example.com/login',
		title='Login Page',
		tabs=[],
	)

	# Simulate action result containing sensitive data after placeholder replacement
	# This represents what happens after typing a password into a form field
	action_results = [
		ActionResult(
			long_term_memory="Successfully typed 'secret_pass123' into the password field",
			error=None,
		)
	]

	# Create model output for step 1
	model_output = AgentOutput(
		evaluation_previous_goal='Navigated to login page',
		memory='On login page, need to enter credentials',
		next_goal='Submit login form',
		action=[],
	)

	step_info = AgentStepInfo(step_number=1, max_steps=10)

	# Create state messages - this should filter sensitive data
	message_manager.create_state_messages(
		browser_state_summary=browser_state,
		model_output=model_output,
		result=action_results,
		step_info=step_info,
		use_vision=False,
	)

	# Get messages that would be sent to LLM
	messages = message_manager.get_messages()

	# Extract all text content from messages
	all_text = []
	for msg in messages:
		if isinstance(msg.content, str):
			all_text.append(msg.content)
		elif isinstance(msg.content, list):
			for part in msg.content:
				if isinstance(part, ContentPartTextParam):
					all_text.append(part.text)

	combined_text = '\n'.join(all_text)

	# Verify the bug is fixed: plaintext password should NOT appear in messages
	assert 'secret_pass123' not in combined_text, (
		'Sensitive data leaked! Real password value found in LLM messages. '
		'The _filter_sensitive_data method should replace it with <secret>password</secret>'
	)

	# Verify the filtered placeholder IS present (proves filtering happened)
	assert '<secret>password</secret>' in combined_text, (
		'Filtering did not work correctly. Expected <secret>password</secret> placeholder in messages.'
	)


def test_sensitive_data_filtered_with_domain_specific_format():
	"""Test that domain-specific sensitive data format is also filtered from action results."""
	import os
	import tempfile
	import uuid

	base_tmp = tempfile.gettempdir()
	file_system_path = os.path.join(base_tmp, str(uuid.uuid4()))

	# Use domain-specific format
	sensitive_data: dict[str, str | dict[str, str]] = {
		'example.com': {'api_key': 'sk-secret-api-key-12345'},
	}

	message_manager = MessageManager(
		task='Use the API',
		system_message=SystemMessage(content='You are a browser automation agent'),
		state=MessageManagerState(),
		file_system=FileSystem(file_system_path),
		sensitive_data=sensitive_data,
	)

	dom_state = SerializedDOMState(_root=None, selector_map={})
	browser_state = BrowserStateSummary(
		dom_state=dom_state,
		url='https://example.com/api',
		title='API Page',
		tabs=[],
	)

	# Action result with API key that should be filtered
	action_results = [
		ActionResult(
			long_term_memory="Set API key to 'sk-secret-api-key-12345' in the input field",
			error=None,
		)
	]

	model_output = AgentOutput(
		evaluation_previous_goal='Opened API settings',
		memory='Need to configure API key',
		next_goal='Save settings',
		action=[],
	)

	step_info = AgentStepInfo(step_number=1, max_steps=10)

	message_manager.create_state_messages(
		browser_state_summary=browser_state,
		model_output=model_output,
		result=action_results,
		step_info=step_info,
		use_vision=False,
	)

	messages = message_manager.get_messages()

	all_text = []
	for msg in messages:
		if isinstance(msg.content, str):
			all_text.append(msg.content)
		elif isinstance(msg.content, list):
			for part in msg.content:
				if isinstance(part, ContentPartTextParam):
					all_text.append(part.text)

	combined_text = '\n'.join(all_text)

	# API key should be filtered out
	assert 'sk-secret-api-key-12345' not in combined_text, 'API key leaked into LLM messages!'
	assert '<secret>api_key</secret>' in combined_text, 'API key placeholder not found in messages'
