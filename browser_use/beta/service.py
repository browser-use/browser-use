from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import inspect
import json
import keyword
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal
from urllib.parse import urlparse

from bubus import EventBus
from pydantic import BaseModel, ValidationError, create_model
from typing_extensions import TypeVar
from uuid_extensions import uuid7str

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)
from browser_use.agent.judge import construct_judge_messages
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.utils import save_conversation
from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.views import (
	ActionResult,
	AgentError,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentSettings,
	AgentState,
	AgentStepInfo,
	AgentStructuredOutput,
	JudgementResult,
	MessageCompactionSettings,
	StepMetadata,
)
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import CHROME_DETERMINISTIC_RENDERING_ARGS, CHROME_DISABLE_SECURITY_ARGS, CHROME_DOCKER_ARGS
from browser_use.browser.views import BrowserStateHistory, BrowserStateSummary, TabInfo
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, ContentPartImageParam, ContentPartTextParam
from browser_use.llm.views import ChatInvokeUsage
from browser_use.observability import observe
from browser_use.screenshots.service import ScreenshotService
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.tokens.custom_pricing import CUSTOM_MODEL_PRICING
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelUsageStats, UsageSummary
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import (
	URL_PATTERN,
	SignalHandler,
	_log_pretty_path,
	check_latest_browser_use_version,
	get_browser_use_version,
	get_git_info,
	is_placeholder_url,
	sanitize_url_candidate,
)

Context = TypeVar('Context')
AgentHookFunc = Callable[['Agent'], Awaitable[None]]
AgentNewStepCallback = (
	Callable[[BrowserStateSummary, AgentOutput, int], None] | Callable[[BrowserStateSummary, AgentOutput, int], Awaitable[None]]
)
AgentDoneCallback = Callable[[AgentHistoryList], Awaitable[None]] | Callable[[AgentHistoryList], None]
logger = logging.getLogger(__name__)
TERMINAL_INSTALL_COMMAND = 'curl -fsSL https://browser-use.com/terminal/install.sh | sh'
AGENT_TOOLS_DIR_ENV = 'BUT_AGENT_TOOLS_DIR'

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore


class BetaAgentError(RuntimeError):
	"""Raised when the beta agent cannot run a task."""


def _laminar_ready() -> bool:
	if Laminar is None:
		return False
	try:
		return bool(Laminar.is_initialized())
	except Exception:
		return False


def _laminar_preview(value: Any, limit: int = 2000) -> Any:
	if value is None or isinstance(value, (bool, int, float)):
		return value
	text = value if isinstance(value, str) else json.dumps(value, default=str)
	if len(text) <= limit:
		return text
	return text[:limit] + f'...[truncated {len(text) - limit} chars]'


def _laminar_set_span_attributes(attributes: dict[str, Any]) -> None:
	if not _laminar_ready():
		return
	safe_attributes = {key: value for key, value in attributes.items() if isinstance(value, (str, bool, int, float))}
	if not safe_attributes:
		return
	try:
		Laminar.set_span_attributes(safe_attributes)
	except Exception:
		logger.debug('Failed to set Laminar span attributes', exc_info=True)


def _laminar_set_span_output(output: Any) -> None:
	if not _laminar_ready():
		return
	try:
		Laminar.set_span_output(output)
	except Exception:
		logger.debug('Failed to set Laminar span output', exc_info=True)


def _laminar_event(name: str, attributes: dict[str, Any] | None = None) -> None:
	if not _laminar_ready():
		return
	safe_attributes = {key: value for key, value in (attributes or {}).items() if isinstance(value, (str, bool, int, float))}
	try:
		Laminar.event(name, safe_attributes or None)
	except Exception:
		logger.debug('Failed to emit Laminar event %s', name, exc_info=True)


def _laminar_start_span(name: str, *, input: Any = None, span_type: str = 'DEFAULT'):
	if not _laminar_ready():
		return nullcontext()
	try:
		return Laminar.start_as_current_span(name=name, input=input, span_type=span_type)
	except Exception:
		logger.debug('Failed to start Laminar span %s', name, exc_info=True)
		return nullcontext()


def _laminar_force_flush() -> None:
	if not _laminar_ready():
		return
	for method_name in ('flush', 'force_flush'):
		method = getattr(Laminar, method_name, None)
		if method is None:
			continue
		try:
			method()
			return
		except Exception:
			logger.debug('Failed to flush Laminar via %s', method_name, exc_info=True)


def _laminar_current_trace_id() -> str | None:
	if not _laminar_ready():
		return None
	try:
		trace_id = Laminar.get_trace_id()
	except Exception:
		return None
	return str(trace_id) if trace_id else None


def find_browser_use_terminal_binary() -> str:
	"""Find the terminal binary used by the Rust-backed Browser Use Agent."""
	env_path = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if env_path:
		return env_path
	packaged_path = _find_packaged_browser_use_terminal_binary()
	if packaged_path:
		return packaged_path
	but_home = Path(os.environ.get('BUT_HOME', '~/.browser-use-terminal')).expanduser()
	but_install_dir = Path(os.environ.get('BUT_INSTALL_DIR', '~/.local/bin')).expanduser()
	candidates = [
		but_home / 'packages' / 'standalone' / 'current' / 'bin' / 'browser-use-terminal',
		but_install_dir / 'browser-use-terminal',
	]
	for candidate in candidates:
		if candidate.exists() and _terminal_supports_sdk_server(candidate):
			return str(candidate)
	path_binary = shutil.which('browser-use-terminal')
	if path_binary and _terminal_supports_sdk_server(Path(path_binary)):
		return path_binary
	raise BetaAgentError(
		f'Could not find browser-use-terminal. Install Browser Use Terminal with `{TERMINAL_INSTALL_COMMAND}`, '
		'install browser-use-core, or set BROWSER_USE_TERMINAL_BINARY to a built terminal CLI.'
	)


def _find_packaged_browser_use_terminal_binary() -> str | None:
	try:
		from browser_use_core import binary_path
	except Exception:
		return None
	try:
		return binary_path('browser-use-terminal')
	except Exception:
		return None


def _apply_agent_tools_env(env: dict[str, str]) -> None:
	agent_tools_dir = _find_agent_tools_dir(env.get(AGENT_TOOLS_DIR_ENV))
	if agent_tools_dir is None:
		return
	env[AGENT_TOOLS_DIR_ENV] = str(agent_tools_dir)
	_prepend_env_path(env, agent_tools_dir)


def _find_agent_tools_dir(preferred_dir: str | None = None) -> Path | None:
	if preferred_dir:
		preferred_path = Path(preferred_dir).expanduser()
		return preferred_path if _agent_tools_dir_contains_ripgrep(preferred_path) else None

	env_binary = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if env_binary:
		agent_tools_dir = _agent_tools_dir_for_terminal_binary(env_binary)
		if agent_tools_dir:
			return agent_tools_dir

	packaged_dir = _find_packaged_agent_tools_dir()
	if packaged_dir:
		return packaged_dir

	try:
		terminal_binary = find_browser_use_terminal_binary()
	except BetaAgentError:
		return None
	return _agent_tools_dir_for_terminal_binary(terminal_binary)


def _find_packaged_agent_tools_dir() -> Path | None:
	try:
		from browser_use_core import agent_tools_dir
	except Exception:
		agent_tools_dir = None

	if agent_tools_dir is not None:
		try:
			candidate = Path(agent_tools_dir())
		except Exception:
			candidate = None
		if candidate and _agent_tools_dir_contains_ripgrep(candidate):
			return candidate

	try:
		from browser_use_core import binary_path
	except Exception:
		return None

	try:
		binary = Path(binary_path('browser-use-terminal'))
	except Exception:
		return None
	candidate = binary.parent / 'agent-tools'
	return candidate if _agent_tools_dir_contains_ripgrep(candidate) else None


def _agent_tools_dir_for_terminal_binary(binary_path: str | Path) -> Path | None:
	candidate = Path(binary_path).expanduser().parent / 'agent-tools'
	return candidate if _agent_tools_dir_contains_ripgrep(candidate) else None


def _agent_tools_dir_contains_ripgrep(directory: Path) -> bool:
	return (directory / _agent_tools_ripgrep_name()).exists()


def _agent_tools_ripgrep_name() -> str:
	return 'rg.exe' if os.name == 'nt' else 'rg'


def _prepend_env_path(env: dict[str, str], directory: Path) -> None:
	directory_str = str(directory)
	path_parts = [part for part in env.get('PATH', '').split(os.pathsep) if part and part != directory_str]
	env['PATH'] = os.pathsep.join([directory_str, *path_parts])


def _terminal_supports_sdk_server(binary: Path) -> bool:
	"""Return whether a terminal binary supports the SDK server subcommand required by this wrapper."""
	try:
		result = subprocess.run(
			[str(binary), '--help'],
			capture_output=True,
			text=True,
			timeout=5,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return False
	return 'sdk-server' in f'{result.stdout}\n{result.stderr}'


class RustSdkJsonRpcError(BetaAgentError):
	"""Raised when the Rust SDK server returns a JSON-RPC error."""

	def __init__(self, code: int, message: str) -> None:
		super().__init__(message)
		self.code = code
		self.message = message


class RustSdkClient:
	"""Minimal stdio JSON-RPC client for browser-use-terminal sdk-server."""

	def __init__(self, command: list[str], env: dict[str, str]) -> None:
		self.command = list(command)
		self.env = dict(env)
		self.process: asyncio.subprocess.Process | None = None
		self._reader_task: asyncio.Task[Any] | None = None
		self._stderr_task: asyncio.Task[Any] | None = None
		self._next_id = 1
		self._pending: dict[int, asyncio.Future[Any]] = {}
		self._write_lock = asyncio.Lock()
		self.stderr_lines: list[str] = []
		self.notifications: list[dict[str, Any]] = []
		self.notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
		self.stream_limit = int(os.environ.get('BROWSER_USE_SDK_STREAM_LIMIT_BYTES', str(64 * 1024 * 1024)))
		self.read_chunk_size = int(os.environ.get('BROWSER_USE_SDK_READ_CHUNK_BYTES', str(1024 * 1024)))
		self.max_line_bytes = int(os.environ.get('BROWSER_USE_SDK_MAX_LINE_BYTES', str(512 * 1024 * 1024)))

	async def start(self) -> None:
		if self.process is not None and self.process.returncode is None:
			return
		try:
			self.process = await asyncio.create_subprocess_exec(
				*self.command,
				stdin=asyncio.subprocess.PIPE,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=self.env,
				limit=self.stream_limit,
			)
		except (FileNotFoundError, PermissionError) as exc:
			command = self.command[0] if self.command else 'browser-use-terminal'
			raise BetaAgentError(
				f'Could not start Rust SDK server command {command!r}. '
				f'Install Browser Use Terminal with `{TERMINAL_INSTALL_COMMAND}`, '
				'or set BROWSER_USE_TERMINAL_BINARY to a built terminal CLI.'
			) from exc
		self._reader_task = asyncio.create_task(self._read_stdout())
		self._stderr_task = asyncio.create_task(self._read_stderr())

	async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
		await self.start()
		if self.process is None or self.process.stdin is None:
			raise BetaAgentError('Rust SDK server stdin is unavailable')
		loop = asyncio.get_running_loop()
		async with self._write_lock:
			request_id = self._next_id
			self._next_id += 1
			future: asyncio.Future[Any] = loop.create_future()
			self._pending[request_id] = future
			request = {
				'jsonrpc': '2.0',
				'id': request_id,
				'method': method,
				'params': params or {},
			}
			try:
				self.process.stdin.write((json.dumps(request) + '\n').encode('utf-8'))
				await self.process.stdin.drain()
			except (BrokenPipeError, ConnectionResetError) as exc:
				self._pending.pop(request_id, None)
				raise BetaAgentError(f'Rust SDK server pipe closed while sending {method}') from exc
		try:
			return await future
		except asyncio.CancelledError:
			self._pending.pop(request_id, None)
			raise

	async def close(self) -> None:
		process = self.process
		if process is None:
			return
		if process.stdin is not None:
			process.stdin.close()
			with suppress(BrokenPipeError, ConnectionResetError):
				await process.stdin.wait_closed()
		if process.returncode is None:
			process.terminate()
			try:
				await asyncio.wait_for(process.wait(), timeout=2)
			except TimeoutError:
				process.kill()
				await process.wait()
		for task in (self._reader_task, self._stderr_task):
			if task is not None:
				task.cancel()
		await asyncio.gather(
			*(task for task in (self._reader_task, self._stderr_task) if task is not None and task is not asyncio.current_task()),
			return_exceptions=True,
		)
		self._fail_all(BetaAgentError('Rust SDK server closed'))
		self.process = None

	async def _read_stdout(self) -> None:
		assert self.process is not None
		assert self.process.stdout is not None
		buffer = bytearray()
		try:
			while True:
				chunk = await self.process.stdout.read(self.read_chunk_size)
				if not chunk:
					if buffer and not self._handle_stdout_line(bytes(buffer)):
						return
					return
				buffer.extend(chunk)
				while True:
					newline_index = buffer.find(b'\n')
					if newline_index < 0:
						break
					raw_line = bytes(buffer[:newline_index])
					del buffer[: newline_index + 1]
					if not self._handle_stdout_line(raw_line):
						return
				if len(buffer) > self.max_line_bytes:
					self._fail_all(BetaAgentError(f'Rust SDK JSON-RPC line exceeded {self.max_line_bytes} bytes without newline'))
					return
		except Exception as exc:
			message = f'Rust SDK stdout reader failed: {exc}'
			self.stderr_lines.append(message)
			self._fail_all(BetaAgentError(message))
		finally:
			if self._pending:
				detail = '\n'.join(self.stderr_lines[-20:])
				message = 'Rust SDK server exited before responding'
				if detail:
					message = f'{message}: {detail}'
				self._fail_all(BetaAgentError(message))

	def _handle_stdout_line(self, raw_line: bytes) -> bool:
		line = raw_line.decode('utf-8', errors='replace').strip()
		if not line:
			return True
		try:
			message = json.loads(line)
		except json.JSONDecodeError as exc:
			self._fail_all(BetaAgentError(f'Invalid Rust SDK JSON-RPC line: {line}: {exc}'))
			return False
		self._handle_message(message)
		return True

	async def _read_stderr(self) -> None:
		assert self.process is not None
		assert self.process.stderr is not None
		async for raw_line in self.process.stderr:
			self.stderr_lines.append(raw_line.decode('utf-8', errors='replace').rstrip())
			del self.stderr_lines[:-500]

	def _handle_message(self, message: Any) -> None:
		if not isinstance(message, dict):
			self._fail_all(BetaAgentError(f'Rust SDK server emitted non-object JSON-RPC message: {message!r}'))
			return
		method = message.get('method')
		if method in {'agent.event', 'agent.projected_event'}:
			notification = {
				'method': method,
				'params': message.get('params') if isinstance(message.get('params'), dict) else {},
			}
			self.notifications.append(notification)
			del self.notifications[:-2000]
			self.notification_queue.put_nowait(notification)
			return
		if 'id' not in message:
			return
		request_id = message.get('id')
		if not isinstance(request_id, int):
			self._fail_all(BetaAgentError('Rust SDK JSON-RPC response id must be an integer'))
			return
		future = self._pending.pop(request_id, None)
		if future is None or future.done():
			return
		if 'error' in message:
			error = message.get('error') or {}
			if not isinstance(error, dict):
				error = {}
			future.set_exception(
				RustSdkJsonRpcError(
					int(error.get('code', -32000)),
					str(error.get('message') or 'Rust SDK server error'),
				)
			)
			return
		future.set_result(message.get('result'))

	def _fail_all(self, error: BaseException) -> None:
		for future in self._pending.values():
			if not future.done():
				future.set_exception(error)
		self._pending.clear()


def _sdk_preview(value: Any, limit: int = 180) -> str | None:
	if value is None:
		return None
	if isinstance(value, str):
		text = value
	else:
		try:
			text = json.dumps(value, default=str)
		except Exception:
			text = str(value)
	text = ' '.join(text.split())
	if not text:
		return None
	if len(text) <= limit:
		return text
	return text[:limit] + f'...[{len(text) - limit} more chars]'


def _sdk_payload_label(payload: dict[str, Any]) -> str | None:
	for key in ('name', 'tool_name', 'tool', 'task', 'command', 'url', 'title', 'result', 'error', 'message'):
		value = _sdk_preview(payload.get(key))
		if value:
			return f'{key}={value}'
	arguments = payload.get('arguments')
	if isinstance(arguments, dict):
		for key in ('name', 'cmd', 'command', 'code', 'url'):
			value = _sdk_preview(arguments.get(key))
			if value:
				return f'{key}={value}'
	return None


def _sdk_notification_summary(notification: dict[str, Any]) -> str | None:
	method = notification.get('method')
	params = notification.get('params')
	if not isinstance(params, dict):
		return None
	event = params.get('event')
	if not isinstance(event, dict):
		return None
	payload = event.get('payload')
	if not isinstance(payload, dict):
		payload = {}
	kind = event.get('kind') or event.get('event_type') or event.get('type')
	if isinstance(kind, dict):
		kind = kind.get('type') or kind.get('name')
	if not isinstance(kind, str) or not kind:
		kind = str(method or 'sdk.notification')

	observed_type = payload.get('event_type')
	observed_payload = payload.get('payload')
	if isinstance(observed_type, str) and observed_type:
		kind = observed_type
		if isinstance(observed_payload, dict):
			payload = observed_payload

	if kind in {
		'model.stream_delta',
		'model.thinking_delta',
		'tool.output_delta',
		'browser.script.output_delta',
		'python.output_delta',
		'exec_command.output_delta',
	}:
		return None

	label = _sdk_payload_label(payload)
	if method == 'agent.projected_event':
		projected_kind = event.get('kind')
		if isinstance(projected_kind, str) and projected_kind:
			kind = f'projected.{projected_kind}'
	return f'{kind} {label}'.strip() if label else kind


def _sdk_notification_events(sdk: Any) -> list[dict[str, Any]]:
	events: list[dict[str, Any]] = []
	seen: set[tuple[Any, Any, Any]] = set()
	for fallback_index, notification in enumerate(list(getattr(sdk, 'notifications', []) or [])):
		if not isinstance(notification, dict) or notification.get('method') not in {'agent.event', 'agent.projected_event'}:
			continue
		params = notification.get('params')
		if not isinstance(params, dict):
			continue
		event = params.get('event')
		if not isinstance(event, dict):
			continue
		if not isinstance(event.get('event_type'), str):
			payload = event.get('payload')
			if not isinstance(payload, dict) or not isinstance(payload.get('event_type'), str):
				continue
			event = {
				'seq': payload.get('seq', event.get('seq')),
				'id': payload.get('id', event.get('id')),
				'session_id': payload.get('session_id', event.get('session_id')),
				'ts_ms': payload.get('ts_ms', event.get('ts_ms')),
				'event_type': payload.get('event_type'),
				'payload': payload.get('payload') if isinstance(payload.get('payload'), dict) else {},
			}
		elif notification.get('method') == 'agent.projected_event':
			event = {
				'seq': event.get('seq'),
				'id': event.get('id'),
				'session_id': event.get('session_id'),
				'ts_ms': event.get('ts_ms'),
				'event_type': event.get('event_type'),
				'payload': event.get('payload') if isinstance(event.get('payload'), dict) else {},
			}
		identity = (event.get('seq'), event.get('id'), event.get('event_type'))
		if identity[0] is None and identity[1] is None:
			identity = (fallback_index, notification.get('method'), event.get('event_type'))
		if identity in seen:
			continue
		seen.add(identity)
		events.append(event)
	return _dedupe_sdk_events(events)


def _event_payload_fingerprint(event: dict[str, Any]) -> str:
	try:
		return json.dumps(_event_payload(event), sort_keys=True, default=str)
	except Exception:
		return repr(_event_payload(event))


def _sdk_event_dedupe_identity(event: dict[str, Any], fallback_index: int) -> tuple[Any, ...]:
	event_type = _event_type(event)
	seq = event.get('seq')
	if seq is not None:
		return ('seq', seq, event_type, _event_payload_fingerprint(event))
	event_id = event.get('id') or event.get('event_id')
	if event_id is not None:
		return ('id', event_id, event_type)
	return ('fallback', fallback_index)


def _dedupe_sdk_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Remove SDK response/projected duplicates while preserving first-seen order."""
	deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
	order: list[tuple[Any, ...]] = []
	for index, event in enumerate(events):
		key = _sdk_event_dedupe_identity(event, index)
		existing = deduped.get(key)
		if existing is None:
			deduped[key] = event
			order.append(key)
			continue
		if not (existing.get('id') or existing.get('event_id')) and (event.get('id') or event.get('event_id')):
			deduped[key] = event
	return [deduped[key] for key in order]


def _sdk_events_truncated_for_transport(events: list[dict[str, Any]]) -> bool:
	return any(_event_type(event) == 'sdk.transport.truncated' for event in events)


def _sdk_transport_error_after_final_result(process_error: str | None) -> bool:
	if not process_error:
		return False
	return any(
		fragment in process_error
		for fragment in (
			'Rust SDK JSON-RPC line exceeded',
			'Rust SDK stdout reader failed',
			'Rust SDK server emitted non-object JSON-RPC message',
			'Invalid Rust SDK JSON-RPC line',
		)
	)


def _model_name(llm: Any | None) -> str:
	for attr in ('model', 'model_name', 'name'):
		value = getattr(llm, attr, None)
		if isinstance(value, str) and value:
			return value
	return os.environ.get('BROWSER_USE_RUST_MODEL', 'gpt-5.3-codex-spark')


def _llm_timeout_for_model(llm: Any | None) -> int:
	model_name = str(getattr(llm, 'model', '') or '').lower()
	if 'gemini' in model_name:
		if '3-pro' in model_name:
			return 90
		return 75
	if 'groq' in model_name:
		return 30
	if 'o3' in model_name or 'claude' in model_name or 'sonnet' in model_name or 'deepseek' in model_name:
		return 90
	return 75


def _resolve_default_llm(llm: BaseChatModel | None) -> BaseChatModel:
	if llm is not None:
		return llm
	try:
		from browser_use.config import CONFIG

		default_llm_name = CONFIG.DEFAULT_LLM
	except Exception:
		default_llm_name = ''
	if default_llm_name:
		from browser_use.llm.models import get_llm_by_name

		return get_llm_by_name(default_llm_name)
	from browser_use import ChatBrowserUse

	return ChatBrowserUse()


def _extract_cdp_url(browser_session: BrowserSession | None) -> str | None:
	if browser_session is None:
		return None
	for attr in ('cdp_url',):
		value = getattr(browser_session, attr, None)
		if isinstance(value, str) and value:
			return value
	profile = getattr(browser_session, 'browser_profile', None)
	value = getattr(profile, 'cdp_url', None)
	if isinstance(value, str) and value:
		return value
	return None


def _extract_profile_cdp_url(browser_profile: BrowserProfile | None) -> str | None:
	if browser_profile is None:
		return None
	value = getattr(browser_profile, 'cdp_url', None)
	if isinstance(value, str) and value:
		return value
	return None


def _extract_headless_preference(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> bool | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		value = getattr(profile, 'headless', None)
		if isinstance(value, bool):
			return value
	value = getattr(browser_session, 'headless', None)
	if isinstance(value, bool):
		return value
	return None


def _extract_cloud_preference(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> bool:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		for attr in ('use_cloud', 'cloud_browser'):
			value = getattr(profile, attr, None)
			if isinstance(value, bool) and value:
				return True
	return False


def _value_from_object(value: Any, key: str) -> Any:
	if value is None:
		return None
	if isinstance(value, dict):
		return value.get(key)
	return getattr(value, key, None)


def _append_unique(items: list[str], seen: set[str], value: Any) -> None:
	if not isinstance(value, str) or not value:
		return
	if value in seen:
		return
	items.append(value)
	seen.add(value)


def _window_size_arg(window_size: Any) -> str | None:
	if window_size is None:
		return None
	if isinstance(window_size, (list, tuple)) and len(window_size) >= 2:
		width, height = window_size[0], window_size[1]
	else:
		width = _value_from_object(window_size, 'width')
		height = _value_from_object(window_size, 'height')
	if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
		return None
	return f'--window-size={width},{height}'


def _window_position_arg(window_position: Any) -> str | None:
	if window_position is None:
		return None
	if isinstance(window_position, (list, tuple)) and len(window_position) >= 2:
		x, y = window_position[0], window_position[1]
	else:
		x = _value_from_object(window_position, 'width')
		y = _value_from_object(window_position, 'height')
	if not isinstance(x, int) or not isinstance(y, int):
		return None
	return f'--window-position={x},{y}'


def _managed_browser_launch_args(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> list[str]:
	args: list[str] = []
	seen: set[str] = set()
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		raw_args = getattr(profile, 'args', None)
		if isinstance(raw_args, set):
			raw_args = sorted(raw_args)
		if isinstance(raw_args, (list, tuple)):
			for arg in raw_args:
				_append_unique(args, seen, arg)
		if getattr(profile, 'disable_security', False) is True:
			for arg in CHROME_DISABLE_SECURITY_ARGS:
				_append_unique(args, seen, arg)
		if getattr(profile, 'deterministic_rendering', False) is True:
			for arg in CHROME_DETERMINISTIC_RENDERING_ARGS:
				_append_unique(args, seen, arg)
		if getattr(profile, 'chromium_sandbox', None) is False:
			for arg in CHROME_DOCKER_ARGS:
				_append_unique(args, seen, arg)
		if getattr(profile, 'devtools', False) is True:
			_append_unique(args, seen, '--auto-open-devtools-for-tabs')
		_append_unique(args, seen, _window_size_arg(getattr(profile, 'window_size', None)))
		_append_unique(args, seen, _window_position_arg(getattr(profile, 'window_position', None)))
		proxy = getattr(profile, 'proxy', None)
		proxy_server = _value_from_object(proxy, 'server')
		if isinstance(proxy_server, str) and proxy_server:
			_append_unique(args, seen, f'--proxy-server={proxy_server}')
			proxy_bypass = _value_from_object(proxy, 'bypass')
			if isinstance(proxy_bypass, str) and proxy_bypass:
				_append_unique(args, seen, f'--proxy-bypass-list={proxy_bypass}')
		user_agent = getattr(profile, 'user_agent', None)
		if isinstance(user_agent, str) and user_agent:
			_append_unique(args, seen, f'--user-agent={user_agent}')
		profile_directory = getattr(profile, 'profile_directory', None)
		if isinstance(profile_directory, str) and profile_directory:
			_append_unique(args, seen, f'--profile-directory={profile_directory}')
	return args


def _managed_browser_profile_dir(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> str | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'user_data_dir', None)
		if isinstance(value, (str, os.PathLike)) and str(value):
			return str(Path(value).expanduser())
	return None


def _managed_browser_executable_path(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> str | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'executable_path', None)
		if isinstance(value, (str, os.PathLike)) and str(value):
			return str(Path(value).expanduser())
	return None


def _env_value_to_str(value: Any) -> str | None:
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (str, int, float, os.PathLike)):
		return str(value)
	return None


def _managed_browser_env(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> dict[str, str]:
	env: dict[str, str] = {}
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		raw_env = getattr(profile, 'env', None)
		if not isinstance(raw_env, dict):
			continue
		for key, value in raw_env.items():
			env_value = _env_value_to_str(value)
			if isinstance(key, str) and key and env_value is not None:
				env[key] = env_value
	return env


def _extract_cdp_headers(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> dict[str, str]:
	headers: dict[str, str] = {}
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		raw_headers = getattr(profile, 'headers', None)
		if not isinstance(raw_headers, dict):
			continue
		for key, value in raw_headers.items():
			header_value = _env_value_to_str(value)
			if isinstance(key, str) and key and header_value is not None:
				headers[key] = header_value
	return headers


def _extract_user_agent(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> str | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'user_agent', None)
		if isinstance(value, str) and value:
			return value
	return None


def _extract_highlight_settings(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> tuple[bool | None, str | None, int | None]:
	enabled: bool | None = None
	color: str | None = None
	duration_ms: int | None = None
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		if enabled is None:
			if getattr(profile, 'dom_highlight_elements', None) is True:
				enabled = False
			else:
				value = getattr(profile, 'highlight_elements', None)
				if isinstance(value, bool):
					enabled = value
		if color is None:
			value = getattr(profile, 'interaction_highlight_color', None)
			if isinstance(value, str) and value:
				color = value
		if duration_ms is None:
			value = getattr(profile, 'interaction_highlight_duration', None)
			if isinstance(value, (int, float)) and value >= 0:
				duration_ms = int(value * 1000)
	return enabled, color, duration_ms


def _seconds_to_ms(value: Any) -> int | None:
	if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
		return None
	return int(value * 1000)


def _extract_wait_timing_settings(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> dict[str, str]:
	settings: dict[str, str] = {}
	session_profile = getattr(browser_session, 'browser_profile', None)
	mappings = (
		('minimum_wait_page_load_time', 'BU_BROWSER_MINIMUM_WAIT_PAGE_LOAD_MS'),
		('wait_for_network_idle_page_load_time', 'BU_BROWSER_NETWORK_IDLE_PAGE_LOAD_MS'),
		('wait_between_actions', 'BU_BROWSER_WAIT_BETWEEN_ACTIONS_MS'),
	)
	for profile in (session_profile, browser_profile, browser_session):
		for attr, env_name in mappings:
			if env_name in settings:
				continue
			value_ms = _seconds_to_ms(getattr(profile, attr, None))
			if value_ms is not None:
				settings[env_name] = str(value_ms)
	return settings


def _extract_block_ip_addresses(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> bool | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = getattr(profile, 'block_ip_addresses', None)
		if isinstance(value, bool):
			return value
	return None


def _extract_profile_permissions(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> list[str]:
	values: list[str] = []
	seen: set[str] = set()
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		raw_permissions = getattr(profile, 'permissions', None)
		if isinstance(raw_permissions, set):
			raw_permissions = sorted(raw_permissions)
		if not isinstance(raw_permissions, (list, tuple)):
			continue
		for permission in raw_permissions:
			if not isinstance(permission, str) or not permission or permission in seen:
				continue
			values.append(permission)
			seen.add(permission)
	return values


def _extract_browser_downloads(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> tuple[bool | None, str | None]:
	accept_downloads: bool | None = None
	downloads_path: str | None = None
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		if accept_downloads is None:
			value = getattr(profile, 'accept_downloads', None)
			if isinstance(value, bool):
				accept_downloads = value
		if downloads_path is None:
			value = getattr(profile, 'downloads_path', None)
			if isinstance(value, (str, os.PathLike)) and str(value):
				downloads_path = str(Path(value).expanduser())
	return accept_downloads, downloads_path


def _viewport_size(value: Any) -> tuple[int, int] | None:
	if value is None:
		return None
	if isinstance(value, (list, tuple)) and len(value) >= 2:
		width, height = value[0], value[1]
	else:
		width = _value_from_object(value, 'width')
		height = _value_from_object(value, 'height')
	if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
		return None
	return width, height


def _extract_browser_viewport(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> tuple[bool | None, dict[str, int | float] | None]:
	no_viewport: bool | None = None
	viewport_size: tuple[int, int] | None = None
	screen_size: tuple[int, int] | None = None
	device_scale_factor: int | float | None = None
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		if no_viewport is None:
			value = getattr(profile, 'no_viewport', None)
			if isinstance(value, bool):
				no_viewport = value
		if viewport_size is None:
			viewport_size = _viewport_size(getattr(profile, 'viewport', None))
		if screen_size is None:
			screen_size = _viewport_size(getattr(profile, 'screen', None))
		if device_scale_factor is None:
			value = getattr(profile, 'device_scale_factor', None)
			if isinstance(value, (int, float)) and value >= 0:
				device_scale_factor = value
	if no_viewport is True:
		return no_viewport, None
	if viewport_size is None and no_viewport is False:
		viewport_size = screen_size
	if viewport_size is None:
		return no_viewport, None
	width, height = viewport_size
	viewport: dict[str, int | float] = {
		'width': width,
		'height': height,
		'deviceScaleFactor': 1 if device_scale_factor is None else device_scale_factor,
	}
	if screen_size is not None:
		screen_width, screen_height = screen_size
		viewport['screenWidth'] = screen_width
		viewport['screenHeight'] = screen_height
	return no_viewport, viewport


def _extract_browser_window_size(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> dict[str, int] | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		window_size = _viewport_size(getattr(profile, 'window_size', None))
		if window_size is not None:
			width, height = window_size
			return {'width': width, 'height': height}
	return None


def _storage_state_value(value: Any) -> dict[str, Any] | None:
	if isinstance(value, dict):
		return value
	if hasattr(value, 'model_dump'):
		dumped = value.model_dump()
		return dumped if isinstance(dumped, dict) else None
	if isinstance(value, (str, os.PathLike)) and str(value):
		path = Path(value).expanduser()
		if not path.exists():
			return None
		try:
			loaded = json.loads(path.read_text())
		except (OSError, json.JSONDecodeError):
			return None
		return loaded if isinstance(loaded, dict) else None
	return None


def _extract_browser_storage_state(
	browser_session: BrowserSession | None, browser_profile: BrowserProfile | None
) -> dict[str, Any] | None:
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile, browser_session):
		value = _storage_state_value(getattr(profile, 'storage_state', None))
		if value is not None:
			return value
	return None


def _is_managed_browser_mode(mode: str) -> bool:
	normalized = mode.strip().lower().replace('_', '-').replace(' ', '-')
	return normalized in {'managed-headless', 'headless', 'headless-chromium', 'managed-headed', 'managed', 'headed'}


def _domain_list(value: Any) -> list[str]:
	if value is None or isinstance(value, str):
		return []
	if isinstance(value, set):
		items = sorted(value)
	elif isinstance(value, list):
		items = value
	else:
		return []
	return [item for item in items if isinstance(item, str) and item]


def _extract_profile_domains(
	browser_session: BrowserSession | None,
	browser_profile: BrowserProfile | None,
	attr: str,
) -> list[str]:
	values: list[str] = []
	seen: set[str] = set()
	session_profile = getattr(browser_session, 'browser_profile', None)
	for profile in (session_profile, browser_profile):
		for domain in _domain_list(getattr(profile, attr, None)):
			if domain in seen:
				continue
			values.append(domain)
			seen.add(domain)
	return values


def _sensitive_data_context(sensitive_data: dict[str, str | dict[str, str]] | None) -> dict[str, Any]:
	if not sensitive_data:
		return {'global_placeholders': [], 'domain_placeholders': {}}
	global_placeholders: list[str] = []
	domain_placeholders: dict[str, list[str]] = {}
	for key, value in sensitive_data.items():
		if isinstance(value, dict):
			placeholders = sorted(name for name, secret in value.items() if isinstance(name, str) and name and secret)
			if placeholders:
				domain_placeholders[key] = placeholders
		elif isinstance(value, str) and value:
			global_placeholders.append(key)
	return {
		'global_placeholders': sorted(global_placeholders),
		'domain_placeholders': domain_placeholders,
	}


def _sensitive_domain_is_allowed(domain_pattern: str, allowed_domain: str) -> bool:
	if domain_pattern == allowed_domain or allowed_domain == '*':
		return True
	pattern_domain = domain_pattern.split('://')[-1] if '://' in domain_pattern else domain_pattern
	allowed_domain_part = allowed_domain.split('://')[-1] if '://' in allowed_domain else allowed_domain
	return pattern_domain == allowed_domain_part or (
		allowed_domain_part.startswith('*.')
		and (pattern_domain == allowed_domain_part[2:] or pattern_domain.endswith('.' + allowed_domain_part[2:]))
	)


def _warn_sensitive_data_domain_constraints(
	logger: logging.Logger,
	sensitive_data: dict[str, str | dict[str, str]] | None,
	allowed_domains: list[str],
) -> None:
	if not sensitive_data:
		return
	if not allowed_domains:
		logger.warning(
			'⚠️ Agent(sensitive_data=••••••••) was provided but Browser(allowed_domains=[...]) is not locked down! ⚠️\n'
			'          ☠️ If the agent visits a malicious website and encounters a prompt-injection attack, your sensitive_data may be exposed!\n\n'
			'   \n'
		)
		return
	for domain_pattern, value in sensitive_data.items():
		if not isinstance(value, dict):
			continue
		if not any(_sensitive_domain_is_allowed(domain_pattern, allowed_domain) for allowed_domain in allowed_domains):
			logger.warning(
				f'⚠️ Domain pattern "{domain_pattern}" in sensitive_data is not covered by any pattern in allowed_domains={allowed_domains}\n'
				f'   This may be a security risk as credentials could be used on unintended domains.'
			)


def _string_env_value(value: Any) -> str | None:
	if value is None:
		return None
	text = str(value).strip()
	return text or None


def _direct_initial_navigation_enabled() -> bool:
	raw = os.getenv('BROWSER_USE_RUST_DIRECT_INITIAL_NAVIGATION')
	if raw is None:
		return True
	return raw.strip().lower() not in {'0', 'false', 'no', 'off'}


def _llm_provider_name(llm: Any) -> str | None:
	provider = getattr(llm, 'provider', None)
	if callable(provider):
		try:
			provider = provider()
		except TypeError:
			provider = None
	text = _string_env_value(provider)
	return text.lower() if text else None


def _llm_env_overrides(llm: Any) -> dict[str, str]:
	provider = _llm_provider_name(llm)
	if provider is None:
		return {}
	api_key = _string_env_value(getattr(llm, 'api_key', None))
	base_url = _string_env_value(getattr(llm, 'base_url', None))
	overrides: dict[str, str] = {}
	if provider == 'openai':
		if api_key:
			overrides['LLM_BROWSER_OPENAI_API_KEY'] = api_key
		if base_url:
			overrides['LLM_BROWSER_OPENAI_BASE_URL'] = base_url
	elif provider == 'anthropic':
		if api_key:
			overrides['LLM_BROWSER_ANTHROPIC_API_KEY'] = api_key
		if base_url:
			overrides['LLM_BROWSER_ANTHROPIC_BASE_URL'] = base_url
	elif provider == 'openrouter':
		if api_key:
			overrides['OPENROUTER_API_KEY'] = api_key
		if base_url:
			overrides['OPENROUTER_BASE_URL'] = base_url
	elif provider == 'deepseek' and api_key:
		overrides['DEEPSEEK_API_KEY'] = api_key
	elif provider == 'browser-use':
		if api_key:
			overrides['LLM_BROWSER_BROWSER_USE_API_KEY'] = api_key
		if base_url:
			overrides['LLM_BROWSER_BROWSER_USE_BASE_URL'] = base_url.rstrip('/').removesuffix('/v1')
	return overrides


def _navigation_url_from_action(action: Any) -> str | None:
	params = _initial_navigation_params_from_action(action)
	return params[0] if params is not None else None


def _initial_navigation_params_from_action(action: Any) -> tuple[str, bool] | None:
	if not isinstance(action, dict):
		return None
	for name, payload in action.items():
		if name in ('open_tab', 'go_to_url', 'navigate') and isinstance(payload, dict):
			url = payload.get('url')
			if isinstance(url, str) and url:
				new_tab = name == 'open_tab' or bool(payload.get('new_tab'))
				return url, new_tab
	return None


def _initial_navigation_url(initial_actions: Any) -> str | None:
	if not isinstance(initial_actions, list):
		return None
	for action in initial_actions:
		url = _navigation_url_from_action(action)
		if url:
			return url
	return None


def _task_with_initial_actions(task: str, initial_actions: Any) -> str:
	if not isinstance(initial_actions, list) or not initial_actions:
		return task
	if len(initial_actions) == 1:
		url = _navigation_url_from_action(initial_actions[0])
		if url:
			return f'First navigate to {url!r}, then complete the task.\n\n{task}'
	actions = json.dumps(initial_actions, indent=2, default=str)
	return f'Before the task, perform these Browser Use initial actions in order:\n{actions}\n\nThen complete the task.\n\n{task}'


def _initial_navigation_state_lines(completed_states: list[dict[str, Any]] | None) -> list[str]:
	lines: list[str] = []
	for state in completed_states or []:
		requested_url = str(state.get('requested_url') or '')
		current_url = str(state.get('url') or '')
		title = str(state.get('title') or '')
		if not requested_url and not current_url and not title:
			continue
		parts = []
		if requested_url:
			parts.append(f'requested={requested_url!r}')
		if current_url:
			parts.append(f'current_url={current_url!r}')
		if title:
			parts.append(f'title={title!r}')
		lines.append('- ' + ', '.join(parts))
	return lines


def _task_with_completed_initial_navigation_context(
	task: str,
	completed_urls: list[str],
	initial_actions: Any = None,
	completed_states: list[dict[str, Any]] | None = None,
) -> str:
	urls = [url for url in completed_urls if isinstance(url, str) and url]
	if not urls:
		return task
	cleaned_task = task
	state_lines = _initial_navigation_state_lines(completed_states)
	state_context = ''
	if state_lines:
		state_context = '\nObserved current page after the completed initial navigation:\n' + '\n'.join(state_lines)
	if len(urls) == 1:
		prefix = f'First navigate to {urls[0]!r}, then complete the task.\n\n'
		if cleaned_task.startswith(prefix):
			cleaned_task = cleaned_task[len(prefix) :]
		return (
			f'The browser session is already open at {urls[0]!r}. '
			'Continue from the current page. Your first browser step should inspect or extract from the current page before any repeat navigation. '
			'Do not navigate to that same start URL again unless browser status or page_info shows a different URL.'
			f'{state_context}'
			f'\n\n{cleaned_task}'
		)
	initial_action_urls: list[str] = []
	if isinstance(initial_actions, list):
		for action in initial_actions:
			url = _navigation_url_from_action(action)
			if url:
				initial_action_urls.append(url)
	if initial_action_urls == urls:
		actions = json.dumps(initial_actions, indent=2, default=str)
		prefix = f'Before the task, perform these Browser Use initial actions in order:\n{actions}\n\nThen complete the task.\n\n'
		if cleaned_task.startswith(prefix):
			cleaned_task = cleaned_task[len(prefix) :]
	completed = ', '.join(repr(url) for url in urls)
	return (
		f'The browser session has already completed these initial navigations: {completed}. '
		'Continue from the current browser state. Do not repeat those navigation steps unless browser status shows a different page.'
		f'{state_context}'
		f'\n\n{cleaned_task}'
	)


def _task_with_schema(task: str, output_model_schema: type[BaseModel] | None) -> str:
	if output_model_schema is None:
		return task
	schema = json.dumps(output_model_schema.model_json_schema(), indent=2)
	return f'{task}\n\nExpected output JSON schema for the final answer:\n{schema}'


def _task_with_available_files(task: str, available_file_paths: list[str] | None) -> str:
	if not available_file_paths:
		return task
	files = '\n'.join(f'- {Path(path).expanduser()}' for path in available_file_paths)
	return f'{task}\n\nAvailable local files:\n{files}'


def _task_with_domain_constraints(task: str, allowed_domains: list[str], prohibited_domains: list[str]) -> str:
	if not allowed_domains and not prohibited_domains:
		return task
	sections = ['Browser profile navigation constraints:']
	if allowed_domains:
		sections.append('Allowed domains:')
		sections.extend(f'- {domain}' for domain in allowed_domains)
	if prohibited_domains:
		sections.append('Prohibited domains:')
		sections.extend(f'- {domain}' for domain in prohibited_domains)
	sections.append('Respect these BrowserProfile domain constraints when navigating.')
	return f'{task}\n\n' + '\n'.join(sections)


def _task_with_sensitive_data_context(task: str, sensitive_context: dict[str, Any]) -> str:
	global_placeholders = sensitive_context.get('global_placeholders') or []
	domain_placeholders = sensitive_context.get('domain_placeholders') or {}
	if not global_placeholders and not domain_placeholders:
		return task
	sections = ['Sensitive data placeholders are available. Use <secret>placeholder</secret> when a matching secret is needed.']
	if global_placeholders:
		sections.append('Global placeholders:')
		sections.extend(f'- {placeholder}' for placeholder in global_placeholders)
	if domain_placeholders:
		sections.append('Domain-scoped placeholders:')
		for domain, placeholders in domain_placeholders.items():
			sections.append(f'- {domain}: {", ".join(placeholders)}')
	sections.append('Do not reveal placeholder values in the final answer.')
	return f'{task}\n\n' + '\n'.join(sections)


def _extract_start_url(task: str) -> str | None:
	task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)
	patterns = [
		r'https?://[^\s<>"\']+',
		r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',
	]
	excluded_extensions = {
		'pdf',
		'doc',
		'docx',
		'xls',
		'xlsx',
		'ppt',
		'pptx',
		'odt',
		'ods',
		'odp',
		'txt',
		'md',
		'csv',
		'json',
		'xml',
		'yaml',
		'yml',
		'zip',
		'rar',
		'7z',
		'tar',
		'gz',
		'bz2',
		'xz',
		'jpg',
		'jpeg',
		'png',
		'gif',
		'bmp',
		'svg',
		'webp',
		'ico',
		'mp3',
		'mp4',
		'avi',
		'mkv',
		'mov',
		'wav',
		'flac',
		'ogg',
		'py',
		'js',
		'css',
		'java',
		'cpp',
		'bib',
		'bibtex',
		'tex',
		'latex',
		'cls',
		'sty',
		'exe',
		'msi',
		'dmg',
		'pkg',
		'deb',
		'rpm',
		'iso',
	}
	excluded_words = {'never', 'dont', 'not', "don't"}

	found_urls = []
	for pattern in patterns:
		for match in re.finditer(pattern, task_without_emails):
			url = sanitize_url_candidate(match.group(0))
			url_lower = url.lower()
			if is_placeholder_url(url):
				continue
			if any(f'.{ext}' in url_lower for ext in excluded_extensions):
				continue
			context_start = max(0, match.start() - 20)
			context_text = task_without_emails[context_start : match.start()]
			if any(word in context_text.lower() for word in excluded_words):
				continue
			if not url.startswith(('http://', 'https://')):
				url = 'https://' + url
			found_urls.append(url)

	unique_urls = list(set(found_urls))
	return unique_urls[0] if len(unique_urls) == 1 else None


def _event_type(event: dict[str, Any]) -> str:
	return str(event.get('event_type') or event.get('type') or '')


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
	payload = event.get('payload')
	return payload if isinstance(payload, dict) else {}


def _event_seq(event: dict[str, Any]) -> int | None:
	for key in ('seq', 'event_seq', 'sequence'):
		value = event.get(key)
		if isinstance(value, bool):
			continue
		if isinstance(value, int):
			return value
	return None


def _rollback_turn_count(payload: dict[str, Any]) -> int:
	for key in ('num_turns', 'turns', 'n'):
		value = payload.get(key)
		if isinstance(value, bool):
			continue
		if isinstance(value, int) and value >= 0:
			return value
	return 1


def _is_terminal_user_turn_event(event: dict[str, Any]) -> bool:
	event_type = _event_type(event)
	if event_type in ('session.input', 'session.followup'):
		return True
	if event_type in ('agent.message', 'agent.mailbox_input'):
		content = _event_payload(event).get('content')
		return isinstance(content, str) and bool(content.strip())
	return False


def _contextual_event_targets_turn(event: dict[str, Any], target_seq: int | None) -> bool:
	if target_seq is None:
		return False
	if _event_type(event) not in (
		'workspace.context',
		'model.switch_context',
		'model.personality_context',
		'model.collaboration_context',
		'model.generated_image_context',
	):
		return False
	before_seq = _event_payload(event).get('before_seq')
	return isinstance(before_seq, int) and before_seq == target_seq


def _compaction_replay_start_seq(event: dict[str, Any]) -> int | None:
	replay_from_seq = _event_payload(event).get('replay_from_seq')
	if isinstance(replay_from_seq, bool):
		return None
	if isinstance(replay_from_seq, int):
		return replay_from_seq
	return _event_seq(event)


def _events_after_terminal_compaction(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
	compaction_index = next(
		(index for index in range(len(events) - 1, -1, -1) if _event_type(events[index]) == 'session.compacted'), None
	)
	if compaction_index is None:
		return events
	replay_start_seq = _compaction_replay_start_seq(events[compaction_index])
	if replay_start_seq is None:
		return events[compaction_index + 1 :]
	replay_events: list[dict[str, Any]] = []
	for index, event in enumerate(events):
		seq = _event_seq(event)
		if seq is not None:
			if seq > replay_start_seq:
				replay_events.append(event)
		elif index > compaction_index:
			replay_events.append(event)
	return replay_events


def _rollback_last_terminal_user_turn(events: list[dict[str, Any]]) -> bool:
	user_pos = next((index for index in range(len(events) - 1, -1, -1) if _is_terminal_user_turn_event(events[index])), None)
	if user_pos is None:
		return False
	target_seq = _event_seq(events[user_pos])
	truncate_at = user_pos
	while truncate_at > 0 and _contextual_event_targets_turn(events[truncate_at - 1], target_seq):
		truncate_at -= 1
	del events[truncate_at:]
	return True


def _events_after_terminal_rollbacks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
	if not any(_event_type(event) == 'session.rollback' for event in events):
		return events
	replay_events: list[dict[str, Any]] = []
	for event in events:
		if _event_type(event) == 'session.rollback':
			for _ in range(_rollback_turn_count(_event_payload(event))):
				if not _rollback_last_terminal_user_turn(replay_events):
					break
			continue
		replay_events.append(event)
	return replay_events


def _result_file_pointer(payload: dict[str, Any]) -> str | None:
	result_file = payload.get('result_file')
	if isinstance(result_file, dict):
		for key in ('url', 'path'):
			value = result_file.get(key)
			if isinstance(value, str) and value:
				return value
	if isinstance(result_file, str) and result_file:
		return result_file
	for key in ('result_file_url', 'result_file_path', 'result_file'):
		value = payload.get(key)
		if isinstance(value, str) and value:
			return value
	return None


def _artifact_attachment_pointer(value: Any) -> str | None:
	if isinstance(value, str) and value:
		return value
	if not isinstance(value, dict):
		return None
	kind = value.get('kind')
	mime = value.get('mime_type') or value.get('mime')
	if isinstance(kind, str) and kind.lower() == 'image':
		return None
	if isinstance(mime, str) and mime.lower().startswith('image/'):
		return None
	for key in ('url', 'file_url', 'path'):
		pointer = value.get(key)
		if isinstance(pointer, str) and pointer:
			return pointer
	return None


def _done_tool_result_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		event_type = _event_type(event)
		if event_type not in ('tool.started', 'tool.output', 'tool.finished'):
			continue
		payload = _event_payload(event)
		if payload.get('name') != 'done':
			continue
		arguments = payload.get('arguments')
		if isinstance(arguments, dict):
			for key in ('text', 'result', 'answer'):
				value = arguments.get(key)
				if isinstance(value, str) and value.strip():
					return value.strip()
		text = _tool_result_text(payload)
		if not text:
			continue
		text = text.strip()
		if text.lower().startswith('done:'):
			text = text[5:].strip()
		if text:
			return text
	return None


def _result_from_events(events: list[dict[str, Any]]) -> str | None:
	done_result = _done_tool_result_from_events(events)
	if done_result:
		return done_result
	for event in reversed(events):
		if _event_type(event) != 'session.done':
			continue
		payload = _event_payload(event)
		result = payload.get('result')
		if isinstance(result, str) and result.strip():
			return result.strip()
		result_file = _result_file_pointer(payload)
		if result_file:
			return f'Saved result file.\n\nFile:\n{result_file}'
	for event in reversed(events):
		if _event_type(event) != 'agent.completed':
			continue
		payload = _event_payload(event).get('payload')
		if not isinstance(payload, dict):
			continue
		result = payload.get('result')
		if isinstance(result, str) and result.strip():
			return result.strip()
	return None


def _last_streamed_assistant_text_from_events(events: list[dict[str, Any]]) -> str | None:
	last_request_index = next(
		(index for index in range(len(events) - 1, -1, -1) if _event_type(events[index]) == 'model.turn.request'),
		-1,
	)
	candidates = events[last_request_index + 1 :] if last_request_index >= 0 else events
	text = _streaming_text_from_events(candidates, ('model.delta', 'model.stream_delta', 'model.response.output_item'))
	if not isinstance(text, str):
		return None
	text = text.strip()
	return text or None


def _attachments_from_events(events: list[dict[str, Any]]) -> list[str] | None:
	attachments: list[str] = []
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		pointers: list[str] = []
		if event_type == 'session.done':
			result_file = _result_file_pointer(payload)
			if result_file:
				pointers.append(result_file)
		elif event_type in ('artifact.created', 'tool.output_spilled'):
			pointer = _artifact_attachment_pointer(payload.get('artifact'))
			if pointer:
				pointers.append(pointer)
		elif event_type == 'capture.curation':
			gif_path = payload.get('gif_path')
			if isinstance(gif_path, str) and gif_path:
				pointers.append(gif_path)
		elif event_type in ('tool.output', 'tool.failed'):
			text_artifact = _artifact_attachment_pointer(payload.get('text_artifact'))
			if text_artifact:
				pointers.append(text_artifact)
			artifacts = payload.get('artifacts')
			if isinstance(artifacts, list):
				for artifact in artifacts:
					pointer = _artifact_attachment_pointer(artifact)
					if pointer:
						pointers.append(pointer)
		for pointer in pointers:
			if pointer not in attachments:
				attachments.append(pointer)
	return attachments or None


def _json_result_candidates(text: str) -> list[str]:
	candidates = [text.strip()]
	candidates.extend(
		match.group(1).strip() for match in re.finditer(r'```(?:json)?\s*(.*?)```', text, re.IGNORECASE | re.DOTALL)
	)
	decoder = json.JSONDecoder()
	for index, char in enumerate(text):
		if char not in '{[':
			continue
		try:
			parsed, _end = decoder.raw_decode(text[index:])
		except json.JSONDecodeError:
			continue
		candidates.append(json.dumps(parsed))
	seen = set()
	unique = []
	for candidate in candidates:
		if not candidate or candidate in seen:
			continue
		seen.add(candidate)
		unique.append(candidate)
	return unique


def _structured_result_text(
	result: str | None,
	output_model_schema: type[BaseModel] | None,
) -> str | None:
	if result is None or output_model_schema is None:
		return result
	for candidate in _json_result_candidates(result):
		try:
			output_model_schema.model_validate_json(candidate)
		except (ValidationError, ValueError):
			continue
		return candidate
	return result


def _failure_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		event_type = _event_type(event)
		if event_type in ('session.failed', 'stream_error'):
			payload = _event_payload(event)
			error = payload.get('error') or payload.get('message')
			if isinstance(error, str) and error:
				return error
		if event_type == 'session.cancelled':
			payload = _event_payload(event)
			reason = payload.get('reason') or payload.get('message') or payload.get('error')
			if isinstance(reason, str) and reason.strip():
				return f'Rust terminal session was cancelled: {reason.strip()}'
			return 'Rust terminal session was cancelled.'
		if event_type == 'session.interrupted':
			payload = _event_payload(event)
			reason = payload.get('reason') or payload.get('message') or payload.get('error')
			if isinstance(reason, str) and reason.strip():
				return f'Rust terminal session was interrupted: {reason.strip()}'
			return 'Rust terminal session was interrupted.'
		if event_type in ('agent.failed', 'agent.cancelled'):
			payload = _event_payload(event)
			inner_payload = payload.get('payload')
			if not isinstance(inner_payload, dict):
				inner_payload = payload
			detail = _payload_failure_detail(inner_payload)
			if detail:
				return detail
			if event_type == 'agent.cancelled':
				return 'Subagent was cancelled.'
			return 'Subagent failed.'
	return None


def _recoverable_failure_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'tool.failed':
			abort_payload = _matching_tool_abort_payload(events, payload)
			error = _tool_abort_message(abort_payload) if abort_payload is not None else _tool_failure_message(payload)
			if error:
				return error
		if event_type == 'tool.aborted':
			error = _tool_abort_message(payload)
			if error:
				return error
		if event_type == 'exec_command.end' and not _matching_tool_result_payload(
			events, payload, ('tool.failed', 'tool.aborted')
		):
			error = _exec_command_end_failure_message(payload)
			if error:
				return error
		if event_type in ('model.turn.error', 'model.turn.context_overflow'):
			error = payload.get('error') or payload.get('message') or payload.get('reason')
			if isinstance(error, str) and error.strip():
				return error.strip()
		error = _terminal_operational_failure_message(event_type, payload)
		if error:
			return error
	return None


def _tool_failure_message(payload: dict[str, Any]) -> str | None:
	error = payload.get('error')
	if not isinstance(error, str) or not error.strip():
		return None
	name = payload.get('name')
	return f'{name} failed: {error.strip()}' if isinstance(name, str) and name else error.strip()


def _tool_abort_message(payload: dict[str, Any]) -> str | None:
	error = payload.get('error') or payload.get('reason') or payload.get('message')
	if not isinstance(error, str) or not error.strip():
		error = 'aborted'
	name = payload.get('name')
	return f'{name} aborted: {error.strip()}' if isinstance(name, str) and name else error.strip()


def _exec_command_end_failure_message(payload: dict[str, Any]) -> str | None:
	exit_code = _int_value(payload.get('exit_code'))
	if exit_code == 0:
		return None
	name = payload.get('name')
	tool_name = name if isinstance(name, str) and name else 'exec_command'
	detail = f'exit code {exit_code}'
	text = _tool_result_text(payload)
	if text:
		detail = f'{detail}: {text}'
	return f'{tool_name} failed: {detail}'


def _payload_failure_detail(payload: dict[str, Any]) -> str | None:
	for key in ('error', 'failure', 'message', 'reason', 'detail', 'details'):
		value = payload.get(key)
		if isinstance(value, str) and value.strip():
			return value.strip()
	if isinstance(payload.get('errors'), list):
		errors = [str(error).strip() for error in payload['errors'] if str(error).strip()]
		if errors:
			return '; '.join(errors)
	return None


def _terminal_operational_failure_message(event_type: str, payload: dict[str, Any]) -> str | None:
	if event_type == 'session.final_answer_not_ready_at_max_turns':
		return _payload_failure_detail(payload) or 'final answer artifact is not ready'
	if event_type == 'browser.cleanup_timed_out':
		timeout_ms = _int_value(payload.get('timeout_ms'))
		if timeout_ms:
			return f'browser cleanup timed out after {timeout_ms}ms'
		return 'browser cleanup timed out'
	labels = {
		'browser.cloud_shutdown_failed': 'browser cloud shutdown failed',
		'browser.cleanup_failed': 'browser cleanup failed',
		'browser.bridge_errors': 'browser bridge failed',
		'command.write_error': 'command write failed',
		'session.compaction_failed': 'session compaction failed',
	}
	label = labels.get(event_type)
	if label is None:
		return None
	detail = _payload_failure_detail(payload)
	return f'{label}: {detail}' if detail else label


def _command_waiting_text(payload: dict[str, Any]) -> str:
	session_id = payload.get('session_id') or payload.get('process_id')
	if session_id is not None and str(session_id):
		return f'Process running with session ID {session_id}'
	return 'Process running'


def _command_waiting_payload(payload: dict[str, Any], previous_payload: dict[str, Any] | None) -> dict[str, Any]:
	waiting_text = _command_waiting_text(payload)
	previous_text = _tool_result_text(previous_payload) if previous_payload is not None else None
	if previous_text and waiting_text not in previous_text:
		waiting_text = f'{previous_text}\n\n{waiting_text}'
	next_payload = dict(payload)
	next_payload['text'] = waiting_text
	return next_payload


_TOOL_OUTPUT_DELTA_EVENTS = ('tool.output_delta', 'exec_command.output_delta', 'browser_script.output_delta')
_BROWSER_SCRIPT_RESULT_EVENTS = ('browser_script.completed', 'browser_script.cancelled', 'browser_script.failed')


_TEXTUAL_TOOL_RESULT_EVENTS = (
	'tool.output',
	'tool.output_delta',
	'exec_command.output_delta',
	'browser_script.output_delta',
	'command.waiting',
	'exec_command.end',
	'tool.finished',
	'model.response.input_item',
	'browser_script.completed',
	'browser_script.cancelled',
)
_MAX_TERMINAL_LONG_TERM_TEXT_LENGTH = 1000


def _is_redundant_paired_output_delta(
	previous_event_type: str,
	previous_payload: dict[str, Any],
	event_type: str,
	payload: dict[str, Any],
	delta_text: str,
) -> bool:
	if previous_event_type not in _TOOL_OUTPUT_DELTA_EVENTS or previous_event_type == event_type:
		return False
	previous_text = previous_payload.get('text')
	if not isinstance(previous_text, str) or not previous_text.endswith(delta_text):
		return False
	previous_stream = previous_payload.get('stream')
	stream = payload.get('stream')
	if previous_stream is not None and stream is not None and previous_stream != stream:
		return False
	previous_session_id = previous_payload.get('session_id') or previous_payload.get('process_id')
	session_id = payload.get('session_id') or payload.get('process_id')
	if previous_session_id is not None and session_id is not None and str(previous_session_id) != str(session_id):
		return False
	return True


def _tool_result_key(payload: dict[str, Any]) -> tuple[str, str] | None:
	call_id = payload.get('tool_call_id') or payload.get('call_id')
	if call_id:
		return ('call_id', str(call_id))
	name = payload.get('name')
	if isinstance(name, str) and name:
		return ('name', name)
	return None


def _matching_tool_result_payload(
	events: list[dict[str, Any]], payload: dict[str, Any], event_types: tuple[str, ...]
) -> dict[str, Any] | None:
	key = _tool_result_key(payload)
	if key is None:
		return None
	for event in events:
		if _event_type(event) not in event_types:
			continue
		result_payload = _event_payload(event)
		if _tool_result_key(result_payload) == key:
			return result_payload
	return None


def _matching_tool_abort_payload(events: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any] | None:
	return _matching_tool_result_payload(events, payload, ('tool.aborted',))


def _safe_tool_action_name(value: Any) -> str | None:
	if not isinstance(value, str):
		return None
	name = value.strip()
	if not name or name.startswith('_') or not name.isidentifier() or keyword.iskeyword(name):
		return None
	return name


def _tool_arguments(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except json.JSONDecodeError:
			return {'value': value}
		return parsed if isinstance(parsed, dict) else {'value': parsed}
	if value is None:
		return {}
	return {'value': value}


def _tool_call_from_payload(payload: dict[str, Any], fallback_id: str) -> dict[str, Any] | None:
	function = payload.get('function')
	if not isinstance(function, dict):
		function = {}
	name = _safe_tool_action_name(payload.get('name') or function.get('name'))
	if name is None:
		return None
	raw_call_id = payload.get('tool_call_id') or payload.get('call_id') or payload.get('id')
	call_id = raw_call_id or fallback_id
	arguments = payload.get('arguments')
	if arguments is None:
		arguments = function.get('arguments')
	return {
		'name': name,
		'tool_call_id': str(call_id),
		'_has_explicit_tool_call_id': raw_call_id is not None,
		'arguments': _tool_arguments(arguments),
	}


def _tool_call_from_response_item(payload: dict[str, Any], fallback_id: str) -> dict[str, Any] | None:
	item = payload.get('item')
	if not isinstance(item, dict):
		return None
	if item.get('type') not in ('function_call', 'custom_tool_call'):
		return None
	return _tool_call_from_payload(item, fallback_id)


def _tool_started_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
	tool_calls: list[dict[str, Any]] = []
	seen_call_ids: set[str] = set()
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type in ('tool.started', 'model.tool_call'):
			tool_call = _tool_call_from_payload(payload, f'tool-{len(tool_calls)}')
		elif event_type == 'model.response.output_item':
			tool_call = _tool_call_from_response_item(payload, f'tool-{len(tool_calls)}')
		else:
			continue
		if tool_call is None:
			continue
		call_id = tool_call['tool_call_id']
		if call_id in seen_call_ids:
			continue
		seen_call_ids.add(call_id)
		tool_calls.append(tool_call)
	return tool_calls


def _tool_calls_with_final_done(
	tool_calls: list[dict[str, Any]],
	*,
	final_result: str | None,
	attachments: list[str] | None,
	is_done: bool,
) -> list[dict[str, Any]]:
	if not is_done or final_result is None:
		return tool_calls
	if tool_calls and tool_calls[-1].get('name') == 'done':
		return tool_calls
	done_arguments: dict[str, Any] = {'text': final_result, 'success': True}
	if attachments:
		done_arguments['files_to_display'] = attachments
	return [
		*tool_calls,
		{
			'name': 'done',
			'tool_call_id': 'session.done',
			'arguments': done_arguments,
		},
	]


def _tool_results_by_call_id(events: list[dict[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
	results: dict[str, tuple[str, dict[str, Any]]] = {}
	for event in events:
		event_type = _event_type(event)
		if event_type not in (
			'tool.output',
			'tool.output_delta',
			'exec_command.output_delta',
			'browser_script.output_delta',
			'command.waiting',
			'exec_command.end',
			'tool.failed',
			'tool.aborted',
			'tool.finished',
			'model.response.input_item',
			*_BROWSER_SCRIPT_RESULT_EVENTS,
		):
			continue
		payload = _event_payload(event)
		if event_type == 'model.response.input_item':
			payload = _response_input_item_tool_payload(payload)
		if event_type in _TOOL_OUTPUT_DELTA_EVENTS:
			delta_text = _tool_output_delta_text(payload)
			if not delta_text:
				continue
		if event_type == 'exec_command.end' and not _tool_result_text(payload):
			continue
		call_id = payload.get('tool_call_id') or payload.get('call_id')
		if call_id:
			key = str(call_id)
			previous = results.get(key)
			if event_type in _TOOL_OUTPUT_DELTA_EVENTS:
				if previous is not None and previous[0] not in (*_TOOL_OUTPUT_DELTA_EVENTS, 'tool.finished'):
					continue
				if (
					previous is not None
					and delta_text
					and _is_redundant_paired_output_delta(previous[0], previous[1], event_type, payload, delta_text)
				):
					continue
				merged_payload = (
					dict(previous[1]) if previous is not None and previous[0] in _TOOL_OUTPUT_DELTA_EVENTS else dict(payload)
				)
				previous_text = (
					merged_payload.get('text') if previous is not None and previous[0] in _TOOL_OUTPUT_DELTA_EVENTS else ''
				)
				for payload_key, payload_value in payload.items():
					if payload_key != 'text':
						merged_payload[payload_key] = payload_value
				merged_payload['text'] = f'{previous_text if isinstance(previous_text, str) else ""}{delta_text}'
				results[key] = (event_type, merged_payload)
				continue
			if event_type == 'command.waiting':
				if previous is not None and previous[0] in (
					'tool.output',
					'tool.failed',
					'tool.aborted',
					'exec_command.end',
					'model.response.input_item',
				):
					continue
				results[key] = (event_type, _command_waiting_payload(payload, previous[1] if previous is not None else None))
				continue
			if (
				event_type == 'exec_command.end'
				and previous is not None
				and previous[0]
				in (
					'tool.output',
					'tool.failed',
					'tool.aborted',
					'model.response.input_item',
				)
			):
				continue
			if event_type == 'tool.failed' and previous is not None and previous[0] == 'tool.aborted':
				continue
			if event_type == 'tool.finished' and previous is not None and previous[0] != 'tool.finished':
				continue
			results[key] = (event_type, payload)
	return results


def _unkeyed_tool_results(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
	results: list[tuple[str, dict[str, Any]]] = []
	for event in events:
		event_type = _event_type(event)
		if event_type not in (
			'tool.output',
			'tool.output_delta',
			'exec_command.output_delta',
			'browser_script.output_delta',
			'command.waiting',
			'exec_command.end',
			'tool.failed',
			'tool.aborted',
			'tool.finished',
			'model.response.input_item',
			*_BROWSER_SCRIPT_RESULT_EVENTS,
		):
			continue
		payload = _event_payload(event)
		if event_type == 'model.response.input_item':
			payload = _response_input_item_tool_payload(payload)
		if payload.get('tool_call_id') or payload.get('call_id'):
			continue
		if event_type in _TOOL_OUTPUT_DELTA_EVENTS:
			delta_text = _tool_output_delta_text(payload)
			if not delta_text:
				continue
			name = payload.get('name')
			previous = next(
				(
					result
					for result in reversed(results)
					if isinstance(name, str) and name and result[0] in _TOOL_OUTPUT_DELTA_EVENTS and result[1].get('name') == name
				),
				None,
			)
			if previous is not None:
				previous_text = previous[1].get('text')
				previous[1]['text'] = f'{previous_text if isinstance(previous_text, str) else ""}{delta_text}'
				continue
			payload = dict(payload)
			payload['text'] = delta_text
		elif event_type == 'tool.output':
			name = payload.get('name')
			previous_delta_index = next(
				(
					index
					for index in range(len(results) - 1, -1, -1)
					if isinstance(name, str)
					and name
					and results[index][0] in _TOOL_OUTPUT_DELTA_EVENTS
					and results[index][1].get('name') == name
				),
				None,
			)
			if previous_delta_index is not None and payload.get('stream') is not True:
				results[previous_delta_index] = (event_type, payload)
				continue
		elif event_type == 'command.waiting':
			name = payload.get('name')
			previous_result_index = next(
				(
					index
					for index in range(len(results) - 1, -1, -1)
					if isinstance(name, str) and name and results[index][1].get('name') == name
				),
				None,
			)
			if previous_result_index is not None:
				previous_event_type, previous_payload = results[previous_result_index]
				if previous_event_type in (
					'tool.output',
					'tool.failed',
					'tool.aborted',
					'exec_command.end',
					'model.response.input_item',
				):
					continue
				results[previous_result_index] = (event_type, _command_waiting_payload(payload, previous_payload))
				continue
			payload = _command_waiting_payload(payload, None)
		elif event_type == 'exec_command.end':
			if not _tool_result_text(payload):
				continue
			name = payload.get('name')
			previous_result_index = next(
				(
					index
					for index in range(len(results) - 1, -1, -1)
					if isinstance(name, str) and name and results[index][1].get('name') == name
				),
				None,
			)
			if previous_result_index is not None:
				previous_event_type = results[previous_result_index][0]
				if previous_event_type in ('tool.output', 'tool.failed', 'tool.aborted', 'model.response.input_item'):
					continue
				results[previous_result_index] = (event_type, payload)
				continue
		if event_type == 'tool.output' and payload.get('stream') is True:
			continue
		if event_type == 'tool.failed':
			name = payload.get('name')
			previous_abort = next(
				(
					result
					for result in reversed(results)
					if isinstance(name, str) and name and result[0] == 'tool.aborted' and result[1].get('name') == name
				),
				None,
			)
			if previous_abort is not None:
				continue
		if event_type == 'tool.finished':
			name = payload.get('name')
			previous = next(
				(
					result
					for result in reversed(results)
					if isinstance(name, str) and name and result[0] != 'tool.finished' and result[1].get('name') == name
				),
				None,
			)
			if previous is not None:
				continue
		results.append((event_type, payload))
	return results


def _matching_unkeyed_tool_result_index(
	results: list[tuple[str, dict[str, Any]]],
	used_indices: set[int],
	name: Any,
	*,
	allow_any: bool,
) -> int | None:
	if isinstance(name, str) and name:
		for index, (_event_type, payload) in enumerate(results):
			if index not in used_indices and payload.get('name') == name:
				return index
	if not allow_any:
		return None
	for index in range(len(results)):
		if index not in used_indices:
			return index
	return None


def _matching_unkeyed_tool_attachment_index(
	attachments: list[tuple[str, list[str]]],
	used_indices: set[int],
	name: Any,
	*,
	allow_any: bool,
) -> int | None:
	if isinstance(name, str) and name:
		for index, (attachment_name, _paths) in enumerate(attachments):
			if index not in used_indices and attachment_name == name:
				return index
	if not allow_any:
		return None
	for index in range(len(attachments)):
		if index not in used_indices:
			return index
	return None


def _response_input_item_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
	item = payload.get('item')
	if not isinstance(item, dict):
		item = {}
	call_id = item.get('call_id') or item.get('id') or payload.get('call_id') or payload.get('id')
	result_payload: dict[str, Any] = dict(payload)
	if call_id:
		result_payload['tool_call_id'] = call_id
	name = item.get('name') or payload.get('name')
	if isinstance(name, str) and name:
		result_payload['name'] = name
	if 'output' in item:
		result_payload['output'] = item.get('output')
	elif 'content' in item:
		result_payload['content'] = item.get('content')
	return result_payload


def _tool_output_text(value: Any) -> str | None:
	if isinstance(value, str) and value.strip():
		return value.strip()
	if isinstance(value, list):
		text_parts = []
		for part in value:
			if isinstance(part, str):
				text_parts.append(part)
			elif isinstance(part, dict):
				text = part.get('text')
				if isinstance(text, str):
					text_parts.append(text)
		text = ''.join(text_parts).strip()
		return text or None
	if isinstance(value, dict):
		return json.dumps(value, ensure_ascii=False, default=str)
	return None


def _tool_output_delta_text(payload: dict[str, Any]) -> str | None:
	for key in ('text', 'delta', 'chunk'):
		value = payload.get(key)
		if isinstance(value, str) and value:
			return value
	return None


def _structured_tool_output_text(value: Any) -> str | None:
	if isinstance(value, str) and value.strip():
		return value.strip()
	if isinstance(value, (dict, list)) and value:
		return json.dumps(value, ensure_ascii=False, default=str)
	return None


def _tool_result_text(payload: dict[str, Any], *, include_completion_fallback: bool = True) -> str | None:
	for key in ('text', 'output', 'result'):
		text = _tool_output_text(payload.get(key))
		if text:
			return text
	content = payload.get('content')
	text = _tool_output_text(content)
	if text:
		return text
	text = _browser_script_running_tool_text(payload)
	if text:
		return text
	for key in ('summary', 'data', 'outputs'):
		text = _structured_tool_output_text(payload.get(key))
		if text:
			return text
	if include_completion_fallback and payload.get('name') == 'browser_script' and payload.get('ok') is True:
		status = payload.get('status')
		if status in ('finished', 'completed') or status is None:
			return 'browser_script completed'
	return None


def _browser_script_running_tool_text(payload: dict[str, Any]) -> str | None:
	if payload.get('name') != 'browser_script' or payload.get('status') != 'running':
		return None
	parts = ['browser_script is still running.']
	run_id = payload.get('run_id')
	if isinstance(run_id, str) and run_id:
		parts.append(f'run_id: {run_id}')
		observe_ms = _int_value(payload.get('next_observe_ms')) or 1000
		parts.append(
			f'Next step: call browser_script with action="observe", run_id="{run_id}", and observe_timeout_ms={observe_ms}.'
		)
	return '\n'.join(parts)


def _synthetic_tool_result_text(name: str) -> str:
	if name == 'update_plan':
		return 'Plan updated'
	if name == 'done':
		return 'done'
	return f'{name} completed'


def _terminal_tool_memory(name: str, text: str) -> tuple[str, bool]:
	if len(text) < _MAX_TERMINAL_LONG_TERM_TEXT_LENGTH:
		return text, False
	tool_name = name or 'tool'
	return (
		f'{tool_name} returned {len(text):,} characters. Full output was included once in <read_state> for that step.',
		True,
	)


def _append_streaming_text_delta(current: str, incoming: str) -> str:
	if not incoming:
		return current
	if not current:
		return incoming
	if incoming == current or incoming.strip() == current.strip():
		return current
	if incoming.startswith(current):
		return current + incoming[len(current) :]
	if len(incoming) >= 24 and current.endswith(incoming):
		return current
	return current + incoming


def _response_content_text(content: Any, part_types: tuple[str, ...]) -> str | None:
	if isinstance(content, str) and content.strip():
		return content
	if not isinstance(content, list):
		return None
	text_parts = []
	for part in content:
		if isinstance(part, str):
			text_parts.append(part)
			continue
		if isinstance(part, dict):
			part_type = part.get('type')
			if part_type in part_types or (part_type is None and 'text' in part):
				text = part.get('text')
				if isinstance(text, str):
					text_parts.append(text)
	text = ''.join(text_parts)
	return text if text.strip() else None


def _response_output_item_text(payload: dict[str, Any]) -> str | None:
	item = payload.get('item')
	if not isinstance(item, dict):
		return None
	if item.get('type') != 'message':
		return None
	if item.get('role', 'user') != 'assistant':
		return None
	return _response_content_text(item.get('content'), ('output_text', 'text', 'input_text'))


def _response_output_item_reasoning_text(payload: dict[str, Any]) -> str | None:
	item = payload.get('item')
	if not isinstance(item, dict):
		return None
	for key in ('reasoning_content', 'thinking', 'reasoning'):
		text = item.get(key)
		if isinstance(text, str) and text.strip():
			return text
	if item.get('type') != 'reasoning':
		return None
	for key in ('text', 'content', 'summary'):
		text = _response_content_text(item.get(key), ('summary_text', 'text', 'output_text', 'input_text'))
		if text:
			return text
	return None


def _streaming_text_from_events(
	events: list[dict[str, Any]],
	stream_event_types: tuple[str, ...],
	*,
	response_item_extractor: Callable[[dict[str, Any]], str | None] = _response_output_item_text,
) -> str | None:
	text = ''
	for event in events:
		event_type = _event_type(event)
		if event_type in ('model.turn.request', 'model.turn.retry', 'model.turn.error'):
			text = ''
			continue
		payload = _event_payload(event)
		if event_type == 'model.response.output_item' and event_type in stream_event_types:
			incoming = response_item_extractor(payload)
		elif event_type in stream_event_types:
			incoming = payload.get('text') or payload.get('delta')
		else:
			continue
		if isinstance(incoming, str):
			text = _append_streaming_text_delta(text, incoming)
	return text if text.strip() else None


def _model_output_from_tool_calls(tool_calls: list[dict[str, Any]], events: list[dict[str, Any]]) -> AgentOutput | None:
	if not tool_calls:
		return None
	action_names = list(dict.fromkeys(call['name'] for call in tool_calls if isinstance(call.get('name'), str)))
	if not action_names:
		return None
	action_fields = {name: (dict[str, Any] | None, None) for name in action_names}
	recovered_action_model = create_model('RustTerminalActionModel', __base__=ActionModel, **action_fields)
	recovered_output_model = AgentOutput.type_with_custom_actions(recovered_action_model)
	actions = []
	for tool_call in tool_calls:
		try:
			actions.append(recovered_action_model(**{tool_call['name']: tool_call['arguments']}))
		except (TypeError, ValueError, ValidationError):
			continue
	if not actions:
		return None
	streamed_text = _streaming_text_from_events(events, ('model.delta', 'model.stream_delta', 'model.response.output_item'))
	thinking_text = _streaming_text_from_events(
		events,
		('model.thinking_delta', 'model.response.output_item'),
		response_item_extractor=_response_output_item_reasoning_text,
	)
	return recovered_output_model(
		thinking=thinking_text,
		evaluation_previous_goal='',
		memory=streamed_text or '',
		next_goal='',
		action=actions,
	)


def _action_results_from_tool_calls(
	tool_calls: list[dict[str, Any]],
	events: list[dict[str, Any]],
	*,
	final_result: str | None,
	attachments: list[str] | None,
	failure: str | None,
	is_done: bool,
	append_terminal_result: bool = True,
) -> list[ActionResult]:
	tool_results = _tool_results_by_call_id(events)
	unkeyed_results = _unkeyed_tool_results(events)
	image_attachments_by_call_id = _tool_image_attachments_by_call_id(events)
	unkeyed_image_attachments = _tool_image_attachments_by_name(events)
	used_unkeyed_result_indices: set[int] = set()
	used_unkeyed_image_attachment_indices: set[int] = set()
	action_results: list[ActionResult] = []
	for tool_call in tool_calls:
		tool_call_id = str(tool_call.get('tool_call_id'))
		event_type, payload = tool_results.get(tool_call_id, ('', {}))
		if not event_type:
			unkeyed_result_index = _matching_unkeyed_tool_result_index(
				unkeyed_results,
				used_unkeyed_result_indices,
				tool_call.get('name'),
				allow_any=not tool_call.get('_has_explicit_tool_call_id', True),
			)
			if unkeyed_result_index is not None:
				used_unkeyed_result_indices.add(unkeyed_result_index)
				event_type, payload = unkeyed_results[unkeyed_result_index]
		tool_attachments = image_attachments_by_call_id.get(tool_call_id)
		if not tool_attachments:
			unkeyed_attachment_index = _matching_unkeyed_tool_attachment_index(
				unkeyed_image_attachments,
				used_unkeyed_image_attachment_indices,
				tool_call.get('name'),
				allow_any=not tool_call.get('_has_explicit_tool_call_id', True),
			)
			if unkeyed_attachment_index is not None:
				used_unkeyed_image_attachment_indices.add(unkeyed_attachment_index)
				tool_attachments = unkeyed_image_attachments[unkeyed_attachment_index][1]
		text = _tool_result_text(payload)
		if event_type == 'tool.finished' and not text:
			name = payload.get('name') or tool_call.get('name') or 'tool'
			text = _synthetic_tool_result_text(str(name))
		if event_type == 'tool.failed':
			error = _tool_failure_message(payload)
		elif event_type == 'browser_script.failed':
			error = _tool_failure_message(payload) or 'browser_script failed'
		elif event_type == 'tool.aborted':
			error = _tool_abort_message(payload)
		elif event_type == 'exec_command.end':
			error = _exec_command_end_failure_message(payload)
		else:
			error = None
		long_term_memory = None
		include_extracted_content_only_once = False
		if event_type in _TEXTUAL_TOOL_RESULT_EVENTS and text:
			name = str(payload.get('name') or tool_call.get('name') or 'tool')
			long_term_memory, include_extracted_content_only_once = _terminal_tool_memory(name, text)
		action_results.append(
			ActionResult(
				error=error,
				attachments=list(tool_attachments) if tool_attachments else None,
				extracted_content=text if event_type in _TEXTUAL_TOOL_RESULT_EVENTS else None,
				long_term_memory=long_term_memory,
				include_extracted_content_only_once=include_extracted_content_only_once,
			)
		)

	if not append_terminal_result:
		return action_results

	final_action = ActionResult(
		is_done=is_done,
		success=True if is_done else None,
		error=failure,
		attachments=attachments,
		extracted_content=final_result,
		long_term_memory=final_result,
	)
	if action_results and tool_calls[-1].get('name') == 'done':
		action_results[-1] = final_action
	else:
		action_results.append(final_action)
	return action_results


def _terminal_turn_spans(events: list[dict[str, Any]]) -> list[tuple[int, int]]:
	starts = [index for index, event in enumerate(events) if _event_type(event) == 'model.turn.request']
	if len(starts) <= 1:
		return []
	return [(start, starts[index + 1] if index + 1 < len(starts) else len(events)) for index, start in enumerate(starts)]


def _event_time_seconds(event: dict[str, Any], fallback: float) -> float:
	ts_ms = event.get('ts_ms')
	if isinstance(ts_ms, (int, float)):
		return float(ts_ms) / 1000.0
	ts = event.get('timestamp') or event.get('time')
	if isinstance(ts, (int, float)):
		return float(ts)
	return fallback


def _history_items_from_terminal_turns(
	events: list[dict[str, Any]],
	*,
	started: float,
	finished: float,
	final_result: str | None,
	attachments: list[str] | None,
	failure: str | None,
	is_done: bool,
) -> list[AgentHistory] | None:
	spans = _terminal_turn_spans(events)
	if not spans:
		return None
	history: list[AgentHistory] = []
	for step_number, (start_index, end_index) in enumerate(spans, start=1):
		step_events = events[start_index:end_index]
		if not step_events:
			continue
		is_final_step = step_number == len(spans)
		step_final_result = final_result if is_final_step else None
		step_failure = failure if is_final_step else None
		step_is_done = is_done if is_final_step else False
		step_attachments = attachments if is_final_step else None
		tool_calls = _tool_calls_with_final_done(
			_tool_started_calls(step_events),
			final_result=step_final_result,
			attachments=step_attachments,
			is_done=step_is_done,
		)
		if not tool_calls and step_final_result is None and step_failure is None:
			continue
		state_events = events[:end_index]
		step_start = _event_time_seconds(step_events[0], started)
		step_end = _event_time_seconds(step_events[-1], finished if is_final_step else step_start)
		history.append(
			AgentHistory(
				model_output=_model_output_from_tool_calls(tool_calls, step_events),
				result=_action_results_from_tool_calls(
					tool_calls,
					step_events,
					final_result=step_final_result,
					attachments=step_attachments,
					failure=step_failure,
					is_done=step_is_done,
					append_terminal_result=is_final_step,
				),
				state=_browser_state_from_events(state_events),
				metadata=StepMetadata(step_start_time=step_start, step_end_time=step_end, step_number=step_number),
			)
		)
	return history or None


def _browser_url(value: Any) -> str:
	if not isinstance(value, str):
		return ''
	value = value.strip()
	if value.startswith(('http://', 'https://', 'about:', 'file://')):
		return value
	return ''


def _internal_browser_endpoint_url(url: str) -> bool:
	parsed = urlparse(url)
	return (
		parsed.scheme in {'http', 'https'}
		and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
		and parsed.path
		in {
			'',
			'/',
		}
	)


def _browser_state_candidates(value: Any) -> list[tuple[str, str, str]]:
	candidates: list[tuple[str, str, str]] = []
	if isinstance(value, dict):
		url = _browser_url(value.get('url'))
		if url:
			title = str(value.get('title') or '')
			raw_target = value.get('target')
			nested_target_id = ''
			if isinstance(raw_target, dict):
				nested_target_id = str(
					raw_target.get('target_id')
					or raw_target.get('targetId')
					or raw_target.get('tab_id')
					or raw_target.get('tabId')
					or ''
				)
			target_id = str(
				value.get('target_id')
				or value.get('targetId')
				or value.get('tab_id')
				or value.get('tabId')
				or nested_target_id
				or 'tab-0'
			)
			candidates.append((url, title, target_id))
		for key, child in value.items():
			if key in ('url', 'live_url', 'title'):
				continue
			candidates.extend(_browser_state_candidates(child))
	elif isinstance(value, list):
		for child in value:
			candidates.extend(_browser_state_candidates(child))
	elif isinstance(value, str):
		text = value.strip()
		url = _browser_url(text)
		if url:
			candidates.append((url, '', 'tab-0'))
		if len(text) > 50_000:
			return candidates
		segments = [text]
		if '\n' in text:
			segments.extend(line.strip() for line in text.splitlines() if line.strip().startswith(('{', '[')))
		seen_segments: set[str] = set()
		for segment in segments:
			if segment in seen_segments or not segment.startswith(('{', '[')):
				continue
			seen_segments.add(segment)
			parsed = None
			for parser in (json.loads, ast.literal_eval):
				try:
					parsed = parser(segment)
					break
				except (SyntaxError, ValueError, TypeError, json.JSONDecodeError):
					continue
			if isinstance(parsed, (dict, list)):
				candidates.extend(_browser_state_candidates(parsed))
	return candidates


def _image_path(value: Any) -> str | None:
	if not isinstance(value, dict):
		return None
	path = value.get('path')
	if isinstance(path, str) and path:
		return path
	url = value.get('url')
	if isinstance(url, str) and url.startswith('file://'):
		return url.removeprefix('file://')
	return None


def _append_unique_attachment(attachments: list[str], pointer: str | None) -> None:
	if pointer and pointer not in attachments:
		attachments.append(pointer)


def _tool_image_attachments_by_call_id(events: list[dict[str, Any]]) -> dict[str, list[str]]:
	attachments: dict[str, list[str]] = {}
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'tool.image':
			image_path = _image_path(payload.get('image'))
			call_id = payload.get('tool_call_id') or payload.get('call_id')
			if image_path and call_id:
				_append_unique_attachment(attachments.setdefault(str(call_id), []), image_path)
			continue
		if event_type not in ('tool.output', 'tool.failed'):
			continue
		call_id = payload.get('tool_call_id') or payload.get('call_id')
		if not call_id:
			continue
		images = payload.get('images')
		if not isinstance(images, list):
			continue
		for image in images:
			image_path = _image_path(image)
			if image_path:
				_append_unique_attachment(attachments.setdefault(str(call_id), []), image_path)
	return attachments


def _tool_image_attachments_by_name(events: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
	attachments: list[tuple[str, list[str]]] = []
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if payload.get('tool_call_id') or payload.get('call_id'):
			continue
		name = payload.get('name')
		if not isinstance(name, str) or not name:
			continue
		image_paths: list[str] = []
		if event_type == 'tool.image':
			_append_unique_attachment(image_paths, _image_path(payload.get('image')))
		elif event_type in ('tool.output', 'tool.failed', *_BROWSER_SCRIPT_RESULT_EVENTS):
			images = payload.get('images')
			if isinstance(images, list):
				for image in images:
					_append_unique_attachment(image_paths, _image_path(image))
		if image_paths:
			attachments.append((name, image_paths))
	return attachments


def _screenshot_path_from_events(events: list[dict[str, Any]]) -> str | None:
	screenshot_path = None
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'tool.image':
			image_path = _image_path(payload.get('image'))
			if image_path:
				screenshot_path = image_path
			continue
		if event_type not in ('tool.output', 'tool.failed', *_BROWSER_SCRIPT_RESULT_EVENTS):
			continue
		images = payload.get('images')
		if not isinstance(images, list):
			continue
		for image in images:
			image_path = _image_path(image)
			if image_path:
				screenshot_path = image_path
	return screenshot_path


def _browser_script_navigation_candidates(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
	if payload.get('name') != 'browser_script':
		return []
	arguments = payload.get('arguments')
	if not isinstance(arguments, dict):
		return []
	code = arguments.get('code')
	if not isinstance(code, str) or not re.search(r'\b(?:goto_url|new_tab|open_tab|navigate)\s*\(', code):
		return []
	candidates = []
	for match in URL_PATTERN.finditer(code):
		url = _browser_url(match.group(0))
		if url:
			candidates.append((url, '', 'tab-0'))
	return candidates


def _browser_state_from_events(events: list[dict[str, Any]]) -> BrowserStateHistory:
	url = ''
	title = ''
	tabs: list[TabInfo] = []
	for event in events:
		event_type = _event_type(event)
		if event_type in ('tool.output', 'tool.started', *_BROWSER_SCRIPT_RESULT_EVENTS):
			payload = _event_payload(event)
			if event_type == 'tool.started':
				candidates = _browser_script_navigation_candidates(payload)
			else:
				candidates = _browser_state_candidates(payload)
			for candidate_url, candidate_title, candidate_target_id in candidates:
				if payload.get('name') == 'browser' and _internal_browser_endpoint_url(candidate_url):
					continue
				url = candidate_url
				title = candidate_title or title
				tabs = [TabInfo(url=url, title=title, target_id=candidate_target_id)]
			continue
		if event_type not in (
			'browser.connected',
			'browser.reconnected',
			'browser.target_changed',
			'browser.live_url',
			'browser.page',
			'browser.state',
		):
			continue
		payload = _event_payload(event)
		next_url = _browser_url(payload.get('live_url')) or _browser_url(payload.get('url'))
		if event_type in {'browser.connected', 'browser.reconnected'} and _internal_browser_endpoint_url(next_url):
			next_url = ''
		url = next_url or url
		title = str(payload.get('title') or title)
		raw_tabs = payload.get('tabs')
		if isinstance(raw_tabs, list):
			next_tabs = []
			for idx, raw in enumerate(raw_tabs):
				if isinstance(raw, dict):
					next_tabs.append(
						TabInfo(
							url=str(raw.get('url') or ''),
							title=str(raw.get('title') or ''),
							target_id=str(raw.get('target_id') or raw.get('tab_id') or f'tab-{idx}'),
						)
					)
			if next_tabs:
				tabs = next_tabs
	if not tabs and (url or title):
		tabs = [TabInfo(url=url, title=title, target_id='tab-0')]
	return BrowserStateHistory(
		url=url,
		title=title,
		tabs=tabs,
		interacted_element=[],
		screenshot_path=_screenshot_path_from_events(events),
	)


def _int_value(value: Any) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _float_value(value: Any) -> float:
	try:
		return float(value or 0.0)
	except (TypeError, ValueError):
		return 0.0


def _int_field(usage: dict[str, Any], keys: tuple[str, ...]) -> int:
	for key in keys:
		if key in usage:
			return _int_value(usage.get(key))
	return 0


def _token_count_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
	info = payload.get('info')
	if isinstance(info, dict):
		raw_usage = info.get('total_token_usage') or info.get('last_token_usage')
	else:
		raw_usage = payload.get('total_token_usage') or payload.get('last_token_usage')
	return raw_usage if isinstance(raw_usage, dict) else None


def _token_count_last_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
	info = payload.get('info')
	if isinstance(info, dict):
		raw_usage = info.get('last_token_usage') or info.get('total_token_usage')
	else:
		raw_usage = payload.get('last_token_usage') or payload.get('total_token_usage')
	return raw_usage if isinstance(raw_usage, dict) else None


def _model_usage_payload(payload: dict[str, Any]) -> dict[str, Any]:
	usage = payload.get('usage')
	return usage if isinstance(usage, dict) else payload


def _optional_positive_int(value: Any) -> int | None:
	integer = _int_value(value)
	return integer if integer > 0 else None


def _cache_creation_usage_tokens(usage: dict[str, Any]) -> tuple[int, int, int]:
	cache_creation = usage.get('cache_creation')
	if isinstance(cache_creation, dict):
		cache_creation_5m_tokens = _int_value(cache_creation.get('ephemeral_5m_input_tokens'))
		cache_creation_1h_tokens = _int_value(cache_creation.get('ephemeral_1h_input_tokens'))
		return cache_creation_5m_tokens + cache_creation_1h_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens

	cache_creation_tokens = _int_field(
		usage, ('cache_creation_input_tokens', 'prompt_cache_creation_tokens', 'input_cache_creation_tokens')
	)
	return cache_creation_tokens, 0, 0


def _input_usage_buckets(usage: dict[str, Any]) -> tuple[int, int, int, int, int]:
	cache_read_tokens = _int_field(usage, ('cache_read_input_tokens', 'input_cached_tokens', 'cached_input_tokens'))
	cache_creation_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens = _cache_creation_usage_tokens(usage)
	input_tokens = _int_value(usage.get('input_tokens'))
	if 'cache_read_input_tokens' in usage or 'cache_creation_input_tokens' in usage:
		input_tokens += cache_read_tokens
	return input_tokens, cache_read_tokens, cache_creation_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens


def _chat_invoke_usage_from_payload(usage: dict[str, Any]) -> ChatInvokeUsage | None:
	input_tokens, cached_input_tokens, cache_creation_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens = (
		_input_usage_buckets(usage)
	)
	completion_tokens = _usage_completion_tokens(usage)
	total_tokens = _usage_total_tokens(usage, input_tokens, cache_creation_tokens, completion_tokens)
	if input_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
		return None
	pricing_multiplier = _float_value(usage.get('pricing_multiplier'))
	if not pricing_multiplier and usage.get('inference_geo') == 'us':
		pricing_multiplier = 1.1
	return ChatInvokeUsage(
		prompt_tokens=input_tokens,
		prompt_cached_tokens=cached_input_tokens or None,
		prompt_cache_creation_tokens=cache_creation_tokens or None,
		prompt_cache_creation_5m_tokens=cache_creation_5m_tokens or None,
		prompt_cache_creation_1h_tokens=cache_creation_1h_tokens or None,
		prompt_image_tokens=_optional_positive_int(usage.get('prompt_image_tokens') or usage.get('image_tokens')),
		completion_tokens=completion_tokens,
		total_tokens=total_tokens,
		pricing_multiplier=pricing_multiplier or None,
	)


def _reasoning_output_tokens(usage: dict[str, Any]) -> int:
	return _int_value(
		usage.get('reasoning_output_tokens') or usage.get('output_reasoning_tokens') or usage.get('reasoning_tokens')
	)


def _usage_completion_tokens(usage: dict[str, Any]) -> int:
	return _int_value(usage.get('output_tokens')) + _reasoning_output_tokens(usage)


def _usage_total_tokens(usage: dict[str, Any], input_tokens: int, cache_creation_tokens: int, completion_tokens: int) -> int:
	computed_total = input_tokens + cache_creation_tokens + completion_tokens
	if 'cache_read_input_tokens' in usage or 'cache_creation_input_tokens' in usage:
		return computed_total
	reported_total = usage.get('total_tokens')
	if reported_total is not None:
		total_tokens = _int_value(reported_total)
		if total_tokens > 0 or computed_total == 0:
			return total_tokens
	return computed_total


def _usage_from_events(events: list[dict[str, Any]], model: str) -> UsageSummary:
	input_tokens = 0
	cached_input_tokens = 0
	cache_creation_tokens = 0
	completion_tokens = 0
	total_tokens = 0
	cost = 0.0
	invocations = 0
	token_count_invocations = 0
	token_count_input_tokens = 0
	token_count_cached_input_tokens = 0
	token_count_cache_creation_tokens = 0
	token_count_completion_tokens = 0
	token_count_total_tokens = 0

	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'model.usage':
			usage = _model_usage_payload(payload)
			event_input_tokens, event_cached_input_tokens, event_cache_creation_tokens, _, _ = _input_usage_buckets(usage)
			event_completion_tokens = _usage_completion_tokens(usage)
			input_tokens += event_input_tokens
			cached_input_tokens += event_cached_input_tokens
			cache_creation_tokens += event_cache_creation_tokens
			completion_tokens += event_completion_tokens
			total_tokens += _usage_total_tokens(usage, event_input_tokens, event_cache_creation_tokens, event_completion_tokens)
			cost += _float_value(usage.get('cost_usd') or usage.get('cost') or payload.get('cost_usd') or payload.get('cost'))
			invocations += 1
			continue
		if event_type == 'token_count':
			token_usage = _token_count_usage(payload)
			if token_usage is None:
				continue
			total_input_tokens, total_cached_input_tokens, total_cache_creation_tokens, _, _ = _input_usage_buckets(token_usage)
			total_completion_tokens = _usage_completion_tokens(token_usage)
			total_usage_tokens = _usage_total_tokens(
				token_usage, total_input_tokens, total_cache_creation_tokens, total_completion_tokens
			)
			last_usage = _token_count_last_usage(payload)
			if isinstance(last_usage, dict):
				last_input_tokens, last_cached_input_tokens, last_cache_creation_tokens, _, _ = _input_usage_buckets(last_usage)
				last_completion_tokens = _usage_completion_tokens(last_usage)
				token_count_input_tokens += last_input_tokens
				token_count_cached_input_tokens += last_cached_input_tokens
				token_count_cache_creation_tokens += last_cache_creation_tokens
				token_count_completion_tokens += last_completion_tokens
				token_count_total_tokens += _usage_total_tokens(
					last_usage, last_input_tokens, last_cache_creation_tokens, last_completion_tokens
				)
			elif total_cache_creation_tokens:
				token_count_cache_creation_tokens = total_cache_creation_tokens
			input_tokens = max(input_tokens, total_input_tokens, token_count_input_tokens)
			cached_input_tokens = max(cached_input_tokens, total_cached_input_tokens, token_count_cached_input_tokens)
			cache_creation_tokens = max(cache_creation_tokens, total_cache_creation_tokens, token_count_cache_creation_tokens)
			completion_tokens = max(completion_tokens, total_completion_tokens, token_count_completion_tokens)
			total_tokens = max(total_tokens, total_usage_tokens, token_count_total_tokens)
			token_count_invocations += 1

	invocations = max(invocations, token_count_invocations)
	by_model = {
		model: ModelUsageStats(
			model=model,
			prompt_tokens=input_tokens,
			completion_tokens=completion_tokens,
			total_tokens=total_tokens,
			cost=cost,
			invocations=invocations,
		)
	}
	return UsageSummary(
		total_prompt_tokens=input_tokens,
		total_prompt_cost=0.0,
		total_prompt_cached_tokens=cached_input_tokens,
		total_prompt_cached_cost=0.0,
		total_prompt_cache_creation_tokens=cache_creation_tokens,
		total_prompt_cache_creation_cost=0.0,
		total_completion_tokens=completion_tokens,
		total_completion_cost=0.0,
		total_tokens=total_tokens,
		total_cost=cost,
		entry_count=invocations,
		by_model=by_model,
	)


def _usage_tokens(summary: UsageSummary | None) -> int:
	if summary is None:
		return 0
	return max(
		_int_value(summary.total_tokens),
		_int_value(summary.total_prompt_tokens)
		+ _int_value(summary.total_prompt_cache_creation_tokens)
		+ _int_value(summary.total_completion_tokens),
	)


def _usage_event_from_sdk_history_usage(raw_usage: Any) -> dict[str, Any] | None:
	if not isinstance(raw_usage, dict):
		return None
	if _chat_invoke_usage_from_payload(raw_usage) is None:
		return None
	return {
		'event_type': 'token_count',
		'payload': {
			'info': {
				'last_token_usage': raw_usage,
				'total_token_usage': raw_usage,
			}
		},
	}


async def _usage_from_events_with_costs(
	events: list[dict[str, Any]],
	model: str,
	token_cost_service: TokenCost,
) -> UsageSummary:
	"""Reconstruct usage from terminal events and price per-call usage when enabled."""
	summary = _usage_from_events(events, model)
	if not token_cost_service.include_cost:
		return summary

	total_prompt_cost = 0.0
	total_completion_cost = 0.0
	total_prompt_cached_cost = 0.0
	total_prompt_cache_creation_cost = 0.0
	total_cost = 0.0
	priced_invocations = 0
	summed_prompt_tokens = 0
	summed_prompt_cached_tokens = 0
	summed_prompt_cache_creation_tokens = 0
	summed_completion_tokens = 0
	summed_total_tokens = 0
	summed_invocations = 0
	has_model_usage = any(_event_type(event) == 'model.usage' for event in events)

	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		raw_usage = None
		if event_type == 'model.usage':
			raw_usage = _model_usage_payload(payload)
		elif event_type == 'token_count':
			if has_model_usage:
				continue
			raw_usage = _token_count_last_usage(payload)
		if not isinstance(raw_usage, dict):
			continue
		chat_usage = _chat_invoke_usage_from_payload(raw_usage)
		if chat_usage is None:
			continue
		summed_invocations += 1
		summed_prompt_tokens += chat_usage.prompt_tokens
		summed_prompt_cached_tokens += chat_usage.prompt_cached_tokens or 0
		summed_prompt_cache_creation_tokens += chat_usage.prompt_cache_creation_tokens or 0
		summed_completion_tokens += chat_usage.completion_tokens
		summed_total_tokens += chat_usage.total_tokens
		cost = await token_cost_service.calculate_cost(model, chat_usage)
		if cost is None:
			continue
		priced_invocations += 1
		total_prompt_cost += cost.prompt_cost
		total_completion_cost += cost.completion_cost
		total_prompt_cached_cost += cost.prompt_read_cached_cost or 0.0
		total_prompt_cache_creation_cost += cost.prompt_cache_creation_cost or 0.0
		total_cost += cost.total_cost

	if priced_invocations == 0 and summed_invocations == 0:
		return summary

	model_stats = dict(summary.by_model)
	stats = model_stats.get(model) or ModelUsageStats(model=model)
	if summed_invocations:
		stats.prompt_tokens = summed_prompt_tokens
		stats.completion_tokens = summed_completion_tokens
		stats.total_tokens = summed_total_tokens
		stats.invocations = max(stats.invocations, summed_invocations)
	if priced_invocations:
		stats.cost = total_cost
	model_stats[model] = stats

	update: dict[str, Any] = {'by_model': model_stats}
	if summed_invocations:
		update.update(
			{
				'total_prompt_tokens': summed_prompt_tokens,
				'total_prompt_cached_tokens': summed_prompt_cached_tokens,
				'total_prompt_cache_creation_tokens': summed_prompt_cache_creation_tokens,
				'total_completion_tokens': summed_completion_tokens,
				'total_tokens': summed_total_tokens,
				'entry_count': max(summary.entry_count, summed_invocations),
			}
		)
	if priced_invocations:
		update.update(
			{
				'total_prompt_cost': total_prompt_cost,
				'total_prompt_cached_cost': total_prompt_cached_cost,
				'total_prompt_cache_creation_cost': total_prompt_cache_creation_cost,
				'total_completion_cost': total_completion_cost,
				'total_cost': total_cost,
			}
		)
	return summary.model_copy(update=update)


def _terminal_model_turn_event_ranges(events: list[dict[str, Any]]) -> list[tuple[int, int]]:
	starts = [index for index, event in enumerate(events) if _event_type(event) == 'model.turn.request']
	return [(start, starts[index + 1] if index + 1 < len(starts) else len(events)) for index, start in enumerate(starts)]


def _terminal_turn_usage_payload(events: list[dict[str, Any]]) -> dict[str, Any] | None:
	raw_usage = None
	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'model.usage':
			raw_usage = _model_usage_payload(payload)
		elif event_type == 'token_count':
			raw_usage = _token_count_last_usage(payload)
	return raw_usage if isinstance(raw_usage, dict) else None


def _terminal_laminar_usage_summary(raw_usage: dict[str, Any] | None) -> dict[str, Any] | None:
	if raw_usage is None:
		return None
	input_tokens, cached_input_tokens, cache_creation_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens = (
		_input_usage_buckets(raw_usage)
	)
	output_tokens = _usage_completion_tokens(raw_usage)
	total_tokens = _usage_total_tokens(raw_usage, input_tokens, cache_creation_tokens, output_tokens)
	cost = _float_value(raw_usage.get('cost_usd') or raw_usage.get('cost') or raw_usage.get('total_cost'))
	summary: dict[str, Any] = {
		'input_tokens': input_tokens,
		'cached_input_tokens': cached_input_tokens,
		'output_tokens': output_tokens,
		'total_tokens': total_tokens,
	}
	if cache_creation_tokens:
		summary['cache_creation_input_tokens'] = cache_creation_tokens
	if cache_creation_5m_tokens or cache_creation_1h_tokens:
		summary['cache_creation'] = {
			'ephemeral_5m_input_tokens': cache_creation_5m_tokens,
			'ephemeral_1h_input_tokens': cache_creation_1h_tokens,
		}
	reasoning_output_tokens = _reasoning_output_tokens(raw_usage)
	if reasoning_output_tokens:
		summary['reasoning_output_tokens'] = reasoning_output_tokens
	if cost:
		summary['cost_usd'] = cost
	if raw_usage.get('inference_geo') is not None:
		summary['inference_geo'] = raw_usage['inference_geo']
	if raw_usage.get('pricing_multiplier') is not None:
		summary['pricing_multiplier'] = raw_usage['pricing_multiplier']
	return summary


def _terminal_laminar_usage_cost(model: str, usage: dict[str, Any] | None) -> dict[str, float] | None:
	if not usage:
		return None
	pricing = CUSTOM_MODEL_PRICING.get(model) or CUSTOM_MODEL_PRICING.get(model.replace('.', '-'))
	if not pricing:
		return None
	input_tokens = int(usage.get('input_tokens') or 0)
	cached_tokens = int(usage.get('cached_input_tokens') or 0)
	cache_creation_tokens, cache_creation_5m_tokens, cache_creation_1h_tokens = _cache_creation_usage_tokens(usage)
	output_tokens = int(usage.get('output_tokens') or 0)
	uncached_tokens = max(0, input_tokens - cached_tokens)
	input_cost = uncached_tokens * float(pricing.get('input_cost_per_token') or 0.0)
	cache_read_cost = cached_tokens * float(pricing.get('cache_read_input_token_cost') or 0.0)
	if cache_creation_5m_tokens or cache_creation_1h_tokens:
		cache_creation_cost = cache_creation_5m_tokens * float(pricing.get('cache_creation_input_token_cost') or 0.0)
		cache_creation_cost += cache_creation_1h_tokens * float(
			pricing.get('cache_creation_1h_input_token_cost') or pricing.get('cache_creation_input_token_cost') or 0.0
		)
	else:
		cache_creation_cost = cache_creation_tokens * float(pricing.get('cache_creation_input_token_cost') or 0.0)
	output_cost = output_tokens * float(pricing.get('output_cost_per_token') or 0.0)
	pricing_multiplier = _float_value(usage.get('pricing_multiplier'))
	if not pricing_multiplier and usage.get('inference_geo') == 'us':
		pricing_multiplier = 1.1
	if pricing_multiplier:
		input_cost *= pricing_multiplier
		cache_read_cost *= pricing_multiplier
		cache_creation_cost *= pricing_multiplier
		output_cost *= pricing_multiplier
	total_cost = input_cost + cache_read_cost + cache_creation_cost + output_cost
	if total_cost <= 0:
		return None
	return {
		'input_cost_usd': input_cost,
		'input_cached_cost_usd': cache_read_cost,
		'input_cache_creation_cost_usd': cache_creation_cost,
		'output_cost_usd': output_cost,
		'cost_usd': total_cost,
	}


def _terminal_laminar_turn_input(
	request_payload: dict[str, Any],
	*,
	default_model: str,
	default_provider: str,
) -> dict[str, Any]:
	composition = request_payload.get('composition')
	if not isinstance(composition, dict):
		composition = {}
	raw_tools = composition.get('tools')
	tools = raw_tools if isinstance(raw_tools, list) else []
	llm_input = request_payload.get('llm_input')
	if not isinstance(llm_input, dict):
		llm_input = {}
	llm_tools = llm_input.get('tools')
	if isinstance(llm_tools, list):
		tools = [tool for tool in llm_tools if isinstance(tool, dict)]
	tool_names = []
	for tool in tools:
		if isinstance(tool, dict) and isinstance(tool.get('name'), str):
			tool_names.append(tool['name'])
	messages = llm_input.get('messages')
	if not isinstance(messages, list):
		messages = []
	system = llm_input.get('system')
	if not isinstance(system, list):
		system = []
	return {
		'model': request_payload.get('model') or default_model,
		'provider': request_payload.get('provider') or default_provider,
		'turn_idx': request_payload.get('turn_idx'),
		'attempt': request_payload.get('attempt'),
		'system_prompt_tokens': composition.get('system_prompt_tokens'),
		'tools_count': len(tools),
		'tool_names': tool_names,
		'tools': tools,
		'system': system,
		'messages': messages,
		'message_count': _int_value(llm_input.get('message_count')),
		'omitted_earlier_messages': _int_value(llm_input.get('omitted_earlier_messages')),
		'truncated': bool(llm_input.get('truncated')),
	}


def _terminal_laminar_turn_output(events: list[dict[str, Any]], raw_usage: dict[str, Any] | None) -> dict[str, Any]:
	assistant_text = _streaming_text_from_events(events, ('model.delta', 'model.stream_delta', 'model.response.output_item'))
	thinking_text = _streaming_text_from_events(
		events,
		('model.thinking_delta', 'model.response.output_item'),
		response_item_extractor=_response_output_item_reasoning_text,
	)
	tool_calls = _tool_started_calls(events)
	assistant_preview = _laminar_preview(assistant_text, limit=2000)
	thinking_preview = _laminar_preview(thinking_text, limit=1200)
	output_messages = []
	if assistant_text:
		output_messages.append({'role': 'assistant', 'content': [{'type': 'text', 'text': assistant_text}]})
	if tool_calls:
		output_messages.append(
			{
				'role': 'assistant',
				'tool_calls': [
					{
						'name': call.get('name'),
						'id': call.get('tool_call_id'),
						'arguments': call.get('arguments'),
					}
					for call in tool_calls[:20]
				],
			}
		)
	return {
		'messages': output_messages,
		'assistant_output_preview': assistant_preview,
		'thinking_preview': thinking_preview,
		'tool_calls_count': len(tool_calls),
		'tool_call_names': [call['name'] for call in tool_calls[:20] if isinstance(call.get('name'), str)],
		'usage': _terminal_laminar_usage_summary(raw_usage),
	}


def _terminal_laminar_system_messages(span_input: dict[str, Any]) -> list[dict[str, Any]]:
	system_messages = []
	system_parts = span_input.get('system')
	if not isinstance(system_parts, list):
		return system_messages
	for part in system_parts:
		if isinstance(part, dict):
			text = part.get('text') or part.get('content')
		else:
			text = part
		if isinstance(text, str) and text:
			system_messages.append({'role': 'system', 'content': [{'type': 'text', 'text': text}]})
	return system_messages


def _terminal_laminar_content_part_for_span(part: Any) -> Any:
	if not isinstance(part, dict):
		return part
	part_type = part.get('type')
	if part_type == 'tool_result':
		content = part.get('content')
		if isinstance(content, list):
			return [_terminal_laminar_content_part_for_span(item) for item in content]
		if isinstance(content, str):
			return {'type': 'text', 'text': content}
	if part_type in {'input_text', 'output_text'}:
		text = part.get('text')
		if isinstance(text, str):
			return {'type': 'text', 'text': text}
	if part_type == 'media':
		mime_type = part.get('mime_type')
		mime_type = mime_type if isinstance(mime_type, str) and mime_type else 'application/octet-stream'
		url = part.get('url')
		data = part.get('data')
		resolved_url = None
		if isinstance(url, str) and url:
			resolved_url = url
		elif isinstance(data, str) and data:
			resolved_url = f'data:{mime_type};base64,{data}'
		if resolved_url and mime_type.startswith('image/'):
			image_url: dict[str, Any] = {'url': resolved_url}
			detail = part.get('detail')
			if isinstance(detail, str) and detail:
				image_url['detail'] = detail
			return {'type': 'image_url', 'image_url': image_url}
		if resolved_url:
			return {'type': 'file', 'file_data': resolved_url}
	if part_type in {'input_image', 'image'}:
		image_url = part.get('image_url')
		if isinstance(image_url, str) and image_url:
			resolved_image: dict[str, Any] = {'url': image_url}
			detail = part.get('detail')
			if isinstance(detail, str) and detail:
				resolved_image['detail'] = detail
			return {'type': 'image_url', 'image_url': resolved_image}
	content = part.get('content')
	if isinstance(content, list):
		normalized = dict(part)
		normalized['content'] = _terminal_laminar_content_parts_for_span(content)
		return normalized
	return part


def _terminal_laminar_content_parts_for_span(parts: list[Any]) -> list[Any]:
	normalized_parts: list[Any] = []
	for part in parts:
		normalized = _terminal_laminar_content_part_for_span(part)
		if isinstance(normalized, list):
			normalized_parts.extend(normalized)
		else:
			normalized_parts.append(normalized)
	return normalized_parts


def _terminal_laminar_message_for_span(message: Any) -> Any:
	if not isinstance(message, dict):
		return message
	content = message.get('content')
	if not isinstance(content, list):
		return message
	normalized = dict(message)
	normalized['content'] = _terminal_laminar_content_parts_for_span(content)
	return normalized


def _terminal_laminar_span_input_messages(span_input: dict[str, Any]) -> list[dict[str, Any]]:
	messages = span_input.get('messages')
	if not isinstance(messages, list):
		messages = []
	normalized_messages = [_terminal_laminar_message_for_span(message) for message in messages]
	return [*_terminal_laminar_system_messages(span_input), *normalized_messages]


def _terminal_laminar_tools_for_span(span_input: dict[str, Any]) -> list[dict[str, Any]]:
	tools = span_input.get('tools')
	if not isinstance(tools, list):
		return []
	return [tool for tool in tools if isinstance(tool, dict)]


def _terminal_laminar_span_input_payload(span_input: dict[str, Any]) -> Any:
	return _terminal_laminar_span_input_messages(span_input)


def _terminal_laminar_span_output_messages(span_output: dict[str, Any]) -> list[dict[str, Any]]:
	messages = span_output.get('messages')
	return messages if isinstance(messages, list) else []


def _terminal_laminar_message_text(message: dict[str, Any]) -> str:
	content = message.get('content')
	if isinstance(content, str):
		return content
	if not isinstance(content, list):
		return _laminar_preview(content, limit=4000) if content else ''
	parts = []
	for part in content:
		if isinstance(part, dict):
			text = part.get('text') or part.get('content')
			if isinstance(text, str):
				parts.append(text)
			elif part.get('type') in {'image', 'image_url', 'media', 'input_image'}:
				parts.append('[image]')
			elif part:
				parts.append(str(_laminar_preview(part, limit=1000)))
		elif isinstance(part, str):
			parts.append(part)
	return '\n'.join(parts)


def _terminal_laminar_semconv_content_part(part: Any, *, inline_image_data: bool = True) -> dict[str, Any]:
	if not isinstance(part, dict):
		return {'type': 'text', 'content': str(part)}
	part_type = part.get('type')
	if part_type in {'text', 'input_text', 'output_text'}:
		text = part.get('text') or part.get('content')
		if isinstance(text, str):
			return {'type': 'text', 'content': text}
	if part_type == 'image_url':
		image_url = part.get('image_url')
		url = image_url.get('url') if isinstance(image_url, dict) else None
		if isinstance(url, str) and url:
			if url.startswith('data:') and ';base64,' in url:
				header, blob = url.split(';base64,', 1)
				mime_type = header.removeprefix('data:') or 'application/octet-stream'
				if not inline_image_data:
					return {'type': 'blob', 'content': '[image in span input]', 'mimeType': mime_type}
				return {'type': 'blob', 'blob': blob, 'mimeType': mime_type}
			return {'type': 'uri', 'uri': url}
	if part_type in {'tool_use', 'tool_call'}:
		tool_call: dict[str, Any] = {'type': 'tool_call'}
		tool_id = part.get('id') or part.get('tool_call_id')
		name = part.get('name')
		arguments = part.get('arguments') if 'arguments' in part else part.get('input')
		if isinstance(tool_id, str):
			tool_call['id'] = tool_id
		if isinstance(name, str):
			tool_call['name'] = name
		if arguments is not None:
			tool_call['arguments'] = arguments
		return tool_call
	if part_type == 'tool_result':
		response: dict[str, Any] = {'type': 'tool_call_response'}
		tool_id = part.get('tool_use_id') or part.get('tool_call_id') or part.get('id')
		if isinstance(tool_id, str):
			response['id'] = tool_id
		if 'content' in part:
			response['response'] = part.get('content')
		return response
	content = part.get('content')
	if isinstance(content, str):
		return {'type': 'text', 'content': content}
	return {'type': 'text', 'content': _terminal_laminar_json_attribute(part)}


def _terminal_laminar_semconv_messages(
	messages: list[dict[str, Any]],
	*,
	inline_image_data: bool = True,
) -> list[dict[str, Any]]:
	semconv_messages: list[dict[str, Any]] = []
	for message in messages:
		if not isinstance(message, dict):
			continue
		role = message.get('role')
		if not isinstance(role, str):
			continue
		content = message.get('content')
		parts: list[dict[str, Any]]
		if isinstance(content, list):
			parts = [_terminal_laminar_semconv_content_part(part, inline_image_data=inline_image_data) for part in content]
		elif isinstance(content, str):
			parts = [{'type': 'text', 'content': content}]
		else:
			parts = []
		tool_calls = message.get('tool_calls')
		if isinstance(tool_calls, list):
			for tool_call in tool_calls:
				parts.append(_terminal_laminar_semconv_content_part({'type': 'tool_call', **tool_call}))
		semconv_messages.append({'role': role, 'parts': parts})
	return semconv_messages


def _terminal_laminar_system_instructions(span_input: dict[str, Any]) -> str:
	system_parts = span_input.get('system')
	if not isinstance(system_parts, list):
		return ''
	texts: list[str] = []
	for part in system_parts:
		if isinstance(part, dict):
			text = part.get('text') or part.get('content')
			if isinstance(text, str):
				texts.append(text)
			elif part:
				texts.append(_terminal_laminar_json_attribute(part))
		elif isinstance(part, str):
			texts.append(part)
	return '\n\n'.join(texts)


def _terminal_laminar_indexed_message_attributes(
	messages: list[dict[str, Any]], prefix: str, *, max_messages: int = 20
) -> dict[str, Any]:
	attributes: dict[str, Any] = {}
	for index, message in enumerate(messages[:max_messages]):
		if not isinstance(message, dict):
			continue
		role = message.get('role')
		if isinstance(role, str):
			attributes[f'{prefix}.{index}.role'] = role
		content = _terminal_laminar_message_text(message)
		if content:
			attributes[f'{prefix}.{index}.content'] = _laminar_preview(content, limit=12_000)
	if len(messages) > max_messages:
		attributes[f'{prefix}.truncated_count'] = len(messages) - max_messages
	return attributes


def _terminal_laminar_json_attribute(value: Any) -> str:
	return json.dumps(value, ensure_ascii=False, default=str)


def _terminal_laminar_tool_definition_attributes(tools: list[dict[str, Any]]) -> dict[str, Any]:
	if not tools:
		return {}
	attributes: dict[str, Any] = {
		'gen_ai.tool.definitions': _terminal_laminar_json_attribute(tools),
		'gen_ai.request.tools': _terminal_laminar_json_attribute(tools),
		'llm.request.functions': _terminal_laminar_json_attribute(tools),
	}
	for index, tool in enumerate(tools):
		name = tool.get('name')
		description = tool.get('description')
		input_schema = tool.get('input_schema') or tool.get('parameters')
		output_schema = tool.get('output_schema')
		namespace = tool.get('namespace')
		namespace_description = tool.get('namespace_description')
		prefix = f'llm.request.functions.{index}'
		if isinstance(name, str):
			attributes[f'{prefix}.name'] = name
			attributes[f'gen_ai.request.tools.{index}.name'] = name
		if isinstance(description, str):
			attributes[f'{prefix}.description'] = description
			attributes[f'gen_ai.request.tools.{index}.description'] = description
		if input_schema is not None:
			schema = _terminal_laminar_json_attribute(input_schema)
			attributes[f'{prefix}.input_schema'] = schema
			attributes[f'{prefix}.parameters'] = schema
			attributes[f'gen_ai.request.tools.{index}.input_schema'] = schema
		if output_schema is not None:
			attributes[f'{prefix}.output_schema'] = _terminal_laminar_json_attribute(output_schema)
		if isinstance(namespace, str):
			attributes[f'{prefix}.namespace'] = namespace
		if isinstance(namespace_description, str):
			attributes[f'{prefix}.namespace_description'] = namespace_description
	return attributes


def _terminal_laminar_gen_ai_attributes(
	span_input: dict[str, Any],
	span_output: dict[str, Any],
	usage: dict[str, int | float] | None,
) -> dict[str, Any]:
	input_messages = _terminal_laminar_span_input_messages(span_input)
	output_messages = _terminal_laminar_span_output_messages(span_output)
	attributes: dict[str, Any] = {
		'gen_ai.operation.name': 'chat',
		'gen_ai.request.model': str(span_input.get('model') or ''),
		'gen_ai.system': str(span_input.get('provider') or ''),
		'gen_ai.system_instructions': _terminal_laminar_system_instructions(span_input),
		# Keep the full image-bearing messages in the span input/output. Repeating
		# base64 blobs in attributes makes OTLP exports exceed Laminar limits.
		'gen_ai.input.messages': _terminal_laminar_json_attribute(
			_terminal_laminar_semconv_messages(input_messages, inline_image_data=False)
		),
		'gen_ai.output.messages': _terminal_laminar_json_attribute(
			_terminal_laminar_semconv_messages(output_messages, inline_image_data=False)
		),
	}
	attributes.update(_terminal_laminar_indexed_message_attributes(input_messages, 'gen_ai.prompt'))
	attributes.update(_terminal_laminar_indexed_message_attributes(output_messages, 'gen_ai.completion'))
	attributes.update(_terminal_laminar_tool_definition_attributes(_terminal_laminar_tools_for_span(span_input)))
	if usage:
		attributes.update(
			{
				'gen_ai.usage.input_tokens': usage.get('input_tokens'),
				'gen_ai.usage.input_cached_tokens': usage.get('cached_input_tokens'),
				'gen_ai.usage.cached_input_tokens': usage.get('cached_input_tokens'),
				'gen_ai.usage.cache_read_input_tokens': usage.get('cached_input_tokens'),
				'gen_ai.usage.cache_creation_input_tokens': usage.get('cache_creation_input_tokens') or 0,
				'gen_ai.usage.input_cache_creation_tokens': usage.get('cache_creation_input_tokens') or 0,
				'gen_ai.usage.output_tokens': usage.get('output_tokens'),
				'gen_ai.usage.total_tokens': usage.get('total_tokens'),
				'llm.usage.input_tokens': usage.get('input_tokens'),
				'llm.usage.output_tokens': usage.get('output_tokens'),
				'llm.usage.input_cached_tokens': usage.get('cached_input_tokens'),
				'llm.usage.cache_creation_input_tokens': usage.get('cache_creation_input_tokens') or 0,
				'llm.usage.total_tokens': usage.get('total_tokens'),
			}
		)
		if usage.get('cost_usd'):
			attributes['gen_ai.usage.cost'] = usage.get('cost_usd')
	return attributes


def _terminal_laminar_tool_result_payload(events: list[dict[str, Any]], tool_call_id: str) -> tuple[str, dict[str, Any]] | None:
	for event in events:
		event_type = _event_type(event)
		if event_type not in ('tool.output', 'tool.failed', 'tool.aborted', 'tool.finished', 'exec_command.end'):
			continue
		payload = _event_payload(event)
		call_id = payload.get('tool_call_id') or payload.get('call_id')
		if call_id is not None and str(call_id) == tool_call_id:
			return event_type, payload
	return None


def _terminal_laminar_image_part_from_path(path: str, mime_type: str | None = None) -> dict[str, Any] | None:
	image_path = Path(path)
	if not image_path.exists() or not image_path.is_file():
		return None
	resolved_mime_type = mime_type or mimetypes.guess_type(str(image_path))[0] or 'image/png'
	try:
		data = base64.b64encode(image_path.read_bytes()).decode('ascii')
	except OSError:
		return None
	return {'type': 'image_url', 'image_url': {'url': f'data:{resolved_mime_type};base64,{data}'}}


def _terminal_laminar_image_part_for_span(image: Any) -> dict[str, Any] | None:
	if isinstance(image, str):
		if image.startswith(('http://', 'https://', 'data:image/')):
			return {'type': 'image_url', 'image_url': {'url': image}}
		return _terminal_laminar_image_part_from_path(image)
	if not isinstance(image, dict):
		return None
	mime_type = image.get('mime_type') or image.get('mimeType') or image.get('media_type') or image.get('mediaType')
	mime_type = mime_type if isinstance(mime_type, str) and mime_type else None
	data = image.get('data') or image.get('base64')
	if isinstance(data, str) and data:
		resolved_mime_type = mime_type or 'image/png'
		return {'type': 'image_url', 'image_url': {'url': f'data:{resolved_mime_type};base64,{data}'}}
	url = image.get('url') or image.get('image_url')
	if isinstance(url, str) and url:
		if url.startswith('file://'):
			return _terminal_laminar_image_part_from_path(url.removeprefix('file://'), mime_type)
		return {'type': 'image_url', 'image_url': {'url': url}}
	path = image.get('path')
	if isinstance(path, str) and path:
		return _terminal_laminar_image_part_from_path(path, mime_type)
	return None


def _terminal_laminar_image_parts_for_span(payload: dict[str, Any]) -> list[dict[str, Any]]:
	images = payload.get('images')
	if not isinstance(images, list):
		return []
	parts: list[dict[str, Any]] = []
	for image in images:
		part = _terminal_laminar_image_part_for_span(image)
		if part is not None:
			parts.append(part)
	return parts


def _terminal_laminar_tool_input_message(tool_call: dict[str, Any]) -> list[dict[str, Any]]:
	return [
		{
			'role': 'assistant',
			'tool_calls': [
				{
					'id': tool_call.get('tool_call_id'),
					'name': tool_call.get('name'),
					'arguments': tool_call.get('arguments'),
				}
			],
		}
	]


def _terminal_laminar_tool_output_message(event_type: str | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
	image_parts = _terminal_laminar_image_parts_for_span(payload)
	content = payload.get('content')
	if isinstance(content, list) and content:
		parts = _terminal_laminar_content_parts_for_span(content)
	else:
		text = _tool_result_text(payload, include_completion_fallback=not bool(image_parts))
		if not text and event_type == 'tool.finished':
			text = _synthetic_tool_result_text(str(payload.get('name') or 'tool'))
		parts = []
		if text:
			parts.append({'type': 'text', 'text': text})
	parts.extend(image_parts)
	if not parts:
		parts = [{'type': 'text', 'text': ''}]
	role = 'tool'
	return [{'role': role, 'content': parts}]


def _record_laminar_terminal_tool_spans(events: list[dict[str, Any]], *, max_spans: int) -> None:
	if not _laminar_ready() or max_spans <= 0:
		return
	tool_calls = _tool_started_calls(events)
	for span_index, tool_call in enumerate(tool_calls[:max_spans], start=1):
		tool_call_id = str(tool_call.get('tool_call_id') or '')
		result = _terminal_laminar_tool_result_payload(events, tool_call_id)
		event_type, payload = result if result is not None else (None, {})
		input_messages = _terminal_laminar_tool_input_message(tool_call)
		output_messages = _terminal_laminar_tool_output_message(event_type, payload)
		with _laminar_start_span(f'rust_core.tool.{tool_call.get("name") or "tool"}', input=input_messages, span_type='TOOL'):
			_laminar_set_span_attributes(
				{
					'runtime': 'browser_use.beta',
					'tool_name': tool_call.get('name'),
					'tool_call_id': tool_call_id,
					'tool_index': span_index,
					'event_type': event_type,
					'ok': payload.get('ok') if payload else None,
					'status': payload.get('status') if payload else None,
					'error': payload.get('error') if payload else None,
					'has_content': bool(payload.get('content')) if payload else False,
					'has_images': bool(payload.get('images')) if payload else False,
					'has_outputs': bool(payload.get('outputs')) if payload else False,
					'has_summary': bool(payload.get('summary')) if payload else False,
				}
			)
			_laminar_set_span_output(output_messages)
		_laminar_force_flush()
	if len(tool_calls) > max_spans:
		_laminar_event('rust_core.tool_spans_truncated', {'recorded': max_spans, 'available': len(tool_calls)})


def _record_laminar_terminal_llm_spans(
	events: list[dict[str, Any]],
	*,
	default_model: str,
	default_provider: str,
) -> None:
	if not _laminar_ready():
		return
	max_spans = _int_value(os.getenv('BROWSER_USE_RUST_LAMINAR_MAX_LLM_SPANS') or 80)
	if max_spans <= 0:
		return
	ranges = _terminal_model_turn_event_ranges(events)
	for span_index, (start, end) in enumerate(ranges[:max_spans], start=1):
		turn_events = events[start:end]
		if not turn_events:
			continue
		request_payload = _event_payload(turn_events[0])
		span_input = _terminal_laminar_turn_input(
			request_payload,
			default_model=default_model,
			default_provider=default_provider,
		)
		raw_usage = _terminal_turn_usage_payload(turn_events)
		usage = _terminal_laminar_usage_summary(raw_usage)
		cost = _terminal_laminar_usage_cost(str(span_input.get('model') or default_model), usage)
		if cost and usage is not None:
			usage.update(cost)
		start_time = _event_time_seconds(turn_events[0], 0.0)
		end_time = _event_time_seconds(turn_events[-1], start_time)
		span_input_payload = _terminal_laminar_span_input_payload(span_input)
		with _laminar_start_span('rust_core.llm', input=span_input_payload, span_type='LLM'):
			span_output = _terminal_laminar_turn_output(turn_events, raw_usage)
			span_output_messages = _terminal_laminar_span_output_messages(span_output)
			_laminar_set_span_attributes(
				{
					'runtime': 'browser_use.beta',
					'model': str(span_input.get('model') or default_model),
					'provider': str(span_input.get('provider') or default_provider),
					'turn_index': span_index,
					'turn_idx': _int_value(span_input.get('turn_idx')),
					'attempt': _int_value(span_input.get('attempt')),
					'system_prompt_tokens': _int_value(span_input.get('system_prompt_tokens')),
					'tools_count': _int_value(span_input.get('tools_count')),
					'tool_names': _laminar_preview(span_input.get('tool_names') or [], limit=2000),
					'message_count': _int_value(span_input.get('message_count')),
					'omitted_earlier_messages': _int_value(span_input.get('omitted_earlier_messages')),
					'truncated': bool(span_input.get('truncated')),
					'assistant_output_preview': span_output.get('assistant_output_preview') or '',
					'thinking_preview': span_output.get('thinking_preview') or '',
					'tool_calls_count': _int_value(span_output.get('tool_calls_count')),
					'tool_call_names': _laminar_preview(span_output.get('tool_call_names') or [], limit=2000),
					'input_tokens': usage.get('input_tokens') if usage else None,
					'cached_input_tokens': usage.get('cached_input_tokens') if usage else None,
					'cache_creation_input_tokens': usage.get('cache_creation_input_tokens') if usage else None,
					'output_tokens': usage.get('output_tokens') if usage else None,
					'total_tokens': usage.get('total_tokens') if usage else None,
					'input_cost_usd': usage.get('input_cost_usd') if usage else None,
					'input_cached_cost_usd': usage.get('input_cached_cost_usd') if usage else None,
					'input_cache_creation_cost_usd': usage.get('input_cache_creation_cost_usd') if usage else None,
					'output_cost_usd': usage.get('output_cost_usd') if usage else None,
					'cost_usd': usage.get('cost_usd') if usage else None,
					'duration_seconds': max(0.0, end_time - start_time),
				}
			)
			_laminar_set_span_attributes(_terminal_laminar_gen_ai_attributes(span_input, span_output, usage))
			_laminar_set_span_output(span_output_messages)
		_laminar_force_flush()
	if len(ranges) > max_spans:
		_laminar_event(
			'rust_core.llm_spans_truncated',
			{'recorded': max_spans, 'available': len(ranges)},
		)


def _history_from_events(
	events: list[dict[str, Any]],
	*,
	model: str,
	started: float,
	finished: float,
	output_model_schema: type[AgentStructuredOutput] | None,
	process_error: str | None,
) -> AgentHistoryList[AgentStructuredOutput]:
	events = _events_after_terminal_rollbacks(_events_after_terminal_compaction(events))
	final_result = _structured_result_text(_result_from_events(events), output_model_schema)
	failure = process_error or _failure_from_events(events)
	if final_result is None and failure is not None:
		final_result = _structured_result_text(_last_streamed_assistant_text_from_events(events), output_model_schema)
	if final_result is None and failure is None:
		failure = _recoverable_failure_from_events(events)
	if final_result is None and failure is None:
		failure = 'Rust terminal session did not produce a final result.'
	is_done = final_result is not None and failure is None
	attachments = _attachments_from_events(events)
	history_items = _history_items_from_terminal_turns(
		events,
		started=started,
		finished=finished,
		final_result=final_result,
		attachments=attachments,
		failure=failure,
		is_done=is_done,
	)
	if history_items is not None:
		history_list: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(
			history=history_items,
			usage=_usage_from_events(events, model),
		)
		history_list._output_model_schema = output_model_schema
		return history_list
	tool_calls = _tool_calls_with_final_done(
		_tool_started_calls(events),
		final_result=final_result,
		attachments=attachments,
		is_done=is_done,
	)
	history = AgentHistory(
		model_output=_model_output_from_tool_calls(tool_calls, events),
		result=_action_results_from_tool_calls(
			tool_calls,
			events,
			final_result=final_result,
			attachments=attachments,
			failure=failure,
			is_done=is_done,
		),
		state=_browser_state_from_events(events),
		metadata=StepMetadata(step_start_time=started, step_end_time=finished, step_number=max(1, len(events))),
	)
	history_list: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(
		history=[history],
		usage=_usage_from_events(events, model),
	)
	history_list._output_model_schema = output_model_schema
	return history_list


def _load_rust_history(file_path: str | Path) -> AgentHistoryList:
	with open(file_path, encoding='utf-8') as history_file:
		data = json.load(history_file)
	if not isinstance(data, dict):
		raise BetaAgentError(f'Invalid Browser Use history file: {file_path}')
	for item in data.get('history', []):
		if isinstance(item, dict):
			item['model_output'] = None
			state = item.get('state')
			if isinstance(state, dict) and 'interacted_element' not in state:
				state['interacted_element'] = None
	return AgentHistoryList.model_validate(data)


def _default_browser_session(
	agent_id: str,
	browser_profile: BrowserProfile | None,
	browser_session: Any | None,
	browser: Any | None,
) -> tuple[Any | None, Any | None]:
	if browser is not None:
		return browser, getattr(browser, 'browser_profile', browser_profile)
	if browser_session is not None:
		return browser_session, getattr(browser_session, 'browser_profile', browser_profile)
	if browser_profile is not None and not isinstance(browser_profile, BrowserProfile):
		return None, browser_profile
	resolved_profile = browser_profile or BrowserProfile()
	session = BrowserSession(
		browser_profile=resolved_profile,
		id=uuid7str()[:-4] + agent_id[-4:],
	)
	return session, session.browser_profile


def _init_file_system(
	state: AgentState,
	agent_directory: Path,
	file_system_path: str | None,
) -> tuple[FileSystem, str]:
	if state.file_system_state and file_system_path:
		raise ValueError(
			'Cannot provide both file_system_state (from agent state) and file_system_path. '
			'Either restore from existing state or create new file system at specified path, not both.'
		)
	if state.file_system_state:
		file_system = FileSystem.from_state(state.file_system_state)
		return file_system, str(file_system.base_dir)
	if file_system_path:
		file_system = FileSystem(file_system_path)
		state.file_system_state = file_system.get_state()
		return file_system, file_system_path
	file_system = FileSystem(agent_directory)
	state.file_system_state = file_system.get_state()
	return file_system, str(agent_directory)


def _resolve_tools(
	tools: Any | None,
	controller: Any | None,
	output_model_schema: type[BaseModel] | None,
	use_vision: bool | Literal['auto'],
	display_files_in_done_text: bool,
) -> Any:
	resolved_tools = tools if tools is not None else controller
	if resolved_tools is None:
		exclude_actions = ['screenshot'] if use_vision is False else []
		resolved_tools = Tools(exclude_actions=exclude_actions, display_files_in_done_text=display_files_in_done_text)
	if output_model_schema is not None and hasattr(resolved_tools, 'use_structured_output_action'):
		resolved_tools.use_structured_output_action(output_model_schema)
	return resolved_tools


def _browser_use_version_and_source(source_override: str | None = None) -> tuple[str | None, str]:
	version = get_browser_use_version()
	try:
		package_root = Path(__file__).parent.parent.parent
		repo_files = ['.git', 'README.md', 'docs', 'examples']
		source = 'git' if all((package_root / file).exists() for file in repo_files) else 'pip'
	except Exception:
		source = 'unknown'
	if source_override is not None:
		source = source_override
	return version, source


def _register_llm_for_usage(token_cost_service: TokenCost, llm: Any | None) -> None:
	if llm is None or not hasattr(llm, 'ainvoke'):
		return
	try:
		token_cost_service.register_llm(llm)
	except Exception:
		return


def _eventbus_name(agent_id: str, prefix: str = 'Agent') -> str:
	suffix = re.sub(r'\W', '_', str(agent_id)[-4:])
	return f'{prefix}_{suffix or "agent"}'


class _CloudEventLLMProxy:
	def __init__(self, model_name: str):
		self.model_name = model_name


class _CloudEventAgentProxy:
	def __init__(self, agent: Agent):
		self._agent = agent
		self.llm = _CloudEventLLMProxy(getattr(agent, 'model', None) or _model_name(getattr(agent, 'llm', None)))

	def __getattr__(self, name: str) -> Any:
		return getattr(self._agent, name)


def _unique_eventbus_name(agent_id: str, prefix: str = 'Agent') -> str:
	unique_suffix = re.sub(r'\W', '_', uuid7str()[-8:])
	return f'{_eventbus_name(agent_id, prefix)}_{unique_suffix}'


def _action_payload(action: Any) -> dict[str, Any]:
	"""Serialize a Browser Use action model into JSON-like data for Rust task context."""
	if isinstance(action, dict):
		return action
	if hasattr(action, 'model_dump'):
		try:
			dumped = action.model_dump(exclude_unset=True, mode='json')
		except TypeError:
			dumped = action.model_dump(exclude_unset=True)
		if isinstance(dumped, dict):
			return dumped
	return {'action': str(action)}


def _done_action_result(payload: dict[str, Any]) -> ActionResult | None:
	done_payload = payload.get('done')
	if done_payload is None:
		return None
	if hasattr(done_payload, 'model_dump'):
		done_payload = done_payload.model_dump(exclude_unset=True, mode='json')
	if not isinstance(done_payload, dict):
		done_payload = {}
	success = done_payload.get('success')
	if not isinstance(success, bool):
		success = True
	text = done_payload.get('text')
	if not isinstance(text, str) and 'data' in done_payload:
		text = json.dumps(done_payload['data'], ensure_ascii=False, default=str)
	if not isinstance(text, str):
		text = ''
	files = done_payload.get('files_to_display')
	attachments = [str(item) for item in files if isinstance(item, (str, os.PathLike))] if isinstance(files, list) else None
	return ActionResult(
		is_done=True,
		success=success,
		extracted_content=text,
		long_term_memory=f'Task completed. Success Status: {success}',
		attachments=attachments or None,
	)


def _actions_instruction(payloads: list[dict[str, Any]]) -> str:
	actions_json = json.dumps(payloads, indent=2, ensure_ascii=False, default=str)
	return (
		'Execute these Browser Use action models in order using the current browser page/session. '
		'Return a concise result for the executed actions.\n\n'
		f'Actions:\n{actions_json}'
	)


def _normalize_initial_action(action_name: str, params: Any) -> tuple[str, Any]:
	if not isinstance(params, dict):
		return action_name, params
	if action_name in ('go_to_url', 'open_tab'):
		normalized = dict(params)
		if action_name == 'open_tab' and 'new_tab' not in normalized:
			normalized['new_tab'] = True
		return 'navigate', normalized
	if action_name == 'click_element_by_index':
		return 'click', params
	if action_name == 'input_text':
		return 'input', params
	return action_name, params


class Agent(Generic[Context, AgentStructuredOutput]):
	"""Browser Use-style Agent backed by the Rust browser-use-terminal core."""

	def __init__(
		self,
		task: str,
		llm: BaseChatModel | None = None,
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		browser: BrowserSession | None = None,
		tools: Tools[Context] | None = None,
		controller: Tools[Context] | None = None,
		skill_ids: list[str | Literal['*']] | None = None,
		skills: list[str | Literal['*']] | None = None,
		skill_service: Any | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		initial_actions: list[dict[str, dict[str, Any]]] | None = None,
		register_new_step_callback: AgentNewStepCallback | None = None,
		register_done_callback: AgentDoneCallback | None = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		register_should_stop_callback: Callable[[], Awaitable[bool]] | None = None,
		output_model_schema: type[AgentStructuredOutput] | None = None,
		extraction_schema: dict | None = None,
		use_vision: bool | Literal['auto'] = True,
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 5,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 5,
		use_thinking: bool = True,
		flash_mode: bool = False,
		demo_mode: bool | None = None,
		max_history_items: int | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		fallback_llm: BaseChatModel | None = None,
		use_judge: bool = True,
		ground_truth: str | None = None,
		judge_llm: BaseChatModel | None = None,
		injected_agent_state: AgentState | None = None,
		source: str | None = None,
		file_system_path: str | None = None,
		task_id: str | None = None,
		calculate_cost: bool = False,
		pricing_url: str | None = None,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int | None = None,
		step_timeout: int = 180,
		directly_open_url: bool = True,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
		final_response_after_failure: bool = True,
		enable_planning: bool = True,
		planning_replan_on_stall: int = 3,
		planning_exploration_limit: int = 5,
		loop_detection_window: int = 20,
		loop_detection_enabled: bool = True,
		llm_screenshot_size: tuple[int, int] | None = None,
		message_compaction: MessageCompactionSettings | bool | None = True,
		max_clickable_elements_length: int = 40000,
		_url_shortening_limit: int = 25,
		enable_signal_handler: bool = True,
		**kwargs,
	):
		if llm_screenshot_size is not None:
			if not isinstance(llm_screenshot_size, tuple) or len(llm_screenshot_size) != 2:
				raise ValueError('llm_screenshot_size must be a tuple of (width, height)')
			width, height = llm_screenshot_size
			if not isinstance(width, int) or not isinstance(height, int):
				raise ValueError('llm_screenshot_size dimensions must be integers')
			if width < 100 or height < 100:
				raise ValueError('llm_screenshot_size dimensions must be at least 100 pixels')
		llm = _resolve_default_llm(llm)
		use_vision = True
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session" parameters. Use "browser" for the cleaner API.')
		if getattr(llm, 'provider', None) == 'browser-use':
			flash_mode = True
		if flash_mode:
			enable_planning = False
		if llm_screenshot_size is None:
			model_name = getattr(llm, 'model', '')
			# rsplit drops the provider prefix so gateway ids like 'anthropic/claude-sonnet-4-6'
			# get the same screenshot auto-config as direct Claude Sonnet models.
			if isinstance(model_name, str) and model_name.rsplit('/', 1)[-1].startswith('claude-sonnet'):
				llm_screenshot_size = (1400, 850)
		if page_extraction_llm is None:
			page_extraction_llm = llm
		if judge_llm is None:
			judge_llm = llm
		if llm_timeout is None:
			llm_timeout = _llm_timeout_for_model(llm)
		self.id = task_id or uuid7str()
		self.task_id = self.id
		self.llm = llm
		self.judge_llm = judge_llm
		self.browser_session, self._browser_profile = _default_browser_session(
			self.id,
			browser_profile,
			browser_session,
			browser,
		)
		if demo_mode is not None and self.browser_profile is not None:
			profile_demo_mode = getattr(self.browser_profile, 'demo_mode', None)
			if profile_demo_mode != demo_mode and hasattr(self.browser_profile, 'model_copy'):
				updated_profile = self.browser_profile.model_copy(update={'demo_mode': demo_mode})
				self._browser_profile = updated_profile
				if self.browser_session is not None and hasattr(self.browser_session, 'browser_profile'):
					self.browser_session.browser_profile = updated_profile
		self.tools = _resolve_tools(
			tools,
			controller,
			output_model_schema,
			use_vision,
			display_files_in_done_text,
		)
		if skills and skill_ids:
			raise ValueError('Cannot specify both "skills" and "skill_ids" parameters. Use "skills" for the cleaner API.')
		skill_ids = skills or skill_ids
		self.skill_service = None
		self._skills_registered = False
		if skill_service is not None:
			self.skill_service = skill_service
		elif skill_ids:
			from browser_use.skills import SkillService

			self.skill_service = SkillService(skill_ids=skill_ids)
		self.extraction_schema = extraction_schema
		if self.extraction_schema is None and output_model_schema is not None:
			self.extraction_schema = output_model_schema.model_json_schema()
		self._fallback_llm = fallback_llm
		self._using_fallback_llm = False
		self._original_llm = llm
		self.sensitive_data = sensitive_data
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback
		self.register_should_stop_callback = register_should_stop_callback
		self.output_model_schema = output_model_schema
		self._set_browser_use_version_and_source(source)
		self.kwargs = kwargs
		self.model = _model_name(llm)
		if isinstance(message_compaction, bool):
			message_compaction = MessageCompactionSettings(enabled=message_compaction)
		self.state = injected_agent_state or AgentState()
		self.state.loop_detector.window_size = loop_detection_window
		timestamp = int(time.time())
		self.agent_directory = Path(tempfile.gettempdir()) / f'browser_use_agent_{self.id}_{timestamp}'
		self._set_file_system(file_system_path)
		self._set_screenshot_service()
		self.settings = AgentSettings(
			use_vision=use_vision,
			vision_detail_level=vision_detail_level,
			save_conversation_path=save_conversation_path,
			save_conversation_path_encoding=save_conversation_path_encoding,
			max_failures=max_failures,
			override_system_message=override_system_message,
			extend_system_message=extend_system_message,
			generate_gif=generate_gif,
			include_attributes=include_attributes,
			max_actions_per_step=max_actions_per_step,
			use_thinking=use_thinking,
			flash_mode=flash_mode,
			max_history_items=max_history_items,
			page_extraction_llm=page_extraction_llm,
			calculate_cost=calculate_cost,
			include_tool_call_examples=include_tool_call_examples,
			llm_timeout=llm_timeout,
			step_timeout=step_timeout,
			final_response_after_failure=final_response_after_failure,
			use_judge=use_judge,
			ground_truth=ground_truth,
			enable_planning=enable_planning,
			planning_replan_on_stall=planning_replan_on_stall,
			planning_exploration_limit=planning_exploration_limit,
			loop_detection_window=loop_detection_window,
			loop_detection_enabled=loop_detection_enabled,
			message_compaction=message_compaction,
			max_clickable_elements_length=max_clickable_elements_length,
		)
		if self.settings.save_conversation_path:
			self.settings.save_conversation_path = Path(self.settings.save_conversation_path).expanduser().resolve()
			self.logger.info(f'💬 Saving conversation to {_log_pretty_path(self.settings.save_conversation_path)}')
		self._setup_action_models()
		self._verify_and_setup_llm()
		logger.debug(
			f'{" +vision" if self.settings.use_vision else ""}'
			f' extraction_model={getattr(self.settings.page_extraction_llm, "model", "Unknown") if self.settings.page_extraction_llm else "Unknown"}'
			f'{" +file_system" if self.file_system else ""}'
		)
		self.token_cost_service = TokenCost(include_cost=calculate_cost, pricing_url=pricing_url)
		_register_llm_for_usage(self.token_cost_service, llm)
		_register_llm_for_usage(self.token_cost_service, page_extraction_llm)
		_register_llm_for_usage(self.token_cost_service, judge_llm)
		if self.settings.message_compaction and self.settings.message_compaction.compaction_llm:
			_register_llm_for_usage(self.token_cost_service, self.settings.message_compaction.compaction_llm)
		self.enable_signal_handler = enable_signal_handler
		self.telemetry = ProductTelemetry()
		self.eventbus = EventBus(name=_eventbus_name(self.id))
		self._eventbus_stopped = False
		self.available_file_paths = available_file_paths or []
		self.allowed_domains = _extract_profile_domains(self.browser_session, self.browser_profile, 'allowed_domains')
		self.prohibited_domains = _extract_profile_domains(self.browser_session, self.browser_profile, 'prohibited_domains')
		self.managed_browser_args = _managed_browser_launch_args(self.browser_session, self.browser_profile)
		self.managed_browser_profile_dir = _managed_browser_profile_dir(self.browser_session, self.browser_profile)
		self.managed_browser_executable_path = _managed_browser_executable_path(self.browser_session, self.browser_profile)
		self.managed_browser_env = _managed_browser_env(self.browser_session, self.browser_profile)
		self.cdp_headers = _extract_cdp_headers(self.browser_session, self.browser_profile)
		self.browser_user_agent = _extract_user_agent(self.browser_session, self.browser_profile)
		self.highlight_enabled, self.highlight_color, self.highlight_duration_ms = _extract_highlight_settings(
			self.browser_session, self.browser_profile
		)
		self.wait_timing_env = _extract_wait_timing_settings(self.browser_session, self.browser_profile)
		self.block_ip_addresses = _extract_block_ip_addresses(self.browser_session, self.browser_profile)
		self.browser_permissions = _extract_profile_permissions(self.browser_session, self.browser_profile)
		self.browser_accept_downloads, self.browser_downloads_path = _extract_browser_downloads(
			self.browser_session, self.browser_profile
		)
		self.browser_no_viewport, self.browser_viewport = _extract_browser_viewport(self.browser_session, self.browser_profile)
		self.browser_window_size = _extract_browser_window_size(self.browser_session, self.browser_profile)
		self.browser_storage_state = _extract_browser_storage_state(self.browser_session, self.browser_profile)
		self.sensitive_data_context = _sensitive_data_context(sensitive_data)
		_warn_sensitive_data_domain_constraints(self.logger, sensitive_data, self.allowed_domains)
		self.display_files_in_done_text = display_files_in_done_text
		self.has_downloads_path = getattr(self.browser_profile, 'downloads_path', None) is not None
		self._last_known_downloads: list[str] = []
		self.directly_open_url = directly_open_url
		self.include_recent_events = include_recent_events
		self.sample_images = sample_images
		self._url_shortening_limit = _url_shortening_limit
		self.initial_url = None
		if self.directly_open_url and not self.state.follow_up_task and not initial_actions:
			self.initial_url = _extract_start_url(task)
			if self.initial_url:
				self.logger.info(f'🔗 Found URL in task: {self.initial_url}, adding as initial action...')
				initial_actions = [{'navigate': {'url': self.initial_url, 'new_tab': False}}]
		self.initial_action_payloads = list(initial_actions or [])
		self.initial_actions = (
			self._convert_initial_actions(self.initial_action_payloads) if self.initial_action_payloads else None
		)
		self._initial_actions_executed = False
		self._completed_initial_navigation_urls: list[str] = []
		self._completed_initial_navigation_states: list[dict[str, Any]] = []
		self._pending_history_prefix: list[AgentHistory] = []
		self.task = _task_with_schema(
			_task_with_available_files(
				_task_with_sensitive_data_context(
					_task_with_domain_constraints(
						_task_with_initial_actions(task, self.initial_action_payloads),
						self.allowed_domains,
						self.prohibited_domains,
					),
					self.sensitive_data_context,
				),
				self.available_file_paths,
			),
			output_model_schema,
		)
		self._message_manager = MessageManager(
			task=self.task,
			system_message=SystemPrompt(
				max_actions_per_step=self.settings.max_actions_per_step,
				override_system_message=self.settings.override_system_message,
				extend_system_message=self.settings.extend_system_message,
				use_thinking=self.settings.use_thinking,
				flash_mode=self.settings.flash_mode,
				is_anthropic=str(getattr(self.llm, 'provider', '')).lower() == 'anthropic',
				is_browser_use_model=str(getattr(self.llm, 'provider', '')).lower() == 'browser-use',
				model_name=getattr(self.llm, 'model', self.model),
			).get_system_message(),
			file_system=self.file_system,
			state=self.state.message_manager_state,
			use_thinking=self.settings.use_thinking,
			include_attributes=self.settings.include_attributes,
			sensitive_data=sensitive_data,
			max_history_items=self.settings.max_history_items,
			vision_detail_level=self.settings.vision_detail_level,
			include_tool_call_examples=self.settings.include_tool_call_examples,
			include_recent_events=self.include_recent_events,
			sample_images=self.sample_images,
			llm_screenshot_size=llm_screenshot_size,
			max_clickable_elements_length=self.settings.max_clickable_elements_length,
		)
		if self.browser_session is not None:
			self.browser_session.llm_screenshot_size = llm_screenshot_size
		self.session_id: str = uuid7str()
		self.terminal_session_id: str | None = None
		self._sdk_agent_id: str | None = None
		self._sdk_browser_id: str | None = None
		self._sdk_client: RustSdkClient | None = None
		self._active_sdk_run_id: str | None = None
		self.laminar_trace_id: str | None = None
		self.history: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(history=[], usage=None)
		self.result: AgentHistoryList[AgentStructuredOutput] | None = None
		self.last_events: list[dict[str, Any]] = []
		self.last_child_events: list[dict[str, Any]] = []
		self.last_usage_events: list[dict[str, Any]] = []
		self.last_observability_events: list[dict[str, Any]] = []
		self.last_stdout = ''
		self.last_stderr = ''
		self._last_synced_history_id: int | None = None
		self._last_step_callback_history_id: int | None = None
		self._last_step_end_callback_history_id: int | None = None
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	def _set_file_system(self, file_system_path: str | None = None) -> None:
		"""Initialize or restore Browser Use file-system state."""
		self.file_system, self.file_system_path = _init_file_system(self.state, self.agent_directory, file_system_path)

	def _set_screenshot_service(self) -> None:
		"""Initialize Browser Use screenshot storage under the agent directory."""
		self.screenshot_service = ScreenshotService(self.agent_directory)

	def _set_browser_use_version_and_source(self, source_override: str | None = None) -> None:
		"""Expose Browser Use version/source metadata on the Rust-backed wrapper."""
		self.version, self.source = _browser_use_version_and_source(source_override)

	def _verify_and_setup_llm(self):
		"""Mirror Browser Use LLM verification state for callers that use the helper."""
		if self.llm is None:
			return True
		try:
			from browser_use.config import CONFIG

			skip_verification = CONFIG.SKIP_LLM_API_KEY_VERIFICATION
		except Exception:
			skip_verification = False
		if getattr(self.llm, '_verified_api_keys', None) is True or skip_verification:
			setattr(self.llm, '_verified_api_keys', True)
		return True

	async def _log_agent_run(self) -> None:
		"""Log Browser Use run metadata for the Rust-backed wrapper."""
		self.logger.info(f'\033[34m🎯 Task: {self.task}\033[0m')
		self.logger.debug(f'🤖 Browser-Use Library Version {self.version} ({self.source})')
		latest_version = await check_latest_browser_use_version()
		if latest_version and latest_version != self.version:
			self.logger.info(
				f'📦 Newer version available: {latest_version} (current: {self.version}). Upgrade with: uv add browser-use=={latest_version}'
			)

	def _log_agent_setup(self) -> None:
		"""Log Browser Use run setup metadata for the Rust-backed wrapper."""
		browser_session_id = getattr(self.browser_session, 'id', None) if self.browser_session else None
		browser_session_suffix = str(browser_session_id)[-4:] if browser_session_id else 'None'
		cdp_url = getattr(self.browser_session, 'cdp_url', None) if self.browser_session else None
		connection_mode = '(connecting via CDP)' if cdp_url else '(launching local browser)'
		self.logger.debug(
			f'Agent setup: Agent Session ID {self.session_id[-4:]}, Task ID {self.task_id[-4:]}, Browser Session ID {browser_session_suffix} {connection_mode}'
		)

	def _log_first_step_startup(self) -> None:
		"""Log the first-step startup line used by Browser Use callers."""
		if len(self.history.history) != 0:
			return
		provider = getattr(self.llm, 'provider', None) or 'rust-terminal'
		model = getattr(self.llm, 'model', None) or self.model
		self.logger.info(f'Starting a browser-use agent with version {self.version}, with provider={provider} and model={model}')

	def _log_main_execution_start(self, max_steps: int) -> None:
		"""Log Browser Use's main execution-loop start for terminal-backed runs."""
		self.logger.debug(f'Starting main execution loop with max {max_steps} steps...')

	def _log_step_context(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Log current step and page context."""
		url = getattr(browser_state_summary, 'url', '') if browser_state_summary else ''
		url_short = url[:50] + '...' if len(url) > 50 else url
		dom_state = getattr(browser_state_summary, 'dom_state', None)
		selector_map = getattr(dom_state, 'selector_map', {}) if dom_state else {}
		interactive_count = len(selector_map) if selector_map else 0
		self.logger.info('')
		self.logger.info(f'Step {self.state.n_steps}:')
		self.logger.debug(f'Evaluating page with {interactive_count} interactive elements on: {url_short}')

	def _log_next_action_summary(self, parsed: AgentOutput) -> None:
		"""Log a concise summary of the next action list."""
		actions = getattr(parsed, 'action', None)
		if not (self.logger.isEnabledFor(logging.DEBUG) and actions):
			return
		action_details = []
		for action in actions:
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys())) if action_data else 'unknown'
			action_params = action_data.get(action_name, {}) if action_data else {}
			param_summary = []
			if isinstance(action_params, dict):
				for key, value in action_params.items():
					if key == 'index':
						param_summary.append(f'#{value}')
					elif key == 'text' and isinstance(value, str):
						text_preview = value[:30] + '...' if len(value) > 30 else value
						param_summary.append(f'text="{text_preview}"')
					elif key == 'url':
						param_summary.append(f'url="{value}"')
					elif key == 'success':
						param_summary.append(f'success={value}')
					elif isinstance(value, (str, int, bool)):
						value_str = str(value)
						value_preview = value_str[:30] + '...' if len(value_str) > 30 else value_str
						param_summary.append(f'{key}={value_preview}')
			param_text = f'({", ".join(param_summary)})' if param_summary else ''
			action_details.append(f'{action_name}{param_text}')
		self.logger.debug(f'Next actions: {", ".join(action_details)}')

	def _log_step_completion_summary(self, step_start_time: float, result: list[ActionResult]) -> None:
		"""Log action count, timing, and success/failure counts for a completed step."""
		if not result:
			return
		step_duration = time.time() - step_start_time
		action_count = len(result)
		success_count = sum(1 for item in result if not item.error)
		failure_count = action_count - success_count
		status_parts = []
		if success_count > 0:
			status_parts.append(f'success={success_count}')
		if failure_count > 0:
			status_parts.append(f'failed={failure_count}')
		status_text = ' | '.join(status_parts) if status_parts else 'success=0'
		self.logger.debug(
			f'Step {self.state.n_steps}: Ran {action_count} action{"" if action_count == 1 else "s"} in {step_duration:.2f}s: {status_text}'
		)

	def _log_final_outcome_messages(self) -> None:
		"""Log Browser Use-style guidance for failed runs."""
		is_successful = self.history.is_successful()
		if is_successful is not False and is_successful is not None:
			return
		final_result = self.history.final_result()
		final_result_str = str(final_result).lower() if final_result else ''
		captcha_keywords = ['captcha', 'cloudflare', 'recaptcha', 'challenge', 'bot detection', 'access denied']
		if any(keyword in final_result_str for keyword in captcha_keywords):
			task_preview = self.task[:10] if len(self.task) > 10 else self.task
			self.logger.info('')
			self.logger.info('Failed because of CAPTCHA? For better browser stealth, try:')
			self.logger.info(f'   agent = Agent(task="{task_preview}...", browser=Browser(use_cloud=True))')
		self.logger.info('')
		self.logger.info('Did the Agent not work as expected? Let us fix this!')
		self.logger.info('   Please open a short issue here: https://github.com/browser-use/browser-use/issues')

	@observe(ignore_input=True, ignore_output=False)
	async def _judge_trace(self) -> JudgementResult | None:
		"""Judge the reconstructed Rust terminal trace with the configured judge LLM."""
		input_messages = construct_judge_messages(
			task=self.task,
			final_result=self.history.final_result() or '',
			agent_steps=self.history.agent_steps(),
			screenshot_paths=[path for path in self.history.screenshot_paths() if path is not None],
			max_images=10,
			ground_truth=self.settings.ground_truth,
			use_vision=self.settings.use_vision,
		)

		kwargs: dict[str, Any] = {'output_format': JudgementResult}
		if getattr(self.judge_llm, 'provider', None) == 'browser-use':
			kwargs['request_type'] = 'judge'
			kwargs['session_id'] = self.session_id

		try:
			response = await self.judge_llm.ainvoke(input_messages, **kwargs)
			return response.completion  # type: ignore[return-value]
		except Exception as exc:
			self.logger.error(f'Judge trace failed: {exc}')
			return None

	async def _judge_and_log(self) -> None:
		"""Run judge evaluation and attach the verdict to the final action result."""
		judgement = await self._judge_trace()
		if not self.history.history:
			return
		last_step = self.history.history[-1]
		if not last_step.result:
			return
		last_result = last_step.result[-1]
		if not last_result.is_done:
			return

		last_result.judgement = judgement
		self_reported_success = last_result.success
		if not judgement:
			return
		if self_reported_success is True and judgement.verdict is True:
			return

		judge_log = '\n'
		if self_reported_success is True and judgement.verdict is False:
			judge_log += '⚠️  \033[33mAgent reported success but judge thinks task failed\033[0m\n'

		verdict_color = '\033[32m' if judgement.verdict else '\033[31m'
		verdict_text = '✅ PASS' if judgement.verdict else '❌ FAIL'
		judge_log += f'⚖️  {verdict_color}Judge Verdict: {verdict_text}\033[0m\n'
		if judgement.failure_reason:
			judge_log += f'   Failure Reason: {judgement.failure_reason}\n'
		if judgement.reached_captcha:
			self.logger.warning(
				'Agent was blocked by a captcha. Cloud browsers include stealth fingerprinting and proxy rotation to avoid this.\n'
				'         Try: Browser(use_cloud=True)  |  Get an API key: https://cloud.browser-use.com?utm_source=oss&utm_medium=captcha_nudge'
			)
		judge_log += f'   {judgement.reasoning}\n'
		self.logger.info(judge_log)

	def _log_agent_event(self, max_steps: int, agent_run_error: str | None = None) -> None:
		"""Emit Browser Use telemetry for a Rust-backed run."""
		usage = self.history.usage
		if usage is None:
			total_input_tokens = 0
			total_output_tokens = 0
			prompt_cached_tokens = 0
			total_tokens = 0
		else:
			total_input_tokens = usage.total_prompt_tokens
			total_output_tokens = usage.total_completion_tokens
			prompt_cached_tokens = usage.total_prompt_cached_tokens
			total_tokens = usage.total_tokens

		action_history_data = []
		for item in self.history.history:
			if item.model_output and item.model_output.action:
				action_history_data.append(
					[action.model_dump(exclude_unset=True) for action in item.model_output.action if action]
				)
			else:
				action_history_data.append(None)

		final_result = self.history.final_result()
		final_result_str = json.dumps(final_result) if final_result is not None else None
		cdp_url = getattr(self.browser_session, 'cdp_url', None) if self.browser_session else None
		model = getattr(self.llm, 'model', None) or self.model
		provider = getattr(self.llm, 'provider', None) or 'rust-terminal'

		self.telemetry.capture(
			AgentTelemetryEvent(
				task=self.task,
				model=model,
				model_provider=provider,
				max_steps=max_steps,
				max_actions_per_step=self.settings.max_actions_per_step,
				use_vision=self.settings.use_vision,
				version=self.version or '',
				source=self.source,
				cdp_url=urlparse(cdp_url).hostname if cdp_url else None,
				agent_type='rust_core',
				action_errors=self.history.errors(),
				action_history=action_history_data,
				urls_visited=[url for url in self.history.urls() if url],
				steps=self.history.number_of_steps(),
				total_input_tokens=total_input_tokens,
				total_output_tokens=total_output_tokens,
				prompt_cached_tokens=prompt_cached_tokens,
				total_tokens=total_tokens,
				total_duration_seconds=self.history.total_duration_seconds(),
				success=self.history.is_successful(),
				final_result_response=final_result_str,
				error_message=agent_run_error,
			)
		)

	def _record_run_telemetry(self, max_steps: int, agent_run_error: str | None = None) -> None:
		"""Record Browser Use run telemetry without allowing telemetry failures to break the run."""
		if getattr(self, '_force_exit_telemetry_logged', False):
			self.logger.debug('Telemetry for force exit (SIGINT) was logged by custom exit callback.')
			return
		try:
			self._log_agent_event(max_steps=max_steps, agent_run_error=agent_run_error)
		except Exception as exc:
			self.logger.error(f'Failed to log telemetry event: {exc}', exc_info=True)

	def _record_laminar_run_observability(
		self,
		*,
		max_steps: int,
		duration_seconds: float | None,
		process_error: str | None = None,
	) -> None:
		"""Populate the current Laminar agent.run span for terminal-backed runs."""
		if not _laminar_ready():
			return
		errors = self.history.errors()
		usage = self.history.usage
		final_result = self.history.final_result()
		model = getattr(self.llm, 'model', None) or self.model
		provider = getattr(self.llm, 'provider', None) or 'rust-terminal'
		summary = {
			'runtime': 'browser_use.beta',
			'model': model,
			'provider': provider,
			'max_steps': max_steps,
			'steps': self.history.number_of_steps(),
			'is_done': self.history.is_done(),
			'is_successful': self.history.is_successful(),
			'errors_count': len(errors or []),
			'errors_preview': _laminar_preview(errors, limit=1500),
			'final_result_preview': _laminar_preview(final_result, limit=2000),
			'terminal_session_id': self.terminal_session_id,
			'browser_use_session_id': self.session_id,
			'terminal_events_count': len(self.last_observability_events or self.last_events or []),
			'duration_seconds': duration_seconds,
			'process_error': process_error,
		}
		if usage is not None:
			summary.update(
				{
					'usage_total_tokens': usage.total_tokens,
					'usage_prompt_tokens': usage.total_prompt_tokens,
					'usage_prompt_cost': usage.total_prompt_cost,
					'usage_prompt_cached_tokens': usage.total_prompt_cached_tokens,
					'usage_prompt_cached_cost': usage.total_prompt_cached_cost,
					'usage_prompt_cache_creation_tokens': usage.total_prompt_cache_creation_tokens,
					'usage_prompt_cache_creation_cost': usage.total_prompt_cache_creation_cost,
					'usage_completion_tokens': usage.total_completion_tokens,
					'usage_completion_cost': usage.total_completion_cost,
					'usage_total_cost': usage.total_cost,
				}
			)
		observability_events = self.last_observability_events or self.last_events or []
		_record_laminar_terminal_llm_spans(
			observability_events,
			default_model=str(model),
			default_provider=str(provider),
		)
		_record_laminar_terminal_tool_spans(
			observability_events,
			max_spans=_int_value(os.getenv('BROWSER_USE_RUST_LAMINAR_MAX_TOOL_SPANS') or 160),
		)
		_laminar_set_span_attributes(
			{
				'runtime': summary['runtime'],
				'model': model,
				'provider': provider,
				'max_steps': max_steps,
				'steps': summary['steps'],
				'is_done': summary['is_done'],
				'is_successful': summary['is_successful'],
				'terminal_session_id': self.terminal_session_id,
				'terminal_events_count': summary['terminal_events_count'],
				'duration_seconds': duration_seconds,
				'process_error': process_error,
				'usage_total_cost': usage.total_cost if usage is not None else None,
				'usage_prompt_cached_tokens': usage.total_prompt_cached_tokens if usage is not None else None,
				'usage_prompt_cache_creation_tokens': usage.total_prompt_cache_creation_tokens if usage is not None else None,
			}
		)
		_laminar_set_span_output(summary)
		_laminar_event(
			'agent.run.terminal_summary',
			{
				'runtime': summary['runtime'],
				'steps': summary['steps'],
				'is_successful': summary['is_successful'],
				'duration_seconds': duration_seconds,
				'terminal_events_count': summary['terminal_events_count'],
			},
		)

	async def _log_run_usage_summary(self) -> None:
		"""Log Browser Use token usage summary for a completed Rust-backed run."""
		await self.token_cost_service.log_usage_summary()

	async def _apply_terminal_usage_costs(self, events: list[dict[str, Any]]) -> None:
		"""Populate cost fields for terminal-reconstructed usage."""
		if self.history is None:
			return
		try:
			self.history.usage = await _usage_from_events_with_costs(events, self.model, self.token_cost_service)
		except Exception as exc:
			self.logger.debug(f'Failed to price Rust terminal usage: {exc}', exc_info=True)

	def _cloud_event_agent(self):
		llm_model_name = getattr(getattr(self, 'llm', None), 'model_name', None)
		if isinstance(llm_model_name, str) and llm_model_name:
			return self
		return _CloudEventAgentProxy(self)

	def _ensure_eventbus(self) -> None:
		if getattr(self, '_eventbus_stopped', False):
			self.eventbus = EventBus(name=_unique_eventbus_name(self.id))
			self._eventbus_stopped = False

	def _register_run_signal_handler(self, max_steps: int) -> SignalHandler:
		"""Register Browser Use SIGINT/SIGTERM handling for a Rust-backed run."""
		self._unregister_run_signal_handler()
		self._force_exit_telemetry_logged = False

		def on_force_exit_log_telemetry() -> None:
			self._record_run_telemetry(max_steps=max_steps, agent_run_error='SIGINT: Cancelled by user')
			if hasattr(self, 'telemetry') and self.telemetry:
				self.telemetry.flush()
			self._force_exit_telemetry_logged = True

		signal_handler = SignalHandler(
			loop=asyncio.get_event_loop(),
			pause_callback=self.pause,
			resume_callback=self.resume,
			custom_exit_callback=on_force_exit_log_telemetry,
			exit_on_second_int=True,
		)
		signal_handler.register()
		self._run_signal_handler = signal_handler
		return signal_handler

	def _unregister_run_signal_handler(self) -> None:
		signal_handler = getattr(self, '_run_signal_handler', None)
		if signal_handler is None:
			return
		try:
			signal_handler.unregister()
		finally:
			self._run_signal_handler = None

	def _dispatch_run_start_events(self) -> None:
		"""Emit Browser Use cloud lifecycle create events for a Rust-backed run."""
		self._ensure_eventbus()
		event_agent = self._cloud_event_agent()
		if not self.state.session_initialized:
			self.logger.debug('Dispatching CreateAgentSessionEvent...')
			self.eventbus.dispatch(CreateAgentSessionEvent.from_agent(event_agent))
			self.state.session_initialized = True
		self.logger.debug('Dispatching CreateAgentTaskEvent...')
		self.eventbus.dispatch(CreateAgentTaskEvent.from_agent(event_agent))

	def _dispatch_run_update_event(self) -> None:
		"""Emit Browser Use cloud lifecycle update event for a completed Rust-backed run."""
		self.eventbus.dispatch(UpdateAgentTaskEvent.from_agent(self._cloud_event_agent()))

	async def _stop_eventbus_after_run(self) -> None:
		"""Stop the eventbus after run-level events have been dispatched."""
		stop = getattr(self.eventbus, 'stop', None)
		if not callable(stop):
			return
		handlers = getattr(self.eventbus, 'handlers', None)
		has_handlers = any(handlers.values()) if isinstance(handlers, dict) else True
		try:
			result = stop(timeout=3.0, clear=not has_handlers)
		except TypeError:
			result = stop(timeout=3.0)
		if inspect.isawaitable(result):
			await result
		self._eventbus_stopped = True

	async def _finalize_run_cleanup(self) -> None:
		"""Mirror Browser Use run cleanup ordering."""
		self._unregister_run_signal_handler()
		await self._stop_eventbus_after_run()
		await self._close_browser_resources()
		await self._close_sdk_client_if_not_keep_alive()

	async def _finalize_exceptional_run(self, max_steps: int, agent_run_error: str) -> None:
		"""Mirror Browser Use run finalization for exceptions that escape Rust execution."""
		if not hasattr(self, '_task_start_time') or not hasattr(self, '_session_start_time'):
			self._initialize_run_lifecycle_state()
		await self._log_run_usage_summary()
		self._record_laminar_run_observability(
			max_steps=max_steps,
			duration_seconds=None,
			process_error=agent_run_error,
		)
		self._record_run_telemetry(max_steps=max_steps, agent_run_error=agent_run_error)
		self._dispatch_run_update_event()
		self._log_final_outcome_messages()
		await self._finalize_run_cleanup()

	def _initialize_run_lifecycle_state(self) -> None:
		"""Initialize Browser Use run timing and session state."""
		self._session_start_time = time.time()
		self._task_start_time = self._session_start_time
		self._dispatch_run_start_events()

	def _log_action(self, action, action_name: str, action_num: int, total_actions: int) -> None:
		"""Log an action before execution with Browser Use-style structure."""
		action_header = f'[{action_num}/{total_actions}] {action_name}:' if total_actions > 1 else f'{action_name}:'
		action_data = action.model_dump(exclude_unset=True)
		params = action_data.get(action_name, {}) if isinstance(action_data, dict) else {}
		param_parts = []
		if isinstance(params, dict):
			for param_name, value in params.items():
				if isinstance(value, str) and len(value) > 150:
					display_value = value[:150] + '...'
				elif isinstance(value, list) and len(str(value)) > 200:
					display_value = str(value)[:200] + '...'
				else:
					display_value = value
				param_parts.append(f'{param_name}: {display_value}')
		if param_parts:
			self.logger.info(f'  {action_header} {", ".join(param_parts)}')
		else:
			self.logger.info(f'  {action_header}')

	@observe(name='agent.run', ignore_input=True, ignore_output=True)
	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		self.laminar_trace_id = _laminar_current_trace_id()
		self._register_run_signal_handler(max_steps)
		try:
			return await self._run_terminal(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end)
		except asyncio.CancelledError:
			await self._finalize_exceptional_run(max_steps=max_steps, agent_run_error='CancelledError')
			raise
		except KeyboardInterrupt:
			self.logger.debug('Got KeyboardInterrupt during execution, returning current history')
			await self._finalize_exceptional_run(max_steps=max_steps, agent_run_error='KeyboardInterrupt')
			return self.history
		except Exception as exc:
			self.logger.error(f'Agent run failed with exception: {exc}', exc_info=True)
			await self._finalize_exceptional_run(max_steps=max_steps, agent_run_error=str(exc))
			raise

	async def _run_terminal(
		self,
		max_steps: int,
		on_step_start: AgentHookFunc | None,
		on_step_end: AgentHookFunc | None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		await self._log_agent_run()
		self._log_agent_setup()
		self._initialize_run_lifecycle_state()
		self._log_first_step_startup()
		started = time.time()
		if await self._should_stop_before_run():
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Beta agent stopped before terminal run.',
			)
			self.history = self.result
			await self._apply_terminal_usage_costs([])
			await self._log_run_usage_summary()
			self._record_laminar_run_observability(
				max_steps=max_steps,
				duration_seconds=finished - started,
				process_error='Beta agent stopped before terminal run.',
			)
			self._record_run_telemetry(max_steps=max_steps, agent_run_error='Beta agent stopped before terminal run.')
			self._dispatch_run_update_event()
			self._log_final_outcome_messages()
			await self._finalize_run_cleanup()
			return self.history
		if self.state.paused:
			self.logger.debug('Agent paused before Rust terminal run, waiting to resume...')
			await self._external_pause_event.wait()
			signal_handler = getattr(self, '_run_signal_handler', None)
			reset = getattr(signal_handler, 'reset', None)
			if callable(reset):
				reset()
			if await self._should_stop_before_run():
				finished = time.time()
				self.result = _history_from_events(
					[],
					model=self.model,
					started=started,
					finished=finished,
					output_model_schema=self.output_model_schema,
					process_error='Beta agent stopped before terminal run.',
				)
				self.history = self.result
				await self._apply_terminal_usage_costs([])
				await self._log_run_usage_summary()
				self._record_laminar_run_observability(
					max_steps=max_steps,
					duration_seconds=finished - started,
					process_error='Beta agent stopped before terminal run.',
				)
				self._record_run_telemetry(max_steps=max_steps, agent_run_error='Beta agent stopped before terminal run.')
				self._dispatch_run_update_event()
				self._log_final_outcome_messages()
				await self._finalize_run_cleanup()
				return self.history

		prefix_start = len(self.history.history)
		await self._execute_initial_actions(allow_terminal_run=False)
		if len(self.history.history) > prefix_start:
			self._pending_history_prefix = list(self.history.history[prefix_start:])
		await self._call_callback(on_step_start, self)
		self._log_main_execution_start(max_steps)
		followup = bool(self.state.follow_up_task and self._sdk_agent_id)
		task = self.task
		if not followup:
			task = _task_with_completed_initial_navigation_context(
				task,
				self._completed_initial_navigation_urls,
				self.initial_action_payloads,
				self._completed_initial_navigation_states,
			)
		self.state.follow_up_task = False
		return await self._run_sdk_agent(
			task=task,
			max_steps=max_steps,
			started=started,
			on_step_end=on_step_end,
			source='follow_up' if followup else 'run',
			followups=[task] if followup else None,
		)

	async def follow_up(
		self,
		task: str,
		max_steps: int | None = None,
		*,
		step_timeout: int | None = None,
		enqueue_timeout: int | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		if not self.terminal_session_id or not self._sdk_agent_id:
			raise BetaAgentError('No active Rust session. Call run() before follow_up().')
		resolved_max_steps = max_steps if max_steps is not None else self.kwargs.get('max_steps', 100)
		self.add_new_task(task)
		self.state.follow_up_task = False
		self._register_run_signal_handler(resolved_max_steps)
		try:
			return await self._follow_up_terminal(
				self.task,
				max_steps=max_steps,
				resolved_max_steps=resolved_max_steps,
				step_timeout=step_timeout,
				enqueue_timeout=enqueue_timeout,
			)
		except asyncio.CancelledError:
			await self._finalize_exceptional_run(max_steps=resolved_max_steps, agent_run_error='CancelledError')
			raise
		except KeyboardInterrupt:
			self.logger.debug('Got KeyboardInterrupt during execution, returning current history')
			await self._finalize_exceptional_run(max_steps=resolved_max_steps, agent_run_error='KeyboardInterrupt')
			return self.history
		except Exception as exc:
			self.logger.error(f'Agent follow-up failed with exception: {exc}', exc_info=True)
			await self._finalize_exceptional_run(max_steps=resolved_max_steps, agent_run_error=str(exc))
			raise

	async def _follow_up_terminal(
		self,
		task: str,
		max_steps: int | None,
		resolved_max_steps: int,
		initialize_lifecycle: bool = True,
		on_step_end: AgentHookFunc | None = None,
		step_timeout: int | None = None,
		enqueue_timeout: int | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		if initialize_lifecycle:
			self._initialize_run_lifecycle_state()
		started = time.time()
		return await self._run_sdk_agent(
			task=task,
			max_steps=resolved_max_steps,
			started=started,
			on_step_end=on_step_end,
			source='follow_up',
			followups=[task],
			step_timeout=step_timeout,
			enqueue_timeout=enqueue_timeout,
		)

	async def _run_sdk_agent(
		self,
		*,
		task: str,
		max_steps: int,
		started: float,
		on_step_end: AgentHookFunc | None,
		source: str,
		followups: list[str] | None = None,
		step_timeout: int | None = None,
		enqueue_timeout: int | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		events: list[dict[str, Any]] = []
		process_error: str | None = None
		result: Any = None
		sdk = await self._ensure_sdk_client()
		_ = step_timeout, enqueue_timeout
		method = 'agent.run' if self._sdk_agent_id or followups else 'agent.run_task'
		params = self._sdk_run_params(max_steps=max_steps, task=task, followups=followups)
		self._active_sdk_run_id = self.terminal_session_id or self._sdk_agent_id
		progress_task: asyncio.Task[Any] | None = None
		self.logger.info(
			'Rust SDK %s starting: max_steps=%s browser_mode=%s browser_id=%s llm_timeout=%s',
			method,
			params.get('max_steps'),
			params.get('browser_mode'),
			params.get('browser_id') or '<new>',
			params.get('llm', {}).get('timeout'),
		)
		if hasattr(sdk, 'notification_queue'):
			progress_task = asyncio.create_task(self._log_sdk_progress(sdk))
		try:
			result = await sdk.call(method, params)
		except asyncio.CancelledError:
			await self._preserve_sdk_notification_history(
				sdk,
				started=started,
				process_error='CancelledError',
			)
			await self._cancel_active_sdk_run()
			raise
		except Exception as exc:
			process_error = str(exc) or exc.__class__.__name__
		finally:
			if progress_task is not None:
				progress_task.cancel()
				with suppress(asyncio.CancelledError):
					await progress_task
			self._active_sdk_run_id = None
		finished = time.time()
		self.last_stdout = str(getattr(sdk, 'stdout_text', '') or '')
		self.last_stderr = str(getattr(sdk, 'stderr_text', '') or '\n'.join(line for line in sdk.stderr_lines if line))
		notification_events = _sdk_notification_events(sdk)
		child_events: list[dict[str, Any]] = []
		usage_events: list[dict[str, Any]] = []
		response_usage_event: dict[str, Any] | None = None
		if isinstance(result, dict):
			agent_id = result.get('agent_id')
			session_id = result.get('session_id')
			browser_id = result.get('browser_id')
			if isinstance(agent_id, str) and agent_id:
				self._sdk_agent_id = agent_id
			if isinstance(session_id, str) and session_id:
				self.terminal_session_id = session_id
			if isinstance(browser_id, str) and browser_id:
				self._sdk_browser_id = browser_id
			history_payload = result.get('history')
			if isinstance(history_payload, dict):
				raw_events = history_payload.get('events')
				if isinstance(raw_events, list):
					events = _dedupe_sdk_events([event for event in raw_events if isinstance(event, dict)])
					errors = history_payload.get('errors')
					if process_error is None and history_payload.get('success') is False and isinstance(errors, list) and errors:
						process_error = '\n'.join(str(error) for error in errors if error)
				raw_child_events = history_payload.get('child_events')
				if isinstance(raw_child_events, list):
					child_events = _dedupe_sdk_events([event for event in raw_child_events if isinstance(event, dict)])
				raw_usage_events = history_payload.get('usage_events')
				if isinstance(raw_usage_events, list):
					usage_events = _dedupe_sdk_events([event for event in raw_usage_events if isinstance(event, dict)])
				response_usage_event = _usage_event_from_sdk_history_usage(history_payload.get('usage'))
		elif process_error is None:
			process_error = 'Rust SDK server returned an invalid response.'
		events_result = _result_from_events(events)
		notification_result = _result_from_events(notification_events)
		used_notification_events = False
		if notification_events and (
			not events
			or _sdk_events_truncated_for_transport(events)
			or len(notification_events) > len(events)
			or (notification_result is not None and events_result is None)
		):
			events = notification_events
			child_events = []
			usage_events = notification_events
			events_result = notification_result
			used_notification_events = True
		if not usage_events:
			usage_events = [*events, *child_events]
		if response_usage_event is not None:
			current_usage = _usage_from_events(usage_events, self.model)
			response_usage = _usage_from_events([response_usage_event], self.model)
			if _usage_tokens(response_usage) > _usage_tokens(current_usage):
				usage_events = [response_usage_event]
		if self.logger.isEnabledFor(logging.INFO):
			self.logger.info(
				'Rust SDK reconstructed history: response_events=%s notification_events=%s usage_events=%s final_from=%s usage_tokens=%s',
				len(events),
				len(notification_events),
				len(usage_events),
				'events' if events_result is not None else 'none',
				_usage_tokens(_usage_from_events(usage_events, self.model)),
			)
		if events_result is not None and (
			process_error == 'CancelledError' or _sdk_transport_error_after_final_result(process_error)
		):
			process_error = None
		if used_notification_events and events_result is not None:
			process_error = None
		self.last_events = events
		self.last_child_events = child_events
		self.last_usage_events = usage_events
		self.last_observability_events = usage_events
		self.result = _history_from_events(
			self.last_events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		if self._pending_history_prefix:
			self.result.history = [*self._pending_history_prefix, *self.result.history]
			self._pending_history_prefix = []
		self.history = self.result
		await self._apply_terminal_usage_costs(self.last_usage_events)
		self._sync_state_from_history()
		await self._log_run_usage_summary()
		self._record_laminar_run_observability(
			max_steps=max_steps,
			duration_seconds=finished - started,
			process_error=process_error,
		)
		self._record_run_telemetry(max_steps=max_steps, agent_run_error=process_error)
		self._dispatch_run_update_event()
		await self._check_and_update_downloads(source)
		await self._save_conversation_if_requested()
		await self._call_new_step_callback()
		await self._call_step_end_callbacks(on_step_end)
		await self._call_done_callback()
		await self._generate_gif_if_requested()
		self._log_final_outcome_messages()
		await self._finalize_run_cleanup()
		return self.history

	async def _preserve_sdk_notification_history(
		self,
		sdk: Any,
		*,
		started: float,
		process_error: str,
	) -> None:
		events = _sdk_notification_events(sdk)
		if not events:
			return
		finished = time.time()
		self.last_stdout = str(getattr(sdk, 'stdout_text', '') or '')
		self.last_stderr = str(
			getattr(sdk, 'stderr_text', '') or '\n'.join(line for line in getattr(sdk, 'stderr_lines', []) if line)
		)
		effective_error = process_error
		if _result_from_events(events) is not None and (
			process_error == 'CancelledError' or _sdk_transport_error_after_final_result(process_error)
		):
			effective_error = None
		self.last_events = events
		self.last_child_events = []
		self.last_usage_events = events
		self.last_observability_events = events
		self.result = _history_from_events(
			self.last_events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=effective_error,
		)
		if self._pending_history_prefix:
			self.result.history = [*self._pending_history_prefix, *self.result.history]
			self._pending_history_prefix = []
		self.history = self.result
		await self._apply_terminal_usage_costs(self.last_usage_events)
		self._sync_state_from_history()

	async def _log_sdk_progress(self, sdk: RustSdkClient) -> None:
		logged = 0
		last_summary: str | None = None
		last_logged_at = 0.0
		while True:
			notification = await sdk.notification_queue.get()
			summary = _sdk_notification_summary(notification)
			if not summary:
				continue
			now = time.time()
			if summary == last_summary and now - last_logged_at < 30:
				continue
			last_summary = summary
			last_logged_at = now
			logged += 1
			self.logger.info('Rust SDK event %s: %s', logged, summary)

	follow_up_task = follow_up

	@property
	def usage(self) -> UsageSummary | None:
		return self.history.usage

	@property
	def logger(self) -> logging.Logger:
		browser_session_id = getattr(self.browser_session, 'id', '----') or '----'
		target_id = '--'
		agent_focus = getattr(self.browser_session, 'agent_focus', None)
		focus_target_id = getattr(agent_focus, 'target_id', None)
		if isinstance(focus_target_id, str) and focus_target_id:
			target_id = focus_target_id[-2:]
		return logging.getLogger(f'browser_use.Agent🅰 {self.task_id[-4:]} ⇢ 🅑 {str(browser_session_id)[-4:]} 🅣 {target_id}')

	@property
	def browser_profile(self) -> Any:
		session_profile = getattr(self.browser_session, 'browser_profile', None)
		return session_profile if session_profile is not None else self._browser_profile

	@property
	def message_manager(self) -> MessageManager:
		return self._message_manager

	def _enhance_task_with_schema(self, task: str, output_model_schema: type[AgentStructuredOutput] | None) -> str:
		"""Enhance task description with Browser Use-style output schema information."""
		if output_model_schema is None:
			return task
		try:
			schema_json = json.dumps(output_model_schema.model_json_schema(), indent=2)
			return f'{task}\nExpected output format: {output_model_schema.__name__}\n{schema_json}'
		except Exception as exc:
			self.logger.debug(f'Could not parse output schema: {exc}')
			return task

	def _extract_start_url(self, task: str) -> str | None:
		"""Extract Browser Use-style direct startup URL from a task string."""
		return _extract_start_url(task)

	def _remove_think_tags(self, text: str) -> str:
		think_tags = re.compile(r'<think>.*?</think>', re.DOTALL)
		stray_close_tag = re.compile(r'.*?</think>', re.DOTALL)
		text = re.sub(think_tags, '', text)
		text = re.sub(stray_close_tag, '', text)
		return text.strip()

	def _replace_urls_in_text(self, text: str) -> tuple[str, dict[str, str]]:
		"""Replace long URL query/fragment tails with shorter reversible forms."""
		replaced_urls: dict[str, str] = {}

		def replace_url(match: re.Match) -> str:
			original_url = match.group(0)
			query_start = original_url.find('?')
			fragment_start = original_url.find('#')
			after_path_start = len(original_url)
			if query_start != -1:
				after_path_start = min(after_path_start, query_start)
			if fragment_start != -1:
				after_path_start = min(after_path_start, fragment_start)

			base_url = original_url[:after_path_start]
			after_path = original_url[after_path_start:]
			if len(after_path) <= self._url_shortening_limit:
				return original_url
			if not after_path:
				return original_url

			truncated = after_path[: self._url_shortening_limit]
			short_hash = hashlib.md5(after_path.encode('utf-8')).hexdigest()[:7]
			shortened = f'{base_url}{truncated}...{short_hash}'
			if len(shortened) < len(original_url):
				replaced_urls[shortened] = original_url
				return shortened
			return original_url

		return URL_PATTERN.sub(replace_url, text), replaced_urls

	def _process_messsages_and_replace_long_urls_shorter_ones(self, input_messages: list[BaseMessage]) -> dict[str, str]:
		"""Replace long URLs in Browser Use LLM messages in place."""
		from browser_use.llm.messages import AssistantMessage, ContentPartTextParam, UserMessage

		urls_replaced: dict[str, str] = {}
		for message in input_messages:
			if not isinstance(message, (UserMessage, AssistantMessage)):
				continue
			if isinstance(message.content, str):
				message.content, replaced_urls = self._replace_urls_in_text(message.content)
				urls_replaced.update(replaced_urls)
			elif isinstance(message.content, list):
				for part in message.content:
					if isinstance(part, ContentPartTextParam):
						part.text, replaced_urls = self._replace_urls_in_text(part.text)
						urls_replaced.update(replaced_urls)
		return urls_replaced

	@staticmethod
	def _recursive_process_all_strings_inside_pydantic_model(model: BaseModel, url_replacements: dict[str, str]) -> None:
		"""Replace shortened URLs with originals inside a Pydantic model in place."""
		for field_name, field_value in model.__dict__.items():
			if isinstance(field_value, str):
				setattr(model, field_name, Agent._replace_shortened_urls_in_string(field_value, url_replacements))
			elif isinstance(field_value, BaseModel):
				Agent._recursive_process_all_strings_inside_pydantic_model(field_value, url_replacements)
			elif isinstance(field_value, dict):
				Agent._recursive_process_dict(field_value, url_replacements)
			elif isinstance(field_value, (list, tuple)):
				setattr(model, field_name, Agent._recursive_process_list_or_tuple(field_value, url_replacements))

	@staticmethod
	def _recursive_process_dict(dictionary: dict, url_replacements: dict[str, str]) -> None:
		for key, value in dictionary.items():
			if isinstance(value, str):
				dictionary[key] = Agent._replace_shortened_urls_in_string(value, url_replacements)
			elif isinstance(value, BaseModel):
				Agent._recursive_process_all_strings_inside_pydantic_model(value, url_replacements)
			elif isinstance(value, dict):
				Agent._recursive_process_dict(value, url_replacements)
			elif isinstance(value, (list, tuple)):
				dictionary[key] = Agent._recursive_process_list_or_tuple(value, url_replacements)

	@staticmethod
	def _recursive_process_list_or_tuple(container: list | tuple, url_replacements: dict[str, str]) -> list | tuple:
		if isinstance(container, tuple):
			processed_items = []
			for item in container:
				if isinstance(item, str):
					processed_items.append(Agent._replace_shortened_urls_in_string(item, url_replacements))
				elif isinstance(item, BaseModel):
					Agent._recursive_process_all_strings_inside_pydantic_model(item, url_replacements)
					processed_items.append(item)
				elif isinstance(item, dict):
					Agent._recursive_process_dict(item, url_replacements)
					processed_items.append(item)
				elif isinstance(item, (list, tuple)):
					processed_items.append(Agent._recursive_process_list_or_tuple(item, url_replacements))
				else:
					processed_items.append(item)
			return tuple(processed_items)
		for index, item in enumerate(container):
			if isinstance(item, str):
				container[index] = Agent._replace_shortened_urls_in_string(item, url_replacements)
			elif isinstance(item, BaseModel):
				Agent._recursive_process_all_strings_inside_pydantic_model(item, url_replacements)
			elif isinstance(item, dict):
				Agent._recursive_process_dict(item, url_replacements)
			elif isinstance(item, (list, tuple)):
				container[index] = Agent._recursive_process_list_or_tuple(item, url_replacements)
		return container

	@staticmethod
	def _replace_shortened_urls_in_string(text: str, url_replacements: dict[str, str]) -> str:
		result = text
		for shortened_url, original_url in url_replacements.items():
			result = result.replace(shortened_url, original_url)
		return result

	def _setup_action_models(self) -> None:
		"""Expose Browser Use-style action model classes from the configured tools."""
		self._setup_action_models_for_page(page_url=None)

	def _setup_action_models_for_page(self, page_url: str | None) -> None:
		"""Create action model classes, optionally filtered for a specific page."""
		registry = getattr(self.tools, 'registry', None)
		create_action_model = getattr(registry, 'create_action_model', None)
		if not callable(create_action_model):
			self.ActionModel = None
			self.DoneActionModel = None
			self.AgentOutput = AgentOutput
			return
		self.ActionModel = create_action_model(page_url=page_url)
		if self.settings.flash_mode:
			self.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.ActionModel)
		elif self.settings.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)
		self.DoneActionModel = create_action_model(include_actions=['done'], page_url=page_url)
		if self.settings.flash_mode:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_flash_mode(self.DoneActionModel)
		elif self.settings.use_thinking:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions(self.DoneActionModel)
		else:
			self.DoneAgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.DoneActionModel)

	async def _update_action_models_for_page(self, page_url: str) -> None:
		"""Update Browser Use-style action model classes for page-filtered tools."""
		self._setup_action_models_for_page(page_url)

	def _convert_initial_actions(self, actions: list[dict[str, dict[str, Any]]]) -> list[ActionModel]:
		"""Convert dictionary initial actions to Browser Use action model instances when possible."""
		converted_actions: list[Any] = []
		registry = getattr(getattr(self.tools, 'registry', None), 'registry', None)
		registry_actions = getattr(registry, 'actions', {})
		action_model = getattr(self, 'ActionModel', None)
		if action_model is None:
			return list(actions)
		for action_dict in actions:
			if not isinstance(action_dict, dict) or not action_dict:
				converted_actions.append(action_dict)
				continue
			action_name = next(iter(action_dict))
			params = action_dict[action_name]
			normalized_name, normalized_params = _normalize_initial_action(action_name, params)
			action_info = registry_actions.get(normalized_name)
			if action_info is None:
				converted_actions.append(action_dict)
				continue
			try:
				validated_params = action_info.param_model(**(normalized_params if isinstance(normalized_params, dict) else {}))
				converted_actions.append(action_model(**{normalized_name: validated_params}))
			except (TypeError, ValueError, ValidationError):
				converted_actions.append(action_dict)
		return converted_actions

	async def _check_and_update_downloads(self, context: str = '') -> None:
		"""Mirror Browser Use's downloaded-file tracking for supplied sessions."""
		if not self.has_downloads_path or self.browser_session is None:
			return
		try:
			current_downloads = getattr(self.browser_session, 'downloaded_files', None)
			if callable(current_downloads):
				current_downloads = current_downloads()
			if inspect.isawaitable(current_downloads):
				current_downloads = await current_downloads
			if not isinstance(current_downloads, list):
				return
			if current_downloads != self._last_known_downloads:
				self._update_available_file_paths(current_downloads)
				self._last_known_downloads = list(current_downloads)
		except Exception:
			_ = context

	def _update_available_file_paths(self, downloads: list[str]) -> None:
		"""Update available_file_paths with downloaded files, preserving caller order."""
		if not self.has_downloads_path:
			return
		current_files = list(self.available_file_paths or [])
		seen = set(current_files)
		for file_path in downloads:
			if not isinstance(file_path, str) or not file_path or file_path in seen:
				continue
			current_files.append(file_path)
			seen.add(file_path)
		self.available_file_paths = current_files

	def save_file_system_state(self) -> None:
		"""Save current Browser Use file system state back onto AgentState."""
		self.state.file_system_state = self.file_system.get_state()

	async def _prepare_context(self, step_info: AgentStepInfo | None = None) -> BrowserStateSummary:
		"""Prepare Browser Use step context from the configured browser session."""
		if self.browser_session is None:
			raise AssertionError('BrowserSession is not set up')
		get_state = getattr(self.browser_session, 'get_browser_state_summary', None)
		if not callable(get_state):
			raise ValueError('BrowserSession does not expose get_browser_state_summary')

		browser_state_summary = await get_state(
			include_screenshot=True,
			include_recent_events=self.include_recent_events,
		)
		await self._check_and_update_downloads(f'Step {self.state.n_steps}: after getting browser state')
		self._log_step_context(browser_state_summary)
		await self._check_stop_or_pause()
		await self._update_action_models_for_page(browser_state_summary.url)

		page_filtered_actions = None
		registry = getattr(getattr(self.tools, 'registry', None), 'get_prompt_description', None)
		if callable(registry):
			page_filtered_actions = registry(browser_state_summary.url)

		self._message_manager.create_state_messages(
			browser_state_summary=browser_state_summary,
			model_output=self.state.last_model_output,
			result=self.state.last_result,
			step_info=step_info,
			use_vision=self.settings.use_vision,
			page_filtered_actions=page_filtered_actions if page_filtered_actions else None,
			sensitive_data=self.sensitive_data,
			available_file_paths=self.available_file_paths,
		)

		await self._force_done_after_last_step(step_info)
		await self._force_done_after_failure()
		return browser_state_summary

	async def get_model_output(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get next Browser Use action output from the configured Python LLM."""
		if self.llm is None or not hasattr(self.llm, 'ainvoke'):
			raise ValueError('A Browser Use-compatible llm with ainvoke(...) is required for get_model_output().')

		urls_replaced = self._process_messsages_and_replace_long_urls_shorter_ones(input_messages)
		response = await self.llm.ainvoke(input_messages, output_format=self.AgentOutput)
		parsed: AgentOutput = getattr(response, 'completion', response)

		if urls_replaced:
			self._recursive_process_all_strings_inside_pydantic_model(parsed, urls_replaced)

		actions = getattr(parsed, 'action', None)
		if actions and len(actions) > self.settings.max_actions_per_step:
			parsed.action = actions[: self.settings.max_actions_per_step]

		if not (hasattr(self.state, 'paused') and (self.state.paused or self.state.stopped)):
			from browser_use.agent.service import log_response

			registry = getattr(getattr(self.tools, 'registry', None), 'registry', None)
			log_response(parsed, registry, self.logger)

		self._log_next_action_summary(parsed)
		return parsed

	async def _get_model_output_with_retry(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get model output, retrying once when the model returns no usable action."""
		model_output = await self.get_model_output(input_messages)
		action_count = len(model_output.action) if getattr(model_output, 'action', None) else 0
		self.logger.debug(f'✅ Step {self.state.n_steps}: Got LLM response with {action_count} actions')

		def has_empty_actions(output: AgentOutput) -> bool:
			actions = getattr(output, 'action', None)
			if not actions or not isinstance(actions, list):
				return True
			return all(getattr(action, 'model_dump', lambda **kwargs: {})() == {} for action in actions)

		if has_empty_actions(model_output):
			from browser_use.llm.messages import UserMessage

			self.logger.warning('Model returned empty action. Retrying...')
			clarification_message = UserMessage(
				content='You forgot to return an action. Please respond with a valid JSON action according to the expected schema with your assessment and next actions.'
			)
			model_output = await self.get_model_output(input_messages + [clarification_message])
			if has_empty_actions(model_output):
				self.logger.warning('Model still returned empty after retry. Inserting safe noop action.')
				try:
					done_action = self.DoneActionModel(done={'success': False, 'text': 'No next action returned by LLM!'})
				except Exception:
					done_action = self.ActionModel()
					setattr(done_action, 'done', {'success': False, 'text': 'No next action returned by LLM!'})
				model_output.action = [done_action]

		return model_output

	async def _handle_post_llm_processing(
		self,
		browser_state_summary: BrowserStateSummary,
		input_messages: list[BaseMessage],
	) -> None:
		"""Handle Browser Use callbacks and conversation saving after an LLM response."""
		if self.register_new_step_callback and self.state.last_model_output:
			if inspect.iscoroutinefunction(self.register_new_step_callback):
				await self.register_new_step_callback(
					browser_state_summary,
					self.state.last_model_output,
					self.state.n_steps,
				)
			else:
				self.register_new_step_callback(
					browser_state_summary,
					self.state.last_model_output,
					self.state.n_steps,
				)

		if self.settings.save_conversation_path and self.state.last_model_output:
			conversation_dir = Path(self.settings.save_conversation_path)
			conversation_filename = f'conversation_{self.id}_{self.state.n_steps}.txt'
			target = conversation_dir / conversation_filename
			await save_conversation(
				input_messages,
				self.state.last_model_output,
				target,
				self.settings.save_conversation_path_encoding,
			)

	async def _get_next_action(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Fetch the next model output and run Browser Use post-LLM hooks."""
		input_messages = self._message_manager.get_messages()
		try:
			model_output = await asyncio.wait_for(
				self._get_model_output_with_retry(input_messages), timeout=self.settings.llm_timeout
			)
		except TimeoutError:
			raise TimeoutError(
				f'LLM call timed out after {self.settings.llm_timeout} seconds. Keep your thinking and output short.'
			)

		self.state.last_model_output = model_output
		await self._check_stop_or_pause()
		await self._handle_post_llm_processing(browser_state_summary, input_messages)
		await self._check_stop_or_pause()

	async def _execute_actions(self) -> None:
		"""Execute actions from the last model output through the Rust-backed action path."""
		if self.state.last_model_output is None:
			raise ValueError('No model output to execute actions from')
		self.state.last_result = await self.multi_act(self.state.last_model_output.action)

	async def _make_history_item(
		self,
		model_output: AgentOutput | None,
		browser_state_summary: BrowserStateSummary,
		result: list[ActionResult],
		metadata: StepMetadata | None = None,
		state_message: str | None = None,
	) -> None:
		"""Create and store a Browser Use history item from a browser-state summary."""
		if model_output:
			selector_map = getattr(getattr(browser_state_summary, 'dom_state', None), 'selector_map', {})
			interacted_elements = AgentHistory.get_interacted_element(model_output, selector_map)
		else:
			interacted_elements = [None]

		screenshot_path = None
		screenshot = getattr(browser_state_summary, 'screenshot', None)
		if screenshot:
			screenshot_path = await self.screenshot_service.store_screenshot(screenshot, self.state.n_steps)

		state_history = BrowserStateHistory(
			url=getattr(browser_state_summary, 'url', ''),
			title=getattr(browser_state_summary, 'title', ''),
			tabs=getattr(browser_state_summary, 'tabs', []),
			interacted_element=interacted_elements,
			screenshot_path=screenshot_path,
		)
		self.history.add_item(
			AgentHistory(
				model_output=model_output,
				result=result,
				state=state_history,
				metadata=metadata,
				state_message=state_message,
			)
		)

	async def _post_process(self) -> None:
		"""Handle Browser Use-style post-action bookkeeping."""
		await self._check_and_update_downloads('after executing actions')
		if self.state.last_result and len(self.state.last_result) == 1 and self.state.last_result[-1].error:
			self.state.consecutive_failures += 1
			self.logger.debug(f'🔄 Step {self.state.n_steps}: Consecutive failures: {self.state.consecutive_failures}')
			return
		if self.state.consecutive_failures > 0:
			self.state.consecutive_failures = 0
			self.logger.debug(f'🔄 Step {self.state.n_steps}: Consecutive failures reset to: {self.state.consecutive_failures}')
		if self.state.last_result and self.state.last_result[-1].is_done:
			success = self.state.last_result[-1].success
			if success:
				self.logger.info(f'\n📄 \033[32m Final Result:\033[0m \n{self.state.last_result[-1].extracted_content}\n\n')
			else:
				self.logger.info(f'\n📄 \033[31m Final Result:\033[0m \n{self.state.last_result[-1].extracted_content}\n\n')
			if self.state.last_result[-1].attachments:
				total_attachments = len(self.state.last_result[-1].attachments)
				for index, file_path in enumerate(self.state.last_result[-1].attachments):
					self.logger.info(f'👉 Attachment {index + 1 if total_attachments > 1 else ""}: {file_path}')

	async def _handle_step_error(self, error: Exception) -> None:
		"""Convert a step exception into Browser Use-style state.last_result."""
		if isinstance(error, InterruptedError):
			self.logger.error('The agent was interrupted mid-step' + (f' - {error}' if str(error) else ''))
			return
		include_trace = self.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		prefix = f'❌ Result failed {self.state.consecutive_failures + 1}/{self.settings.max_failures + int(self.settings.final_response_after_failure)} times:\n '
		self.state.consecutive_failures += 1
		if 'Could not parse response' in error_msg or 'tool_use_failed' in error_msg:
			logger.error(f'Model: {getattr(self.llm, "model", None)} failed')
			logger.error(f'{prefix}{error_msg}')
		else:
			self.logger.error(f'{prefix}{error_msg}')
		self.state.last_result = [ActionResult(error=error_msg)]

	async def _finalize(self, browser_state_summary: BrowserStateSummary | None) -> None:
		"""Finalize one Browser Use-style step after Rust-backed helper execution."""
		step_end_time = time.time()
		if not self.state.last_result:
			return
		step_start_time = getattr(self, 'step_start_time', step_end_time)
		step_event = None
		if browser_state_summary is not None:
			metadata = StepMetadata(
				step_number=self.state.n_steps,
				step_start_time=step_start_time,
				step_end_time=step_end_time,
			)
			state_message = getattr(self._message_manager, 'last_state_message_text', None)
			await self._make_history_item(
				self.state.last_model_output,
				browser_state_summary,
				self.state.last_result,
				metadata,
				state_message=state_message,
			)
			if self.state.last_model_output:
				actions_data = []
				for action in self.state.last_model_output.action or []:
					action_dict = action.model_dump() if hasattr(action, 'model_dump') else {}
					actions_data.append(action_dict)
				step_event = CreateAgentStepEvent.from_agent_step(
					self,
					self.state.last_model_output,
					self.state.last_result,
					actions_data,
					browser_state_summary,
				)
		self._log_step_completion_summary(step_start_time, self.state.last_result)
		self.save_file_system_state()
		if step_event is not None:
			self.eventbus.dispatch(step_event)
		self.state.n_steps += 1

	async def _force_done_after_last_step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Switch to done-only output on the last configured step."""
		if not (step_info and step_info.is_last_step()):
			return
		from browser_use.llm.messages import UserMessage

		msg = 'You reached max_steps - this is your last step. Your only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
		msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
		msg += '\nInclude everything you found out for the ultimate task in the done text.'
		self.logger.debug('Last step finishing up')
		self._message_manager._add_context_message(UserMessage(content=msg))
		self.AgentOutput = self.DoneAgentOutput

	async def _force_done_after_failure(self) -> None:
		"""Switch to done-only output after max failures when final response is enabled."""
		if self.state.consecutive_failures < self.settings.max_failures or not self.settings.final_response_after_failure:
			return
		from browser_use.llm.messages import UserMessage

		msg = f'You failed {self.settings.max_failures} times. Therefore we terminate the agent.'
		msg += '\nYour only tool available is the "done" tool. No other tool is available. All other tools which you see in history or examples are not available.'
		msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed. Else success to true.'
		msg += '\nInclude everything you found out for the ultimate task in the done text.'
		self.logger.debug('Force done action, because we reached max_failures.')
		self._message_manager._add_context_message(UserMessage(content=msg))
		self.AgentOutput = self.DoneAgentOutput

	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one Browser Use-style step through the Rust terminal core."""
		await self.take_step(step_info)

	async def take_step(self, step_info: AgentStepInfo | None = None) -> tuple[bool, bool]:
		"""Take one Rust terminal turn and return Browser Use-style step status."""
		if step_info is not None:
			self.state.n_steps = max(self.state.n_steps, step_info.step_number)
			if step_info.step_number == 0:
				try:
					await self._execute_initial_actions()
				except InterruptedError:
					pass
		history = await self.run(max_steps=1)
		if history.is_done():
			return True, True
		return False, False

	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
		"""Execute Browser Use action models through the Rust-backed session.

		The Rust terminal owns browser actions, so non-`done` action batches are
		serialized as a follow-up instruction for the active Rust session. A
		standalone `done` action preserves Browser Use's local completion semantics.
		"""
		payloads = []
		total_actions = len(actions)
		for index, action in enumerate(actions):
			payload = _action_payload(action)
			if index > 0 and payload.get('done') is not None:
				self.logger.debug(
					f'Done action is allowed only as a single action - stopped after action {index} / {total_actions}.'
				)
				break
			payloads.append(payload)
			if payload.get('done') is not None:
				break
		if not payloads:
			return []
		if len(payloads) == 1:
			done_result = _done_action_result(payloads[0])
			if done_result is not None:
				return [done_result]
		instruction = _actions_instruction(payloads)
		max_steps = max(1, len(payloads))
		if self.terminal_session_id:
			history = await self.follow_up(instruction, max_steps=max_steps)
			return history.action_results()
		original_task = self.task
		self.task = f'{self.task}\n\n{instruction}'
		try:
			history = await self.run(max_steps=max_steps)
		finally:
			self.task = original_task
		return history.action_results()

	async def _execute_initial_actions(self, *, allow_terminal_run: bool = True) -> None:
		"""Execute configured Browser Use initial actions through the Rust-backed action path."""
		if not self.initial_actions or self.state.follow_up_task or self._initial_actions_executed:
			return
		self.logger.debug(f'⚡ Executing {len(self.initial_actions)} initial actions...')
		result = await self._execute_direct_initial_navigation_actions()
		if result is None:
			if not allow_terminal_run:
				self.logger.debug('Initial actions left for Rust task context; direct CDP navigation was not available')
				return
			result = await self.multi_act(self.initial_actions)
		self._initial_actions_executed = True
		if result and self.initial_url and result[0].long_term_memory:
			result[0].long_term_memory = f'Found initial url and automatically loaded it. {result[0].long_term_memory}'
		self.state.last_result = result

		if self.settings.flash_mode:
			model_output = self.AgentOutput(
				evaluation_previous_goal=None,
				memory='Initial navigation',
				next_goal=None,
				action=self.initial_actions,
			)
		else:
			model_output = self.AgentOutput(
				evaluation_previous_goal='Start',
				memory=None,
				next_goal='Initial navigation',
				action=self.initial_actions,
			)

		metadata = StepMetadata(
			step_number=0,
			step_start_time=time.time(),
			step_end_time=time.time(),
		)
		initial_state_context = self._completed_initial_navigation_states[-1] if self._completed_initial_navigation_states else {}
		initial_state_url = str(initial_state_context.get('url') or self.initial_url or '')
		initial_state_title = str(initial_state_context.get('title') or 'Initial Actions')
		initial_state_tabs = []
		for index, tab in enumerate(initial_state_context.get('tabs') or []):
			if not isinstance(tab, dict):
				continue
			tab_url = str(tab.get('url') or '')
			if not tab_url:
				continue
			initial_state_tabs.append(TabInfo(url=tab_url, title=str(tab.get('title') or ''), target_id=f'initial-tab-{index}'))
		state_history = BrowserStateHistory(
			url=initial_state_url,
			title=initial_state_title,
			tabs=initial_state_tabs,
			interacted_element=[None] * len(self.initial_actions),
			screenshot_path=None,
		)
		self.history.add_item(
			AgentHistory(
				model_output=model_output,
				result=result,
				state=state_history,
				metadata=metadata,
			)
		)
		self.logger.debug('📝 Saved initial actions to history as step 0')
		self.logger.debug('Initial actions completed')

	async def _execute_direct_initial_navigation_actions(self) -> list[ActionResult] | None:
		"""Pre-navigate existing CDP-backed browser sessions before the Beta agent starts."""
		self._completed_initial_navigation_urls = []
		self._completed_initial_navigation_states = []
		if not _direct_initial_navigation_enabled():
			return None
		if self.browser_session is None:
			return None
		if not (_extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile)):
			return None
		navigate_to = getattr(self.browser_session, 'navigate_to', None)
		if not callable(navigate_to):
			return None
		payloads = [_action_payload(action) for action in self.initial_actions or []]
		nav_actions = [_initial_navigation_params_from_action(payload) for payload in payloads]
		if not nav_actions or any(action is None for action in nav_actions):
			return None
		results: list[ActionResult] = []
		for url, new_tab in nav_actions:
			try:
				await navigate_to(url, new_tab=new_tab)
			except Exception as exc:
				message = f'Initial navigation to {url} failed: {exc}'
				self.logger.warning(message)
				results.append(ActionResult(error=message))
				continue
			state = await self._capture_direct_initial_navigation_state(url)
			if not self._direct_initial_navigation_state_matches(url, getattr(state, 'url', '') if state else None):
				observed_url = getattr(state, 'url', None) if state else None
				self.logger.warning(
					'Initial navigation to %s was not confirmed by browser state; observed %s. '
					'Leaving navigation in the Rust task context.',
					url,
					observed_url or '<unknown>',
				)
				self._completed_initial_navigation_urls = []
				self._completed_initial_navigation_states = []
				return None
			state_context = self._direct_initial_navigation_state_context(url, state)
			text = f'Navigated to {url}'
			current_url = state_context.get('url')
			title = state_context.get('title')
			if current_url or title:
				text += f'. Current page: {current_url or url}'
				if title:
					text += f' ({title})'
			self._completed_initial_navigation_urls.append(url)
			self._completed_initial_navigation_states.append(state_context)
			results.append(ActionResult(extracted_content=text, long_term_memory=text))
		return results

	async def _capture_direct_initial_navigation_state(
		self, requested_url: str, *, timeout_seconds: float = 7.0
	) -> BrowserStateSummary | None:
		if self.browser_session is None:
			return None
		get_state = getattr(self.browser_session, 'get_browser_state_summary', None)
		if not callable(get_state):
			return None
		deadline = time.monotonic() + max(0.0, timeout_seconds)
		last_state: BrowserStateSummary | None = None
		while True:
			try:
				state = await get_state(include_screenshot=False)
			except Exception as exc:
				self.logger.debug(f'Initial navigation state probe failed: {exc}')
				state = None
			if state is not None:
				last_state = state
				if self._direct_initial_navigation_state_matches(requested_url, getattr(state, 'url', '')):
					return state
			if time.monotonic() >= deadline:
				return last_state
			await asyncio.sleep(0.25)

	@staticmethod
	def _direct_initial_navigation_state_matches(requested_url: str, current_url: str | None) -> bool:
		current = str(current_url or '')
		requested = str(requested_url or '')
		if not current:
			return False
		if current == requested:
			return True
		try:
			current_parts = urlparse(current)
			requested_parts = urlparse(requested)
			if not requested_parts.netloc or current_parts.netloc != requested_parts.netloc:
				return False
			requested_path = (requested_parts.path or '/').rstrip('/') or '/'
			current_path = (current_parts.path or '/').rstrip('/') or '/'
			if requested_path != '/' and current_path != requested_path:
				return False
			if requested_parts.query and current_parts.query != requested_parts.query:
				return False
			return True
		except Exception:
			return False

	@staticmethod
	def _direct_initial_navigation_state_context(requested_url: str, state: BrowserStateSummary | None) -> dict[str, Any]:
		context: dict[str, Any] = {'requested_url': requested_url}
		if state is None:
			return context
		url = getattr(state, 'url', None)
		title = getattr(state, 'title', None)
		if isinstance(url, str) and url:
			context['url'] = url
		if isinstance(title, str) and title:
			context['title'] = title
		tabs = getattr(state, 'tabs', None)
		if isinstance(tabs, list) and tabs:
			tab_summaries = []
			for tab in tabs[:5]:
				tab_url = getattr(tab, 'url', None)
				tab_title = getattr(tab, 'title', None)
				if isinstance(tab_url, str) and tab_url:
					tab_summaries.append({'url': tab_url, 'title': tab_title if isinstance(tab_title, str) else ''})
			if tab_summaries:
				context['tabs'] = tab_summaries
		return context

	def add_new_task(self, new_task: str) -> None:
		"""Add a follow-up task while keeping the same Browser Use-style agent object."""
		self.task = new_task
		self._message_manager.add_new_task(new_task)
		self.state.follow_up_task = True
		self.state.stopped = False
		self.state.paused = False
		self.eventbus = EventBus(name=_unique_eventbus_name(self.id))
		self._eventbus_stopped = False
		self._external_pause_event.set()

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the current Browser Use history to disk."""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path, sensitive_data=self.sensitive_data)

	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = True,
		delay_between_actions: float = 2.0,
	) -> list[ActionResult]:
		"""Rerun through the Rust core and return Browser Use-style action results.

		The Python Agent replays serialized Python action models. Rust terminal
		histories do not expose those action models, so this compatibility path
		reruns the current task through the Rust core while preserving the public
		retry and skip-failure controls from Browser Use's rerun API.
		"""
		_ = history
		max_retries = max(1, max_retries)
		last_results: list[ActionResult] = []
		last_error: str | None = None
		for attempt in range(1, max_retries + 1):
			try:
				result = await self.run(max_steps=self.kwargs.get('max_steps', 100))
				last_results = result.action_results()
				errors = [error for error in result.errors() if error]
				if not errors:
					return last_results
				last_error = errors[0]
			except Exception as error:
				last_results = []
				last_error = str(error)

			if attempt < max_retries:
				self.logger.warning(f'Rerun failed (attempt {attempt}/{max_retries}), retrying...')
				await asyncio.sleep(delay_between_actions)

		error_msg = f'Rerun failed after {max_retries} attempts: {last_error or "unknown error"}'
		self.logger.error(error_msg)
		if not skip_failures:
			raise RuntimeError(error_msg)
		return last_results or [ActionResult(error=error_msg)]

	async def load_and_rerun(self, history_file: str | Path | None = None, **kwargs) -> list[ActionResult]:
		"""Load a saved Rust-backed Browser Use history and rerun the task."""
		if not history_file:
			history_file = 'AgentHistory.json'
		history = _load_rust_history(history_file)
		return await self.rerun_history(history, **kwargs)

	def pause(self) -> None:
		"""Pause the Rust-backed agent before the next terminal run."""
		print('\n\n⏸️ Paused the agent and left the browser open.\n\tPress [Enter] to resume or [Ctrl+C] again to quit.')
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume a paused Rust-backed agent."""
		print('----------------------------------------------------------------------')
		print('▶️  Resuming agent execution where it left off...\n')
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the Rust-backed agent before the next terminal run."""
		self.logger.info('⏹️ Agent stopping')
		self.state.stopped = True
		self._external_pause_event.set()
		if self._sdk_client is not None:
			try:
				loop = asyncio.get_running_loop()
			except RuntimeError:
				return
			loop.create_task(self._cancel_active_sdk_run())

	async def close(self):
		"""Close Browser Use session resources when the caller did not request keep-alive."""
		await self._close_browser_resources()
		await self._close_sdk_client_if_not_keep_alive()
		return None

	def _should_keep_browser_alive(self) -> bool:
		profile = getattr(self.browser_session, 'browser_profile', None) or self.browser_profile
		return bool(getattr(profile, 'keep_alive', False))

	async def _close_sdk_browser_resources(self) -> None:
		"""Close Rust-owned SDK agent/browser resources when this run is not keep-alive."""
		if self._should_keep_browser_alive() or self._sdk_client is None:
			return
		if isinstance(self._sdk_client, RustSdkClient) and self._sdk_client.process is None:
			return
		client = self._sdk_client
		agent_id = self._sdk_agent_id
		browser_id = self._sdk_browser_id
		if agent_id:
			with suppress(Exception):
				await client.call('agent.close', {'agent_id': agent_id})
		if browser_id:
			with suppress(Exception):
				await client.call('browser.close', {'browser_id': browser_id})
		self._sdk_agent_id = None
		self._sdk_browser_id = None
		self.terminal_session_id = None

	async def _close_sdk_client_if_not_keep_alive(self) -> None:
		if self._should_keep_browser_alive() or self._sdk_client is None:
			return
		try:
			await self._sdk_client.close()
		except Exception as exc:
			self.logger.error(f'Error closing Rust SDK client: {exc}')
		else:
			self._sdk_client = None

	async def _close_browser_resources(self):
		"""Close Browser Use session resources without tearing down the Rust SDK process."""
		try:
			await self._close_sdk_browser_resources()
			if self.browser_session is not None:
				if not self._should_keep_browser_alive():
					kill = getattr(self.browser_session, 'kill', None)
					if callable(kill):
						result = kill()
						if inspect.isawaitable(result):
							await result
			import gc

			gc.collect()
		except Exception as exc:
			self.logger.error(f'Error during cleanup: {exc}')
		return None

	async def log_completion(self) -> None:
		"""Log Browser Use-style task completion."""
		if self.history.is_successful():
			self.logger.info('✅ Task completed successfully')

	def run_sync(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Synchronous wrapper around the async run method."""
		return asyncio.run(self.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))

	async def authenticate_cloud_sync(self, show_instructions: bool = True) -> bool:
		"""Browser Use-compatible cloud-sync hook.

		The upstream Python Agent currently reports cloud sync as unavailable.
		The Rust wrapper mirrors that contract.
		"""
		_ = show_instructions
		self.logger.warning('Cloud sync has been removed and is no longer available')
		return False

	def get_trace_object(self) -> dict[str, Any]:
		"""Get Browser Use-style trace and trace_details data for the Rust-backed run."""

		def extract_task_website(task_text: str) -> str | None:
			match = re.search(
				r'https?://[^\s<>"\']+|www\.[^\s<>"\']+|[^\s<>"\']+\.[a-z]{2,}(?:/[^\s<>"\']*)?', task_text, re.IGNORECASE
			)
			return match.group(0) if match else None

		def json_default(value: Any) -> str:
			return str(value)

		def complete_history_without_screenshots() -> str:
			history_data = self.history.model_dump(sensitive_data=self.sensitive_data)
			for item in history_data.get('history', []):
				state = item.get('state')
				if isinstance(state, dict) and 'screenshot' in state:
					state['screenshot'] = None
			return json.dumps(history_data, default=json_default)

		trace_id = uuid7str()
		timestamp = datetime.now().isoformat()
		git_info = get_git_info()
		structured_output = self.history.structured_output
		structured_output_json = json.dumps(structured_output.model_dump(), default=json_default) if structured_output else None
		final_result = self.history.final_result()
		action_history = self.history.action_history()
		action_errors = self.history.errors()
		urls = self.history.urls()
		usage = self.history.usage

		return {
			'trace': {
				'trace_id': trace_id,
				'timestamp': timestamp,
				'browser_use_version': get_browser_use_version(),
				'git_info': json.dumps(git_info, default=json_default) if git_info else None,
				'model': self.model,
				'settings': json.dumps(self.settings.model_dump(), default=json_default) if self.settings else None,
				'task_id': self.task_id,
				'task_truncated': self.task[:20000] if len(self.task) > 20000 else self.task,
				'task_website': extract_task_website(self.task),
				'structured_output_truncated': (
					structured_output_json[:20000]
					if structured_output_json and len(structured_output_json) > 20000
					else structured_output_json
				),
				'action_history_truncated': json.dumps(action_history, default=json_default) if action_history else None,
				'action_errors': json.dumps(action_errors, default=json_default) if action_errors else None,
				'urls': json.dumps(urls, default=json_default) if urls else None,
				'final_result_response_truncated': final_result[:20000]
				if final_result and len(final_result) > 20000
				else final_result,
				'self_report_completed': 1 if self.history.is_done() else 0,
				'self_report_success': 1 if self.history.is_successful() else 0,
				'duration': self.history.total_duration_seconds(),
				'steps_taken': self.history.number_of_steps(),
				'usage': json.dumps(usage.model_dump(), default=json_default) if usage else None,
			},
			'trace_details': {
				'trace_id': trace_id,
				'timestamp': timestamp,
				'task': self.task,
				'structured_output': structured_output_json,
				'final_result_response': final_result,
				'complete_history': complete_history_without_screenshots(),
			},
		}

	def _sdk_server_argv(self) -> list[str]:
		explicit = os.environ.get('BROWSER_USE_SDK_SERVER')
		command = [explicit] if explicit else [find_browser_use_terminal_binary()]
		return [
			*command,
			*self._state_dir_args(),
			'sdk-server',
			'--transport',
			'stdio',
		]

	async def _ensure_sdk_client(self) -> RustSdkClient:
		if self._sdk_client is not None and self._sdk_client.process is not None and self._sdk_client.process.returncode is None:
			return self._sdk_client
		if self._sdk_client is not None:
			self._sdk_agent_id = None
			self._sdk_browser_id = None
			self.terminal_session_id = None
		self._sdk_client = RustSdkClient(self._sdk_server_argv(), self._run_env())
		try:
			ping = await self._sdk_client.call('runtime.ping')
			protocol_version = ping.get('sdk_protocol_version') if isinstance(ping, dict) else None
			if protocol_version == 1:
				return self._sdk_client
		except Exception as exc:
			await self._sdk_client.close()
			self._sdk_client = None
			raise BetaAgentError(
				'Failed to negotiate browser-use-terminal SDK protocol via runtime.ping. '
				'Install a compatible browser-use-core package or set BROWSER_USE_TERMINAL_BINARY to a compatible binary.'
			) from exc
		await self._sdk_client.close()
		self._sdk_client = None
		raise BetaAgentError(
			f'Unsupported browser-use-terminal SDK protocol {protocol_version!r}; expected 1. '
			'Install a compatible browser-use-core package or set BROWSER_USE_TERMINAL_BINARY to a compatible binary.'
		)

	def _sdk_llm_payload(self) -> dict[str, Any]:
		provider = _llm_provider_name(self.llm) or 'browser-use'
		payload: dict[str, Any] = {
			'provider': provider,
			'model': self.model,
		}
		if self.settings.llm_timeout is not None:
			payload['timeout'] = int(self.settings.llm_timeout)
		return payload

	def _sdk_browser_payload(self) -> dict[str, Any]:
		payload: dict[str, Any] = {}

		def put(key: str, value: Any) -> None:
			if value is None:
				return
			if isinstance(value, str) and not value:
				return
			payload[key] = value

		put('cdp_url', _extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile))
		put('cdp_headers', self.cdp_headers or None)
		put('user_agent', self.browser_user_agent)
		put('viewport', self.browser_viewport)
		put('window_size', self.browser_window_size)
		put('storage_state', self.browser_storage_state)
		put('downloads_path', self.browser_downloads_path)
		put('allowed_domains', self.allowed_domains or None)
		put('blocked_domains', self.prohibited_domains or None)
		put('state_dir', self._sdk_browser_state_dir())
		put('no_viewport', self.browser_no_viewport)
		put('accept_downloads', self.browser_accept_downloads)
		put('headless', _extract_headless_preference(self.browser_session, self.browser_profile))
		put('keep_alive', getattr(self.browser_profile, 'keep_alive', None))
		profile_id = self._sdk_profile_id()
		put('profile_id', profile_id)
		proxy_country_code = self._sdk_proxy_country_code()
		put('proxy_country_code', proxy_country_code)
		return payload

	def _sdk_profile_id(self) -> str | None:
		session_profile = getattr(self.browser_session, 'browser_profile', None)
		for profile in (session_profile, self.browser_profile, self.browser_session):
			for attr in ('profile_id', 'cloud_profile_id'):
				value = getattr(profile, attr, None)
				if isinstance(value, str) and value:
					return value
		return None

	def _sdk_proxy_country_code(self) -> str | None:
		session_profile = getattr(self.browser_session, 'browser_profile', None)
		for profile in (session_profile, self.browser_profile, self.browser_session):
			for attr in ('cloud_proxy_country_code', 'proxy_country_code'):
				value = getattr(profile, attr, None)
				if isinstance(value, str) and value:
					return value
		return None

	def _sdk_browser_state_dir(self) -> str | None:
		value = getattr(self.browser_profile, 'state_dir', None)
		if isinstance(value, (str, os.PathLike)) and str(value):
			return str(Path(value).expanduser())
		return None

	def _sdk_run_params(self, *, max_steps: int, task: str, followups: list[str] | None = None) -> dict[str, Any]:
		params: dict[str, Any] = {
			'task': task,
			'cwd': os.getcwd(),
			'llm': self._sdk_llm_payload(),
			'max_steps': int(max_steps),
			'browser_mode': self._browser_mode(),
			'browser': self._sdk_browser_payload(),
			'calculate_cost': bool(self.settings.calculate_cost),
			'use_vision': self.settings.use_vision,
			'max_actions_per_step': int(self.settings.max_actions_per_step),
			'config_overrides': {'full_llm_input_events': True},
		}
		if self._sdk_agent_id:
			params['agent_id'] = self._sdk_agent_id
		if self._sdk_browser_id:
			params['browser_id'] = self._sdk_browser_id
		if followups:
			params['followups'] = list(followups)
		if self.extraction_schema:
			params['output_schema'] = self.extraction_schema
		return params

	async def _cancel_active_sdk_run(self) -> None:
		client = self._sdk_client
		if client is None:
			return
		await client.close()

	async def _call_callback(self, callback: AgentHookFunc | None, *args: Any) -> None:
		if callback is None:
			return
		result = callback(*args)
		if inspect.isawaitable(result):
			await result

	async def _call_done_callback(self) -> None:
		if not self.history.is_done():
			return
		await self.log_completion()
		if self.register_done_callback is None:
			return
		result = self.register_done_callback(self.history)
		if inspect.isawaitable(result):
			await result

	async def _call_new_step_callback(self) -> None:
		if self.register_new_step_callback is None or not self.history.history:
			return
		history_id = id(self.history)
		if history_id == self._last_step_callback_history_id:
			return
		start_step = max(1, self.state.n_steps - len(self.history.history) + 1)
		for offset, history_item in enumerate(self.history.history):
			result = self.register_new_step_callback(history_item.state, None, start_step + offset)
			if inspect.isawaitable(result):
				await result
		self._last_step_callback_history_id = history_id

	async def _call_step_end_callbacks(self, callback: AgentHookFunc | None) -> None:
		if callback is None or not self.history.history:
			return
		history_id = id(self.history)
		if history_id == self._last_step_end_callback_history_id:
			return
		for _history_item in self.history.history:
			await self._call_callback(callback, self)
		self._last_step_end_callback_history_id = history_id

	def _sync_state_from_history(self) -> None:
		if not self.history.history:
			return
		history_id = id(self.history)
		if history_id != self._last_synced_history_id:
			self.state.n_steps += max(1, len(self.history.history))
			self._last_synced_history_id = history_id
		action_results = self.history.action_results()
		if action_results:
			self.state.last_result = action_results

	async def _save_conversation_if_requested(self) -> None:
		if not self.settings.save_conversation_path:
			return
		conversation_dir = Path(self.settings.save_conversation_path).expanduser()
		conversation_dir.mkdir(parents=True, exist_ok=True)
		target = conversation_dir / f'conversation_{self.id}_{self.state.n_steps}.json'
		target.write_text(
			json.dumps(self._conversation_snapshot(), indent=2, default=str),
			encoding=self.settings.save_conversation_path_encoding or 'utf-8',
		)

	async def _generate_gif_if_requested(self) -> None:
		if not self.settings.generate_gif:
			return
		output_path = 'agent_history.gif'
		if isinstance(self.settings.generate_gif, str):
			output_path = self.settings.generate_gif

		from browser_use.agent.gif import create_history_gif

		create_history_gif(task=self.task, history=self.history, output_path=output_path)
		if Path(output_path).exists():
			output_event = await CreateAgentOutputFileEvent.from_agent_and_file(self, output_path)
			self.eventbus.dispatch(output_event)

	def _conversation_snapshot(self) -> dict[str, Any]:
		return {
			'agent': 'browser_use.beta.Agent',
			'task_id': self.task_id,
			'session_id': self.session_id,
			'terminal_session_id': self.terminal_session_id,
			'model': self.model,
			'browser_mode': self._browser_mode(),
			'task': self.task,
			'final_result': self.history.final_result(),
			'is_done': self.history.is_done(),
			'is_successful': self.history.is_successful(),
			'errors': self.history.errors(),
			'urls': self.history.urls(),
			'usage': self.history.usage.model_dump() if self.history.usage else None,
			'events': self.last_events,
			'child_events': self.last_child_events,
			'usage_events': self.last_usage_events,
			'stdout': self.last_stdout,
			'stderr': self.last_stderr,
		}

	async def _check_stop_or_pause(self) -> None:
		"""Check Browser Use-style stop/pause controls and raise when interrupted."""
		if self.register_should_stop_callback is not None:
			should_stop = self.register_should_stop_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.logger.info('External callback requested stop')
				self.state.stopped = True
				raise InterruptedError

		if self.register_external_agent_status_raise_error_callback is not None:
			should_stop = self.register_external_agent_status_raise_error_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				raise InterruptedError

		if self.state.stopped:
			raise InterruptedError

		if self.state.paused:
			raise InterruptedError

	async def _should_stop_before_run(self) -> bool:
		if self.state.stopped:
			return True
		if self.register_should_stop_callback is not None:
			should_stop = self.register_should_stop_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		if self.register_external_agent_status_raise_error_callback is not None:
			should_stop = self.register_external_agent_status_raise_error_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		return False

	def _state_dir_args(self) -> list[str]:
		state_dir = os.environ.get('BROWSER_USE_RUST_STATE_DIR')
		return ['--state-dir', state_dir] if state_dir else []

	def _browser_mode(self) -> str:
		if _extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile):
			return 'remote-cdp'
		value = os.environ.get('BROWSER_USE_RUST_BROWSER_MODE')
		if value:
			return value
		value = os.environ.get('BROWSER_USE_BROWSER_MODE')
		if value:
			return value
		if _extract_cloud_preference(self.browser_session, self.browser_profile):
			return 'cloud'
		headless = _extract_headless_preference(self.browser_session, self.browser_profile)
		if headless is False:
			return 'managed-headed'
		if headless is True:
			return 'managed-headless'
		return 'managed-headless'

	def _run_env(self) -> dict[str, str]:
		env = os.environ.copy()
		env.update(_llm_env_overrides(self.llm))
		if self.settings.calculate_cost:
			env['BU_USE_CALCULATE_COST'] = 'true'
			if _llm_provider_name(self.llm) in {'openrouter', 'deepseek'}:
				env['LLM_BROWSER_OPENAI_COMPAT_INCLUDE_USAGE'] = 'true'
		browser_mode = self._browser_mode()
		env['LLM_BROWSER_BROWSER_MODE'] = browser_mode
		env.setdefault('BROWSER_USE_PYTHON', sys.executable)
		_apply_agent_tools_env(env)
		cdp_url = _extract_cdp_url(self.browser_session) or _extract_profile_cdp_url(self.browser_profile)
		if cdp_url:
			env['BU_CDP_URL'] = cdp_url
		if self.cdp_headers:
			env['BU_CDP_HEADERS'] = json.dumps(self.cdp_headers)
		if self.browser_user_agent:
			env['BU_BROWSER_USER_AGENT'] = self.browser_user_agent
		if self.highlight_enabled is not None:
			env['BROWSER_USE_TERMINAL_AUTO_HIGHLIGHT'] = 'true' if self.highlight_enabled else 'false'
		if self.highlight_color:
			env['BROWSER_USE_TERMINAL_HIGHLIGHT_COLOR'] = self.highlight_color
		if self.highlight_duration_ms is not None:
			env['BROWSER_USE_TERMINAL_HIGHLIGHT_DURATION_MS'] = str(self.highlight_duration_ms)
		env.update(self.wait_timing_env)
		if self.block_ip_addresses is not None:
			env['BU_BROWSER_BLOCK_IP_ADDRESSES'] = 'true' if self.block_ip_addresses else 'false'
		if self.allowed_domains:
			env['BU_BROWSER_ALLOWED_DOMAINS'] = json.dumps(self.allowed_domains)
		if self.prohibited_domains:
			env['BU_BROWSER_PROHIBITED_DOMAINS'] = json.dumps(self.prohibited_domains)
		if self.browser_permissions:
			env['BU_BROWSER_PERMISSIONS'] = json.dumps(self.browser_permissions)
		if self.browser_accept_downloads is not None:
			env['BU_BROWSER_ACCEPT_DOWNLOADS'] = 'true' if self.browser_accept_downloads else 'false'
		if self.browser_downloads_path:
			env['BU_BROWSER_DOWNLOADS_PATH'] = self.browser_downloads_path
		if self.browser_no_viewport is not None:
			env['BU_BROWSER_NO_VIEWPORT'] = 'true' if self.browser_no_viewport else 'false'
		if self.browser_viewport:
			env['BU_BROWSER_VIEWPORT'] = json.dumps(self.browser_viewport)
		if self.browser_storage_state:
			env['BU_BROWSER_STORAGE_STATE'] = json.dumps(self.browser_storage_state)
		if self.managed_browser_env and _is_managed_browser_mode(browser_mode):
			env.update(self.managed_browser_env)
		if self.managed_browser_args and _is_managed_browser_mode(browser_mode):
			env['BU_MANAGED_BROWSER_ARGS'] = json.dumps(self.managed_browser_args)
		if self.managed_browser_profile_dir and _is_managed_browser_mode(browser_mode):
			env['BU_MANAGED_BROWSER_PROFILE'] = self.managed_browser_profile_dir
		if self.managed_browser_executable_path and _is_managed_browser_mode(browser_mode):
			env['CHROME_PATH'] = self.managed_browser_executable_path
		return env


Agent.__module__ = 'browser_use.agent.service'
Agent.__doc__ = None


def _align_browser_use_agent_signatures() -> None:
	from browser_use.agent.service import _PythonAgent

	for name, browser_use_method in vars(_PythonAgent).items():
		if name.startswith('__') and name != '__init__':
			continue
		beta_method = getattr(Agent, name, None)
		if beta_method is None or not callable(browser_use_method) or not callable(beta_method):
			continue
		try:
			beta_method.__signature__ = inspect.signature(browser_use_method)
			beta_method.__annotations__ = dict(getattr(browser_use_method, '__annotations__', {}))
		except (TypeError, ValueError, AttributeError):
			continue
	try:
		Agent.__signature__ = inspect.signature(_PythonAgent)
	except (TypeError, ValueError, AttributeError):
		pass
	agent_hook_func = Callable[[_PythonAgent], Awaitable[None]]
	for name in ('run', 'run_sync'):
		beta_method = getattr(Agent, name, None)
		if beta_method is None:
			continue
		try:
			beta_method.__annotations__['on_step_start'] = agent_hook_func | None
			beta_method.__annotations__['on_step_end'] = agent_hook_func | None
		except (TypeError, AttributeError, KeyError):
			continue


_align_browser_use_agent_signatures()
