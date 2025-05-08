import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.views import MessageManagerState
from browser_use.controller.registry.service import Registry


class SensitiveParams(BaseModel):
	"""Test parameter model for sensitive data testing."""

	text: str = Field(description='Text with sensitive data placeholders')


@pytest.fixture
def registry():
	return Registry()


@pytest.fixture
def message_manager():
	return MessageManager(
		task='Test task',
		system_message=SystemMessage(content='System message'),
		settings=MessageManagerSettings(),
		state=MessageManagerState(),
	)


def test_replace_sensitive_data_with_missing_keys(registry):
	"""Test that _replace_sensitive_data handles missing keys gracefully"""
	# Create a simple Pydantic model with sensitive data placeholders
	params = SensitiveParams(text='Please enter <secret>username</secret> and <secret>password</secret>')

	# Case 1: All keys present
	sensitive_data = {'username': 'user123', 'password': 'pass456'}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert 'pass456' in result.text
	# Both keys should be replaced

	# Case 2: One key missing
	sensitive_data = {'username': 'user123'}  # password is missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text
	# Verify the behavior - username replaced, password kept as tag

	# Case 3: Multiple keys missing
	sensitive_data = {}  # both keys missing
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert '<secret>username</secret>' in result.text
	assert '<secret>password</secret>' in result.text
	# Verify both tags are preserved when keys are missing

	# Case 4: One key empty
	sensitive_data = {'username': 'user123', 'password': ''}
	result = registry._replace_sensitive_data(params, sensitive_data)
	assert 'user123' in result.text
	assert '<secret>password</secret>' in result.text
	# Empty value should be treated the same as missing key


def test_filter_sensitive_data(message_manager):
	"""Test that _filter_sensitive_data handles all sensitive data scenarios correctly"""
	# Set up a message with sensitive information
	message = HumanMessage(content='My username is admin and password is secret123')

	# Case 1: No sensitive data provided
	message_manager.settings.sensitive_data = None
	result = message_manager._filter_sensitive_data(message)
	assert result.content == 'My username is admin and password is secret123'

	# Case 2: All sensitive data is properly replaced
	message_manager.settings.sensitive_data = {'username': 'admin', 'password': 'secret123'}
	result = message_manager._filter_sensitive_data(message)
	assert '<secret>username</secret>' in result.content
	assert '<secret>password</secret>' in result.content

	# Case 3: Make sure it works with nested content
	nested_message = HumanMessage(content=[{'type': 'text', 'text': 'My username is admin and password is secret123'}])
	result = message_manager._filter_sensitive_data(nested_message)
	assert '<secret>username</secret>' in result.content[0]['text']
	assert '<secret>password</secret>' in result.content[0]['text']

	# Case 4: Test with empty values
	message_manager.settings.sensitive_data = {'username': 'admin', 'password': ''}
	result = message_manager._filter_sensitive_data(message)
	assert '<secret>username</secret>' in result.content
	# Only username should be replaced since password is empty
