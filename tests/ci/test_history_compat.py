"""Regression tests for loading legacy history entries (no interacted_element)."""

from browser_use.agent.views import AgentHistoryList, AgentOutput


def test_load_from_dict_legacy_state_without_interacted_element():
	"""A history entry whose state predates interacted_element must load (issue #5844).

	The compatibility branch in AgentHistoryList.load_from_dict() existed to
	tolerate legacy entries, but it filled the missing key with None while
	BrowserStateHistory.interacted_element requires a list, so validation
	always failed for the only input the branch handles.
	"""
	history = AgentHistoryList.load_from_dict(
		{
			'history': [
				{
					'model_output': None,
					'result': [],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		},
		AgentOutput,
	)
	assert len(history.history) == 1
	assert history.history[0].state is not None
	assert history.history[0].state.interacted_element == []


def test_load_from_dict_existing_interacted_element_preserved():
	"""Entries that already carry interacted_element are left untouched."""
	history = AgentHistoryList.load_from_dict(
		{
			'history': [
				{
					'model_output': None,
					'result': [],
					'state': {
						'url': 'https://example.com',
						'title': 'Example',
						'tabs': [],
						'interacted_element': [None],
					},
				}
			]
		},
		AgentOutput,
	)
	assert history.history[0].state.interacted_element == [None]
