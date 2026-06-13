"""Tests for the browser-use python command help and safety documentation."""

import os
import re
import subprocess
import sys
from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess:
	"""Run the CLI as a subprocess, returning the result."""
	env = os.environ.copy()
	env.pop('BROWSER_USE_API_KEY', None)

	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=15,
	)


def test_python_help_documents_trusted_local_execution_boundary():
	"""The Python command help should make the execution trust boundary explicit."""
	result = run_cli('python', '--help')

	assert result.returncode == 0
	help_text = result.stdout + result.stderr
	assert 'trusted local Python' in help_text
	assert re.search(r'not\s+a\s+sandbox', help_text)


def test_cli_readme_documents_python_execution_boundary():
	"""The persistent Python README docs should warn users that code is unsandboxed."""
	repo_root = Path(__file__).resolve().parents[2]
	readme = (repo_root / 'browser_use/skill_cli/README.md').read_text()

	assert 'trusted local Python' in readme
	assert 'not a sandbox' in readme
