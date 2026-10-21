"""Regression tests for usage persistence in the saved agent history.

`Agent.run()` sets `self.history.usage` right before saving, but
`AgentHistoryList.model_dump` only serialized `history` — the saved JSON
therefore lost the token/cost summary, and reloading the history dropped it
even though the field round-trips through pydantic validation.
"""

import json

from browser_use.agent.views import AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.tokens.views import UsageSummary


def _usage() -> UsageSummary:
	return UsageSummary(
		total_prompt_tokens=100,
		total_prompt_cost=0.1,
		total_prompt_cached_tokens=0,
		total_prompt_cached_cost=0.0,
		total_completion_tokens=50,
		total_completion_cost=0.2,
		total_tokens=150,
		total_cost=0.3,
		entry_count=2,
	)


def _history_with_usage() -> AgentHistoryList:
	item = AgentHistory(
		model_output=None,
		result=[],
		state=BrowserStateHistory(url='https://example.com', title='t', tabs=[], interacted_element=[None]),
	)
	return AgentHistoryList(history=[item], usage=_usage())


def test_saved_history_contains_usage(tmp_path):
	history = _history_with_usage()
	path = tmp_path / 'history.json'
	history.save_to_file(path)

	saved = json.loads(path.read_text(encoding='utf-8'))
	assert 'usage' in saved, 'saved history JSON must contain the usage summary'
	assert saved['usage']['total_tokens'] == 150
	assert saved['usage']['total_cost'] == 0.3


def test_usage_survives_save_and_reload_roundtrip(tmp_path):
	history = _history_with_usage()
	path = tmp_path / 'history.json'
	history.save_to_file(path)

	reloaded = AgentHistoryList.load_from_file(path, AgentOutput)
	assert reloaded.usage is not None, 'usage must survive a save/reload round-trip'
	assert reloaded.usage.total_tokens == 150
	assert reloaded.usage.total_cost == 0.3


def test_history_without_usage_still_dumps_cleanly():
	item = AgentHistory(
		model_output=None,
		result=[],
		state=BrowserStateHistory(url='https://example.com', title='t', tabs=[], interacted_element=[None]),
	)
	history = AgentHistoryList(history=[item], usage=None)

	dumped = history.model_dump()

	assert dumped['usage'] is None
	assert len(dumped['history']) == 1
