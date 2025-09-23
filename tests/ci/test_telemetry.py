"""Test telemetry functionality."""

from unittest.mock import MagicMock, patch

import pytest

from browser_use.config import CONFIG
from browser_use.telemetry import (
	CLITelemetryEvent,
	MCPClientTelemetryEvent,
	MCPServerTelemetryEvent,
	ProductTelemetry,
)
from browser_use.utils import get_browser_use_version


@pytest.fixture
def reset_telemetry_singleton():
	"""Reset the telemetry singleton between tests."""
	# The singleton decorator stores instance in a list at index 0
	# We need to access the closure variable which stores the singleton instance
	# Import the actual module to access the wrapped function
	from browser_use.telemetry import service

	# Get the ProductTelemetry wrapper function created by @singleton
	wrapper_func = service.ProductTelemetry

	# Access the closure variable (instance list) and reset it
	# The closure contains the 'instance' list at index 0
	# Type ignore needed because pyright doesn't know this is a wrapper function
	if hasattr(wrapper_func, '__closure__') and wrapper_func.__closure__:  # type: ignore
		for cell in wrapper_func.__closure__:  # type: ignore
			if hasattr(cell.cell_contents, '__setitem__'):
				# This is the instance list
				cell.cell_contents[0] = None
				break

	yield

	# Reset again after test
	if hasattr(wrapper_func, '__closure__') and wrapper_func.__closure__:  # type: ignore
		for cell in wrapper_func.__closure__:  # type: ignore
			if hasattr(cell.cell_contents, '__setitem__'):
				cell.cell_contents[0] = None
				break


@pytest.fixture
def mock_posthog():
	"""Mock PostHog client."""
	with patch('browser_use.telemetry.service.Posthog') as mock:
		yield mock


def test_telemetry_disabled_when_config_false(monkeypatch, reset_telemetry_singleton):
	"""Test that telemetry is disabled when ANONYMIZED_TELEMETRY is False."""
	# Set env var to disable telemetry
	monkeypatch.setattr(CONFIG, 'ANONYMIZED_TELEMETRY', False)

	# Create telemetry instance
	telemetry = ProductTelemetry()

	# Check that posthog client is None
	assert telemetry._posthog_client is None

	# Try to capture an event - should not fail
	event = CLITelemetryEvent(
		version=get_browser_use_version(),
		action='start',
		mode='interactive',
	)
	telemetry.capture(event)  # Should not raise


def test_telemetry_enabled_when_config_true(monkeypatch, mock_posthog, reset_telemetry_singleton):
	"""Test that telemetry is enabled when ANONYMIZED_TELEMETRY is True."""
	# Set env var to enable telemetry
	monkeypatch.setattr(CONFIG, 'ANONYMIZED_TELEMETRY', True)

	# Create telemetry instance
	telemetry = ProductTelemetry()

	# Check that posthog client is created
	assert telemetry._posthog_client is not None
	mock_posthog.assert_called_once()


def test_cli_telemetry_event():
	"""Test CLITelemetryEvent structure."""
	event = CLITelemetryEvent(
		version='1.0.0',
		action='start',
		mode='interactive',
		model='gpt-4o',
		model_provider='OpenAI',
		duration_seconds=10.5,
		error_message=None,
	)

	assert event.name == 'cli_event'
	assert event.version == '1.0.0'
	assert event.action == 'start'
	assert event.mode == 'interactive'
	assert event.model == 'gpt-4o'
	assert event.model_provider == 'OpenAI'
	assert event.duration_seconds == 10.5
	assert event.error_message is None

	# Check properties
	props = event.properties
	assert 'version' in props
	assert 'action' in props
	assert 'mode' in props
	assert 'is_docker' in props  # Docker context should be included
	assert isinstance(props['is_docker'], bool)  # Should be a boolean
	assert 'name' not in props  # name should not be in properties


def test_mcp_client_telemetry_event():
	"""Test MCPClientTelemetryEvent structure."""
	event = MCPClientTelemetryEvent(
		server_name='test-server',
		command='npx',
		tools_discovered=5,
		version='1.0.0',
		action='connect',
		tool_name='browser_navigate',
		duration_seconds=2.5,
		error_message=None,
	)

	assert event.name == 'mcp_client_event'
	assert event.server_name == 'test-server'
	assert event.command == 'npx'
	assert event.tools_discovered == 5
	assert event.version == '1.0.0'
	assert event.action == 'connect'
	assert event.tool_name == 'browser_navigate'
	assert event.duration_seconds == 2.5
	assert event.error_message is None


def test_mcp_server_telemetry_event():
	"""Test MCPServerTelemetryEvent structure."""
	event = MCPServerTelemetryEvent(
		version='1.0.0',
		action='start',
		tool_name='browser_click',
		duration_seconds=1.2,
		error_message='Test error',
	)

	assert event.name == 'mcp_server_event'
	assert event.version == '1.0.0'
	assert event.action == 'start'
	assert event.tool_name == 'browser_click'
	assert event.duration_seconds == 1.2
	assert event.error_message == 'Test error'


def test_telemetry_capture_with_mock(monkeypatch, reset_telemetry_singleton):
	"""Test telemetry capture with mocked PostHog client."""
	# Enable telemetry
	monkeypatch.setattr(CONFIG, 'ANONYMIZED_TELEMETRY', True)

	# Create mock posthog client
	mock_client = MagicMock()

	# Create telemetry instance and inject mock
	telemetry = ProductTelemetry()
	telemetry._posthog_client = mock_client

	# Capture an event
	event = CLITelemetryEvent(
		version='1.0.0',
		action='start',
		mode='oneshot',
	)
	telemetry.capture(event)

	# Check that capture was called
	mock_client.capture.assert_called_once()
	call_args = mock_client.capture.call_args
	assert call_args[1]['event'] == 'cli_event'
	assert 'properties' in call_args[1]
	assert call_args[1]['properties']['version'] == '1.0.0'
	assert call_args[1]['properties']['action'] == 'start'
	assert call_args[1]['properties']['mode'] == 'oneshot'


def test_telemetry_flush(monkeypatch, reset_telemetry_singleton):
	"""Test telemetry flush method."""
	# Enable telemetry
	monkeypatch.setattr(CONFIG, 'ANONYMIZED_TELEMETRY', True)

	# Create mock posthog client
	mock_client = MagicMock()

	# Create telemetry instance and inject mock
	telemetry = ProductTelemetry()
	telemetry._posthog_client = mock_client

	# Call flush
	telemetry.flush()

	# Check that flush was called
	mock_client.flush.assert_called_once()


def test_telemetry_user_id_generation(tmp_path, monkeypatch, reset_telemetry_singleton):
	"""Test that telemetry generates and persists user ID."""
	# Set BROWSER_USE_CONFIG_DIR to temp directory
	config_dir = tmp_path / 'config' / 'browseruse'
	config_dir.mkdir(parents=True)
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(config_dir))

	# Enable telemetry
	monkeypatch.setattr(CONFIG, 'ANONYMIZED_TELEMETRY', True)

	# Create telemetry instance with patched path
	telemetry1 = ProductTelemetry()
	# Manually patch the USER_ID_PATH on the instance
	telemetry1.USER_ID_PATH = str(config_dir / 'device_id')

	user_id1 = telemetry1.user_id

	# Check that user ID is generated
	assert user_id1 != 'UNKNOWN_USER_ID'
	assert len(user_id1) > 0

	# Create another instance - should get same ID
	telemetry2 = ProductTelemetry()
	telemetry2.USER_ID_PATH = str(config_dir / 'device_id')
	user_id2 = telemetry2.user_id

	assert user_id1 == user_id2

	# Check that ID was persisted in config directory
	id_file = config_dir / 'device_id'
	assert id_file.exists()
	assert id_file.read_text() == user_id1


def test_mcp_server_telemetry_event_with_parent_process():
	"""Test MCPServerTelemetryEvent with parent_process_cmdline field."""
	event = MCPServerTelemetryEvent(
		version='1.0.0',
		action='start',
		tool_name=None,
		duration_seconds=None,
		error_message=None,
		parent_process_cmdline='python -m browser_use.mcp.server',
	)

	assert event.name == 'mcp_server_event'
	assert event.version == '1.0.0'
	assert event.action == 'start'
	assert event.parent_process_cmdline == 'python -m browser_use.mcp.server'

	# Check properties includes parent_process_cmdline
	props = event.properties
	assert 'parent_process_cmdline' in props
	assert props['parent_process_cmdline'] == 'python -m browser_use.mcp.server'
	assert 'is_docker' in props  # Docker context should be included
	assert isinstance(props['is_docker'], bool)  # Should be a boolean


def test_telemetry_device_id_uses_config_dir():
	"""Test that telemetry device_id is stored in config directory, not cache directory."""
	# This test verifies that the ProductTelemetry class uses CONFIG.BROWSER_USE_CONFIG_DIR
	# for the device_id file location instead of the cache directory.

	# Import ProductTelemetry to check the path
	from browser_use.telemetry.service import ProductTelemetry

	# Create telemetry instance
	telemetry = ProductTelemetry()

	# The USER_ID_PATH should use the config directory
	# We check that it contains the config dir path and ends with 'device_id'
	assert 'browseruse/device_id' in telemetry.USER_ID_PATH or 'browseruse\\device_id' in telemetry.USER_ID_PATH
	assert telemetry.USER_ID_PATH.endswith('device_id')

	# Verify it's not using the cache directory path
	assert 'cache' not in telemetry.USER_ID_PATH
	assert 'telemetry_user_id' not in telemetry.USER_ID_PATH
