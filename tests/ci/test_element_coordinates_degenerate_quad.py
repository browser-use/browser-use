"""Regression test: `get_element_coordinates` must not give up on an element whose first content quad is degenerate.

Chromium returns a zero-width/zero-height quad for inline elements that start with a line break, even
though the element itself has bounds. The method used to read only `quads[0]` and return `None`, skipping
the `DOM.getBoxModel` and `getBoundingClientRect` fallbacks entirely.
"""

from types import SimpleNamespace
from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

# Recorded from Chromium (headless shell, Chromium 139) for:
# <div style="width:60px">aaaa <span id="t"><br>bbbbb</span></div>
DEGENERATE_FIRST_QUAD = {'quads': [[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17], [0, 18, 40, 18, 40, 35, 0, 35]]}
BOX_MODEL = {'model': {'content': [0, 0, 40, 0, 40, 35, 0, 35]}}


class DOM:
	def __init__(self, quads=None, box_model=None):
		self._quads = quads
		self._box_model = box_model
		self.calls: list[str] = []

	async def getContentQuads(self, params, session_id=None):
		self.calls.append('getContentQuads')
		return self._quads

	async def getBoxModel(self, params, session_id=None):
		self.calls.append('getBoxModel')
		return self._box_model

	async def resolveNode(self, params, session_id=None):
		self.calls.append('resolveNode')
		return {}


class Runtime:
	"""Stands in for the JS fallback so the tests can prove it was never reached."""

	def __init__(self):
		self.calls: list[str] = []

	async def callFunctionOn(self, params, session_id=None):
		self.calls.append('callFunctionOn')
		return {}


def _cdp_session(dom: DOM) -> Any:
	return SimpleNamespace(
		session_id='s1',
		cdp_client=SimpleNamespace(send=SimpleNamespace(DOM=dom, Runtime=Runtime())),
	)


def _session() -> BrowserSession:
	return BrowserSession(browser_profile=BrowserProfile(headless=True))


async def test_degenerate_first_quad_uses_next_quad() -> None:
	session = _session()
	rect = await session.get_element_coordinates(
		backend_node_id=1, cdp_session=_cdp_session(DOM(quads=DEGENERATE_FIRST_QUAD, box_model=BOX_MODEL))
	)

	assert rect is not None, 'element has a 40x17 quad but get_element_coordinates returned None'
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 18, 40, 17)


async def test_only_degenerate_quads_fall_back_to_box_model() -> None:
	session = _session()
	rect = await session.get_element_coordinates(
		backend_node_id=1,
		cdp_session=_cdp_session(DOM(quads={'quads': [DEGENERATE_FIRST_QUAD['quads'][0]]}, box_model=BOX_MODEL)),
	)

	assert rect is not None, 'box model has a 40x35 box but get_element_coordinates returned None'
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 40, 35)


async def test_usable_quad_still_short_circuits() -> None:
	dom = DOM(quads={'quads': [[10, 10, 60, 10, 60, 30, 10, 30]]})
	session = _session()
	rect = await session.get_element_coordinates(backend_node_id=1, cdp_session=_cdp_session(dom))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (10, 10, 50, 20)

	# A usable first quad must not reach either fallback.
	assert dom.calls == ['getContentQuads']


# All four points sit on the line y = x: the bounding box is 30x30, the area is zero.
COLLINEAR_QUAD: list[float] = [0, 0, 10, 10, 20, 20, 30, 30]


def test_rect_from_quad_rejects_collinear_quad() -> None:
	assert BrowserSession._rect_from_quad(COLLINEAR_QUAD) is None


async def test_collinear_quad_falls_back_to_box_model() -> None:
	dom = DOM(quads={'quads': [COLLINEAR_QUAD]}, box_model=BOX_MODEL)
	session = _session()
	rect = await session.get_element_coordinates(backend_node_id=1, cdp_session=_cdp_session(dom))

	assert rect is not None, 'the only quad is degenerate, so the box model has to answer'
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 40, 35)
	assert dom.calls == ['getContentQuads', 'getBoxModel']
