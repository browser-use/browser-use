from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.tools.service import Tools


def _make_history_with_partial_metadata(
	results: list[ActionResult],
	interacted_elements: list[None],
) -> AgentHistoryList:
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)

	return AgentHistoryList(
		history=[
			AgentHistory(
				model_output=AgentOutputWithActions(
					evaluation_previous_goal='Opened the page',
					memory='Need to report the result',
					next_goal='Finish',
					action=[
						ActionModel(done={'text': 'first action', 'success': False}),
						ActionModel(done={'text': 'second action', 'success': True}),
					],
				),
				result=results,
				state=BrowserStateHistory(
					url='https://example.com',
					title='Example',
					tabs=[],
					interacted_element=interacted_elements,
				),
			)
		]
	)


def test_model_actions_preserves_actions_when_interacted_elements_shorter():
	history = _make_history_with_partial_metadata(
		results=[
			ActionResult(long_term_memory='first result'),
			ActionResult(long_term_memory='second result'),
		],
		interacted_elements=[None],
	)

	actions = history.model_actions()

	assert [action['done']['text'] for action in actions] == ['first action', 'second action']
	assert actions[0]['interacted_element'] is None
	assert actions[1]['interacted_element'] is None


def test_action_history_preserves_actions_when_results_shorter():
	history = _make_history_with_partial_metadata(
		results=[ActionResult(long_term_memory='first result')],
		interacted_elements=[None, None],
	)

	action_history = history.action_history()

	assert len(action_history) == 1
	assert [action['done']['text'] for action in action_history[0]] == ['first action', 'second action']
	assert action_history[0][0]['result'] == 'first result'
	assert action_history[0][1]['result'] is None
