import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import DOMElementNode, DOMTextNode
from browser_use.filesystem.file_system import FileSystem


@pytest.fixture(
	params=[
		ChatOpenAI(model='gpt-4o-mini'),
		AzureChatOpenAI(model='gpt-4o', api_version='2024-02-15-preview'),
		ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=100, temperature=0.0, stop=None),
	],
	ids=['gpt-4o-mini', 'gpt-4o', 'claude-3-5-sonnet'],
)
def message_manager(request: pytest.FixtureRequest):
	task = 'Test task'
	action_descriptions = 'Test actions'

	import os
	import tempfile
	import uuid

	base_tmp = tempfile.gettempdir()  # e.g., /tmp on Unix
	file_system_path = os.path.join(base_tmp, str(uuid.uuid4()))
	return MessageManager(
		task=task,
		system_message=SystemMessage(content=action_descriptions),
		settings=MessageManagerSettings(
			max_input_tokens=1000,
			estimated_characters_per_token=3,
			image_tokens=800,
		),
		file_system=FileSystem(file_system_path),
	)


def test_initial_messages(message_manager: MessageManager):
	"""Test that message manager initializes with system and task messages"""
	messages = message_manager.get_messages()
	assert len(messages) == 2
	assert isinstance(messages[0], SystemMessage)
	assert isinstance(messages[1], HumanMessage)
	assert 'Test task' in messages[1].content


def test_add_state_message(message_manager: MessageManager):
	"""Test adding browser state message"""
	state = BrowserStateSummary(
		url='https://test.com',
		title='Test Page',
		element_tree=DOMElementNode(
			tag_name='div',
			attributes={},
			children=[],
			is_visible=True,
			parent=None,
			xpath='//div',
		),
		selector_map={},
		tabs=[TabInfo(page_id=1, url='https://test.com', title='Test Page')],
	)
	message_manager.add_state_message(browser_state_summary=state)

	messages = message_manager.get_messages()
	assert len(messages) == 3
	assert isinstance(messages[2], HumanMessage)
	assert 'https://test.com' in messages[2].content


def test_add_state_with_memory_result(message_manager: MessageManager):
	"""Test adding state with result that should be included in memory"""
	state = BrowserStateSummary(
		url='https://test.com',
		title='Test Page',
		element_tree=DOMElementNode(
			tag_name='div',
			attributes={},
			children=[],
			is_visible=True,
			parent=None,
			xpath='//div',
		),
		selector_map={},
		tabs=[TabInfo(page_id=1, url='https://test.com', title='Test Page')],
	)
	result = ActionResult(extracted_content='Important content', include_in_memory=True)

	message_manager.add_state_message(browser_state_summary=state, result=[result])
	messages = message_manager.get_messages()

	# Should have system, task, extracted content, and state messages
	assert len(messages) == 4
	assert 'Important content' in messages[2].content
	assert isinstance(messages[2], HumanMessage)
	assert isinstance(messages[3], HumanMessage)
	assert 'Important content' not in messages[3].content


def test_add_state_with_non_memory_result(message_manager: MessageManager):
	"""Test adding state with result that should not be included in memory"""
	state = BrowserStateSummary(
		url='https://test.com',
		title='Test Page',
		element_tree=DOMElementNode(
			tag_name='div',
			attributes={},
			children=[],
			is_visible=True,
			parent=None,
			xpath='//div',
		),
		selector_map={},
		tabs=[TabInfo(page_id=1, url='https://test.com', title='Test Page')],
	)
	result = ActionResult(extracted_content='Temporary content', include_in_memory=False)

	message_manager.add_state_message(browser_state_summary=state, result=[result])
	messages = message_manager.get_messages()

	# Should have system, task, and combined state+result message
	assert len(messages) == 3
	assert 'Temporary content' in messages[2].content
	assert isinstance(messages[2], HumanMessage)


@pytest.mark.skip('not sure how to fix this')
@pytest.mark.parametrize('max_tokens', [100000, 10000, 5000])
def test_token_overflow_handling_with_real_flow(message_manager: MessageManager, max_tokens):
	"""Test handling of token overflow in a realistic message flow"""
	# Set more realistic token limit
	message_manager.settings.max_input_tokens = max_tokens

	# Create a long sequence of interactions
	for i in range(200):  # Simulate 40 steps of interaction
		# Create state with varying content length
		state = BrowserStateSummary(
			url=f'https://test{i}.com',
			title=f'Test Page {i}',
			element_tree=DOMElementNode(
				tag_name='div',
				attributes={},
				children=[
					DOMTextNode(
						text=f'Content {j} ' * (10 + i),  # Increasing content length
						is_visible=True,
						parent=None,
					)
					for j in range(5)  # Multiple DOM items
				],
				is_visible=True,
				parent=None,
				xpath='//div',
			),
			selector_map={j: f'//div[{j}]' for j in range(5)},
			tabs=[TabInfo(page_id=1, url=f'https://test{i}.com', title=f'Test Page {i}')],
		)

		# Alternate between different types of results
		result = None
		if i % 2 == 0:  # Every other iteration
			result = ActionResult(
				extracted_content=f'Important content from step {i}' * 5,
				include_in_memory=i % 4 == 0,  # Include in memory every 4th message
			)

		# Add state message
		if result:
			message_manager.add_state_message(browser_state_summary=state, result=[result])
		else:
			message_manager.add_state_message(browser_state_summary=state)

		try:
			messages = message_manager.get_messages()
		except ValueError as e:
			if 'Max token limit reached - history is too long' in str(e):
				return  # If error occurs, end the test
			else:
				raise e

		assert message_manager.state.history.current_tokens <= message_manager.settings.max_input_tokens + 100

		last_msg = messages[-1]
		assert isinstance(last_msg, HumanMessage)

		if i % 4 == 0:
			assert isinstance(message_manager.state.history.messages[-2].message, HumanMessage)
		if i % 2 == 0 and not i % 4 == 0:
			if isinstance(last_msg.content, list):
				assert 'Current url: https://test' in last_msg.content[0]['text']
			else:
				assert 'Current url: https://test' in last_msg.content

		# Add model output every time
		from browser_use.agent.views import AgentBrain, AgentOutput
		from browser_use.controller.registry.views import ActionModel

		output = AgentOutput(
			current_state=AgentBrain(
				evaluation_previous_goal=f'Success in step {i}',
				memory=f'Memory from step {i}',
				next_goal=f'Goal for step {i + 1}',
			),
			action=[ActionModel()],
		)
		message_manager._remove_last_state_message()
		message_manager.add_model_output(output)

		# Get messages and verify after each addition
		messages = [m.message for m in message_manager.state.history.messages]

		# Verify token limit is respected

		# Verify essential messages are preserved
		assert isinstance(messages[0], SystemMessage)  # System prompt always first
		assert isinstance(messages[1], HumanMessage)  # Task always second
		assert 'Test task' in messages[1].content

		# Verify structure of latest messages
		assert isinstance(messages[-1], AIMessage)  # Last message should be model output
		assert f'step {i}' in messages[-1].content  # Should contain current step info

		# Log token usage for debugging
		token_usage = message_manager.state.history.current_tokens
		token_limit = message_manager.settings.max_input_tokens
		# print(f'Step {i}: Using {token_usage}/{token_limit} tokens')

		# go through all messages and verify that the token count and total tokens is correct
		total_tokens = 0
		real_tokens = []
		stored_tokens = []
		for msg in message_manager.state.history.messages:
			total_tokens += msg.metadata.tokens
			stored_tokens.append(msg.metadata.tokens)
			real_tokens.append(message_manager._count_tokens(msg.message))
		assert total_tokens == sum(real_tokens)
		assert stored_tokens == real_tokens
		assert message_manager.state.history.current_tokens == total_tokens


# pytest -s browser_use/agent/message_manager/tests.py
