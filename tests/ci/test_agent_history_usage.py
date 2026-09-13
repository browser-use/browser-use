import json
from pathlib import Path
from typing import Any

from browser_use.agent.views import AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.tokens.views import UsageSummary


def test_agent_history_list_saves_and_loads_usage(tmp_path: Path):
	usage = UsageSummary(
		total_prompt_tokens=100,
		total_prompt_cost=0.01,
		total_prompt_cached_tokens=0,
		total_prompt_cached_cost=0.0,
		total_completion_tokens=50,
		total_completion_cost=0.02,
		total_tokens=150,
		total_cost=0.03,
		entry_count=1,
	)

	history_list = AgentHistoryList[Any](
		history=[
			AgentHistory(
				model_output=None,
				result=[],
				state=BrowserStateHistory(url='https://example.com', title='Example', tabs=[], interacted_element=[None]),
			)
		],
		usage=usage,
	)

	filepath = tmp_path / 'history_with_usage.json'
	history_list.save_to_file(filepath)

	# Verify raw json content includes usage
	with open(filepath, encoding='utf-8') as f:
		raw_data = json.load(f)

	assert 'usage' in raw_data
	assert raw_data['usage']['total_tokens'] == 150

	# Verify loading from file restores usage
	loaded = AgentHistoryList.load_from_file(filepath, AgentOutput)
	assert loaded.usage is not None
	assert loaded.usage.total_tokens == 150
	assert loaded.usage.total_prompt_tokens == 100
	assert loaded.usage.total_completion_tokens == 50
	assert loaded.usage.total_cost == 0.03


def test_agent_history_list_model_dump_filters():
	usage = UsageSummary(
		total_prompt_tokens=10,
		total_prompt_cost=0.01,
		total_prompt_cached_tokens=0,
		total_prompt_cached_cost=0.0,
		total_completion_tokens=5,
		total_completion_cost=0.02,
		total_tokens=15,
		total_cost=0.03,
		entry_count=1,
	)

	history_with_usage = AgentHistoryList[Any](history=[], usage=usage)
	assert 'usage' in history_with_usage.model_dump()
	assert 'usage' not in history_with_usage.model_dump(exclude={'usage'})
	assert 'usage' not in history_with_usage.model_dump(include={'history'})

	history_without_usage = AgentHistoryList[Any](history=[], usage=None)
	assert history_without_usage.model_dump()['usage'] is None
	assert 'usage' not in history_without_usage.model_dump(exclude_none=True)
	assert 'usage' not in history_without_usage.model_dump(exclude_unset=True)
	assert 'usage' not in history_without_usage.model_dump(exclude_defaults=True)
