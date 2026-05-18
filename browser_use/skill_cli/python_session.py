"""Jupyter-like persistent Python execution for browser-use CLI."""

import asyncio
import io
import traceback
import types
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal


def _make_safe_builtin_class() -> Any:
	"""Build the ``_SafeBuiltin`` callable class in an isolated namespace.

	A normal closure wrapper leaks this module's globals via ``wrapper.__globals__``
	(e.g. ``print.__globals__['io']`` or ``print.__globals__['Path']``). A callable
	class instance has no ``__globals__`` attribute at all, and by compiling the
	class inside an isolated ``exec`` namespace its methods' ``__globals__`` point
	to that isolated dict rather than this module — closing the escape.
	"""
	isolated: dict[str, Any] = {
		'__name__': '_safe_builtin_ns',
		'__builtins__': {
			'__build_class__': __build_class__,
			'object': object,
			'AttributeError': AttributeError,
		},
	}
	source = (
		'class _SafeBuiltin:\n'
		'    """Callable wrapper that hides __self__, __globals__, and the underlying fn."""\n'
		'    __slots__ = ("_fn",)\n'
		'    def __init__(self, fn):\n'
		'        object.__setattr__(self, "_fn", fn)\n'
		'    def __call__(self, *args, **kwargs):\n'
		'        return object.__getattribute__(self, "_fn")(*args, **kwargs)\n'
		'    def __getattribute__(self, name):\n'
		'        # Only __call__ is reachable from sandboxed code — no __self__,\n'
		'        # no __globals__, no _fn, no __class__-chain introspection.\n'
		'        if name == "__call__":\n'
		'            return object.__getattribute__(self, "__call__")\n'
		'        raise AttributeError(name)\n'
	)
	exec(source, isolated)
	return isolated['_SafeBuiltin']


_SafeBuiltin = _make_safe_builtin_class()


def _wrap_builtin(fn: Any) -> Any:
	"""Wrap a builtin function/type so ``__self__`` and ``__globals__`` don't leak."""
	return _SafeBuiltin(fn)


if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.skill_cli.actions import ActionHandler


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

	# Modules that must never be available in the execution namespace.
	_BLOCKED_MODULES = frozenset(
		{
			'os',
			'subprocess',
			'shutil',
			'sys',
			'importlib',
			'ctypes',
			'socket',
			'http',
			'ftplib',
			'smtplib',
			'webbrowser',
			'code',
			'codeop',
			'compileall',
			'multiprocessing',
			'signal',
			'tempfile',
			'builtins',
			'pathlib',
			'asyncio',
		}
	)

	def __post_init__(self) -> None:
		"""Initialize namespace with useful imports.

		Only safe, non-system-access modules are exposed. The ``os`` module and
		other modules that provide file-system, process, or network access are
		deliberately excluded to prevent arbitrary code execution beyond what the
		browser wrapper already provides.
		"""

		# Resolve the real import callable once so the guard doesn't depend on
		# this function's __globals__ (which would leak via __import__.__globals__).
		_real_import = __builtins__['__import__'] if isinstance(__builtins__, dict) else __import__
		_blocked = PythonSession._BLOCKED_MODULES

		def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
			"""Import guard that blocks dangerous modules."""
			top_level = name.split('.')[0]
			if top_level in _blocked:
				raise ImportError(f"import of '{name}' is not allowed in this environment")
			return _real_import(name, *args, **kwargs)

		safe_builtins: dict[str, Any] = {
			'__build_class__': __build_class__,
			# Wrap _safe_import in _SafeBuiltin so its __globals__ doesn't leak
			# this module's real __builtins__ (which would defeat the sandbox).
			'__import__': _SafeBuiltin(_safe_import),
			'print': print,
			'range': range,
			'len': len,
			'int': int,
			'float': float,
			'str': str,
			'bool': bool,
			'list': list,
			'dict': dict,
			'tuple': tuple,
			'set': set,
			'frozenset': frozenset,
			'bytes': bytes,
			'bytearray': bytearray,
			'type': type,
			'isinstance': isinstance,
			'issubclass': issubclass,
			'hasattr': hasattr,
			'getattr': getattr,
			'setattr': setattr,
			'delattr': delattr,
			'callable': callable,
			'iter': iter,
			'next': next,
			'enumerate': enumerate,
			'zip': zip,
			'map': map,
			'filter': filter,
			'sorted': sorted,
			'reversed': reversed,
			'min': min,
			'max': max,
			'sum': sum,
			'abs': abs,
			'round': round,
			'pow': pow,
			'divmod': divmod,
			'hash': hash,
			'id': id,
			'repr': repr,
			'ascii': ascii,
			'chr': chr,
			'ord': ord,
			'hex': hex,
			'oct': oct,
			'bin': bin,
			'format': format,
			'any': any,
			'all': all,
			'dir': dir,
			'vars': vars,
			'property': property,
			'staticmethod': staticmethod,
			'classmethod': classmethod,
			'super': super,
			'object': object,
			'Exception': Exception,
			'BaseException': BaseException,
			'TypeError': TypeError,
			'ValueError': ValueError,
			'KeyError': KeyError,
			'IndexError': IndexError,
			'AttributeError': AttributeError,
			'RuntimeError': RuntimeError,
			'StopIteration': StopIteration,
			'GeneratorExit': GeneratorExit,
			'NotImplementedError': NotImplementedError,
			'ImportError': ImportError,
			'FileNotFoundError': FileNotFoundError,
			'OSError': OSError,
			'IOError': IOError,
			'ArithmeticError': ArithmeticError,
			'ZeroDivisionError': ZeroDivisionError,
			'OverflowError': OverflowError,
			'LookupError': LookupError,
			'NameError': NameError,
			'SyntaxError': SyntaxError,
			'True': True,
			'False': False,
			'None': None,
		}

		# Wrap builtin functions so __self__ doesn't leak the builtins module
		for key, val in safe_builtins.items():
			if isinstance(val, types.BuiltinFunctionType):
				safe_builtins[key] = _wrap_builtin(val)

		self.namespace.update(
			{
				'__name__': '__main__',
				'__doc__': None,
				'__builtins__': safe_builtins,
				'json': __import__('json'),
				're': __import__('re'),
			}
		)

	def execute(
		self,
		code: str,
		browser_session: 'BrowserSession',
		loop: asyncio.AbstractEventLoop | None = None,
		actions: 'ActionHandler | None' = None,
	) -> ExecutionResult:
		"""Execute code in persistent namespace.

		The `browser` variable is injected into the namespace before each execution,
		providing a convenient wrapper around the BrowserSession.

		Args:
			code: Python code to execute
			browser_session: The browser session for browser operations
			loop: The event loop for async operations (required for browser access)
			actions: Optional ActionHandler for direct execution (no event bus)
		"""
		# Inject browser wrapper with the event loop for async operations
		if loop is not None and actions is not None:
			self.namespace['browser'] = BrowserWrapper(browser_session, loop, actions)
		self.execution_count += 1

		stdout = io.StringIO()
		stderr = io.StringIO()

		try:
			with redirect_stdout(stdout), redirect_stderr(stderr):
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
		skip = {'__name__', '__doc__', '__builtins__', 'json', 're', 'browser'}
		return {k: type(v).__name__ for k, v in self.namespace.items() if not k.startswith('_') and k not in skip}


class BrowserWrapper:
	"""Convenient browser access for Python code.

	Provides synchronous methods that wrap async BrowserSession operations.
	Runs coroutines on the server's event loop using run_coroutine_threadsafe.
	"""

	def __init__(self, session: 'BrowserSession', loop: asyncio.AbstractEventLoop, actions: 'ActionHandler') -> None:
		self._session = session
		self._loop = loop
		self._actions = actions

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
		await self._actions.navigate(url)

	def click(self, index: int) -> None:
		"""Click element by index."""
		self._run(self._click_async(index))

	async def _click_async(self, index: int) -> None:
		node = await self._session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'Element index {index} not found')
		await self._actions.click_element(node)

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
		node = await self._session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'Element index {index} not found')
		await self._actions.click_element(node)
		await self._actions.type_text(node, text)

	def upload(self, index: int, path: str) -> None:
		"""Upload a file to a file input element."""
		self._run(self._upload_async(index, path))

	async def _upload_async(self, index: int, path: str) -> None:
		from pathlib import Path as P

		file_path = str(P(path).expanduser().resolve())
		p = P(file_path)
		if not p.exists():
			raise FileNotFoundError(f'File not found: {file_path}')
		if not p.is_file():
			raise ValueError(f'Not a file: {file_path}')
		if p.stat().st_size == 0:
			raise ValueError(f'File is empty (0 bytes): {file_path}')

		node = await self._session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'Element index {index} not found')

		file_input_node = self._session.find_file_input_near_element(node)
		if file_input_node is None:
			raise ValueError(f'Element {index} is not a file input and no file input found nearby')

		await self._actions.upload_file(file_input_node, file_path)

	def scroll(self, direction: Literal['up', 'down', 'left', 'right'] = 'down', amount: int = 500) -> None:
		"""Scroll the page."""
		self._run(self._scroll_async(direction, amount))

	async def _scroll_async(self, direction: Literal['up', 'down', 'left', 'right'], amount: int) -> None:
		await self._actions.scroll(direction, amount)

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
		await self._actions.send_keys(keys)

	def back(self) -> None:
		"""Go back in history."""
		self._run(self._back_async())

	async def _back_async(self) -> None:
		await self._actions.go_back()

	def wait(self, seconds: float) -> None:
		"""Wait for specified seconds."""
		import time

		time.sleep(seconds)

	def extract(self, query: str) -> Any:
		"""Extract data using LLM (requires API key)."""
		# This would need LLM integration
		raise NotImplementedError('extract() requires LLM integration - use agent.run() instead')
