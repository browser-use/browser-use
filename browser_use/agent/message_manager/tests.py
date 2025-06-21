import pytest

from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.views import ActionResult
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import DOMElementNode
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


@pytest.fixture(
	params=[
		ChatOpenAI(model='gpt-4o-mini'),
		# AzureChatOpenAI(model='gpt-4o', api_version='2024-02-15-preview'),
		ChatAnthropic(model='claude-3-5-sonnet-20240620', temperature=0.0),
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
	assert isinstance(messages[1], UserMessage)
	assert 'Test task' in messages[1].text


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
	assert isinstance(messages[2], UserMessage)
	assert 'https://test.com' in messages[2].text


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
	assert 'Important content' in messages[2].text
	assert isinstance(messages[2], UserMessage)
	assert isinstance(messages[3], UserMessage)
	assert 'Important content' not in messages[3].text


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
	assert 'Temporary content' in messages[2].text
	assert isinstance(messages[2], UserMessage)


# pytest -s browser_use/agent/message_manager/tests.py
