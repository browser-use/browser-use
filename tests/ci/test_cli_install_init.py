"""
Tests for browser-use CLI install and init commands.

These commands are handled early in the CLI before argparse, to avoid loading
heavy dependencies for simple setup tasks.
"""

import json
import subprocess
import sys
import textwrap


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


def test_mcp_mode_forwards_cdp_url_to_server(tmp_path):
	"""Test that --cdp-url is still honored by the early --mcp entrypoint."""
	output_path = tmp_path / 'mcp_args.json'
	code = textwrap.dedent(
		"""
		import json
		import runpy
		import sys
		import types
		from pathlib import Path

		output_path = Path(sys.argv[1])
		fake_server = types.ModuleType('browser_use.mcp.server')

		async def main(session_timeout_minutes=10, browser_profile_overrides=None):
			output_path.write_text(
				json.dumps(
					{
						'session_timeout_minutes': session_timeout_minutes,
						'browser_profile_overrides': browser_profile_overrides,
					}
				),
				encoding='utf-8',
			)

		fake_server.main = main
		sys.modules['browser_use.mcp.server'] = fake_server
		sys.argv = ['browser-use', '--cdp-url', 'http://127.0.0.1:9223', '--mcp']

		try:
			runpy.run_module('browser_use.skill_cli.main', run_name='__main__')
		except SystemExit as exc:
			if exc.code not in (0, None):
				raise
		"""
	)

	result = subprocess.run(
		[sys.executable, '-c', code, str(output_path)],
		capture_output=True,
		text=True,
	)

	assert result.returncode == 0, result.stderr
	assert json.loads(output_path.read_text(encoding='utf-8'))['browser_profile_overrides'] == {
		'cdp_url': 'http://127.0.0.1:9223'
	}


def test_template_flag_help():
	"""Test that the --template flag is documented in help."""
	result = subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0
	assert '--template' in result.stdout
