"""Continuous navigation (periodic navigator LLM) — settings and CLI wiring."""

from browser_use.agent.views import AgentSettings
from browser_use.cli_navigator import resolve_navigator_llm_for_agent


def test_agent_settings_continuous_navigation_defaults():
	s = AgentSettings()
	assert s.continuous_navigation is False
	assert s.navigator_replan_interval == 5
	assert s.navigator_replan_on_stall is True
	assert s.navigator_context_max_chars == 6000


def _fake_get_llm(_config):
	raise AssertionError('get_llm should not be called')


def test_resolve_navigator_llm_returns_executor_when_disabled(mock_llm):
	cfg = {'agent': {'continuous_navigation': False}}
	assert resolve_navigator_llm_for_agent(cfg, mock_llm, _fake_get_llm) is mock_llm


def test_resolve_navigator_llm_returns_executor_when_no_navigator_model(mock_llm):
	cfg = {'agent': {'continuous_navigation': True}}
	assert resolve_navigator_llm_for_agent(cfg, mock_llm, _fake_get_llm) is mock_llm
