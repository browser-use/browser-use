import pytest
from pydantic import BaseModel, Field

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import MessageManagerState
from browser_use.controller.registry.service import Registry
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage, UserMessage
from browser_use.llm.messages import ContentPartTextParam
from browser_use.utils import match_url_with_domain_pattern


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
	# Set log level to capture warnings
	import logging

	# Temporarily enable propagation for browser_use logger to capture logs
	browser_use_logger = logging.getLogger('browser_use')
	original_propagate = browser_use_logger.propagate
	browser_use_logger.propagate = True

	caplog.set_level(logging.WARNING, logger='browser_use.controller.registry.service')

	# Create a simple Pydantic model with sensitive data placeholders
	params = SensitiveParams(text='Please enter <secret>username</secret> and <secret>password</secret>')

	# Case 1: All keys present
	sensitive_data = {'username': 'user123', 'password': 'pass456'}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert 'pass456' in result.text
	# Both keys should be replaced
	assert 'Missing' not in caplog.text
	caplog.clear()

	# Case 2: One key missing
	sensitive_data = {'username': 'user123'}  # password is missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text
	# Verify the behavior - username replaced, password kept as tag
	assert 'password' in caplog.text
	caplog.clear()

	# Case 3: Multiple keys missing
	sensitive_data = {}  # both keys missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert '<secret>username</secret>' in result.text
	assert '<secret>password</secret>' in result.text
	# Verify both tags are preserved when keys are missing
	assert 'Missing' in caplog.text
	caplog.clear()

	# Case 4: One key empty
	sensitive_data = {'username': 'user123', 'password': ''}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text
	# Empty value should be treated the same as missing key
	assert 'password' in caplog.text
	caplog.clear()

	# Restore original propagate setting
	browser_use_logger.propagate = original_propagate


def test_simple_domain_specific_sensitive_data(registry, caplog):
	"""Test the basic functionality of domain-specific sensitive data replacement"""
	# Set log level to capture warnings
	import logging

	# Temporarily enable propagation for browser_use logger to capture logs
	browser_use_logger = logging.getLogger('browser_use')
	original_propagate = browser_use_logger.propagate
	browser_use_logger.propagate = True

	caplog.set_level(logging.WARNING, logger='browser_use.controller.registry.service')

	# Create a simple Pydantic model with sensitive data placeholders
	params = SensitiveParams(text='Please enter <secret>username</secret> and <secret>password</secret>')

	# Simple test with directly instantiable values
	sensitive_data = {
		'example.com': {'username': 'example_user'},
		'other_data': 'non_secret_value',  # Old format mixed with new
	}

	# Without a URL, domain-specific secrets should NOT be exposed
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert '<secret>username</secret>' in result.text  # Should NOT be replaced without URL
	assert '<secret>password</secret>' in result.text  # Password is missing in sensitive_data
	assert 'username' in caplog.text  # Both should be logged as missing
	assert 'password' in caplog.text
	caplog.clear()

	# Test with a matching URL - domain-specific secrets should be exposed
	result = registry._replace_sensitive_data(params, sensitive_data, 'https://example.com/login')
	assert 'example_user' in result.text  # Should be replaced with matching URL
	assert '<secret>password</secret>' in result.text  # Password is still missing
	assert 'password' in caplog.text  # Only password should be logged as missing
	caplog.clear()

	# Restore original propagate setting
	browser_use_logger.propagate = original_propagate


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

	# Test about:blank handling
	assert match_url_with_domain_pattern('about:blank', 'example.com') is False
	assert match_url_with_domain_pattern('about:blank', '*://*') is False


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
