import json

import pytest

from browser_use.config import load_and_migrate_config


def test_invalid_json_does_not_reset_security_profile(tmp_path):
    config_path = tmp_path / 'config.json'
    config_path.write_text('{"browser_profile": {"bad":', encoding='utf-8')

    with pytest.raises(ValueError, match='invalid|Failed to parse'):
        load_and_migrate_config(config_path)


def test_valid_backup_is_restored_when_config_is_malformed(tmp_path):
    config_path = tmp_path / 'config.json'
    backup_path = tmp_path / 'config.json.bak'

    valid = {
        "browser_profile": {
            "abc123": {
                "id": "abc123",
                "default": True,
                "headless": False,
                "user_data_dir": None,
                "allowed_domains": ["example.com"],
                "prohibited_domains": ["127.0.0.1"],
                "block_ip_addresses": True,
            }
        },
        "llm": {"llm1": {"id": "llm1", "default": True, "model": "gpt-4.1-mini"}},
        "agent": {"agent1": {"id": "agent1", "default": True}},
    }

    config_path.write_text('not valid json', encoding='utf-8')
    backup_path.write_text(json.dumps(valid), encoding='utf-8')

    cfg = load_and_migrate_config(config_path)

    assert cfg.browser_profile["abc123"].allowed_domains == ["example.com"]
    assert cfg.browser_profile["abc123"].block_ip_addresses is True