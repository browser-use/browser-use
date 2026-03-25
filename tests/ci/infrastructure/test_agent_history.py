"""Tests for AgentHistoryList.load_from_dict non-mutation and backward compatibility."""

from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.tools.service import Tools


def _make_output_model():
	"""Create a concrete AgentOutput subclass with registered actions for testing."""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	return AgentOutput.type_with_custom_actions(ActionModel)


def _make_done_action():
	return {'done': {'text': 'done', 'success': True}}


class TestLoadFromDictNonMutation:
	"""Verify load_from_dict never mutates the caller's input data."""

	def test_does_not_mutate_history_list_reference(self):
		"""history entries in caller's list must not be replaced/modified."""
		AgentOutput = _make_output_model()

		entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		original_history = [entry]
		data = {'history': original_history}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# The caller's original list must still contain the original entry reference
		assert data['history'] is original_history
		assert data['history'][0] is entry

	def test_does_not_mutate_model_output_value(self):
		"""model_output dict values must not be replaced in caller's entry."""
		AgentOutput = _make_output_model()

		raw_model_output = {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''}
		entry = {
			'model_output': raw_model_output,
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		data = {'history': [entry]}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Callers model_output must still be the raw dict (not replaced with AgentOutput instance)
		assert entry['model_output'] is raw_model_output
		assert not isinstance(entry['model_output'], AgentOutput)

	def test_does_not_mutate_state_dict_reference(self):
		"""state dict in caller's entry must not be replaced."""
		AgentOutput = _make_output_model()

		original_state = {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []}
		entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': original_state,
		}
		data = {'history': [entry]}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Caller's state dict must not be replaced
		assert entry['state'] is original_state

	def test_does_not_mutate_interacted_element_when_present(self):
		"""state['interacted_element'] must not be mutated when already present."""
		AgentOutput = _make_output_model()

		state = {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': [None]}
		entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': state,
		}
		data = {'history': [entry]}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Caller's state must not be mutated
		assert state['interacted_element'] == [None]
		assert 'interacted_element' in state

	def test_does_not_mutate_interacted_element_when_absent(self):
		"""state['interacted_element'] must not be added to caller's state dict."""
		AgentOutput = _make_output_model()

		# state without interacted_element
		state = {'url': 'https://example.com', 'title': 'Example', 'tabs': []}
		entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': state,
		}
		data = {'history': [entry]}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Caller's state dict must NOT have interacted_element added
		assert 'interacted_element' not in state

	def test_does_not_mutate_result_list_reference(self):
		"""The caller's result list must not be replaced with a new list."""
		AgentOutput = _make_output_model()

		original_result = [{'extracted_content': 'test', 'is_done': True}]
		entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': original_result,
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		data = {'history': [entry]}
		original_result_item_id = id(original_result[0])

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# The caller's result list is still the same list (data['history'] assignment
		# replaces the list reference but doesn't deep-copy the nested list back).
		# Item dicts inside the list must also stay the same objects.
		assert id(data['history'][0]['result']) == id(original_result)
		assert id(original_result[0]) == original_result_item_id
		# And the list length must not change
		assert len(original_result) == 1

	def test_does_not_mutate_top_level_keys(self):
		"""Top-level keys in caller's data dict must not be replaced."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}]}

		original_history = data['history']

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# The caller's data['history'] must still be the original list (not replaced)
		# Note: data['history'] = validated_history mutates the shallow copy, not the caller
		assert data['history'] is original_history


class TestLoadFromDictBackwardCompatibility:
	"""Verify load_from_dict tolerates old and partial history schemas."""

	def test_missing_history_key(self):
		"""Must handle data with no 'history' key gracefully."""
		AgentOutput = _make_output_model()

		data = {}
		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history == []

	def test_null_history(self):
		"""Must handle history=None gracefully."""
		AgentOutput = _make_output_model()

		data = {'history': None}
		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history == []

	def test_empty_history(self):
		"""Must handle history=[] gracefully."""
		AgentOutput = _make_output_model()

		data = {'history': []}
		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history == []

	def test_non_dict_history_entry_skipped(self):
		"""Non-dict items in history must be skipped without raising."""
		AgentOutput = _make_output_model()

		valid_entry = {
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		data = {'history': [None, 'not-a-dict', valid_entry, 42]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		# Only the valid dict entry should be in the result
		assert len(result.history) == 1

	def test_missing_model_output_key(self):
		"""Must handle entries without 'model_output' key."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].model_output is None

	def test_null_model_output(self):
		"""Must handle model_output=None gracefully."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': None,
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].model_output is None

	def test_non_dict_non_null_model_output_normalized_to_none(self):
		"""model_output present but not a dict must be normalized to None."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': 'invalid-string',
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].model_output is None

	def test_state_none_normalized(self):
		"""state=None must be normalized to a valid dict with interacted_element=[]."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': None,
			'result': [],
			'state': None,
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == []

	def test_state_missing_normalized(self):
		"""Missing state must be normalized to a valid dict with all required fields."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': None,
			'result': [],
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == []
		assert result.history[0].state.url == ''
		assert result.history[0].state.title == ''
		assert result.history[0].state.tabs == []

	def test_state_non_dict_normalized(self):
		"""state as non-dict (e.g., string) must be normalized to a valid dict."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': None,
			'result': [],
			'state': 'not-a-dict',
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == []
		assert result.history[0].state.url == ''
		assert result.history[0].state.title == ''
		assert result.history[0].state.tabs == []

	def test_state_partial_fields_normalized(self):
		"""state with missing url/title/tabs must get defaults, preserving interacted_element."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': None,
			'result': [],
			'state': {'interacted_element': [None]},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == [None]
		assert result.history[0].state.url == ''
		assert result.history[0].state.title == ''
		assert result.history[0].state.tabs == []

	def test_state_interacted_element_absent_added(self):
		"""state without interacted_element must get interacted_element=[] added."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == []

	def test_state_interacted_element_already_list_preserved(self):
		"""state with existing interacted_element must preserve the list."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': {'action': [_make_done_action()], 'memory': 'test', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': [None]},
		}]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.interacted_element == [None]


class TestFinalResult:
	"""Verify final_result() is guarded against empty result list."""

	def test_final_result_returns_none_when_result_is_empty(self):
		"""final_result() must return None (not IndexError) when last step has empty result."""
		AgentOutput = _make_output_model()

		data = {'history': [{
			'model_output': {'action': [_make_done_action()], 'memory': '', 'evaluation_previous_goal': '', 'next_goal': ''},
			'result': [],  # Empty result list
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}]}

		history = AgentHistoryList.load_from_dict(data, AgentOutput)
		result = history.final_result()

		assert result is None
