"""Security tests for PythonSession sandbox.

Verifies that dangerous modules and builtins are blocked from user code
executed via eval/exec in the PythonSession namespace.
"""

from unittest.mock import MagicMock

import pytest

from browser_use.skill_cli.python_session import PythonSession


@pytest.fixture
def session():
	return PythonSession()


@pytest.fixture
def browser_session():
	return MagicMock()


# ---------------------------------------------------------------------------
# Blocked modules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	'module',
	[
		'os',
		'subprocess',
		'shutil',
		'sys',
		'importlib',
		'ctypes',
		'socket',
		'http',
		'multiprocessing',
		'signal',
		'tempfile',
	],
)
def test_blocked_module_not_in_namespace(session, module):
	"""Dangerous modules must not be pre-loaded in the namespace."""
	assert module not in session.namespace


@pytest.mark.parametrize(
	'code',
	[
		'import os',
		'import subprocess',
		'import shutil',
		'import sys',
		'import ctypes',
		'import socket',
		'from os import path',
		'from subprocess import run',
		"__import__('os')",
		"__import__('subprocess')",
		'import builtins',
		"import builtins; builtins.open('/etc/passwd')",
		"import builtins; builtins.__import__('os')",
	],
)
def test_blocked_module_import_fails(session, browser_session, code):
	"""Importing blocked modules via user code must fail."""
	result = session.execute(code, browser_session)
	assert not result.success
	assert result.error is not None
	assert 'not allowed' in result.error or 'ImportError' in result.error


# ---------------------------------------------------------------------------
# Blocked builtins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	'code',
	[
		"open('/etc/passwd')",
		"exec('1+1')",
		"eval('1+1')",
		"compile('1', '<x>', 'exec')",
	],
)
def test_dangerous_builtins_blocked(session, browser_session, code):
	"""open(), exec(), eval(), compile() must not be available in user code."""
	result = session.execute(code, browser_session)
	assert not result.success
	assert result.error is not None


# ---------------------------------------------------------------------------
# Safe operations still work
# ---------------------------------------------------------------------------


def test_basic_arithmetic(session, browser_session):
	result = session.execute('2 + 3', browser_session)
	assert result.success
	assert '5' in result.output


def test_json_available(session, browser_session):
	result = session.execute("json.dumps({'a': 1})", browser_session)
	assert result.success
	assert '"a"' in result.output


def test_re_available(session, browser_session):
	result = session.execute("re.match(r'\\d+', '123').group()", browser_session)
	assert result.success
	assert '123' in result.output


def test_path_available(session, browser_session):
	result = session.execute("str(Path('.'))", browser_session)
	assert result.success
	assert '.' in result.output


def test_safe_import_allowed(session, browser_session):
	"""Non-blocked modules like math should be importable."""
	result = session.execute('import math; math.sqrt(4)', browser_session)
	assert result.success


def test_class_definition(session, browser_session):
	"""Class definitions must work (__build_class__ is available)."""
	session.execute('class Foo:\n\tx = 42', browser_session)
	result = session.execute('Foo.x', browser_session)
	assert result.success
	assert '42' in result.output


def test_list_comprehension(session, browser_session):
	result = session.execute('[x**2 for x in range(5)]', browser_session)
	assert result.success
	assert '[0, 1, 4, 9, 16]' in result.output


def test_variable_persistence(session, browser_session):
	session.execute('x = 42', browser_session)
	result = session.execute('x', browser_session)
	assert result.success
	assert '42' in result.output


def test_get_variables_excludes_builtins(session):
	"""__builtins__ must not appear in user-visible variables."""
	variables = session.get_variables()
	assert '__builtins__' not in variables


def test_reset_restores_sandbox(session, browser_session):
	"""After reset, blocked modules must still be blocked."""
	session.reset()
	result = session.execute('import os', browser_session)
	assert not result.success
