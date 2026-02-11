"""Tests for the python REPL action."""

import tempfile
from pathlib import Path

from browser_use.agent.views import ActionResult
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.python.execution import (
	create_namespace,
	execute_code,
	get_changed_variables,
	truncate_output,
)
from browser_use.tools.python.views import PythonSession
from browser_use.tools.service import Tools


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _make_tools_with_python() -> Tools:
	"""Create a Tools instance with python REPL enabled."""
	tools = Tools()
	tools.enable_python_repl()
	return tools


def _make_file_system() -> FileSystem:
	"""Create a FileSystem backed by a temp directory."""
	tmp = Path(tempfile.mkdtemp(prefix='bu_python_test_'))
	return FileSystem(base_dir=tmp)


async def _execute_python(tools: Tools, code: str, file_system: FileSystem | None = None) -> ActionResult:
	"""Execute python through the registry (no browser needed for simple code)."""
	fs = file_system or _make_file_system()
	result = await tools.registry.execute_action(
		action_name='python',
		params={'code': code},
		file_system=fs,
	)
	assert isinstance(result, ActionResult)
	return result


# ─── Registration ──────────────────────────────────────────────────────────────


def test_python_not_registered_by_default():
	"""python should NOT be registered by default (opt-in)."""
	tools = Tools()
	assert 'python' not in tools.registry.registry.actions


def test_python_registered_after_enable():
	"""enable_python_repl() should register the action."""
	tools = _make_tools_with_python()
	assert 'python' in tools.registry.registry.actions


def test_python_enable_is_idempotent():
	"""Calling enable_python_repl() twice should not crash."""
	tools = Tools()
	tools.enable_python_repl()
	tools.enable_python_repl()
	assert 'python' in tools.registry.registry.actions


# ─── Basic execution ──────────────────────────────────────────────────────────


async def test_python_basic_execution():
	"""Simple print statement should produce output."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, 'print("hello world")')
	assert result.error is None
	assert 'hello world' in result.extracted_content


async def test_python_no_output():
	"""Code with no print should still succeed."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, 'x = 42')
	assert result.error is None
	assert 'x' in result.extracted_content  # variable created


# ─── Persistent namespace ────────────────────────────────────────────────────


async def test_python_persistent_namespace():
	"""Variables should persist across calls."""
	tools = _make_tools_with_python()
	fs = _make_file_system()

	await _execute_python(tools, 'counter = 0', file_system=fs)
	await _execute_python(tools, 'counter += 10', file_system=fs)
	result = await _execute_python(tools, 'print(f"counter={counter}")', file_system=fs)

	assert result.error is None
	assert 'counter=10' in result.extracted_content


# ─── Syntax error ─────────────────────────────────────────────────────────────


async def test_python_syntax_error():
	"""Syntax errors should be reported."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, 'def foo(')
	assert result.error is not None
	assert 'SyntaxError' in result.error


# ─── Runtime error ────────────────────────────────────────────────────────────


async def test_python_runtime_error():
	"""Runtime errors should be reported with traceback."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, '1 / 0')
	assert result.error is not None
	assert 'ZeroDivisionError' in result.error


# ─── Async code ───────────────────────────────────────────────────────────────


async def test_python_async_code():
	"""Code with await should execute correctly."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, '''
import asyncio
await asyncio.sleep(0.01)
print("async done")
''')
	assert result.error is None
	assert 'async done' in result.extracted_content


# ─── Output truncation ───────────────────────────────────────────────────────


def test_truncate_output_short():
	"""Short output should not be truncated."""
	assert truncate_output('hello') == 'hello'


def test_truncate_output_long():
	"""Long output should be truncated with midpoint ellipsis."""
	long_text = 'x' * 50000
	result = truncate_output(long_text, max_length=1000)
	assert len(result) < len(long_text)
	assert 'truncated' in result.lower()
	assert result.startswith('x' * 100)
	assert result.endswith('x' * 100)


# ─── Variable tracking ───────────────────────────────────────────────────────


def test_get_changed_variables_basic():
	"""Should detect new variables, filter system vars."""
	before = {'json', 're', 'browser'}
	after = {'json', 're', 'browser', 'my_var', 'result', '__internal'}
	namespace = {'json': None, 're': None, 'browser': None, 'my_var': 42, 'result': [], '__internal': True}
	changed = get_changed_variables(before, after, namespace)
	assert 'my_var' in changed
	assert 'result' in changed
	assert '__internal' not in changed  # starts with _
	assert 'browser' not in changed  # system var


# ─── Pre-imported libs ────────────────────────────────────────────────────────


async def test_python_preimported_libs():
	"""Common libraries should be pre-imported in namespace."""
	tools = _make_tools_with_python()
	result = await _execute_python(tools, '''
import sys
available = []
for name in ['json', 're', 'csv', 'Path']:
    if name in dir():
        available.append(name)
print(",".join(available))
''')
	assert result.error is None
	for lib in ['json', 're', 'csv', 'Path']:
		assert lib in result.extracted_content


# ─── File helpers ─────────────────────────────────────────────────────────────


async def test_python_save_json():
	"""save_json helper should create a file."""
	tools = _make_tools_with_python()
	fs = _make_file_system()

	result = await _execute_python(tools, '''
path = save_json({"key": "value"}, "test_output.json")
print(f"saved to {path}")
''', file_system=fs)

	assert result.error is None
	assert 'saved to' in result.extracted_content
	assert (fs.get_dir() / 'test_output.json').exists()


# ─── create_namespace ────────────────────────────────────────────────────────


def test_create_namespace_without_browser():
	"""Namespace should work without a browser session."""
	ns = create_namespace(browser_session=None, file_system=None, existing_namespace={})
	assert 'json' in ns
	assert 're' in ns
	assert 'Path' in ns
	assert 'browser' not in ns  # no session provided


def test_create_namespace_preserves_existing():
	"""Existing namespace values should carry forward."""
	ns = create_namespace(
		browser_session=None,
		file_system=None,
		existing_namespace={'my_var': 42, 'my_list': [1, 2, 3]},
	)
	assert ns['my_var'] == 42
	assert ns['my_list'] == [1, 2, 3]


# ─── PythonSession ──────────────────────────────────────────────────────────


def test_python_session_history():
	"""Session should track execution history."""
	session = PythonSession()
	assert session.execution_count == 0

	count = session.increment_execution_count()
	assert count == 1
	assert session.execution_count == 1

	cell = session.add_history(source='x = 1', output=None, variables_created=['x'])
	assert cell.execution_count == 1
	assert cell.source == 'x = 1'
	assert 'x' in cell.variables_created

	assert len(session.history) == 1


# ─── execute_code directly ───────────────────────────────────────────────────


async def test_execute_code_sync():
	"""Direct execution of sync code."""
	output, error = await execute_code('x = 5\nprint(x)', {})
	assert error is None
	assert '5' in output


async def test_execute_code_async():
	"""Direct execution of async code."""
	import asyncio

	output, error = await execute_code('import asyncio\nawait asyncio.sleep(0)\nprint("ok")', {})
	assert error is None
	assert 'ok' in output


async def test_execute_code_preserves_namespace():
	"""Variables set during execution should persist in the namespace."""
	ns: dict = {}
	await execute_code('my_val = 123', ns)
	assert ns.get('my_val') == 123

	output, error = await execute_code('print(my_val + 1)', ns)
	assert error is None
	assert '124' in output
