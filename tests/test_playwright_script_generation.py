"""
Tests for Playwright script generation functionality.

This module tests the extraction of Playwright actions from agent history
and the generation of Playwright scripts from those actions.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from browser_use.agent.service import Agent


class TestPlaywrightActionExtraction:
	"""Tests for extracting Playwright actions from agent history."""

	@pytest.fixture
	def mock_agent_with_history(self):
		"""Create a mock agent with predefined history for testing."""
		agent = MagicMock(spec=Agent)
		agent.state = MagicMock()
		agent.state.history = MagicMock()

		# Create mock history item with actions and results
		history_item = MagicMock()
		history_item.model_output = MagicMock()

		# Define test actions
		action1 = MagicMock()
		action1.model_dump.return_value = {'go_to_url': {'url': 'https://example.com'}}

		action2 = MagicMock()
		action2.model_dump.return_value = {'click_element': {'selector': '#button'}}

		history_item.model_output.action = [action1, action2]

		# Define test results
		result1 = MagicMock()
		result1.model_dump.return_value = {'status': 'success'}

		result2 = MagicMock()
		result2.model_dump.return_value = {'status': 'success', 'element_found': True}

		history_item.result = [result1, result2]

		# Add history item to agent history
		agent.state.history.history = [history_item]

		return agent

	def test_extract_actions_basic(self, mock_agent_with_history):
		"""Test basic extraction of actions from agent history."""
		# Call the method directly on the Agent class with our mock instance
		with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
			actions = Agent.extract_playwright_actions(mock_agent_with_history)

		# Verify results
		assert len(actions) == 2
		assert actions[0]['action_name'] == 'go_to_url'
		assert actions[0]['params']['url'] == 'https://example.com'
		assert actions[0]['result']['status'] == 'success'
		assert actions[1]['action_name'] == 'click_element'
		assert actions[1]['params']['selector'] == '#button'
		assert actions[1]['result']['status'] == 'success'
		assert actions[1]['result']['element_found']

	def test_extract_actions_empty_history(self):
		"""Test extraction with empty history."""
		# Create agent with empty history
		agent = MagicMock(spec=Agent)
		agent.state = MagicMock()
		agent.state.history = MagicMock()
		agent.state.history.history = []

		# Call the method
		with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
			actions = Agent.extract_playwright_actions(agent)

		# Verify empty list is returned
		assert isinstance(actions, list)
		assert len(actions) == 0

	def test_extract_actions_debug_mode(self, mock_agent_with_history, tmp_path):
		"""Test JSON saving when debug mode is enabled."""
		# Set up temp file path
		output_path = tmp_path / 'test_actions.json'

		# Mock environment variable for debug mode
		with patch.dict(os.environ, {'BROWSER_USE_LOGGING_LEVEL': 'debug'}):
			# Call the method with output path
			with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
				actions = Agent.extract_playwright_actions(mock_agent_with_history, output_path=output_path)

		# Verify file was created
		assert output_path.exists()

		# Verify file contents
		with open(output_path, encoding='utf-8') as f:
			saved_actions = json.load(f)

		assert len(saved_actions) == 2
		assert saved_actions[0]['action_name'] == 'go_to_url'
		assert saved_actions[1]['action_name'] == 'click_element'

	def test_extract_actions_no_debug_mode(self, mock_agent_with_history, tmp_path):
		"""Test that JSON is not saved when debug mode is disabled."""
		# Set up temp file path
		output_path = tmp_path / 'test_actions.json'

		# Mock environment variable to disable debug mode
		with patch.dict(os.environ, {'BROWSER_USE_LOGGING_LEVEL': 'info'}):
			# Call the method with output path
			with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
				actions = Agent.extract_playwright_actions(mock_agent_with_history, output_path=output_path)

		# Verify file was not created
		assert not output_path.exists()

	def test_extract_actions_with_initial_actions(self):
		"""Test extraction of initial actions."""
		# Create a mock agent with initial actions but empty history
		agent = MagicMock(spec=Agent)
		agent.state = MagicMock()
		agent.state.history = MagicMock()
		agent.state.history.history = []

		# Create mock initial actions
		initial_action1 = MagicMock()
		initial_action1.model_dump.return_value = {'go_to_url': {'url': 'https://initial-example.com'}}

		initial_action2 = MagicMock()
		initial_action2.model_dump.return_value = {'wait_for_load': {'timeout': 5000}}

		# Set initial actions on the agent
		agent.initial_actions = [initial_action1, initial_action2]

		# Call the method
		with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
			actions = Agent.extract_playwright_actions(agent)

		# Verify results
		assert len(actions) == 2
		assert actions[0]['action_name'] == 'go_to_url'
		assert actions[0]['params']['url'] == 'https://initial-example.com'
		assert actions[0]['result'] is None  # Initial actions don't have results
		assert actions[1]['action_name'] == 'wait_for_load'
		assert actions[1]['params']['timeout'] == 5000

	def test_extract_actions_exclude_initial_actions(self):
		"""Test extraction with initial actions explicitly excluded."""
		# Create a mock agent with initial actions but empty history
		agent = MagicMock(spec=Agent)
		agent.state = MagicMock()
		agent.state.history = MagicMock()
		agent.state.history.history = []

		# Create mock initial actions
		initial_action = MagicMock()
		initial_action.model_dump.return_value = {'go_to_url': {'url': 'https://initial-example.com'}}

		# Set initial actions on the agent
		agent.initial_actions = [initial_action]

		# Call the method with include_initial_actions=False
		with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
			actions = Agent.extract_playwright_actions(agent, include_initial_actions=False)

		# Verify no actions were extracted
		assert len(actions) == 0

	def test_extract_actions_combined(self, mock_agent_with_history):
		"""Test extraction of both initial actions and history actions."""
		# Add initial actions to the mock agent
		initial_action = MagicMock()
		initial_action.model_dump.return_value = {'go_to_url': {'url': 'https://initial-site.com'}}
		mock_agent_with_history.initial_actions = [initial_action]

		# Call the method
		with patch.object(Agent, 'extract_playwright_actions', Agent.extract_playwright_actions):
			actions = Agent.extract_playwright_actions(mock_agent_with_history)

		# Verify results
		assert len(actions) == 3  # 1 initial action + 2 history actions

		# Check initial action
		assert actions[0]['action_name'] == 'go_to_url'
		assert actions[0]['params']['url'] == 'https://initial-site.com'
		assert actions[0]['result'] is None

		# Check history actions
		assert actions[1]['action_name'] == 'go_to_url'
		assert actions[1]['params']['url'] == 'https://example.com'
		assert actions[2]['action_name'] == 'click_element'
		assert actions[2]['params']['selector'] == '#button'


class TestPlaywrightScriptGeneration:
	"""Tests for generating Playwright scripts from extracted actions."""

	@pytest.fixture
	def mock_llm(self):
		"""Create a mock LLM that returns a predefined script."""
		llm = AsyncMock()

		# Mock the response content
		response = MagicMock()
		response.content = """```python
from playwright.sync_api import expect

async def run(playwright):
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    
    # Navigate to example.com
    await page.goto('https://example.com')
    await expect(page).to_have_url('https://example.com')
    
    # Click the button
    await page.click('#button')
    await expect(page.locator('#result')).to_be_visible()
```"""

		# Set up the mock to return this response
		llm.ainvoke = AsyncMock(return_value=response)
		return llm

	@pytest.fixture
	def mock_agent(self, mock_llm):
		"""Create a mock agent with the mock LLM."""
		agent = MagicMock(spec=Agent)
		agent.llm = mock_llm
		agent.task = 'Test task'
		return agent

	@pytest.fixture
	def test_actions(self):
		"""Create test actions for script generation."""
		return [
			{'action_name': 'go_to_url', 'params': {'url': 'https://example.com'}, 'result': {'status': 'success'}},
			{'action_name': 'click_element', 'params': {'selector': '#button'}, 'result': {'status': 'success'}},
		]

	@pytest.mark.asyncio
	async def test_script_generation_basic(self, mock_agent, test_actions):
		"""Test basic script generation with mocked LLM."""
		# Call the method with patch
		with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
			script = await Agent.generate_playwright_script(mock_agent, actions=test_actions, headless=False)

		# Verify results
		assert 'from playwright.sync_api import expect' in script
		assert "await page.goto('https://example.com')" in script
		assert "await expect(page).to_have_url('https://example.com')" in script
		assert "await page.click('#button')" in script
		assert "await expect(page.locator('#result')).to_be_visible()" in script

	@pytest.mark.asyncio
	async def test_script_generation_empty_actions(self, mock_agent):
		"""Test script generation with empty actions list."""
		# Call the method with empty actions
		with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
			script = await Agent.generate_playwright_script(mock_agent, actions=[], headless=False)

		# Verify empty string is returned
		assert script == ''

	@pytest.mark.asyncio
	async def test_llm_prompt_construction(self, mock_agent, test_actions):
		"""Test that the LLM is called with the correct prompt."""
		# Call the method
		with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
			await Agent.generate_playwright_script(mock_agent, actions=test_actions, headless=True)

		# Verify LLM was called with correct messages
		mock_agent.llm.ainvoke.assert_called_once()
		call_args = mock_agent.llm.ainvoke.call_args[0][0]

		# Check system message
		assert isinstance(call_args[0], SystemMessage)
		assert 'expert Playwright automation developer' in call_args[0].content

		# Check human message
		assert isinstance(call_args[1], HumanMessage)
		assert 'Convert these actions into a complete, runnable Playwright Python script' in call_args[1].content
		assert 'headless=True' in call_args[1].content
		assert 'expect assertions' in call_args[1].content

		# Check that actions are included in the prompt
		assert 'go_to_url' in call_args[1].content
		assert 'click_element' in call_args[1].content
		assert 'https://example.com' in call_args[1].content

	@pytest.mark.asyncio
	async def test_script_cleanup(self, mock_agent, test_actions):
		"""Test that markdown code blocks are properly removed from the script."""
		# Modify the mock LLM to return different markdown formats
		mock_agent.llm.ainvoke.return_value.content = """```python
def test():
    print("Hello")
```"""

		# Call the method
		with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
			script1 = await Agent.generate_playwright_script(mock_agent, actions=test_actions)

		# Verify markdown was removed
		assert script1 == 'def test():\n    print("Hello")'

		# Test with different markdown format
		mock_agent.llm.ainvoke.return_value.content = """```
def test():
    print("Hello")
```"""

		# Call the method again
		with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
			script2 = await Agent.generate_playwright_script(mock_agent, actions=test_actions)

		# Verify markdown was removed
		assert script2 == 'def test():\n    print("Hello")'

	@pytest.mark.asyncio
	async def test_output_path_generation(self, mock_agent, test_actions):
		"""Test that the default output path is correctly generated from the task."""
		# Set a specific task with special characters
		mock_agent.task = 'Go to https://example.com/test/page and click button'

		# Mock time.strftime to return a fixed timestamp
		with patch('time.strftime', return_value='20250603_123456'):
			# Call the method with patch but without specifying output_path
			with patch.object(Agent, 'generate_playwright_script', Agent.generate_playwright_script):
				with patch('aiofiles.open') as mock_aiofiles_open:
					# Mock the file operations
					mock_file = AsyncMock()
					mock_file.write = AsyncMock()
					mock_aiofiles_open.return_value.__aenter__.return_value = mock_file

					await Agent.generate_playwright_script(mock_agent, actions=test_actions)

		# Verify the path was generated correctly
		# Get the path from the call to aiofiles.open
		call_args = mock_aiofiles_open.call_args[0][0]

		# Verify path components
		assert isinstance(call_args, Path)
		assert 'go_to_example.com_test_page_and_click' in str(call_args)
		assert '20250603_123456.py' in str(call_args)
		assert 'playwright_scripts' in str(call_args)
