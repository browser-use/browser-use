import os

import pytest
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, SecretStr

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
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
async def controller():
	"""Initialize the controller with self-registered actions"""
	controller = Controller()

	# Define custom actions without Pydantic models
	@controller.action('Print a message')
	def print_message(message: str):
		print(f'Message: {message}')
		return f'Printed message: {message}'

	@controller.action('Add two numbers')
	def add_numbers(a: int, b: int):
		result = a + b
		return f'The sum is {result}'

	@controller.action('Concatenate strings')
	def concatenate_strings(str1: str, str2: str):
		result = str1 + str2
		return f'Concatenated string: {result}'

	# Define Pydantic models
	class SimpleModel(BaseModel):
		name: str
		age: int

	class Address(BaseModel):
		street: str
		city: str

	class NestedModel(BaseModel):
		user: SimpleModel
		address: Address

	# Add actions with Pydantic model arguments
	@controller.action('Process simple model', param_model=SimpleModel)
	def process_simple_model(model: SimpleModel):
		return f'Processed {model.name}, age {model.age}'

	@controller.action('Process nested model', param_model=NestedModel)
	def process_nested_model(model: NestedModel):
		user_info = f'{model.user.name}, age {model.user.age}'
		address_info = f'{model.address.street}, {model.address.city}'
		return f'Processed user {user_info} at address {address_info}'

	@controller.action('Process multiple models')
	def process_multiple_models(model1: SimpleModel, model2: Address):
		return f'Processed {model1.name} living at {model2.street}, {model2.city}'

	yield controller


@pytest.fixture
def llm():
	"""Initialize language model for testing"""

	# return ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=25, stop=None)
	return AzureChatOpenAI(
		model='gpt-4o',
		api_version='2024-10-21',
		azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
		api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
	)


# @pytest.mark.skip(reason="Skipping test for now")
async def test_self_registered_actions_no_pydantic(llm, controller):
	"""Test self-registered actions with individual arguments"""
	agent = Agent(
		task="First, print the message 'Hello, World!'. Then, add 10 and 20. Next, concatenate 'foo' and 'bar'.",
		llm=llm,
		controller=controller,
	)
	history: AgentHistoryList = await agent.run(max_steps=10)
	# Check that custom actions were executed
	action_names = history.action_names()

	assert 'print_message' in action_names
	assert 'add_numbers' in action_names
	assert 'concatenate_strings' in action_names


# @pytest.mark.skip(reason="Skipping test for now")
async def test_mixed_arguments_actions(llm, controller):
	"""Test actions with mixed argument types"""

	# Define another action during the test
	# Test for async actions
	@controller.action('Calculate the area of a rectangle')
	async def calculate_area(length: float, width: float):
		area = length * width
		return f'The area is {area}'

	agent = Agent(
		task='Calculate the area of a rectangle with length 5.5 and width 3.2.',
		llm=llm,
		controller=controller,
	)
	history = await agent.run(max_steps=5)

	# Check that the action was executed
	action_names = history.action_names()

	assert 'calculate_area' in action_names
	# check result
	correct = 'The area is 17.6'
	for content in history.extracted_content():
		if correct in content:
			break
	else:
		pytest.fail(f'{correct} not found in extracted content')


async def test_pydantic_simple_model(llm, controller):
	"""Test action with a simple Pydantic model argument"""
	agent = Agent(
		task="Process a simple model with name 'Alice' and age 30.",
		llm=llm,
		controller=controller,
	)
	history = await agent.run(max_steps=5)

	# Check that the action was executed
	action_names = history.action_names()

	assert 'process_simple_model' in action_names
	correct = 'Processed Alice, age 30'
	for content in history.extracted_content():
		if correct in content:
			break
	else:
		pytest.fail(f'{correct} not found in extracted content')


async def test_pydantic_nested_model(llm, controller):
	"""Test action with a nested Pydantic model argument"""
	agent = Agent(
		task="Process a nested model with user name 'Bob', age 25, living at '123 Maple St', 'Springfield'.",
		llm=llm,
		controller=controller,
	)
	history = await agent.run(max_steps=5)

	# Check that the action was executed
	action_names = history.action_names()

	assert 'process_nested_model' in action_names
	correct = 'Processed user Bob, age 25 at address 123 Maple St, Springfield'
	for content in history.extracted_content():
		if correct in content:
			break
	else:
		pytest.fail(f'{correct} not found in extracted content')


# run this file with:
# pytest tests/test_self_registered_actions.py --capture=no
