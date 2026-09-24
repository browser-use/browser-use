"""Tests for lazy loading configuration system."""

import json
import os
from pathlib import Path

from browser_use.config import CONFIG, load_and_migrate_config


class TestLazyConfig:
	"""Test lazy loading of environment variables through CONFIG object."""

	def test_config_reads_env_vars_lazily(self):
		"""Test that CONFIG reads environment variables each time they're accessed."""
		# Set an env var
		original_value = os.environ.get('BROWSER_USE_LOGGING_LEVEL', '')
		try:
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'debug'

			# Change the env var
			os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'info'
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'info'

			# Delete the env var to test default
			del os.environ['BROWSER_USE_LOGGING_LEVEL']
			assert CONFIG.BROWSER_USE_LOGGING_LEVEL == 'info'  # default value
		finally:
			# Restore original value
			if original_value:
				os.environ['BROWSER_USE_LOGGING_LEVEL'] = original_value
			else:
				os.environ.pop('BROWSER_USE_LOGGING_LEVEL', None)

	def test_boolean_env_vars(self):
		"""Test boolean environment variables are parsed correctly."""
		original_value = os.environ.get('ANONYMIZED_TELEMETRY', '')
		try:
			# Test true values
			for true_val in ['true', 'True', 'TRUE', 'yes', 'Yes', '1']:
				os.environ['ANONYMIZED_TELEMETRY'] = true_val
				assert CONFIG.ANONYMIZED_TELEMETRY is True, f'Failed for value: {true_val}'

			# Test false values
			for false_val in ['false', 'False', 'FALSE', 'no', 'No', '0']:
				os.environ['ANONYMIZED_TELEMETRY'] = false_val
				assert CONFIG.ANONYMIZED_TELEMETRY is False, f'Failed for value: {false_val}'
		finally:
			if original_value:
				os.environ['ANONYMIZED_TELEMETRY'] = original_value
			else:
				os.environ.pop('ANONYMIZED_TELEMETRY', None)

	def test_api_keys_lazy_loading(self):
		"""Test API keys are loaded lazily."""
		original_value = os.environ.get('OPENAI_API_KEY', '')
		try:
			# Test empty default
			os.environ.pop('OPENAI_API_KEY', None)
			assert CONFIG.OPENAI_API_KEY == ''

			# Set a value
			os.environ['OPENAI_API_KEY'] = 'test-key-123'
			assert CONFIG.OPENAI_API_KEY == 'test-key-123'

			# Change the value
			os.environ['OPENAI_API_KEY'] = 'new-key-456'
			assert CONFIG.OPENAI_API_KEY == 'new-key-456'
		finally:
			if original_value:
				os.environ['OPENAI_API_KEY'] = original_value
			else:
				os.environ.pop('OPENAI_API_KEY', None)

	def test_path_configuration(self):
		"""Test path configuration variables."""
		original_value = os.environ.get('XDG_CACHE_HOME', '')
		try:
			# Test custom path
			test_path = '/tmp/test-cache'
			os.environ['XDG_CACHE_HOME'] = test_path
			# Use Path().resolve() to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
			from pathlib import Path

			assert CONFIG.XDG_CACHE_HOME == Path(test_path).resolve()

			# Test default path expansion
			os.environ.pop('XDG_CACHE_HOME', None)
			assert '/.cache' in str(CONFIG.XDG_CACHE_HOME)
		finally:
			if original_value:
				os.environ['XDG_CACHE_HOME'] = original_value
			else:
				os.environ.pop('XDG_CACHE_HOME', None)

	def test_cloud_sync_inherits_telemetry(self):
		"""Test BROWSER_USE_CLOUD_SYNC inherits from ANONYMIZED_TELEMETRY when not set."""
		telemetry_original = os.environ.get('ANONYMIZED_TELEMETRY', '')
		sync_original = os.environ.get('BROWSER_USE_CLOUD_SYNC', '')
		try:
			# When BROWSER_USE_CLOUD_SYNC is not set, it should inherit from ANONYMIZED_TELEMETRY
			os.environ['ANONYMIZED_TELEMETRY'] = 'true'
			os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is True

			os.environ['ANONYMIZED_TELEMETRY'] = 'false'
			os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is False

			# When explicitly set, it should use its own value
			os.environ['ANONYMIZED_TELEMETRY'] = 'false'
			os.environ['BROWSER_USE_CLOUD_SYNC'] = 'true'
			assert CONFIG.BROWSER_USE_CLOUD_SYNC is True
		finally:
			if telemetry_original:
				os.environ['ANONYMIZED_TELEMETRY'] = telemetry_original
			else:
				os.environ.pop('ANONYMIZED_TELEMETRY', None)
			if sync_original:
				os.environ['BROWSER_USE_CLOUD_SYNC'] = sync_original
			else:
				os.environ.pop('BROWSER_USE_CLOUD_SYNC', None)


class TestConfigMigration:
	"""A config that cannot be read must not be replaced by defaults on disk."""

	@staticmethod
	def _write(config_path: Path, text: str) -> bytes:
		config_path.write_text(text)
		return config_path.read_bytes()

	def test_unparseable_config_is_left_on_disk(self, tmp_path: Path):
		"""A truncated file (killed mid-write) must survive the failed load."""
		config_path = tmp_path / 'config.json'
		original = self._write(config_path, '{"llm": {"abc": {"id": "abc", "api_key": "sk-real-key"')

		config = load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original
		assert 'sk-real-key' in config_path.read_text()
		# The caller still gets a usable config for this run.
		assert config.llm

	def test_invalid_field_does_not_overwrite_config(self, tmp_path: Path):
		"""One mistyped field raises ValidationError; the file must be kept."""
		config_path = tmp_path / 'config.json'
		payload = {
			'browser_profile': {'p1': {'id': 'p1', 'default': True, 'headless': 'not-a-bool'}},
			'llm': {'l1': {'id': 'l1', 'default': True, 'api_key': 'sk-real-key'}},
			'agent': {},
		}
		original = self._write(config_path, json.dumps(payload))

		load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original

	def test_config_without_browser_profiles_is_not_migrated(self, tmp_path: Path):
		"""An empty browser_profile is still the new format, not the old one."""
		config_path = tmp_path / 'config.json'
		payload = {
			'browser_profile': {},
			'llm': {'l1': {'id': 'l1', 'default': True, 'api_key': 'sk-real-key'}},
			'agent': {},
		}
		original = self._write(config_path, json.dumps(payload))

		config = load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original
		assert config.llm['l1'].api_key == 'sk-real-key'

	def test_non_utf8_config_is_left_on_disk(self, tmp_path: Path):
		"""Bytes that are not valid UTF-8 fail the read; the file must survive it."""
		config_path = tmp_path / 'config.json'
		config_path.write_bytes(
			b'{"browser_profile": {}, "llm": {"l1": {"id": "l1", "api_key": "sk-real-\xff\xfe"}}, "agent": {}}'
		)
		original = config_path.read_bytes()

		config = load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original
		# The caller still gets a usable config for this run.
		assert config.llm

	def test_empty_config_is_kept_but_still_usable(self, tmp_path: Path):
		"""An entirely empty config is not overwritten, and still yields defaults."""
		config_path = tmp_path / 'config.json'
		original = self._write(config_path, json.dumps({'browser_profile': {}, 'llm': {}, 'agent': {}}))

		config = load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original
		assert config.browser_profile and config.llm and config.agent

	def test_failed_migration_write_does_not_truncate(self, tmp_path: Path, monkeypatch):
		"""A write that fails mid-migration must not leave an empty file behind."""
		config_path = tmp_path / 'config.json'
		original = self._write(config_path, json.dumps({'browser_profile': {'headless': False}, 'llm': {}, 'agent': {}}))

		def no_space(*args, **kwargs):
			raise OSError(28, 'No space left on device')

		monkeypatch.setattr(json, 'dump', no_space)
		config = load_and_migrate_config(config_path)

		assert config_path.read_bytes() == original
		assert not (tmp_path / 'config.json.tmp').exists()
		assert config.llm

	def test_repeated_failed_loads_reuse_one_fallback(self, tmp_path: Path):
		"""One bad file read three times is one fallback config, not three."""
		config_path = tmp_path / 'config.json'
		self._write(config_path, '{"llm": {"abc": ')

		first = load_and_migrate_config(config_path)
		second = load_and_migrate_config(config_path)

		assert list(first.llm) == list(second.llm)
		assert list(first.browser_profile) == list(second.browser_profile)

	def test_migration_keeps_the_file_mode(self, tmp_path: Path):
		"""config.json holds an api_key: a 0600 file must not come back 0644."""
		import os

		config_path = tmp_path / 'config.json'
		self._write(config_path, json.dumps({'browser_profile': {'headless': False}, 'llm': {}, 'agent': {}}))
		os.chmod(config_path, 0o600)

		load_and_migrate_config(config_path)

		assert config_path.stat().st_mode & 0o777 == 0o600
		assert not list(tmp_path.glob('*.tmp'))

	def test_migration_drops_a_stale_fallback(self, tmp_path: Path):
		"""Once the file reads again, this run must stop serving the cached defaults."""
		config_path = tmp_path / 'config.json'
		self._write(config_path, '{"llm": {"abc": ')
		fallback = load_and_migrate_config(config_path)

		# The user repairs the file, in the old format, so the migration path runs.
		self._write(config_path, json.dumps({'browser_profile': {'headless': False}, 'llm': {}, 'agent': {}}))
		migrated = load_and_migrate_config(config_path)
		assert list(migrated.llm) != list(fallback.llm)

		# A later failure gets its own fresh defaults, not the pre-migration ones.
		self._write(config_path, '{"llm": {"abc": ')
		later = load_and_migrate_config(config_path)
		assert list(later.llm) != list(fallback.llm)

	def test_old_format_is_still_migrated(self, tmp_path: Path):
		"""The migration path itself must keep working."""
		config_path = tmp_path / 'config.json'
		self._write(config_path, json.dumps({'browser_profile': {'headless': False}, 'llm': {}, 'agent': {}}))

		config = load_and_migrate_config(config_path)

		written = json.loads(config_path.read_text())
		assert set(written) == {'browser_profile', 'llm', 'agent'}
		assert written['browser_profile']
		assert config.browser_profile
