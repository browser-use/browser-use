"""Agent(ultrafast=True) is a latency preset, so its contents are the contract.

It spans agent settings, the browser profile and the tool registry, and every field in it was
picked from an eval measurement. A silent change to any of them is a silent perf regression.
"""

import pytest

from browser_use import Agent, BrowserProfile, ChatOpenAI


def _agent(**kwargs) -> Agent:
	return Agent(task='t', llm=ChatOpenAI(model='test', api_key='x'), **kwargs)


class TestUltrafastPreset:
	def test_applies_agent_settings(self):
		s = _agent(ultrafast=True).settings

		assert s.flash_mode is True
		assert s.flash_thinking is True  # small models need scratch space, but capped
		assert s.flash_memory is False
		assert s.use_vision == 'auto'  # images on request, not on every step
		assert s.capture_screenshots is False
		assert s.use_judge is False
		assert s.enable_planning is False  # flash mode strips the plan fields from the schema
		assert s.message_compaction is not None and s.message_compaction.enabled is False
		# History is cheap and prevents wasted steps, so the preset keeps all of it.
		assert s.max_history_items is None

	def test_applies_browser_profile_settings(self):
		profile = _agent(ultrafast=True).browser_session.browser_profile

		assert profile.wait_between_actions == 0.0
		assert profile.highlight_elements is False  # visual only, costs CDP round trips per action
		# Measured no faster when disabled, so the preset leaves accuracy features alone.
		assert profile.paint_order_filtering is True
		assert profile.cross_origin_iframes is True

	def test_rewrites_the_profile_of_a_caller_supplied_session(self):
		from browser_use import BrowserSession

		session = BrowserSession(browser_profile=BrowserProfile(wait_between_actions=0.5))
		_agent(ultrafast=True, browser_session=session)

		assert session.browser_profile.wait_between_actions == 0.0

	def test_removes_the_wait_action(self):
		"""The model must not be able to spend a whole step deciding to do nothing."""
		assert 'wait' not in _agent(ultrafast=True).tools.registry.registry.actions
		assert 'wait' in _agent().tools.registry.registry.actions

	def test_keeps_the_screenshot_tool(self):
		"""Skipping capture must not take away the agent's way to ask for an image."""
		assert 'screenshot' in _agent(ultrafast=True).tools.registry.registry.actions
		assert 'screenshot' not in _agent(use_vision=False).tools.registry.registry.actions


class TestOnDemandScreenshotCapture:
	"""capture_screenshots=False must still capture on the step that will show the image.

	The message manager attaches the image when the previous result asked for one. If capture
	does not follow the same rule, the screenshot tool becomes a silent no-op.
	"""

	def test_capture_follows_a_screenshot_request(self):
		from browser_use.agent.views import ActionResult

		agent = _agent(ultrafast=True)
		agent.state.last_result = [ActionResult(extracted_content='x', metadata={'include_screenshot': True})]

		assert agent._screenshot_was_requested() is True

	def test_no_capture_without_a_request(self):
		from browser_use.agent.views import ActionResult

		agent = _agent(ultrafast=True)
		agent.state.last_result = [ActionResult(extracted_content='x')]

		assert agent._screenshot_was_requested() is False
		assert _agent(ultrafast=True)._screenshot_was_requested() is False

	def test_off_by_default(self):
		s = _agent().settings

		assert s.capture_screenshots is True
		assert s.flash_mode is False


def test_skipping_capture_is_incompatible_with_always_on_vision():
	"""use_vision=True wants an image every step, so every step must capture one."""
	with pytest.raises(ValueError, match='capture_screenshots=False'):
		_agent(capture_screenshots=False, use_vision=True)
