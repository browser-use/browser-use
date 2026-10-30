"""Regression tests for load_and_migrate_config handling of an unreadable config.json.

A config.json that exists but cannot be parsed used to be silently replaced with a
fresh default config. The default profile has no allowed_domains / prohibited_domains /
block_ip_addresses, so the security watchdog's allow-all branch took over and the
operator's network boundary was lost permanently (issue #6218).

The loader must distinguish "file absent" (fresh default is fine) from "file present
but unreadable" (fail closed, preserve the original bytes).
"""

import json
import os
from pathlib import Path

import pytest

from browser_use.config import load_and_migrate_config


@pytest.fixture(autouse=True)
def _sandboxed_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	"""Point browser-use's config dir at a temp dir so tests never touch ~/.config."""
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'cfgdir'))
	os.environ.setdefault('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
	yield


RESTRICTED_CONFIG = {
	'browser_profile': {
		'11111111-1111-1111-1111-111111111111': {
			'id': '11111111-1111-1111-1111-111111111111',
			'default': True,
			'headless': True,
			'user_data_dir': None,
			'allowed_domains': ['example.com'],
			'prohibited_domains': ['127.0.0.1'],
			'block_ip_addresses': True,
		}
	},
	'llm': {},
	'agent': {},
}


def _restricted_profile(config: object) -> dict:
	profiles = [p for p in config.browser_profile.values() if p.default]
	assert profiles, 'expected a default profile'
	profile = profiles[0]
	return profile.model_dump(exclude_none=True)


def test_absent_file_still_creates_fresh_default(tmp_path: Path):
	"""First run with no config file keeps the create-default behavior."""
	config_path = tmp_path / 'config.json'

	config = load_and_migrate_config(config_path)

	assert config_path.exists(), 'fresh default config should be written on first run'
	profile = _restricted_profile(config)
	assert 'allowed_domains' not in profile
	assert 'block_ip_addresses' not in profile


def test_corrupt_file_raises_instead_of_failing_open(tmp_path: Path):
	"""Truncated/invalid JSON must not collapse into an allow-all default profile."""
	config_path = tmp_path / 'config.json'
	config_path.write_text(json.dumps(RESTRICTED_CONFIG), encoding='utf-8')
	config_path.write_text('{"browser_profile": {"oops"', encoding='utf-8')  # truncate

	with pytest.raises(Exception) as exc_info:
		load_and_migrate_config(config_path)

	# The error must be about the unreadable config, not a silent fallback.
	assert 'config' in str(exc_info.value).lower()


def test_corrupt_file_is_not_overwritten_and_bak_preserved(tmp_path: Path):
	"""The operator's original bytes must survive a failed parse."""
	config_path = tmp_path / 'config.json'
	original = '{"browser_profile": {"oops"'
	config_path.write_text(original, encoding='utf-8')

	with pytest.raises(Exception):
		load_and_migrate_config(config_path)

	assert config_path.read_text(encoding='utf-8') == original, 'corrupt config must not be replaced with defaults'
	backup = config_path.with_name(config_path.name + '.bak')
	assert backup.exists(), 'a .bak of the original file should be preserved'
	assert backup.read_text(encoding='utf-8') == original


def test_valid_restricted_file_still_loads(tmp_path: Path):
	"""A parseable config keeps loading exactly as before."""
	config_path = tmp_path / 'config.json'
	config_path.write_text(json.dumps(RESTRICTED_CONFIG), encoding='utf-8')

	config = load_and_migrate_config(config_path)

	profile = _restricted_profile(config)
	assert profile['allowed_domains'] == ['example.com']
	assert profile['prohibited_domains'] == ['127.0.0.1']
	assert profile['block_ip_addresses'] is True
