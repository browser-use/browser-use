"""Regression tests for validating the final URL after redirects."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from browser_use.browser.events import NavigateToUrlEvent, NavigationCompleteEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


class _FakeTargetClient:
	def __init__(self, url: str | None = None):
		self.url = url

	async def getTargetInfo(self, params):
		if self.url is None:
			raise RuntimeError('target info unavailable')
		return {'targetInfo': {'targetId': params['targetId'], 'url': self.url}}


def _make_session(target_url: str | None, cdp_url: str | None = None):
	target = SimpleNamespace(url=target_url) if target_url is not None else None
	target_client = _FakeTargetClient(cdp_url)
	session = BrowserSession(
		browser_profile=BrowserProfile(
			enable_default_extensions=False,
			headless=True,
			user_data_dir=None,
		)
	)
	session.agent_focus_target_id = 'target-1'
	session.session_manager = SimpleNamespace(get_target=lambda _target_id: target)
	setattr(session, '_cdp_client_root', SimpleNamespace(send=SimpleNamespace(Target=target_client)))
	session._navigate_and_wait = AsyncMock(return_value=None)
	session._close_extension_options_pages = AsyncMock()
	dispatch = AsyncMock()
	session.event_bus.dispatch = cast(Any, dispatch)
	return session, target, dispatch


async def test_navigation_complete_reports_final_redirect_url():
	"""The completion event must expose the redirect target so security policy can validate it."""
	requested_url = 'http://127.0.0.1:8080/redirect'
	redirect_url = 'http://localhost:8080/blocked'
	session, target, dispatch = _make_session(requested_url, redirect_url)

	await session.on_NavigateToUrlEvent(NavigateToUrlEvent(url=requested_url))

	events = [call.args[0] for call in dispatch.await_args_list]
	completed = [event for event in events if isinstance(event, NavigationCompleteEvent)]

	assert completed[-1].url == redirect_url
	assert target is not None
	assert target.url == redirect_url


async def test_navigation_complete_falls_back_to_session_target_when_cdp_is_unavailable():
	"""The cached target URL is used when the fresh CDP query fails."""
	requested_url = 'http://127.0.0.1:8080/redirect'
	cached_url = 'http://127.0.0.1:8080/cached'
	session, _, dispatch = _make_session(cached_url)

	await session.on_NavigateToUrlEvent(NavigateToUrlEvent(url=requested_url))

	events = [call.args[0] for call in dispatch.await_args_list]
	completed = [event for event in events if isinstance(event, NavigationCompleteEvent)]

	assert completed[-1].url == cached_url


async def test_navigation_complete_falls_back_to_requested_url_when_target_is_unavailable():
	"""The requested URL is retained when no cached or fresh target URL can be read."""
	requested_url = 'http://127.0.0.1:8080/redirect'
	session, _, dispatch = _make_session(None)

	await session.on_NavigateToUrlEvent(NavigateToUrlEvent(url=requested_url))

	events = [call.args[0] for call in dispatch.await_args_list]
	completed = [event for event in events if isinstance(event, NavigationCompleteEvent)]

	assert completed[-1].url == requested_url
