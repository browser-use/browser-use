"""Test opt-in safe code execution for REPL path."""

import os

import pytest

from browser_use.skill_cli.python_session import SAFE_CODE_EXECUTION, _safe_exec


class TestSafeCodeExecution:
	"""Test _safe_exec blocks dangerous operations."""

	def test_safe_exec_blocks_import_builtin(self):
		"""Block __import__ and similar dangerous builtins."""
		with pytest.raises(ValueError, match='Disallowed function'):
			_safe_exec("__import__('os').system('echo hacked')", {})

	def test_safe_exec_blocks_import_statement(self):
		"""Block import statements (ast.Import not in allowlist)."""
		with pytest.raises(ValueError, match='Disallowed operation'):
			_safe_exec('import os', {})

	def test_safe_exec_allows_simple_expressions(self):
		"""Allow simple expressions and assignments."""
		ns: dict = {}
		_safe_exec('x = 1 + 2', ns)
		assert ns['x'] == 3

	def test_safe_exec_allows_print(self):
		"""Allow print (in safe_builtins)."""
		ns: dict = {}
		_safe_exec('print("hello")', ns)
		# No exception, print executed

	def test_safe_exec_allows_namespace_attrs(self):
		"""Allow attribute access on namespace objects (json, Path)."""
		ns: dict = {'json': __import__('json')}
		_safe_exec('r = json.dumps({"a": 1})', ns)
		assert ns['r'] == '{"a": 1}'


def test_safe_code_execution_flag_default_off():
	"""SAFE_CODE_EXECUTION defaults to False when env not set."""
	# Avoid pollution from other tests - check default
	if 'BROWSER_USE_SAFE_CODE_EXECUTION' not in os.environ:
		assert SAFE_CODE_EXECUTION is False
