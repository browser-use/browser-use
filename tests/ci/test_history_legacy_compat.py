"""Regression tests for legacy history entries written before
`BrowserStateHistory.interacted_element` existed.

Both compatibility loaders used to inject `None` for the missing field, but the
field is typed as a list, so validation rejected exactly the payloads the
compatibility branches were meant to accept.
"""

import json

import pytest
from pydantic import ValidationError

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.beta.service import _load_rust_history


def _legacy_entry(**state_overrides) -> dict:
	state = {'url': 'https://example.com', 'title': 'Example', 'tabs': []}
	state.update(state_overrides)
	return {'model_output': None, 'result': [], 'state': state}


def _assert_single_legacy_entry(history_list: AgentHistoryList) -> None:
	assert len(history_list.history) == 1
	assert history_list.history[0].state.interacted_element == []


def test_load_from_dict_accepts_missing_interacted_element():
	history = AgentHistoryList.load_from_dict({'history': [_legacy_entry()]}, AgentOutput)
	_assert_single_legacy_entry(history)


def test_load_from_dict_normalizes_none_interacted_element():
	history = AgentHistoryList.load_from_dict({'history': [_legacy_entry(interacted_element=None)]}, AgentOutput)
	_assert_single_legacy_entry(history)


def test_load_from_file_accepts_legacy_entry(tmp_path):
	path = tmp_path / 'history.json'
	path.write_text(json.dumps({'history': [_legacy_entry()]}), encoding='utf-8')
	history = AgentHistoryList.load_from_file(path, AgentOutput)
	_assert_single_legacy_entry(history)


def test_load_from_dict_still_rejects_non_list_interacted_element():
	# Normalization must stay narrow: a malformed value is a real error.
	with pytest.raises(ValidationError):
		AgentHistoryList.load_from_dict({'history': [_legacy_entry(interacted_element={'selector': 'x'})]}, AgentOutput)


def test_rust_history_accepts_missing_interacted_element(tmp_path):
	path = tmp_path / 'rust-history.json'
	path.write_text(json.dumps({'history': [_legacy_entry()]}), encoding='utf-8')
	_assert_single_legacy_entry(_load_rust_history(path))


def test_rust_history_normalizes_none_interacted_element(tmp_path):
	path = tmp_path / 'rust-history.json'
	path.write_text(json.dumps({'history': [_legacy_entry(interacted_element=None)]}), encoding='utf-8')
	_assert_single_legacy_entry(_load_rust_history(path))


def test_rust_history_still_rejects_non_list_interacted_element(tmp_path):
	# Same guard as the dict loader: the rust path must stay narrow too.
	path = tmp_path / 'rust-history.json'
	path.write_text(json.dumps({'history': [_legacy_entry(interacted_element={'selector': 'x'})]}), encoding='utf-8')
	with pytest.raises(ValidationError):
		_load_rust_history(path)
