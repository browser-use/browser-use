"""Compatibility Safari session wrapper.

Safari support now runs through ``BrowserSession`` with the Safari real-profile
backend enabled on the underlying ``BrowserProfile``. This wrapper preserves
the old import path and gives callers an explicit Safari session type without
forking the session implementation.
"""

from __future__ import annotations

from typing import Any

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


class SafariBrowserSession(BrowserSession):
	"""BrowserSession preconfigured for the Safari real-profile backend."""

	def __init__(
		self,
		*,
		id: str | None = None,
		browser_profile: BrowserProfile | None = None,
		profile: str | None = None,
		**kwargs: Any,
	) -> None:
		resolved_profile = profile or kwargs.pop('safari_profile', None) or 'active'
		browser_profile = browser_profile or BrowserProfile(
			automation_backend='safari',
			safari_profile=resolved_profile,
			profile_directory=resolved_profile,
			headless=False,
		)
		super().__init__(
			id=id,
			browser_profile=browser_profile,
			automation_backend='safari',
			safari_profile=resolved_profile,
			headless=False,
			**kwargs,
		)
