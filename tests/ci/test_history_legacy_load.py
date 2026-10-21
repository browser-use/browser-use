"""Tests for loading legacy AgentHistory JSON lacking `interacted_element`.

Older browser-use versions serialized `BrowserStateHistory` without an
`interacted_element` key (or with an explicit `null`). `AgentHistoryList.load_from_dict`
normalizes those entries before validation; these tests make sure loading such
legacy history does not raise and produces an empty element list, while valid
modern history keeps loading unchanged.

Pure dict based tests - no browser required.
"""

from typing import Any

from browser_use.agent.views import AgentHistoryList

_VALID_ELEMENT: dict[str, Any] = {
	'node_id': 1,
	'backend_node_id': 1,
	'frame_id': None,
	'node_type': 1,  # NodeType.ELEMENT_NODE
	'node_value': '',
	'node_name': 'BUTTON',
	'attributes': {'id': 'submit', 'aria-label': 'Submit'},
	'bounds': None,
	'x_path': 'html/body/button',
	'element_hash': 12345,
}


def _make_state(**overrides: Any) -> dict[str, Any]:
	"""BrowserStateHistory dict as written by legacy versions (no interacted_element by default)."""
	state: dict[str, Any] = {
		'url': 'https://example.com',
		'title': 'Example',
		'tabs': [],
	}
	state.update(overrides)
	return state


def _history_data(state: dict[str, Any]) -> dict[str, Any]:
	"""Minimal AgentHistoryList payload with a single legacy step."""
	return {
		'history': [
			{
				'model_output': None,
				'result': [],
				'state': state,
			}
		]
	}


def test_load_legacy_history_missing_interacted_element():
	"""Legacy AgentHistory.json entries whose state lacks the key entirely must load."""
	data = _history_data(_make_state())

	history = AgentHistoryList.load_from_dict(data, None)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []


def test_load_legacy_history_null_interacted_element():
	"""Legacy AgentHistory.json entries whose state has an explicit null must load."""
	data = _history_data(_make_state(interacted_element=None))

	history = AgentHistoryList.load_from_dict(data, None)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []


def test_load_history_with_valid_interacted_element():
	"""Regression: history containing a valid element list is unaffected by the shim."""
	data = _history_data(_make_state(interacted_element=[_VALID_ELEMENT, None]))

	history = AgentHistoryList.load_from_dict(data, None)

	assert len(history.history) == 1
	elements = history.history[0].state.interacted_element
	assert len(elements) == 2
	assert elements[0] is not None
	assert elements[0].node_name == 'BUTTON'
	assert elements[1] is None
