"""Tests for screenshot action: always-available behavior and CDP capture + save to disk."""

from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools
from browser_use.tools.views import ScreenshotAction
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='function')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='function')
def file_system(tmp_path):
	return FileSystem(base_dir=tmp_path, create_default_files=False)


# ---------------------------------------------------------------------------
# 1. Screenshot is always registered regardless of use_vision mode
# ---------------------------------------------------------------------------


def test_screenshot_available_with_use_vision_false():
	"""Screenshot should be available even when use_vision=False (saves to disk)."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(task='test', llm=mock_llm, use_vision=False)

	assert 'screenshot' in agent.tools.registry.registry.actions, (
		'Screenshot should be available when use_vision=False (it saves to disk)'
	)


def test_screenshot_available_with_use_vision_true():
	"""Screenshot should be available when use_vision=True."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(task='test', llm=mock_llm, use_vision=True)

	assert 'screenshot' in agent.tools.registry.registry.actions, (
		'Screenshot should be available when use_vision=True'
	)


def test_screenshot_available_with_use_vision_auto():
	"""Screenshot should be available when use_vision='auto'."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	agent = Agent(task='test', llm=mock_llm, use_vision='auto')

	assert 'screenshot' in agent.tools.registry.registry.actions, (
		'Screenshot should be available when use_vision="auto"'
	)


def test_screenshot_available_with_custom_tools():
	"""Screenshot should be available in custom tools passed to agent."""
	mock_llm = create_mock_llm(actions=['{"action": [{"done": {"text": "test", "success": true}}]}'])

	custom_tools = Tools()
	assert 'screenshot' in custom_tools.registry.registry.actions

	agent = Agent(task='test', llm=mock_llm, tools=custom_tools, use_vision=False)

	assert 'screenshot' in agent.tools.registry.registry.actions, (
		'Screenshot should remain available in custom tools regardless of use_vision'
	)


# ---------------------------------------------------------------------------
# 2. Explicit exclusion still works
# ---------------------------------------------------------------------------


def test_tools_exclude_action_method():
	"""Test the Tools.exclude_action() method directly."""
	tools = Tools()

	assert 'screenshot' in tools.registry.registry.actions, 'Screenshot should be included by default'

	tools.exclude_action('screenshot')

	assert 'screenshot' not in tools.registry.registry.actions, 'Screenshot should be excluded after calling exclude_action()'
	assert 'screenshot' in tools.registry.exclude_actions, 'Screenshot should be in exclude_actions list'


def test_exclude_action_prevents_re_registration():
	"""Test that excluded actions cannot be re-registered."""
	tools = Tools()

	tools.exclude_action('screenshot')
	assert 'screenshot' not in tools.registry.registry.actions

	@tools.registry.action('Test screenshot action')
	async def screenshot():
		return 'test'

	assert 'screenshot' not in tools.registry.registry.actions, 'Excluded action should not be re-registered'


def test_screenshot_excluded_via_exclude_actions_param():
	"""Users can still exclude screenshot by passing it in exclude_actions."""
	tools = Tools(exclude_actions=['screenshot'])

	assert 'screenshot' not in tools.registry.registry.actions, (
		'Screenshot should be excluded when explicitly passed in exclude_actions'
	)


# ---------------------------------------------------------------------------
# 3. ScreenshotAction model
# ---------------------------------------------------------------------------


def test_screenshot_action_defaults():
	"""ScreenshotAction defaults to viewport-only (full_page=False)."""
	action = ScreenshotAction()
	assert action.full_page is False


def test_screenshot_action_full_page():
	"""ScreenshotAction supports full_page=True."""
	action = ScreenshotAction(full_page=True)
	assert action.full_page is True


# ---------------------------------------------------------------------------
# 4. Screenshot capture saves to disk and returns correct path
# ---------------------------------------------------------------------------


async def test_screenshot_saves_to_disk(browser_session: BrowserSession, file_system: FileSystem, httpserver: HTTPServer):
	"""Screenshot action should capture via CDP and save PNG to FileSystem dir."""
	httpserver.expect_request('/').respond_with_data(
		'<html><body><h1>Screenshot Test</h1></body></html>',
		content_type='text/html',
	)

	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=browser_session)

	result = await tools.registry.execute_action(
		'screenshot',
		{'full_page': False},
		browser_session=browser_session,
		file_system=file_system,
	)

	assert result.error is None, f'Screenshot action failed: {result.error}'
	assert result.extracted_content is not None
	assert 'viewport' in result.extracted_content
	assert result.metadata and result.metadata.get('include_screenshot') is True

	# Extract the path from the result text
	path_str = result.extracted_content.split('to ')[-1]
	saved_path = Path(path_str)

	assert saved_path.exists(), f'Screenshot file not found at {saved_path}'
	assert saved_path.suffix == '.png'

	file_bytes = saved_path.read_bytes()
	assert len(file_bytes) > 0, 'Screenshot file is empty'
	# PNG magic bytes
	assert file_bytes[:4] == b'\x89PNG', 'File is not a valid PNG'


async def test_screenshot_full_page(browser_session: BrowserSession, file_system: FileSystem, httpserver: HTTPServer):
	"""full_page=True should capture the entire scrollable page."""
	long_content = '<br>'.join([f'<p>Line {i}</p>' for i in range(100)])
	httpserver.expect_request('/long').respond_with_data(
		f'<html><body>{long_content}</body></html>',
		content_type='text/html',
	)

	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/long'), new_tab=False, browser_session=browser_session)

	viewport_result = await tools.registry.execute_action(
		'screenshot',
		{'full_page': False},
		browser_session=browser_session,
		file_system=file_system,
	)
	assert viewport_result.error is None
	viewport_path = Path(viewport_result.extracted_content.split('to ')[-1])
	viewport_size = viewport_path.stat().st_size

	full_result = await tools.registry.execute_action(
		'screenshot',
		{'full_page': True},
		browser_session=browser_session,
		file_system=file_system,
	)
	assert full_result.error is None
	assert 'full page' in full_result.extracted_content
	full_path = Path(full_result.extracted_content.split('to ')[-1])
	full_size = full_path.stat().st_size

	assert full_size > viewport_size, (
		f'Full page screenshot ({full_size}B) should be larger than viewport ({viewport_size}B)'
	)


async def test_screenshot_counter_increments(browser_session: BrowserSession, file_system: FileSystem, httpserver: HTTPServer):
	"""Multiple screenshots should produce uniquely numbered files."""
	httpserver.expect_request('/').respond_with_data(
		'<html><body>Counter test</body></html>',
		content_type='text/html',
	)

	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=browser_session)

	result1 = await tools.registry.execute_action(
		'screenshot', {}, browser_session=browser_session, file_system=file_system,
	)
	result2 = await tools.registry.execute_action(
		'screenshot', {}, browser_session=browser_session, file_system=file_system,
	)

	assert result1.error is None
	assert result2.error is None

	path1 = Path(result1.extracted_content.split('to ')[-1])
	path2 = Path(result2.extracted_content.split('to ')[-1])

	assert path1 != path2, 'Each screenshot should get a unique filename'
	assert 'screenshot_1' in path1.name
	assert 'screenshot_2' in path2.name
	assert path1.exists()
	assert path2.exists()


# ---------------------------------------------------------------------------
# 5. done() handles absolute screenshot paths in files_to_display
# ---------------------------------------------------------------------------


async def test_done_with_screenshot_attachment(browser_session: BrowserSession, file_system: FileSystem, httpserver: HTTPServer):
	"""done(files_to_display=[abs_path]) should include screenshot PNGs in attachments."""
	httpserver.expect_request('/').respond_with_data(
		'<html><body>Done test</body></html>',
		content_type='text/html',
	)

	tools = Tools()
	await tools.navigate(url=httpserver.url_for('/'), new_tab=False, browser_session=browser_session)

	# Take a screenshot first
	ss_result = await tools.registry.execute_action(
		'screenshot', {}, browser_session=browser_session, file_system=file_system,
	)
	assert ss_result.error is None
	screenshot_path = ss_result.extracted_content.split('to ')[-1]

	# Now call done with the absolute screenshot path
	done_result = await tools.registry.execute_action(
		'done',
		{'text': 'Here is the screenshot', 'success': True, 'files_to_display': [screenshot_path]},
		file_system=file_system,
	)

	assert done_result.is_done is True
	assert done_result.success is True
	assert done_result.attachments is not None
	assert len(done_result.attachments) >= 1
	assert screenshot_path in done_result.attachments, (
		f'Screenshot path {screenshot_path} should be in attachments {done_result.attachments}'
	)
