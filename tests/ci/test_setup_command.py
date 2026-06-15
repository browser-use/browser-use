"""Tests for setup command.

Verifies the setup command runs and returns expected structure.
"""

import tempfile
from pathlib import Path

from browser_use.skill_cli.commands import setup


def test_setup_returns_valid_structure(monkeypatch):
	"""Test setup handle returns expected result structure."""
	with tempfile.TemporaryDirectory(prefix='bu-') as d:
		monkeypatch.setenv('BROWSER_USE_HOME', d)
		result = setup.handle(yes=True)

		assert isinstance(result, dict)
		assert 'status' in result or 'error' in result


def test_setup_creates_config(monkeypatch):
	"""Test setup creates config.json."""
	with tempfile.TemporaryDirectory(prefix='bu-') as d:
		monkeypatch.setenv('BROWSER_USE_HOME', d)
		setup.handle(yes=True)

		config_path = Path(d) / 'config.json'
		assert config_path.exists()
