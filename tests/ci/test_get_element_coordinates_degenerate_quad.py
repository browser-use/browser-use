"""get_element_coordinates must not return None when only the first content quad is degenerate.

Chromium can return a non-empty getContentQuads list whose first quad has zero
width/height (e.g. an inline element that starts with a <br>) while later quads
and DOM.getBoxModel still have bounds. Previously we took quads[0] only and
skipped the box-model / getBoundingClientRect fallbacks whenever the list was
non-empty, so a visible element returned None.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Recorded from Chromium for:
# <div style="width:60px">aaaa <span id="t"><br>bbbbb</span></div>
CONTENT_QUADS = {
	'quads': [
		[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17],  # zero width
		[0, 18, 40, 18, 40, 35, 0, 35],  # 40x17
	]
}
BOX_MODEL = {'model': {'content': [0, 0, 40, 0, 40, 35, 0, 35]}}


class _DOM:
	async def getContentQuads(self, params, session_id=None):
		return CONTENT_QUADS

	async def getBoxModel(self, params, session_id=None):
		return BOX_MODEL


def _cdp_session():
	return SimpleNamespace(
		session_id='s1',
		cdp_client=SimpleNamespace(send=SimpleNamespace(DOM=_DOM())),
	)


def test_element_with_degenerate_first_quad_gets_coordinates():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	rect = asyncio.run(session.get_element_coordinates(backend_node_id=1, cdp_session=_cdp_session()))
	assert rect is not None
	assert rect.width > 0
	assert rect.height > 0


def test_all_degenerate_quads_fall_back_to_box_model():
	"""When every content quad is zero-area, Method 2 (getBoxModel) must still run."""

	class DegenerateOnlyDOM:
		async def getContentQuads(self, params, session_id=None):
			return {
				'quads': [[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17]],
			}

		async def getBoxModel(self, params, session_id=None):
			return BOX_MODEL

	cdp = SimpleNamespace(
		session_id='s1',
		cdp_client=SimpleNamespace(send=SimpleNamespace(DOM=DegenerateOnlyDOM())),
	)
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	rect = asyncio.run(session.get_element_coordinates(backend_node_id=1, cdp_session=cdp))
	assert rect is not None
	assert rect.width == 40
	assert rect.height == 35
