"""An existing config.json that cannot be parsed must not be replaced with allow-all defaults."""

import json

import pytest

from browser_use.config import create_default_config, load_and_migrate_config


def test_missing_config_is_created_with_defaults(tmp_path):
	config_path = tmp_path / 'config.json'

	config = load_and_migrate_config(config_path)

	assert config_path.exists()
	assert len(config.browser_profile) == 1
	assert json.loads(config_path.read_text())['browser_profile']


def test_valid_config_keeps_browser_restrictions(tmp_path):
	config_path = tmp_path / 'config.json'
	data = create_default_config().model_dump()
	profile = next(iter(data['browser_profile'].values()))
	profile.update(allowed_domains=['example.com'], prohibited_domains=['127.0.0.1'])
	config_path.write_text(json.dumps(data))

	config = load_and_migrate_config(config_path)

	loaded = next(iter(config.browser_profile.values())).model_dump()
	assert loaded['allowed_domains'] == ['example.com']
	assert loaded['prohibited_domains'] == ['127.0.0.1']


def test_unparseable_config_fails_closed_and_is_left_unchanged(tmp_path):
	config_path = tmp_path / 'config.json'
	data = create_default_config().model_dump()
	next(iter(data['browser_profile'].values()))['allowed_domains'] = ['example.com']
	corrupt = json.dumps(data)[:-10]  # truncated JSON
	config_path.write_text(corrupt)

	with pytest.raises(ValueError, match='Failed to load browser-use config'):
		load_and_migrate_config(config_path)

	assert config_path.read_text() == corrupt


def test_failed_migration_write_leaves_old_config_intact(tmp_path, monkeypatch):
	config_path = tmp_path / 'config.json'
	old_format = json.dumps({'browser_profile': {'headless': True}})
	config_path.write_text(old_format)

	def failing_dump(*args, **kwargs):
		raise OSError('disk full')

	monkeypatch.setattr('browser_use.config.json.dump', failing_dump)

	config = load_and_migrate_config(config_path)

	assert len(config.browser_profile) == 1
	assert config_path.read_text() == old_format
	assert [p.name for p in tmp_path.iterdir()] == ['config.json']
