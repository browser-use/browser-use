"""Loading a history entry that predates `state.interacted_element` must not fail validation."""

import json

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.beta.service import _load_rust_history
from browser_use.tools.service import Tools


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


def test_load_from_dict_pads_a_legacy_entry_with_actions_one_slot_per_action():
	"""Replay reads `state.interacted_element[i]` for each action, so an entry that has actions needs a slot per action."""
	tools = Tools()
	output_model = AgentOutput.type_with_custom_actions(tools.registry.create_action_model())
	entry = {
		'model_output': {'thinking': 'x', 'memory': 'm', 'action': [{'done': {'text': 'ok', 'success': True}}]},
		'result': [],
		'state': dict(_LEGACY_STATE),
	}

	history = AgentHistoryList.load_from_dict({'history': [entry]}, output_model)
	loaded = history.history[0]

	assert len(loaded.model_output.action) == 1
	assert loaded.state.interacted_element == [None]
