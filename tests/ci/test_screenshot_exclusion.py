"""Test that screenshot action is excluded when use_vision != 'auto'."""

import pytest

from browser_use.agent.service import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='function')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


def test_screenshot_excluded_with_use_vision_false():
	"""Test that screenshot action is excluded when use_vision=False."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(
		task='test',
		llm=mock_llm,
		use_vision=False,
	)

	# Verify screenshot is not in the registry
	assert 'screenshot' not in agent.tools.registry.registry.actions, 'Screenshot should be excluded when use_vision=False'


def test_screenshot_excluded_with_use_vision_true():
	"""Test that screenshot action is excluded when use_vision=True."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(
		task='test',
		llm=mock_llm,
		use_vision=True,
	)

	# Verify screenshot is not in the registry
	assert 'screenshot' not in agent.tools.registry.registry.actions, 'Screenshot should be excluded when use_vision=True'


def test_screenshot_included_with_use_vision_auto():
	"""Test that screenshot action is included when use_vision='auto'."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(
		task='test',
		llm=mock_llm,
		use_vision='auto',
	)

	# Verify screenshot IS in the registry
	assert 'screenshot' in agent.tools.registry.registry.actions, 'Screenshot should be included when use_vision="auto"'


def test_screenshot_excluded_with_custom_tools_and_use_vision_false():
	"""Test that screenshot action is excluded even when user passes custom tools and use_vision=False.

	This is the critical test case that verifies the fix:
	When users pass their own Tools instance with screenshot included,
	the Agent should still enforce the exclusion if use_vision != 'auto'.
	"""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	# Create custom tools that includes screenshot action
	custom_tools = Tools()
	assert 'screenshot' in custom_tools.registry.registry.actions, 'Custom tools should have screenshot by default'

	# Pass custom tools to agent with use_vision=False
	agent = Agent(
		task='test',
		llm=mock_llm,
		tools=custom_tools,
		use_vision=False,
	)

	# Verify screenshot is excluded even though user passed custom tools
	assert 'screenshot' not in agent.tools.registry.registry.actions, (
		'Screenshot should be excluded when use_vision=False, even with custom tools'
	)


def test_screenshot_excluded_with_custom_tools_and_use_vision_true():
	"""Test that screenshot action is excluded even when user passes custom tools and use_vision=True.

	This is another critical test case:
	When users pass their own Tools instance with screenshot included,
	the Agent should still enforce the exclusion if use_vision != 'auto'.
	"""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	# Create custom tools - by default Tools() includes screenshot
	# (unless exclude_actions is passed)
	custom_tools = Tools()
	# Note: We check if screenshot exists in the default set, but it might not
	# exist if use_vision defaults have changed. The key is that after passing
	# to Agent with use_vision=True, it should be excluded.
	has_screenshot_before = 'screenshot' in custom_tools.registry.registry.actions

	# Pass custom tools to agent with use_vision=True
	agent = Agent(
		task='test',
		llm=mock_llm,
		tools=custom_tools,
		use_vision=True,
	)

	# Verify screenshot is excluded even though user passed custom tools
	# The key test: screenshot should be excluded after Agent init
	assert 'screenshot' not in agent.tools.registry.registry.actions, (
		f'Screenshot should be excluded when use_vision=True, even with custom tools (had screenshot before: {has_screenshot_before})'
	)


def test_screenshot_included_with_custom_tools_and_use_vision_auto():
	"""Test that screenshot action is kept when user passes custom tools and use_vision='auto'."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	# Create custom tools that includes screenshot action
	custom_tools = Tools()
	assert 'screenshot' in custom_tools.registry.registry.actions, 'Custom tools should have screenshot by default'

	# Pass custom tools to agent with use_vision='auto'
	agent = Agent(
		task='test',
		llm=mock_llm,
		tools=custom_tools,
		use_vision='auto',
	)

	# Verify screenshot is kept when use_vision='auto'
	assert 'screenshot' in agent.tools.registry.registry.actions, (
		'Screenshot should be included when use_vision="auto", even with custom tools'
	)


def test_tools_exclude_action_method():
	"""Test the Tools.exclude_action() method directly."""
	tools = Tools()

	# Verify screenshot is included initially
	assert 'screenshot' in tools.registry.registry.actions, 'Screenshot should be included by default'

	# Exclude screenshot
	tools.exclude_action('screenshot')

	# Verify screenshot is excluded
	assert 'screenshot' not in tools.registry.registry.actions, 'Screenshot should be excluded after calling exclude_action()'
	assert 'screenshot' in tools.registry.exclude_actions, 'Screenshot should be in exclude_actions list'


def test_exclude_action_prevents_re_registration():
	"""Test that excluded actions cannot be re-registered."""
	tools = Tools()

	# Exclude screenshot
	tools.exclude_action('screenshot')
	assert 'screenshot' not in tools.registry.registry.actions

	# Try to re-register screenshot (simulating what happens in __init__)
	# The decorator should skip registration since it's in exclude_actions
	@tools.registry.action('Test screenshot action')
	async def screenshot():
		return 'test'

	# Verify it was not re-registered
	assert 'screenshot' not in tools.registry.registry.actions, 'Excluded action should not be re-registered'
