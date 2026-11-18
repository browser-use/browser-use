"""History loading must leave caller-owned serialized history reusable."""

import copy
import json

import pytest
from pydantic import ValidationError

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.tools.registry.views import ActionModel


class HistoryAction(ActionModel):
	wait: int


HistoryOutput = AgentOutput.type_with_custom_actions(HistoryAction)


@pytest.fixture
def history_data():
	return {
		'history': [
			{
				'model_output': {'action': [{'wait': 2}]},
				'result': [],
				'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
			}
		]
	}


def test_load_from_dict_preserves_serialized_input(history_data):
	"""Loading must not replace the source action dictionary with a model."""
	original = copy.deepcopy(history_data)
	loaded = AgentHistoryList.load_from_dict(history_data, HistoryOutput)

	assert loaded.last_action() == {'wait': 2}
	assert history_data == original
	assert json.loads(json.dumps(history_data)) == original


def test_load_from_dict_can_reuse_the_same_input(history_data):
	"""Loading a cached history twice must preserve actions on both loads."""
	first = AgentHistoryList.load_from_dict(history_data, HistoryOutput)
	second = AgentHistoryList.load_from_dict(history_data, HistoryOutput)

	assert first.last_action() == second.last_action() == {'wait': 2}


def test_failed_load_from_dict_preserves_input(history_data):
	"""A validation failure must not leave an input partially converted."""
	del history_data['history'][0]['state']['url']
	original = copy.deepcopy(history_data)

	with pytest.raises(ValidationError):
		AgentHistoryList.load_from_dict(history_data, HistoryOutput)

	assert history_data == original
