"""
Tests for AgentHistoryList.load_from_dict.

Covers:
- Non-mutation of caller-owned data (deep-copy at every level, verified with id() checks)
- Malformed history items fully filtered before model validation
- State non-dict fallback with all required BrowserStateHistory fields
- model_output normalization (None, non-dict, absent key)
- result coercion for non-list/non-iterable values
- final_result edge cases (empty result, None result, missing result)
- True model_dump -> load_from_dict round-trip

Attribution: non-mutation regression issues identified by cubic.
"""

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory, TabInfo


class TestLoadFromDictNonMutation:
	"""Caller-owned data must never be mutated by load_from_dict."""

	def test_top_level_data_dict_not_mutated(self):
		"""The caller's top-level data dict must not be modified."""
		original_history = [
			{
				'model_output': None,
				'result': [{'extracted_content': 'test', 'is_done': True}],
				'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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

	def test_history_item_dicts_not_mutated(self):
		"""Individual history item dicts must not be modified.

		Unlike id() checks alone (which only guard against replacement), this
		test also verifies in-place mutations of nested values by capturing
		the actual string/list values and asserting them unchanged after the
		call.  Together the id checks and the value checks give complete
		coverage of both replacement and mutation of caller-owned data.
		"""
		item = {
			'model_output': None,
			'result': [{'extracted_content': 'test', 'is_done': True}],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		data = {'history': [item]}
		item_id = id(item)
		state_id = id(item['state'])
		result_id = id(item['result'])
		# Capture nested values directly (not as dict copies) so that any
		# in-place mutation of those values would be visible here.
		before_url = item['state']['url']
		before_title = item['state']['title']
		before_tabs_len = len(item['state']['tabs'])
		before_result_content = item['result'][0]['extracted_content']
		before_result_is_done = item['result'][0]['is_done']

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# item dict identity preserved (not replaced)
		assert id(data['history'][0]) == item_id
		# state dict identity preserved
		assert id(data['history'][0]['state']) == state_id
		# result list identity preserved
		assert id(data['history'][0]['result']) == result_id
		# Nested values also unchanged (catches in-place mutation of state/result)
		assert item['state']['url'] == before_url
		assert item['state']['title'] == before_title
		assert len(item['state']['tabs']) == before_tabs_len
		assert item['result'][0]['extracted_content'] == before_result_content
		assert item['result'][0]['is_done'] == before_result_is_done

	def test_caller_owned_nested_state_keys_not_added(self):
		"""Caller-owned state dict must not have new keys added and values must not be mutated."""
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
		state_values_before = dict(original_state)

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# State dict must not have new keys added
		assert set(original_state.keys()) == state_keys_before
		# State dict values must not be mutated (covers in-place value changes)
		assert dict(original_state) == state_values_before

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
		result_list_id = id(original_result)
		result_item_id = id(original_result[0])
		before = [dict(r) if isinstance(r, dict) else r for r in original_result]

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# Result list identity preserved
		assert id(data['history'][0]['result']) == result_list_id
		# Result item identity preserved
		assert id(data['history'][0]['result'][0]) == result_item_id
		# Content unchanged
		assert original_result == before

	def test_model_output_dict_not_mutated_when_valid(self):
		"""Caller-owned model_output dict must not be mutated when it is a valid dict."""
		original_model_output = {
			'evaluation_previous_goal': 'good',
			'memory': 'some memory',
			'next_goal': 'finish',
			'action': [],
		}
		data = {
			'history': [
				{
					'model_output': original_model_output,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}
		# Snapshot keys/values before load_from_dict to verify no mutation
		before_keys = set(original_model_output.keys())
		before_val = original_model_output['evaluation_previous_goal']

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		# The original model_output dict keys must not be changed
		assert set(original_model_output.keys()) == before_keys
		assert original_model_output['evaluation_previous_goal'] == before_val
		# The returned pydantic model is a different object (validated)
		assert isinstance(result.history[0].model_output, AgentOutput)

	def test_caller_history_list_not_mutated_content(self):
		"""Caller-owned history list content must not be modified."""
		original_item = {
			'model_output': None,
			'result': [{'extracted_content': 'test', 'is_done': True}],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		history_list = [original_item]
		data = {'history': history_list}
		item_id = id(original_item)

		AgentHistoryList.load_from_dict(data, AgentOutput)

		# history_list content preserved (load_from_dict creates a new list)
		assert len(history_list) == 1
		assert id(history_list[0]) == item_id
		# original item still unchanged
		assert history_list[0] == original_item

	def test_caller_result_list_not_mutated_content(self):
		"""Caller-owned result list items that are dicts are preserved; non-dict items are filtered in result.

		Non-dict items in result lists (e.g. strings) are filtered out by the normalization
		logic, which is the expected behavior for data cleaning. Only dict items are kept in the
		returned result. The caller's original result list is preserved (deep-copy protects it).
		"""
		original_result = [
			'skip me',
			{'extracted_content': 'keep me', 'is_done': True},
		]
		data = {
			'history': [
				{
					'model_output': None,
					'result': original_result,
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		# Returned result is filtered to only dict items
		assert len(result.history[0].result) == 1
		assert result.history[0].result[0].extracted_content == 'keep me'
		# Caller's original result list is preserved (not modified due to deep-copy)
		assert original_result == ['skip me', {'extracted_content': 'keep me', 'is_done': True}]


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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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

	def test_missing_history_key_treated_as_empty(self):
		"""Missing 'history' key must be treated as empty list."""
		data = {}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 0

	def test_explicit_none_history_treated_as_empty(self):
		"""Explicit None for 'history' key must be treated as empty list."""
		data = {'history': None}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 0

	def test_non_dict_items_not_left_in_data_history(self):
		"""Non-dict history items must be removed before model_validate.

		Non-dict items (None, string, int) in history are filtered out so that
		model_validate receives only valid dict items. The returned object has
		correct length; the caller's data is not mutated due to deep-copy protection.
		"""
		valid_item1 = {
			'model_output': None,
			'result': [{'extracted_content': 'valid1', 'is_done': True}],
			'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
		}
		valid_item2 = {
			'model_output': None,
			'result': [{'extracted_content': 'valid2', 'is_done': False}],
			'state': {'url': 'https://test.com', 'title': 'Test', 'tabs': [], 'interacted_element': []},
		}
		# Mix valid dicts with non-dict items (None, string, int)
		data = {'history': [None, valid_item1, 'not a dict', 42, valid_item2]}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		# Returned object has correct history (non-dict items filtered)
		assert len(result.history) == 2
		assert result.history[0].result[0].extracted_content == 'valid1'
		assert result.history[1].result[0].extracted_content == 'valid2'
		# Caller's data is not mutated (deep-copy protects it)
		assert len(data['history']) == 5

	def test_result_non_list_coerced_to_empty(self):
		"""Non-list result (string) must be coerced to [] without crashing."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': 'not a list',
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].result == []

	def test_result_non_iterable_coerced_to_empty(self):
		"""Non-iterable result (int) must be coerced to [] without crashing."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': 42,
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].result == []

	def test_result_none_coerced_to_empty(self):
		"""None result must be coerced to [] without crashing."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': None,
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].result == []

	def test_result_bare_dict_coerced_to_empty(self):
		"""A bare dict result (not a list of result dicts) must be coerced to [].

		A bare dict is not a list, so it's not a valid result. Iterating a dict yields
		keys (strings) which would cause pydantic validation to fail. Coerce to [].
		"""
		data = {
			'history': [
				{
					'model_output': None,
					'result': {'extracted_content': 'should be list'},
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].result == []

	def test_result_list_non_dict_items_filtered(self):
		"""Non-dict items in a result list must be silently dropped, not cause validation errors.

		A list like ['string', 42, None] is iterable but its items are not ActionResult dicts.
		Filtering to only dict items prevents pydantic validation from failing on the remaining
		valid dict items.
		"""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [
						'skip me',
						42,
						None,
						{'extracted_content': 'keep me', 'is_done': True},
						{'extracted_content': 'keep me too', 'is_done': False},
					],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert len(result.history[0].result) == 2
		assert result.history[0].result[0].extracted_content == 'keep me'
		assert result.history[0].result[1].extracted_content == 'keep me too'


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

	def test_state_partial_missing_url_title_tabs_normalized(self):
		"""State dict missing url/title/tabs must still load without a validation error."""
		# State has interacted_element but is missing url, title, and tabs — all required
		# BrowserStateHistory fields. load_from_dict must set defaults so validation passes.
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert len(result.history) == 1
		assert result.history[0].state.url == ''
		assert result.history[0].state.title == ''
		assert result.history[0].state.tabs == []
		assert result.history[0].state.interacted_element == []

	def test_state_interacted_element_existing_preserved(self):
		"""State dict with existing 'interacted_element' must preserve it."""
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

	def test_state_wrong_type_url_normalized(self):
		"""State with non-str url must be coerced to ''."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 123, 'title': 'Example', 'tabs': [], 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].state.url == ''

	def test_state_wrong_type_tabs_normalized(self):
		"""State with non-list tabs must be coerced to []."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': 'not a list', 'interacted_element': []},
				}
			]
		}

		result = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert result.history[0].state.tabs == []


class TestLoadFromDictModelOutputNormalization:
	"""model_output field normalization: absent key / None / non-dict handled gracefully."""

	def test_model_output_absent_key_normalized_to_none(self):
		"""Absent 'model_output' key must be normalized to None."""
		data = {
			'history': [
				{
					# 'model_output' key absent
					'result': [{'extracted_content': 'test', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
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
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				},
				{
					'model_output': None,
					'result': [{'extracted_content': 'second', 'is_done': True}],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': [], 'interacted_element': []},
				},
			]
		}
		history = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history.final_result() == 'second'


class TestLoadFromDictRoundTrip:
	"""True round-trip: model_dump -> load_from_dict preserves essential data."""

	def test_roundtrip_preserves_history_structure(self):
		"""model_dump then load_from_dict must preserve history count and essential fields."""
		# Build a live AgentHistoryList, serialize it with model_dump (what gets written to disk),
		# then load it back via load_from_dict. This is a true round-trip exercising the
		# JSON-serializable dict path end-to-end.
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

	def test_roundtrip_preserves_model_output(self):
		"""model_dump -> load_from_dict must preserve validated model_output."""
		original = AgentHistoryList.load_from_dict(
			{
				'history': [
					{
						'model_output': {
							'evaluation_previous_goal': 'good',
							'memory': 'some memory',
							'next_goal': 'finish',
							'action': [],
						},
						'result': [{'extracted_content': 'result1', 'is_done': True}],
						'state': {
							'url': 'https://example.com',
							'title': 'Example Page',
							'tabs': [],
							'interacted_element': [],
						},
					},
				]
			},
			AgentOutput,
		)
		serialized = original.model_dump()
		restored = AgentHistoryList.load_from_dict(serialized, AgentOutput)

		assert restored.history[0].model_output is not None
		assert isinstance(restored.history[0].model_output, AgentOutput)
		assert restored.history[0].model_output.evaluation_previous_goal == 'good'
		assert restored.history[0].model_output.memory == 'some memory'
		assert restored.history[0].model_output.next_goal == 'finish'

	def test_roundtrip_preserves_result_metadata(self):
		"""Round-trip must preserve multiple result fields."""
		original = AgentHistoryList.load_from_dict(
			{
				'history': [
					{
						'model_output': None,
						'result': [
							{'extracted_content': 'content1', 'is_done': True, 'success': True, 'error': None},
							{'extracted_content': 'content2', 'is_done': False, 'success': None, 'error': 'some error'},
						],
						'state': {
							'url': 'https://example.com',
							'title': 'Example Page',
							'tabs': [],
							'interacted_element': [],
						},
					},
				]
			},
			AgentOutput,
		)
		serialized = original.model_dump()
		restored = AgentHistoryList.load_from_dict(serialized, AgentOutput)

		assert len(restored.history[0].result) == 2
		assert restored.history[0].result[0].extracted_content == 'content1'
		assert restored.history[0].result[0].is_done is True
		assert restored.history[0].result[0].success is True
		assert restored.history[0].result[1].extracted_content == 'content2'
		assert restored.history[0].result[1].is_done is False
		assert restored.history[0].result[1].error == 'some error'

	def test_roundtrip_from_constructed_model_exercises_full_dump_load_cycle(self):
		"""Round-trip starting from a live pydantic model catches bugs in load_from_dict alone.

		Unlike test_roundtrip_preserves_history_structure which starts from load_from_dict
		(and would miss load_from_dict bugs), this test builds a real AgentHistoryList with
		properly constructed pydantic models (AgentHistory, BrowserStateHistory, TabInfo,
		ActionResult), serializes it via model_dump, then deserializes via load_from_dict.
		"""
		# Build state with a real TabInfo object
		state = BrowserStateHistory(
			url='https://constructed.example/page',
			title='Constructed Page',
			tabs=[TabInfo(url='https://constructed.example/page', title='Constructed Page', target_id='tab-1')],
			interacted_element=[],
		)
		# Build result with a real ActionResult object
		result = [ActionResult(extracted_content='constructed result', is_done=True, success=True)]
		# Build history with real AgentHistory
		history_item = AgentHistory(
			model_output=None,
			result=result,
			state=state,
		)
		# Wrap in AgentHistoryList (this is a properly constructed, fully-validated object)
		original = AgentHistoryList(history=[history_item])

		# Serialize as the file-save path does
		serialized = original.model_dump()

		# Deserialize as load_from_file does
		restored = AgentHistoryList.load_from_dict(serialized, AgentOutput)

		# Verify round-trip data integrity
		assert len(restored.history) == 1
		assert restored.history[0].state.url == 'https://constructed.example/page'
		assert restored.history[0].state.title == 'Constructed Page'
		assert len(restored.history[0].state.tabs) == 1
		assert restored.history[0].state.tabs[0].url == 'https://constructed.example/page'
		assert restored.history[0].result[0].extracted_content == 'constructed result'
		assert restored.history[0].result[0].is_done is True
		assert restored.history[0].result[0].success is True
