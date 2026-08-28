import pytest
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.groq.chat import ChatGroq


def test_openai_get_client_caching_and_invalidation():
	chat = ChatOpenAI(model='gpt-4o', api_key='sk-test-1')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatOpenAI.get_client() must return the cached client instance'

	# Mutate config -> cache invalidated and rebuilt
	chat.api_key = 'sk-test-2'
	client3 = chat.get_client()
	assert client3 is not client1, 'ChatOpenAI.get_client() must rebuild when api_key changes'
	assert chat.get_client() is client3, 'ChatOpenAI.get_client() must cache the newly rebuilt client'


def test_anthropic_get_client_caching_and_invalidation():
	chat = ChatAnthropic(model='claude-3-5-sonnet', api_key='sk-test-1')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatAnthropic.get_client() must return the cached client instance'

	# Mutate config -> cache invalidated and rebuilt
	chat.api_key = 'sk-test-2'
	client3 = chat.get_client()
	assert client3 is not client1, 'ChatAnthropic.get_client() must rebuild when api_key changes'
	assert chat.get_client() is client3, 'ChatAnthropic.get_client() must cache the newly rebuilt client'


def test_groq_get_client_caching_and_invalidation():
	chat = ChatGroq(model='llama-3.3-70b-versatile', api_key='gsk-test-1')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatGroq.get_client() must return the cached client instance'

	# Mutate config -> cache invalidated and rebuilt
	chat.api_key = 'gsk-test-2'
	client3 = chat.get_client()
	assert client3 is not client1, 'ChatGroq.get_client() must rebuild when api_key changes'
	assert chat.get_client() is client3, 'ChatGroq.get_client() must cache the newly rebuilt client'
