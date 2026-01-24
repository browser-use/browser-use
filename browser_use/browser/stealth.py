import asyncio
import math
import random
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession
	from browser_use.actor.mouse import Mouse


UA_STRINGS = [
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
	'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
	'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
]


class StealthConfig(BaseModel):
	"""Configuration for stealth mode."""

	enabled: bool = Field(default=False, description='Enable stealth mode')
	navigator_webdriver: bool = Field(default=True, description='Patch navigator.webdriver to false')
	webgl_vendor: str = Field(default='Intel Inc.', description='Spoofed WebGL vendor')
	webgl_renderer: str = Field(default='Intel Iris OpenGL Engine', description='Spoofed WebGL renderer')
	nav_plugins: bool = Field(default=True, description='Mock navigator.plugins and navigator.mimeTypes')
	nav_languages: bool = Field(default=True, description='Mock navigator.languages')
	random_user_agent: bool = Field(default=True, description='Randomize User-Agent')

	# Mouse stealth settings
	mouse_smoothing: bool = Field(default=True, description='Use Bezier curves for mouse movement')
	mouse_jitter: bool = Field(default=True, description='Add random jitter to mouse movement')
	random_delays: bool = Field(default=True, description='Add random delays between actions')


class StealthService:
	"""Service to apply stealth patches to the browser."""

	def __init__(self, config: StealthConfig):
		self.config = config

	async def apply_stealth(self, session: 'CDPSession') -> None:
		"""Apply stealth scripts to the session."""
		if not self.config.enabled:
			return

		tasks = []

		if self.config.navigator_webdriver:
			tasks.append(self._patch_navigator_webdriver(session))
		
		if self.config.webgl_vendor and self.config.webgl_renderer:
			tasks.append(self._patch_webgl(session))
			
		if self.config.nav_plugins:
			tasks.append(self._patch_plugins(session))
			
		if self.config.nav_languages:
			tasks.append(self._patch_languages(session))

		if self.config.random_user_agent:
			tasks.append(self._patch_user_agent(session))

		await asyncio.gather(*tasks)

	async def _patch_user_agent(self, session: 'CDPSession') -> None:
		ua = random.choice(UA_STRINGS)
		await session.cdp_client.send.Network.setUserAgentOverride(
			params={'userAgent': ua},
			session_id=session.session_id,
		)

	async def _patch_navigator_webdriver(self, session: 'CDPSession') -> None:
		script = """
			Object.defineProperty(navigator, 'webdriver', {
				get: () => false,
			});
		"""
		await session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script},
			session_id=session.session_id,
		)

	async def _patch_webgl(self, session: 'CDPSession') -> None:
		script = f"""
			const getParameter = WebGLRenderingContext.prototype.getParameter;
			WebGLRenderingContext.prototype.getParameter = function(parameter) {{
				if (parameter === 37445) {{
					return '{self.config.webgl_vendor}';
				}}
				if (parameter === 37446) {{
					return '{self.config.webgl_renderer}';
				}}
				return getParameter(parameter);
			}};
		"""
		await session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script},
			session_id=session.session_id,
		)

	async def _patch_plugins(self, session: 'CDPSession') -> None:
		# Basic mock for plugins/mimeTypes
		script = """
			Object.defineProperty(navigator, 'plugins', {
				get: () => [1, 2, 3, 4, 5],
			});
			Object.defineProperty(navigator, 'mimeTypes', {
				get: () => [1, 2, 3, 4, 5],
			});
		"""
		await session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script},
			session_id=session.session_id,
		)
		
	async def _patch_languages(self, session: 'CDPSession') -> None:
		script = """
			Object.defineProperty(navigator, 'languages', {
				get: () => ['en-US', 'en'],
			});
		"""
		await session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script},
			session_id=session.session_id,
		)


class BezierMouse:
	"""Implements human-like mouse movement using Bezier curves."""

	@staticmethod
	def _binomial(n: int, k: int) -> float:
		return math.factorial(n) / (math.factorial(k) * math.factorial(n - k))

	@staticmethod
	def _bernstein(n: int, k: int, t: float) -> float:
		return BezierMouse._binomial(n, k) * (t**k) * ((1 - t) ** (n - k))

	@staticmethod
	def _bezier(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
		n = len(points) - 1
		x = sum(BezierMouse._bernstein(n, i, t) * points[i][0] for i in range(n + 1))
		y = sum(BezierMouse._bernstein(n, i, t) * points[i][1] for i in range(n + 1))
		return x, y

	@staticmethod
	async def move(mouse: 'Mouse', start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 10) -> None:
		"""Move mouse from start to end using a Bezier curve."""
		
		# Control points for the Bezier curve
		# Add some randomness to the control points to make it look human
		delta_x = end_x - start_x
		delta_y = end_y - start_y
		
		# Random control points
		c1_x = start_x + delta_x * random.uniform(0.2, 0.4) + random.uniform(-50, 50)
		c1_y = start_y + delta_y * random.uniform(0.1, 0.3) + random.uniform(-50, 50)
		
		c2_x = start_x + delta_x * random.uniform(0.6, 0.8) + random.uniform(-50, 50)
		c2_y = start_y + delta_y * random.uniform(0.7, 0.9) + random.uniform(-50, 50)
		
		points = [(start_x, start_y), (c1_x, c1_y), (c2_x, c2_y), (end_x, end_y)]
		
		# Calculate path
		path = []
		for i in range(steps + 1):
			t = i / steps
			# Apply easing (ease-in-out)
			t_eased = t * t * (3 - 2 * t)
			x, y = BezierMouse._bezier(points, t_eased)
			path.append((int(x), int(y)))
			
		# Execute movement
		for point in path:
			await mouse._client.send.Input.dispatchMouseEvent(
				params={'type': 'mouseMoved', 'x': point[0], 'y': point[1]},
				session_id=mouse._session_id,
			)
			# Random micro-delay
			await asyncio.sleep(random.uniform(0.001, 0.005))
