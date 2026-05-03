"""Tests for configurable download timeout (issue #3168)."""

from browser_use.browser import BrowserProfile, BrowserSession


def test_download_timeout_default():
	"""Default download_timeout should be 30.0 seconds."""
	profile = BrowserProfile()
	assert profile.download_timeout == 30.0


def test_download_timeout_custom():
	"""Custom download_timeout should be stored in profile."""
	profile = BrowserProfile(download_timeout=120.0)
	assert profile.download_timeout == 120.0


def test_download_timeout_passthrough_via_session():
	"""download_timeout passed to BrowserSession should propagate to BrowserProfile."""
	session = BrowserSession(download_timeout=60.0)
	assert session.browser_profile.download_timeout == 60.0


def test_download_timeout_session_default():
	"""BrowserSession without download_timeout should use BrowserProfile default."""
	session = BrowserSession()
	assert session.browser_profile.download_timeout == 30.0


def test_download_timeout_profile_on_session():
	"""BrowserSession with explicit BrowserProfile should use profile's download_timeout."""
	profile = BrowserProfile(download_timeout=90.0)
	session = BrowserSession(browser_profile=profile)
	assert session.browser_profile.download_timeout == 90.0
