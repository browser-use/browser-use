from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal
from urllib.parse import urlparse

from bubus import EventBus
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar
from uuid_extensions import uuid7str

from browser_use.agent.message_manager.utils import save_conversation
from browser_use.agent.message_manager.service import MessageManager
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
	StepMetadata,
)
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import CHROME_DETERMINISTIC_RENDERING_ARGS, CHROME_DISABLE_SECURITY_ARGS, CHROME_DOCKER_ARGS
from browser_use.browser.views import BrowserStateHistory, BrowserStateSummary, TabInfo
from browser_use.dom.views import DOMInteractedElement
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage, ContentPartImageParam, ContentPartTextParam
from browser_use.screenshots.service import ScreenshotService
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import ModelUsageStats, UsageSummary
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.service import Tools
from browser_use.utils import URL_PATTERN, check_latest_browser_use_version, get_browser_use_version


Context = TypeVar('Context')
AgentHookFunc = Callable[['Agent'], Awaitable[None]]
AgentNewStepCallback = (
	Callable[[BrowserStateSummary, AgentOutput, int], None]
	| Callable[[BrowserStateSummary, AgentOutput, int], Awaitable[None]]
)
AgentDoneCallback = Callable[[AgentHistoryList], Awaitable[None]] | Callable[[AgentHistoryList], None]


class RustAgentError(RuntimeError):
	"""Raised when the Rust terminal core cannot run a task."""


def find_browser_use_terminal_binary() -> str:
	"""Find the terminal binary used by the Rust-backed Browser Use Agent."""
	env_path = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if env_path:
		return env_path
	path_binary = shutil.which('browser-use-terminal')
	if path_binary:
		return path_binary
	candidates = [
		Path.cwd() / 'target' / 'debug' / 'browser-use-terminal',
		Path.cwd().parent / 'terminal' / 'target' / 'debug' / 'browser-use-terminal',
		Path('/home/exedev/Developer/terminal/target/debug/browser-use-terminal'),
	]
	for candidate in candidates:
		if candidate.exists():
			return str(candidate)
	raise RustAgentError(
		'Could not find browser-use-terminal. Set BROWSER_USE_TERMINAL_BINARY or build the terminal CLI.'
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
		return 45
	if 'groq' in model_name:
		return 30
	if 'o3' in model_name or 'claude' in model_name or 'sonnet' in model_name or 'deepseek' in model_name:
		return 90
	return 60


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


def _managed_browser_executable_path(browser_session: BrowserSession | None, browser_profile: BrowserProfile | None) -> str | None:
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


def _navigation_url_from_action(action: Any) -> str | None:
	if not isinstance(action, dict):
		return None
	for name, payload in action.items():
		if name in ('open_tab', 'go_to_url', 'navigate') and isinstance(payload, dict):
			url = payload.get('url')
			if isinstance(url, str) and url:
				return url
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
			url = re.sub(r'[.,;:!?()\[\]]+$', '', match.group(0))
			url_lower = url.lower()
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


def _result_from_events(events: list[dict[str, Any]]) -> str | None:
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
	return None


def _attachments_from_events(events: list[dict[str, Any]]) -> list[str] | None:
	attachments: list[str] = []
	for event in events:
		if _event_type(event) != 'session.done':
			continue
		result_file = _result_file_pointer(_event_payload(event))
		if result_file and result_file not in attachments:
			attachments.append(result_file)
	return attachments or None


def _json_result_candidates(text: str) -> list[str]:
	candidates = [text.strip()]
	candidates.extend(match.group(1).strip() for match in re.finditer(r'```(?:json)?\s*(.*?)```', text, re.IGNORECASE | re.DOTALL))
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
	return None


def _browser_url(value: Any) -> str:
	if not isinstance(value, str):
		return ''
	value = value.strip()
	if value.startswith(('http://', 'https://', 'about:', 'file://')):
		return value
	return ''


def _browser_state_candidates(value: Any) -> list[tuple[str, str, str]]:
	candidates: list[tuple[str, str, str]] = []
	if isinstance(value, dict):
		url = _browser_url(value.get('url'))
		if url:
			title = str(value.get('title') or '')
			target_id = str(value.get('target_id') or value.get('targetId') or value.get('tab_id') or value.get('tabId') or 'tab-0')
			candidates.append((url, title, target_id))
		for child in value.values():
			candidates.extend(_browser_state_candidates(child))
	elif isinstance(value, list):
		for child in value:
			candidates.extend(_browser_state_candidates(child))
	return candidates


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
		if event_type in ('tool.output', 'tool.started'):
			payload = _event_payload(event)
			if event_type == 'tool.started':
				candidates = _browser_script_navigation_candidates(payload)
			else:
				candidates = _browser_state_candidates(payload)
			for candidate_url, candidate_title, candidate_target_id in candidates:
				url = candidate_url
				title = candidate_title or title
				tabs = [TabInfo(url=url, title=title, target_id=candidate_target_id)]
			continue
		if event_type not in ('browser.connected', 'browser.reconnected', 'browser.target_changed', 'browser.page', 'browser.state'):
			continue
		payload = _event_payload(event)
		url = _browser_url(payload.get('url')) or url
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
	return BrowserStateHistory(url=url, title=title, tabs=tabs, interacted_element=[])


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


def _token_count_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
	info = payload.get('info')
	if isinstance(info, dict):
		raw_usage = info.get('total_token_usage') or info.get('last_token_usage')
	else:
		raw_usage = payload.get('total_token_usage') or payload.get('last_token_usage')
	return raw_usage if isinstance(raw_usage, dict) else None


def _usage_from_events(events: list[dict[str, Any]], model: str) -> UsageSummary:
	input_tokens = 0
	cached_input_tokens = 0
	output_tokens = 0
	cost = 0.0
	invocations = 0
	token_count_invocations = 0

	for event in events:
		event_type = _event_type(event)
		payload = _event_payload(event)
		if event_type == 'model.usage':
			input_tokens += _int_value(payload.get('input_tokens'))
			cached_input_tokens += _int_value(payload.get('input_cached_tokens') or payload.get('cached_input_tokens'))
			output_tokens += _int_value(payload.get('output_tokens'))
			cost += _float_value(payload.get('cost_usd') or payload.get('cost'))
			invocations += 1
			continue
		if event_type == 'token_count':
			token_usage = _token_count_usage(payload)
			if token_usage is None:
				continue
			input_tokens = _int_value(token_usage.get('input_tokens'))
			cached_input_tokens = _int_value(token_usage.get('cached_input_tokens') or token_usage.get('input_cached_tokens'))
			output_tokens = _int_value(token_usage.get('output_tokens'))
			token_count_invocations += 1

	invocations = max(invocations, token_count_invocations)

	total_tokens = input_tokens + output_tokens
	by_model = {
		model: ModelUsageStats(
			model=model,
			prompt_tokens=input_tokens,
			completion_tokens=output_tokens,
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
		total_completion_tokens=output_tokens,
		total_completion_cost=0.0,
		total_tokens=total_tokens,
		total_cost=cost,
		entry_count=invocations,
		by_model=by_model,
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
	final_result = _structured_result_text(_result_from_events(events), output_model_schema)
	failure = process_error or _failure_from_events(events)
	if final_result is None and failure is None:
		failure = 'Rust terminal session did not produce a final result.'
	is_done = final_result is not None and failure is None
	result = ActionResult(
		is_done=is_done,
		success=True if is_done else None,
		error=failure,
		attachments=_attachments_from_events(events),
		extracted_content=final_result,
	)
	history = AgentHistory(
		model_output=None,
		result=[result],
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
		raise RustAgentError(f'Invalid Browser Use history file: {file_path}')
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
	resolved_tools = controller or tools
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
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		initial_actions: list[dict[str, dict[str, Any]]] | None = None,
		register_new_step_callback: AgentNewStepCallback | None = None,
		register_done_callback: AgentDoneCallback | None = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		register_should_stop_callback: Callable[[], Awaitable[bool]] | None = None,
		output_model_schema: type[AgentStructuredOutput] | None = None,
		use_vision: bool | Literal['auto'] = 'auto',
		save_conversation_path: str | Path | None = None,
		save_conversation_path_encoding: str | None = 'utf-8',
		max_failures: int = 3,
		override_system_message: str | None = None,
		extend_system_message: str | None = None,
		generate_gif: bool | str = False,
		available_file_paths: list[str] | None = None,
		include_attributes: list[str] | None = None,
		max_actions_per_step: int = 10,
		use_thinking: bool = True,
		flash_mode: bool = False,
		max_history_items: int | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		injected_agent_state: AgentState | None = None,
		source: str | None = None,
		file_system_path: str | None = None,
		task_id: str | None = None,
		calculate_cost: bool = False,
		display_files_in_done_text: bool = True,
		include_tool_call_examples: bool = False,
		vision_detail_level: Literal['auto', 'low', 'high'] = 'auto',
		llm_timeout: int | None = None,
		step_timeout: int = 120,
		directly_open_url: bool = True,
		include_recent_events: bool = False,
		sample_images: list[ContentPartTextParam | ContentPartImageParam] | None = None,
		final_response_after_failure: bool = True,
		_url_shortening_limit: int = 25,
		**kwargs,
	):
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session".')
		if tools is not None and controller is not None:
			raise ValueError('Cannot specify both "tools" and "controller".')
		if getattr(llm, 'provider', None) == 'browser-use':
			flash_mode = True
		if page_extraction_llm is None:
			page_extraction_llm = llm
		if llm_timeout is None:
			llm_timeout = _llm_timeout_for_model(llm)
		self.id = task_id or uuid7str()
		self.task_id = self.id
		self.llm = llm
		self.browser_session, self._browser_profile = _default_browser_session(
			self.id,
			browser_profile,
			browser_session,
			browser,
		)
		self.tools = _resolve_tools(
			tools,
			controller,
			output_model_schema,
			use_vision,
			display_files_in_done_text,
		)
		self.sensitive_data = sensitive_data
		self.register_new_step_callback = register_new_step_callback
		self.register_done_callback = register_done_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback
		self.register_should_stop_callback = register_should_stop_callback
		self.output_model_schema = output_model_schema
		self._set_browser_use_version_and_source(source)
		self.kwargs = kwargs
		self.model = _model_name(llm)
		self.state = injected_agent_state or AgentState()
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
		)
		self._setup_action_models()
		model_name = str(getattr(self.llm, 'model', self.model) or '').lower()
		if 'deepseek' in model_name:
			self.logger.warning('DeepSeek models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		if 'grok' in model_name:
			self.logger.warning('XAI models do not support use_vision=True yet. Setting use_vision=False for now...')
			self.settings.use_vision = False
		self.token_cost_service = TokenCost(include_cost=calculate_cost)
		_register_llm_for_usage(self.token_cost_service, llm)
		_register_llm_for_usage(self.token_cost_service, page_extraction_llm)
		self.telemetry = ProductTelemetry()
		self.eventbus = EventBus(name=_eventbus_name(self.id))
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
		self.browser_no_viewport, self.browser_viewport = _extract_browser_viewport(
			self.browser_session, self.browser_profile
		)
		self.browser_storage_state = _extract_browser_storage_state(self.browser_session, self.browser_profile)
		self.sensitive_data_context = _sensitive_data_context(sensitive_data)
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
				initial_actions = [{'navigate': {'url': self.initial_url, 'new_tab': False}}]
		self.initial_action_payloads = list(initial_actions or [])
		self.initial_actions = self._convert_initial_actions(self.initial_action_payloads) if self.initial_action_payloads else None
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
		)
		self.session_id: str = uuid7str()
		self.terminal_session_id: str | None = None
		self.history: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(history=[], usage=None)
		self.result: AgentHistoryList[AgentStructuredOutput] | None = None
		self.last_events: list[dict[str, Any]] = []
		self.last_stdout = ''
		self.last_stderr = ''
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
		self.logger.info(f'\033[34mTask: {self.task}\033[0m')
		self.logger.debug(f'Browser-Use Library Version {self.version} ({self.source})')
		latest_version = await check_latest_browser_use_version()
		if latest_version and latest_version != self.version:
			self.logger.info(
				f'Newer version available: {latest_version} (current: {self.version}). Upgrade with: uv add browser-use@{latest_version}'
			)

	def _log_first_step_startup(self) -> None:
		"""Log the first-step startup line used by Browser Use callers."""
		if len(self.history.history) != 0:
			return
		provider = getattr(self.llm, 'provider', None) or 'rust-terminal'
		model = getattr(self.llm, 'model', None) or self.model
		self.logger.info(
			f'Starting a browser-use agent with version {self.version}, with provider={provider} and model={model}'
		)

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
				agent_type=None,
				action_errors=self.history.errors(),
				action_history=action_history_data,
				urls_visited=self.history.urls(),
				steps=self.state.n_steps,
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

	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		await self._call_callback(on_step_start, self)
		started = time.time()
		if await self._should_stop_before_run():
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent stopped before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.paused:
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent is paused before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.follow_up_task and self.terminal_session_id:
			self.state.follow_up_task = False
			return await self.follow_up(self.task, max_steps=max_steps)

		returncode, stdout_text, stderr_text = await self._run_process(self._run_argv(max_steps), timeout_seconds=self.settings.step_timeout)
		finished = time.time()
		self.last_stdout = stdout_text
		self.last_stderr = stderr_text
		self.terminal_session_id = self._session_id_from_stdout(stdout_text)
		events = await self._load_events()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		elif not self.terminal_session_id:
			process_error = 'browser-use-terminal did not print a session id.'
		self.last_events = events
		self.result = _history_from_events(
			events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		self._sync_state_from_history()
		await self._check_and_update_downloads('run')
		await self._save_conversation_if_requested()
		await self._call_new_step_callback()
		await self._call_callback(on_step_end, self)
		await self._call_done_callback()
		self._generate_gif_if_requested()
		return self.history

	async def follow_up(self, task: str, max_steps: int | None = None) -> AgentHistoryList[AgentStructuredOutput]:
		if not self.terminal_session_id:
			raise RustAgentError('No active Rust session. Call run() before follow_up().')
		started = time.time()
		binary = find_browser_use_terminal_binary()
		returncode, stdout_text, stderr_text = await self._run_process(
			[binary, *self._state_dir_args(), 'followup', self.terminal_session_id, task],
			timeout_seconds=self.settings.step_timeout,
		)
		if returncode:
			raise RustAgentError(stderr_text or stdout_text)
		returncode, _stdout_text, stderr_text = await self._run_process(
			self._run_existing_argv(max_steps if max_steps is not None else self.kwargs.get('max_steps', 100)),
			timeout_seconds=self.settings.step_timeout,
		)
		finished = time.time()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		self.last_events = await self._load_events()
		self.result = _history_from_events(
			self.last_events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		self._sync_state_from_history()
		await self._check_and_update_downloads('follow_up')
		await self._save_conversation_if_requested()
		await self._call_new_step_callback()
		await self._call_done_callback()
		self._generate_gif_if_requested()
		return self.history

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
		return logging.getLogger(
			f'browser_use.rust.Agent {self.task_id[-4:]} -> BrowserSession {str(browser_session_id)[-4:]} Target {target_id}'
		)

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

		self._log_next_action_summary(parsed)
		return parsed

	async def _get_model_output_with_retry(self, input_messages: list[BaseMessage]) -> AgentOutput:
		"""Get model output, retrying once when the model returns no usable action."""
		model_output = await self.get_model_output(input_messages)

		def has_empty_actions(output: AgentOutput) -> bool:
			actions = getattr(output, 'action', None)
			if not actions or not isinstance(actions, list):
				return True
			return all(getattr(action, 'model_dump', lambda **kwargs: {})() == {} for action in actions)

		if has_empty_actions(model_output):
			from browser_use.llm.messages import UserMessage

			clarification_message = UserMessage(
				content='You forgot to return an action. Please respond with a valid JSON action according to the expected schema with your assessment and next actions.'
			)
			model_output = await self.get_model_output(input_messages + [clarification_message])
			if has_empty_actions(model_output):
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
			self.logger.debug(f'Step {self.state.n_steps}: Consecutive failures: {self.state.consecutive_failures}')
			return
		if self.state.consecutive_failures > 0:
			self.state.consecutive_failures = 0
			self.logger.debug(f'Step {self.state.n_steps}: Consecutive failures reset to: {self.state.consecutive_failures}')
		if self.state.last_result and self.state.last_result[-1].is_done:
			self.logger.info(f'\nFinal Result:\n{self.state.last_result[-1].extracted_content}\n')
			if self.state.last_result[-1].attachments:
				total_attachments = len(self.state.last_result[-1].attachments)
				for index, file_path in enumerate(self.state.last_result[-1].attachments):
					label = f'Attachment {index + 1}' if total_attachments > 1 else 'Attachment'
					self.logger.info(f'{label}: {file_path}')

	async def _handle_step_error(self, error: Exception) -> None:
		"""Convert a step exception into Browser Use-style state.last_result."""
		if isinstance(error, InterruptedError):
			self.logger.error('The agent was interrupted mid-step' + (f' - {error}' if str(error) else ''))
			return
		include_trace = self.logger.isEnabledFor(logging.DEBUG)
		error_msg = AgentError.format_error(error, include_trace=include_trace)
		self.state.consecutive_failures += 1
		self.logger.error(
			f'Result failed {self.state.consecutive_failures}/{self.settings.max_failures + int(self.settings.final_response_after_failure)} times:\n {error_msg}'
		)
		self.state.last_result = [ActionResult(error=error_msg)]

	async def _finalize(self, browser_state_summary: BrowserStateSummary | None) -> None:
		"""Finalize one Browser Use-style step after Rust-backed helper execution."""
		step_end_time = time.time()
		if not self.state.last_result:
			return
		if browser_state_summary is not None:
			step_start_time = getattr(self, 'step_start_time', step_end_time)
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
			self._log_step_completion_summary(step_start_time, self.state.last_result)
		self.save_file_system_state()
		self.state.n_steps += 1

	async def _force_done_after_last_step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Switch to done-only output on the last configured step."""
		if not (step_info and step_info.is_last_step()):
			return
		from browser_use.llm.messages import UserMessage

		msg = 'You reached max_steps - this is your last step. Your only tool available is the "done" tool. No other tool is available.'
		msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false. Else success to true.'
		msg += '\nInclude everything you found out for the ultimate task in the done text.'
		self._message_manager._add_context_message(UserMessage(content=msg))
		self.AgentOutput = self.DoneAgentOutput

	async def _force_done_after_failure(self) -> None:
		"""Switch to done-only output after max failures when final response is enabled."""
		if self.state.consecutive_failures < self.settings.max_failures or not self.settings.final_response_after_failure:
			return
		from browser_use.llm.messages import UserMessage

		msg = f'You failed {self.settings.max_failures} times. Therefore we terminate the agent.'
		msg += '\nYour only tool available is the "done" tool. No other tool is available.'
		msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false. Else success to true.'
		msg += '\nInclude everything you found out for the ultimate task in the done text.'
		self._message_manager._add_context_message(UserMessage(content=msg))
		self.AgentOutput = self.DoneAgentOutput

	async def step(self, step_info: AgentStepInfo | None = None) -> None:
		"""Execute one Browser Use-style step through the Rust terminal core."""
		await self.take_step(step_info)

	async def take_step(self, step_info: AgentStepInfo | None = None) -> tuple[bool, bool]:
		"""Take one Rust terminal turn and return Browser Use-style step status."""
		if step_info is not None:
			self.state.n_steps = max(self.state.n_steps, step_info.step_number)
		history = await self.run(max_steps=1)
		is_valid = not history.has_errors()
		return history.is_done(), is_valid

	async def _execute_step(
		self,
		step: int,
		max_steps: int,
		step_info: AgentStepInfo,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> bool:
		"""Execute one Browser Use-style run step through the Rust terminal core."""
		self.state.n_steps = max(self.state.n_steps, step_info.step_number)
		try:
			history = await self.run(max_steps=1, on_step_start=on_step_start, on_step_end=on_step_end)
		except TimeoutError:
			error_msg = f'Step {step + 1} timed out after {self.settings.step_timeout} seconds'
			self.state.consecutive_failures += 1
			self.state.last_result = [ActionResult(error=error_msg)]
			await self._call_callback(on_step_end, self)
			return False
		_ = max_steps
		return history.is_done()

	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
		"""Execute Browser Use action models through the Rust-backed session.

		The Rust terminal owns browser actions, so non-`done` action batches are
		serialized as a follow-up instruction for the active Rust session. A
		standalone `done` action preserves Browser Use's local completion semantics.
		"""
		payloads = [_action_payload(action) for action in actions]
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

	async def _execute_initial_actions(self) -> None:
		"""Execute configured Browser Use initial actions through the Rust-backed action path."""
		if not self.initial_actions or self.state.follow_up_task:
			return
		result = await self.multi_act(self.initial_actions)
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
		state_history = BrowserStateHistory(
			url=self.initial_url or '',
			title='Initial Actions',
			tabs=[],
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

	async def _execute_history_step(self, history_item: AgentHistory, delay: float) -> list[ActionResult]:
		"""Replay a Browser Use history step when Python action models are available."""
		if self.browser_session is None:
			raise ValueError('BrowserSession is not set up')
		get_state = getattr(self.browser_session, 'get_browser_state_summary', None)
		if not callable(get_state):
			raise ValueError('BrowserSession does not expose get_browser_state_summary')
		state = await get_state(include_screenshot=False)
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')

		updated_actions = []
		for index, action in enumerate(history_item.model_output.action):
			historical_element = history_item.state.interacted_element[index]
			updated_action = await self._update_action_indices(historical_element, action, state)
			if updated_action is None:
				raise ValueError(f'Could not find matching element {index} in current page')
			updated_actions.append(updated_action)

		result = await self.multi_act(updated_actions)
		await asyncio.sleep(delay)
		return result

	async def _update_action_indices(
		self,
		historical_element: DOMInteractedElement | None,
		action: ActionModel,
		browser_state_summary: BrowserStateSummary,
	) -> ActionModel | None:
		"""Update an action index when a historical DOM element moved."""
		selector_map = getattr(getattr(browser_state_summary, 'dom_state', None), 'selector_map', {})
		if not historical_element or not selector_map:
			return action
		historical_hash = getattr(historical_element, 'element_hash', None)
		highlight_index = None
		for candidate_index, element in selector_map.items():
			if getattr(element, 'element_hash', None) == historical_hash:
				highlight_index = candidate_index
				break
		if highlight_index is None:
			return None

		get_index = getattr(action, 'get_index', None)
		set_index = getattr(action, 'set_index', None)
		if callable(get_index) and callable(set_index):
			old_index = get_index()
			if old_index != highlight_index:
				set_index(highlight_index)
				self.logger.info(f'Element moved in DOM, updated index from {old_index} to {highlight_index}')
		return action

	def add_new_task(self, new_task: str) -> None:
		"""Add a follow-up task while keeping the same Browser Use-style agent object."""
		self.task = _task_with_schema(new_task, self.output_model_schema)
		self._message_manager.add_new_task(new_task)
		self.state.follow_up_task = True
		self.state.stopped = False
		self.state.paused = False
		self.eventbus = EventBus(name=_unique_eventbus_name(self.id))
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
		reruns the current task through the Rust core and returns reconstructed
		action results.
		"""
		_ = (history, max_retries, skip_failures, delay_between_actions)
		result = await self.run(max_steps=self.kwargs.get('max_steps', 100))
		return result.action_results()

	async def load_and_rerun(self, history_file: str | Path | None = None, **kwargs) -> list[ActionResult]:
		"""Load a saved Rust-backed Browser Use history and rerun the task."""
		if not history_file:
			history_file = 'AgentHistory.json'
		history = _load_rust_history(history_file)
		return await self.rerun_history(history, **kwargs)

	def pause(self) -> None:
		"""Pause the Rust-backed agent before the next terminal run."""
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume a paused Rust-backed agent."""
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the Rust-backed agent before the next terminal run."""
		self.state.stopped = True
		self._external_pause_event.set()

	async def close(self):
		"""Browser Use-compatible close hook.

		The Rust terminal owns browser lifecycle for managed modes, and remote CDP
		browsers are owned by the caller, so the Python wrapper has nothing to close.
		"""
		return None

	async def log_completion(self) -> None:
		"""Log Browser Use-style task completion."""
		if self.history.is_successful():
			self.logger.info('Task completed successfully')
		else:
			self.logger.info('Task completed without success')

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
		return False

	def get_trace_object(self) -> dict[str, Any]:
		"""Get Browser Use-style trace and trace_details data for the Rust-backed run."""

		def extract_task_website(task_text: str) -> str | None:
			match = re.search(r'https?://[^\s<>"\']+|www\.[^\s<>"\']+|[^\s<>"\']+\.[a-z]{2,}(?:/[^\s<>"\']*)?', task_text, re.IGNORECASE)
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
				'browser_use_version': None,
				'git_info': None,
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
				'final_result_response_truncated': final_result[:20000] if final_result and len(final_result) > 20000 else final_result,
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

	def _run_argv(self, max_steps: int) -> list[str]:
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex',
			self.task,
			'--model',
			self.model,
		]

	async def _run_process(self, argv: list[str], timeout_seconds: int | None = None) -> tuple[int, str, str]:
		proc = await asyncio.create_subprocess_exec(
			*argv,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		try:
			stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
		except TimeoutError:
			proc.kill()
			stdout, stderr = await proc.communicate()
			stdout_text = stdout.decode(errors='replace')
			stderr_text = stderr.decode(errors='replace')
			timeout_error = f'browser-use-terminal timed out after {timeout_seconds} seconds'
			return 124, stdout_text, '\n'.join(part for part in (stderr_text.strip(), timeout_error) if part)
		return proc.returncode or 0, stdout.decode(errors='replace'), stderr.decode(errors='replace')

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
		history_item = self.history.history[-1]
		step_number = history_item.metadata.step_number if history_item.metadata else len(self.history.history)
		result = self.register_new_step_callback(history_item.state, None, step_number)
		if inspect.isawaitable(result):
			await result

	def _sync_state_from_history(self) -> None:
		if not self.history.history:
			return
		metadata = self.history.history[-1].metadata
		if metadata is not None:
			self.state.n_steps = metadata.step_number
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

	def _generate_gif_if_requested(self) -> None:
		if not self.settings.generate_gif:
			return
		output_path = 'agent_history.gif'
		if isinstance(self.settings.generate_gif, str):
			output_path = self.settings.generate_gif

		from browser_use.agent.gif import create_history_gif

		create_history_gif(task=self.task, history=self.history, output_path=output_path)

	def _conversation_snapshot(self) -> dict[str, Any]:
		return {
			'agent': 'browser_use.rust.Agent',
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

	def _run_existing_argv(self, max_steps: int) -> list[str]:
		if not self.terminal_session_id:
			raise RustAgentError('No active Rust session. Call run() before rerunning an existing session.')
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex-session',
			self.terminal_session_id,
			'--model',
			self.model,
		]

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
		browser_mode = self._browser_mode()
		env['LLM_BROWSER_BROWSER_MODE'] = browser_mode
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

	def _session_id_from_stdout(self, stdout: str) -> str | None:
		for line in reversed(stdout.splitlines()):
			token = line.strip().split()[-1:] or ['']
			candidate = token[0]
			if len(candidate) >= 8 and all(ch in '0123456789abcdef-' for ch in candidate.lower()):
				return candidate
		return None

	async def _load_events(self) -> list[dict[str, Any]]:
		if not self.terminal_session_id:
			return []
		binary = find_browser_use_terminal_binary()
		proc = await asyncio.create_subprocess_exec(
			binary,
			*self._state_dir_args(),
			'events',
			self.terminal_session_id,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		stdout, _stderr = await proc.communicate()
		events = []
		for line in stdout.decode(errors='replace').splitlines():
			try:
				parsed = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(parsed, dict):
				events.append(parsed)
		return events


Agent.__module__ = 'browser_use.agent.service'
