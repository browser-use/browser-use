"""Tests for local browser executable discovery."""

from pathlib import Path

from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


def test_default_channel_prefers_playwright_chromium(monkeypatch, tmp_path: Path):
	"""Test default discovery returns bundled Chromium before other fallbacks."""
	monkeypatch.setattr('platform.system', lambda: 'Darwin')
	monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path))

	bundled_chromium = tmp_path / 'chromium-123' / 'chrome-mac' / 'Chromium.app' / 'Contents' / 'MacOS' / 'Chromium'
	bundled_chromium.parent.mkdir(parents=True)
	bundled_chromium.touch()

	assert LocalBrowserWatchdog._find_installed_browser_path() == str(bundled_chromium)
