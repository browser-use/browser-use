"""Tests for loading legacy AgentHistory JSON lacking `interacted_element`.

Older browser-use versions serialized `BrowserStateHistory` without an
`interacted_element` key (or with an explicit `null`). `AgentHistoryList.load_from_dict`
normalizes those entries before validation; these tests make sure loading such
legacy history does not raise and produces an empty element list, while valid
modern history keeps loading unchanged.

Pure dict based tests - no browser required.
"""

from typing import Any

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.dom.views import DOMInteractedElement, SerializedDOMState

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

	history = AgentHistoryList.load_from_dict(data, AgentOutput)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []


def test_load_legacy_history_null_interacted_element():
	"""Legacy AgentHistory.json entries whose state has an explicit null must load."""
	data = _history_data(_make_state(interacted_element=None))

	history = AgentHistoryList.load_from_dict(data, AgentOutput)

	assert len(history.history) == 1
	assert history.history[0].state.interacted_element == []


def test_load_history_with_valid_interacted_element():
	"""Regression: history containing a valid element list is unaffected by the shim."""
	data = _history_data(_make_state(interacted_element=[_VALID_ELEMENT, None]))

	history = AgentHistoryList.load_from_dict(data, AgentOutput)

	assert len(history.history) == 1
	elements = history.history[0].state.interacted_element
	assert len(elements) == 2
	assert elements[0] is not None
	assert elements[0].node_name == 'BUTTON'
	assert elements[1] is None


def _element(**overrides: Any) -> DOMInteractedElement:
	data = dict(_VALID_ELEMENT)
	data.update(overrides)
	return DOMInteractedElement(**data)


def test_history_step_with_more_actions_than_elements_does_not_crash():
	"""Bounds guard: a rerun step whose action list is longer than its
	`interacted_element` list must not raise IndexError.

	The out-of-range actions fall back to `historical_elem=None`, which
	`_update_action_indices` passes through unchanged, so the whole step still
	executes as a batch (the pre-existing replay semantics for histories that
	carry no element info).
	"""
	import asyncio
	import logging
	from functools import partial
	from types import SimpleNamespace
	from unittest.mock import AsyncMock

	from browser_use import Tools
	from browser_use.agent.service import Agent

	registered_action_model = Tools().registry.create_action_model()
	output_cls = AgentOutput.type_with_custom_actions(registered_action_model)
	history_item = AgentHistory(
		model_output=output_cls(action=[{'click': {'index': 1}}, {'click': {'index': 2}}]),  # type: ignore[arg-type]
		result=[],
		state=BrowserStateHistory(
			url='https://example.com', title='t', tabs=[], interacted_element=[_element()]
		),  # one element for two actions
	)
	state = SimpleNamespace(dom_state=SerializedDOMState(_root=None, selector_map={}))  # type: ignore[arg-type]
	executed: list[Any] = []

	async def fake_multi_act(actions: Any, **_: Any) -> list[ActionResult]:
		executed.extend(actions)
		return [ActionResult() for _ in actions]

	fake_self = SimpleNamespace(
		browser_session=SimpleNamespace(get_browser_state_summary=AsyncMock(return_value=state)),
		logger=logging.getLogger('test_history_legacy_load'),
		multi_act=fake_multi_act,
	)
	fake_self._update_action_indices = partial(Agent._update_action_indices, fake_self)  # type: ignore[assignment]

	results = asyncio.run(Agent._execute_history_step(fake_self, history_item, 0))  # type: ignore[arg-type]

	assert len(results) == 2, 'both actions must execute: no IndexError from the shorter element list'
	assert len(executed) == 2
	assert executed[1].model_dump(exclude_unset=True) == {'click': {'index': 2}}, (
		'out-of-range action passes through with its original index'
	)
