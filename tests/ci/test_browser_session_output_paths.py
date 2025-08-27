"""Test all recording and save functionality for Agent and BrowserSession."""

from pathlib import Path

import pytest

from browser_use import Agent, AgentHistoryList
from browser_use.browser import BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


@pytest.fixture
def test_dir(tmp_path):
	"""Create a test directory that gets cleaned up after each test."""
	test_path = tmp_path / 'test_recordings'
	test_path.mkdir(exist_ok=True)
	yield test_path


@pytest.fixture
async def httpserver_url(httpserver):
	"""Simple test page."""
	# Use expect_ordered_request with multiple handlers to handle repeated requests
	for _ in range(10):  # Allow up to 10 requests to the same URL
		httpserver.expect_ordered_request('/').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Test Page</title>
			</head>
			<body>
				<h1>Test Recording Page</h1>
				<input type="text" id="search" placeholder="Search here" />
				<button type="button" id="submit">Submit</button>
			</body>
			</html>
			""",
			content_type='text/html',
		)
	return httpserver.url_for('/')


@pytest.fixture
def llm():
	"""Create mocked LLM instance for tests."""
	return create_mock_llm()


@pytest.fixture
def interactive_llm(httpserver_url):
	"""Create mocked LLM that navigates to page and interacts with elements."""
	actions = [
		# First action: Navigate to the page
		f"""
		{{
			"thinking": "null",
			"evaluation_previous_goal": "Starting the task",
			"memory": "Need to navigate to the test page",
			"next_goal": "Navigate to the URL",
			"action": [
				{{
					"go_to_url": {{
						"url": "{httpserver_url}",
						"new_tab": false
					}}
				}}
			]
		}}
		""",
		# Second action: Click in the search box
		"""
		{
			"thinking": "null",
			"evaluation_previous_goal": "Successfully navigated to the page",
			"memory": "Page loaded, can see search box and submit button",
			"next_goal": "Click on the search box to focus it",
			"action": [
				{
					"click_element_by_index": {
						"index": 0
					}
				}
			]
		}
		""",
		# Third action: Type text in the search box
		"""
		{
			"thinking": "null",
			"evaluation_previous_goal": "Clicked on search box",
			"memory": "Search box is focused and ready for input",
			"next_goal": "Type 'test' in the search box",
			"action": [
				{
					"input_text": {
						"index": 0,
						"text": "test"
					}
				}
			]
		}
		""",
		# Fourth action: Click submit button
		"""
		{
			"thinking": "null",
			"evaluation_previous_goal": "Typed 'test' in search box",
			"memory": "Text 'test' has been entered successfully",
			"next_goal": "Click the submit button to complete the task",
			"action": [
				{
					"click_element_by_index": {
						"index": 1
					}
				}
			]
		}
		""",
		# Fifth action: Done - task completed
		"""
		{
			"thinking": "null",
			"evaluation_previous_goal": "Clicked the submit button",
			"memory": "Successfully navigated to the page, typed 'test' in the search box, and clicked submit",
			"next_goal": "Task completed",
			"action": [
				{
					"done": {
						"text": "Task completed - typed 'test' in search box and clicked submit",
						"success": true
					}
				}
			]
		}
		""",
	]
	return create_mock_llm(actions)


class TestAgentRecordings:
	"""Test Agent save_conversation_path and generate_gif parameters."""

	@pytest.mark.parametrize('path_type', ['with_slash', 'without_slash', 'deep_directory'])
	async def test_save_conversation_path(self, test_dir, httpserver_url, llm, path_type):
		"""Test saving conversation with different path types."""
		if path_type == 'with_slash':
			conversation_path = test_dir / 'logs' / 'conversation'
		elif path_type == 'without_slash':
			conversation_path = test_dir / 'logs'
		else:  # deep_directory
			conversation_path = test_dir / 'logs' / 'deep' / 'directory' / 'conversation'

		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True, user_data_dir=None))
		await browser_session.start()
		try:
			agent = Agent(
				task=f'go to {httpserver_url} and type "test" in the search box',
				llm=llm,
				browser_session=browser_session,
				save_conversation_path=str(conversation_path),
			)
			history: AgentHistoryList = await agent.run(max_steps=2)

			result = history.final_result()
			assert result is not None

			# Check that the conversation directory and files were created
			assert conversation_path.exists(), f'{path_type}: conversation directory was not created'
			# Files are now always created as conversation_<agent_id>_<step>.txt inside the directory
			conversation_files = list(conversation_path.glob('conversation_*.txt'))
			assert len(conversation_files) > 0, f'{path_type}: conversation file was not created in {conversation_path}'
		finally:
			await browser_session.kill()

	@pytest.mark.skip(reason='TODO: fix')
	@pytest.mark.parametrize('generate_gif', [False, True, 'custom_path'])
	async def test_generate_gif(self, test_dir, httpserver_url, llm, generate_gif):
		"""Test GIF generation with different settings."""
		# Clean up any existing GIFs first
		for gif in Path.cwd().glob('agent_*.gif'):
			gif.unlink()

		gif_param = generate_gif
		expected_gif_path = None

		if generate_gif == 'custom_path':
			expected_gif_path = test_dir / 'custom_agent.gif'
			gif_param = str(expected_gif_path)

		browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True, user_data_dir=None))
		await browser_session.start()
		try:
			agent = Agent(
				task=f'go to {httpserver_url}',
				llm=llm,
				browser_session=browser_session,
				generate_gif=gif_param,
			)
			history: AgentHistoryList = await agent.run(max_steps=2)

			result = history.final_result()
			assert result is not None

			# Check GIF creation
			if generate_gif is False:
				gif_files = list(Path.cwd().glob('*.gif'))
				assert len(gif_files) == 0, 'GIF file was created when generate_gif=False'
			elif generate_gif is True:
				# With mock LLM that doesn't navigate, all screenshots will be about:blank placeholders
				# So no GIF will be created (this is expected behavior)
				gif_files = list(Path.cwd().glob('agent_history.gif'))
				assert len(gif_files) == 0, 'GIF should not be created when all screenshots are placeholders'
			else:  # custom_path
				assert expected_gif_path is not None, 'expected_gif_path should be set for custom_path'
				# With mock LLM that doesn't navigate, no GIF will be created
				assert not expected_gif_path.exists(), 'GIF should not be created when all screenshots are placeholders'
		finally:
			await browser_session.kill()
