"""Test OpenAI model button click."""


from browser_use.llm.openai.chat import ChatOpenAI
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_openai_gpt_4_1_mini(httpserver):
	"""Test OpenAI gpt-4.1-mini can click a button."""
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name='gpt-4.1-mini',
		api_key_env='OPENAI_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


class TestReasoningModelDetection:
	"""Test the reasoning model detection logic to avoid false positives."""

	def test_exact_match_is_reasoning_model(self):
		"""Test that exact model name matches are detected as reasoning models."""
		llm = ChatOpenAI(model='gpt-5', api_key='test')
		assert llm._is_reasoning_model() is True

	def test_prefix_with_hyphen_is_reasoning_model(self):
		"""Test that model names with hyphen suffix are detected as reasoning models."""
		llm = ChatOpenAI(model='gpt-5-mini', api_key='test')
		assert llm._is_reasoning_model() is True

		llm = ChatOpenAI(model='gpt-5-nano', api_key='test')
		assert llm._is_reasoning_model() is True

	def test_versioned_model_is_not_reasoning_model(self):
		"""Test that versioned models like gpt-5.2 are NOT incorrectly matched as reasoning models.

		This is the key bug fix - gpt-5.2 should NOT be treated as a reasoning model
		just because 'gpt-5' is a substring of 'gpt-5.2'.
		"""
		llm = ChatOpenAI(model='gpt-5.2', api_key='test')
		assert llm._is_reasoning_model() is False

		llm = ChatOpenAI(model='gpt-5.2-chat-latest', api_key='test')
		assert llm._is_reasoning_model() is False

		llm = ChatOpenAI(model='gpt-5.1', api_key='test')
		assert llm._is_reasoning_model() is False

	def test_o_series_reasoning_models(self):
		"""Test that o-series models are correctly detected as reasoning models."""
		llm = ChatOpenAI(model='o3', api_key='test')
		assert llm._is_reasoning_model() is True

		llm = ChatOpenAI(model='o3-mini', api_key='test')
		assert llm._is_reasoning_model() is True

		llm = ChatOpenAI(model='o4-mini', api_key='test')
		assert llm._is_reasoning_model() is True

	def test_non_reasoning_model(self):
		"""Test that non-reasoning models are correctly identified."""
		llm = ChatOpenAI(model='gpt-4.1-mini', api_key='test')
		assert llm._is_reasoning_model() is False

		llm = ChatOpenAI(model='gpt-4o', api_key='test')
		assert llm._is_reasoning_model() is False

	def test_case_insensitive_matching(self):
		"""Test that reasoning model detection is case insensitive."""
		llm = ChatOpenAI(model='GPT-5', api_key='test')
		assert llm._is_reasoning_model() is True

		llm = ChatOpenAI(model='GPT-5-MINI', api_key='test')
		assert llm._is_reasoning_model() is True

	def test_empty_reasoning_models_list(self):
		"""Test that empty reasoning models list returns False."""
		llm = ChatOpenAI(model='gpt-5', api_key='test', reasoning_models=[])
		assert llm._is_reasoning_model() is False

	def test_none_reasoning_models(self):
		"""Test that None reasoning models list returns False."""
		llm = ChatOpenAI(model='gpt-5', api_key='test', reasoning_models=None)
		assert llm._is_reasoning_model() is False
