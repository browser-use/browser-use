"""Session registry - manages BrowserSession instances."""

import logging
from dataclasses import dataclass, field
from typing import Any

from browser_use.browser.session import BrowserSession
from browser_use.skill_cli.python_session import PythonSession

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
	"""Information about a browser session."""

	name: str
	browser_mode: str
	headed: bool
	profile: str | None
	browser_session: BrowserSession
	python_session: PythonSession = field(default_factory=PythonSession)


class SessionRegistry:
	"""Registry of active browser sessions.

	Sessions are created on-demand when first accessed. Each named session
	is isolated with its own BrowserSession and Python namespace.
	"""

	def __init__(self) -> None:
		self._sessions: dict[str, SessionInfo] = {}

	async def get_or_create(
		self,
		name: str,
		browser_mode: str,
		headed: bool,
		profile: str | None,
	) -> SessionInfo:
		"""Get existing session or create new one."""
		if name in self._sessions:
			return self._sessions[name]

		logger.info(f'Creating new session: {name} (mode={browser_mode}, headed={headed})')

		browser_session = await create_browser_session(browser_mode, headed, profile)
		await browser_session.start()

		session_info = SessionInfo(
			name=name,
			browser_mode=browser_mode,
			headed=headed,
			profile=profile,
			browser_session=browser_session,
		)
		self._sessions[name] = session_info
		return session_info

	def get(self, name: str) -> SessionInfo | None:
		"""Get session by name."""
		return self._sessions.get(name)

	def list_sessions(self) -> list[dict[str, Any]]:
		"""List all active sessions."""
		return [
			{
				'name': s.name,
				'browser_mode': s.browser_mode,
				'headed': s.headed,
				'profile': s.profile,
			}
			for s in self._sessions.values()
		]

	async def close_session(self, name: str) -> bool:
		"""Close and remove a session."""
		if name not in self._sessions:
			return False

		session = self._sessions.pop(name)
		logger.info(f'Closing session: {name}')
		try:
			await session.browser_session.kill()
		except Exception as e:
			logger.warning(f'Error closing session {name}: {e}')
		return True

	async def close_all(self) -> None:
		"""Close all sessions."""
		for name in list(self._sessions.keys()):
			await self.close_session(name)


async def create_browser_session(
	mode: str,
	headed: bool,
	profile: str | None,
) -> BrowserSession:
	"""Create BrowserSession based on mode.

	Modes:
	- chromium: Playwright-managed Chromium (default)
	- real: User's Chrome with profile
	- remote: Browser-Use Cloud (requires API key)
	"""
	if mode == 'chromium':
		return BrowserSession(
			headless=not headed,
		)

	elif mode == 'real':
		from browser_use.skill_cli.utils import find_chrome_executable, get_chrome_profile_path

		chrome_path = find_chrome_executable()
		if not chrome_path:
			raise RuntimeError('Could not find Chrome executable. Please install Chrome or specify --browser chromium')

		user_data_dir = get_chrome_profile_path(profile)

		return BrowserSession(
			executable_path=chrome_path,
			user_data_dir=user_data_dir,
			headless=False,  # Real browser always visible
		)

	elif mode == 'remote':
		from browser_use.skill_cli.api_key import require_api_key

		require_api_key('Remote browser')
		return BrowserSession(
			use_cloud=True,
		)

	else:
		raise ValueError(f'Unknown browser mode: {mode}')
