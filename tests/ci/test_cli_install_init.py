"""
Tests for browser-use CLI install and init commands.

These commands are handled early in the CLI before argparse, to avoid loading
heavy dependencies for simple setup tasks.
"""

import subprocess
import sys


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
