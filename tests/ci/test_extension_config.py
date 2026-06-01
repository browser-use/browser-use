"""Tests for extension configuration environment variables."""

import os

import pytest


class TestDisableExtensionsEnvVar:
	"""Test BROWSER_USE_DISABLE_EXTENSIONS environment variable."""

	def test_default_value_is_true(self):
		"""Without env var set, enable_default_extensions should default to True."""
		# Clear the env var if it exists
		original = os.environ.pop('BROWSER_USE_DISABLE_EXTENSIONS', None)
		try:
			# Import fresh to get the default
			from browser_use.browser.profile import _get_enable_default_extensions_default

			assert _get_enable_default_extensions_default() is True
		finally:
			if original is not None:
				os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = original

	@pytest.mark.parametrize(
		'env_value,expected_enabled',
		[
			# Truthy values for DISABLE = extensions disabled (False)
			('true', False),
			('True', False),
			('TRUE', False),
			('1', False),
			('yes', False),
			('on', False),
			# Falsy values for DISABLE = extensions enabled (True)
			('false', True),
			('False', True),
			('FALSE', True),
			('0', True),
			('no', True),
			('off', True),
			('', True),
		],
	)
	def test_env_var_values(self, env_value: str, expected_enabled: bool):
		"""Test various env var values are parsed correctly."""
		original = os.environ.get('BROWSER_USE_DISABLE_EXTENSIONS')
		try:
			os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = env_value
			from browser_use.browser.profile import _get_enable_default_extensions_default

			result = _get_enable_default_extensions_default()
			assert result is expected_enabled, (
				f"Expected enable_default_extensions={expected_enabled} for DISABLE_EXTENSIONS='{env_value}', got {result}"
			)
		finally:
			if original is not None:
				os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = original
			else:
				os.environ.pop('BROWSER_USE_DISABLE_EXTENSIONS', None)

	def test_browser_profile_uses_env_var(self):
		"""Test that BrowserProfile picks up the env var."""
		original = os.environ.get('BROWSER_USE_DISABLE_EXTENSIONS')
		try:
			# Test with env var set to true (disable extensions)
			os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = 'true'

			from browser_use.browser.profile import BrowserProfile

			profile = BrowserProfile(headless=True)
			assert profile.enable_default_extensions is False, (
				'BrowserProfile should disable extensions when BROWSER_USE_DISABLE_EXTENSIONS=true'
			)

			# Test with env var set to false (enable extensions)
			os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = 'false'
			profile2 = BrowserProfile(headless=True)
			assert profile2.enable_default_extensions is True, (
				'BrowserProfile should enable extensions when BROWSER_USE_DISABLE_EXTENSIONS=false'
			)

		finally:
			if original is not None:
				os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = original
			else:
				os.environ.pop('BROWSER_USE_DISABLE_EXTENSIONS', None)

	def test_explicit_param_overrides_env_var(self):
		"""Test that explicit enable_default_extensions parameter overrides env var."""
		original = os.environ.get('BROWSER_USE_DISABLE_EXTENSIONS')
		try:
			os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = 'true'

			from browser_use.browser.profile import BrowserProfile

			# Explicitly set to True should override env var
			profile = BrowserProfile(headless=True, enable_default_extensions=True)
			assert profile.enable_default_extensions is True, 'Explicit param should override env var'

		finally:
			if original is not None:
				os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = original
			else:
				os.environ.pop('BROWSER_USE_DISABLE_EXTENSIONS', None)

	def test_browser_session_uses_env_var(self):
		"""Test that BrowserSession picks up the env var via BrowserProfile."""
		original = os.environ.get('BROWSER_USE_DISABLE_EXTENSIONS')
		try:
			os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = '1'

			from browser_use.browser import BrowserSession

			session = BrowserSession(headless=True)
			assert session.browser_profile.enable_default_extensions is False, (
				'BrowserSession should disable extensions when BROWSER_USE_DISABLE_EXTENSIONS=1'
			)

		finally:
			if original is not None:
				os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = original
			else:
				os.environ.pop('BROWSER_USE_DISABLE_EXTENSIONS', None)
