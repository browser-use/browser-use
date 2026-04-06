"""Unit tests for variable substitution in agent history"""

from types import SimpleNamespace

from browser_use.agent.service import Agent
from browser_use.dom.views import DOMInteractedElement, NodeType


def create_test_element(attributes: dict[str, str] | None = None) -> DOMInteractedElement:
	"""Helper to create a DOMInteractedElement for testing"""
	return DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id='frame1',
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='input',
		attributes=attributes or {},
		bounds=None,
		x_path='//*[@id="test"]',
		element_hash=12345,
	)


def create_mock_history(actions_with_elements: list[tuple[dict, DOMInteractedElement | None]]):
	"""Helper to create mock history for testing"""
	history_items = []
	for action_dict, element in actions_with_elements:
		mock_action = SimpleNamespace(**action_dict)
		mock_output = SimpleNamespace(action=[mock_action])
		mock_state = SimpleNamespace(interacted_element=[element] if element else None)
		mock_history_item = SimpleNamespace(model_output=mock_output, state=mock_state)
		history_items.append(mock_history_item)

	return SimpleNamespace(history=history_items)


def test_substitute_single_variable(mock_llm):
	"""Test substitution of a single variable"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history with email
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, element),
		]
	)

	# Substitute the email
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'email': 'new@example.com'},
	)

	# Check that the value was substituted
	action = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action_dict = vars(action)
	assert action_dict['input']['text'] == 'new@example.com'


def test_substitute_multiple_variables(mock_llm):
	"""Test substitution of multiple variables"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history with email and name
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, create_test_element(attributes={'type': 'email'})),
			({'input': {'index': 2, 'text': 'John'}}, create_test_element(attributes={'name': 'first_name'})),
			({'input': {'index': 3, 'text': '1990-01-01'}}, create_test_element(attributes={'type': 'date'})),
		]
	)

	# Substitute all variables
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{
			'email': 'new@example.com',
			'first_name': 'Jane',
			'date': '1995-05-15',
		},
	)

	# Check that all values were substituted
	action1 = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action2 = modified_history.history[1].model_output.action[0]  # type: ignore[attr-defined]
	action3 = modified_history.history[2].model_output.action[0]  # type: ignore[attr-defined]

	assert vars(action1)['input']['text'] == 'new@example.com'
	assert vars(action2)['input']['text'] == 'Jane'
	assert vars(action3)['input']['text'] == '1995-05-15'


def test_substitute_partial_variables(mock_llm):
	"""Test substitution of only some variables"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history with email and name
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, create_test_element(attributes={'type': 'email'})),
			({'input': {'index': 2, 'text': 'John'}}, create_test_element(attributes={'name': 'first_name'})),
		]
	)

	# Substitute only email
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'email': 'new@example.com'},
	)

	# Check that only email was substituted
	action1 = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action2 = modified_history.history[1].model_output.action[0]  # type: ignore[attr-defined]

	assert vars(action1)['input']['text'] == 'new@example.com'
	assert vars(action2)['input']['text'] == 'John'  # Unchanged


def test_substitute_nonexistent_variable(mock_llm):
	"""Test that substituting a nonexistent variable doesn't break things"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history with email
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, element),
		]
	)

	# Try to substitute a variable that doesn't exist
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'nonexistent_var': 'some_value'},
	)

	# Check that nothing changed
	action = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action_dict = vars(action)
	assert action_dict['input']['text'] == 'old@example.com'


def test_substitute_in_nested_dict(mock_llm):
	"""Test substitution in nested dictionary structures"""
	agent = Agent(task='test', llm=mock_llm)

	# Create a more complex action with nested structure
	complex_action = {
		'search_google': {
			'query': 'test@example.com',
			'metadata': {'user': 'test@example.com'},
		}
	}

	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history([(complex_action, element)])

	# Substitute the email
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'email': 'new@example.com'},
	)

	# Check that values in nested structures were substituted
	action = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action_dict = vars(action)
	assert action_dict['search_google']['query'] == 'new@example.com'
	assert action_dict['search_google']['metadata']['user'] == 'new@example.com'


def test_substitute_in_list(mock_llm):
	"""Test substitution in list structures"""
	agent = Agent(task='test', llm=mock_llm)

	# Create history with an input action first (so email is detected)
	# Then an action with a list containing the same email
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'test@example.com'}}, create_test_element(attributes={'type': 'email'})),
			({'some_action': {'items': ['test@example.com', 'other_value', 'test@example.com']}}, None),
		]
	)

	# Substitute the email
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'email': 'new@example.com'},
	)

	# Check that values in the first action were substituted
	action1 = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	assert vars(action1)['input']['text'] == 'new@example.com'

	# Check that values in lists were also substituted
	action2 = modified_history.history[1].model_output.action[0]  # type: ignore[attr-defined]
	action_dict = vars(action2)
	assert action_dict['some_action']['items'] == ['new@example.com', 'other_value', 'new@example.com']


def test_substitute_preserves_original_history(mock_llm):
	"""Test that substitution doesn't modify the original history"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, element),
		]
	)

	# Get original value
	original_action = history.history[0].model_output.action[0]
	original_value = vars(original_action)['input']['text']

	# Substitute
	agent._substitute_variables_in_history(history, {'email': 'new@example.com'})  # type: ignore[arg-type]

	# Check that original history is unchanged
	current_value = vars(original_action)['input']['text']
	assert current_value == original_value
	assert current_value == 'old@example.com'


def test_substitute_empty_variables(mock_llm):
	"""Test substitution with empty variables dict"""
	agent = Agent(task='test', llm=mock_llm)

	# Create mock history
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, element),
		]
	)

	# Substitute with empty dict
	modified_history = agent._substitute_variables_in_history(history, {})  # type: ignore[arg-type]

	# Check that nothing changed
	action = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action_dict = vars(action)
	assert action_dict['input']['text'] == 'old@example.com'


def test_substitute_same_value_multiple_times(mock_llm):
	"""Test that the same value is substituted across multiple actions"""
	agent = Agent(task='test', llm=mock_llm)

	# Create history where same email appears twice
	element = create_test_element(attributes={'type': 'email'})
	history = create_mock_history(
		[
			({'input': {'index': 1, 'text': 'old@example.com'}}, element),
			({'input': {'index': 2, 'text': 'old@example.com'}}, element),
		]
	)

	# Substitute the email
	modified_history = agent._substitute_variables_in_history(
		history,  # type: ignore[arg-type]
		{'email': 'new@example.com'},
	)

	# Check that both occurrences were substituted
	action1 = modified_history.history[0].model_output.action[0]  # type: ignore[attr-defined]
	action2 = modified_history.history[1].model_output.action[0]  # type: ignore[attr-defined]

	assert vars(action1)['input']['text'] == 'new@example.com'
	assert vars(action2)['input']['text'] == 'new@example.com'
