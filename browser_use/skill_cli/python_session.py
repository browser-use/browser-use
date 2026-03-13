"""Jupyter-like persistent Python execution for browser-use CLI."""

import ast
import asyncio
import io
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession

SAFE_CODE_EXECUTION = os.getenv('BROWSER_USE_SAFE_CODE_EXECUTION') == '1'

SAFE_BUILTINS = {'print': print, 'len': len, 'range': range}


def _safe_exec(code: str, parent_namespace: dict[str, Any]) -> None:
	"""Execute code in an isolated namespace. Blocks imports and dangerous operations.

	Dangerous objects (os, Path, etc.) from parent_namespace are NOT visible.
	Only a minimal builtin allowlist is exposed. Safe variables are copied back after execution.
	"""
	tree = ast.parse(code)

	# Explicit import blocking — unambiguous restriction for reviewers
	_DISALLOWED_NODES = (ast.Import, ast.ImportFrom)
	for node in ast.walk(tree):
		if isinstance(node, _DISALLOWED_NODES):
			raise ValueError('Import statements are not allowed in safe execution mode')

	allowed_nodes = (
		ast.Module,
		ast.Expr,
		ast.Assign,
		ast.AugAssign,
		ast.Name,
		ast.Load,
		ast.Store,
		ast.Constant,
		ast.BinOp,
		ast.UnaryOp,
		ast.Call,
		ast.Attribute,
		ast.Dict,
		ast.List,
		ast.Tuple,
		ast.Subscript,
		ast.Index,
		ast.Slice,
		ast.ExtSlice,
		# BinOp operators
		ast.Add,
		ast.Sub,
		ast.Mult,
		ast.Div,
		ast.FloorDiv,
		ast.Mod,
		ast.Pow,
		ast.LShift,
		ast.RShift,
		ast.BitOr,
		ast.BitXor,
		ast.BitAnd,
		ast.MatMult,
		# UnaryOp operators
		ast.UAdd,
		ast.USub,
		ast.Not,
		ast.Invert,
	)
	_DANGEROUS_NAMES = frozenset({'__import__', 'open', 'exec', 'eval', 'compile', 'globals', 'locals', 'vars'})
	# Block introspection attributes that enable sandbox escape (e.g. __class__.__subclasses__)
	_DANGEROUS_ATTRS = frozenset(
		{
			'__class__',
			'__bases__',
			'__base__',
			'__mro__',
			'__subclasses__',
			'__globals__',
			'__builtins__',
			'__code__',
			'__closure__',
			'__self__',
			'func_globals',
			'f_globals',
			'f_locals',
			'__doc__',
			'__dict__',
		}
	)

	def _get_call_name(n: ast.AST) -> str | None:
		if isinstance(n, ast.Name):
			return n.id
		if isinstance(n, ast.Attribute):
			return _get_call_name(n.value)
		return None

	for node in ast.walk(tree):
		if not isinstance(node, allowed_nodes):
			raise ValueError(f'Disallowed operation: {type(node).__name__}')
		if isinstance(node, ast.Call):
			name = _get_call_name(node.func)
			if name in _DANGEROUS_NAMES:
				raise ValueError(f'Disallowed function: {name}')
		if isinstance(node, ast.Attribute):
			if node.attr in _DANGEROUS_ATTRS:
				raise ValueError(f'Disallowed attribute: {node.attr}')

	# Build safe namespace: browser (if present) + user vars from previous runs
	_DANGEROUS_PARENT_KEYS = frozenset({'__name__', '__doc__', 'json', 're', 'os', 'Path', 'asyncio'})
	_SAFE_VALUE_TYPES = (type(None), bool, int, float, str, bytes, tuple, list, dict, set, range)

	safe_locals: dict[str, object] = {}
	for k, v in parent_namespace.items():
		if k == 'browser':
			safe_locals[k] = v
		elif k not in _DANGEROUS_PARENT_KEYS and not k.startswith('_'):
			if isinstance(v, _SAFE_VALUE_TYPES):
				safe_locals[k] = v
	# Fresh builtins per execution to avoid cross-call mutation
	safe_globals = {'__builtins__': dict(SAFE_BUILTINS)}
	exec(compile(tree, '<safe>', 'exec'), safe_globals, safe_locals)

	# Persist user vars for next run; only copy safe types to avoid leaking objects
	for k, v in safe_locals.items():
		if k != 'browser' and not k.startswith('_') and isinstance(v, _SAFE_VALUE_TYPES):
			parent_namespace[k] = v


@dataclass
class ExecutionResult:
	"""Result of Python code execution."""

	success: bool
	output: str = ''
	error: str | None = None


@dataclass
class PythonSession:
	"""Jupyter-like persistent Python execution.

	Maintains a namespace across multiple code executions, allowing variables
	to persist between commands. Provides a `browser` object for browser control.
	"""

	namespace: dict[str, Any] = field(default_factory=dict)
	execution_count: int = 0
	history: list[tuple[str, ExecutionResult]] = field(default_factory=list)

	def __post_init__(self) -> None:
		"""Initialize namespace with useful imports."""
		self.namespace.update(
			{
				'__name__': '__main__',
				'__doc__': None,
				'json': __import__('json'),
				're': __import__('re'),
				'os': __import__('os'),
				'Path': Path,
				'asyncio': asyncio,
			}
		)

	def execute(
		self, code: str, browser_session: 'BrowserSession', loop: asyncio.AbstractEventLoop | None = None
	) -> ExecutionResult:
		"""Execute code in persistent namespace.

		The `browser` variable is injected into the namespace before each execution,
		providing a convenient wrapper around the BrowserSession.

		Args:
			code: Python code to execute
			browser_session: The browser session for browser operations
			loop: The event loop for async operations (required for browser access)
		"""
		# Inject browser wrapper with the event loop for async operations
		if loop is not None:
			self.namespace['browser'] = BrowserWrapper(browser_session, loop)
		self.execution_count += 1

		stdout = io.StringIO()
		stderr = io.StringIO()

		try:
			with redirect_stdout(stdout), redirect_stderr(stderr):
				if SAFE_CODE_EXECUTION:
					_safe_exec(code, self.namespace)
				else:
					try:
						# First try to compile as expression (for REPL-like behavior)
						compiled = compile(code, '<input>', 'eval')
						result = eval(compiled, self.namespace)
						if result is not None:
							print(repr(result))
					except SyntaxError:
						# Compile as statements
						compiled = compile(code, '<input>', 'exec')
						exec(compiled, self.namespace)

			output = stdout.getvalue()
			if stderr.getvalue():
				output += stderr.getvalue()

			result = ExecutionResult(success=True, output=output)

		except Exception as e:
			output = stdout.getvalue()
			error_msg = traceback.format_exc()
			result = ExecutionResult(success=False, output=output, error=error_msg)

		self.history.append((code, result))
		return result

	def reset(self) -> None:
		"""Clear namespace and history."""
		self.namespace.clear()
		self.history.clear()
		self.execution_count = 0
		self.__post_init__()

	def get_variables(self) -> dict[str, str]:
		"""Get user-defined variables and their types."""
		skip = {'__name__', '__doc__', 'json', 're', 'os', 'Path', 'asyncio', 'browser'}
		return {k: type(v).__name__ for k, v in self.namespace.items() if not k.startswith('_') and k not in skip}


class BrowserWrapper:
	"""Convenient browser access for Python code.

	Provides synchronous methods that wrap async BrowserSession operations.
	Runs coroutines on the server's event loop using run_coroutine_threadsafe.
	"""

	def __init__(self, session: 'BrowserSession', loop: asyncio.AbstractEventLoop) -> None:
		self._session = session
		self._loop = loop

	def _run(self, coro: Any) -> Any:
		"""Run coroutine on the server's event loop."""
		future = asyncio.run_coroutine_threadsafe(coro, self._loop)
		return future.result(timeout=60)

	@property
	def url(self) -> str:
		"""Get current page URL."""
		return self._run(self._get_url())

	async def _get_url(self) -> str:
		state = await self._session.get_browser_state_summary(include_screenshot=False)
		return state.url if state else ''

	@property
	def title(self) -> str:
		"""Get current page title."""
		return self._run(self._get_title())

	async def _get_title(self) -> str:
		state = await self._session.get_browser_state_summary(include_screenshot=False)
		return state.title if state else ''

	def goto(self, url: str) -> None:
		"""Navigate to URL."""
		self._run(self._goto_async(url))

	async def _goto_async(self, url: str) -> None:
		from browser_use.browser.events import NavigateToUrlEvent

		await self._session.event_bus.dispatch(NavigateToUrlEvent(url=url))

	def click(self, index: int) -> None:
		"""Click element by index."""
		self._run(self._click_async(index))

	async def _click_async(self, index: int) -> None:
		from browser_use.browser.events import ClickElementEvent

		node = await self._session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'Element index {index} not found')
		await self._session.event_bus.dispatch(ClickElementEvent(node=node))

	def type(self, text: str) -> None:
		"""Type text into focused element."""
		self._run(self._type_async(text))

	async def _type_async(self, text: str) -> None:
		cdp_session = await self._session.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			raise RuntimeError('No active browser session')
		await cdp_session.cdp_client.send.Input.insertText(
			params={'text': text},
			session_id=cdp_session.session_id,
		)

	def input(self, index: int, text: str) -> None:
		"""Click element and type text."""
		self._run(self._input_async(index, text))

	async def _input_async(self, index: int, text: str) -> None:
		from browser_use.browser.events import ClickElementEvent, TypeTextEvent

		node = await self._session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'Element index {index} not found')
		await self._session.event_bus.dispatch(ClickElementEvent(node=node))
		await self._session.event_bus.dispatch(TypeTextEvent(node=node, text=text))

	def scroll(self, direction: Literal['up', 'down', 'left', 'right'] = 'down', amount: int = 500) -> None:
		"""Scroll the page."""
		self._run(self._scroll_async(direction, amount))

	async def _scroll_async(self, direction: Literal['up', 'down', 'left', 'right'], amount: int) -> None:
		from browser_use.browser.events import ScrollEvent

		await self._session.event_bus.dispatch(ScrollEvent(direction=direction, amount=amount))

	def screenshot(self, path: str | None = None) -> bytes:
		"""Take screenshot, optionally save to file."""
		data = self._run(self._session.take_screenshot())
		if path:
			Path(path).write_bytes(data)
		return data

	@property
	def html(self) -> str:
		"""Get page HTML."""
		return self._run(self._get_html())

	async def _get_html(self) -> str:
		cdp_session = await self._session.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			return ''
		# Get the document root
		doc = await cdp_session.cdp_client.send.DOM.getDocument(
			params={},
			session_id=cdp_session.session_id,
		)
		if not doc or 'root' not in doc:
			return ''
		# Get outer HTML of the root node
		result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
			params={'nodeId': doc['root']['nodeId']},
			session_id=cdp_session.session_id,
		)
		return result.get('outerHTML', '') if result else ''

	def keys(self, keys: str) -> None:
		"""Send keyboard keys."""
		self._run(self._keys_async(keys))

	async def _keys_async(self, keys: str) -> None:
		from browser_use.browser.events import SendKeysEvent

		await self._session.event_bus.dispatch(SendKeysEvent(keys=keys))

	def back(self) -> None:
		"""Go back in history."""
		self._run(self._back_async())

	async def _back_async(self) -> None:
		from browser_use.browser.events import GoBackEvent

		await self._session.event_bus.dispatch(GoBackEvent())

	def wait(self, seconds: float) -> None:
		"""Wait for specified seconds."""
		import time

		time.sleep(seconds)

	def extract(self, query: str) -> Any:
		"""Extract data using LLM (requires API key)."""
		# This would need LLM integration
		raise NotImplementedError('extract() requires LLM integration - use agent.run() instead')
