"""Test that the CLI boots with only the minimal deps from requirements-cli.txt.

Creates a temp venv, installs browser-use with --no-deps, installs only the
requirements-cli.txt deps, then verifies the CLI's critical import paths work.
If this test fails, someone added a new import to the CLI path without updating
browser_use/skill_cli/requirements-cli.txt.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Path to the repo root (two levels up from tests/ci/)
REPO_ROOT = Path(__file__).parent.parent.parent
REQUIREMENTS_CLI = REPO_ROOT / 'browser_use' / 'skill_cli' / 'requirements-cli.txt'


@pytest.fixture(scope='module')
def lite_venv():
	"""Create a temp venv with only CLI deps installed."""
	with tempfile.TemporaryDirectory() as tmp:
		venv_dir = Path(tmp) / 'venv'

		# Create venv
		result = subprocess.run(
			['uv', 'venv', str(venv_dir), '--python', sys.executable],
			capture_output=True,
			text=True,
		)
		assert result.returncode == 0, f'Failed to create venv: {result.stderr}'

		# Get the python binary in the venv
		python = venv_dir / 'bin' / 'python'
		if not python.exists():
			python = venv_dir / 'Scripts' / 'python.exe'  # Windows

		# Install browser-use without deps
		result = subprocess.run(
			['uv', 'pip', 'install', str(REPO_ROOT), '--no-deps', '--python', str(python)],
			capture_output=True,
			text=True,
		)
		assert result.returncode == 0, f'Failed to install browser-use: {result.stderr}'

		# Install only CLI requirements
		result = subprocess.run(
			['uv', 'pip', 'install', '-r', str(REQUIREMENTS_CLI), '--python', str(python)],
			capture_output=True,
			text=True,
		)
		assert result.returncode == 0, f'Failed to install CLI deps: {result.stderr}'

		yield python


def _import_check(python: Path, import_stmt: str) -> subprocess.CompletedProcess:
	"""Run an import statement in the lite venv and return the result."""
	return subprocess.run(
		[str(python), '-c', import_stmt],
		capture_output=True,
		text=True,
		timeout=30,
	)


def test_cli_entry_point(lite_venv):
	"""The CLI entry point must run --help with only CLI deps."""
	result = subprocess.run(
		[str(lite_venv), '-m', 'browser_use.skill_cli.main', '--help'],
		capture_output=True,
		text=True,
		timeout=30,
	)
	assert result.returncode == 0, f'CLI --help failed:\n{result.stderr}'
	assert 'browser-use' in result.stdout.lower() or 'browser automation' in result.stdout.lower()


def test_daemon_imports(lite_venv):
	"""The daemon module must import with only CLI deps."""
	result = _import_check(lite_venv, 'from browser_use.skill_cli.daemon import main')
	assert result.returncode == 0, f'daemon import failed:\n{result.stderr}'


def test_browser_session_imports(lite_venv):
	"""BrowserSession must import with only CLI deps."""
	result = _import_check(lite_venv, 'from browser_use.browser.session import BrowserSession')
	assert result.returncode == 0, f'BrowserSession import failed:\n{result.stderr}'
