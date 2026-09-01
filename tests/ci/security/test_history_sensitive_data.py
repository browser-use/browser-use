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


def test_recursive_filter_redacts_the_circular_marker_when_it_is_sensitive():
	history = _history('unused').history[0]
	circular: list[object] = []
	circular.append(circular)

	filtered = history._filter_sensitive_data_from_dict({'payload': circular}, {'marker': '<circular container reference>'})

	assert len(filtered['payload'][0]) == 1
	assert '<circular container reference>' not in filtered['payload'][0]


def test_recursive_filter_redacts_chained_secrets_in_the_circular_marker():
	history = _history('unused').history[0]
	circular: list[object] = []
	circular.append(circular)
	sensitive_data: dict[str, str | dict[str, str]] = {
		'marker': '<circular container reference>',
		'generated': '<secret>marker</secret>',
	}

	filtered = history._filter_sensitive_data_from_dict({'payload': circular}, sensitive_data)

	assert len(filtered['payload'][0]) == 1
	assert all(secret not in filtered['payload'][0] for secret in sensitive_data.values())


def test_recursive_filter_redacts_generated_collision_keys():
	secret = 'token-123'
	history = _history(secret).history[0]
	generated_key = '<secret>api_key</secret>#2'

	filtered = history._filter_sensitive_data_from_dict(
		{secret: 'secret-key', '<secret>api_key</secret>': 'literal-key'},
		{'api_key': secret, 'generated_key': generated_key},
	)

	assert generated_key not in filtered
	assert '<secret>api_key</secret>' in filtered
	assert set(filtered.values()) == {'secret-key', 'literal-key'}
	assert all(secret not in key for key in filtered for secret in {'token-123', generated_key})


def test_recursive_filter_rechecks_every_changed_key_for_generated_secrets():
	history = _history('unused').history[0]
	sensitive_data: dict[str, str | dict[str, str]] = {'label': 'A', 'other': 'label'}

	filtered = history._filter_sensitive_data_from_dict({'A': 'value'}, sensitive_data)
	filtered_key = next(iter(filtered))

	assert len(filtered_key) == 1
	assert all(secret not in filtered_key for secret in sensitive_data.values())
	assert filtered[filtered_key] == 'value'


def test_recursive_filter_replaces_self_identical_secret_placeholders_in_keys_and_values():
	history = _history('unused').history[0]
	secret = '<secret>label</secret>'

	filtered = history._filter_sensitive_data_from_dict({secret: secret}, {'label': secret})
	filtered_key = next(iter(filtered))

	assert filtered_key != secret
	assert filtered[filtered_key] != secret
	assert len(filtered_key) == 1
	assert len(filtered[filtered_key]) == 1


def test_recursive_filter_preserves_identity_for_distinct_unsafe_values():
	history = _history('unused').history[0]
	secret_a = '<secret>a</secret>'
	secret_b = '<secret>b</secret>'

	filtered = history._filter_sensitive_data_from_dict(
		{'values': [secret_a, secret_a, secret_b]},
		{'a': secret_a, 'b': secret_b},
	)
	first_a, second_a, filtered_b = filtered['values']

	assert first_a == second_a
	assert first_a != filtered_b
	assert all(len(value) == 1 for value in filtered['values'])
	assert all(secret not in value for value in filtered['values'] for secret in (secret_a, secret_b))


def test_recursive_filter_does_not_reuse_an_unchanged_user_value_as_a_fallback():
	history = _history('unused').history[0]
	secret = '<secret>a</secret>'
	unchanged = '\ue000'

	filtered = history._filter_sensitive_data_from_dict({'values': [secret, unchanged]}, {'a': secret})
	filtered_secret, filtered_unchanged = filtered['values']

	assert filtered_unchanged == unchanged
	assert filtered_secret != filtered_unchanged
	assert secret not in filtered_secret


def test_recursive_filter_does_not_reuse_an_unchanged_user_value_for_a_circular_marker():
	history = _history('unused').history[0]
	unchanged = '\ue000'
	circular: list[object] = []
	circular.append(circular)

	filtered = history._filter_sensitive_data_from_dict(
		{'values': [circular, unchanged]}, {'marker': '<circular container reference>'}
	)
	filtered_circular, filtered_unchanged = filtered['values']

	assert filtered_unchanged == unchanged
	assert filtered_circular[0] != filtered_unchanged
	assert '<circular container reference>' not in filtered_circular[0]


def test_generated_string_filter_uses_an_opaque_fallback_for_replacement_cycles():
	history = _history('unused').history[0]
	sensitive_data: dict[str, str | dict[str, str]] = {
		'a': '<secret>b</secret>',
		'b': '<secret>a</secret>',
	}

	filtered = history._filter_sensitive_data_from_dict({'<secret>a</secret>': 'value'}, sensitive_data)
	filtered_key = next(iter(filtered))

	assert len(filtered_key) == 1
	assert all(secret not in filtered_key for secret in sensitive_data.values())
	assert filtered[filtered_key] == 'value'


def test_generated_string_filter_bounds_expanding_replacements():
	history = _history('unused').history[0]
	sensitive_data: dict[str, str | dict[str, str]] = {'expands': 'x', 'unrelated': 'safe'}

	filtered = history._filter_sensitive_data_from_dict({'x': 'value'}, sensitive_data)
	filtered_key = next(iter(filtered))

	assert len(filtered_key) == 1
	assert all(secret not in filtered_key for secret in sensitive_data.values())
	assert filtered[filtered_key] == 'value'


def test_generated_string_filter_skips_singleton_secrets_across_the_bmp_private_use_range():
	history = _history('unused').history[0]
	sensitive_data: dict[str, str | dict[str, str]] = {
		f'pua_{codepoint:x}': chr(codepoint) for codepoint in range(0xE000, 0xF900)
	}
	sensitive_data['generated'] = '<secret>pua_e000</secret>'

	filtered = history._filter_sensitive_data_from_dict({chr(0xE000): 'value'}, sensitive_data)
	filtered_key = next(iter(filtered))

	assert len(filtered_key) == 1
	assert filtered_key not in sensitive_data.values()
	assert ord(filtered_key) >= 0xF0000
	assert filtered[filtered_key] == 'value'


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
