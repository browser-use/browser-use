"""get_element_coordinates must not treat a degenerate leading quad as 'no bounds'.

Chromium's DOM.getContentQuads for an inline span that starts with a line break
returns a zero-width first quad (the ``<br>``) and a later quad that covers the
text. A non-empty quad list is not proof the element has no bounds: use the
first quad with positive area, and only then fall through to DOM.getBoxModel
and getBoundingClientRect.

Recorded from Chromium 139 headless shell for::

    <div style="width:60px">aaaa <span id="t"><br>bbbbb</span></div>
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, cast

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession, CDPSession

# First quad is the line break (zero width). Second quad is the text fragment.
_LEADING_BREAK_QUADS = [
	[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17],
	[0, 18, 40, 18, 40, 35, 0, 35],
]
# Box-model content for the same span: the union of both fragments, 40x35.
_BOX_MODEL_CONTENT = [0, 0, 40, 0, 40, 35, 0, 35]


class _RecordingDOM:
	def __init__(
		self,
		*,
		quads: Sequence[Sequence[float]] | None,
		box_content: Sequence[float] | None,
		calls: list[str],
	) -> None:
		self._quads = quads
		self._box_content = box_content
		self.calls = calls

	async def getContentQuads(self, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
		self.calls.append('getContentQuads')
		if self._quads is None:
			raise RuntimeError('getContentQuads unavailable')
		return {'quads': self._quads}

	async def getBoxModel(self, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
		self.calls.append('getBoxModel')
		if self._box_content is None:
			raise RuntimeError('getBoxModel unavailable')
		return {'model': {'content': self._box_content}}

	async def resolveNode(self, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
		self.calls.append('resolveNode')
		return {'object': {'objectId': 'obj-1'}}


class _RecordingRuntime:
	def __init__(self, rect: dict[str, float] | None, calls: list[str]) -> None:
		self._rect = rect
		self.calls = calls

	async def callFunctionOn(self, params: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
		self.calls.append('callFunctionOn')
		if self._rect is None:
			raise RuntimeError('getBoundingClientRect unavailable')
		return {'result': {'value': self._rect}}


def _cdp_session(dom: _RecordingDOM, runtime: _RecordingRuntime) -> CDPSession:
	client = SimpleNamespace(send=SimpleNamespace(DOM=dom, Runtime=runtime))
	return cast(CDPSession, SimpleNamespace(session_id='s1', cdp_client=client))


def _browser_session() -> BrowserSession:
	return BrowserSession(browser_profile=BrowserProfile(headless=True))


async def test_leading_degenerate_quad_uses_first_positive_quad() -> None:
	"""A zero-width first fragment must not hide a later quad that has area."""
	calls: list[str] = []
	dom = _RecordingDOM(quads=_LEADING_BREAK_QUADS, box_content=_BOX_MODEL_CONTENT, calls=calls)
	runtime = _RecordingRuntime(rect={'x': 1, 'y': 2, 'width': 3, 'height': 4}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None, 'element has a positive content quad but get_element_coordinates returned None'
	# The text fragment, not the 40x35 box-model union of the break plus the text.
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 18, 40, 17)
	assert calls == ['getContentQuads']


async def test_degenerate_quads_fall_back_to_box_model() -> None:
	"""When every content quad has zero area, DOM.getBoxModel still supplies bounds."""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[28.40625, 0, 28.40625, 0, 28.40625, 17, 28.40625, 17]],
		box_content=_BOX_MODEL_CONTENT,
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 1, 'y': 2, 'width': 3, 'height': 4}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None, 'element has a 40x35 box but get_element_coordinates returned None'
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 40, 35)
	assert calls == ['getContentQuads', 'getBoxModel']


async def test_degenerate_quads_and_box_model_fall_back_to_bounding_client_rect() -> None:
	"""getBoundingClientRect runs when content quads and the box model have no area."""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[0, 0, 0, 0, 0, 0, 0, 0]],
		box_content=[0, 0, 0, 0, 0, 0, 0, 0],
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 5, 'y': 6, 'width': 70, 'height': 15}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (5, 6, 70, 15)
	assert calls == ['getContentQuads', 'getBoxModel', 'resolveNode', 'callFunctionOn']


async def test_positive_first_quad_skips_fallbacks() -> None:
	"""A normal element still uses its first content quad and does not call fallbacks."""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[10, 20, 110, 20, 110, 60, 10, 60]],
		box_content=[0, 0, 1, 0, 1, 1, 0, 1],
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 0, 'y': 0, 'width': 9, 'height': 9}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (10, 20, 100, 40)
	assert calls == ['getContentQuads']


async def test_collinear_rotated_quad_falls_back_to_box_model() -> None:
	"""A zero-area quad with a positive bounding box must not count as bounds.

	These four points lie on y=x, so the axis-aligned box is 20x20 while the
	polygon area is 0. That quad is skipped and DOM.getBoxModel is used.
	"""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[0, 0, 10, 10, 20, 20, 5, 5]],
		box_content=[2, 3, 12, 3, 12, 9, 2, 9],
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 1, 'y': 2, 'width': 3, 'height': 4}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (2, 3, 10, 6)
	assert calls == ['getContentQuads', 'getBoxModel']


async def test_collinear_quad_and_box_model_fall_back_to_bounding_client_rect() -> None:
	"""getBoundingClientRect runs when the box model quad is collinear too."""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[0, 0, 10, 10, 20, 20, 5, 5]],
		box_content=[1, 1, 4, 4, 8, 8, 2, 2],
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 5, 'y': 6, 'width': 70, 'height': 15}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (5, 6, 70, 15)
	assert calls == ['getContentQuads', 'getBoxModel', 'resolveNode', 'callFunctionOn']


async def test_rotated_positive_area_quad_is_used() -> None:
	"""A rotated quad with real area still wins over the box model.

	Diamond (5, 0), (10, 5), (5, 10), (0, 5) has area 50. Its axis-aligned
	bounds are the 10x10 box at the origin.
	"""
	calls: list[str] = []
	dom = _RecordingDOM(
		quads=[[5, 0, 10, 5, 5, 10, 0, 5]],
		box_content=[0, 0, 1, 0, 1, 1, 0, 1],
		calls=calls,
	)
	runtime = _RecordingRuntime(rect={'x': 9, 'y': 9, 'width': 9, 'height': 9}, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (0, 0, 10, 10)
	assert calls == ['getContentQuads']


async def test_empty_quads_fall_back_to_box_model() -> None:
	"""An empty quad list still falls through to DOM.getBoxModel."""
	calls: list[str] = []
	dom = _RecordingDOM(quads=[], box_content=[4, 5, 14, 5, 14, 25, 4, 25], calls=calls)
	runtime = _RecordingRuntime(rect=None, calls=calls)

	rect = await _browser_session().get_element_coordinates(1, _cdp_session(dom, runtime))

	assert rect is not None
	assert (rect.x, rect.y, rect.width, rect.height) == (4, 5, 10, 20)
	assert calls == ['getContentQuads', 'getBoxModel']
