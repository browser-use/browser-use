"""Trusted pointer travel before a click, as a person moves the mouse.

Akamai validates its _abck sensor cookie only after real mouseMoved travel: _abck reached ~0~ in 16/16 cloud sessions
with a 10-20 step curved path (hilton.com, homedepot.com) vs ~1/46 with teleport clicks or no mouse. A page that saw no
trusted press at all got its login POST refused (hilton.com: 403 in 18/18 vs 0/28 with one).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait

logger = logging.getLogger(__name__)

STEPS = (10, 12)  # mouseMoved events per path
STEP_S = (0.01, 0.025)  # time between them; Chrome coalesces moves closer than a frame
ACK_WAIT_S = 2.0  # a tab hidden mid-path acks each move only after ~5 s: go on without them
VIEW_JS = '[document.visibilityState, innerWidth, innerHeight]'


class Mouse:
	"""click(x, y): a curved mouseMoved path from the last pointer position to (x, y), then press and release.

	The moves go out without waiting for each answer, spaced as a hand moves: one at a time, a cloud browser's round
	trip (~80 ms from a laptop) set the pace, and a path cost ~0.7 s per click instead of ~0.25 s."""

	def __init__(self, cdp: Callable[..., dict]):
		self.cdp = cdp
		self.at: tuple[float, float] | None = None
		self._pool = ThreadPoolExecutor(16, thread_name_prefix='mouse')

	def move_to(self, x: float, y: float) -> None:
		try:
			state, width, height = self.cdp('Runtime.evaluate', expression=VIEW_JS, returnByValue=True)['result']['value']
		except Exception:
			state, width, height = 'unknown', 800, 600
		if state != 'visible':  # Chrome acks each mouseMoved to a hidden tab only after ~5 s (measured, headless)
			logger.debug('No mouse path: the tab is %s', state)
			return
		x0, y0 = self.at or (random.uniform(0.2, 0.8) * width, random.uniform(0.2, 0.8) * height)
		# quadratic Bezier through a random control point, eased in and out, ending exactly on the target
		cx = (x0 + x) / 2 + random.uniform(-0.15, 0.15) * width
		cy = (y0 + y) / 2 + random.uniform(-0.15, 0.15) * height
		steps = random.randint(*STEPS)
		sent = []
		for i in range(1, steps + 1):
			t = i / steps
			t = t * t * (3 - 2 * t)
			px = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x if i < steps else x
			py = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y if i < steps else y
			sent.append(self._pool.submit(self.cdp, 'Input.dispatchMouseEvent', type='mouseMoved', x=px, y=py))
			if i < steps:
				time.sleep(random.uniform(*STEP_S))
		self.at = (x, y)
		done, late = wait(sent, ACK_WAIT_S)
		failed = [f.exception() for f in done if f.exception()]
		if late or failed:
			logger.debug('Mouse path: %d moves unanswered, %d failed (%s)', len(late), len(failed), failed[:1])

	def click(self, x: float, y: float, button: str = 'left', clicks: int = 1) -> None:
		self.move_to(x, y)
		time.sleep(random.uniform(0.02, 0.06))
		self.cdp('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button=button, clickCount=clicks)
		time.sleep(random.uniform(0.02, 0.05))
		self.cdp('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button=button, clickCount=clicks)
		self.at = (x, y)
