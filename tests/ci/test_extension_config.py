"""Tests for browser configuration environment variables."""

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.profile import (
	BrowserProfile,
	_get_enable_default_extensions_default,
	_get_headless_default,
)

TRUTHY_STRINGS = ['true', 'True', 'TRUE', '1', 'yes', 'on']
FALSY_STRINGS = ['false', 'False', 'FALSE', '0', 'no', 'off', '']


class TestConfigEnvVars:
	"""Tests for browser profile env var configuration."""

	def test_default_values_without_env(self, monkeypatch: pytest.MonkeyPatch):
		"""Verify default values when environment variables are unset."""
		monkeypatch.delenv('BROWSER_USE_DISABLE_EXTENSIONS', raising=False)
		monkeypatch.delenv('BROWSER_USE_HEADLESS', raising=False)

		assert _get_enable_default_extensions_default() is True
		assert _get_headless_default() is None

	@pytest.mark.parametrize(
		'env_var,getter,expected',
		[
			('BROWSER_USE_DISABLE_EXTENSIONS', _get_enable_default_extensions_default, False),
			('BROWSER_USE_HEADLESS', _get_headless_default, True),
		],
	)
	def test_env_var_truthy_values(
		self,
		monkeypatch: pytest.MonkeyPatch,
		env_var: str,
		getter,
		expected: bool,
	):
		"""Test truthy env var values are parsed correctly."""
		for val in TRUTHY_STRINGS:
			monkeypatch.setenv(env_var, val)
			assert getter() is expected, f'Failed for {env_var}={val}'

	@pytest.mark.parametrize(
		'env_var,getter,expected',
		[
			('BROWSER_USE_DISABLE_EXTENSIONS', _get_enable_default_extensions_default, True),
			('BROWSER_USE_HEADLESS', _get_headless_default, False),
		],
	)
	def test_env_var_falsy_values(
		self,
		monkeypatch: pytest.MonkeyPatch,
		env_var: str,
		getter,
		expected: bool,
	):
		"""Test falsy env var values are parsed correctly."""
		for val in FALSY_STRINGS:
			monkeypatch.setenv(env_var, val)
			assert getter() is expected, f'Failed for {env_var}={val}'

	@pytest.mark.parametrize(
		'env_var,attr_name,truthy_val,falsy_val',
		[
			('BROWSER_USE_DISABLE_EXTENSIONS', 'enable_default_extensions', False, True),
			('BROWSER_USE_HEADLESS', 'headless', True, False),
		],
	)
	def test_browser_profile_and_session_env_var(
		self,
		monkeypatch: pytest.MonkeyPatch,
		env_var: str,
		attr_name: str,
		truthy_val: bool,
		falsy_val: bool,
	):
		"""Test that BrowserProfile and BrowserSession pick up env vars."""
		# Test truthy env value
		monkeypatch.setenv(env_var, 'true')
		profile = BrowserProfile()
		assert getattr(profile, attr_name) is truthy_val
		session = BrowserSession()
		assert getattr(session.browser_profile, attr_name) is truthy_val

		# Test falsy env value
		monkeypatch.setenv(env_var, 'false')
		profile_falsy = BrowserProfile()
		assert getattr(profile_falsy, attr_name) is falsy_val
		session_falsy = BrowserSession()
		assert getattr(session_falsy.browser_profile, attr_name) is falsy_val

	@pytest.mark.parametrize(
		'env_var,attr_name,env_val,explicit_arg,expected',
		[
			('BROWSER_USE_DISABLE_EXTENSIONS', 'enable_default_extensions', 'true', {'enable_default_extensions': True}, True),
			('BROWSER_USE_DISABLE_EXTENSIONS', 'enable_default_extensions', 'false', {'enable_default_extensions': False}, False),
			('BROWSER_USE_HEADLESS', 'headless', 'true', {'headless': False}, False),
			('BROWSER_USE_HEADLESS', 'headless', 'false', {'headless': True}, True),
		],
	)
	def test_explicit_parameter_overrides_env_var(
		self,
		monkeypatch: pytest.MonkeyPatch,
		env_var: str,
		attr_name: str,
		env_val: str,
		explicit_arg: dict,
		expected: bool,
	):
		"""Test that explicit constructor parameters override env vars."""
		monkeypatch.setenv(env_var, env_val)
		profile = BrowserProfile(**explicit_arg)
		assert getattr(profile, attr_name) is expected
