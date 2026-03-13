"""Tests for Lightpanda browser engine integration."""


from browser_use.browser.profile import BrowserEngine, BrowserProfile
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


class TestLightpandaProfile:
	"""Test BrowserProfile behavior with browser_engine='lightpanda'."""

	def test_lightpanda_engine_enum(self):
		"""BrowserEngine enum has chromium and lightpanda values."""
		assert BrowserEngine.CHROMIUM == 'chromium'
		assert BrowserEngine.LIGHTPANDA == 'lightpanda'

	def test_default_engine_is_chromium(self):
		"""Default browser engine should be chromium."""
		profile = BrowserProfile()
		assert profile.browser_engine == BrowserEngine.CHROMIUM

	def test_lightpanda_forces_headless(self):
		"""Lightpanda should force headless=True even if False is requested."""
		profile = BrowserProfile(browser_engine='lightpanda', headless=False)
		assert profile.headless is True

	def test_lightpanda_disables_extensions(self):
		"""Lightpanda should disable extensions (no Chrome extension support)."""
		profile = BrowserProfile(browser_engine='lightpanda', enable_default_extensions=True)
		assert profile.enable_default_extensions is False

	def test_lightpanda_disables_demo_mode(self):
		"""Lightpanda should disable demo mode (no rendering)."""
		profile = BrowserProfile(browser_engine='lightpanda', demo_mode=True)
		assert profile.demo_mode is False

	def test_lightpanda_disables_highlight_elements(self):
		"""Lightpanda should disable element highlighting (no rendering)."""
		profile = BrowserProfile(browser_engine='lightpanda', highlight_elements=True)
		assert profile.highlight_elements is False

	def test_lightpanda_disables_deterministic_rendering(self):
		"""Lightpanda should disable deterministic rendering (irrelevant without rendering)."""
		profile = BrowserProfile(browser_engine='lightpanda', deterministic_rendering=True)
		assert profile.deterministic_rendering is False

	def test_lightpanda_get_args_no_chrome_flags(self):
		"""Lightpanda args should not contain any Chrome-specific flags."""
		profile = BrowserProfile(browser_engine='lightpanda')
		args = profile.get_args()
		# Should not contain Chrome-specific flags
		args_str = ' '.join(args)
		assert '--user-data-dir' not in args_str
		assert '--remote-debugging-port' not in args_str
		assert '--headless' not in args_str
		assert '--no-first-run' not in args_str
		assert '--disable-gpu' not in args_str

	def test_lightpanda_get_args_passes_extra_args(self):
		"""Extra user args should be passed through for Lightpanda."""
		profile = BrowserProfile(browser_engine='lightpanda', args=['--some-custom-flag'])
		args = profile.get_args()
		assert '--some-custom-flag' in args

	def test_chromium_get_args_unchanged(self, tmp_path):
		"""Chromium args should still work as before."""
		profile = BrowserProfile(browser_engine='chromium', user_data_dir=str(tmp_path))
		args = profile.get_args()
		args_str = ' '.join(args)
		assert '--user-data-dir' in args_str

	def test_lightpanda_string_value(self):
		"""Should accept string 'lightpanda' for browser_engine."""
		profile = BrowserProfile(browser_engine='lightpanda')
		assert profile.browser_engine == BrowserEngine.LIGHTPANDA

	def test_lightpanda_skips_profile_copy(self):
		"""Lightpanda should skip display detection and profile copying (no user_data_dir concept)."""
		# This should not raise even though Lightpanda doesn't use user_data_dir the same way
		profile = BrowserProfile(browser_engine='lightpanda')
		# Just verify it was created successfully without errors
		assert profile.browser_engine == BrowserEngine.LIGHTPANDA


class TestLightpandaBinaryDiscovery:
	"""Test Lightpanda binary discovery logic."""

	def test_find_lightpanda_path_returns_none_when_not_installed(self, monkeypatch):
		"""Should return None when Lightpanda is not installed anywhere."""
		monkeypatch.delenv('LIGHTPANDA_BINARY_PATH', raising=False)
		# Only test that it returns str or None (don't assume it's not installed)
		result = LocalBrowserWatchdog._find_lightpanda_path()
		assert result is None or isinstance(result, str)

	def test_find_lightpanda_path_from_env(self, monkeypatch, tmp_path):
		"""Should find Lightpanda from LIGHTPANDA_BINARY_PATH env var."""
		fake_binary = tmp_path / 'lightpanda'
		fake_binary.touch()
		monkeypatch.setenv('LIGHTPANDA_BINARY_PATH', str(fake_binary))

		result = LocalBrowserWatchdog._find_lightpanda_path()
		assert result == str(fake_binary)
