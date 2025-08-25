"""Test that GIF generation works properly when real navigation happens."""

import asyncio

from browser_use import Agent, AgentHistoryList
from browser_use.browser import BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


async def test_gif_generation_with_real_navigation(httpserver, tmp_path):
	"""Test that GIF is properly generated when agent navigates to a real page."""
	# Set up a test page with visible content
	httpserver.expect_request('/').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Test Page for GIF</title>
			<style>
				body {
					background-color: #f0f0f0;
					font-family: Arial, sans-serif;
					padding: 50px;
				}
				h1 {
					color: #333;
					font-size: 48px;
				}
				.content {
					background: white;
					padding: 30px;
					border-radius: 10px;
					box-shadow: 0 2px 10px rgba(0,0,0,0.1);
				}
			</style>
		</head>
		<body>
			<div class="content">
				<h1>Test Page for GIF Generation</h1>
				<p>This page has real content that should appear in the GIF.</p>
				<button id="test-button">Click Me</button>
			</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Create a mock LLM that navigates then completes
	navigate_action = f'{{"action": [{{"go_to_url": {{"url": "{httpserver.url_for("/")}"}}}}]}}'
	done_action = '{"action": [{"done": {"text": "Navigated successfully", "success": true}}]}'
	llm_with_navigation = create_mock_llm(actions=[navigate_action, done_action])

	# Set up output path
	gif_path = tmp_path / 'test_agent.gif'

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True, user_data_dir=None))
	await browser_session.start()

	try:
		agent = Agent(
			task=f'Navigate to {httpserver.url_for("/")} and verify the page loads',
			llm=llm_with_navigation,
			browser_session=browser_session,
			generate_gif=str(gif_path),
		)

		history: AgentHistoryList = await agent.run(max_steps=3)

		# Verify the task completed
		result = history.final_result()
		assert result is not None
		# result is a string, not an object with success attribute

		# Give a moment for GIF to be written
		await asyncio.sleep(0.1)

		# Verify GIF was created
		assert gif_path.exists(), f'GIF was not created at {gif_path}'

		# Verify GIF has substantial content (not just placeholders)
		gif_size = gif_path.stat().st_size
		assert gif_size > 10000, f'GIF file is too small ({gif_size} bytes), likely only contains placeholders'

		# Verify history contains real screenshots (not placeholders)
		has_real_screenshot = False
		for item in history.history:
			screenshot_b64 = item.state.get_screenshot()
			if (
				screenshot_b64
				and screenshot_b64
				!= 'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGP8//8/AwwwMSAB3BwAlm4DBfIlvvkAAAAASUVORK5CYII='
			):
				has_real_screenshot = True
				break

		assert has_real_screenshot, 'No real screenshots found in history, only placeholders'

	finally:
		await browser_session.kill()


async def test_gif_generation_without_vision(httpserver, tmp_path):
	"""Test that GIF is generated even when use_vision=False (issue #2615)."""
	# Set up a test page with visible content
	httpserver.expect_request('/').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Test Page - No Vision Mode</title>
			<style>
				body {
					background-color: #e0f0ff;
					font-family: Arial, sans-serif;
					padding: 50px;
				}
				h1 {
					color: #0066cc;
					font-size: 48px;
				}
				.content {
					background: white;
					padding: 30px;
					border-radius: 10px;
					box-shadow: 0 2px 10px rgba(0,0,0,0.1);
				}
			</style>
		</head>
		<body>
			<div class="content">
				<h1>No Vision Mode Test</h1>
				<p>This page should generate a GIF even when use_vision=False.</p>
				<button id="test-button">Test Button</button>
			</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Create a mock LLM that navigates then completes
	navigate_action = f'{{"action": [{{"go_to_url": {{"url": "{httpserver.url_for("/")}"}}}}]}}'
	done_action = '{"action": [{"done": {"text": "Successfully tested without vision", "success": true}}]}'
	llm_no_vision = create_mock_llm(actions=[navigate_action, done_action])

	# Set up output path
	gif_path = tmp_path / 'no_vision_test.gif'

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True, user_data_dir=None))
	await browser_session.start()

	try:
		agent = Agent(
			task=f'Navigate to {httpserver.url_for("/")} without using vision',
			llm=llm_no_vision,
			browser_session=browser_session,
			use_vision=False,  # Key: disable vision
			generate_gif=str(gif_path),  # Key: enable GIF generation
		)

		history: AgentHistoryList = await agent.run(max_steps=3)

		# Verify the task completed
		result = history.final_result()
		assert result is not None

		# Give a moment for GIF to be written
		await asyncio.sleep(0.1)

		# Verify GIF was created even without vision
		assert gif_path.exists(), f'GIF was not created at {gif_path} when use_vision=False'

		# Verify GIF has content (non-zero size)
		assert gif_path.stat().st_size > 0, f'GIF file is empty at {gif_path}'

		# Verify we have screenshots in history for GIF generation
		screenshots = history.screenshots(return_none_if_not_screenshot=True)
		assert screenshots, 'No screenshots found in history for GIF generation'

		# Verify at least one valid screenshot exists (not all placeholders)
		valid_screenshots = [
			s
			for s in screenshots
			if s and s != 'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAE0lEQVR42mP8/5+BgYGBgYGBgQEAAP//AwMC/wE='
		]
		assert valid_screenshots, 'No valid screenshots found for GIF generation'

	finally:
		await browser_session.kill()


async def test_gif_not_created_when_only_placeholders(tmp_path):
	"""Test that no GIF is created when all screenshots are placeholders."""
	# Use default mock LLM that just returns done without navigation
	llm = create_mock_llm()

	gif_path = tmp_path / 'should_not_exist.gif'

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, disable_security=True, user_data_dir=None))
	await browser_session.start()

	try:
		agent = Agent(
			task='Just complete without navigation',
			llm=llm,
			browser_session=browser_session,
			generate_gif=str(gif_path),
		)

		history: AgentHistoryList = await agent.run(max_steps=2)

		# Task should complete
		result = history.final_result()
		assert result is not None

		# GIF should NOT be created
		assert not gif_path.exists(), 'GIF should not be created when all screenshots are placeholders'

	finally:
		await browser_session.kill()
