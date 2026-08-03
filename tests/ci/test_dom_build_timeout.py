"""Configurable DOM tree-build CDP timeout (dom_build_timeout / dom_build_retry_timeout).

DomService._get_all_trees waits for the parallel CDP tree-build calls (snapshot,
DOM, accessibility, viewport) with a budget that used to be hardcoded (10s, then a
2s retry). On slow remote/proxied browsers a full getFullAXTree can exceed 10s, so
the build fell back to a minimal DOM state with no way to raise the budget short of
patching the source. These are now BrowserProfile fields threaded through
DOMWatchdog into DomService.

Defaults must preserve the old behavior; overrides must be stored on DomService and
reach the asyncio.wait calls in _get_all_trees.
"""

from __future__ import annotations

import inspect

from browser_use import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
from browser_use.dom.service import DomService


def test_profile_defaults_preserve_legacy_budget():
	"""Unset fields must keep the historical 10s + 2s budget (backward compatible)."""
	profile = BrowserProfile()
	assert profile.dom_build_timeout == 10.0
	assert profile.dom_build_retry_timeout == 2.0


def test_profile_accepts_overrides():
	profile = BrowserProfile(dom_build_timeout=20.0, dom_build_retry_timeout=6.0)
	assert profile.dom_build_timeout == 20.0
	assert profile.dom_build_retry_timeout == 6.0


def test_dom_service_stores_timeouts():
	"""DomService keeps the default budget and honors explicit overrides."""
	session = BrowserSession(browser_profile=BrowserProfile())

	default = DomService(browser_session=session)
	assert default.dom_build_timeout == 10.0
	assert default.dom_build_retry_timeout == 2.0

	configured = DomService(browser_session=session, dom_build_timeout=20.0, dom_build_retry_timeout=6.0)
	assert configured.dom_build_timeout == 20.0
	assert configured.dom_build_retry_timeout == 6.0


def test_get_all_trees_uses_configured_timeouts_not_literals():
	"""Regression guard: _get_all_trees must read the configured attributes and not
	re-introduce the old hardcoded 10.0/2.0 literals. Exercising the full call path
	needs a live CDP session, so we assert on the source of the two lines this
	feature changed."""
	source = inspect.getsource(DomService._get_all_trees)
	assert 'timeout=self.dom_build_timeout' in source
	assert 'timeout=self.dom_build_retry_timeout' in source
	assert 'timeout=10.0' not in source
	assert 'timeout=2.0' not in source


def test_dom_watchdog_threads_profile_timeouts_into_dom_service():
	"""Regression guard for the profile -> DOMWatchdog -> DomService wiring."""
	source = inspect.getsource(DOMWatchdog._build_dom_tree_without_highlights)
	assert 'dom_build_timeout=self.browser_session.browser_profile.dom_build_timeout' in source
	assert 'dom_build_retry_timeout=self.browser_session.browser_profile.dom_build_retry_timeout' in source
