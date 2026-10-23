"""get_element_coordinates must not return None when content quads include a degenerate first line box.

Fixes #6153. CDP replies recorded from Chromium for:
  <div style="width:60px">aaaa <span id="t"><br>bbbbb</span></div>
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


CONTENT_QUADS = {
	'quads': [
		[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17],  # degenerate (zero width)
		[0, 18, 40, 18, 40, 35, 0, 35],  # real line box
	]
}
BOX_MODEL = {'model': {'content': [0, 0, 40, 0, 40, 35, 0, 35]}}
ALL_DEGENERATE_QUADS = {
	'quads': [
		[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17],
	]
}


class _DOM:
	def __init__(self, quads_payload, box_payload=BOX_MODEL):
		self._quads = quads_payload
		self._box = box_payload
		self.box_calls = 0

	async def getContentQuads(self, params, session_id=None):
		return self._quads

	async def getBoxModel(self, params, session_id=None):
		self.box_calls += 1
		return self._box


def _cdp_session(dom: _DOM):
	return SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(DOM=dom)))


def test_skips_degenerate_first_content_quad():
	dom = _DOM(CONTENT_QUADS)
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	rect = asyncio.run(session.get_element_coordinates(backend_node_id=1, cdp_session=_cdp_session(dom)))
	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 18, 40, 17)
	assert dom.box_calls == 0  # positive-area content quad wins; no fallback


def test_falls_back_to_box_model_when_all_content_quads_degenerate():
	dom = _DOM(ALL_DEGENERATE_QUADS)
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	rect = asyncio.run(session.get_element_coordinates(backend_node_id=1, cdp_session=_cdp_session(dom)))
	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 40, 35)
	assert dom.box_calls == 1
