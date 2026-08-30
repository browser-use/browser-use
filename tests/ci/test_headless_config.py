"""Tests for the BROWSER_USE_HEADLESS environment variable (see issue #5420).

Mirrors tests/ci/test_extension_config.py's pattern for BROWSER_USE_DISABLE_EXTENSIONS.
"""

import os

import pytest


class TestHeadlessEnvVar:
	"""Test BROWSER_USE_HEADLESS environment variable."""

	def test_default_value_is_none(self):
		"""Without env var set, _get_headless_default should return None (fall back to display detection)."""
		original = os.environ.pop('BROWSER_USE_HEADLESS', None)
		try:
			from browser_use.browser.profile import _get_headless_default

			assert _get_headless_default() is None
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original

	@pytest.mark.parametrize(
		'env_value,expected_headless',
		[
			('true', True),
			('True', True),
			('TRUE', True),
			('1', True),
			('yes', True),
			('on', True),
			('false', False),
			('False', False),
			('FALSE', False),
			('0', False),
			('no', False),
			('off', False),
			('', False),
		],
	)
	def test_env_var_values(self, env_value: str, expected_headless: bool):
		"""Test various env var values are parsed correctly."""
		original = os.environ.get('BROWSER_USE_HEADLESS')
		try:
			os.environ['BROWSER_USE_HEADLESS'] = env_value
			from browser_use.browser.profile import _get_headless_default

			result = _get_headless_default()
			assert result is expected_headless, (
				f"Expected headless={expected_headless} for BROWSER_USE_HEADLESS='{env_value}', got {result}"
			)
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
			else:
				os.environ.pop('BROWSER_USE_HEADLESS', None)

	def test_browser_profile_uses_env_var(self):
		"""Test that BrowserProfile picks up the env var."""
		original = os.environ.get('BROWSER_USE_HEADLESS')
		try:
			os.environ['BROWSER_USE_HEADLESS'] = 'true'

			from browser_use.browser.profile import BrowserProfile

			profile = BrowserProfile()
			assert profile.headless is True, 'BrowserProfile should be headless when BROWSER_USE_HEADLESS=true'

			os.environ['BROWSER_USE_HEADLESS'] = 'false'
			profile2 = BrowserProfile()
			assert profile2.headless is False, 'BrowserProfile should be headful when BROWSER_USE_HEADLESS=false'
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
			else:
				os.environ.pop('BROWSER_USE_HEADLESS', None)

	def test_explicit_param_overrides_env_var(self):
		"""Test that an explicit headless= parameter overrides the env var."""
		original = os.environ.get('BROWSER_USE_HEADLESS')
		try:
			os.environ['BROWSER_USE_HEADLESS'] = 'true'

			from browser_use.browser.profile import BrowserProfile

			profile = BrowserProfile(headless=False)
			assert profile.headless is False, 'Explicit headless=False should override BROWSER_USE_HEADLESS=true'
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
			else:
				os.environ.pop('BROWSER_USE_HEADLESS', None)

	def test_browser_session_uses_env_var(self):
		"""Test that BrowserSession picks up the env var via BrowserProfile.

		BrowserSession.__init__ filters None values out of the kwargs it forwards to BrowserProfile,
		so an unpassed headless= must still reach the field's default_factory rather than being
		overridden with an explicit None - this is a distinct code path from BrowserProfile() directly.
		"""
		original = os.environ.get('BROWSER_USE_HEADLESS')
		try:
			os.environ['BROWSER_USE_HEADLESS'] = 'true'

			from browser_use.browser import BrowserSession

			session = BrowserSession()
			assert session.browser_profile.headless is True, 'BrowserSession should be headless when BROWSER_USE_HEADLESS=true'

			session2 = BrowserSession(headless=False)
			assert session2.browser_profile.headless is False, 'Explicit headless=False should override the env var'
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
			else:
				os.environ.pop('BROWSER_USE_HEADLESS', None)

	def test_env_var_headless_yields_to_explicit_devtools(self):
		"""Regression test: BROWSER_USE_HEADLESS=true must not make BrowserProfile(devtools=True) raise.

		default_factory populates the headless field before validate_devtools_headless (mode='after')
		runs, so a naive implementation would turn a previously-valid BrowserProfile(devtools=True) call
		into an AssertionError as soon as the env var is set. devtools takes priority: headless is forced
		back to False instead of raising, since the caller never wrote headless=True themselves.
		"""
		original = os.environ.get('BROWSER_USE_HEADLESS')
		try:
			os.environ['BROWSER_USE_HEADLESS'] = 'true'

			from browser_use.browser.profile import BrowserProfile

			profile = BrowserProfile(devtools=True)
			assert profile.headless is False
			assert profile.devtools is True
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
			else:
				os.environ.pop('BROWSER_USE_HEADLESS', None)

	def test_explicit_headless_true_still_conflicts_with_devtools(self):
		"""An explicit headless=True (not from the env var) must still raise with devtools=True, unchanged."""
		original = os.environ.pop('BROWSER_USE_HEADLESS', None)
		try:
			from pydantic import ValidationError

			from browser_use.browser.profile import BrowserProfile

			with pytest.raises(ValidationError, match='headless=True and devtools=True cannot both be set'):
				BrowserProfile(headless=True, devtools=True)
		finally:
			if original is not None:
				os.environ['BROWSER_USE_HEADLESS'] = original
