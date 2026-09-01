from pydantic import BaseModel

from browser_use.agent.views import AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.tools.registry.views import ActionModel


class HistorySensitiveParams(BaseModel):
	rows: list[list[str]]
	payload: tuple[dict[str, tuple[str, list[str]]], ...]
	lookup: dict[str, str]
	unchanged: str


class HistorySensitiveAction(ActionModel):
	input: HistorySensitiveParams


def _history(secret: str) -> AgentHistoryList:
	custom_output = AgentOutput.type_with_custom_actions(HistorySensitiveAction)
	return AgentHistoryList(
		history=[
			AgentHistory(
				model_output=custom_output(
					evaluation_previous_goal='ok',
					memory='ok',
					next_goal='done',
					action=[
						HistorySensitiveAction(
							input=HistorySensitiveParams(
								rows=[[secret]],
								payload=({'credentials': (secret, ['safe', secret])},),
								lookup={secret: 'secret-key', '<secret>api_key</secret>': 'literal-key'},
								unchanged='safe',
							)
						)
					],
				),
				result=[],
				state=BrowserStateHistory(
					url='about:blank',
					title='Blank',
					tabs=[],
					interacted_element=[],
				),
			)
		]
	)


def test_model_dump_redacts_secrets_inside_nested_action_containers():
	secret = 'token-123'

	dumped = _history(secret).history[0].model_dump(sensitive_data={'api_key': secret})
	input_data = dumped['model_output']['action'][0]['input']

	assert input_data['rows'] == [['<secret>api_key</secret>']]
	assert input_data['payload'] == [{'credentials': ['<secret>api_key</secret>', ['safe', '<secret>api_key</secret>']]}]
	assert input_data['lookup'] == {
		'<secret>api_key</secret>#2': 'secret-key',
		'<secret>api_key</secret>': 'literal-key',
	}
	assert input_data['unchanged'] == 'safe'


def test_save_to_file_redacts_secrets_inside_nested_action_containers(tmp_path):
	secret = 'token-123'
	output_path = tmp_path / 'history.json'

	_history(secret).save_to_file(output_path, sensitive_data={'api_key': secret})
	saved = output_path.read_text(encoding='utf-8')

	assert secret not in saved
	assert '<secret>api_key</secret>' in saved


def test_recursive_filter_preserves_tuple_containers():
	secret = 'token-123'
	history = _history(secret).history[0]

	filtered = history._filter_sensitive_data_from_dict(
		{'payload': ({'credentials': (secret, ['safe', secret])},)},
		{'api_key': secret},
	)

	assert filtered == {'payload': ({'credentials': ('<secret>api_key</secret>', ['safe', '<secret>api_key</secret>'])},)}
	assert isinstance(filtered['payload'], tuple)
	assert isinstance(filtered['payload'][0]['credentials'], tuple)


def test_recursive_filter_preserves_literal_keys_regardless_of_order():
	secret = 'token-123'
	history = _history(secret).history[0]
	expected = {
		'<secret>api_key</secret>': 'literal-key',
		'<secret>api_key</secret>#2': 'secret-key',
	}

	assert history._filter_sensitive_data_from_dict(
		{secret: 'secret-key', '<secret>api_key</secret>': 'literal-key'}, {'api_key': secret}
	) == {
		'<secret>api_key</secret>#2': 'secret-key',
		'<secret>api_key</secret>': 'literal-key',
	}
	assert (
		history._filter_sensitive_data_from_dict(
			{'<secret>api_key</secret>': 'literal-key', secret: 'secret-key'}, {'api_key': secret}
		)
		== expected
	)


def test_recursive_filter_replaces_circular_containers():
	secret = 'token-123'
	history = _history(secret).history[0]
	circular: list[object] = []
	circular.append(circular)

	filtered = history._filter_sensitive_data_from_dict({'payload': circular}, {'api_key': secret})

	assert filtered == {'payload': ['<circular container reference>']}


def test_recursive_filter_handles_deep_containers_without_recursion():
	secret = 'token-123'
	history = _history(secret).history[0]
	nested: object = secret
	for _ in range(1100):
		nested = [nested]

	filtered = history._filter_sensitive_data_from_dict({'payload': nested}, {'api_key': secret})
	leaf = filtered['payload']
	for _ in range(1100):
		leaf = leaf[0]
	assert leaf == '<secret>api_key</secret>'
