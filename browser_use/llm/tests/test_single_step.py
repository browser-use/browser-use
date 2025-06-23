import logging
import tempfile

import pytest

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.service import Agent
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import DOMElementNode, SelectorMap
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.base import BaseChatModel
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.openai.chat import ChatOpenAI

# Set logging level to INFO for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def create_mock_state_message(temp_dir: str):
	"""Create a mock state message with a single clickable element."""

	# Create a mock DOM element with a single clickable button
	mock_button = DOMElementNode(
		tag_name='button',
		xpath="//button[@id='test-button']",
		attributes={'id': 'test-button'},
		children=[],
		is_visible=True,
		is_interactive=True,
		is_top_element=True,
		is_in_viewport=True,
		shadow_root=False,
		highlight_index=1,  # This makes it clickable with index 1
		viewport_coordinates=None,
		page_coordinates=None,
		viewport_info=None,
		parent=None,
	)

	# Create selector map
	selector_map: SelectorMap = {1: mock_button}

	# Create mock tab info with proper integer page_id
	mock_tab = TabInfo(
		page_id=1,  # Changed to integer
		url='https://example.com',
		title='Test Page',
	)

	# Create mock browser state with required selector_map
	mock_browser_state = BrowserStateSummary(
		element_tree=mock_button,  # Using the actual DOM element
		selector_map=selector_map,  # Added missing parameter
		url='https://example.com',
		title='Test Page',
		tabs=[mock_tab],
		screenshot='',  # Empty screenshot
		pixels_above=0,
		pixels_below=0,
	)

	# Create file system using the provided temp directory
	mock_file_system = FileSystem(temp_dir)

	# Create the agent message prompt
	agent_prompt = AgentMessagePrompt(
		browser_state_summary=mock_browser_state,
		file_system=mock_file_system,  # Now using actual FileSystem instance
		agent_history_description='',  # Empty history
		read_state_description='',  # Empty read state
		task='Click the button on the page',
		include_attributes=['id'],
		step_info=None,
		page_filtered_actions=None,
		max_clickable_elements_length=40000,
		sensitive_data=None,
	)

	# Override the clickable_elements_to_string method to return our simple element
	mock_button.clickable_elements_to_string = lambda include_attributes=None: '[1]<button id="test-button">Click Me</button>'

	# Get the formatted message
	message = agent_prompt.get_user_message(use_vision=False)

	return message


# Pytest parameterized version
@pytest.mark.parametrize(
	'llm_class,model_name',
	[
		(ChatGroq, 'meta-llama/llama-4-maverick-17b-128e-instruct'),
		(ChatGoogle, 'gemini-2.0-flash-exp'),
		(ChatOpenAI, 'gpt-4o-mini'),
		(ChatAnthropic, 'claude-3-5-sonnet-latest'),
		(ChatAzureOpenAI, 'gpt-4o-mini'),
	],
)
async def test_single_step_parametrized(llm_class, model_name):
	"""Test single step with different LLM providers using pytest parametrize."""
	llm = llm_class(model=model_name)

	agent = Agent(task='Click the button on the page', llm=llm)

	# Create temporary directory that will stay alive during the test
	with tempfile.TemporaryDirectory() as temp_dir:
		# Create mock state message
		mock_message = create_mock_state_message(temp_dir)

		agent.message_manager._add_message_with_type(mock_message)

		messages = agent.message_manager.get_messages()

		# Test with simple question
		response = await llm.ainvoke(messages, agent.AgentOutput)

		# Basic assertions to ensure response is valid
		assert response.completion is not None
		assert response.usage is not None
		assert response.usage.total_tokens > 0


async def test_single_step():
	"""Original test function that tests all models in a loop."""
	# Create a list of models to test
	models: list[BaseChatModel] = [
		ChatGroq(model='meta-llama/llama-4-maverick-17b-128e-instruct'),
		ChatGoogle(model='gemini-2.0-flash-exp'),
		ChatOpenAI(model='gpt-4.1'),
		ChatAnthropic(model='claude-3-5-sonnet-latest'),  # Using haiku for cost efficiency
		ChatAzureOpenAI(model='gpt-4o-mini'),
	]

	for llm in models:
		print(f'\n{"=" * 60}')
		print(f'Testing with model: {llm.provider} - {llm.model}')
		print(f'{"=" * 60}\n')

		agent = Agent(task='Click the button on the page', llm=llm)

		# Create temporary directory that will stay alive during the test
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create mock state message
			mock_message = create_mock_state_message(temp_dir)

			# Print the mock message content to see what it looks like
			print('Mock state message:')
			print(mock_message.content)
			print('\n' + '=' * 50 + '\n')

			agent.message_manager._add_message_with_type(mock_message)

			messages = agent.message_manager.get_messages()

			# Test with simple question
			try:
				response = await llm.ainvoke(messages, agent.AgentOutput)
				logger.info(f'Response from {llm.provider}: {response.completion}')
				logger.info(f'Actions: {str(response.completion.action)}')

			except Exception as e:
				logger.error(f'Error with {llm.provider}: {type(e).__name__}: {str(e)}')

		print(f'\n{"=" * 60}\n')


if __name__ == '__main__':
	import asyncio

	asyncio.run(test_single_step())
