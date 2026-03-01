"""Tests for install configuration module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestInstallConfig:
	"""Tests for browser_use.skill_cli.install_config module."""

	@pytest.fixture
	def temp_config_dir(self, tmp_path: Path):
		"""Create a temporary config directory and patch CONFIG_PATH."""
		config_path = tmp_path / 'install-config.json'
		with patch('browser_use.skill_cli.install_config.CONFIG_PATH', config_path):
			yield config_path

	def test_get_config_default_all_modes(self, temp_config_dir: Path):
		"""If no config file, all modes available (pip install users)."""
		from browser_use.skill_cli.install_config import get_config

		# Config file doesn't exist
		assert not temp_config_dir.exists()

		config = get_config()
		assert config['installed_modes'] == ['chromium', 'real', 'remote']
		assert config['default_mode'] == 'chromium'

	def test_get_config_reads_existing_file(self, temp_config_dir: Path):
		"""Config is read from existing file."""
		from browser_use.skill_cli.install_config import get_config

		# Create config file with remote-only mode
		temp_config_dir.parent.mkdir(parents=True, exist_ok=True)
		temp_config_dir.write_text(json.dumps({'installed_modes': ['remote'], 'default_mode': 'remote'}))

		config = get_config()
		assert config['installed_modes'] == ['remote']
		assert config['default_mode'] == 'remote'

	def test_get_config_handles_corrupt_file(self, temp_config_dir: Path):
		"""Corrupt config file returns default."""
		from browser_use.skill_cli.install_config import get_config

		# Create corrupt config file
		temp_config_dir.parent.mkdir(parents=True, exist_ok=True)
		temp_config_dir.write_text('not valid json {{{')

		config = get_config()
		# Should return default
		assert config['installed_modes'] == ['chromium', 'real', 'remote']
		assert config['default_mode'] == 'chromium'

	def test_save_config_creates_file(self, temp_config_dir: Path):
		"""save_config creates the config file."""
		from browser_use.skill_cli.install_config import save_config

		assert not temp_config_dir.exists()

		save_config(['remote'], 'remote')

		assert temp_config_dir.exists()
		config = json.loads(temp_config_dir.read_text())
		assert config['installed_modes'] == ['remote']
		assert config['default_mode'] == 'remote'

	def test_save_config_creates_parent_directories(self, tmp_path: Path):
		"""save_config creates parent directories if needed."""
		from browser_use.skill_cli.install_config import save_config

		nested_path = tmp_path / 'deep' / 'nested' / 'install-config.json'
		with patch('browser_use.skill_cli.install_config.CONFIG_PATH', nested_path):
			save_config(['chromium', 'real'], 'chromium')

		assert nested_path.exists()

	def test_is_mode_available_remote_only(self, temp_config_dir: Path):
		"""Config with only remote mode blocks local modes."""
		from browser_use.skill_cli.install_config import is_mode_available, save_config

		save_config(['remote'], 'remote')

		assert is_mode_available('remote') is True
		assert is_mode_available('chromium') is False
		assert is_mode_available('real') is False

	def test_is_mode_available_local_only(self, temp_config_dir: Path):
		"""Config with only local modes blocks remote mode."""
		from browser_use.skill_cli.install_config import is_mode_available, save_config

		save_config(['chromium', 'real'], 'chromium')

		assert is_mode_available('chromium') is True
		assert is_mode_available('real') is True
		assert is_mode_available('remote') is False

	def test_is_mode_available_full_install(self, temp_config_dir: Path):
		"""Config with all modes allows everything."""
		from browser_use.skill_cli.install_config import is_mode_available, save_config

		save_config(['chromium', 'real', 'remote'], 'chromium')

		assert is_mode_available('chromium') is True
		assert is_mode_available('real') is True
		assert is_mode_available('remote') is True

	def test_is_mode_available_local_modes_linked(self, temp_config_dir: Path):
		"""If chromium is installed, real is also available (and vice versa)."""
		from browser_use.skill_cli.install_config import is_mode_available, save_config

		# Only chromium in the list, but real should also work
		save_config(['chromium'], 'chromium')

		assert is_mode_available('chromium') is True
		assert is_mode_available('real') is True  # Linked to chromium

		# Only real in the list
		save_config(['real'], 'real')

		assert is_mode_available('chromium') is True  # Linked to real
		assert is_mode_available('real') is True

	def test_get_default_mode(self, temp_config_dir: Path):
		"""Default --browser value comes from config."""
		from browser_use.skill_cli.install_config import get_default_mode, save_config

		# Remote-only install
		save_config(['remote'], 'remote')
		assert get_default_mode() == 'remote'

		# Local-only install
		save_config(['chromium', 'real'], 'chromium')
		assert get_default_mode() == 'chromium'

	def test_get_available_modes(self, temp_config_dir: Path):
		"""get_available_modes returns list from config."""
		from browser_use.skill_cli.install_config import get_available_modes, save_config

		save_config(['remote'], 'remote')
		assert get_available_modes() == ['remote']

		save_config(['chromium', 'real', 'remote'], 'chromium')
		assert get_available_modes() == ['chromium', 'real', 'remote']

	def test_get_mode_unavailable_error_message(self, temp_config_dir: Path):
		"""Clear error when requesting unavailable mode."""
		from browser_use.skill_cli.install_config import get_mode_unavailable_error, save_config

		save_config(['remote'], 'remote')

		error = get_mode_unavailable_error('chromium')
		assert 'chromium' in error
		assert 'not installed' in error.lower()
		assert 'remote' in error  # Shows available modes
		assert '--full' in error  # Shows reinstall instructions

	def test_no_config_file_means_all_modes_available(self, temp_config_dir: Path):
		"""pip install users (no config file) have all modes available."""
		from browser_use.skill_cli.install_config import (
			get_available_modes,
			get_default_mode,
			is_mode_available,
		)

		# Ensure no config exists
		assert not temp_config_dir.exists()

		# All modes should be available
		assert is_mode_available('chromium') is True
		assert is_mode_available('real') is True
		assert is_mode_available('remote') is True

		# Default should be chromium
		assert get_default_mode() == 'chromium'

		# All modes should be in the list
		assert get_available_modes() == ['chromium', 'real', 'remote']
