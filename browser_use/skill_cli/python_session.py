"""Jupyter-like persistent Python execution for browser-use CLI."""

import asyncio
import io
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession


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

	def extract(
		self,
		query: str,
		output_schema: dict[str, Any] | None = None,
		extract_links: bool = False,
		start_from_char: int = 0,
	) -> Any:
		"""Extract page data using the configured CLI LLM.

		Returns structured data when ``output_schema`` is provided, otherwise returns
		the extraction text payload from the page.
		"""
		return self._run(
			self._extract_async(
				query=query,
				output_schema=output_schema,
				extract_links=extract_links,
				start_from_char=start_from_char,
			)
		)

	async def _extract_async(
		self,
		query: str,
		output_schema: dict[str, Any] | None = None,
		extract_links: bool = False,
		start_from_char: int = 0,
	) -> Any:
		from browser_use.agent.views import ActionResult
		from browser_use.filesystem.file_system import FileSystem
		from browser_use.skill_cli.commands.agent import get_llm
		from browser_use.tools.service import Tools

		page_extraction_llm = get_llm()
		if page_extraction_llm is None:
			raise RuntimeError(
				'No LLM configured for browser.extract(). '
				'Set BROWSER_USE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY.'
			)

		with tempfile.TemporaryDirectory(prefix='browser-use-python-extract-') as tmp:
			file_system = FileSystem(tmp)
			tools = Tools()
			result = await tools.extract(
				query=query,
				extract_links=extract_links,
				start_from_char=start_from_char,
				output_schema=output_schema,
				browser_session=self._session,
				page_extraction_llm=page_extraction_llm,
				file_system=file_system,
			)

		assert isinstance(result, ActionResult)
		if result.error:
			raise RuntimeError(result.error)

		if output_schema is not None and result.metadata:
			extraction_result = result.metadata.get('extraction_result')
			if isinstance(extraction_result, dict) and 'data' in extraction_result:
				return extraction_result['data']

		if result.extracted_content is not None:
			return result.extracted_content
		return result.long_term_memory
