import asyncio
import random
import string
import time

import pytest
from langchain_openai import ChatOpenAI

from browser_use.agent.service import Agent
from browser_use.browser.views import BrowserState
from browser_use.controller.service import Controller


@pytest.fixture
def llm():
	"""Initialize the language model"""
	return ChatOpenAI(model='gpt-4o')  # Use appropriate model


def generate_random_text(length: int) -> str:
	"""Generate random text of specified length"""
	return ''.join(random.choices(string.ascii_letters + string.digits + ' ', k=length))


@pytest.fixture
async def controller():
	"""Initialize the controller"""
	controller = Controller()
	large_text = generate_random_text(12345)

	@controller.action('call this magical function to get very special text')
	def get_very_special_text():
		return large_text

	@controller.action('Concatenate strings')
	def concatenate_strings(str1: str, str2: str):
		return large_text

	try:
		yield controller
	finally:
		if controller.browser:
			controller.browser.close(force=True)


@pytest.mark.asyncio
async def test_token_limit_with_large_extraction(llm, controller):
	"""Test handling of large extracted content exceeding token limit"""
	# Generate large text that will exceed token limit

	agent = Agent(
		task='Concatenate strings  times',
		llm=llm,
		controller=controller,
		max_input_tokens=5000,
	)

	history = await agent.run(max_steps=3)
	if history[-1].model_output:
		last_action = history[-1].model_output.action
		# Verify that messages were properly truncated
		assert last_action == 'done'
		# Verify the agent didn't crash and completed some steps
		assert len(history) > 0


@pytest.mark.asyncio
async def test_token_limit_with_multiple_extractions(llm, controller):
	"""Test handling of multiple smaller extractions accumulating tokens"""

	agent = Agent(
		task='Give me the special text 5 times',
		llm=llm,
		controller=controller,
		max_input_tokens=4000,
	)

	history = await agent.run(max_steps=10)
	if history[-1].model_output:
		last_action = history[-1].model_output.action
		assert last_action == 'done'

	# ckeck if 5 times called get_special_text
	calls = [
		h.model_output.action
		for h in history
		if h.model_output and h.model_output.action == 'get_special_text'
	]
	assert len(calls) == 5


# should get rate limited
@pytest.mark.asyncio
async def test_open_10_tabs_and_extract_content(llm, controller):
	"""Stress test: Open 10 tabs and extract content"""
	agent = Agent(
		task='Open new tabs with example.com, example.net, example.org, and seven more example sites. Then, extract the content from each.',
		llm=llm,
		controller=controller,
	)
	start_time = time.time()
	history = await agent.run(max_steps=50)
	end_time = time.time()

	total_time = end_time - start_time

	print(f'Total time: {total_time:.2f} seconds')
	# Check for errors
	errors = [h.result.error for h in history if h.result and h.result.error]
	assert len(errors) == 0, 'Errors occurred during the test'
	# check if 10 tabs were opened
	assert len(controller.browser.current_state.tabs) >= 10, '10 tabs were not opened'
