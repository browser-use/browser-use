"""Test all recording and save functionality for Agent and BrowserSession."""

import asyncio
import json
import shutil
import zipfile
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
	httpserver.expect_request('/').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>Test Page</title></head>
		<body>
			<h1>Test Recording Page</h1>
			<input type="text" id="search" placeholder="Search here">
			<button id="submit">Submit</button>
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
						"url": "{httpserver_url}"
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
			await browser_session.stop()

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
				gif_files = list(Path.cwd().glob('agent_*.gif'))
				assert len(gif_files) > 0, 'No GIF file was created when generate_gif=True'
				# Clean up
				for gif in gif_files:
					gif.unlink()
			else:  # custom_path
				assert expected_gif_path is not None, 'expected_gif_path should be set for custom_path'
				assert expected_gif_path.exists(), f'GIF was not created at {expected_gif_path}'
		finally:
			await browser_session.stop()


class TestBrowserProfileRecordings:
	"""Test BrowserProfile recording parameters with aliases."""

	@pytest.mark.parametrize(
		'context_type,alias',
		[
			('incognito', 'save_recording_path'),
			('incognito', 'record_video_dir'),
			('persistent', 'save_recording_path'),
			('persistent', 'record_video_dir'),
		],
	)
	async def test_video_recording(self, test_dir, httpserver_url, context_type, alias):
		"""Test video recording with different contexts and aliases."""
		video_dir = test_dir / f'videos_{context_type}_{alias}'
		user_data_dir = None if context_type == 'incognito' else str(test_dir / 'user_data')

		# Create profile with dynamic alias
		profile_kwargs = {'headless': True, 'disable_security': True, 'user_data_dir': user_data_dir, alias: str(video_dir)}
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(**profile_kwargs)  # type: ignore
		)
		await browser_session.start()
		try:
			await browser_session.navigate(httpserver_url)
			await asyncio.sleep(0.5)
		finally:
			await browser_session.stop()

		# Add delay for video processing
		await asyncio.sleep(1)

		# Check if videos were created (may not work in all CI environments)
		if video_dir.exists():
			video_files = list(video_dir.glob('*.webm'))
			if video_files:
				for video_file in video_files:
					file_size = video_file.stat().st_size
					assert file_size > 1000, f'Video file {video_file.name} is too small'
		else:
			# Video recording might not work in headless CI environments - skip gracefully
			pytest.skip('Video recording not supported in this environment')

	@pytest.mark.parametrize(
		'context_type,alias',
		[
			('incognito', 'save_har_path'),
			('incognito', 'record_har_path'),
			('persistent', 'save_har_path'),
			('persistent', 'record_har_path'),
		],
	)
	async def test_har_recording(self, test_dir, httpserver_url, context_type, alias):
		"""Test HAR recording with different contexts and aliases."""
		har_path = test_dir / f'network_{context_type}_{alias}.har'
		user_data_dir = None if context_type == 'incognito' else str(test_dir / f'user_data_har_{alias}')

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				disable_security=True,
				user_data_dir=user_data_dir,
				**{alias: str(har_path)},  # type: ignore
			)
		)
		await browser_session.start()
		try:
			await browser_session.navigate(httpserver_url)
			await asyncio.sleep(0.5)
		finally:
			await browser_session.stop()

		# HAR files should be created
		assert har_path.exists(), f'HAR file was not created at {har_path}'

		# Check HAR file content
		har_content = json.loads(har_path.read_text())
		assert 'log' in har_content, "HAR file missing 'log' key"
		assert 'entries' in har_content['log'], 'HAR file missing entries'
		assert len(har_content['log']['entries']) > 0, 'HAR file has no network entries'

	@pytest.mark.parametrize(
		'context_type,alias',
		[
			('incognito', 'trace_path'),
			('incognito', 'traces_dir'),
			('persistent', 'trace_path'),
			('persistent', 'traces_dir'),
		],
	)
	async def test_trace_recording(self, test_dir, httpserver_url, context_type, alias, interactive_llm):
		"""Test trace recording with different contexts and aliases."""
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				disable_security=True,
				user_data_dir=None if context_type == 'incognito' else str(test_dir / f'user_data_trace_{alias}'),
			)
		)

		# Use browser session ID to create unique trace directory
		trace_dir = test_dir / f'trace_{context_type}_{alias}_{browser_session.id}'

		# Clean up any existing directory at this path
		if trace_dir.exists():
			shutil.rmtree(trace_dir)

		# Set the trace directory - trace_path is an alias for traces_dir
		if alias == 'trace_path':
			browser_session.browser_profile.traces_dir = str(trace_dir)
		else:
			setattr(browser_session.browser_profile, alias, str(trace_dir))  # type: ignore

		await browser_session.start()
		try:
			# Use Agent to interact with page for better trace content
			agent = Agent(
				task=f'go to {httpserver_url} and type "test" in the search box',
				llm=interactive_llm,
				browser_session=browser_session,
			)
			await agent.run(max_steps=5)
		finally:
			await browser_session.stop()

		# Check trace file - should be created automatically in the directory
		assert trace_dir.exists(), f'Trace directory was not created at {trace_dir}'
		trace_files = list(trace_dir.glob('*.zip'))
		assert len(trace_files) > 0, f'No trace files were created in {trace_dir}'

		trace_file = trace_files[0]
		assert zipfile.is_zipfile(trace_file), 'Trace file is not a valid ZIP'

		with zipfile.ZipFile(trace_file, 'r') as zip_file:
			files = zip_file.namelist()
			assert len(files) > 0, 'Trace ZIP file is empty'
			assert any('trace' in f.lower() for f in files), 'Trace ZIP missing trace data'


class TestCombinedRecordings:
	"""Test using multiple recording parameters together."""

	async def test_all_recording_parameters(self, test_dir, httpserver_url, interactive_llm):
		"""Test using all recording parameters together."""
		conversation_path = test_dir / 'conversation'
		gif_path = test_dir / 'agent.gif'
		video_dir = test_dir / 'videos'
		har_path = test_dir / 'network.har'
		trace_dir = test_dir / 'traces'

		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				disable_security=True,
				user_data_dir=None,
				record_video_dir=str(video_dir),
				record_har_path=str(har_path),
				traces_dir=str(trace_dir),
			)
		)

		await browser_session.start()

		try:
			agent = Agent(
				task=f'go to {httpserver_url} and type "test" in the search box',
				llm=interactive_llm,
				browser_session=browser_session,
				save_conversation_path=str(conversation_path),
				generate_gif=str(gif_path),
			)
			history: AgentHistoryList = await agent.run(max_steps=5)

			result = history.final_result()
			assert result is not None

			# Check conversation files in directory
			conversation_files = list(conversation_path.glob('conversation_*.txt'))
			assert len(conversation_files) > 0, 'Conversation file was not created'

			# Check GIF
			assert gif_path.exists(), 'GIF was not created'

			# Check video directory
			assert video_dir.exists(), 'Video directory was not created'
		finally:
			await browser_session.stop()

		# Check files created after browser close
		video_files = list(video_dir.glob('*.webm'))
		assert len(video_files) > 0, 'No video files were created'

		assert har_path.exists(), 'HAR file was not created'

		# Verify HAR file
		har_content = json.loads(har_path.read_text())
		assert 'log' in har_content and 'entries' in har_content['log'], 'Invalid HAR structure'

		assert trace_dir.exists(), 'Trace directory was not created'
		trace_files = list(trace_dir.glob('*.zip'))
		assert len(trace_files) > 0, 'No trace files were created'

		# Verify trace file
		trace_file = trace_files[0]
		assert zipfile.is_zipfile(trace_file), 'Trace file is not a valid ZIP'
