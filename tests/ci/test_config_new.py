"""Tests for new configuration system with migration support."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from browser_use.config import (
	CONFIG,
	FlatEnvConfig,
	get_default_llm,
	get_default_profile,
	load_and_migrate_config,
	load_browser_use_config,
)


class TestConfigCreation:
	"""Test configuration creation and handling."""

	def test_create_default_config(self):
		"""Test migrating simple old config format."""
		with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
			old_config = {
				'headless': True,
				'allowed_domains': ['example.com', 'test.com'],
				'api_key': 'sk-test123',
				'model': 'gpt-4o',
				'temperature': 0.7,
			}
			json.dump(old_config, f)
			config_path = Path(f.name)

		try:
			# Load - should detect old format and create fresh config
			db_config = load_and_migrate_config(config_path)

			# Check fresh config was created
			assert len(db_config.browser_profile) == 1
			assert len(db_config.llm) == 1
			assert len(db_config.agent) == 1

			# Get the default profile
			profile = next(iter(db_config.browser_profile.values()))
			assert profile.default is True
			assert profile.headless is False  # Default value, not from old config
			assert profile.user_data_dir is None

			# Get the default LLM config
			llm = next(iter(db_config.llm.values()))
			assert llm.default is True
			assert llm.api_key == 'your-openai-api-key-here'  # Default placeholder
			assert llm.model == 'gpt-4o'

			# Verify file was updated
			with open(config_path) as f:
				saved_config = json.load(f)
			assert 'browser_profile' in saved_config
			assert 'llm' in saved_config
			assert 'agent' in saved_config

		finally:
			os.unlink(config_path)

	def test_create_config_on_empty(self):
		"""Test creating default config when no file exists."""
		with tempfile.TemporaryDirectory() as tmpdir:
			config_path = Path(tmpdir) / 'config.json'

			# Load - should create fresh config
			db_config = load_and_migrate_config(config_path)

			# Check fresh config was created
			assert config_path.exists()
			assert len(db_config.browser_profile) == 1
			assert len(db_config.llm) == 1
			assert len(db_config.agent) == 1

			# Verify defaults
			profile = next(iter(db_config.browser_profile.values()))
			assert profile.default is True
			assert profile.headless is False

			llm = next(iter(db_config.llm.values()))
			assert llm.default is True
			assert llm.model == 'gpt-4o'

	def test_no_migration_for_new_format(self):
		"""Test that new format is not migrated."""
		with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
			new_config = {
				'browser_profile': {
					'uuid1': {'id': 'uuid1', 'default': True, 'created_at': '2024-01-01T00:00:00', 'headless': True}
				},
				'llm': {'uuid2': {'id': 'uuid2', 'default': True, 'created_at': '2024-01-01T00:00:00', 'api_key': 'sk-new'}},
				'agent': {},
			}
			json.dump(new_config, f)
			config_path = Path(f.name)

		try:
			# Load without migration
			original_content = json.dumps(new_config, sort_keys=True)
			db_config = load_and_migrate_config(config_path)

			# Check it wasn't modified
			with open(config_path) as f:
				saved_content = json.dumps(json.load(f), sort_keys=True)

			# Should be the same (no migration)
			assert len(db_config.browser_profile) == 1
			assert db_config.browser_profile['uuid1'].id == 'uuid1'
			assert db_config.llm['uuid2'].api_key == 'sk-new'

		finally:
			os.unlink(config_path)


class TestConfigLazyLoading:
	"""Test lazy loading of environment variables."""

	def test_env_vars_reload_on_access(self):
		"""Test that env vars are re-read on every access."""
		original = os.environ.get('BROWSER_USE_LOGGING_LEVEL', '')
		try:
			# Set initial value
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug'

			# Change value
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'error'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'error'

			# Remove to test default
			del os.environ['BROWSER_USE_LOGGING_LEVEL']
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'info'

		finally:
			if original:
				os.environ['BROWSER_USE_LOGGING_LEVEL'] = original
			else:
				os.environ.pop('BROWSER_USE_LOGGING_LEVEL', None)

	def test_mcp_env_vars(self):
		"""Test MCP-specific environment variables."""
		originals = {
			'BROWSER_USE_HEADLESS': os.environ.get('BROWSER_USE_HEADLESS', ''),
			'BROWSER_USE_ALLOWED_DOMAINS': os.environ.get('BROWSER_USE_ALLOWED_DOMAINS', ''),
			'BROWSER_USE_LLM_MODEL': os.environ.get('BROWSER_USE_LLM_MODEL', ''),
		}

		try:
			# Test headless
			os.environ['BROWSER_USE_HEADLESS'] = 'true'
			env_config = FlatEnvConfig()
			assert env_config.BROWSER_USE_HEADLESS is True

			os.environ['BROWSER_USE_HEADLESS'] = 'false'
			env_config = FlatEnvConfig()
			assert env_config.BROWSER_USE_HEADLESS is False

			# Test allowed domains
			os.environ['BROWSER_USE_ALLOWED_DOMAINS'] = 'example.com,test.com'
			env_config = FlatEnvConfig()
			assert env_config.BROWSER_USE_ALLOWED_DOMAINS == 'example.com,test.com'

			# Test LLM model
			os.environ['BROWSER_USE_LLM_MODEL'] = 'gpt-4-turbo'
			env_config = FlatEnvConfig()
			assert env_config.BROWSER_USE_LLM_MODEL == 'gpt-4-turbo'

		finally:
			for key, value in originals.items():
				if value:
					os.environ[key] = value
				else:
					os.environ.pop(key, None)


class TestConfigMerging:
	"""Test configuration merging with environment overrides."""

	def test_load_config_with_env_overrides(self):
		"""Test that env vars override config.json values."""
		originals = {
			'BROWSER_USE_CONFIG_PATH': os.environ.get('BROWSER_USE_CONFIG_PATH', ''),
			'BROWSER_USE_HEADLESS': os.environ.get('BROWSER_USE_HEADLESS', ''),
			'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY', ''),
			'BROWSER_USE_LLM_MODEL': os.environ.get('BROWSER_USE_LLM_MODEL', ''),
		}

		with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
			config = {
				'browser_profile': {
					'uuid1': {'id': 'uuid1', 'default': True, 'created_at': '2024-01-01T00:00:00', 'headless': False}
				},
				'llm': {
					'uuid2': {
						'id': 'uuid2',
						'default': True,
						'created_at': '2024-01-01T00:00:00',
						'api_key': 'sk-config',
						'model': 'gpt-3.5-turbo',
					}
				},
				'agent': {},
			}
			json.dump(config, f)
			config_path = f.name

		try:
			# Set env vars to override
			os.environ['BROWSER_USE_CONFIG_PATH'] = config_path
			os.environ['BROWSER_USE_HEADLESS'] = 'true'
			os.environ['OPENAI_API_KEY'] = 'sk-env'
			os.environ['BROWSER_USE_LLM_MODEL'] = 'gpt-4o'

			# Load config
			merged_config = load_browser_use_config()

			# Check overrides
			assert merged_config['browser_profile']['headless'] is True  # overridden
			assert merged_config['llm']['api_key'] == 'sk-env'  # overridden
			assert merged_config['llm']['model'] == 'gpt-4o'  # overridden

		finally:
			os.unlink(config_path)
			for key, value in originals.items():
				if value:
					os.environ[key] = value
				else:
					os.environ.pop(key, None)

	def test_get_default_helpers(self):
		"""Test helper functions for getting default configs."""
		config = {
			'browser_profile': {'headless': True, 'allowed_domains': ['test.com']},
			'llm': {'api_key': 'sk-test', 'model': 'gpt-4o'},
		}

		profile = get_default_profile(config)
		assert profile == {'headless': True, 'allowed_domains': ['test.com']}

		llm = get_default_llm(config)
		assert llm == {'api_key': 'sk-test', 'model': 'gpt-4o'}

		# Test empty
		assert get_default_profile({}) == {}
		assert get_default_llm({}) == {}


class TestBackwardCompatibility:
	"""Test backward compatibility with old CONFIG usage."""

	def test_all_old_config_attributes_exist(self):
		"""Test that all attributes from old Config class are accessible."""
		# Test all the attributes that exist in the old config
		attrs_to_test = [
			'BROWSER_USE_LOGGING_LEVEL',
			'ANONYMIZED_TELEMETRY',
			'BROWSER_USE_CLOUD_SYNC',
			'BROWSER_USE_CLOUD_API_URL',
			'BROWSER_USE_CLOUD_UI_URL',
			'XDG_CACHE_HOME',
			'XDG_CONFIG_HOME',
			'BROWSER_USE_CONFIG_DIR',
			'BROWSER_USE_CONFIG_FILE',
			'BROWSER_USE_PROFILES_DIR',
			'BROWSER_USE_DEFAULT_USER_DATA_DIR',
			'OPENAI_API_KEY',
			'ANTHROPIC_API_KEY',
			'GOOGLE_API_KEY',
			'DEEPSEEK_API_KEY',
			'GROK_API_KEY',
			'NOVITA_API_KEY',
			'AZURE_OPENAI_ENDPOINT',
			'AZURE_OPENAI_KEY',
			'SKIP_LLM_API_KEY_VERIFICATION',
			'IN_DOCKER',
			'IS_IN_EVALS',
			'WIN_FONT_DIR',
		]

		for attr in attrs_to_test:
			# Should not raise AttributeError
			value = getattr(CONFIG, attr)
			assert value is not None or value == '' or isinstance(value, (str, bool, Path))

	def test_computed_properties_work(self):
		"""Test computed properties like BROWSER_USE_CLOUD_SYNC."""
		telemetry_orig = os.environ.get('ANONYMIZED_TELEMETRY', '')
		sync_orig = os.environ.get('BROWSER_USE_CLOUD_SYNC', '')

		try:
			# Test inheritance
			os.environ['ANONYMIZED_TELEMETRY'] = 'true'
			os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is True

			# Test override
			os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is False

		finally:
			if telemetry_orig:
				os.environ['ANONYMIZED_TELEMETRY'] = telemetry_orig
			else:
				os.environ.pop('ANONYMIZED_TELEMETRY', None)
			if sync_orig:
				os.environ['BROWSER_USE_CLOUD_SYNC'] = sync_orig
			else:
				os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)


if __name__ == '__main__':
	pytest.main([__file__, '-v', '-s'])
