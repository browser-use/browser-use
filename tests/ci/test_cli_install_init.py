"""
Tests for browser-use CLI install and init commands.

These commands are handled early in the CLI before argparse, to avoid loading
heavy dependencies for simple setup tasks.
"""

import hashlib
import subprocess
import sys

import pytest

from browser_use import init_cmd


def test_install_command_help():
	"""Test that the install command is documented in help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert 'install' in result.stdout
	assert 'Install Chromium browser' in result.stdout


def test_init_command_help():
	"""Test that the init command is documented in help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert 'init' in result.stdout
	assert 'Generate browser-use template file' in result.stdout


def test_init_subcommand_help():
	"""Test that the init subcommand has its own help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', 'init', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert '--template' in result.stdout or '-t' in result.stdout
	assert '--list' in result.stdout or '-l' in result.stdout


def test_init_list_templates():
	"""Test that init --list shows available templates."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', 'init', '--list'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert 'default' in result.stdout
	assert 'advanced' in result.stdout


def test_mcp_flag_help():
	"""Test that the --mcp flag is documented in help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert '--mcp' in result.stdout
	assert 'MCP server' in result.stdout


def test_template_flag_help():
	"""Test that the --template flag is documented in help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert '--template' in result.stdout


def test_fetch_template_list_rejects_tampered_manifest(monkeypatch):
	"""Template metadata should be pinned to the expected manifest hash."""
	class _Response:
		def __init__(self, payload: bytes):
			self._payload = payload

		def __enter__(self):
			return self

		def __exit__(self, exc_type, exc, tb):
			return False

		def read(self):
			return self._payload

	monkeypatch.setattr(init_cmd, 'TEMPLATE_MANIFEST_SHA256', '0' * 64)
	monkeypatch.setattr(init_cmd.request, 'urlopen', lambda *args, **kwargs: _Response(b'{}'))

	with pytest.raises(RuntimeError, match='Template manifest integrity check failed'):
		init_cmd._fetch_template_list()


def test_get_template_content_rejects_tampered_python_template(monkeypatch):
	"""Template code should be rejected if the fetched file hash changes."""
	content = 'print("tampered")\n'
	monkeypatch.setattr(init_cmd, '_fetch_from_github', lambda file_path: content)
	monkeypatch.setattr(
		init_cmd,
		'TEMPLATE_FILE_SHA256',
		{'default_template.py': hashlib.sha256(b'print("safe")\n').hexdigest()},
	)

	with pytest.raises(RuntimeError, match='Template integrity check failed for default_template.py'):
		init_cmd._get_template_content('default_template.py')
