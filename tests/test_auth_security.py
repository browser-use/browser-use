import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

from browser_use.sync.auth import CloudAuthConfig, get_or_create_device_id


def test_cloud_auth_config_save_permissions():
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir)
		with patch('browser_use.sync.auth.CONFIG.BROWSER_USE_CONFIG_DIR', tmp_path):
			config = CloudAuthConfig(api_token='secret_test_token_123', user_id='user_abc')
			config.save_to_file()

			config_file = tmp_path / 'cloud_auth.json'
			assert config_file.exists()

			# Check file permissions on POSIX
			if hasattr(os, 'stat'):
				file_stat = os.stat(config_file)
				file_mode = stat.S_IMODE(file_stat.st_mode)
				# Ensure file has 0o600 permissions (read/write only for owner)
				assert file_mode & 0o077 == 0, f'Expected 0o600 but got {oct(file_mode)}'

			# Verify content can be loaded back
			loaded = CloudAuthConfig.load_from_file()
			assert loaded.api_token == 'secret_test_token_123'
			assert loaded.user_id == 'user_abc'


def test_get_or_create_device_id_permissions():
	with tempfile.TemporaryDirectory() as tmp_dir:
		tmp_path = Path(tmp_dir)
		with patch('browser_use.sync.auth.CONFIG.BROWSER_USE_CONFIG_DIR', tmp_path):
			device_id = get_or_create_device_id()
			assert device_id is not None

			device_file = tmp_path / 'device_id'
			assert device_file.exists()

			if hasattr(os, 'stat'):
				file_stat = os.stat(device_file)
				file_mode = stat.S_IMODE(file_stat.st_mode)
				assert file_mode & 0o077 == 0, f'Expected 0o600 but got {oct(file_mode)}'
