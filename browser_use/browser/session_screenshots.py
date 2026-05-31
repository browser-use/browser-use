"""Screenshot helpers for BrowserSession."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from cdp_use.cdp.page import CaptureScreenshotParameters

from browser_use.observability import observe_debug


class BrowserSessionScreenshotMixin:
	"""CDP screenshot and element-bounds helpers."""

	@observe_debug(ignore_input=True, ignore_output=True, name='take_screenshot')
	async def take_screenshot(
		self: Any,
		path: str | None = None,
		full_page: bool = False,
		format: str = 'png',
		quality: int | None = None,
		clip: dict | None = None,
	) -> bytes:
		"""Take a screenshot using CDP."""
		cdp_session = await self.get_or_create_cdp_session()

		params: CaptureScreenshotParameters = {
			'format': format,
			'captureBeyondViewport': full_page,
		}

		if quality is not None and format == 'jpeg':
			params['quality'] = quality

		if clip:
			params['clip'] = {
				'x': clip['x'],
				'y': clip['y'],
				'width': clip['width'],
				'height': clip['height'],
				'scale': 1,
			}

		params = CaptureScreenshotParameters(**params)

		result = await cdp_session.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp_session.session_id)

		if not result or 'data' not in result:
			raise Exception('Screenshot failed - no data returned')

		screenshot_data = base64.b64decode(result['data'])

		if path:
			Path(path).write_bytes(screenshot_data)

		return screenshot_data

	async def screenshot_element(
		self: Any,
		selector: str,
		path: str | None = None,
		format: str = 'png',
		quality: int | None = None,
	) -> bytes:
		"""Take a screenshot of a specific element."""
		bounds = await self._get_element_bounds(selector)
		if not bounds:
			raise ValueError(f"Element '{selector}' not found or has no bounds")

		return await self.take_screenshot(
			path=path,
			format=format,
			quality=quality,
			clip=bounds,
		)

	async def _get_element_bounds(self: Any, selector: str) -> dict | None:
		"""Get an element bounding box using CDP."""
		cdp_session = await self.get_or_create_cdp_session()

		doc = await cdp_session.cdp_client.send.DOM.getDocument(params={'depth': 1}, session_id=cdp_session.session_id)

		node_result = await cdp_session.cdp_client.send.DOM.querySelector(
			params={'nodeId': doc['root']['nodeId'], 'selector': selector}, session_id=cdp_session.session_id
		)

		node_id = node_result.get('nodeId')
		if not node_id:
			return None

		box_result = await cdp_session.cdp_client.send.DOM.getBoxModel(
			params={'nodeId': node_id}, session_id=cdp_session.session_id
		)

		box_model = box_result.get('model')
		if not box_model:
			return None

		content = box_model['content']
		return {
			'x': min(content[0], content[2], content[4], content[6]),
			'y': min(content[1], content[3], content[5], content[7]),
			'width': max(content[0], content[2], content[4], content[6]) - min(content[0], content[2], content[4], content[6]),
			'height': max(content[1], content[3], content[5], content[7]) - min(content[1], content[3], content[5], content[7]),
		}
