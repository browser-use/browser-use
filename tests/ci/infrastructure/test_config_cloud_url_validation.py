import pytest
from pydantic import ValidationError

from browser_use.config import Config, FlatEnvConfig


def test_config_invalid_cloud_api_url(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', 'not-a-url')
	c = Config()
	with pytest.raises(ValueError, match='BROWSER_USE_CLOUD_API_URL must be a valid URL'):
		_ = c.BROWSER_USE_CLOUD_API_URL


def test_config_valid_cloud_api_url_default(monkeypatch):
	monkeypatch.delenv('BROWSER_USE_CLOUD_API_URL', raising=False)
	c = Config()
	assert '://' in c.BROWSER_USE_CLOUD_API_URL


def test_config_invalid_cloud_ui_url_when_set(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_UI_URL', 'not-a-url')
	c = Config()
	with pytest.raises(ValueError, match='BROWSER_USE_CLOUD_UI_URL must be a valid URL if set'):
		_ = c.BROWSER_USE_CLOUD_UI_URL


def test_config_cloud_ui_url_empty_ok(monkeypatch):
	monkeypatch.delenv('BROWSER_USE_CLOUD_UI_URL', raising=False)
	monkeypatch.setenv('BROWSER_USE_CLOUD_UI_URL', '')
	c = Config()
	assert c.BROWSER_USE_CLOUD_UI_URL == ''


def test_flat_env_config_invalid_cloud_api_url(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', 'not-a-url')
	with pytest.raises(ValidationError, match='BROWSER_USE_CLOUD_API_URL must be a valid URL'):
		FlatEnvConfig()


def test_flat_env_config_invalid_cloud_ui_url_when_set(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_UI_URL', 'bad')
	with pytest.raises(ValidationError, match='BROWSER_USE_CLOUD_UI_URL must be a valid URL if set'):
		FlatEnvConfig()


def test_flat_env_config_cloud_ui_url_empty_ok(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_UI_URL', '')
	FlatEnvConfig()
