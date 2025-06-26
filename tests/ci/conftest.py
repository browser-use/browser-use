"""
Pytest configuration for browser-use CI tests.

Sets up environment variables to ensure tests never connect to production services.
"""

import os
import tempfile
from unittest.mock import AsyncMock

import pytest
from dotenv import load_dotenv
from pytest_httpserver import HTTPServer

from browser_use.agent.views import AgentOutput
from browser_use.controller.service import Controller
from browser_use.llm import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion

# Load environment variables before any imports
load_dotenv()


# Skip LLM API key verification for tests
os.environ['SKIP_LLM_API_KEY_VERIFICATION'] = 'true'

from bubus import BaseEvent

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.sync.service import CloudSync


@pytest.fixture(autouse=True)
def setup_test_environment():
	"""
	Automatically set up test environment for all tests.
	"""

	# Create a temporary directory for test config
	config_dir = tempfile.mkdtemp(prefix='browseruse_tests_')

	original_env = {}
	test_env_vars = {
		'SKIP_LLM_API_KEY_VERIFICATION': 'true',
		'ANONYMIZED_TELEMETRY': 'false',
		'BROWSER_USE_CLOUD_SYNC': 'true',
		'BROWSER_USE_CLOUD_API_URL': 'http://placeholder-will-be-replaced-by-specific-test-fixtures',
		'BROWSER_USE_CLOUD_UI_URL': 'http://placeholder-will-be-replaced-by-specific-test-fixtures',
		'BROWSER_USE_CONFIG_DIR': config_dir,
	}

	for key, value in test_env_vars.items():
		original_env[key] = os.environ.get(key)
		os.environ[key] = value

	yield

	# Restore original environment
	for key, value in original_env.items():
		if value is None:
			os.environ.pop(key, None)
		else:
			os.environ[key] = value


# not a fixture, mock_llm() provides this in a fixture below, this is a helper so that it can accept args
def create_mock_llm(actions: list[str] | None = None) -> BaseChatModel:
	"""Create a mock LLM that returns specified actions or a default done action.

	Args:
		actions: Optional list of JSON strings representing actions to return in sequence.
			If not provided, returns a single done action.
			After all actions are exhausted, returns a done action.

	Returns:
		Mock LLM that will return the actions in order, or just a done action if no actions provided.
	"""
	controller = Controller()
	ActionModel = controller.registry.create_action_model()
	AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)

	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-llm'
	llm._verified_api_keys = True

	# Add missing properties from BaseChatModel protocol
	llm.provider = 'mock'
	llm.name = 'mock-llm'
	llm.model_name = 'mock-llm'  # Ensure this returns a string, not a mock

	# Default done action
	default_done_action = """
	{
		"thinking": "null",
		"evaluation_previous_goal": "Successfully completed the task",
		"memory": "Task completed",
		"next_goal": "Task completed",
		"action": [
			{
				"done": {
					"text": "Task completed successfully",
					"success": true
				}
			}
		]
	}
	"""

	# Unified logic for both cases
	action_index = 0

	def get_next_action() -> str:
		nonlocal action_index
		if actions is not None and action_index < len(actions):
			action = actions[action_index]
			action_index += 1
			return action
		else:
			return default_done_action

	async def mock_ainvoke(*args, **kwargs):
		# Check if output_format is provided (2nd argument or in kwargs)
		output_format = None
		if len(args) >= 2:
			output_format = args[1]
		elif 'output_format' in kwargs:
			output_format = kwargs['output_format']

		action_json = get_next_action()

		if output_format is None:
			# Return string completion
			return ChatInvokeCompletion(completion=action_json, usage=None)
		else:
			# Parse with provided output_format (could be AgentOutputWithActions or another model)
			if output_format == AgentOutputWithActions:
				parsed = AgentOutputWithActions.model_validate_json(action_json)
			else:
				# For other output formats, try to parse the JSON with that model
				parsed = output_format.model_validate_json(action_json)
			return ChatInvokeCompletion(completion=parsed, usage=None)

	llm.ainvoke.side_effect = mock_ainvoke

	return llm


@pytest.fixture(scope='module')
async def browser_session():
	"""Create a real browser session for testing"""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,  # Use temporary directory
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.stop()


@pytest.fixture(scope='function')
def cloud_sync(httpserver: HTTPServer):
	"""
	Create a CloudSync instance configured for testing.

	This fixture creates a real CloudSync instance and sets up the test environment
	to use the httpserver URLs.
	"""

	# Set up test environment
	test_http_server_url = httpserver.url_for('')
	os.environ['BROWSER_USE_CLOUD_API_URL'] = test_http_server_url
	os.environ['BROWSER_USE_CLOUD_UI_URL'] = test_http_server_url
	os.environ['BROWSER_USE_CLOUD_SYNC'] = 'true'

	# Create CloudSync with test server URL
	cloud_sync = CloudSync(
		base_url=test_http_server_url,
		enable_auth=False,  # Disable auth for most tests, they can override this if needed
	)

	return cloud_sync


@pytest.fixture(scope='function')
def mock_llm():
	"""Create a mock LLM that just returns the done action if queried"""
	return create_mock_llm(actions=None)


@pytest.fixture(scope='function')
def agent_with_cloud(browser_session, mock_llm, cloud_sync):
	"""Create agent with cloud sync enabled (using real CloudSync)."""
	agent = Agent(
		task='Test task',
		llm=mock_llm,
		browser_session=browser_session,
		cloud_sync=cloud_sync,
	)
	return agent


@pytest.fixture(scope='function')
def event_collector():
	"""Helper to collect all events emitted during tests"""
	events = []
	event_order = []

	class EventCollector:
		def __init__(self):
			self.events = events
			self.event_order = event_order

		async def collect_event(self, event: BaseEvent):
			self.events.append(event)
			self.event_order.append(event.event_type)
			return 'collected'

		def get_events_by_type(self, event_type: str) -> list[BaseEvent]:
			return [e for e in self.events if e.event_type == event_type]

		def clear(self):
			self.events.clear()
			self.event_order.clear()

	return EventCollector()
