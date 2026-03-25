"""
Tests for AgentHistoryList.load_from_dict.

Covers:
- Non-mutation of caller-owned data (shallow copies at every level)
- Malformed history items fully filtered before model validation
- State non-dict fallback with all required BrowserStateHistory fields
- model_output normalization (None, non-dict, absent key)
- final_result edge cases (empty result, None result, missing result)
- Normal happy-path round-trip
"""

from browser_use.agent.views import AgentHistoryList, AgentOutput


class TestLoadFromDictNonMutation:
	"""Caller-owned data must never be mutated by load_from_dict."""

	def test_top_level_data_dict_not_mutated(self):
		"""The caller's top-level data dict must not be modified."""
		original_history = [
			{
				'model_output': None,
				'result': [{'extracted_content': 'test', 'is_done': True}],
				'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
			}
		]
		data = {'history': original_history}
		original_id = id(data)
		original_history_id = id(data['history'])

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Top-level dict identity preserved
		assert id(data) == original_id
		# history list identity preserved (not replaced)
		assert id(data['history']) == original_history_id

	def test_history_items_not_mutated(self):
		"""Individual history item dicts must not be modified."""
		item = {
			'model_output': None,
			'result': [{'extracted_content': 'test', 'is_done': True}],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
		}
		data = {'history': [item]}
		original_item_id = id(item)
		original_state_id = id(item['state'])

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Item dict identity preserved
		assert id(data['history'][0]) == original_item_id
		# State dict identity preserved
		assert id(data['history'][0]['state']) == original_state_id

	def test_caller_owned_nested_state_not_mutated(self):
		"""Caller-owned state dict inside history items must not be mutated."""
		original_state = {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []}
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': original_state,
				}
			]
		}
		state_keys_before = set(original_state.keys())

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# State dict must not have new keys added
		assert set(original_state.keys()) == state_keys_before
		# State dict identity preserved
		assert id(data['history'][0]['state']) == id(original_state)

	def test_caller_owned_result_list_not_mutated(self):
		"""Caller-owned result list inside history items must not be mutated."""
		original_result = [{'extracted_content': 'test', 'is_done': True}]
		data = {
			'history': [
				{
					'model_output': None,
					'result': original_result,
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}
		result_len_before = len(original_result)
		original_result_item_id = id(original_result[0])

		AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(original_result) == result_len_before
		# The caller's result list is still the same object (data['history'] assignment
		# replaces the list reference, but doesn't deep-copy the nested list back).
		# The item dicts inside the list must also stay the same objects.
		assert id(data['history'][0]['result']) == id(original_result)
		assert id(original_result[0]) == original_result_item_id


class TestLoadFromDictMalformedHistory:
	"""Malformed history items must be silently filtered, not cause validation errors."""

	def test_none_history_item_filtered(self):
		"""None items in history must be skipped; rest must load successfully."""
		data = {
			'history': [
				None,
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				},
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].result[0].extracted_content == 'test'

	def test_string_history_item_filtered(self):
		"""String items in history must be skipped."""
		data = {
			'history': [
				'not a dict',
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				},
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1

	def test_list_history_item_filtered(self):
		"""List items in history must be skipped."""
		data = {
			'history': [
				[1, 2, 3],
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				},
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1

	def test_empty_history_acceptable(self):
		"""Empty history list must load without error."""
		data = {'history': []}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 0

	def test_missing_history_treated_as_empty(self):
		"""Missing 'history' key must be treated as empty list."""
		data = {}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 0

	def test_explicit_none_history_treated_as_empty(self):
		"""Explicit None for 'history' key must be treated as empty list."""
		data = {'history': None}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 0


class TestLoadFromDictStateNormalization:
	"""State field normalization: non-dict/missing must not cause validation errors."""

	def test_state_missing_uses_defaults(self):
		"""Missing state must not cause a validation error; defaults are applied."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					# 'state' key absent entirely
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.url == ''
		assert result.history[0].state.title == ''
		assert result.history[0].state.tabs == []
		assert result.history[0].state.interacted_element == []

	def test_state_is_string_uses_defaults(self):
		"""Non-dict state (e.g., string) must not cause a validation error."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': 'not a dict',
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.url == ''
		assert result.history[0].state.interacted_element == []

	def test_state_is_none_uses_defaults(self):
		"""Explicit None state must not cause a validation error."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': None,
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.url == ''

	def test_state_interacted_element_missing_gets_default(self):
		"""State dict without 'interacted_element' must get default []."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].state.interacted_element == []

	def test_state_interacted_element_existing_preserved(self):
		"""State dict with existing 'interacted_element' must preserve it."""
		# interacted_element is list[DOMInteractedElement | None]; use empty list
		# which is the most common case and clearly valid.
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {
						'url': 'https://example.com',
						'title': 'Example',
						'tabs': [],
						'interacted_element': [],
					},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].state.interacted_element == []


class TestLoadFromDictModelOutputNormalization:
	"""model_output field normalization: absent key / None / non-dict handled gracefully."""

	def test_model_output_absent_key_normalized_to_none(self):
		"""Absent 'model_output' key must be normalized to None."""
		data = {
			'history': [
				{
					# 'model_output' key absent
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].model_output is None

	def test_model_output_explicit_none_normalized_to_none(self):
		"""Explicit None model_output must remain None."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].model_output is None

	def test_model_output_non_dict_normalized_to_none(self):
		"""Non-dict model_output (e.g., string) must be normalized to None."""
		data = {
			'history': [
				{
					'model_output': 'invalid string',
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].model_output is None

	def test_model_output_valid_dict_validated(self):
		"""Valid dict model_output must be pydantic-validated to AgentOutput."""
		data = {
			'history': [
				{
					'model_output': {
						'evaluation_previous_goal': 'good',
						'memory': 'some memory',
						'next_goal': 'finish',
						'action': [],
					},
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].model_output is not None
		assert isinstance(result.history[0].model_output, AgentOutput)
		assert result.history[0].model_output.evaluation_previous_goal == 'good'


class TestLoadFromDictFinalResult:
	"""final_result() edge cases covered by guards in load_from_dict and the method itself."""

	def test_final_result_returns_none_when_history_empty(self):
		"""final_result must return None when history is empty."""
		data = {'history': []}
		history = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history.final_result() is None

	def test_final_result_returns_none_when_result_empty(self):
		"""final_result must return None when last step has empty result list."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}
		history = AgentHistoryList.load_from_dict(data, AgentOutput)

		# result is empty list so final_result returns None
		assert history.final_result() is None

	def test_final_result_returns_content(self):
		"""final_result returns extracted_content when present."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'the answer is 42', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}
		history = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history.final_result() == 'the answer is 42'

	def test_final_result_last_step_wins(self):
		"""final_result returns the last step's extracted_content."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'first', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				},
				{
					'model_output': None,
					'result': [{'extracted_content': 'second', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				},
			]
		}
		history = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history.final_result() == 'second'


class TestLoadFromDictRoundTrip:
	"""Happy-path round-trip: model_dump -> load_from_dict preserves essential data."""

	def test_roundtrip_preserves_history_structure(self):
		"""Serializing and deserializing preserves history count and essential fields."""
		# Build a live AgentHistoryList, serialize it with model_dump (realistic JSON
		# output), then load it back via load_from_dict. This is a true round-trip that
		# exercises the JSON-serializable dict path end-to-end.
		original = AgentHistoryList.load_from_dict(
			{
				'history': [
					{
						'model_output': None,
						'result': [{'extracted_content': 'result1', 'is_done': True}],
						'state': {
							'url': 'https://example.com',
							'title': 'Example Page',
							'tabs': [],
							'interacted_element': [],
						},
					},
					{
						'model_output': None,
						'result': [{'extracted_content': 'result2', 'is_done': False}],
						'state': {
							'url': 'https://example.com/page2',
							'title': 'Example Page 2',
							'tabs': [],
							'interacted_element': [],
						},
					},
				]
			},
			AgentOutput,
		)
		# Serialize to a plain dict (this is what gets written to disk)
		serialized = original.model_dump()
		# Deserialize from the serialized form (this is what load_from_file does)
		restored = AgentHistoryList.load_from_dict(serialized, AgentOutput)

		assert len(restored.history) == 2
		assert restored.history[0].result[0].extracted_content == 'result1'
		assert restored.history[1].result[0].extracted_content == 'result2'
		assert restored.history[0].state.url == 'https://example.com'
		assert restored.history[1].state.url == 'https://example.com/page2'
		# The round-trip must preserve is_done flag (a common field)
		assert restored.history[0].result[0].is_done is True
		assert restored.history[1].result[0].is_done is False
