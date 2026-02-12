"""Python code execution engine for the python REPL tool.

Handles namespace creation, async/sync code execution, output
truncation, and variable tracking.
"""

import ast
import asyncio
import csv as csv_module
import io
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from browser_use.tools.python.browser_wrapper import BrowserWrapper

if TYPE_CHECKING:
	from browser_use.browser import BrowserSession
	from browser_use.filesystem.file_system import FileSystem

# Match bash tool output limits
MAX_OUTPUT_LENGTH = 30000


def create_namespace(
	browser_session: 'BrowserSession | None',
	file_system: 'FileSystem | None',
	existing_namespace: dict[str, Any],
) -> dict[str, Any]:
	"""Create execution namespace with browser access and helpers.

	Args:
		browser_session: Active browser session (may be None if not started)
		file_system: FileSystem for sandboxed file helpers
		existing_namespace: Previous namespace to carry forward
	"""
	namespace: dict[str, Any] = {**existing_namespace}

	# Browser access
	if browser_session is not None:
		namespace['browser'] = BrowserWrapper(browser_session)

	# Core modules (always available)
	namespace['json'] = json
	namespace['re'] = re
	namespace['csv'] = csv_module
	namespace['Path'] = Path
	namespace['asyncio'] = asyncio

	# Helper functions bound to file_system
	if file_system is not None:

		def _save_json(data: Any, path: str | None = None) -> str:
			"""Save data as JSON. Returns the absolute path.

			Args:
				data: Data to serialize as JSON.
				path: Filename/relative path (must be a string). Defaults to 'output.json'.
			"""
			if path is None or not isinstance(path, str):
				# Model sometimes passes (data, data) or forgets the path
				path = 'output.json'
			file_path = file_system.get_dir() / path
			file_path.parent.mkdir(parents=True, exist_ok=True)
			with open(file_path, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=2, ensure_ascii=False)
			return str(file_path)

		def _save_csv(data: list[dict], path: str | None = None) -> str:
			"""Save list of dicts as CSV. Returns the absolute path.

			Args:
				data: List of dicts to write as CSV rows.
				path: Filename/relative path (must be a string). Defaults to 'output.csv'.
			"""
			if path is None or not isinstance(path, str):
				path = 'output.csv'
			file_path = file_system.get_dir() / path
			file_path.parent.mkdir(parents=True, exist_ok=True)
			if not data:
				file_path.write_text('')
				return str(file_path)
			fieldnames = list(data[0].keys())
			with open(file_path, 'w', newline='', encoding='utf-8') as f:
				writer = csv_module.DictWriter(f, fieldnames=fieldnames)
				writer.writeheader()
				writer.writerows(data)
			return str(file_path)

		def _read_file(path: str) -> str:
			"""Read file from the working directory."""
			file_path = file_system.get_dir() / path
			return file_path.read_text(encoding='utf-8')

		namespace['save_json'] = _save_json
		namespace['save_csv'] = _save_csv
		namespace['read_file'] = _read_file

	# Add optional libraries if available
	try:
		from bs4 import BeautifulSoup

		namespace['BeautifulSoup'] = BeautifulSoup
	except ImportError:
		pass

	try:
		import requests

		namespace['requests'] = requests
	except ImportError:
		pass

	try:
		import pandas as pd  # type: ignore[import-not-found]

		namespace['pd'] = pd
		namespace['pandas'] = pd
	except ImportError:
		pass

	try:
		import numpy as np  # type: ignore[import-not-found]

		namespace['np'] = np
		namespace['numpy'] = np
	except ImportError:
		pass

	try:
		import matplotlib.pyplot as plt  # type: ignore[import-not-found]

		namespace['plt'] = plt
	except ImportError:
		pass

	try:
		from tabulate import tabulate as tabulate_fn

		namespace['tabulate'] = tabulate_fn
	except ImportError:
		pass

	return namespace


class _AsyncAutoAwaitTransformer(ast.NodeTransformer):
	"""AST transformer that auto-inserts await for common async patterns.

	Handles:
	- asyncio.run(coro) → await coro
	- loop.run_until_complete(coro) → await coro
	- browser.method(...) → await browser.method(...) (all BrowserWrapper methods are async)
	"""

	# All async methods on BrowserWrapper
	_BROWSER_ASYNC_METHODS = {
		'get_html', 'evaluate', 'navigate', 'click', 'input',
		'scroll', 'wait', 'send_keys', 'go_back',
	}

	def __init__(self) -> None:
		self.transformed = False

	def visit_Call(self, node: ast.Call) -> ast.AST:
		self.generic_visit(node)
		# Match asyncio.run(x)
		if (
			isinstance(node.func, ast.Attribute)
			and isinstance(node.func.value, ast.Name)
			and node.func.value.id == 'asyncio'
			and node.func.attr == 'run'
			and len(node.args) >= 1
		):
			self.transformed = True
			return ast.copy_location(ast.Await(value=node.args[0]), node)
		# Match loop.run_until_complete(x)
		if (
			isinstance(node.func, ast.Attribute)
			and node.func.attr == 'run_until_complete'
			and len(node.args) >= 1
		):
			self.transformed = True
			return ast.copy_location(ast.Await(value=node.args[0]), node)
		# Match browser.method(...) — all BrowserWrapper methods are async
		if (
			isinstance(node.func, ast.Attribute)
			and isinstance(node.func.value, ast.Name)
			and node.func.value.id == 'browser'
			and node.func.attr in self._BROWSER_ASYNC_METHODS
		):
			# Only add await if not already inside an Await node
			# (the parent check is handled by _visit_Await below)
			self.transformed = True
			return ast.copy_location(ast.Await(value=node), node)
		return node

	def visit_Await(self, node: ast.Await) -> ast.AST:
		"""Prevent double-await: if user already wrote `await browser.get_html()`,
		don't wrap it again."""
		# Process the inner value WITHOUT the browser auto-await
		if (
			isinstance(node.value, ast.Call)
			and isinstance(node.value.func, ast.Attribute)
			and isinstance(node.value.func.value, ast.Name)
			and node.value.func.value.id == 'browser'
			and node.value.func.attr in self._BROWSER_ASYNC_METHODS
		):
			# Already awaited — just visit args/kwargs but don't transform the call
			self.generic_visit(node.value)
			return node
		self.generic_visit(node)
		return node


async def execute_code(
	code: str,
	namespace: dict[str, Any],
) -> tuple[str | None, str | None]:
	"""Execute Python code in namespace.

	Handles async code automatically by detecting await expressions.
	Rewrites asyncio.run() calls to await expressions since we're
	already inside a running event loop.

	Returns:
		(output, error) tuple
	"""
	old_stdout = sys.stdout
	old_stderr = sys.stderr
	captured_stdout = io.StringIO()
	captured_stderr = io.StringIO()

	try:
		sys.stdout = captured_stdout
		sys.stderr = captured_stderr

		# Parse to check for await expressions
		try:
			tree = ast.parse(code, mode='exec')
		except SyntaxError as e:
			return None, f'SyntaxError: {e}'

		# Auto-await async patterns: asyncio.run(), browser.method(), etc.
		transformer = _AsyncAutoAwaitTransformer()
		tree = transformer.visit(tree)
		ast.fix_missing_locations(tree)

		# Check if code needs async wrapping (explicit await/async OR transformer added awaits)
		needs_async = transformer.transformed or any(
			isinstance(node, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for node in ast.walk(tree)
		)

		if needs_async:
			# Re-unparse the transformed AST back to source for async wrapping
			try:
				transformed_code = ast.unparse(tree)
			except Exception:
				transformed_code = code
			indented_code = textwrap.indent(transformed_code, '    ')
			wrapped = f'''async def __python_exec_async__():
{indented_code}
    return dict((k, v) for k, v in locals().items() if not k.startswith('_'))
'''
			exec(compile(wrapped, '<python>', 'exec'), namespace)  # noqa: S102

			# Get the async function and await it
			async_fn = namespace.pop('__python_exec_async__')
			result_locals = await async_fn()

			# Merge locals back to namespace (excluding internal vars)
			for k, v in result_locals.items():
				if not k.startswith('_'):
					namespace[k] = v
		else:
			# Execute directly for synchronous code
			compiled = compile(tree, '<python>', 'exec')
			exec(compiled, namespace)  # noqa: S102

		stdout_output = captured_stdout.getvalue()
		stderr_output = captured_stderr.getvalue()
		output = stdout_output
		if stderr_output:
			output = (output + '\n' if output else '') + f'[stderr]\n{stderr_output}'

		return output if output else None, None

	except Exception as e:
		import traceback

		error_msg = f'{type(e).__name__}: {e}'
		tb = traceback.format_exc()
		return captured_stdout.getvalue() or None, f'{error_msg}\n{tb}'

	finally:
		sys.stdout = old_stdout
		sys.stderr = old_stderr


def truncate_output(output: str, max_length: int = MAX_OUTPUT_LENGTH) -> str:
	"""Truncate output with midpoint ellipsis if it exceeds max length."""
	if len(output) <= max_length:
		return output
	half = max_length // 2
	return output[:half] + f'\n\n... [Output truncated - {len(output)} total characters] ...\n\n' + output[-half:]


def get_changed_variables(
	before: set[str],
	after: set[str],
	namespace: dict[str, Any],
) -> list[str]:
	"""Get list of new variable names, filtering out system vars."""
	new_vars = after - before

	system_vars = {
		'browser',
		'json',
		're',
		'csv',
		'Path',
		'asyncio',
		'save_json',
		'save_csv',
		'read_file',
		'BeautifulSoup',
		'requests',
		'pd',
		'pandas',
		'np',
		'numpy',
		'plt',
		'tabulate',
	}
	changed = [v for v in new_vars if not v.startswith('_') and v not in system_vars]

	return sorted(changed)
