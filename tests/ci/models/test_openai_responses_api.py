"""Tests for OpenAI Responses API support in ChatOpenAI."""

from browser_use.llm.openai.chat import RESPONSES_API_ONLY_MODELS, ChatOpenAI


class TestChatOpenAIShouldUseResponsesAPI:
	"""Tests for the _should_use_responses_api method on ChatOpenAI."""

	def test_use_responses_api_true(self):
		"""use_responses_api=True forces the Responses API for any model."""
		llm = ChatOpenAI(model='gpt-4o', api_key='test', use_responses_api=True)
		assert llm._should_use_responses_api() is True

	def test_use_responses_api_false(self):
		"""use_responses_api=False forces Chat Completions even for Responses-only models."""
		llm = ChatOpenAI(model='gpt-5-codex', api_key='test', use_responses_api=False)
		assert llm._should_use_responses_api() is False

	def test_use_responses_api_auto_with_responses_only_model(self):
		"""'auto' mode detects every model in RESPONSES_API_ONLY_MODELS."""
		for model_name in RESPONSES_API_ONLY_MODELS:
			llm = ChatOpenAI(model=model_name, api_key='test', use_responses_api='auto')
			assert llm._should_use_responses_api() is True, f'Expected Responses API for {model_name}'

	def test_use_responses_api_auto_with_regular_model(self):
		"""'auto' mode keeps regular models on Chat Completions."""
		regular_models = ['gpt-4o', 'gpt-4.1-mini', 'gpt-3.5-turbo', 'gpt-4']
		for model_name in regular_models:
			llm = ChatOpenAI(model=model_name, api_key='test', use_responses_api='auto')
			assert llm._should_use_responses_api() is False, f'Expected Chat Completions for {model_name}'

	def test_use_responses_api_auto_with_reasoning_model(self):
		"""'auto' mode keeps reasoning models (gpt-5, o-series) on Chat Completions for
		backwards compatibility — users opt in explicitly with use_responses_api=True."""
		reasoning_models = ['gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'o3', 'o3-mini', 'o4-mini']
		for model_name in reasoning_models:
			llm = ChatOpenAI(model=model_name, api_key='test', use_responses_api='auto')
			assert llm._should_use_responses_api() is False, (
				f'Reasoning model {model_name} should default to Chat Completions under auto mode'
			)

	def test_use_responses_api_auto_is_default(self):
		"""'auto' is the default value for use_responses_api."""
		llm = ChatOpenAI(model='gpt-4o', api_key='test')
		assert llm.use_responses_api == 'auto'

	def test_responses_api_only_models_list(self):
		"""RESPONSES_API_ONLY_MODELS contains the expected models."""
		expected_models = [
			'gpt-5.1-codex',
			'gpt-5.1-codex-mini',
			'gpt-5.1-codex-max',
			'gpt-5-codex',
			'codex-mini-latest',
			'computer-use-preview',
		]
		for model in expected_models:
			assert model in RESPONSES_API_ONLY_MODELS, f'{model} should be in RESPONSES_API_ONLY_MODELS'
