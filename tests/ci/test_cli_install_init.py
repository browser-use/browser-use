"""
Tests for browser-use CLI install and init commands.

These commands are handled early in the CLI before argparse, to avoid loading
heavy dependencies for simple setup tasks.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest_httpserver import HTTPServer

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


# ---------------------------------------------------------------------------
# Path-traversal regression tests for templates.json (`dest`/`source`/`file`)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	'name',
	[
		'/etc/crontab',
		'/tmp/abs',
		'../../../etc/passwd',
		'foo/../../bar',
		'..',
		'a/../b',
		'',
		'foo\\bar',  # backslashes treated as a literal char on POSIX – ambiguous, reject
		'foo\x00bar',
	],
)
def test_validate_relative_path_rejects_dangerous_inputs(name: str):
	with pytest.raises(ValueError):
		init_cmd._validate_relative_path(name, field='dest')


@pytest.mark.parametrize(
	'name',
	[
		'main.py',
		'subdir/main.py',
		'a/b/c/d.txt',
		'.gitignore',
	],
)
def test_validate_relative_path_accepts_plain_names(name: str):
	assert init_cmd._validate_relative_path(name, field='dest') == name


def test_safe_join_keeps_path_inside_base(tmp_path: Path):
	base = tmp_path / 'tpl'
	base.mkdir()
	resolved = init_cmd._safe_join(base, 'sub/file.py', field='dest')
	assert resolved == (base / 'sub' / 'file.py').resolve()


def test_safe_join_rejects_absolute_dest(tmp_path: Path):
	base = tmp_path / 'tpl'
	base.mkdir()
	with pytest.raises(ValueError):
		init_cmd._safe_join(base, '/etc/crontab', field='dest')


def test_safe_join_rejects_traversal_dest(tmp_path: Path):
	base = tmp_path / 'tpl'
	base.mkdir()
	with pytest.raises(ValueError):
		init_cmd._safe_join(base, '../escape.py', field='dest')


def _malicious_manifest() -> dict:
	"""A templates.json shaped exactly like the one in the vuln report."""
	return {
		'evil': {
			'description': 'Innocuous-looking template',
			'file': 'evil/main.py',
			'files': [
				{
					'source': 'evil/payload.sh',
					'dest': '../../../../../../tmp/browser_use_pwn_marker',
					'executable': True,
				},
				{
					'source': 'evil/cron',
					'dest': '/tmp/browser_use_pwn_abs_marker',
					'binary': False,
				},
			],
		}
	}


def test_init_refuses_manifest_path_traversal(tmp_path: Path, httpserver: HTTPServer, monkeypatch):
	"""
	End-to-end: a compromised templates.json that points `dest` at /tmp or
	outside the template dir must NOT cause writes outside the per-template
	directory the user created in their cwd.
	"""
	manifest = _malicious_manifest()
	httpserver.expect_request('/templates.json').respond_with_json(manifest)
	# main.py for the template is fetched first; serve a benign body so the
	# code reaches the `files` loop where the traversal would happen.
	httpserver.expect_request('/evil/main.py').respond_with_data('print("hi")\n')
	httpserver.expect_request('/evil/payload.sh').respond_with_data('#!/bin/sh\necho pwn\n')
	httpserver.expect_request('/evil/cron').respond_with_data('* * * * * root pwn\n')

	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', httpserver.url_for('').rstrip('/'))
	monkeypatch.chdir(tmp_path)

	# Pre-create the marker locations to assert they are NOT overwritten.
	rel_marker = Path('/tmp/browser_use_pwn_marker')
	abs_marker = Path('/tmp/browser_use_pwn_abs_marker')
	for m in (rel_marker, abs_marker):
		if m.exists():
			m.unlink()

	runner = CliRunner()
	result = runner.invoke(init_cmd.main, ['--template', 'evil', '--force'])

	# The benign main.py write should still succeed; only the malicious entries
	# get skipped with a warning.
	assert result.exit_code == 0, result.output
	assert (tmp_path / 'evil' / 'main.py').exists()
	assert not rel_marker.exists(), 'traversal `dest` wrote outside template dir'
	assert not abs_marker.exists(), 'absolute `dest` wrote outside template dir'
	assert 'unsafe template entry' in result.output


def test_init_refuses_traversal_in_template_name(tmp_path: Path, httpserver: HTTPServer, monkeypatch):
	"""A manifest that names a template `..` (used as cwd subdir) is rejected."""
	httpserver.expect_request('/templates.json').respond_with_json({'../escape': {'file': 'x.py'}})
	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', httpserver.url_for('').rstrip('/'))
	monkeypatch.chdir(tmp_path)

	runner = CliRunner()
	result = runner.invoke(init_cmd.main, ['--template', '../escape', '--force'])
	assert result.exit_code == 1
	assert 'template name' in result.output
	# Make sure no escape directory was created in the parent.
	assert not (tmp_path.parent / 'escape').exists()


def test_init_refuses_traversal_in_template_file(tmp_path: Path, httpserver: HTTPServer, monkeypatch):
	"""A manifest whose `file` URL path tries to escape the repo URL is rejected."""
	httpserver.expect_request('/templates.json').respond_with_json({'evil': {'file': '../../private/secret.py'}})
	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', httpserver.url_for('').rstrip('/'))
	monkeypatch.chdir(tmp_path)

	runner = CliRunner()
	result = runner.invoke(init_cmd.main, ['--template', 'evil', '--force'])
	# main exits non-zero via sys.exit(1) inside the except block.
	assert result.exit_code == 1
	assert 'template file' in result.output


def test_init_happy_path_still_writes_files(tmp_path: Path, httpserver: HTTPServer, monkeypatch):
	"""Sanity check: a normal manifest with relative paths still works."""
	manifest = {
		'good': {
			'description': 'Benign',
			'file': 'good/main.py',
			'files': [
				{'source': 'good/helper.py', 'dest': 'helper.py'},
			],
		}
	}
	httpserver.expect_request('/templates.json').respond_with_json(manifest)
	httpserver.expect_request('/good/main.py').respond_with_data('print("main")\n')
	httpserver.expect_request('/good/helper.py').respond_with_data('print("helper")\n')

	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', httpserver.url_for('').rstrip('/'))
	monkeypatch.chdir(tmp_path)

	runner = CliRunner()
	result = runner.invoke(init_cmd.main, ['--template', 'good', '--force'])
	assert result.exit_code == 0, result.output
	assert (tmp_path / 'good' / 'main.py').read_text() == 'print("main")\n'
	assert (tmp_path / 'good' / 'helper.py').read_text() == 'print("helper")\n'
