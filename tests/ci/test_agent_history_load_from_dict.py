"""
Tests for AgentHistoryList.load_from_dict.

Covers:
- Non-mutation of caller-owned data (deep copy at every level)
- Malformed history items fully filtered before model validation
- State non-dict fallback with all required BrowserStateHistory fields
- model_output normalization (None, non-dict, absent key)
- final_result edge cases (empty result, None result, missing result)
- Normal happy-path round-trip

Source: cubic automated review of PR #4479/PR #4488
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
		before = {
			'model_output': item['model_output'],
			'result': [dict(r) if isinstance(r, dict) else r for r in item['result']],
			'state': dict(item['state']),
		}

		AgentHistoryList.load_from_dict(data, AgentOutput)

		assert item == before

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
		before = [dict(r) if isinstance(r, dict) else r for r in original_result]

		AgentHistoryList.load_from_dict(data, AgentOutput)

		assert original_result == before


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

	def test_result_non_list_does_not_crash(self):
		"""Non-list result (string, int, etc.) must not crash load_from_dict."""
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

		# Must load gracefully with empty result
		assert len(result.history) == 1
		assert result.history[0].result == []

	def test_result_non_iterable_does_not_crash(self):
		"""Non-iterable result (int) must not crash load_from_dict."""
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


class TestFinalResultGuards:
	"""final_result() must not crash on empty/missing/None result."""

	def test_final_result_empty_history_returns_none(self):
		"""Empty history must not crash final_result."""
		data = {'history': []}
		history_list = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history_list.final_result() is None

	def test_final_result_missing_result_field_returns_none(self):
		"""History item without 'result' field must not crash final_result."""
		data = {
			'history': [
				{
					'model_output': None,
					# 'result' absent
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}
		history_list = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history_list.final_result() is None

	def test_final_result_empty_result_list_returns_none(self):
		"""History item with empty result list must not crash final_result."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}
		history_list = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history_list.final_result() is None

	def test_final_result_returns_extracted_content(self):
		"""final_result must return extracted_content from the last result entry."""
		data = {
			'history': [
				{
					'model_output': None,
					'result': [
						{'extracted_content': 'first content', 'is_done': False},
						{'extracted_content': 'final content', 'is_done': True},
					],
					'state': {'url': 'https://example.com', 'title': 'Example', 'tabs': []},
				}
			]
		}
		history_list = AgentHistoryList.load_from_dict(data, AgentOutput)

		assert history_list.final_result() == 'final content'


class TestLoadFromDictRoundTrip:
	"""True serialization/deserialization round-trip: model_dump -> load_from_dict."""

	def test_roundtrip_preserves_history_structure(self):
		"""A true round-trip (model_dump then load_from_dict) preserves history structure."""
		# Build a live AgentHistoryList with a real AgentHistory item
		history_list = AgentHistoryList(
			history=[
				{
					'model_output': None,
					'result': [{'extracted_content': 'round-trip test', 'is_done': True}],
					'state': {
						'url': 'https://roundtrip.example.com',
						'title': 'Round Trip',
						'tabs': [],
						'interacted_element': [],
					},
				}
			]
		)

		# Dump to dict (serialization)
		dumped = history_list.model_dump()

		# Load back (deserialization)
		reloaded = AgentHistoryList.load_from_dict(dumped, AgentOutput)

		assert len(reloaded.history) == 1
		assert reloaded.history[0].result[0].extracted_content == 'round-trip test'
		assert reloaded.history[0].state.url == 'https://roundtrip.example.com'

	def test_roundtrip_non_destructively_modifies_data(self):
		"""Round-trip must not modify the original dumped dict."""
		history_list = AgentHistoryList(
			history=[
				{
					'model_output': None,
					'result': [{'extracted_content': 'preserve me', 'is_done': True}],
					'state': {'url': 'https://preserve.example.com', 'title': 'Preserve', 'tabs': [], 'interacted_element': []},
				}
			]
		)
		dumped = history_list.model_dump()
		original_history_len = len(dumped['history'])

		AgentHistoryList.load_from_dict(dumped, AgentOutput)

		# Dumped data must not be mutated
		assert len(dumped['history']) == original_history_len
