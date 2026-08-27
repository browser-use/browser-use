import pytest
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.groq.chat import ChatGroq


def test_openai_get_client_caching():
	chat = ChatOpenAI(model='gpt-4o', api_key='sk-test')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatOpenAI.get_client() must return the cached client instance'


def test_anthropic_get_client_caching():
	chat = ChatAnthropic(model='claude-3-5-sonnet', api_key='sk-test')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatAnthropic.get_client() must return the cached client instance'


def test_groq_get_client_caching():
	chat = ChatGroq(model='llama-3.3-70b-versatile', api_key='gsk-test')
	client1 = chat.get_client()
	client2 = chat.get_client()
	assert client1 is client2, 'ChatGroq.get_client() must return the cached client instance'
