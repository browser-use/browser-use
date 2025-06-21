import os
import random
import string
import time

import pytest
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.controller.service import Controller


@pytest.fixture
async def browser_session():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


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


async def test_token_limit_with_multiple_extractions(llm, controller, browser_session):
	"""Test handling of multiple smaller extractions accumulating tokens"""
	agent = Agent(
		task='Call the magical function to get very special text 5 times',
		llm=llm,
		controller=controller,
		browser_session=browser_session,
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
async def test_open_3_tabs_and_extract_content(llm, controller, browser_session, max_tokens):
	"""Stress test: Open 3 tabs with urls and extract content"""
	agent = Agent(
		task='Open 3 tabs with https://en.wikipedia.org/wiki/Internet and extract the content from each.',
		llm=llm,
		controller=controller,
		browser_session=browser_session,
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
	current_state = await browser_session.get_state_summary()
	assert len(current_state.tabs) >= 3, '3 tabs were not opened'
