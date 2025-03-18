

import pytest

from browser_use.browser.context import BrowserContextConfig

from browser_use.browser.context import BrowserContextConfig, BrowserContext

class TestBrowserContextConfig:
	def test_default_values(self):
		# Arrange
		config = BrowserContextConfig()
		# Act
		# Assert
		assert config.cookies_file is None
		assert config.minimum_wait_page_load_time == 0.25
		assert config.wait_for_network_idle_page_load_time == 0.5
		assert config.maximum_wait_page_load_time == 5
		assert config.wait_between_actions == 0.5
		assert config.disable_security is True
		assert config.browser_window_size['width'] == 1280
		assert config.browser_window_size['height'] == 1100
		assert config.no_viewport is None
		assert config.save_recording_path is None
		assert config.save_downloads_path is None
		assert config.trace_path is None
		assert config.locale is None
		assert config.user_agent == 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
		assert config.highlight_elements is True
		assert config.viewport_expansion == 500
		assert config.allowed_domains is None
		assert config.include_dynamic_attributes is True

class TestBrowserContextConfig:
	async def test_set_custom_user_agent(self):
		# Arrange
		custom_user_agent = 'CustomUserAgent/1.0'
		config = BrowserContextConfig(user_agent=custom_user_agent)
		# Act
		browser_context = BrowserContext(browser=None, config=config)
		await browser_context.__aenter__()
		# Assert
		assert browser_context.config.user_agent == custom_user_agent
		await browser_context.__aexit__(None, None, None)

class TestBrowserContextConfig:
	async def test_valid_allowed_domains(self):
		# Arrange
		allowed_domains = ['example.com', 'api.example.com']
		config = BrowserContextConfig(allowed_domains=allowed_domains)
		# Act
		result = config.allowed_domains
		# Assert
		assert result == allowed_domains

class TestBrowserContextConfig:
	def test_default_values(self):
		# Arrange
		config = BrowserContextConfig()
		# Act
		default_values = {
			'cookies_file': None,
			'minimum_wait_page_load_time': 0.25,
			'wait_for_network_idle_page_load_time': 0.5,
			'maximum_wait_page_load_time': 5,
			'wait_between_actions': 0.5,
			'disable_security': True,
			'browser_window_size': {'width': 1280, 'height': 1100},
			'no_viewport': None,
			'save_recording_path': None,
			'save_downloads_path': None,
			'trace_path': None,
			'locale': None,
			'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
			'highlight_elements': True,
			'viewport_expansion': 500,
			'allowed_domains': None,
			'include_dynamic_attributes': True
		}
		# Assert
		for key, value in default_values.items():
			assert getattr(config, key) == value

class TestBrowserContextConfig:
	def test_set_custom_cookies_file_path(self):
		# Arrange
		custom_cookies_path = 'path/to/cookies.json'
		config = BrowserContextConfig(cookies_file=custom_cookies_path)
		# Act
		set_cookies_file_path = config.cookies_file
		# Assert
		assert set_cookies_file_path == custom_cookies_path

class TestBrowserContextConfig:
	def test_valid_browser_window_size(self):
		# Arrange
		config = BrowserContextConfig(browser_window_size={'width': 1920, 'height': 1080})
		# Act
		window_size = config.browser_window_size
		# Assert
		assert window_size['width'] == 1920
		assert window_size['height'] == 1080

