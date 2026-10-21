"""Mouse class for mouse operations."""

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
	from cdp_use.cdp.input.commands import DispatchMouseEventParameters, SynthesizeScrollGestureParameters
	from cdp_use.cdp.input.types import MouseButton

	from browser_use.browser.session import BrowserSession


def _resolve_scroll_anchor(x: int | None, y: int | None, viewport_width: float, viewport_height: float) -> tuple[float, float]:
	"""Resolve the (x, y) point a scroll event should be dispatched at.

	An explicit 0 must be honored as "left/top edge", not treated as "unset".
	Only a genuinely missing (None) coordinate falls back to the viewport center.
	"""
	scroll_x = x if x is not None else viewport_width / 2
	scroll_y = y if y is not None else viewport_height / 2
	return scroll_x, scroll_y


class Mouse:
	"""Mouse operations for a target."""

	def __init__(self, browser_session: 'BrowserSession', session_id: str | None = None, target_id: str | None = None):
		self._browser_session = browser_session
		self._client = browser_session.cdp_client
		self._session_id = session_id
		self._target_id = target_id
		self._x: float = 0
		self._y: float = 0
		self._buttons = 0

	@staticmethod
	def _modifiers(modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] | None) -> int:
		bits = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
		return sum(bits[key] for key in set(modifiers or []))

	@staticmethod
	def _button_bit(button: 'MouseButton') -> int:
		return {'none': 0, 'left': 1, 'right': 2, 'middle': 4, 'back': 8, 'forward': 16}[button]

	async def click(
		self,
		x: float,
		y: float,
		button: 'MouseButton' = 'left',
		click_count: int = 1,
		modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] | None = None,
	) -> None:
		"""Click at viewport coordinates, emitting complete click sequences."""
		if click_count < 1:
			raise ValueError('click_count must be positive')
		await self.move(x, y, modifiers=modifiers)
		for count in range(1, click_count + 1):
			try:
				await self.down(button, count, modifiers=modifiers)
			finally:
				await self.up(button, count, modifiers=modifiers)

	async def down(
		self,
		button: 'MouseButton' = 'left',
		click_count: int = 1,
		modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] | None = None,
	) -> None:
		"""Press at this Mouse instance's last position and retain button state."""
		buttons = self._buttons | self._button_bit(button)
		params: 'DispatchMouseEventParameters' = {
			'type': 'mousePressed',
			'x': self._x,
			'y': self._y,
			'button': button,
			'buttons': buttons,
			'clickCount': click_count,
			'modifiers': self._modifiers(modifiers),
		}
		await self._client.send.Input.dispatchMouseEvent(params, session_id=self._session_id)
		self._buttons = buttons

	async def up(
		self,
		button: 'MouseButton' = 'left',
		click_count: int = 1,
		modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] | None = None,
	) -> None:
		"""Release at the last position, preserving any other held buttons."""
		buttons = self._buttons & ~self._button_bit(button)
		params: 'DispatchMouseEventParameters' = {
			'type': 'mouseReleased',
			'x': self._x,
			'y': self._y,
			'button': button,
			'buttons': buttons,
			'clickCount': click_count,
			'modifiers': self._modifiers(modifiers),
		}
		await self._client.send.Input.dispatchMouseEvent(params, session_id=self._session_id)
		self._buttons = buttons

	async def move(
		self,
		x: float,
		y: float,
		steps: int = 1,
		modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] | None = None,
	) -> None:
		"""Move in linear steps while retaining pressed buttons for dragging."""
		if steps < 1:
			raise ValueError('steps must be positive')
		start_x, start_y = self._x, self._y
		for step in range(1, steps + 1):
			px = start_x + (x - start_x) * step / steps
			py = start_y + (y - start_y) * step / steps
			params: 'DispatchMouseEventParameters' = {
				'type': 'mouseMoved',
				'x': px,
				'y': py,
				'buttons': self._buttons,
				'modifiers': self._modifiers(modifiers),
			}
			await self._client.send.Input.dispatchMouseEvent(params, session_id=self._session_id)
			self._x, self._y = px, py

	async def scroll(
		self, x: int | None = None, y: int | None = None, delta_x: int | None = None, delta_y: int | None = None
	) -> None:
		"""Scroll the page using robust CDP methods."""
		if not self._session_id:
			raise RuntimeError('Session ID is required for scroll operations')

		# Get viewport dimensions (used to resolve x/y when the caller doesn't specify a coordinate)
		try:
			layout_metrics = await self._client.send.Page.getLayoutMetrics(session_id=self._session_id)
			viewport_width = layout_metrics['layoutViewport']['clientWidth']
			viewport_height = layout_metrics['layoutViewport']['clientHeight']
		except Exception:
			viewport_width = viewport_height = 0

		scroll_x, scroll_y = _resolve_scroll_anchor(x, y, viewport_width, viewport_height)

		# Calculate scroll deltas (positive = down/right)
		scroll_delta_x = delta_x or 0
		scroll_delta_y = delta_y or 0

		# Method 1: Try mouse wheel event (most reliable)
		try:
			await self._client.send.Input.dispatchMouseEvent(
				params={
					'type': 'mouseWheel',
					'x': scroll_x,
					'y': scroll_y,
					'deltaX': scroll_delta_x,
					'deltaY': scroll_delta_y,
				},
				session_id=self._session_id,
			)
			return

		except Exception:
			pass

		# Method 2: Fallback to synthesizeScrollGesture
		try:
			params: 'SynthesizeScrollGestureParameters' = {
				'x': scroll_x,
				'y': scroll_y,
				'xDistance': -(delta_x or 0),
				'yDistance': -(delta_y or 0),
			}
			await self._client.send.Input.synthesizeScrollGesture(
				params,
				session_id=self._session_id,
			)
		except Exception:
			# Method 3: JavaScript fallback
			scroll_js = f'window.scrollBy({delta_x or 0}, {delta_y or 0})'
			await self._client.send.Runtime.evaluate(
				params={'expression': scroll_js, 'returnByValue': True},
				session_id=self._session_id,
			)
