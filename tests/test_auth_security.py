import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

from browser_use.sync.auth import CloudAuthConfig, get_or_create_device_id


def test_cloud_auth_config_save_permissions():
	with tempfile.TemporaryDirectory() as tmp_dir:
		target_dir = Path(tmp_dir) / 'nested_config_dir'
		with patch('browser_use.sync.auth.CONFIG.BROWSER_USE_CONFIG_DIR', target_dir):
			config = CloudAuthConfig(api_token='secret_test_token_123', user_id='user_abc')
			config.save_to_file()

			config_file = target_dir / 'cloud_auth.json'
			assert config_file.exists()

			# Check file and directory permissions on POSIX
			if os.name != 'nt':
				dir_stat = os.stat(target_dir)
				assert stat.S_IMODE(dir_stat.st_mode) == 0o700, f'Expected 0o700 dir but got {oct(stat.S_IMODE(dir_stat.st_mode))}'

				file_stat = os.stat(config_file)
				file_mode = stat.S_IMODE(file_stat.st_mode)
				assert file_mode == 0o600, f'Expected 0o600 but got {oct(file_mode)}'

			# Verify content can be loaded back
			loaded = CloudAuthConfig.load_from_file()
			assert loaded.api_token == 'secret_test_token_123'
			assert loaded.user_id == 'user_abc'


def test_get_or_create_device_id_permissions():
	with tempfile.TemporaryDirectory() as tmp_dir:
		target_dir = Path(tmp_dir) / 'nested_config_dir'
		with patch('browser_use.sync.auth.CONFIG.BROWSER_USE_CONFIG_DIR', target_dir):
			device_id = get_or_create_device_id()
			assert device_id is not None

			device_file = target_dir / 'device_id'
			assert device_file.exists()

			if os.name != 'nt':
				dir_stat = os.stat(target_dir)
				assert stat.S_IMODE(dir_stat.st_mode) == 0o700, f'Expected 0o700 dir but got {oct(stat.S_IMODE(dir_stat.st_mode))}'

				file_stat = os.stat(device_file)
				file_mode = stat.S_IMODE(file_stat.st_mode)
				assert file_mode == 0o600, f'Expected 0o600 but got {oct(file_mode)}'


def test_existing_permissive_file_remediation():
	with tempfile.TemporaryDirectory() as tmp_dir:
		target_dir = Path(tmp_dir) / 'nested_config_dir'
		target_dir.mkdir(parents=True, exist_ok=True)
		config_file = target_dir / 'cloud_auth.json'
		config_file.write_text('{}')
		if os.name != 'nt':
			os.chmod(config_file, 0o644)

		with patch('browser_use.sync.auth.CONFIG.BROWSER_USE_CONFIG_DIR', target_dir):
			config = CloudAuthConfig(api_token='secret_new_token', user_id='user_xyz')
			config.save_to_file()

			if os.name != 'nt':
				file_stat = os.stat(config_file)
				assert stat.S_IMODE(file_stat.st_mode) == 0o600

