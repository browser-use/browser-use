from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import json
import logging
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem

logger = logging.getLogger(__name__)

_LAST_EXPR_NAME = '__browser_use_last_expr__'


class CodeExecutionResult(BaseModel):
	"""Bounded result returned by one in-process Python cell."""

	output: str = ''
	error: str | None = None
	images: list[dict[str, Any]] = Field(default_factory=list)
	timed_out: bool = False
	duration_seconds: float = 0.0


class JavaScriptErrorDetails(BaseModel):
	"""Structured JavaScript failure returned by Chrome Runtime.evaluate."""

	exception_type: str = 'JavaScriptError'
	message: str
	line: int | None = None
	column: int | None = None
	source_excerpt: str | None = None
	stack: str | None = None
	url: str | None = None
	session_id: str | None = None

	def format_for_model(self) -> str:
		"""Render a compact diagnostic without discarding Chrome's useful details."""
		location = ''
		if self.line is not None:
			location = f' at line {self.line}'
			if self.column is not None:
				location += f', column {self.column}'
		parts = [f'{self.exception_type}{location}: {self.message}']
		if self.url:
			parts.append(f'Script URL: {self.url}')
		if self.source_excerpt:
			parts.append(f'Source:\n{self.source_excerpt}')
		if self.stack:
			parts.append(f'Stack:\n{self.stack}')
		if self.session_id:
			parts.append(f'CDP session: {self.session_id}')
		return '\n'.join(parts)


class JavaScriptEvaluationError(RuntimeError):
	"""Exception carrying structured JavaScript error details."""

	def __init__(self, details: JavaScriptErrorDetails) -> None:
		self.details = details
		super().__init__(details.format_for_model())


def _javascript_source_excerpt(expression: str, zero_based_line: int | None) -> str | None:
	"""Return a bounded source window around a zero-based CDP line number."""
	lines = expression.splitlines()
	if not lines:
		return None
	if zero_based_line is None:
		snippet = expression.strip().replace('\n', '\\n')
		return snippet[:500] + ('...' if len(snippet) > 500 else '')
	line_index = max(0, min(zero_based_line, len(lines) - 1))
	start = max(0, line_index - 1)
	end = min(len(lines), line_index + 2)
	return '\n'.join(f'{">" if index == line_index else " "} {index + 1}: {lines[index]}' for index in range(start, end))


def _decode_unserializable_javascript_value(value: str) -> Any:
	if value == 'NaN':
		return float('nan')
	if value == 'Infinity':
		return float('inf')
	if value == '-Infinity':
		return float('-inf')
	if value == '-0':
		return -0.0
	if value.endswith('n'):
		return int(value[:-1])
	return value


class DirectCdpBridge:
	"""Direct BrowserSession CDP routing shared by evaluate and Python code mode."""

	_ROOT_CDP_DOMAINS = {'Browser', 'Target', 'SystemInfo'}

	def __init__(self, browser_session: BrowserSession) -> None:
		self.browser_session = browser_session

	async def send(
		self,
		method: Any,
		params: Any = None,
		session: Any = None,
		request_timeout: float = 30.0,
	) -> dict[str, Any]:
		"""Send an arbitrary raw CDP command with root/target/session resolution."""
		if not isinstance(method, str) or '.' not in method:
			raise ValueError('CDP method must be a string like "Page.navigate" or "Runtime.evaluate".')
		if params is None:
			params = {}
		if not isinstance(params, dict):
			raise TypeError('CDP params must be a dict or None.')
		session_id = await self.resolve_session_id(method, session)
		return await self._send_resolved(method, params, session_id, request_timeout)

	async def _send_resolved(
		self,
		method: str,
		params: dict[str, Any],
		session_id: str | None,
		request_timeout: float,
	) -> dict[str, Any]:
		request_timeout = max(0.1, float(request_timeout))
		started_at = time.monotonic()
		logger.debug(f'🐍 Direct CDP request started: {method}')
		try:
			async with asyncio.timeout(request_timeout):
				return await self.browser_session.cdp_client.send_raw(
					method=method,
					params=params,
					session_id=session_id,
				)
		except TimeoutError as exc:
			raise TimeoutError(f'{method} did not return within {request_timeout:g}s.') from exc
		finally:
			duration = time.monotonic() - started_at
			if duration >= 5:
				logger.info(f'🐍 Direct CDP request {method} returned after {duration:.1f}s')
			else:
				logger.debug(f'🐍 Direct CDP request completed: {method} ({duration:.3f}s)')

	async def resolve_session_id(self, method: str, session: Any) -> str | None:
		"""Resolve root, raw session, target, or short tab identifiers."""
		if session is False or session == 'root':
			return None
		if hasattr(session, 'session_id'):
			return str(session.session_id)
		if session is None:
			if method.split('.', 1)[0] in self._ROOT_CDP_DOMAINS:
				return None
			cdp_session = await self.browser_session.get_or_create_cdp_session(focus=False)
			return str(cdp_session.session_id)

		session_key = str(session)
		session_manager = self.browser_session.session_manager
		if session_manager is not None:
			cdp_session = session_manager.get_session(session_key)
			if cdp_session is not None:
				return str(cdp_session.session_id)
			for session_id, cdp_session in session_manager.get_all_sessions().items():
				if str(session_id).endswith(session_key):
					return str(cdp_session.session_id)
			for target_id in session_manager.get_all_target_ids():
				if str(target_id) == session_key or str(target_id).endswith(session_key):
					cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)
					return str(cdp_session.session_id)

		try:
			target_id = await self.browser_session.get_target_id_from_tab_id(session_key)
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target_id, focus=False)
			return str(cdp_session.session_id)
		except Exception as exc:
			raise ValueError(f'Could not resolve CDP session or target for {session_key!r}.') from exc

	async def evaluate_javascript(
		self,
		expression: str,
		await_promise: bool = True,
		return_by_value: bool = True,
		session: Any = None,
		timeout: float = 15.0,
	) -> Any:
		"""Evaluate page JavaScript with function invocation and actionable errors."""
		timeout = max(0.1, float(timeout))
		session_id = await self.resolve_session_id('Runtime.evaluate', session)
		try:
			result = await self._evaluate_once(expression, await_promise, return_by_value, session_id, timeout)
		except JavaScriptEvaluationError as exc:
			if 'Illegal return statement' not in exc.details.message:
				raise
			wrapped = f'(function(){{{expression}}})()'
			result = await self._evaluate_once(wrapped, await_promise, return_by_value, session_id, timeout)

		remote_object = result.get('result', {})
		if return_by_value and remote_object.get('type') == 'function':
			object_id = remote_object.get('objectId')
			if object_id:
				result = await self._send_resolved(
					'Runtime.callFunctionOn',
					{
						'objectId': object_id,
						'functionDeclaration': 'function() { return this(); }',
						'awaitPromise': await_promise,
						'returnByValue': True,
						'timeout': timeout * 1000,
					},
					session_id,
					timeout + 5,
				)
			else:
				result = await self._evaluate_once(
					f'Promise.resolve((({expression}))()).then(value => value)',
					await_promise,
					True,
					session_id,
					timeout,
				)
			self._raise_for_javascript_error(result, expression, session_id)
			remote_object = result.get('result', {})

		if not return_by_value:
			return remote_object
		if 'value' in remote_object:
			return remote_object['value']
		if 'unserializableValue' in remote_object:
			return _decode_unserializable_javascript_value(str(remote_object['unserializableValue']))
		return None

	async def _evaluate_once(
		self,
		expression: str,
		await_promise: bool,
		return_by_value: bool,
		session_id: str | None,
		timeout: float,
	) -> dict[str, Any]:
		result = await self._send_resolved(
			'Runtime.evaluate',
			{
				'expression': expression,
				'awaitPromise': await_promise,
				'returnByValue': return_by_value,
				'timeout': timeout * 1000,
			},
			session_id,
			timeout + 5,
		)
		self._raise_for_javascript_error(result, expression, session_id)
		return result

	@staticmethod
	def _raise_for_javascript_error(result: dict[str, Any], expression: str, session_id: str | None) -> None:
		remote_object_value = result.get('result')
		remote_object: dict[str, Any] = remote_object_value if isinstance(remote_object_value, dict) else {}
		details_value = result.get('exceptionDetails')
		details: dict[str, Any] = details_value if isinstance(details_value, dict) else {}
		if not details and remote_object.get('subtype') != 'error' and not remote_object.get('wasThrown'):
			return

		exception_value = details.get('exception')
		exception: dict[str, Any] = exception_value if isinstance(exception_value, dict) else {}
		description = remote_object.get('description') or exception.get('description')
		if not description and 'value' in exception:
			description = str(exception['value'])
		description = description or exception.get('className') or details.get('text') or 'JavaScript evaluation failed'
		description_lines = str(description).splitlines()
		message = description_lines[0] if description_lines else 'JavaScript evaluation failed'
		exception_type = (
			remote_object.get('className')
			or exception.get('className')
			or (message.split(':', 1)[0] if ':' in message else 'JavaScriptError')
		)
		type_prefix = f'{exception_type}:'
		if message.startswith(type_prefix):
			message = message[len(type_prefix) :].strip()

		stack_lines = description_lines[1:]
		stack_trace = details.get('stackTrace') or {}
		for frame in stack_trace.get('callFrames') or []:
			function_name = frame.get('functionName') or '<anonymous>'
			frame_url = frame.get('url') or '<anonymous>'
			line = int(frame.get('lineNumber', 0)) + 1
			column = int(frame.get('columnNumber', 0)) + 1
			stack_lines.append(f'at {function_name} ({frame_url}:{line}:{column})')

		zero_based_line = details.get('lineNumber')
		zero_based_column = details.get('columnNumber')
		error = JavaScriptErrorDetails(
			exception_type=str(exception_type),
			message=message,
			line=int(zero_based_line) + 1 if zero_based_line is not None else None,
			column=int(zero_based_column) + 1 if zero_based_column is not None else None,
			source_excerpt=_javascript_source_excerpt(expression, int(zero_based_line) if zero_based_line is not None else None),
			stack='\n'.join(dict.fromkeys(stack_lines)) or None,
			url=details.get('url') or None,
			session_id=session_id,
		)
		raise JavaScriptEvaluationError(error)


class _BoundedOutput:
	"""Retain a bounded head and tail without accumulating unlimited output."""

	def __init__(self, max_chars: int) -> None:
		self.max_chars = max(1, max_chars)
		self.head_limit = max(1, self.max_chars * 2 // 3)
		self.tail_limit = max(1, self.max_chars - self.head_limit)
		self.head = ''
		self.tail = ''
		self.total_chars = 0

	def write(self, text: str) -> None:
		self.total_chars += len(text)
		remainder = text
		if len(self.head) < self.head_limit:
			take = min(self.head_limit - len(self.head), len(remainder))
			self.head += remainder[:take]
			remainder = remainder[take:]
		if remainder:
			self.tail = (self.tail + remainder)[-self.tail_limit :]

	def render(self) -> str:
		if self.total_chars <= self.max_chars:
			return self.head + self.tail
		omitted = max(0, self.total_chars - len(self.head) - len(self.tail))
		return f'{self.head}\n... [{omitted} characters omitted] ...\n{self.tail}'


def _compile_cell(code: str) -> Any:
	"""Compile a cell with top-level await and automatic final-expression display."""
	module = ast.parse(code, mode='exec')
	if module.body and isinstance(module.body[-1], ast.Expr):
		expression = module.body[-1]
		module.body[-1] = ast.copy_location(
			ast.Assign(targets=[ast.Name(id=_LAST_EXPR_NAME, ctx=ast.Store())], value=expression.value),
			expression,
		)
		ast.fix_missing_locations(module)
	return compile(module, '<browser-use-run-python>', 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def _format_value(value: Any) -> str:
	if isinstance(value, str):
		return value
	try:
		return json.dumps(value, ensure_ascii=False, indent=2, default=str)
	except (TypeError, ValueError):
		return repr(value)


class InProcessPythonExecutor:
	"""Execute trusted Python directly beside BrowserSession and its CDP client."""

	def __init__(
		self,
		browser_session: BrowserSession,
		timeout: float = 30.0,
		max_output_chars: int = 12000,
		file_system: FileSystem | None = None,
		workspace_dir: str | Path | None = None,
	) -> None:
		self.browser_session = browser_session
		self.timeout = timeout
		self.max_output_chars = max_output_chars
		self.workspace_dir = (
			file_system.get_dir()
			if file_system is not None
			else Path(workspace_dir)
			if workspace_dir is not None
			else Path(tempfile.mkdtemp(prefix='browser-use-code-workspace-'))
		)
		self.workspace_dir.mkdir(parents=True, exist_ok=True)
		self.direct_cdp = DirectCdpBridge(browser_session)
		self._lock = asyncio.Lock()
		self._event_lock = asyncio.Lock()
		self._event_waiters: dict[str, list[tuple[asyncio.Future[dict[str, Any]], str | None, bool]]] = {}
		self._event_original_handlers: dict[str, Any] = {}
		self._event_wrappers: dict[str, Any] = {}

	async def run(self, code: str) -> CodeExecutionResult:
		"""Execute one trusted cell with cooperative timeout handling."""
		async with self._lock:
			started_at = time.monotonic()
			output = _BoundedOutput(self.max_output_chars)
			images: list[dict[str, Any]] = []
			namespace = self._create_namespace(output, images)
			cell_task = asyncio.create_task(
				self._execute_cell(code, namespace, output),
				name='browser-use-run-python',
			)

			logger.info(f'🐍 In-process Python cell started (timeout={self.timeout:g}s)')
			try:
				done, _ = await asyncio.wait({cell_task}, timeout=self.timeout)
			except asyncio.CancelledError:
				await self._cancel_and_join_cell(cell_task)
				logger.info('🐍 In-process Python cell cancelled with the agent action')
				raise

			if not done:
				await self._cancel_and_join_cell(cell_task)
				duration = time.monotonic() - started_at
				return CodeExecutionResult(
					output=output.render(),
					error=(
						f'Python cell exceeded {self.timeout:g}s. Cooperative cancellation was requested; '
						'kill the agent worker if it remains unresponsive.'
					),
					images=images,
					timed_out=True,
					duration_seconds=duration,
				)

			duration = time.monotonic() - started_at
			try:
				cell_task.result()
			except asyncio.CancelledError:
				error = 'Python cell cancelled itself.'
				logger.warning(f'🐍 In-process Python cell cancelled itself after {duration:.1f}s')
				return CodeExecutionResult(
					output=output.render(),
					error=error,
					images=images,
					duration_seconds=duration,
				)
			except BaseException as exc:
				error = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
				logger.warning(f'🐍 In-process Python cell failed after {duration:.1f}s')
				return CodeExecutionResult(
					output=output.render(),
					error=self._truncate(error),
					images=images,
					duration_seconds=duration,
				)

			logger.info(f'🐍 In-process Python cell completed in {duration:.1f}s')
			return CodeExecutionResult(
				output=output.render(),
				images=images,
				duration_seconds=duration,
			)

	async def _execute_cell(self, code: str, namespace: dict[str, Any], output: _BoundedOutput) -> None:
		compiled = _compile_cell(code)
		result = eval(compiled, namespace, namespace)
		if inspect.isawaitable(result):
			await result
		last_expression = namespace.pop(_LAST_EXPR_NAME, None)
		if last_expression is not None:
			output.write(_format_value(last_expression) + '\n')

	def _create_namespace(self, output: _BoundedOutput, images: list[dict[str, Any]]) -> dict[str, Any]:
		async def cdp(
			method: str,
			params: dict[str, Any] | None = None,
			session: Any = None,
			request_timeout: float = 30.0,
		) -> dict[str, Any]:
			return await self.direct_cdp.send(method, params, session, request_timeout)

		async def js(
			expression: str,
			await_promise: bool = True,
			return_by_value: bool = True,
			session: Any = None,
			timeout: float = 15.0,
		) -> Any:
			return await self.direct_cdp.evaluate_javascript(
				expression=expression,
				await_promise=await_promise,
				return_by_value=return_by_value,
				session=session,
				timeout=timeout,
			)

		async def tabs() -> list[dict[str, Any]]:
			return await self._get_tabs()

		async def targets() -> list[dict[str, Any]]:
			return await self._get_targets()

		async def wait_for_event(method: str, timeout: float = 30.0, session: Any = None) -> dict[str, Any]:
			return await self._wait_for_event(method, session, timeout)

		def captured_print(
			*values: Any,
			sep: str = ' ',
			end: str = '\n',
			file: Any = None,
			flush: bool = False,
		) -> None:
			if file is not None:
				builtins.print(*values, sep=sep, end=end, file=file, flush=flush)
				return
			output.write(sep.join(str(value) for value in values) + end)

		def workspace_open(file: Any, *args: Any, **kwargs: Any) -> Any:
			if isinstance(file, (str, Path)):
				path = Path(file)
				if not path.is_absolute():
					file = self.workspace_dir / path
			return builtins.open(file, *args, **kwargs)

		def show_image(data: str, name: str = 'image.png') -> dict[str, Any]:
			image = {'name': name, 'data': data}
			images.append(image)
			return image

		return {
			'__name__': '__browser_use_code__',
			'asyncio': asyncio,
			'cdp': cdp,
			'js': js,
			'tabs': tabs,
			'targets': targets,
			'wait_for_event': wait_for_event,
			'print': captured_print,
			'open': workspace_open,
			'show_image': show_image,
			'images': images,
			'Path': Path,
			'WORKSPACE_DIR': self.workspace_dir,
		}

	async def _get_tabs(self) -> list[dict[str, Any]]:
		return [tab.model_dump(mode='json') for tab in await self.browser_session.get_tabs()]

	async def _get_targets(self) -> list[dict[str, Any]]:
		session_manager = self.browser_session.session_manager
		if session_manager is None:
			return []
		targets: list[dict[str, Any]] = []
		target_sessions = session_manager.get_target_sessions_mapping()
		for target_id in session_manager.get_all_target_ids():
			target = session_manager.get_target(target_id)
			if target is None:
				continue
			targets.append(
				{
					'target_id': str(target_id),
					'tab_id': str(target_id)[-4:],
					'type': target.target_type,
					'url': target.url,
					'title': target.title,
					'session_ids': [str(session_id) for session_id in target_sessions.get(target_id, set())],
					'focused': target_id == self.browser_session.agent_focus_target_id,
				}
			)
		return targets

	async def _wait_for_event(self, method: Any, session: Any, timeout: Any) -> dict[str, Any]:
		if not isinstance(method, str) or '.' not in method:
			raise ValueError('CDP event must be a string like "Network.responseReceived".')
		timeout_seconds = float(timeout if timeout is not None else 30.0)
		if not 0 < timeout_seconds <= 120:
			raise ValueError('CDP event timeout must be greater than 0 and at most 120 seconds.')

		match_any_session = session == 'any'
		expected_session = None if match_any_session else await self.direct_cdp.resolve_session_id(method, session)
		future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
		waiter = (future, expected_session, match_any_session)

		async with self._event_lock:
			waiters = self._event_waiters.setdefault(method, [])
			if not waiters:
				registry = self.browser_session.cdp_client._event_registry
				original = registry._handlers.get(method)
				self._event_original_handlers[method] = original

				async def multiplex(params: Any, session_id: str | None = None) -> None:
					if original is not None:
						try:
							original_result = original(params, session_id)
							if inspect.isawaitable(original_result):
								await original_result
						except Exception:
							pass
					for pending, pending_session, any_session in list(self._event_waiters.get(method, [])):
						if pending.done() or (not any_session and pending_session != session_id):
							continue
						pending.set_result(params if isinstance(params, dict) else {'value': params})

				self._event_wrappers[method] = multiplex
				registry.register(method, cast(Any, multiplex))

			waiters.append(waiter)

		try:
			return await asyncio.wait_for(future, timeout=timeout_seconds)
		except TimeoutError as exc:
			raise TimeoutError(f'Timed out waiting {timeout_seconds:g}s for CDP event {method}.') from exc
		finally:
			async with self._event_lock:
				waiters = self._event_waiters.get(method, [])
				if waiter in waiters:
					waiters.remove(waiter)
				if not waiters:
					self._event_waiters.pop(method, None)
					self._event_wrappers.pop(method, None)
					original = self._event_original_handlers.pop(method, None)
					registry = self.browser_session.cdp_client._event_registry
					if original is None:
						registry.unregister(method)
					else:
						registry.register(method, cast(Any, original))

	async def _cancel_and_join_cell(self, task: asyncio.Task[Any]) -> None:
		"""Cancel a yielding cell without ever leaving model code running in the background."""
		task.cancel()
		await asyncio.sleep(0)
		if not task.done():
			logger.critical('🐍 Python cell ignored cancellation. Waiting for it to stop; kill the agent worker if it does not.')
		try:
			await task
		except BaseException:
			pass

	def _truncate(self, text: str) -> str:
		if len(text) <= self.max_output_chars:
			return text
		head = self.max_output_chars * 2 // 3
		tail = self.max_output_chars - head
		return f'{text[:head]}\n... [{len(text) - self.max_output_chars} characters omitted] ...\n{text[-tail:]}'
