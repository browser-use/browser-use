"""Regression test: `get_element_coordinates` must not give up on an element whose first content quad is degenerate.

Chromium returns a zero-width/zero-height quad for inline elements that start with a line break, even
though the element itself has bounds. The method used to read only `quads[0]` and return `None`, skipping
the `DOM.getBoxModel` and `getBoundingClientRect` fallbacks entirely.
"""

from types import SimpleNamespace

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

	async def getContentQuads(self, params, session_id=None):
		return self._quads

	async def getBoxModel(self, params, session_id=None):
		return self._box_model


def _cdp_session(dom: DOM) -> SimpleNamespace:
	return SimpleNamespace(session_id='s1', cdp_client=SimpleNamespace(send=SimpleNamespace(DOM=dom)))


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
		cdp_session=_cdp_session(
			DOM(quads={'quads': [DEGENERATE_FIRST_QUAD['quads'][0]]}, box_model=BOX_MODEL)
		),
	)

	assert rect is not None, 'box model has a 40x35 box but get_element_coordinates returned None'
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 40, 35)


async def test_usable_quad_still_short_circuits() -> None:
	session = _session()
	rect = await session.get_element_coordinates(
		backend_node_id=1,
		cdp_session=_cdp_session(DOM(quads={'quads': [[10, 10, 60, 10, 60, 30, 10, 30]]})),
	)

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (10, 10, 50, 20)
