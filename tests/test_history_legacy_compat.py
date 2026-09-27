import pytest
from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.beta.service import _load_rust_history
import json
import tempfile
from pathlib import Path


def test_legacy_history_entry_without_interacted_element():
	"""Verify loading legacy history where state has no interacted_element succeeds and normalizes to []."""
	data = {
		'history': [
			{
				'model_output': None,
				'result': [],
				'state': {
					'url': 'https://example.com',
					'title': 'Example Domain',
					'tabs': [],
				},
			}
		]
	}
	history_list = AgentHistoryList.load_from_dict(data, AgentOutput)
	assert len(history_list.history) == 1
	assert history_list.history[0].state.interacted_element == []


def test_legacy_history_entry_with_none_interacted_element():
	"""Verify loading legacy history where state has interacted_element: None normalizes to []."""
	data = {
		'history': [
			{
				'model_output': None,
				'result': [],
				'state': {
					'url': 'https://example.com',
					'title': 'Example Domain',
					'tabs': [],
					'interacted_element': None,
				},
			}
		]
	}
	history_list = AgentHistoryList.load_from_dict(data, AgentOutput)
	assert len(history_list.history) == 1
	assert history_list.history[0].state.interacted_element == []


def test_load_rust_history_without_interacted_element():
	"""Verify _load_rust_history normalizes missing interacted_element to []."""
	data = {
		'history': [
			{
				'model_output': None,
				'result': [],
				'state': {
					'url': 'https://example.com',
					'title': 'Example Domain',
					'tabs': [],
				},
			}
		]
	}
	with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
		json.dump(data, f)
		f_path = Path(f.name)

	try:
		history_list = _load_rust_history(f_path)
		assert len(history_list.history) == 1
		assert history_list.history[0].state.interacted_element == []
	finally:
		f_path.unlink(missing_ok=True)
