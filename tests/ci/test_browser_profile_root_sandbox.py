import os
import sys

from browser_use.browser import BrowserProfile


def test_browser_profile_disables_sandbox_for_root_on_linux(monkeypatch):
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(os, 'geteuid', lambda: 0)

	profile = BrowserProfile(headless=True, chromium_sandbox=True)

	assert profile.chromium_sandbox is False


def test_browser_profile_keeps_sandbox_for_non_root(monkeypatch):
	monkeypatch.setattr(sys, 'platform', 'linux')
	monkeypatch.setattr(os, 'geteuid', lambda: 1000)

	profile = BrowserProfile(headless=True, chromium_sandbox=True)

	assert profile.chromium_sandbox is True
