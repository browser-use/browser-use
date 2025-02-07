import asyncio
import os
import random
import string
import time

import pytest
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller


@pytest.fixture(scope='session')
def event_loop():
	loop = asyncio.get_event_loop_policy().new_event_loop()
	yield loop
	loop.close()


@pytest.fixture(scope='session')
async def browser(event_loop):
	browser_instance = Browser(
		config=BrowserConfig(
			headless=True,
		)
	)
	yield browser_instance
	await browser_instance.close()


@pytest.fixture
async def context(browser):
	async with await browser.new_context() as context:
		yield context


@pytest.fixture
def llm():
	"""Initialize the language model"""
	model = AzureChatOpenAI(
		api_version='2024-10-21',
		model='gpt-4o',
		azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
		api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
	)
	return model


def generate_random_text(length: int) -> str:
	"""Generate random text of specified length"""
	return ''.join(random.choices(string.ascii_letters + string.digits + ' ', k=length))


@pytest.fixture
async def controller():
	"""Initialize the controller"""
	controller = Controller()
	large_text = generate_random_text(10000)

	@controller.action('call this magical function to get very special text')
	def get_very_special_text():
		return large_text

	yield controller


@pytest.mark.asyncio
async def test_token_limit_with_multiple_extractions(llm, controller, context):
	"""Test handling of multiple smaller extractions accumulating tokens"""
	agent = Agent(
		task='Call the magical function to get very special text 5 times',
		llm=llm,
		controller=controller,
		browser_context=context,
		max_input_tokens=2000,
		save_conversation_path='tmp/stress_test/test_token_limit_with_multiple_extractions.json',
	)

	history = await agent.run(max_steps=5)

	# check if 5 times called get_special_text
	calls = [a for a in history.action_names() if a == 'get_very_special_text']
	assert len(calls) == 5
	# check the message history should be max 3 messages
	assert len(agent.message_manager.history.messages) > 3


@pytest.mark.slow
@pytest.mark.parametrize('max_tokens', [4000])  # 8000 20000
@pytest.mark.asyncio
async def test_open_3_tabs_and_extract_content(llm, controller, context, max_tokens):
	"""Stress test: Open 3 tabs with urls and extract content"""
	agent = Agent(
		task='Open 3 tabs with https://en.wikipedia.org/wiki/Internet and extract the content from each.',
		llm=llm,
		controller=controller,
		browser_context=context,
		max_input_tokens=max_tokens,
		save_conversation_path='tmp/stress_test/test_open_3_tabs_and_extract_content.json',
	)
	start_time = time.time()
	history = await agent.run(max_steps=7)
	end_time = time.time()

	total_time = end_time - start_time

	print(f'Total time: {total_time:.2f} seconds')
	# Check for errors
	errors = history.errors()
	assert len(errors) == 0, 'Errors occurred during the test'
	# check if 3 tabs were opened
	assert len(context.current_state.tabs) >= 3, '3 tabs were not opened'
