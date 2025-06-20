import os

import pytest
from pydantic import BaseModel

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.messages import AssistantMessage, BaseMessage, SystemMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


class CapitalResponse(BaseModel):
	"""Structured response for capital question"""

	country: str
	capital: str


# OpenAI Tests
@pytest.mark.asyncio
async def test_openai_ainvoke_normal():
	"""Test normal text response from OpenAI"""
	# Skip if no API key
	if not os.getenv('OPENAI_API_KEY'):
		pytest.skip('OPENAI_API_KEY not set')

	chat = ChatOpenAI(model_name='gpt-4o-mini', temperature=0)

	messages: list[BaseMessage] = [
		SystemMessage(content='You are a helpful assistant.'),
		UserMessage(content='What is the capital of France? Answer in one word.'),
		AssistantMessage(content='Paris'),
		UserMessage(content='What is the capital of Germany? Answer in one word.'),
	]

	response = await chat.ainvoke(messages)

	assert isinstance(response, str)
	assert 'berlin' in response.lower()


@pytest.mark.asyncio
async def test_openai_ainvoke_structured():
	"""Test structured output from OpenAI"""
	# Skip if no API key
	if not os.getenv('OPENAI_API_KEY'):
		pytest.skip('OPENAI_API_KEY not set')

	chat = ChatOpenAI(model_name='gpt-4o-mini', temperature=0)

	messages: list[BaseMessage] = [UserMessage(content='What is the capital of France?')]

	response = await chat.ainvoke(messages, output_format=CapitalResponse)

	assert isinstance(response, CapitalResponse)
	assert response.country.lower() == 'france'
	assert response.capital.lower() == 'paris'


# Anthropic Tests
@pytest.mark.asyncio
async def test_anthropic_ainvoke_normal():
	"""Test normal text response from Anthropic"""
	# Skip if no API key
	if not os.getenv('ANTHROPIC_API_KEY'):
		pytest.skip('ANTHROPIC_API_KEY not set')

	chat = ChatAnthropic(model_name='claude-3-5-haiku-latest', max_tokens=100, temperature=0)

	messages: list[BaseMessage] = [
		SystemMessage(content='You are a helpful assistant.'),
		UserMessage(content='What is the capital of France? Answer in one word.'),
		AssistantMessage(content='Paris'),
		UserMessage(content='What is the capital of Germany? Answer in one word.'),
	]

	response = await chat.ainvoke(messages)

	assert isinstance(response, str)
	assert 'berlin' in response.lower()


@pytest.mark.asyncio
async def test_anthropic_ainvoke_structured():
	"""Test structured output from Anthropic"""
	# Skip if no API key
	if not os.getenv('ANTHROPIC_API_KEY'):
		pytest.skip('ANTHROPIC_API_KEY not set')

	chat = ChatAnthropic(model_name='claude-3-5-haiku-latest', max_tokens=100, temperature=0)

	messages: list[BaseMessage] = [UserMessage(content='What is the capital of France?')]

	response = await chat.ainvoke(messages, output_format=CapitalResponse)

	assert isinstance(response, CapitalResponse)
	assert response.country.lower() == 'france'
	assert response.capital.lower() == 'paris'
