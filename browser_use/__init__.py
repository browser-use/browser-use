from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel

DEFAULT_MODEL = 'browser-use/openai/gpt-6-luna'


class BrowserUseError(RuntimeError):
	pass


def _schema(schema: dict[str, Any]) -> dict[str, Any]:
	def visit(value: Any, refs: frozenset[str] = frozenset()) -> Any:
		if isinstance(value, list):
			return [visit(item, refs) for item in value]
		if not isinstance(value, dict):
			return value
		if '$ref' in value:
			ref = value['$ref']
			if not isinstance(ref, str) or not ref.startswith('#/') or ref in refs:
				raise BrowserUseError('Only non-recursive local JSON Schema references are supported.')
			target: Any = schema
			try:
				for key in ref[2:].split('/'):
					target = target[key.replace('~1', '/').replace('~0', '~')]
			except (KeyError, TypeError) as exc:
				raise BrowserUseError(f'Unresolved schema reference: {ref}') from exc

			if set(value) - {'$ref', 'title', 'description'}:
				raise BrowserUseError('Schema reference siblings are unsupported.')
			return visit(target, refs | {ref})
		return {key: visit(item, refs) for key, item in value.items() if key not in {'$defs', 'definitions'}}

	return visit(schema)


@dataclass(frozen=True)
class Tool:
	name: str
	description: str
	parameters: type[BaseModel]
	execute: Callable[[BaseModel], Any | Awaitable[Any]]


@dataclass(frozen=True)
class RunResult:
	status: str
	output: Any
	text: str
	metadata: dict[str, Any]

	@property
	def partial(self) -> dict[str, Any] | None:
		return self.metadata.get('partial')

	@property
	def usage(self) -> dict[str, Any]:
		return self.metadata['usage']


class BrowserUse:
	_default_model: str | None = None

	def __init__(self, *, model: str | None = None, **options: Any) -> None:
		self._initial_options = {'model': model, **options}
		self._callbacks: dict[str, Callable[..., Any]] = {}
		self._run_active = False
		self._result_validator: Callable[..., Any] | None = None
		self.workspace = ''
		self._process: asyncio.subprocess.Process | None = None
		self._pending: dict[int, asyncio.Future[Any]] = {}
		self._next_id = 0
		self._write_lock = asyncio.Lock()
		self._tools: dict[str, Tool] = {}
		self._tool_tasks: dict[str, asyncio.Task[None]] = {}
		self._queues: set[asyncio.Queue[Any]] = set()
		self._reader: asyncio.Task[None] | None = None
		self._stderr_task: asyncio.Task[None] | None = None
		self._stderr = ''
		self._closed = False
		self._closing: asyncio.Task[None] | None = None
		self._configuring = False

	@classmethod
	async def create(
		cls,
		*,
		model: str | None = None,
		tools: list[Tool] | None = None,
		node: str | None = None,
		server_path: str | Path | None = None,
		**options: Any,
	) -> Self:
		agent = await cls.start(tools=tools, node=node, server_path=server_path)
		return await agent.configure(model=model, **options)

	@classmethod
	async def start(
		cls,
		*,
		tools: list[Tool] | None = None,
		node: str | None = None,
		server_path: str | Path | None = None,
	) -> Self:
		self = cls()
		for tool in tools or []:
			if tool.name in self._tools:
				raise ValueError(f'Duplicate tool: {tool.name}')
			self._tools[tool.name] = tool
		private_node = Path(__file__).with_name('runtime') / ('node.exe' if os.name == 'nt' else 'node')
		executable = node or os.environ.get('BROWSER_USE_NODE') or str(private_node)
		if not Path(executable).is_file():
			raise BrowserUseError('Private Node runtime is missing; reinstall browser-use or supply node= explicitly.')
		server = Path(server_path) if server_path else Path(__file__).with_name('runtime') / 'server.mjs'
		if not server.is_file():
			raise BrowserUseError('Packaged JS runtime is missing. Build with npm run build:python, or pass server_path.')

		allowed = {
			'PATH',
			'HOME',
			'TMPDIR',
			'TEMP',
			'SYSTEMROOT',
			'SSL_CERT_FILE',
			'NODE_EXTRA_CA_CERTS',
			'BROWSER_USE_CHROME_EXECUTABLE',
			'DO_NOT_TRACK',
			'ANONYMIZED_TELEMETRY',
			'BROWSER_USE_MODEL',
			'ProgramFiles',
			'ProgramFiles(x86)',
			'PROGRAMFILES',
			'PROGRAMFILES(X86)',
		}
		allowed.update(
			{
				'OPENAI_API_KEY',
				'ANTHROPIC_API_KEY',
				'GOOGLE_API_KEY',
				'GEMINI_API_KEY',
				'OPENROUTER_API_KEY',
				'BROWSER_USE_API_KEY',
			}
		)
		env = {key: value for key, value in os.environ.items() if key in allowed}
		self._process = await asyncio.create_subprocess_exec(
			executable,
			str(server.resolve()),
			stdin=asyncio.subprocess.PIPE,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=env,
			limit=64_000_001,
		)
		self._reader = asyncio.create_task(self._read())
		self._stderr_task = asyncio.create_task(self._read_stderr())
		try:
			ping = await asyncio.wait_for(self._call('ping'), 10)
			if ping.get('protocol') != 1:
				raise BrowserUseError('Unsupported runtime protocol.')
			version = tuple(int(part) for part in ping['node'].split('.')[:2])
			if version < (22, 19):
				raise BrowserUseError('Node.js 22.19+ is required.')
			return self
		except BaseException:
			await self.close()
			raise

	async def configure(self, *, model: str | None = None, **options: Any) -> Self:
		if self._configuring:
			raise BrowserUseError('Session is already configured.')
		self._configuring = True
		try:
			specs = [
				{
					'name': t.name,
					'description': t.description,
					'parameters': _schema(t.parameters.model_json_schema()),
				}
				for t in self._tools.values()
			]
			options = _options(options)
			for name in ('beforeToolCall', 'afterToolCall', 'validateResult', 'onBrowserReady'):
				callback = options.pop(name, None)
				if callback is not None:
					if not callable(callback):
						raise TypeError(f'{name} must be callable.')
					self._callbacks[name] = callback
			model = self._default_model if model is None else model
			options['callbacks'] = list(self._callbacks)
			options.setdefault('clientLanguage', 'python')
			result = await asyncio.wait_for(
				self._call('create', {**({'model': model} if model is not None else {}), **options, 'tools': specs}), 30
			)
			self.workspace = result['workspace']
			return self
		except BaseException:
			await self.close()
			raise

	async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
		if self._closed or not self._process or self._process.returncode is not None:
			raise BrowserUseError('Session is closed or runtime exited.')
		self._next_id += 1
		request_id = self._next_id
		future = asyncio.get_running_loop().create_future()
		self._pending[request_id] = future
		try:
			message = (
				json.dumps(
					{'id': request_id, 'method': method, 'params': params or {}},
					allow_nan=False,
				).encode()
				+ b'\n'
			)
			if len(message) > 16_000_000:
				raise BrowserUseError('Bridge request exceeds 16 MB; use a workspace file.')
			async with self._write_lock:
				assert self._process.stdin
				self._process.stdin.write(message)
				await self._process.stdin.drain()
			return await future
		finally:
			self._pending.pop(request_id, None)

	async def _read(self) -> None:
		assert self._process and self._process.stdout
		error: Exception = BrowserUseError('Node runtime exited. JS state is lost; inspect browser state before retrying.')
		try:
			while line := await self._process.stdout.readline():
				message = json.loads(line)
				if 'id' in message:
					future = self._pending.get(message['id'])
					if future and not future.done():
						if 'error' in message:
							future.set_exception(BrowserUseError(message['error']['message']))
						else:
							future.set_result(message.get('result'))
				elif message.get('method') == 'tool_call':
					params = message['params']
					task = asyncio.create_task(self._execute_tool(params))
					self._tool_tasks[params['id']] = task
					task.add_done_callback(lambda _task, key=params['id']: self._tool_tasks.pop(key, None))
				elif message.get('method') == 'callback_call':
					params = message['params']
					task = asyncio.create_task(self._execute_callback(params))
					self._tool_tasks[params['id']] = task
					task.add_done_callback(lambda _task, key=params['id']: self._tool_tasks.pop(key, None))
				elif message.get('method') in {'tool_cancel', 'callback_cancel'}:
					task = self._tool_tasks.get(message['params']['id'])
					if task:
						task.cancel()
				elif message.get('method') in {'event', 'stream_error'}:
					self._broadcast(message['params'])
		except (
			ValueError,
			TypeError,
			KeyError,
			ConnectionError,
			asyncio.LimitOverrunError,
		) as exc:
			error = BrowserUseError(f'Runtime protocol failure: {exc}')
		finally:
			for future in list(self._pending.values()):
				if not future.done():
					future.set_exception(error)
			for task in list(self._tool_tasks.values()):
				task.cancel()
			self._broadcast(error)

	def _broadcast(self, event: Any) -> None:
		for queue in list(self._queues):
			if queue.full():
				while not queue.empty():
					queue.get_nowait()
				queue.put_nowait(BrowserUseError('Event consumer fell behind; read the persisted run log.'))
				self._queues.discard(queue)
			else:
				queue.put_nowait(event)

	async def _read_stderr(self) -> None:
		assert self._process and self._process.stderr
		while chunk := await self._process.stderr.read(4096):
			self._stderr = (self._stderr + chunk.decode(errors='replace'))[-16000:]

	async def _execute_callback(self, params: dict[str, Any]) -> None:
		try:
			name = params['name']
			callback = self._result_validator if name == 'validateResult' and self._result_validator else self._callbacks[name]
			argument = self if name == 'onBrowserReady' else params['args']
			result = (
				await callback(argument) if inspect.iscoroutinefunction(callback) else await asyncio.to_thread(callback, argument)
			)
			if inspect.isawaitable(result):
				result = await result
			await self._call('callback_result', {'id': params['id'], 'result': result})
		except asyncio.CancelledError:
			raise
		except Exception as exc:
			await self._call('callback_result', {'id': params['id'], 'error': str(exc)})

	async def _execute_tool(self, params: dict[str, Any]) -> None:
		try:
			tool = self._tools[params['name']]
			args = tool.parameters.model_validate(params['args'])

			result = (
				await tool.execute(args)
				if inspect.iscoroutinefunction(tool.execute)
				else await asyncio.to_thread(tool.execute, args)
			)
			if inspect.isawaitable(result):
				result = await result
			if isinstance(result, BaseModel):
				result = result.model_dump(mode='json')
			await self._call('tool_result', {'id': params['id'], 'result': result})
		except asyncio.CancelledError:
			raise
		except Exception as exc:
			try:
				await self._call('tool_result', {'id': params['id'], 'error': str(exc)})
			except BrowserUseError:
				pass

	async def _run(
		self,
		method: str,
		task: str,
		schema: type[BaseModel] | dict[str, Any] | None,
		options: dict[str, Any],
	) -> RunResult:
		if self._run_active:
			raise BrowserUseError('This session is busy; await its active run.')
		options = _options(options)
		validator = options.pop('validateResult', None)
		if validator is not None and not callable(validator):
			raise TypeError('validate_result must be callable.')
		previous_validator = self._result_validator
		if inspect.isclass(schema) and issubclass(schema, BaseModel):

			async def validate(output: Any) -> str | None:
				try:
					schema.model_validate(output)
				except ValueError as error:
					return str(error)
				callback = validator or self._callbacks.get('validateResult')
				if callback:
					value = callback(output)
					feedback = await value if inspect.isawaitable(value) else value
					if feedback is not None and not isinstance(feedback, str):
						raise TypeError('Result validator must return text or None.')
					return feedback
				return None

			self._result_validator = validate
			options['validateResult'] = True
		elif validator is not None:
			self._result_validator = validator
			options['validateResult'] = True
		if schema is not None:
			options['schema'] = (
				_schema(schema.model_json_schema())
				if inspect.isclass(schema) and issubclass(schema, BaseModel)
				else _schema(schema)
			)
		self._run_active = True
		try:
			result = await self._call(method, {'task': task, 'options': options})
		except asyncio.CancelledError:
			await asyncio.shield(self.cancel())
			raise
		finally:
			self._run_active = False
			self._result_validator = previous_validator
		output = result.get('output')
		if result['status'] == 'completed' and inspect.isclass(schema) and issubclass(schema, BaseModel):
			output = schema.model_validate(output)
		return RunResult(result['status'], output, result['text'], result)

	async def run(
		self,
		task: str,
		*,
		schema: type[BaseModel] | dict[str, Any] | None = None,
		**options: Any,
	) -> RunResult:
		return await self._run('run', task, schema, options)

	async def follow_up(
		self,
		task: str,
		*,
		schema: type[BaseModel] | dict[str, Any] | None = None,
		**options: Any,
	) -> RunResult:
		return await self._run('followUp', task, schema, options)

	async def _execute(self, method: str, params: dict[str, Any]) -> Any:
		try:
			return await self._call(method, params)
		except asyncio.CancelledError:
			await asyncio.shield(self._call('cancel'))
			raise

	async def execute_json(self, expression: str, **options: Any) -> Any:
		return await self._execute('executeJson', {'expression': expression, 'options': _options(options)})

	async def execute(self, code: str, **options: Any) -> dict[str, Any]:
		return await self._execute('execute', {'code': code, 'options': _options(options)})

	async def events(self) -> AsyncIterator[dict[str, Any]]:
		queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
		self._queues.add(queue)
		try:
			while not self._closed:
				item = await queue.get()
				if isinstance(item, Exception):
					raise item
				if item is None:
					return
				yield item
		finally:
			self._queues.discard(queue)

	async def pause(self) -> bool:
		return (await self._call('pause'))['paused']

	async def resume(self) -> None:
		await self._call('resume')

	async def steer(self, text: str) -> None:
		await self._call('steer', {'text': text})

	async def cancel(self) -> None:
		await self._call('cancel')

	async def files(self) -> list[dict[str, Any]]:
		return await self._call('files')

	async def history(self) -> dict[str, Any]:
		return await self._call('history')

	async def save_history(self, path: str | None = None) -> str:
		return await self._call('saveHistory', {'path': path} if path else {})

	async def export_recording(self, path: str, **options: Any) -> str:
		return await self._call('exportRecording', {'path': path, 'options': options})

	async def current_target(self) -> str | None:
		return await self._call('currentTarget')

	async def connect_browser(
		self, cdp_url: str, *, target_id: str | None = None, cdp_options: dict[str, Any] | None = None
	) -> None:
		params: dict[str, Any] = {'cdpUrl': cdp_url}
		if target_id:
			params['targetId'] = target_id
		if cdp_options:
			params['cdpOptions'] = cdp_options
		await self._call('connectBrowser', params)

	async def close(self, *, keep_tabs: bool | str = False) -> None:
		if self._closing is None:
			self._closing = asyncio.create_task(self._close(keep_tabs))
		await asyncio.shield(self._closing)

	async def _close(self, keep_tabs: bool | str = False) -> None:
		if self._closed:
			return
		cleanup_error: Exception | None = None
		try:
			if self._process and self._process.returncode is None and self._configuring:
				for _attempt in range(2):
					try:
						await asyncio.wait_for(
							self._call('close', {'keepTabs': keep_tabs} if keep_tabs else None),
							10,
						)
						cleanup_error = None
						break
					except (BrowserUseError, ConnectionError, TimeoutError) as exc:
						cleanup_error = exc
						self._stderr = (self._stderr + f'\nGraceful close failed: {exc}')[-16000:]
		finally:
			try:
				if self._process and self._process.returncode is None:
					if self._process.stdin:
						self._process.stdin.close()
					try:
						await asyncio.wait_for(self._process.wait(), 5)
					except TimeoutError:
						self._process.kill()
						await self._process.wait()
			finally:
				self._closed = True
				self._broadcast(None)
				tasks = [
					task
					for task in [
						self._reader,
						self._stderr_task,
						*self._tool_tasks.values(),
					]
					if task
				]
				for task in tasks:
					if not task.done():
						task.cancel()
				await asyncio.gather(*tasks, return_exceptions=True)
		if cleanup_error is not None:
			raise BrowserUseError(f'Browser cleanup failed after retry: {cleanup_error}') from cleanup_error

	async def __aenter__(self) -> Self:
		if self._process is None:
			self._entered = await type(self).create(**self._initial_options)
			return self._entered
		return self

	async def __aexit__(self, *_exc: object) -> None:
		await getattr(self, '_entered', self).close()


def _options(options: dict[str, Any]) -> dict[str, Any]:
	aliases = {
		'allowed_domains': 'allowedDomains',
		'prohibited_domains': 'prohibitedDomains',
		'secrets': 'sensitiveData',
		'sensitive_data': 'sensitiveData',
		'research_tools': 'researchTools',
		'shell_env': 'shellEnv',
		'shell_timeout_ms': 'shellTimeoutMs',
		'model_info': 'modelInfo',
		'api_key': 'apiKey',
		'base_url': 'baseUrl',
		'model_id': 'modelId',
		'max_steps': 'maxSteps',
		'timeout_ms': 'timeoutMs',
		'max_cost_usd': 'maxCostUsd',
		'max_context_chars': 'maxContextChars',
		'before_tool_call': 'beforeToolCall',
		'after_tool_call': 'afterToolCall',
		'validate_result': 'validateResult',
		'on_browser_ready': 'onBrowserReady',
		'history_file': 'historyFile',
		'highlight_actions': 'highlightActions',
		'hook_timeout_ms': 'hookTimeoutMs',
		'client_language': 'clientLanguage',
		'init_scripts': 'initScripts',
	}
	result: dict[str, Any] = {}
	for name, value in options.items():
		key = aliases.get(name, name)
		if key in result:
			raise TypeError(f'Duplicate option: {key}')
		result[key] = value
	return result


class Agent(BrowserUse):
	_default_model = DEFAULT_MODEL


class Browser(BrowserUse):
	@staticmethod
	def cloud(**options: Any) -> dict[str, Any]:
		aliases = {
			'api_key': 'apiKey',
			'profile_id': 'profileId',
			'timeout_minutes': 'timeoutMinutes',
			'proxy_country_code': 'proxyCountryCode',
		}
		return {'kind': 'cloud', **{aliases.get(key, key): value for key, value in options.items()}}

	@staticmethod
	def chrome(**options: Any) -> dict[str, Any]:
		aliases = {
			'cdp_url': 'cdpUrl',
			'profile_dir': 'profileDir',
			'target_id': 'targetId',
			'approve_connection': 'approveConnection',
		}
		return {'kind': 'chrome', **{aliases.get(key, key): value for key, value in options.items()}}

	@staticmethod
	def chromium(**options: Any) -> dict[str, Any]:
		aliases = {'profile_dir': 'profileDir', 'executable_path': 'executablePath'}
		return {'kind': 'chromium', **{aliases.get(key, key): value for key, value in options.items()}}

	@staticmethod
	def cdp(url: str, **options: Any) -> dict[str, Any]:
		return {'cdpUrl': url, **options}
