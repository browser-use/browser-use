"""Verify that coordinates from the model's screenshot hit the real page target."""

import base64
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from pytest_httpserver import HTTPServer

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser.profile import BrowserProfile, ViewportSize
from browser_use.browser.session import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import ContentPartImageParam
from browser_use.tools.service import Tools


@pytest.fixture
async def coordinate_browser_session(device_scale_factor: int) -> AsyncIterator[BrowserSession]:
	"""Use a fixed CSS viewport and an isolated browser without extension downloads."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			enable_default_extensions=False,
			highlight_elements=False,
			viewport=ViewportSize(width=1200, height=800),
			device_scale_factor=device_scale_factor,
		)
	)
	try:
		await session.start()
		yield session
	finally:
		await session.kill()


def screenshot_target_center(image: Image.Image) -> tuple[int, int]:
	"""Locate the solid magenta target using pixels, independently of coordinate scaling."""
	red, green, blue = image.convert('RGB').split()
	bright_channel = [255 if value > 240 else 0 for value in range(256)]
	dark_channel = [255 if value < 15 else 0 for value in range(256)]
	mask = ImageChops.multiply(red.point(bright_channel), blue.point(bright_channel))
	mask = ImageChops.multiply(mask, green.point(dark_channel))
	bounds = mask.getbbox()
	assert bounds is not None, 'The target must be visible in the screenshot sent to the model'
	left, top, right, bottom = bounds
	return (left + right) // 2, (top + bottom) // 2


@pytest.mark.parametrize(
	('llm_screenshot_size', 'scroll_y', 'device_scale_factor'),
	[
		pytest.param(None, 0, 1, id='no-resize'),
		pytest.param((1200, 800), 0, 1, id='same-size'),
		pytest.param((600, 400), 0, 1, id='uniform-downscale'),
		pytest.param((600, 200), 0, 1, id='nonuniform-downscale'),
		pytest.param((1800, 1200), 0, 1, id='uniform-upscale'),
		pytest.param((600, 200), 600, 1, id='nonuniform-downscale-after-scroll'),
		pytest.param((600, 200), 0, 2, id='nonuniform-downscale-hidpi'),
	],
)
async def test_screenshot_coordinates_click_target(
	coordinate_browser_session: BrowserSession,
	httpserver: HTTPServer,
	tmp_path: Path,
	llm_screenshot_size: tuple[int, int] | None,
	scroll_y: int,
	device_scale_factor: int,
) -> None:
	"""Exercise state capture, prompt resizing, action conversion, and real CDP input together."""
	httpserver.expect_request('/coordinate-target').respond_with_data(
		f"""
		<!doctype html>
		<html>
		<head>
			<title>Screenshot coordinate target</title>
			<link rel="icon" href="data:,">
			<style>
				::-webkit-scrollbar {{ width: 16px; height: 16px; }}
				body {{ margin: 0; width: 1600px; height: 2000px; background: white; }}
				#target {{ position: absolute; left: 1008px; top: {356 + scroll_y}px;
					width: 24px; height: 24px; padding: 0; border: 0;
					background: rgb(255, 0, 255); }}
			</style>
		</head>
		<body>
			<button id="target" aria-label="Click target"></button>
			<script>
				window.clicks = [];
				document.addEventListener('click', event => {{
					window.clicks.push({{id: event.target.id, x: event.clientX,
						y: event.clientY, trusted: event.isTrusted}});
				}});
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)
	session = coordinate_browser_session
	session.llm_screenshot_size = llm_screenshot_size
	await session.navigate_to(httpserver.url_for('/coordinate-target'))
	cdp_session = await session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': f'window.scrollTo(0, {scroll_y}); new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))',
			'awaitPromise': True,
		},
		session_id=cdp_session.session_id,
	)

	# Capture through the observation pipeline so it must populate the original viewport itself.
	state = await session.get_browser_state_summary(include_screenshot=True)
	assert state.screenshot is not None
	message = AgentMessagePrompt(
		browser_state_summary=state,
		file_system=FileSystem(tmp_path),
		screenshots=[state.screenshot],
		llm_screenshot_size=llm_screenshot_size,
	).get_user_message(use_vision=True)
	assert isinstance(message.content, list)
	images = [part for part in message.content if isinstance(part, ContentPartImageParam)]
	assert len(images) == 1
	with Image.open(BytesIO(base64.b64decode(images[0].image_url.url.split(',', 1)[1]))) as image:
		assert image.size == (llm_screenshot_size or (1200 * device_scale_factor, 800 * device_scale_factor))
		coordinate_x, coordinate_y = screenshot_target_center(image)

	tools = Tools()
	tools.set_coordinate_clicking(True)
	result = await tools.registry.execute_action(
		'click', {'coordinate_x': coordinate_x, 'coordinate_y': coordinate_y}, browser_session=session
	)
	assert result.error is None, result.error

	# The DOM event is the oracle: a successful tool response alone does not prove a hit.
	response = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """(() => {
				const rect = document.getElementById('target').getBoundingClientRect();
				return {clicks: window.clicks, scrollY: window.scrollY,
					centerX: rect.left + rect.width / 2, centerY: rect.top + rect.height / 2};
			})()""",
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	page_result = response['result'].get('value')
	assert page_result is not None
	assert page_result['scrollY'] == scroll_y
	assert len(page_result['clicks']) == 1
	click = page_result['clicks'][0]
	assert click['id'] == 'target', f'Clicked {click} instead of the screenshot target'
	assert click['trusted'] is True
	assert click['x'] == pytest.approx(page_result['centerX'], abs=2)
	assert click['y'] == pytest.approx(page_result['centerY'], abs=2)
