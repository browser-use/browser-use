"""Tests for realistic typing speed configuration."""

import os
from unittest.mock import MagicMock

from browser_use.browser.profile import BrowserProfile


class TestTypingSpeedConfig:
	"""Test typing speed configuration in BrowserProfile."""

	def test_default_typing_delays(self):
		"""Default BrowserProfile should have fast typing delays (1ms-10ms)."""
		profile = BrowserProfile()
		assert profile.typing_delay_min == 0.001
		assert profile.typing_delay_max == 0.010

	def test_explicit_typing_delays(self):
		"""User should be able to set custom typing delays."""
		profile = BrowserProfile(typing_delay_min=0.05, typing_delay_max=0.2)
		assert profile.typing_delay_min == 0.05
		assert profile.typing_delay_max == 0.2

	def test_realistic_typing_env_var_enabled(self):
		"""BROWSER_USE_REALISTIC_TYPING=true should set realistic delays."""
		original = os.environ.get('BROWSER_USE_REALISTIC_TYPING', '')
		try:
			os.environ['BROWSER_USE_REALISTIC_TYPING'] = 'true'
			profile = BrowserProfile()
			assert profile.typing_delay_min == 0.05
			assert profile.typing_delay_max == 0.15
		finally:
			if original:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = original
			else:
				os.environ.pop('BROWSER_USE_REALISTIC_TYPING', None)

	def test_realistic_typing_env_var_values(self):
		"""Various truthy env var values should all enable realistic typing."""
		original = os.environ.get('BROWSER_USE_REALISTIC_TYPING', '')
		try:
			for value in ['true', '1', 'yes', 'on', 'True', 'YES', 'ON']:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = value
				profile = BrowserProfile()
				assert profile.typing_delay_min == 0.05, f'Failed for BROWSER_USE_REALISTIC_TYPING={value}'
				assert profile.typing_delay_max == 0.15, f'Failed for BROWSER_USE_REALISTIC_TYPING={value}'
		finally:
			if original:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = original
			else:
				os.environ.pop('BROWSER_USE_REALISTIC_TYPING', None)

	def test_realistic_typing_env_var_does_not_override_explicit(self):
		"""Env var should NOT override explicitly set typing delays."""
		original = os.environ.get('BROWSER_USE_REALISTIC_TYPING', '')
		try:
			os.environ['BROWSER_USE_REALISTIC_TYPING'] = 'true'
			profile = BrowserProfile(typing_delay_min=0.02, typing_delay_max=0.03)
			# Should keep explicit values, not override to 0.05/0.15
			assert profile.typing_delay_min == 0.02
			assert profile.typing_delay_max == 0.03
		finally:
			if original:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = original
			else:
				os.environ.pop('BROWSER_USE_REALISTIC_TYPING', None)

	def test_realistic_typing_env_var_disabled(self):
		"""When env var is not set or falsy, defaults should remain fast."""
		original = os.environ.get('BROWSER_USE_REALISTIC_TYPING', '')
		try:
			os.environ.pop('BROWSER_USE_REALISTIC_TYPING', None)
			profile = BrowserProfile()
			assert profile.typing_delay_min == 0.001
			assert profile.typing_delay_max == 0.010

			for value in ['false', '0', 'no', 'off', '']:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = value
				profile = BrowserProfile()
				assert profile.typing_delay_min == 0.001, f'Failed for BROWSER_USE_REALISTIC_TYPING={value!r}'
				assert profile.typing_delay_max == 0.010, f'Failed for BROWSER_USE_REALISTIC_TYPING={value!r}'
		finally:
			if original:
				os.environ['BROWSER_USE_REALISTIC_TYPING'] = original
			else:
				os.environ.pop('BROWSER_USE_REALISTIC_TYPING', None)


class TestSampleTypingDelay:
	"""Test the _sample_typing_delay method on DefaultActionWatchdog."""

	def _make_watchdog(self, min_d: float = 0.001, max_d: float = 0.010):
		"""Create a mock watchdog with given typing delays."""
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

		mock_session = MagicMock()
		mock_session.browser_profile.typing_delay_min = min_d
		mock_session.browser_profile.typing_delay_max = max_d

		watchdog = DefaultActionWatchdog.__new__(DefaultActionWatchdog)
		object.__setattr__(watchdog, 'browser_session', mock_session)
		return watchdog

	def test_fast_mode_returns_in_range(self):
		"""In fast mode (small range), delay should be within min/max."""
		watchdog = self._make_watchdog(0.001, 0.010)
		for _ in range(100):
			delay = watchdog._sample_typing_delay()
			assert 0.001 <= delay <= 0.010, f'Delay {delay} out of range [0.001, 0.010]'

	def test_realistic_mode_returns_reasonable(self):
		"""In realistic mode, delay should be within extended range."""
		watchdog = self._make_watchdog(0.05, 0.15)
		for _ in range(200):
			delay = watchdog._sample_typing_delay()
			assert 0.05 <= delay <= 0.15 * 3.3, f'Delay {delay} out of range [0.05, {0.15 * 3.3}]'

	def test_realistic_mode_mean_is_reasonable(self):
		"""In realistic mode, the mean delay should be close to expected range."""
		watchdog = self._make_watchdog(0.05, 0.15)
		delays = [watchdog._sample_typing_delay() for _ in range(1000)]
		mean_delay = sum(delays) / len(delays)
		# Mean should be roughly in the 50-200ms range
		assert 0.04 < mean_delay < 0.25, f'Mean delay {mean_delay} seems unreasonable'
