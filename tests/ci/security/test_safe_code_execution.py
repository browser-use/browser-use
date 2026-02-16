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
		"""Block import statements via explicit AST check."""
		with pytest.raises(ValueError, match='Import statements are not allowed'):
			_safe_exec('import os', {})

	def test_safe_exec_blocks_import_from(self):
		"""Block from x import y statements."""
		with pytest.raises(ValueError, match='Import statements are not allowed'):
			_safe_exec('from os import system', {})

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

	def test_safe_exec_copies_back_variables(self):
		"""Safe variables are copied back to parent namespace."""
		ns: dict = {}
		_safe_exec('r = {"a": 1}', ns)
		assert ns['r'] == {'a': 1}

	def test_safe_exec_isolates_namespace_no_escape(self):
		"""Dangerous objects in parent namespace are NOT visible (no os.system escape)."""
		ns: dict = {'os': __import__('os')}
		with pytest.raises((NameError, ValueError)):
			_safe_exec('os.system("echo pwned")', ns)


def test_safe_code_execution_flag_default_off():
	"""SAFE_CODE_EXECUTION defaults to False when env not set."""
	# Avoid pollution from other tests - check default
	if 'BROWSER_USE_SAFE_CODE_EXECUTION' not in os.environ:
		assert SAFE_CODE_EXECUTION is False
