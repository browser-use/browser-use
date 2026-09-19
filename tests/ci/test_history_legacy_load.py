"""Loading a history entry that predates `state.interacted_element` must not fail validation."""

import json

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.beta.service import _load_rust_history


def _legacy_entry(state: dict) -> dict:
	return {'model_output': None, 'result': [], 'state': state}


_LEGACY_STATE = {'url': 'https://example.com', 'title': 'Example', 'tabs': []}


def test_load_from_dict_accepts_state_without_interacted_element():
	"""A stored state that predates the field still has to validate, so the guard must fill a list."""
	data = {'history': [_legacy_entry(dict(_LEGACY_STATE))]}

	history = AgentHistoryList.load_from_dict(data, AgentOutput)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []


def test_load_from_dict_keeps_a_stored_interacted_element():
	history = AgentHistoryList.load_from_dict(
		{'history': [_legacy_entry({**_LEGACY_STATE, 'interacted_element': [None]})]},
		AgentOutput,
	)

	assert history.history[0].state.interacted_element == [None]


def test_load_rust_history_accepts_state_without_interacted_element(tmp_path):
	history_file = tmp_path / 'agent_history.json'
	history_file.write_text(json.dumps({'history': [_legacy_entry(dict(_LEGACY_STATE))]}), encoding='utf-8')

	history = _load_rust_history(history_file)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []
