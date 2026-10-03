"""ChatAzureOpenAI must hand timeout and max_retries to the SDK client like ChatOpenAI does."""

from browser_use.llm.azure.chat import ChatAzureOpenAI


def _llm(**kwargs) -> ChatAzureOpenAI:
	return ChatAzureOpenAI(model='gpt-4.1-mini', api_key='test-key', azure_endpoint='https://example.openai.azure.com', **kwargs)


def test_timeout_and_max_retries_reach_the_client():
	client = _llm(timeout=13.0, max_retries=9).get_client()
	assert client.timeout == 13.0
	assert client.max_retries == 9


def test_default_max_retries_matches_chat_openai():
	assert _llm().get_client().max_retries == ChatAzureOpenAI.max_retries == 5


def test_unset_timeout_keeps_sdk_default():
	params = _llm()._get_client_params()
	assert 'timeout' not in params
