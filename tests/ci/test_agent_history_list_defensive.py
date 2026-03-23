"""Regression tests for AgentHistoryList.load_from_dict and final_result edge cases."""

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput, BrowserStateHistory


def test_load_from_dict_missing_top_level_history_key():
	loaded = AgentHistoryList.load_from_dict({}, AgentOutput)
	assert loaded.history == []


def test_load_from_dict_step_without_model_output_key():
	state = {
		'url': 'https://example.com',
		'title': 'Test',
		'tabs': [],
		'interacted_element': [],
	}
	data = {'history': [{'result': [], 'state': state}]}
	loaded = AgentHistoryList.load_from_dict(data, AgentOutput)
	assert len(loaded.history) == 1
	assert loaded.history[0].model_output is None


def test_final_result_returns_none_when_last_step_result_empty():
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[],
				state=BrowserStateHistory(
					url='https://example.com',
					title='Test',
					tabs=[],
					interacted_element=[],
				),
			)
		]
	)
	assert history.final_result() is None


def test_final_result_returns_content_when_last_step_has_results():
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[ActionResult(extracted_content='done', is_done=True)],
				state=BrowserStateHistory(
					url='https://example.com',
					title='Test',
					tabs=[],
					interacted_element=[],
				),
			)
		]
	)
	assert history.final_result() == 'done'
