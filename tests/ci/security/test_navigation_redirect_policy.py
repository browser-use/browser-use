"""Regression tests for validating the final URL after redirects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from browser_use.browser.events import NavigateToUrlEvent, NavigationCompleteEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


async def test_navigation_complete_reports_final_redirect_url():
	"""The completion event must expose the redirect target so security policy can validate it."""
	requested_url = 'http://127.0.0.1:8080/redirect'
	redirect_url = 'http://localhost:8080/blocked'
	target = SimpleNamespace(url=requested_url)

	session = BrowserSession(
		browser_profile=BrowserProfile(
			enable_default_extensions=False,
			headless=True,
			user_data_dir=None,
		)
	)
	session.agent_focus_target_id = 'target-1'
	session.session_manager = SimpleNamespace(get_target=lambda _target_id: target)

	async def fake_navigate(*args, **kwargs):
		target.url = redirect_url
		return None

	session._navigate_and_wait = fake_navigate
	session._close_extension_options_pages = AsyncMock()
	dispatch = AsyncMock()
	session.event_bus.dispatch = dispatch

	await session.on_NavigateToUrlEvent(NavigateToUrlEvent(url=requested_url))

	events = [call.args[0] for call in dispatch.await_args_list]
	completed = [event for event in events if isinstance(event, NavigationCompleteEvent)]

	assert completed[-1].url == redirect_url
