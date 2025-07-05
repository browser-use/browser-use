from __future__ import annotations

import asyncio
import atexit
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

from browser_use.config import CONFIG
from browser_use.utils import _log_pretty_path, _log_pretty_url

from .utils import normalize_url

os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'  # https://github.com/microsoft/playwright/issues/35972

import anyio
import psutil
from playwright._impl._api_structures import ViewportSize
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, InstanceOf, PrivateAttr, model_validator
from uuid_extensions import uuid7str

from browser_use.browser.profile import BROWSERUSE_DEFAULT_CHANNEL, BrowserChannel, BrowserProfile
from browser_use.browser.types import (
	Browser,
	BrowserContext,
	ElementHandle,
	FrameLocator,
	Page,
	Patchright,
	PlaywrightOrPatchright,
	async_patchright,
	async_playwright,
)
from browser_use.browser.views import (
	BrowserError,
	BrowserStateSummary,
	TabInfo,
	URLNotAllowedError,
)
from browser_use.dom.clickable_element_processor.service import ClickableElementProcessor
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, SelectorMap
from browser_use.utils import match_url_with_domain_pattern, merge_dicts, retry, time_execution_async, time_execution_sync

_GLOB_WARNING_SHOWN = False  # used inside _is_url_allowed to avoid spamming the logs with the same warning multiple times

GLOBAL_PLAYWRIGHT_API_OBJECT = None  # never instantiate the playwright API object more than once per thread
GLOBAL_PATCHRIGHT_API_OBJECT = None  # never instantiate the patchright API object more than once per thread
GLOBAL_PLAYWRIGHT_EVENT_LOOP = None  # track which event loop the global objects belong to
GLOBAL_PATCHRIGHT_EVENT_LOOP = None  # track which event loop the global objects belong to

MAX_SCREENSHOT_HEIGHT = 2000
MAX_SCREENSHOT_WIDTH = 1920


def _log_glob_warning(domain: str, glob: str, logger: logging.Logger):
	global _GLOB_WARNING_SHOWN
	if not _GLOB_WARNING_SHOWN:
		logger.warning(
			# glob patterns are very easy to mess up and match too many domains by accident
			# e.g. if you only need to access gmail, don't use *.google.com because an attacker could convince the agent to visit a malicious doc
			# on docs.google.com/s/some/evil/doc to set up a prompt injection attack
			f"⚠️ Allowing agent to visit {domain} based on allowed_domains=['{glob}', ...]. Set allowed_domains=['{domain}', ...] explicitly to avoid matching too many domains!"
		)
		_GLOB_WARNING_SHOWN = True


def require_initialization(func):
	"""decorator for BrowserSession methods to require the BrowserSession be already active"""

	assert asyncio.iscoroutinefunction(func), '@require_initialization only supports decorating async methods on BrowserSession'

	@wraps(func)
	async def wrapper(self, *args, **kwargs):
		try:
			if not self.initialized or not self.browser_context:
				# raise RuntimeError('BrowserSession(...).start() must be called first to launch or connect to the browser')
				await self.start()  # just start it automatically if not already started

			if not self.agent_current_page or self.agent_current_page.is_closed():
				self.agent_current_page = (
					self.browser_context.pages[0] if (self.browser_context and len(self.browser_context.pages) > 0) else None
				)

			if not self.agent_current_page or self.agent_current_page.is_closed():
				await self.create_new_tab()

			assert self.agent_current_page and not self.agent_current_page.is_closed()

			if not hasattr(self, '_cached_browser_state_summary'):
				raise RuntimeError('BrowserSession(...).start() must be called first to initialize the browser session')

			return await func(self, *args, **kwargs)

		except Exception as e:
			# Check if this is a TargetClosedError or similar connection error
			if 'TargetClosedError' in str(type(e)) or 'context or browser has been closed' in str(e):
				self.logger.warning(
					f'✂️ Browser {self._connection_str} disconnected before BrowserSession.{func.__name__} could run...'
				)
				self._reset_connection_state()
				# Re-raise the error so the caller can handle it appropriately
				raise
			else:
				# Re-raise other exceptions unchanged
				raise

	return wrapper


DEFAULT_BROWSER_PROFILE = BrowserProfile()


@dataclass
class CachedClickableElementHashes:
	"""
	Clickable elements hashes for the last state
	"""

	url: str
	hashes: set[str]


class BrowserSession(BaseModel):
	"""
	Represents an active browser session with a running browser process somewhere.

	Chromium flags should be passed via extra_launch_args.
	Extra Playwright launch options (e.g., handle_sigterm, handle_sigint) can be passed as kwargs to BrowserSession and will be forwarded to the launch() call.
	"""

	model_config = ConfigDict(
		extra='allow',
		validate_assignment=False,
		revalidate_instances='always',
		frozen=False,
		arbitrary_types_allowed=True,
		validate_by_alias=True,
		validate_by_name=True,
	)
	# this class accepts arbitrary extra **kwargs in init because of the extra='allow' pydantic option
	# they are saved on the model, then applied to self.browser_profile via .apply_session_overrides_to_profile()

	# Persistent ID for this browser session
	id: str = Field(default_factory=uuid7str)

	# template profile for the BrowserSession, will be copied at init/validation time, and overrides applied to the copy
	browser_profile: InstanceOf[BrowserProfile] = Field(
		default=DEFAULT_BROWSER_PROFILE,
		description='BrowserProfile() instance containing config for the BrowserSession',
		validation_alias=AliasChoices(
			'profile', 'config', 'new_context_config'
		),  # abbreviations = 'profile', old deprecated names = 'config', 'new_context_config'
	)

	# runtime props/state: these can be passed in as props at init, or get auto-setup by BrowserSession.start()
	wss_url: str | None = Field(
		default=None,
		description='WSS URL of the node.js playwright browser server to connect to, outputted by (await chromium.launchServer()).wsEndpoint()',
	)
	cdp_url: str | None = Field(
		default=None,
		description='CDP URL of the browser to connect to, e.g. http://localhost:9222 or ws://127.0.0.1:9222/devtools/browser/387adf4c-243f-4051-a181-46798f4a46f4',
	)
	browser_pid: int | None = Field(
		default=None,
		description='pid of a running chromium-based browser process to connect to on localhost',
		validation_alias=AliasChoices('chrome_pid'),  # old deprecated name = chrome_pid
	)
	playwright: PlaywrightOrPatchright | None = Field(
		default=None,
		description='Playwright library object returned by: await (playwright or patchright).async_playwright().start()',
		exclude=True,
	)
	browser: Browser | None = Field(
		default=None,
		description='playwright Browser object to use (optional)',
		validation_alias=AliasChoices('playwright_browser'),
		exclude=True,
	)
	browser_context: BrowserContext | None = Field(
		default=None,
		description='playwright BrowserContext object to use (optional)',
		validation_alias=AliasChoices('playwright_browser_context', 'context'),
		exclude=True,
	)

	# runtime state: state that changes during the lifecycle of a BrowserSession(), updated by the methods below
	initialized: bool = Field(
		default=False,
		description='Mark BrowserSession launch/connection as already ready and skip setup (not recommended)',
		validation_alias=AliasChoices('is_initialized'),
	)
	agent_current_page: Page | None = Field(  # mutated by self.create_new_tab(url)
		default=None,
		description='Foreground Page that the agent is focused on',
		validation_alias=AliasChoices('current_page', 'page'),  # alias page= allows passing in a playwright Page object easily
		exclude=True,
	)
	human_current_page: Page | None = Field(  # mutated by self._setup_current_page_change_listeners()
		default=None,
		description='Foreground Page that the human is focused on',
		exclude=True,
	)

	_cached_browser_state_summary: BrowserStateSummary | None = PrivateAttr(default=None)
	_cached_clickable_element_hashes: CachedClickableElementHashes | None = PrivateAttr(default=None)
	_tab_visibility_callback: Any = PrivateAttr(default=None)
	_logger: logging.Logger | None = PrivateAttr(default=None)
	_downloaded_files: list[str] = PrivateAttr(default_factory=list)
	_original_browser_session: Any = PrivateAttr(default=None)  # Reference to prevent GC of the original session when copied
	_owns_browser_resources: bool = PrivateAttr(default=True)  # True if this instance owns and should clean up browser resources

	@model_validator(mode='after')
	def apply_session_overrides_to_profile(self) -> Self:
		"""Apply any extra **kwargs passed to BrowserSession(...) as session-specific config overrides on top of browser_profile"""
		session_own_fields = type(self).model_fields.keys()

		# get all the extra kwarg overrides passed to BrowserSession(...) that are actually
		# config Fields tracked by BrowserProfile, instead of BrowserSession's own args
		profile_overrides = self.model_dump(exclude=set(session_own_fields))

		# FOR REPL DEBUGGING ONLY, NEVER ALLOW CIRCULAR REFERENCES IN REAL CODE:
		# self.browser_profile._in_use_by_session = self

		self.browser_profile = self.browser_profile.model_copy(update=profile_overrides)

		# FOR REPL DEBUGGING ONLY, NEVER ALLOW CIRCULAR REFERENCES IN REAL CODE:
		# self.browser_profile._in_use_by_session = self

		return self

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with session ID in the name"""
		if self._logger is None:
			self._logger = logging.getLogger(f'browser_use.{self}')
		return self._logger

	def __repr__(self) -> str:
		is_copy = '©' if self._original_browser_session else '#'
		return f'BrowserSession🆂 {self.id[-4:]} {is_copy}{str(id(self))[-2:]} ({self._connection_str}, profile={self.browser_profile})'

	def __str__(self) -> str:
		is_copy = '©' if self._original_browser_session else '#'
		return f'BrowserSession🆂 {self.id[-4:]} {is_copy}{str(id(self))[-2:]} 🅟 {str(id(self.agent_current_page))[-2:]}'

	# better to force people to get it from the right object, "only one way to do it" is better python
	# def __getattr__(self, key: str) -> Any:
	# 	"""
	# 	fall back to getting any attrs from the underlying self.browser_profile when not defined on self.
	# 	(extra kwargs passed e.g. BrowserSession(extra_kwarg=124) on init get saved into self.browser_profile on validation,
	# 	so this also allows you to read those: browser_session.extra_kwarg => browser_session.browser_profile.extra_kwarg)
	# 	"""
	# 	return getattr(self.browser_profile, key)

	async def start(self) -> Self:
		"""
		Starts the browser session by either connecting to an existing browser or launching a new one.
		Precedence order for launching/connecting:
			1. page=Page playwright object, will use its page.context as browser_context
			2. browser_context=PlaywrightBrowserContext object, will use its browser
			3. browser=PlaywrightBrowser object, will use its first available context
			4. browser_pid=int, will connect to a local chromium-based browser via pid
			5. wss_url=str, will connect to a remote playwright browser server via WSS
			6. cdp_url=str, will connect to a remote chromium-based browser via CDP
			7. playwright=Playwright object, will use its chromium instance to launch a new browser
		"""

		# if we're already initialized and the connection is still valid, return the existing session state and start from scratch

		# Use timeout to prevent indefinite waiting on lock acquisition

		# Quick return if already connected
		if self.initialized and await self.is_connected():
			return self

		# Reset if we were initialized but lost connection
		if self.initialized:
			self.logger.warning(f'💔 Browser {self._connection_str} has gone away, attempting to reconnect...')
			self._reset_connection_state()

		try:
			# Setup
			self.browser_profile.detect_display_configuration()
			self.prepare_user_data_dir()

			# Get playwright object (has its own retry/semaphore)
			await self.setup_playwright()

			# Try to connect/launch browser (each has appropriate retry logic)
			await self._connect_or_launch_browser()

			# Ensure we have a context
			assert self.browser_context, f'Failed to create BrowserContext for browser={self.browser}'

			# Configure browser
			await self._setup_viewports()
			await self._setup_current_page_change_listeners()
			await self._start_context_tracing()

			self.initialized = True
			return self

		except BaseException:
			self.initialized = False
			raise

	@property
	def _connection_str(self) -> str:
		"""Get a logging-ready string describing the connection method e.g. browser=playwright+google-chrome-canary (local)"""
		binary_name = (
			Path(self.browser_profile.executable_path).name.lower().replace(' ', '-').replace('.exe', '')
			if self.browser_profile.executable_path
			else (self.browser_profile.channel or BROWSERUSE_DEFAULT_CHANNEL).name.lower().replace('_', '-').replace(' ', '-')
		)  # Google Chrome Canary.exe -> google-chrome-canary
		driver_name = 'playwright'
		if self.browser_profile.stealth:
			driver_name = 'patchright'
		return (
			f'cdp_url={self.cdp_url}'
			if self.cdp_url
			else f'wss_url={self.wss_url}'
			if self.wss_url
			else f'browser_pid={self.browser_pid}'
			if self.browser_pid
			else f'browser={driver_name}:{binary_name}'
		)

	async def stop(self, _hint: str = '') -> None:
		"""Shuts down the BrowserSession, killing the browser process (only works if keep_alive=False)"""

		# Save cookies to disk if configured
		if self.browser_context:
			try:
				await self.save_storage_state()
			except Exception as e:
				self.logger.warning(f'⚠️ Failed to save auth storage state before stopping: {type(e).__name__}: {e}')

		if self.browser_profile.keep_alive:
			self.logger.info(
				'🕊️ BrowserSession.stop() called but keep_alive=True, leaving the browser running. Use .kill() to force close.'
			)
			return  # nothing to do if keep_alive=True, leave the browser running

		# Only the owner can actually stop the browser
		if not self._owns_browser_resources:
			self.logger.debug(f'🔗 BrowserSession.stop() called on a copy, not closing shared browser resources {_hint}')
			# Still reset our references though
			self._reset_connection_state()
			return

		if self.browser_context or self.browser:
			self.logger.info(f'🛑 Closing {self._connection_str} browser context {_hint} {self.browser or self.browser_context}')

			# Save trace recording if configured
			if self.browser_profile.traces_dir and self.browser_context:
				try:
					await self._save_trace_recording()
				except Exception as e:
					# TargetClosedError is expected when browser has already been closed
					from browser_use.browser.types import TargetClosedError

					if isinstance(e, TargetClosedError):
						self.logger.debug('Browser context already closed, trace may have been saved automatically')
					else:
						self.logger.error(f'❌ Error saving browser context trace: {type(e).__name__}: {e}')

			# Log video/HAR save operations (saved automatically on close)
			if self.browser_profile.record_video_dir:
				self.logger.info(f'🎥 Saving video recording to record_video_dir= {self.browser_profile.record_video_dir}...')
			if self.browser_profile.record_har_path:
				self.logger.info(f'🎥 Saving HAR file to record_har_path= {self.browser_profile.record_har_path}...')

			# Close browser context and browser using retry-decorated methods
			try:
				# IMPORTANT: Close context first to ensure HAR/video files are saved
				await self._close_browser_context()
				await self._close_browser()
			except Exception as e:
				if 'browser has been closed' not in str(e):
					self.logger.warning(f'❌ Error closing browser: {type(e).__name__}: {e}')
			finally:
				# Always clear references to ensure a fresh start next time
				self.browser_context = None
				self.browser = None

		# Kill the chrome subprocess if we started it
		if self.browser_pid:
			try:
				await self._terminate_browser_process(_hint='(stop() called)')
			except psutil.NoSuchProcess:
				self.browser_pid = None
			except (TimeoutError, psutil.TimeoutExpired):
				# If graceful termination failed, force kill
				try:
					proc = psutil.Process(pid=self.browser_pid)
					self.logger.warning(f'⏱️ Process did not terminate gracefully, force killing browser_pid={self.browser_pid}')
					proc.kill()
				except psutil.NoSuchProcess:
					pass
				self.browser_pid = None
			except Exception as e:
				if 'NoSuchProcess' not in type(e).__name__:
					self.logger.debug(f'❌ Error terminating subprocess: {type(e).__name__}: {e}')
				self.browser_pid = None

		# Clean up temporary user data directory
		if self.browser_profile.user_data_dir and Path(self.browser_profile.user_data_dir).name.startswith('browseruse-tmp'):
			shutil.rmtree(self.browser_profile.user_data_dir, ignore_errors=True)

		self._reset_connection_state()

	async def close(self) -> None:
		"""Deprecated: Provides backwards-compatibility with old method Browser().close() and playwright BrowserContext.close()"""
		await self.stop(_hint='(close() called)')

	async def kill(self) -> None:
		"""Stop the BrowserSession even if keep_alive=True"""
		# self.logger.debug(
		# 	f'⏹️ Browser browser_pid={self.browser_pid} user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"} keep_alive={self.browser_profile.keep_alive} (close() called)'
		# )
		self.browser_profile.keep_alive = False
		await self.stop(_hint='(kill() called)')

		# do not stop self.playwright here as its likely used by other parallel browser_sessions
		# let it be cleaned up by the garbage collector when no refs use it anymore

	async def new_context(self, **kwargs):
		"""Deprecated: Provides backwards-compatibility with old class method Browser().new_context()."""
		# TODO: remove this after >=0.3.0
		return self

	async def __aenter__(self) -> BrowserSession:
		await self.start()
		return self

	def __eq__(self, other: object) -> bool:
		"""Check if two BrowserSession instances are using the same browser."""

		if not isinstance(other, BrowserSession):
			return False

		# Two sessions are considered equal if they're connected to the same browser
		# All three connection identifiers must match
		return self.browser_pid == other.browser_pid and self.cdp_url == other.cdp_url and self.wss_url == other.wss_url

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		# self.logger.debug(
		# 	f'⏹️ Stopping gracefully browser_pid={self.browser_pid} user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"} keep_alive={self.browser_profile.keep_alive} (context manager exit)'
		# )
		await self.stop(_hint='(context manager exit)')

	def model_copy(self, **kwargs) -> Self:
		"""Create a copy of this BrowserSession that shares the browser resources but doesn't own them.

		This method creates a copy that:
		- Shares the same browser, browser_context, and playwright objects
		- Doesn't own the browser resources (won't close them when garbage collected)
		- Keeps a reference to the original to prevent premature garbage collection
		"""
		# Create the copy using the parent class method
		copy = super().model_copy(**kwargs)

		# The copy doesn't own the browser resources
		copy._owns_browser_resources = False

		# Keep a reference to the original to prevent garbage collection
		copy._original_browser_session = self

		# Manually copy over the excluded fields that are needed for browser connection
		# These fields are excluded in the model config but need to be shared
		copy.playwright = self.playwright
		copy.browser = self.browser
		copy.browser_context = self.browser_context
		copy.agent_current_page = self.agent_current_page
		copy.human_current_page = self.human_current_page
		copy.browser_pid = self.browser_pid

		return copy

	def __del__(self):
		profile = getattr(self, 'browser_profile', None)
		keep_alive = getattr(profile, 'keep_alive', None)
		user_data_dir = getattr(profile, 'user_data_dir', None)
		owns_browser = getattr(self, '_owns_browser_resources', True)
		status = f'🪓 killing pid={self.browser_pid}...' if (self.browser_pid and owns_browser) else '☠️'
		self.logger.debug(
			f'🗑️ Garbage collected BrowserSession 🆂 {self.id[-4:]}.{str(id(self.agent_current_page))[-2:]} ref #{str(id(self))[-4:]} keep_alive={keep_alive} owns_browser={owns_browser} {status}'
		)
		# Only kill browser processes if this instance owns them
		if owns_browser:
			# Avoid keeping references in __del__ that might prevent garbage collection
			try:
				self._kill_child_processes(_hint='(garbage collected)')
			except TimeoutError:
				# Never let __del__ raise Timeout exceptions
				pass

	def _kill_child_processes(self, _hint: str = '') -> None:
		"""Kill any child processes that might be related to the browser"""

		if not self.browser_profile.keep_alive and self.browser_pid:
			try:
				browser_proc = psutil.Process(self.browser_pid)
				try:
					browser_proc.terminate()
					browser_proc.wait(
						timeout=5
					)  # wait up to 5 seconds for the process to exit cleanly and commit its user_data_dir changes
					self.logger.debug(f' ↳ Killed browser process browser_pid={self.browser_pid} {_hint}')
				except (psutil.NoSuchProcess, psutil.AccessDenied, TimeoutError):
					pass

				# Kill all child processes first (recursive)
				for child in browser_proc.children(recursive=True):
					try:
						# self.logger.debug(f'Force killing child process: {child.pid} ({child.name()})')
						child.kill()
						self.logger.debug(f' ↳ Killed browser helper process pid={child.pid} {_hint}')
					except (psutil.NoSuchProcess, psutil.AccessDenied):
						pass

				# Kill the main browser process
				# self.logger.debug(f'Force killing browser process: {self.browser_pid}')
				browser_proc.kill()
				self.logger.debug(f' ↳ Killed browser process browser_pid={self.browser_pid} {_hint}')
			except psutil.NoSuchProcess:
				pass
			except Exception as e:
				self.logger.warning(f'Error force-killing browser in BrowserSession.__del__: {type(e).__name__}: {e}')

	@staticmethod
	async def _start_global_playwright_subprocess(is_stealth: bool) -> PlaywrightOrPatchright:
		"""Create and return a new playwright or patchright node.js subprocess / API connector"""
		global GLOBAL_PLAYWRIGHT_API_OBJECT, GLOBAL_PATCHRIGHT_API_OBJECT
		global GLOBAL_PLAYWRIGHT_EVENT_LOOP, GLOBAL_PATCHRIGHT_EVENT_LOOP

		try:
			current_loop = asyncio.get_running_loop()
		except RuntimeError:
			current_loop = None

		if is_stealth:
			GLOBAL_PATCHRIGHT_API_OBJECT = await async_patchright().start()
			GLOBAL_PATCHRIGHT_EVENT_LOOP = current_loop
			return GLOBAL_PATCHRIGHT_API_OBJECT
		else:
			GLOBAL_PLAYWRIGHT_API_OBJECT = await async_playwright().start()
			GLOBAL_PLAYWRIGHT_EVENT_LOOP = current_loop
			return GLOBAL_PLAYWRIGHT_API_OBJECT

	async def _unsafe_get_or_start_playwright_object(self) -> PlaywrightOrPatchright:
		"""Get existing or create new global playwright object with proper locking."""
		global GLOBAL_PLAYWRIGHT_API_OBJECT, GLOBAL_PATCHRIGHT_API_OBJECT
		global GLOBAL_PLAYWRIGHT_EVENT_LOOP, GLOBAL_PATCHRIGHT_EVENT_LOOP

		# Get current event loop
		try:
			current_loop = asyncio.get_running_loop()
		except RuntimeError:
			current_loop = None

		is_stealth = self.browser_profile.stealth
		driver_name = 'patchright' if is_stealth else 'playwright'
		global_api_object = GLOBAL_PATCHRIGHT_API_OBJECT if is_stealth else GLOBAL_PLAYWRIGHT_API_OBJECT
		global_event_loop = GLOBAL_PATCHRIGHT_EVENT_LOOP if is_stealth else GLOBAL_PLAYWRIGHT_EVENT_LOOP

		# Check if we need to create or recreate the global object
		should_recreate = False

		if global_api_object and global_event_loop != current_loop:
			self.logger.debug(
				f'Detected event loop change. Previous {driver_name} instance was created in a different event loop. '
				'Creating new instance to avoid disconnection when the previous loop closes.'
			)
			should_recreate = True

		# Also check if the object exists but is no longer functional
		if global_api_object and not should_recreate:
			try:
				# Try to access the chromium property to verify the object is still valid
				_ = global_api_object.chromium.executable_path
			except Exception as e:
				self.logger.debug(f'Detected invalid {driver_name} instance: {type(e).__name__}. Creating new instance.')
				should_recreate = True

		# If we already have a valid object, use it
		if global_api_object and not should_recreate:
			return global_api_object

		# Create new playwright object
		return await self._start_global_playwright_subprocess(is_stealth=is_stealth)

	@retry(wait=1, retries=2, timeout=45, semaphore_limit=1, semaphore_scope='self', semaphore_lax=False)
	async def _close_browser_context(self) -> None:
		"""Close browser context with retry logic."""
		await self._unsafe_close_browser_context()

	async def _unsafe_close_browser_context(self) -> None:
		"""Unsafe browser context close logic without retry protection."""
		if self.browser_context:
			await self.browser_context.close()
			self.browser_context = None

	@retry(wait=1, retries=2, timeout=10, semaphore_limit=1, semaphore_scope='self', semaphore_lax=False)
	async def _close_browser(self) -> None:
		"""Close browser instance with retry logic."""
		await self._unsafe_close_browser()

	async def _unsafe_close_browser(self) -> None:
		"""Unsafe browser close logic without retry protection."""
		if self.browser and self.browser.is_connected():
			await self.browser.close()
			self.browser = None

	@retry(
		wait=0.5,
		retries=3,
		timeout=5,
		semaphore_limit=1,
		semaphore_scope='self',
		semaphore_lax=True,
		retry_on=(TimeoutError, psutil.TimeoutExpired),  # Only retry on timeouts, not NoSuchProcess
	)
	async def _terminate_browser_process(self, _hint: str = '') -> None:
		"""Terminate browser process with retry logic."""
		await self._unsafe_terminate_browser_process(_hint='(terminate() called)')

	async def _unsafe_terminate_browser_process(self, _hint: str = '') -> None:
		"""Unsafe browser process termination without retry protection."""
		if self.browser_pid:
			try:
				proc = psutil.Process(pid=self.browser_pid)
				cmdline = proc.cmdline()
				executable_path = cmdline[0] if cmdline else 'unknown'
				self.logger.info(f' ↳ Killing browser_pid={self.browser_pid} {_log_pretty_path(executable_path)} {_hint}')

				# Try graceful termination first
				proc.terminate()
				self._kill_child_processes(_hint=_hint)
				await asyncio.to_thread(proc.wait, timeout=4)
			except psutil.NoSuchProcess:
				# Process already gone, that's fine
				pass
			finally:
				self.browser_pid = None

	@retry(wait=0.5, retries=2, timeout=30, semaphore_limit=1, semaphore_scope='self', semaphore_lax=True)
	async def _save_trace_recording(self) -> None:
		"""Save browser trace recording."""
		if self.browser_profile.traces_dir and self.browser_context is not None:
			traces_path = Path(self.browser_profile.traces_dir)
			if traces_path.suffix:
				# Path has extension, use as-is (user specified exact file path)
				final_trace_path = traces_path
			else:
				# Path has no extension, treat as directory and create filename
				trace_filename = f'BrowserSession_{self.id}.zip'
				final_trace_path = traces_path / trace_filename

			self.logger.info(f'🎥 Saving browser context trace to {final_trace_path}...')
			await self.browser_context.tracing.stop(path=str(final_trace_path))

	async def _connect_or_launch_browser(self) -> None:
		"""Try all connection methods in order of precedence."""
		# Try connecting via passed objects first
		await self.setup_browser_via_passed_objects()
		if self.browser_context:
			return

		# Try connecting via browser PID
		await self.setup_browser_via_browser_pid()
		if self.browser_context:
			return

		# Try connecting via WSS URL
		await self.setup_browser_via_wss_url()
		if self.browser_context:
			return

		# Try connecting via CDP URL
		await self.setup_browser_via_cdp_url()
		if self.browser_context:
			return

		# Launch new browser as last resort
		await self.setup_new_browser_context()

	@retry(
		wait=1,  # wait 1s between attempts
		retries=2,  # 3 attempts
		timeout=15,  # 15 second reasonable timeout
		semaphore_name='screenshot_global',
		semaphore_limit=3,  # only 3 concurrent screenshots at a time total on the entire machine (ideally)
		semaphore_scope='global',  # because it's a hardware VRAM bottleneck, chrome crashes if too many concurrent screenshots are rendered via CDP
		semaphore_timeout=5,  # 5 second semaphore timeout
		semaphore_lax=True,  # proceed anyway if we cant get a lock
	)
	async def _take_screenshot_hybrid(self, page: Page) -> str:
		"""Take screenshot using Playwright, with retry and semaphore protection."""

		# Critical: Check for crashed target BEFORE any operations
		try:
			await page.evaluate('1')
		except Exception:
			raise Exception('Cannot screenshot - page is closed/crashed')

		# Check if browser context is still valid
		try:
			# Quick validation that the context is still functional
			if not self.browser_context or not self.browser_context.pages:
				raise Exception('Browser context is invalid or has no pages')

			# Verify the page is still in the context's active pages
			if page not in self.browser_context.pages:
				raise Exception('Page is no longer in browser context - target crashed')

		except Exception as e:
			self.logger.warning(f'🚨 Browser context validation failed: {type(e).__name__}: {e}')
			raise Exception(f'Browser context invalid: {e}')

		# Use Playwright screenshot directly
		assert self.browser_context

		# Fast crash detection - if this fails quickly, target is crashed
		try:
			# This should complete in <100ms on healthy pages, hang/error on crashed ones
			await asyncio.wait_for(page.evaluate('() => document.readyState'), timeout=2.0)
		except TimeoutError:
			raise Exception('Page is unresponsive - likely crashed target')
		except Exception as e:
			# Handle specific Playwright target crash errors
			error_str = str(e).lower()
			if any(
				crash_indicator in error_str
				for crash_indicator in ['target crashed', 'target closed', 'context has been closed', 'page has been closed']
			):
				raise Exception(f'Detected crashed target: {type(e).__name__}: {e}')
			raise Exception(f'Page evaluation failed: {type(e).__name__}: {e}')

		# Final assertion - this should be very fast on healthy pages
		try:
			assert await asyncio.wait_for(page.evaluate('() => true'), timeout=1.0), 'Page evaluation failed'
		except TimeoutError:
			raise Exception('Page assertion timeout - crashed target')
		except Exception as e:
			raise Exception(f'Page assertion failed: {type(e).__name__}: {e}')

		await page.bring_to_front()

		try:
			# Reasonable timeout for screenshot
			screenshot = await page.screenshot(
				full_page=False,
				# scale='css',
				timeout=self.browser_profile.default_timeout or 10000,
				# clip=FloatRect(**clip) if clip else None,
				animations='allow',
				caret='initial',
			)
		except TimeoutError:
			self.logger.warning('🚨 Screenshot deadlock detected (asyncio timeout), restarting browser...')
			self._reset_connection_state()
			await self.start()
			raise Exception('Screenshot deadlock detected, browser restarted')
		except Exception as err:
			if 'timeout' in str(err).lower() or 'TimeoutError' in str(type(err).__name__):
				self.logger.warning(
					'🚨 Screenshot timed out (playwright timeout), resetting connection state and restarting browser...'
				)
				self._reset_connection_state()
				await self.start()
			raise err

		# Final validation - should be instant on healthy pages
		try:
			assert await asyncio.wait_for(page.evaluate('() => true'), timeout=1.0), 'Page is not usable after screenshot!'
		except TimeoutError:
			raise Exception('Post-screenshot validation timeout - page may have crashed during screenshot')
		except Exception as e:
			raise Exception(f'Post-screenshot validation failed: {type(e).__name__}: {e}')

		# Quick encoding check - if this is slow, we have a problem
		screenshot_size_mb = len(screenshot) / (1024 * 1024)
		if screenshot_size_mb > 5.0:  # Warn about unusually large screenshots
			self.logger.warning(
				f'Unusually large screenshot: {screenshot_size_mb:.1f}MB - this may indicate page rendering issues'
			)

		screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
		assert screenshot_b64, 'Playwright page.screenshot() returned empty base64'
		return screenshot_b64

	@retry(
		wait=1,
		retries=3,
		timeout=10,
		semaphore_limit=1,
		semaphore_name='playwright_global_object',
		semaphore_scope='global',
		semaphore_lax=False,
		semaphore_timeout=5,  # 5s to wait for global playwright object
	)
	async def setup_playwright(self) -> None:
		"""
		Set up playwright library client object: usually the result of (await async_playwright().start())
		Override to customize the set up of the playwright or patchright library object
		"""
		is_stealth = self.browser_profile.stealth

		# Configure browser channel based on stealth mode
		if is_stealth:
			# use patchright + chrome when stealth=True
			self.browser_profile.channel = self.browser_profile.channel or BrowserChannel.CHROME
			self.logger.info(f'🕶️ Activated stealth mode using patchright {self.browser_profile.channel.name.lower()} browser...')
		else:
			# use playwright + chromium by default
			self.browser_profile.channel = self.browser_profile.channel or BrowserChannel.CHROMIUM

		# Get or create the global playwright object
		self.playwright = self.playwright or await self._unsafe_get_or_start_playwright_object()

		# Log stealth best-practices warnings if applicable
		if is_stealth:
			if self.browser_profile.channel and self.browser_profile.channel != BrowserChannel.CHROME:
				self.logger.info(
					' 🪄 For maximum stealth, BrowserSession(...) should be passed channel=None or BrowserChannel.CHROME'
				)
			if not self.browser_profile.user_data_dir:
				self.logger.info(' 🪄 For maximum stealth, BrowserSession(...) should be passed a persistent user_data_dir=...')
			if self.browser_profile.headless or not self.browser_profile.no_viewport:
				self.logger.info(' 🪄 For maximum stealth, BrowserSession(...) should be passed headless=False & viewport=None')

		# register a shutdown hook to stop the shared global playwright node.js client when the program exits (if an event loop is still running)
		def shudown_playwright():
			if not self.playwright:
				return
			try:
				loop = asyncio.get_running_loop()
				self.logger.debug('🛑 Shutting down shared global playwright node.js client')
				task = loop.create_task(self.playwright.stop())
				if hasattr(task, '_log_destroy_pending'):
					task._log_destroy_pending = False  # type: ignore
			except Exception:
				pass
			self.playwright = None

		atexit.register(shudown_playwright)

	async def setup_browser_via_passed_objects(self) -> None:
		"""Override to customize the set up of the connection to an existing browser"""

		# 1. check for a passed Page object, if present, it always takes priority, set browser_context = page.context
		if self.agent_current_page:
			try:
				# Test if the page is still usable by evaluating simple JS
				await self.agent_current_page.evaluate('() => true')
				self.browser_context = self.agent_current_page.context
			except Exception:
				# Page is closed or unusable, clear it
				self.agent_current_page = None
				self.browser_context = None

		# 2. Check if the current browser connection is valid, if not clear the invalid objects
		if self.browser_context:
			try:
				# Try to access a property that would fail if the context is closed
				_ = self.browser_context.pages
				# Additional check: verify the browser is still connected
				if self.browser_context.browser and not self.browser_context.browser.is_connected():
					self.browser_context = None
			except Exception:
				# Context is closed, clear it
				self.browser_context = None

		# 3. if we have a browser object but it's disconnected, clear it and the context because we cant use either
		if self.browser and not self.browser.is_connected():
			if self.browser_context and (self.browser_context.browser is self.browser):
				self.browser_context = None
			self.browser = None

		# 4. if we have a context now, it always takes precedence, set browser = context.browser, otherwise use the passed browser
		browser_from_context = self.browser_context and self.browser_context.browser
		if browser_from_context and browser_from_context.is_connected():
			self.browser = browser_from_context

		if self.browser or self.browser_context:
			self.logger.info(f'🎭 Connected to existing user-provided browser: {self.browser_context}')
			self._set_browser_keep_alive(True)  # we connected to an existing browser, dont kill it at the end

	async def setup_browser_via_browser_pid(self) -> None:
		"""if browser_pid is provided, calcuclate its CDP URL by looking for --remote-debugging-port=... in its CLI args, then connect to it"""

		if self.browser or self.browser_context:
			return  # already connected to a browser
		if not self.browser_pid:
			return  # no browser_pid provided, nothing to do

		# check that browser_pid process is running, otherwise we cannot connect to it
		try:
			chrome_process = psutil.Process(pid=self.browser_pid)
			if not chrome_process.is_running():
				self.logger.warning(f'⚠️ Expected Chrome process with pid={self.browser_pid} is not running')
				return
			args = chrome_process.cmdline()
		except psutil.NoSuchProcess:
			self.logger.warning(f'⚠️ Expected Chrome process with pid={self.browser_pid} not found, unable to (re-)connect')
			return
		except Exception as e:
			self.browser_pid = None
			self.logger.warning(f'⚠️ Error accessing chrome process with pid={self.browser_pid}: {type(e).__name__}: {e}')
			return

		# check that browser_pid process is exposing a debug port we can connect to, otherwise we cannot connect to it
		debug_port = next((arg for arg in args if arg.startswith('--remote-debugging-port=')), '').split('=')[-1].strip()
		if not debug_port:
			# provided pid is unusable, it's either not running or doesnt have an open debug port we can connect to
			if '--remote-debugging-pipe' in args:
				self.logger.error(
					f'❌ Found --remote-debugging-pipe in browser launch args for browser_pid={self.browser_pid} but it was started by a different BrowserSession, cannot connect to it'
				)
			else:
				self.logger.error(
					f'❌ Could not find --remote-debugging-port=... to connect to in browser launch args for browser_pid={self.browser_pid}: {" ".join(args)}'
				)
			self.browser_pid = None
			return

		self.cdp_url = self.cdp_url or f'http://localhost:{debug_port}/'
		self.logger.info(f'🌎 Connecting to existing local browser process: browser_pid={self.browser_pid} on {self.cdp_url}')
		assert self.playwright is not None, 'playwright instance is None'
		self.browser = self.browser or await self.playwright.chromium.connect_over_cdp(
			self.cdp_url,
			**self.browser_profile.kwargs_for_connect().model_dump(),
		)
		self._set_browser_keep_alive(True)  # we connected to an existing browser, dont kill it at the end

	async def setup_browser_via_wss_url(self) -> None:
		"""check for a passed wss_url, connect to a remote playwright browser server via WSS"""

		if self.browser or self.browser_context:
			return  # already connected to a browser
		if not self.wss_url:
			return  # no wss_url provided, nothing to do

		self.logger.info(f'🌎 Connecting to existing remote chromium playwright node.js server over WSS: {self.wss_url}')
		assert self.playwright is not None, 'playwright instance is None'
		self.browser = self.browser or await self.playwright.chromium.connect(
			self.wss_url,
			**self.browser_profile.kwargs_for_connect().model_dump(),
		)
		self._set_browser_keep_alive(True)  # we connected to an existing browser, dont kill it at the end

	async def setup_browser_via_cdp_url(self) -> None:
		"""check for a passed cdp_url, connect to a remote chromium-based browser via CDP"""

		if self.browser or self.browser_context:
			return  # already connected to a browser
		if not self.cdp_url:
			return  # no cdp_url provided, nothing to do

		self.logger.info(f'🌎 Connecting to existing remote chromium-based browser over CDP: {self.cdp_url}')
		assert self.playwright is not None, 'playwright instance is None'
		self.browser = self.browser or await self.playwright.chromium.connect_over_cdp(
			self.cdp_url,
			**self.browser_profile.kwargs_for_connect().model_dump(),
		)
		self._set_browser_keep_alive(True)  # we connected to an existing browser, dont kill it at the end

	@retry(wait=1, retries=2, timeout=45, semaphore_limit=1, semaphore_scope='self', semaphore_lax=False)
	async def setup_new_browser_context(self) -> None:
		"""Launch a new browser and browser_context"""
		# Double-check after semaphore acquisition to prevent duplicate browser launches
		if self.browser_context:
			try:
				# Check if context is still valid and has pages
				if self.browser_context.pages and not all(page.is_closed() for page in self.browser_context.pages):
					self.logger.debug('Browser context already exists after semaphore acquisition, skipping launch')
					return
			except Exception:
				# If we can't check pages, assume context is invalid and continue with launch
				pass
		await self._unsafe_setup_new_browser_context()

	async def _unsafe_setup_new_browser_context(self) -> None:
		"""Unsafe browser context setup without retry protection."""
		current_process = psutil.Process(os.getpid())
		child_pids_before_launch = {child.pid for child in current_process.children(recursive=True)}

		# if we have a browser object but no browser_context, use the first context discovered or make a new one
		if self.browser and not self.browser_context:
			if self.browser.contexts:
				self.browser_context = self.browser.contexts[0]
				self.logger.info(f'🌎 Using first browser_context available in existing browser: {self.browser_context}')
			else:
				self.browser_context = await self.browser.new_context(
					**self.browser_profile.kwargs_for_new_context().model_dump(mode='json')
				)
				storage_info = (
					f' + loaded storage_state={len(self.browser_profile.storage_state) if self.browser_profile.storage_state else 0} cookies'
					if self.browser_profile.storage_state and isinstance(self.browser_profile.storage_state, dict)
					else ''
				)
				self.logger.info(
					f'🌎 Created new empty browser_context in existing browser{storage_info}: {self.browser_context}'
				)

		# if we still have no browser_context by now, launch a new local one using launch_persistent_context()
		if not self.browser_context:
			assert self.browser_profile.channel is not None, 'browser_profile.channel is None'
			self.logger.info(
				f'🌎 Launching new local browser '
				f'{str(type(self.playwright).__module__).split(".")[0]}:{self.browser_profile.channel.name.lower()} keep_alive={self.browser_profile.keep_alive or False} '
				f'user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"}'
			)

			# if no user_data_dir is provided, generate a unique one for this temporary browser_context (will be used to uniquely identify the browser_pid later)
			if not self.browser_profile.user_data_dir:
				# self.logger.debug('🌎 Launching local browser in incognito mode')
				# if no user_data_dir is provided, generate a unique one for this temporary browser_context (will be used to uniquely identify the browser_pid later)
				self.browser_profile.user_data_dir = self.browser_profile.user_data_dir or Path(
					tempfile.mkdtemp(prefix='browseruse-tmp-')
				)

			# user data dir was provided, prepare it for use
			self.prepare_user_data_dir()

			# search for potentially conflicting local processes running on the same user_data_dir
			for proc in psutil.process_iter(['pid', 'cmdline']):
				if f'--user-data-dir={self.browser_profile.user_data_dir}' in (proc.info['cmdline'] or []):
					self.logger.error(
						f'🚨 Found potentially conflicting browser process browser_pid={proc.info["pid"]} '
						f'already running with the same user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir)}'
					)
					break

			# if a user_data_dir is provided, launch a persistent context with that user_data_dir
			try:
				async with asyncio.timeout(self.browser_profile.timeout / 1000):
					try:
						assert self.playwright is not None, 'playwright instance is None'
						self.browser_context = await self.playwright.chromium.launch_persistent_context(
							**self.browser_profile.kwargs_for_launch_persistent_context().model_dump(mode='json')
						)
					except Exception as e:
						# Check if it's a SingletonLock error
						if 'SingletonLock' in str(e) or 'ProcessSingleton' in str(e):
							self.logger.warning('⚠️ SingletonLock error detected. Cleaning up and retrying...')
							# Remove the stale lock file
							singleton_lock = Path(self.browser_profile.user_data_dir) / 'SingletonLock'
							if singleton_lock.exists():
								singleton_lock.unlink()
							# Wait a moment for cleanup
							await asyncio.sleep(0.1)
							# Retry the launch
							assert self.playwright is not None, 'playwright instance is None'
							self.browser_context = await self.playwright.chromium.launch_persistent_context(
								**self.browser_profile.kwargs_for_launch_persistent_context().model_dump(mode='json')
							)
						# Re-raise if not a timeout
						elif not isinstance(e, asyncio.TimeoutError):
							raise
			except TimeoutError:
				self.logger.warning(
					'Browser operation timed out. This may indicate the playwright instance is invalid due to event loop changes. '
					'Recreating playwright instance and retrying...'
				)
				# Force recreation of the playwright object
				self.playwright = await self._start_global_playwright_subprocess(is_stealth=self.browser_profile.stealth)
				# Retry the operation with the new playwright instance
				async with asyncio.timeout(self.browser_profile.timeout / 1000):
					assert self.playwright is not None, 'playwright instance is None'
					self.browser_context = await self.playwright.chromium.launch_persistent_context(
						**self.browser_profile.kwargs_for_launch_persistent_context().model_dump()
					)
			except Exception as e:
				# show a nice logger hint explaining what went wrong with the user_data_dir
				# calculate the version of the browser that the user_data_dir is for, and the version of the browser we are running with
				user_data_dir_chrome_version = '???'
				test_browser_version = '???'
				try:
					# user_data_dir is corrupted or unreadable because it was migrated to a newer version of chrome than we are running with
					user_data_dir_chrome_version = (Path(self.browser_profile.user_data_dir) / 'Last Version').read_text().strip()
				except Exception:
					pass  # let the logger below handle it
				try:
					assert self.playwright is not None, 'playwright instance is None'
					test_browser = await self.playwright.chromium.launch(headless=True)
					test_browser_version = test_browser.version
					await test_browser.close()
				except Exception:
					pass

				# failed to parse extensions == most common error text when user_data_dir is corrupted / has an unusable schema
				reason = 'due to bad' if 'Failed parsing extensions' in str(e) else 'for unknown reason with'
				driver = str(type(self.playwright).__module__).split('.')[0].lower()
				browser_channel = (
					Path(self.browser_profile.executable_path).name.replace(' ', '-').replace('.exe', '').lower()
					if self.browser_profile.executable_path
					else (self.browser_profile.channel or BROWSERUSE_DEFAULT_CHANNEL).name.lower()
				)
				self.logger.error(
					f'❌ Launching new local browser {driver}:{browser_channel} (v{test_browser_version}) failed!'
					f'\n\tFailed {reason} user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir)} (created with v{user_data_dir_chrome_version})'
					'\n\tTry using a different browser version/channel or delete the user_data_dir to start over with a fresh profile.'
					'\n\t(can happen if different versions of Chrome/Chromium/Brave/etc. tried to share one dir)'
					f'\n\n{type(e).__name__} {e}'
				)
				raise

		# Only restore browser from context if it's connected, otherwise keep it None to force new launch
		browser_from_context = self.browser_context and self.browser_context.browser
		if browser_from_context and browser_from_context.is_connected():
			self.browser = browser_from_context
		# ^ self.browser can unfortunately still be None at the end ^
		# playwright does not give us a browser object at all when we use launch_persistent_context()!

		# Detect any new child chrome processes that we might have launched above
		def is_our_chrome_proc(pid: int) -> psutil.Process | None:
			try:
				proc = psutil.Process(pid)
				cmdline = proc.cmdline()
				if 'Helper' in proc.name():
					return None
				if proc.status() != 'running':
					return None
				if (
					self.browser_profile.executable_path
					and Path(cmdline[0]).expanduser().resolve()
					!= Path(self.browser_profile.executable_path).expanduser().resolve()
				):
					# self.logger.debug(f'❌ Found new child chrome process that does not match our executable: {str(cmdline)[:50]}')
					return None
				if (
					self.browser_profile.user_data_dir
					and f'--user-data-dir={Path(self.browser_profile.user_data_dir).expanduser().resolve()}' in cmdline
				):
					# self.logger.debug(f'✅ Found new child chrome process that matches our user_data_dir: {str(cmdline)[:50]}')
					return proc
				else:
					# self.logger.debug(f'❌ Found new child chrome process that does not match our user_data_dir: {[arg for arg in cmdline if "--user-data-dir=" in arg]}')
					return None
			except Exception:
				pass
			return None

		child_pids_after_launch = {child.pid for child in current_process.children(recursive=True)}
		new_child_pids = child_pids_after_launch - child_pids_before_launch
		new_child_procs = list(filter(bool, (is_our_chrome_proc(pid) for pid in new_child_pids)))
		if not new_child_procs:
			self.logger.debug(f'❌ Failed to find any new child chrome processes after launching new browser: {new_child_pids}')
			new_chrome_proc = None
			# Browser PID detection can fail in some environments (e.g. CI, containers)
			# This is not critical - the browser is still running and usable
			self.browser_pid = None
		elif len(new_child_procs) > 1:
			self.logger.debug(f'❌ Found multiple new child chrome processes after launching new browser: {new_child_procs}')
			new_chrome_proc = None
			self.browser_pid = None
		else:
			new_chrome_proc = new_child_procs[0]

		if new_chrome_proc and not self.browser_pid:
			# look through the discovered new chrome processes to uniquely identify the one that *we* launched,
			# match using unique user_data_dir
			try:
				self.browser_pid = new_chrome_proc.pid
				cmdline = new_chrome_proc.cmdline()
				executable_path = cmdline[0] if cmdline else 'unknown'
				self.logger.info(f' ↳ Spawned browser_pid={self.browser_pid} {_log_pretty_path(executable_path)}')
				if cmdline:
					self.logger.debug(' '.join(cmdline))  # print the entire launch command for debugging
				self._set_browser_keep_alive(False)  # close the browser at the end because we launched it
			except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
				self.logger.warning(f'Browser process {self.browser_pid} died immediately after launch: {type(e).__name__}')

		if self.browser:
			assert self.browser.is_connected(), (
				f'Browser is not connected, did the browser process crash or get killed? (connection method: {self._connection_str})'
			)
		self.logger.debug(f'🪢 Browser {self._connection_str} connected {self.browser or self.browser_context}')

		assert self.browser_context, (
			f'{self} Failed to create a playwright BrowserContext {self.browser_context} for browser={self.browser}'
		)

		# self.logger.debug('Setting up init scripts in browser')

		init_script = """
			// check to make sure we're not inside the PDF viewer
			window.isPdfViewer = !!document?.body?.querySelector('body > embed[type="application/pdf"][width="100%"]')
			if (!window.isPdfViewer) {

				// Permissions
				const originalQuery = window.navigator.permissions.query;
				window.navigator.permissions.query = (parameters) => (
					parameters.name === 'notifications' ?
						Promise.resolve({ state: Notification.permission }) :
						originalQuery(parameters)
				);
				(() => {
					if (window._eventListenerTrackerInitialized) return;
					window._eventListenerTrackerInitialized = true;

					const originalAddEventListener = EventTarget.prototype.addEventListener;
					const eventListenersMap = new WeakMap();

					EventTarget.prototype.addEventListener = function(type, listener, options) {
						if (typeof listener === "function") {
							let listeners = eventListenersMap.get(this);
							if (!listeners) {
								listeners = [];
								eventListenersMap.set(this, listeners);
							}

							listeners.push({
								type,
								listener,
								listenerPreview: listener.toString().slice(0, 100),
								options
							});
						}

						return originalAddEventListener.call(this, type, listener, options);
					};

					window.getEventListenersForNode = (node) => {
						const listeners = eventListenersMap.get(node) || [];
						return listeners.map(({ type, listenerPreview, options }) => ({
							type,
							listenerPreview,
							options
						}));
					};
				})();
			}
		"""

		# Expose anti-detection scripts
		try:
			await self.browser_context.add_init_script(init_script)
		except Exception as e:
			if 'Target page, context or browser has been closed' in str(e):
				self.logger.warning('⚠️ Browser context was closed before init script could be added')
				# Reset connection state since browser is no longer valid
				self._reset_connection_state()
			else:
				raise

		if self.browser_profile.stealth and not isinstance(self.playwright, Patchright):
			self.logger.warning('⚠️ Failed to set up stealth mode. (...) got normal playwright objects as input.')

	# async def _fork_locked_user_data_dir(self) -> None:
	# 	"""Fork an in-use user_data_dir by cloning it to a new location to allow a second browser to use it"""
	# 	# TODO: implement copy-on-write using overlayfs or zfs or something
	# 	suffix_num = str(self.browser_profile.user_data_dir).rsplit('.', 1)[-1] or '1'
	# 	suffix_num = int(suffix_num) if suffix_num.isdigit() else 1
	# 	dir_name = self.browser_profile.user_data_dir.name
	# 	incremented_name = dir_name.replace(f'.{suffix_num}', f'.{suffix_num + 1}')
	# 	fork_path = self.browser_profile.user_data_dir.parent / incremented_name

	# 	# keep incrementing the suffix_num until we find a path that doesn't exist
	# 	while fork_path.exists():
	# 		suffix_num += 1
	# 		fork_path = self.browser_profile.user_data_dir.parent / (dir_name.rsplit('.', 1)[0] + f'.{suffix_num}')

	# 	# use shutil to recursively copy the user_data_dir to a new location
	# 	shutil.copytree(
	# 		str(self.browser_profile.user_data_dir),
	# 		str(fork_path),
	# 		symlinks=True,
	# 		ignore_dangling_symlinks=True,
	# 		dirs_exist_ok=False,
	# 	)
	# 	self.browser_profile.user_data_dir = fork_path
	# 	self.browser_profile.prepare_user_data_dir()

	async def _setup_current_page_change_listeners(self) -> None:
		# Uses a combination of:
		# - visibilitychange events
		# - window focus/blur events
		# - pointermove events

		# This annoying multi-method approach is needed for more reliable detection across browsers because playwright provides no API for this.

		# TODO: pester the playwright team to add a new event that fires when a headful tab is focused.
		# OR implement a browser-use chrome extension that acts as a bridge to the chrome.tabs API.

		#         - https://github.com/microsoft/playwright/issues/1290
		#         - https://github.com/microsoft/playwright/issues/2286
		#         - https://github.com/microsoft/playwright/issues/3570
		#         - https://github.com/microsoft/playwright/issues/13989

		# set up / detect foreground page
		assert self.browser_context is not None, 'BrowserContext object is not set'
		pages = self.browser_context.pages
		foreground_page = None
		if pages:
			foreground_page = pages[0]
			self.logger.debug(
				f'👁️‍🗨️ Found {len(pages)} existing tabs in browser, Agent 🅰 {self.id[-4:]}.{str(id(self.agent_current_page))[-2:]} will start focused on tab 🄿 [{pages.index(foreground_page)}]: {foreground_page.url}'  # type: ignore
			)
		else:
			foreground_page = await self.browser_context.new_page()
			pages = [foreground_page]
			self.logger.debug('➕ Opened new tab in empty browser context...')

		self.agent_current_page = self.agent_current_page or foreground_page
		self.human_current_page = self.human_current_page or foreground_page
		# self.logger.debug('About to define _BrowserUseonTabVisibilityChange callback')

		def _BrowserUseonTabVisibilityChange(source: dict[str, Page]):
			"""hook callback fired when init script injected into a page detects a focus event"""
			new_page = source['page']

			# Update human foreground tab state
			old_foreground = self.human_current_page
			assert self.browser_context is not None, 'BrowserContext object is not set'
			assert old_foreground is not None, 'Old foreground page is not set'
			old_tab_idx = self.browser_context.pages.index(old_foreground)  # type: ignore
			self.human_current_page = new_page
			new_tab_idx = self.browser_context.pages.index(new_page)  # type: ignore

			# Log before and after for debugging
			old_url = old_foreground and old_foreground.url or 'about:blank'
			new_url = new_page and new_page.url or 'about:blank'
			agent_url = self.agent_current_page and self.agent_current_page.url or 'about:blank'
			agent_tab_idx = self.browser_context.pages.index(self.agent_current_page)  # type: ignore
			if old_url != new_url:
				self.logger.info(
					f'👁️ Foregound tab changed by human from [{old_tab_idx}]{_log_pretty_url(old_url)} '
					f'➡️ [{new_tab_idx}]{_log_pretty_url(new_url)} '
					f'(agent will stay on [{agent_tab_idx}]{_log_pretty_url(agent_url)})'
				)

		# Store the callback so we can potentially clean it up later
		self._tab_visibility_callback = _BrowserUseonTabVisibilityChange

		# self.logger.info('About to call expose_binding')
		try:
			await self.browser_context.expose_binding('_BrowserUseonTabVisibilityChange', _BrowserUseonTabVisibilityChange)
			# self.logger.debug('window._BrowserUseonTabVisibilityChange binding attached via browser_context')
		except Exception as e:
			if 'Function "_BrowserUseonTabVisibilityChange" has been already registered' in str(e):
				self.logger.debug(
					'⚠️ Function "_BrowserUseonTabVisibilityChange" has been already registered, '
					'this is likely because the browser was already started with an existing BrowserSession()'
				)

			else:
				raise

		update_tab_focus_script = """
			// --- Method 1: visibilitychange event (unfortunately *all* tabs are always marked visible by playwright, usually does not fire) ---
			document.addEventListener('visibilitychange', async () => {
				if (document.visibilityState === 'visible') {
					await window._BrowserUseonTabVisibilityChange({ source: 'visibilitychange', url: document.location.href });
					console.log('BrowserUse Foreground tab change event fired', document.location.href);
				}
			});
			
			// --- Method 2: focus/blur events, most reliable method for headful browsers ---
			window.addEventListener('focus', async () => {
				await window._BrowserUseonTabVisibilityChange({ source: 'focus', url: document.location.href });
				console.log('BrowserUse Foreground tab change event fired', document.location.href);
			});
			
			// --- Method 3: pointermove events (may be fired by agent if we implement AI hover movements, also very noisy) ---
			// Use a throttled handler to avoid excessive calls
			// let lastMove = 0;
			// window.addEventListener('pointermove', async () => {
			// 	const now = Date.now();
			// 	if (now - lastMove > 1000) {  // Throttle to once per second
			// 		lastMove = now;
			// 		await window._BrowserUseonTabVisibilityChange({ source: 'pointermove', url: document.location.href });
			//      console.log('BrowserUse Foreground tab change event fired', document.location.href);
			// 	}
			// });
		"""
		try:
			await self.browser_context.add_init_script(update_tab_focus_script)
		except Exception as e:
			self.logger.warning(f'⚠️ Failed to register init script for tab focus detection: {e}')

		# Set up visibility listeners for all existing tabs
		# self.logger.info(f'Setting up visibility listeners for {len(self.browser_context.pages)} pages')
		for page in self.browser_context.pages:
			# self.logger.info(f'Processing page with URL: {repr(page.url)}')
			# Skip about:blank pages as they can hang when evaluating scripts
			if page.url == 'about:blank':
				continue

			try:
				await page.evaluate(update_tab_focus_script)
				# self.logger.debug(f'👁️ Added visibility listener to existing tab: {page.url}')
			except Exception as e:
				page_idx = self.browser_context.pages.index(page)  # type: ignore
				self.logger.debug(
					f'⚠️ Failed to add visibility listener to existing tab, is it crashed or ignoring CDP commands?: [{page_idx}]{page.url}: {type(e).__name__}: {e}'
				)

	async def _setup_viewports(self) -> None:
		"""Resize any existing page viewports to match the configured size, set up storage_state, permissions, geolocation, etc."""

		assert self.browser_context, 'BrowserSession.browser_context must already be set up before calling _setup_viewports()'

		# log the viewport settings to terminal
		viewport = self.browser_profile.viewport
		self.logger.debug(
			'📐 Setting up viewport: '
			+ f'headless={self.browser_profile.headless} '
			+ (
				f'window={self.browser_profile.window_size["width"]}x{self.browser_profile.window_size["height"]}px '
				if self.browser_profile.window_size
				else '(no window) '
			)
			+ (
				f'screen={self.browser_profile.screen["width"]}x{self.browser_profile.screen["height"]}px '
				if self.browser_profile.screen
				else ''
			)
			+ (f'viewport={viewport["width"]}x{viewport["height"]}px ' if viewport else '(no viewport) ')
			+ f'device_scale_factor={self.browser_profile.device_scale_factor or 1.0} '
			+ f'is_mobile={self.browser_profile.is_mobile} '
			+ (f'color_scheme={self.browser_profile.color_scheme.value} ' if self.browser_profile.color_scheme else '')
			+ (f'locale={self.browser_profile.locale} ' if self.browser_profile.locale else '')
			+ (f'timezone_id={self.browser_profile.timezone_id} ' if self.browser_profile.timezone_id else '')
			+ (f'geolocation={self.browser_profile.geolocation} ' if self.browser_profile.geolocation else '')
			+ (f'permissions={",".join(self.browser_profile.permissions or ["<none>"])} ')
			+ f'storage_state={_log_pretty_path(str(self.browser_profile.storage_state or self.browser_profile.cookies_file or "<none>"))} '
		)

		# if we have any viewport settings in the profile, make sure to apply them to the entire browser_context as defaults
		if self.browser_profile.permissions:
			try:
				await self.browser_context.grant_permissions(self.browser_profile.permissions)
			except Exception as e:
				self.logger.warning(
					f'⚠️ Failed to grant browser permissions {self.browser_profile.permissions}: {type(e).__name__}: {e}'
				)
		try:
			if self.browser_profile.default_timeout:
				self.browser_context.set_default_timeout(self.browser_profile.default_timeout)
			if self.browser_profile.default_navigation_timeout:
				self.browser_context.set_default_navigation_timeout(self.browser_profile.default_navigation_timeout)
		except Exception as e:
			self.logger.warning(
				f'⚠️ Failed to set playwright timeout settings '
				f'cdp_api={self.browser_profile.default_timeout} '
				f'navigation={self.browser_profile.default_navigation_timeout}: {type(e).__name__}: {e}'
			)
		try:
			if self.browser_profile.extra_http_headers:
				await self.browser_context.set_extra_http_headers(self.browser_profile.extra_http_headers)
		except Exception as e:
			self.logger.warning(
				f'⚠️ Failed to setup playwright extra_http_headers: {type(e).__name__}: {e}'
			)  # dont print the secret header contents in the logs!

		try:
			if self.browser_profile.geolocation:
				await self.browser_context.set_geolocation(self.browser_profile.geolocation)
		except Exception as e:
			self.logger.warning(
				f'⚠️ Failed to update browser geolocation {self.browser_profile.geolocation}: {type(e).__name__}: {e}'
			)

		await self.load_storage_state()

		page = None

		for page in self.browser_context.pages:
			# apply viewport size settings to any existing pages
			if viewport:
				await page.set_viewport_size(viewport)

			# show browser-use dvd screensaver-style bouncing loading animation on any about:blank pages
			if page.url == 'about:blank':
				await self._show_dvd_screensaver_loading_animation(page)

		page = page or (await self.browser_context.new_page())

		if (not viewport) and (self.browser_profile.window_size is not None) and not self.browser_profile.headless:
			# attempt to resize the actual browser window

			# cdp api: https://chromedevtools.github.io/devtools-protocol/tot/Browser/#method-setWindowBounds
			try:
				cdp_session = await page.context.new_cdp_session(page)  # type: ignore
				window_id_result = await cdp_session.send('Browser.getWindowForTarget')
				await cdp_session.send(
					'Browser.setWindowBounds',
					{
						'windowId': window_id_result['windowId'],
						'bounds': {
							**self.browser_profile.window_size,
							'windowState': 'normal',  # Ensure window is not minimized/maximized
						},
					},
				)
				await cdp_session.detach()
			except Exception as e:
				_log_size = lambda size: f'{size["width"]}x{size["height"]}px'
				try:
					# fallback to javascript resize if cdp setWindowBounds fails
					await page.evaluate(
						"""(width, height) => {window.resizeTo(width, height)}""",
						[self.browser_profile.window_size['width'], self.browser_profile.window_size['height']],
					)
					return
				except Exception:
					pass

				self.logger.warning(
					f'⚠️ Failed to resize browser window to {_log_size(self.browser_profile.window_size)} using CDP setWindowBounds: {type(e).__name__}: {e}'
				)

	def _set_browser_keep_alive(self, keep_alive: bool | None) -> None:
		"""set the keep_alive flag on the browser_profile, defaulting to True if keep_alive is None"""
		if self.browser_profile.keep_alive is None:
			self.browser_profile.keep_alive = keep_alive

	async def is_connected(self, restart: bool = True) -> bool:
		"""
		Check if the browser session has valid, connected browser and context objects.
		Returns False if any of the following conditions are met:
		- No browser_context exists
		- Browser exists but is disconnected
		- Browser_context's browser exists but is disconnected
		- Browser_context itself is closed/unusable

		Args:
			restart: If True, will attempt to create a new tab if no pages exist (valid contexts must always have at least one page open).
			        If False, will only check connection status without side effects.
		"""
		if not self.browser_context:
			return False

		if self.browser_context.browser and not self.browser_context.browser.is_connected():
			return False

		# Check if the browser_context itself is closed/unusable
		try:
			# The only reliable way to check if a browser context is still valid
			# is to try to use it. We'll try a simple page.evaluate() call.
			if self.browser_context.pages:
				# Use the first available page to test the connection
				test_page = self.browser_context.pages[0]
				# Try a simple evaluate to check if the connection is alive
				result = await test_page.evaluate('() => true')
				return result is True
			elif restart:
				await self.create_new_tab()
				# Test the new tab
				if self.browser_context.pages:
					test_page = self.browser_context.pages[0]
					result = await test_page.evaluate('() => true')
					return result is True
				return False
			else:
				return False
		except Exception:
			# Any exception means the context is closed or invalid
			return False

	def _reset_connection_state(self) -> None:
		"""Reset the browser connection state when disconnection is detected"""

		already_disconnected = not any(
			(
				self.initialized,
				self.browser,
				self.browser_context,
				self.agent_current_page,
				self.human_current_page,
				self._cached_clickable_element_hashes,
				self._cached_browser_state_summary,
			)
		)

		self.initialized = False
		self.browser = None
		self.browser_context = None
		self.agent_current_page = None
		self.human_current_page = None
		self._cached_clickable_element_hashes = None
		self._cached_browser_state_summary = None
		# Don't clear self.playwright here - it should be cleared explicitly in kill()

		if self.browser_pid:
			try:
				# browser_pid is different from all the other state objects, it's closer to cdp_url or wss_url
				# because we might still be able to reconnect to the same browser even if self.browser_context died
				# if we have a self.browser_pid, check if it's still alive and serving a remote debugging port
				# if so, don't clear it because there's a chance we can re-use it by just reconnecting to the same pid's port
				proc = psutil.Process(self.browser_pid)
				proc_is_alive = proc.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
				assert proc_is_alive and '--remote-debugging-port' in ' '.join(proc.cmdline())
			except Exception:
				self.logger.info(f' ↳ Browser browser_pid={self.browser_pid} process is no longer running')
				# process has gone away or crashed, pid is no longer valid so we clear it
				self.browser_pid = None

		if not already_disconnected:
			self.logger.debug(f'⚰️ Browser {self._connection_str} disconnected')

	def prepare_user_data_dir(self) -> None:
		"""Create and unlock the user data dir and ensure all recording paths exist."""

		if self.browser_profile.user_data_dir:
			try:
				self.browser_profile.user_data_dir = Path(self.browser_profile.user_data_dir).expanduser().resolve()
				self.browser_profile.user_data_dir.mkdir(parents=True, exist_ok=True)
				(self.browser_profile.user_data_dir / '.browseruse_profile_id').write_text(self.browser_profile.id)
			except Exception as e:
				raise ValueError(
					f'Unusable path provided for user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir)} (check for typos/permissions issues)'
				) from e

			# clear any existing locks by any other chrome processes (hacky)
			singleton_lock = self.browser_profile.user_data_dir / 'SingletonLock'
			if singleton_lock.exists():
				singleton_lock.unlink()
				self.logger.warning(
					f'⚠️ Multiple chrome processes may be trying to share user_data_dir={self.browser_profile.user_data_dir} which can lead to crashes and profile data corruption!'
				)

		# Create directories for all paths that need them
		dir_paths = {
			'downloads_path': self.browser_profile.downloads_path,
			'record_video_dir': self.browser_profile.record_video_dir,
			'traces_dir': self.browser_profile.traces_dir,
		}

		file_paths = {
			'record_har_path': self.browser_profile.record_har_path,
		}

		# Handle directory creation
		for path_name, path_value in dir_paths.items():
			if path_value:
				try:
					path_obj = Path(path_value).expanduser().resolve()
					path_obj.mkdir(parents=True, exist_ok=True)
					setattr(self.browser_profile, path_name, str(path_obj) if path_name == 'traces_dir' else path_obj)
				except Exception as e:
					self.logger.error(f'❌ Failed to create {path_name} directory {path_value}: {e}')

		# Handle file path parent directory creation
		for path_name, path_value in file_paths.items():
			if path_value:
				try:
					path_obj = Path(path_value).expanduser().resolve()
					path_obj.parent.mkdir(parents=True, exist_ok=True)
				except Exception as e:
					self.logger.error(f'❌ Failed to create parent directory for {path_name} {path_value}: {e}')

	# --- Tab management ---
	async def get_current_page(self) -> Page:
		"""Get the current page + ensure it's not None / closed"""

		if not self.initialized:
			await self.start()

		# get-or-create the browser_context if it's not already set up
		if not self.browser_context:
			await self.start()
			assert self.browser_context, 'BrowserContext is not set up'

		# if either focused page is closed, clear it so we dont use a dead object
		if (not self.human_current_page) or self.human_current_page.is_closed():
			self.human_current_page = None
		if (not self.agent_current_page) or self.agent_current_page.is_closed():
			self.agent_current_page = None

		# if either one is None, fallback to using the other one for both
		self.agent_current_page = self.agent_current_page or self.human_current_page or None
		self.human_current_page = self.human_current_page or self.agent_current_page or None

		# if both are still None, fallback to using the first open tab we can find
		if self.agent_current_page is None:
			if self.browser_context.pages:
				first_available_tab = self.browser_context.pages[0]
				self.agent_current_page = first_available_tab
				self.human_current_page = first_available_tab
			else:
				# if all tabs are closed, open a new one, never allow a context with 0 tabs
				new_tab = await self.create_new_tab()
				self.agent_current_page = new_tab
				self.human_current_page = new_tab

		assert self.agent_current_page is not None, f'{self} Failed to find or create a new page for the agent'
		assert self.human_current_page is not None, f'{self} Failed to find or create a new page for the human'

		return self.agent_current_page

	@property
	def tabs(self) -> list[Page]:
		if not self.browser_context:
			return []
		return list(self.browser_context.pages)

	@require_initialization
	async def new_tab(self, url: str | None = None) -> Page:
		return await self.create_new_tab(url=url)

	@require_initialization
	async def switch_tab(self, tab_index: int) -> Page:
		assert self.browser_context is not None, 'BrowserContext is not set up'
		pages = self.browser_context.pages
		if not pages or tab_index >= len(pages):
			raise IndexError('Tab index out of range')
		page = pages[tab_index]
		self.agent_current_page = page

		# Invalidate cached state since we've switched to a different tab
		# The cached state contains DOM elements and selector map from the previous tab
		self._cached_browser_state_summary = None
		self._cached_clickable_element_hashes = None

		return page

	@require_initialization
	async def wait_for_element(self, selector: str, timeout: int = 10000) -> None:
		page = await self.get_current_page()
		await page.wait_for_selector(selector, state='visible', timeout=timeout)

	@require_initialization
	@time_execution_async('--remove_highlights')
	async def remove_highlights(self):
		"""
		Removes all highlight overlays and labels created by the highlightElement function.
		Handles cases where the page might be closed or inaccessible.
		"""
		page = await self.get_current_page()
		try:
			await page.evaluate(
				"""
				try {
					// Remove the highlight container and all its contents
					const container = document.getElementById('playwright-highlight-container');
					if (container) {
						container.remove();
					}

					// Remove highlight attributes from elements
					const highlightedElements = document.querySelectorAll('[browser-user-highlight-id^="playwright-highlight-"]');
					highlightedElements.forEach(el => {
						el.removeAttribute('browser-user-highlight-id');
					});
				} catch (e) {
					console.error('Failed to remove highlights:', e);
				}
				"""
			)
		except Exception as e:
			self.logger.debug(f'⚠️ Failed to remove highlights (this is usually ok): {type(e).__name__}: {e}')
			# Don't raise the error since this is not critical functionality

	@require_initialization
	async def get_dom_element_by_index(self, index: int) -> DOMElementNode | None:
		"""Get DOM element by index."""
		selector_map = await self.get_selector_map()
		return selector_map.get(index)

	@require_initialization
	@time_execution_async('--click_element_node')
	async def _click_element_node(self, element_node: DOMElementNode) -> str | None:
		"""
		Optimized method to click an element using xpath.
		"""
		page = await self.get_current_page()
		try:
			# Highlight before clicking
			# if element_node.highlight_index is not None:
			# 	await self._update_state(focus_element=element_node.highlight_index)

			element_handle = await self.get_locate_element(element_node)

			if element_handle is None:
				raise Exception(f'Element: {repr(element_node)} not found')

			async def perform_click(click_func):
				"""Performs the actual click, handling both download and navigation scenarios."""

				# only wait the 5s extra for potential downloads if they are enabled
				# TODO: instead of blocking for 5s, we should register a non-block page.on('download') event
				# and then check if the download has been triggered within the event handler
				if self.browser_profile.downloads_path:
					try:
						# Try short-timeout expect_download to detect a file download has been been triggered
						async with page.expect_download(timeout=5000) as download_info:
							await click_func()
						download = await download_info.value
						# Determine file path
						suggested_filename = download.suggested_filename
						unique_filename = await self._get_unique_filename(self.browser_profile.downloads_path, suggested_filename)
						download_path = os.path.join(self.browser_profile.downloads_path, unique_filename)
						await download.save_as(download_path)
						self.logger.info(f'⬇️ Downloaded file to: {download_path}')

						# Track the downloaded file in the session
						self._downloaded_files.append(download_path)
						self.logger.info(f'📁 Added download to session tracking (total: {len(self._downloaded_files)} files)')

						return download_path
					except Exception:
						# If no download is triggered, treat as normal click
						self.logger.debug('No download triggered within timeout. Checking navigation...')
						try:
							await page.wait_for_load_state()
						except Exception as e:
							self.logger.warning(
								f'⚠️ Page {_log_pretty_url(page.url)} failed to finish loading after click: {type(e).__name__}: {e}'
							)
						await self._check_and_handle_navigation(page)
				else:
					# If downloads are disabled, just perform the click
					await click_func()
					try:
						await page.wait_for_load_state()
					except Exception as e:
						self.logger.warning(
							f'⚠️ Page {_log_pretty_url(page.url)} failed to finish loading after click: {type(e).__name__}: {e}'
						)
					await self._check_and_handle_navigation(page)

			try:
				return await perform_click(lambda: element_handle and element_handle.click(timeout=1500))
			except URLNotAllowedError as e:
				raise e
			except Exception as e:
				# Check if it's a context error and provide more info
				if 'Cannot find context with specified id' in str(e) or 'Protocol error' in str(e):
					self.logger.warning(f'⚠️ Element context lost, attempting to re-locate element: {type(e).__name__}')
					# Try to re-locate the element
					element_handle = await self.get_locate_element(element_node)
					if element_handle is None:
						raise Exception(f'Element no longer exists in DOM after context loss: {repr(element_node)}')
					# Try click again with fresh element
					try:
						return await perform_click(lambda: element_handle.click(timeout=1500))
					except Exception:
						# Fall back to JavaScript click
						return await perform_click(lambda: page.evaluate('(el) => el.click()', element_handle))
				else:
					# Original fallback for other errors
					try:
						return await perform_click(lambda: page.evaluate('(el) => el.click()', element_handle))
					except URLNotAllowedError as e:
						raise e
					except Exception as e:
						# Final fallback - try clicking by coordinates if available
						if element_node.viewport_coordinates and element_node.viewport_coordinates.center:
							try:
								self.logger.warning(
									f'⚠️ Element click failed, falling back to coordinate click at ({element_node.viewport_coordinates.center.x}, {element_node.viewport_coordinates.center.y})'
								)
								await page.mouse.click(
									element_node.viewport_coordinates.center.x, element_node.viewport_coordinates.center.y
								)
								try:
									await page.wait_for_load_state()
								except Exception:
									pass
								await self._check_and_handle_navigation(page)
								return None  # Success
							except Exception as coord_e:
								self.logger.error(f'Coordinate click also failed: {type(coord_e).__name__}: {coord_e}')
						raise Exception(f'Failed to click element: {type(e).__name__}: {e}')

		except URLNotAllowedError as e:
			raise e
		except Exception as e:
			raise Exception(f'Failed to click element: {repr(element_node)}. Error: {str(e)}')

	@require_initialization
	@time_execution_async('--get_tabs_info')
	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""
		assert self.browser_context is not None, 'BrowserContext is not set up'
		tabs_info = []
		for page_id, page in enumerate(self.browser_context.pages):
			try:
				title = await self._get_page_title(page)
				tab_info = TabInfo(page_id=page_id, url=page.url, title=title)
			except Exception:
				# page.title() can hang forever on tabs that are crashed/disappeared/about:blank
				# we dont want to try automating those tabs because they will hang the whole script
				self.logger.debug(f'⚠️ Failed to get tab info for tab #{page_id}: {_log_pretty_url(page.url)} (ignoring)')
				tab_info = TabInfo(page_id=page_id, url='about:blank', title='ignore this tab and do not use it')
			tabs_info.append(tab_info)

		return tabs_info

	@retry(timeout=1, retries=0)  # Single attempt with 1s timeout, no retries
	async def _get_page_title(self, page: Page) -> str:
		"""Get page title with timeout protection."""
		return await page.title()

	@retry(timeout=20, retries=1, semaphore_limit=1, semaphore_scope='self')
	async def _set_viewport_size(self, page: Page, viewport: dict[str, int] | ViewportSize) -> None:
		"""Set viewport size with timeout protection."""
		if isinstance(viewport, dict):
			await page.set_viewport_size(ViewportSize(width=viewport['width'], height=viewport['height']))
		else:
			await page.set_viewport_size(viewport)

	@require_initialization
	async def close_tab(self, tab_index: int | None = None) -> None:
		assert self.browser_context is not None, 'BrowserContext is not set up'
		pages = self.browser_context.pages
		if not pages:
			return

		if tab_index is None:
			# to tab_index passed, just close the current agent page
			page = await self.get_current_page()
		else:
			# otherwise close the tab at the given index
			if tab_index >= len(pages) or tab_index < 0:
				raise IndexError(f'Tab index {tab_index} out of range. Available tabs: {len(pages)}')
			page = pages[tab_index]

		await page.close()

		# reset the self.agent_current_page and self.human_current_page references to first available tab
		await self.get_current_page()

	# --- Page navigation ---
	@require_initialization
	async def navigate(self, url: str) -> None:
		# Add https:// if there's no protocol

		normalized_url = normalize_url(url)

		try:
			if self.agent_current_page:
				await self.agent_current_page.goto(normalized_url, wait_until='domcontentloaded')
			else:
				await self.create_new_tab(normalized_url)
		except Exception as e:
			if 'timeout' in str(e).lower():
				self.logger.warning(
					f"⚠️ Loading {_log_pretty_url(normalized_url)} didn't finish after {(self.browser_profile.default_navigation_timeout or 30000) / 1000}s, continuing anyway..."
				)
				# Don't re-raise timeout errors - the page is likely still usable and will continue to load in the background
			else:
				# Re-raise non-timeout errors
				raise

	@require_initialization
	async def refresh(self) -> None:
		if self.agent_current_page and not self.agent_current_page.is_closed():
			await self.agent_current_page.reload()
		else:
			await self.create_new_tab()

	@require_initialization
	async def execute_javascript(self, script: str) -> Any:
		page = await self.get_current_page()
		return await page.evaluate(script)

	async def get_cookies(self) -> list[dict[str, Any]]:
		if self.browser_context:
			return [dict(x) for x in await self.browser_context.cookies()]
		return []

	async def save_cookies(self, *args, **kwargs) -> None:
		"""
		Old name for the new save_storage_state() function.
		"""
		await self.save_storage_state(*args, **kwargs)

	async def _save_cookies_to_file(self, path: Path, cookies: list[dict[str, Any]] | None) -> None:
		if not (path or self.browser_profile.cookies_file):
			return

		if not cookies:
			return

		try:
			cookies_file_path = Path(path or self.browser_profile.cookies_file).expanduser().resolve()
			cookies_file_path.parent.mkdir(parents=True, exist_ok=True)

			# Write to a temporary file first
			cookies = cookies or []
			temp_path = cookies_file_path.with_suffix('.tmp')
			temp_path.write_text(json.dumps(cookies, indent=4))

			try:
				# backup any existing cookies_file if one is already present
				cookies_file_path.replace(cookies_file_path.with_suffix('.json.bak'))
			except Exception:
				pass
			temp_path.replace(cookies_file_path)

			self.logger.info(f'🍪 Saved {len(cookies)} cookies to cookies_file= {_log_pretty_path(cookies_file_path)}')
		except Exception as e:
			self.logger.warning(
				f'❌ Failed to save cookies to cookies_file= {_log_pretty_path(cookies_file_path)}: {type(e).__name__}: {e}'
			)

	async def _save_storage_state_to_file(self, path: str | Path, storage_state: dict[str, Any] | None) -> None:
		try:
			json_path = Path(path).expanduser().resolve()
			json_path.parent.mkdir(parents=True, exist_ok=True)
			assert self.browser_context is not None, 'BrowserContext is not set up'
			storage_state = storage_state or dict(await self.browser_context.storage_state())

			# always atomic merge storage states, never overwrite (so two browsers can share the same storage_state.json)
			merged_storage_state = storage_state
			if json_path.exists():
				try:
					existing_storage_state = json.loads(json_path.read_text())
					merged_storage_state = merge_dicts(existing_storage_state, storage_state)
				except Exception as e:
					self.logger.error(
						f'❌ Failed to merge cookie changes with existing storage_state= {_log_pretty_path(json_path)}: {type(e).__name__}: {e}'
					)
					return

			# write to .tmp file first to avoid partial writes, then mv original to .bak and .tmp to original
			temp_path = json_path.with_suffix('.json.tmp')
			temp_path.write_text(json.dumps(merged_storage_state, indent=4))
			try:
				json_path.replace(json_path.with_suffix('.json.bak'))
			except Exception:
				pass
			temp_path.replace(json_path)

			self.logger.info(
				f'🍪 Saved {len(storage_state["cookies"]) + len(storage_state.get("origins", []))} cookies to storage_state= {_log_pretty_path(json_path)}'
			)
		except Exception as e:
			self.logger.warning(f'❌ Failed to save cookies to storage_state= {_log_pretty_path(path)}: {type(e).__name__}: {e}')

	@retry(timeout=5, retries=1, semaphore_limit=1, semaphore_scope='self')
	async def save_storage_state(self, path: Path | None = None) -> None:
		"""
		Save cookies to the specified path or the configured cookies_file and/or storage_state.
		"""
		await self._unsafe_save_storage_state(path)

	async def _unsafe_save_storage_state(self, path: Path | None = None) -> None:
		"""
		Unsafe storage state save logic without retry protection.
		"""
		if not (path or self.browser_profile.storage_state or self.browser_profile.cookies_file):
			return

		assert self.browser_context is not None, 'BrowserContext is not set up'
		storage_state: dict[str, Any] = dict(await self.browser_context.storage_state())
		cookies = storage_state['cookies']
		has_any_auth_data = cookies or storage_state.get('origins', [])

		# they passed an explicit path, only save to that path and return
		if path and has_any_auth_data:
			if path.name == 'storage_state.json':
				await self._save_storage_state_to_file(path, storage_state)
				return
			else:
				# assume they're using the old API when path meant a cookies_file path,
				# also save new format next to it for convenience to help them migrate
				await self._save_cookies_to_file(path, cookies)
				await self._save_storage_state_to_file(path.parent / 'storage_state.json', storage_state)
				new_path = path.parent / 'storage_state.json'
				self.logger.warning(
					'⚠️ cookies_file is deprecated and will be removed in a future version. '
					f'Please use storage_state="{_log_pretty_path(new_path)}" instead for persisting cookies and other browser state. '
					'See: https://playwright.dev/python/docs/api/class-browsercontext#browser-context-storage-state'
				)
				return

		# save cookies_file if passed a cookies file path or if profile cookies_file is configured
		if cookies and self.browser_profile.cookies_file:
			# only show warning if they configured cookies_file (not if they passed in a path to this function as an arg)
			await self._save_cookies_to_file(self.browser_profile.cookies_file, cookies)
			new_path = self.browser_profile.cookies_file.parent / 'storage_state.json'
			await self._save_storage_state_to_file(new_path, storage_state)
			self.logger.warning(
				'⚠️ cookies_file is deprecated and will be removed in a future version. '
				f'Please use storage_state="{_log_pretty_path(new_path)}" instead for persisting cookies and other browser state. '
				'See: https://playwright.dev/python/docs/api/class-browsercontext#browser-context-storage-state'
			)

		if self.browser_profile.storage_state is None:
			return

		if isinstance(self.browser_profile.storage_state, dict):
			# cookies that never get updated rapidly expire or become invalid,
			# e.g. cloudflare bumps a nonce + does a tiny proof-of-work chain on every request that gets stored back into the cookie
			# if your cookies are frozen in time and don't update, they'll block you as a bot almost immediately
			# if they pass a dict in it means they have to get the updated cookies manually with browser_context.cookies()
			# and persist them manually on every change. most people don't realize they have to do that, so show a warning
			self.logger.warning(
				f'⚠️ storage_state was set as a {type(self.browser_profile.storage_state)} and will not be updated with any cookie changes, use a json file path instead to persist changes'
			)
			return

		if isinstance(self.browser_profile.storage_state, (str, Path)):
			await self._save_storage_state_to_file(self.browser_profile.storage_state, storage_state)
			return

		raise Exception(f'Got unexpected type for storage_state: {type(self.browser_profile.storage_state)}')

	async def load_storage_state(self) -> None:
		"""
		Load cookies from the storage_state or cookies_file and apply them to the browser context.
		"""

		assert self.browser_context, 'Browser context is not initialized, cannot load storage state'

		if self.browser_profile.cookies_file:
			# Show deprecation warning
			self.logger.warning(
				'⚠️ cookies_file is deprecated and will be removed in a future version. '
				'Please use storage_state instead for loading cookies and other browser state. '
				'See: https://playwright.dev/python/docs/api/class-browsercontext#browser-context-storage-state'
			)

			cookies_path = Path(self.browser_profile.cookies_file).expanduser()
			if not cookies_path.is_absolute():
				cookies_path = Path(self.browser_profile.downloads_path or '.').expanduser().resolve() / cookies_path.name

			try:
				cookies_data = json.loads(cookies_path.read_text())
				if cookies_data:
					await self.browser_context.add_cookies(cookies_data)
					self.logger.info(f'🍪 Loaded {len(cookies_data)} cookies from cookies_file= {_log_pretty_path(cookies_path)}')
			except Exception as e:
				self.logger.warning(
					f'❌ Failed to load cookies from cookies_file= {_log_pretty_path(cookies_path)}: {type(e).__name__}: {e}'
				)

		if self.browser_profile.storage_state:
			storage_state = self.browser_profile.storage_state
			if isinstance(storage_state, (str, Path)):
				try:
					storage_state_text = await anyio.Path(storage_state).read_text()
					storage_state = dict(json.loads(storage_state_text))
				except Exception as e:
					self.logger.warning(
						f'❌ Failed to load cookies from storage_state= {_log_pretty_path(storage_state)}: {type(e).__name__}: {e}'
					)
					return

			try:
				assert isinstance(storage_state, dict), f'Got unexpected type for storage_state: {type(storage_state)}'
				await self.browser_context.add_cookies(storage_state['cookies'])
				# TODO: also handle localStroage, IndexedDB, SessionStorage
				# playwright doesn't provide an API for setting these before launch
				# https://playwright.dev/python/docs/auth#session-storage
				# await self.browser_context.add_local_storage(storage_state['localStorage'])
				num_entries = len(storage_state['cookies']) + len(storage_state.get('origins', []))
				if num_entries:
					self.logger.info(f'🍪 Loaded {num_entries} cookies from storage_state= {storage_state}')
			except Exception as e:
				self.logger.warning(f'❌ Failed to load cookies from storage_state= {storage_state}: {type(e).__name__}: {e}')
				return

	async def load_cookies_from_file(self, *args, **kwargs) -> None:
		"""
		Old name for the new load_storage_state() function.
		"""
		await self.load_storage_state(*args, **kwargs)

	@property
	def downloaded_files(self) -> list[str]:
		"""
		Get list of all files downloaded during this browser session.

		Returns:
		    list[str]: List of absolute file paths to downloaded files
		"""
		self.logger.debug(f'📁 Retrieved {len(self._downloaded_files)} downloaded files from session tracking')
		return self._downloaded_files.copy()

	# @property
	# def browser_extension_pages(self) -> list[Page]:
	# 	if not self.browser_context:
	# 		return []
	# 	return [p for p in self.browser_context.pages if p.url.startswith('chrome-extension://')]

	# @property
	# def saved_downloads(self) -> list[Path]:
	# 	"""
	# 	Return a list of files in the downloads_path.
	# 	"""
	# 	return list(Path(self.browser_profile.downloads_path).glob('*'))

	async def _wait_for_stable_network(self):
		pending_requests = set()
		last_activity = asyncio.get_event_loop().time()

		page = await self.get_current_page()

		# Define relevant resource types and content types
		RELEVANT_RESOURCE_TYPES = {
			'document',
			'stylesheet',
			'image',
			'font',
			'script',
			'iframe',
		}

		RELEVANT_CONTENT_TYPES = {
			'text/html',
			'text/css',
			'application/javascript',
			'image/',
			'font/',
			'application/json',
		}

		# Additional patterns to filter out
		IGNORED_URL_PATTERNS = {
			# Analytics and tracking
			'analytics',
			'tracking',
			'telemetry',
			'beacon',
			'metrics',
			# Ad-related
			'doubleclick',
			'adsystem',
			'adserver',
			'advertising',
			# Social media widgets
			'facebook.com/plugins',
			'platform.twitter',
			'linkedin.com/embed',
			# Live chat and support
			'livechat',
			'zendesk',
			'intercom',
			'crisp.chat',
			'hotjar',
			# Push notifications
			'push-notifications',
			'onesignal',
			'pushwoosh',
			# Background sync/heartbeat
			'heartbeat',
			'ping',
			'alive',
			# WebRTC and streaming
			'webrtc',
			'rtmp://',
			'wss://',
			# Common CDNs for dynamic content
			'cloudfront.net',
			'fastly.net',
		}

		async def on_request(request):
			# Filter by resource type
			if request.resource_type not in RELEVANT_RESOURCE_TYPES:
				return

			# Filter out streaming, websocket, and other real-time requests
			if request.resource_type in {
				'websocket',
				'media',
				'eventsource',
				'manifest',
				'other',
			}:
				return

			# Filter out by URL patterns
			url = request.url.lower()
			if any(pattern in url for pattern in IGNORED_URL_PATTERNS):
				return

			# Filter out data URLs and blob URLs
			if url.startswith(('data:', 'blob:')):
				return

			# Filter out requests with certain headers
			headers = request.headers
			if headers.get('purpose') == 'prefetch' or headers.get('sec-fetch-dest') in [
				'video',
				'audio',
			]:
				return

			nonlocal last_activity
			pending_requests.add(request)
			last_activity = asyncio.get_event_loop().time()
			# self.logger.debug(f'Request started: {request.url} ({request.resource_type})')

		async def on_response(response):
			request = response.request
			if request not in pending_requests:
				return

			# Filter by content type if available
			content_type = response.headers.get('content-type', '').lower()

			# Skip if content type indicates streaming or real-time data
			if any(
				t in content_type
				for t in [
					'streaming',
					'video',
					'audio',
					'webm',
					'mp4',
					'event-stream',
					'websocket',
					'protobuf',
				]
			):
				pending_requests.remove(request)
				return

			# Only process relevant content types
			if not any(ct in content_type for ct in RELEVANT_CONTENT_TYPES):
				pending_requests.remove(request)
				return

			# Skip if response is too large (likely not essential for page load)
			content_length = response.headers.get('content-length')
			if content_length and int(content_length) > 5 * 1024 * 1024:  # 5MB
				pending_requests.remove(request)
				return

			nonlocal last_activity
			pending_requests.remove(request)
			last_activity = asyncio.get_event_loop().time()
			# self.logger.debug(f'Request resolved: {request.url} ({content_type})')

		# Attach event listeners
		page.on('request', on_request)
		page.on('response', on_response)

		now = asyncio.get_event_loop().time()
		try:
			# Wait for idle time
			start_time = asyncio.get_event_loop().time()
			while True:
				await asyncio.sleep(0.1)
				now = asyncio.get_event_loop().time()
				if (
					len(pending_requests) == 0
					and (now - last_activity) >= self.browser_profile.wait_for_network_idle_page_load_time
				):
					break
				if now - start_time > self.browser_profile.maximum_wait_page_load_time:
					self.logger.debug(
						f'{self} Network timeout after {self.browser_profile.maximum_wait_page_load_time}s with {len(pending_requests)} '
						f'pending requests: {[r.url for r in pending_requests]}'
					)
					break

		finally:
			# Clean up event listeners
			page.remove_listener('request', on_request)
			page.remove_listener('response', on_response)

		elapsed = now - start_time
		if elapsed > 1:
			self.logger.debug(f'💤 Page network traffic calmed down after {now - start_time:.2f} seconds')

	async def _wait_for_page_and_frames_load(self, timeout_overwrite: float | None = None):
		"""
		Ensures page is fully loaded before continuing.
		Waits for either network to be idle or minimum WAIT_TIME, whichever is longer.
		Also checks if the loaded URL is allowed.
		"""
		# Start timing
		start_time = time.time()

		# Wait for page load
		page = await self.get_current_page()
		try:
			await self._wait_for_stable_network()

			# Check if the loaded URL is allowed
			await self._check_and_handle_navigation(page)
		except URLNotAllowedError as e:
			raise e
		except Exception as e:
			self.logger.warning(
				f'⚠️ Page load for {_log_pretty_url(page.url)} failed due to {type(e).__name__}, continuing anyway...'
			)

		# Calculate remaining time to meet minimum WAIT_TIME
		elapsed = time.time() - start_time
		remaining = max((timeout_overwrite or self.browser_profile.minimum_wait_page_load_time) - elapsed, 0)

		# Skip expensive performance API logging - can cause significant delays on complex pages
		bytes_used = None

		try:
			tab_idx = self.tabs.index(page)
		except ValueError:
			tab_idx = '??'

		extra_delay = ''
		if remaining > 0:
			extra_delay = f', waiting +{remaining:.2f}s for all frames to finish'

		if bytes_used is not None:
			self.logger.info(
				f'➡️ Page navigation [{tab_idx}]{_log_pretty_url(page.url, 40)} used {bytes_used / 1024:.1f} KB in {elapsed:.2f}s{extra_delay}'
			)
		else:
			self.logger.info(f'➡️ Page navigation [{tab_idx}]{_log_pretty_url(page.url, 40)} took {elapsed:.2f}s{extra_delay}')

		# Sleep remaining time if needed
		if remaining > 0:
			await asyncio.sleep(remaining)

	def _is_url_allowed(self, url: str) -> bool:
		"""
		Check if a URL is allowed based on the whitelist configuration. SECURITY CRITICAL.

		Supports optional glob patterns and schemes in allowed_domains:
		- *.example.com will match sub.example.com and example.com
		- *google.com will match google.com, agoogle.com, and www.google.com
		- http*://example.com will match http://example.com, https://example.com
		- chrome-extension://* will match chrome-extension://aaaaaaaaaaaa and chrome-extension://bbbbbbbbbbbbb
		"""

		if not self.browser_profile.allowed_domains:
			return True  # allowed_domains are not configured, allow everything by default

		# Special case: Always allow 'about:blank' new tab page
		if url == 'about:blank':
			return True

		for allowed_domain in self.browser_profile.allowed_domains:
			try:
				if match_url_with_domain_pattern(url, allowed_domain, log_warnings=True):
					# If it's a pattern with wildcards, show a warning
					if '*' in allowed_domain:
						parsed_url = urlparse(url)
						domain = parsed_url.hostname.lower() if parsed_url.hostname else ''
						_log_glob_warning(domain, allowed_domain, self.logger)
					return True
			except AssertionError:
				# This would only happen if about:blank is passed to match_url_with_domain_pattern,
				# which shouldn't occur since we check for it above
				continue

		return False

	async def _check_and_handle_navigation(self, page: Page) -> None:
		"""Check if current page URL is allowed and handle if not."""
		if not self._is_url_allowed(page.url):
			self.logger.warning(f'⛔️ Navigation to non-allowed URL detected: {page.url}')
			try:
				await self.go_back()
			except Exception as e:
				self.logger.error(f'⛔️ Failed to go back after detecting non-allowed URL: {type(e).__name__}: {e}')
			raise URLNotAllowedError(f'Navigation to non-allowed URL: {page.url}')

	async def navigate_to(self, url: str):
		"""Navigate the agent's current tab to a URL"""

		# Add https:// if there's no protocol

		normalized_url = normalize_url(url)

		if not self._is_url_allowed(normalized_url):
			raise BrowserError(f'Navigation to non-allowed URL: {normalized_url}')

		page = await self.get_current_page()
		await page.goto(normalized_url)
		try:
			await page.wait_for_load_state()
		except Exception as e:
			self.logger.warning(
				f'⚠️ Page {_log_pretty_url(page.url)} failed to fully load after navigation: {type(e).__name__}: {e}'
			)

	async def refresh_page(self):
		"""Refresh the agent's current page"""

		page = await self.get_current_page()
		await page.reload()
		try:
			await page.wait_for_load_state()
		except Exception as e:
			self.logger.warning(f'⚠️ Page {_log_pretty_url(page.url)} failed to fully load after refresh: {type(e).__name__}: {e}')

	async def go_back(self):
		"""Navigate the agent's tab back in browser history"""
		try:
			# 10 ms timeout
			page = await self.get_current_page()
			await page.go_back(timeout=10, wait_until='domcontentloaded')

			# await self._wait_for_page_and_frames_load(timeout_overwrite=1.0)
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			self.logger.debug(f'⏮️ Error during go_back: {type(e).__name__}: {e}')

	async def go_forward(self):
		"""Navigate the agent's tab forward in browser history"""
		try:
			page = await self.get_current_page()
			await page.go_forward(timeout=10, wait_until='domcontentloaded')
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			self.logger.debug(f'⏭️ Error during go_forward: {type(e).__name__}: {e}')

	async def close_current_tab(self):
		"""Close the current tab that the agent is working with.

		This closes the tab that the agent is currently using (agent_current_page),
		not necessarily the tab that is visible to the user (human_current_page).
		If they are the same tab, both references will be updated.
		"""
		assert self.browser_context is not None, 'Browser context is not set'
		assert self.agent_current_page is not None, 'Agent current page is not set'

		# Check if this is the foreground tab as well
		is_foreground = self.agent_current_page == self.human_current_page

		# Close the tab
		try:
			await self.agent_current_page.close()
		except Exception as e:
			self.logger.debug(f'⛔️ Error during close_current_tab: {type(e).__name__}: {e}')

		# Clear agent's reference to the closed tab
		self.agent_current_page = None

		# Clear foreground reference if needed
		if is_foreground:
			self.human_current_page = None

		# Switch to the first available tab if any exist
		if self.browser_context.pages:
			await self.switch_to_tab(0)
			# switch_to_tab already updates both tab references

		# Otherwise, the browser will be closed

	async def get_page_html(self) -> str:
		"""Get the HTML content of the agent's current page"""
		page = await self.get_current_page()
		return await page.content()

	async def get_page_structure(self) -> str:
		"""Get a debug view of the page structure including iframes"""
		debug_script = """(() => {
			function getPageStructure(element = document, depth = 0, maxDepth = 10) {
				if (depth >= maxDepth) return '';

				const indent = '  '.repeat(depth);
				let structure = '';

				// Skip certain elements that clutter the output
				const skipTags = new Set(['script', 'style', 'link', 'meta', 'noscript']);

				// Add current element info if it's not the document
				if (element !== document) {
					const tagName = element.tagName.toLowerCase();

					// Skip uninteresting elements
					if (skipTags.has(tagName)) return '';

					const id = element.id ? `#${element.id}` : '';
					const classes = element.className && typeof element.className === 'string' ?
						`.${element.className.split(' ').filter(c => c).join('.')}` : '';

					// Get additional useful attributes
					const attrs = [];
					if (element.getAttribute('role')) attrs.push(`role="${element.getAttribute('role')}"`);
					if (element.getAttribute('aria-label')) attrs.push(`aria-label="${element.getAttribute('aria-label')}"`);
					if (element.getAttribute('type')) attrs.push(`type="${element.getAttribute('type')}"`);
					if (element.getAttribute('name')) attrs.push(`name="${element.getAttribute('name')}"`);
					if (element.getAttribute('src')) {
						const src = element.getAttribute('src');
						attrs.push(`src="${src.substring(0, 50)}${src.length > 50 ? '...' : ''}"`);
					}

					// Add element info
					structure += `${indent}${tagName}${id}${classes}${attrs.length ? ' [' + attrs.join(', ') + ']' : ''}\\n`;

					// Handle iframes specially
					if (tagName === 'iframe') {
						try {
							const iframeDoc = element.contentDocument || element.contentWindow?.document;
							if (iframeDoc) {
								structure += `${indent}  [IFRAME CONTENT]:\\n`;
								structure += getPageStructure(iframeDoc, depth + 2, maxDepth);
							} else {
								structure += `${indent}  [IFRAME: No access - likely cross-origin]\\n`;
							}
						} catch (e) {
							structure += `${indent}  [IFRAME: Access denied - ${e.message}]\\n`;
						}
					}
				}

				// Get all child elements
				const children = element.children || element.childNodes;
				for (const child of children) {
					if (child.nodeType === 1) { // Element nodes only
						structure += getPageStructure(child, depth + 1, maxDepth);
					}
				}

				return structure;
			}

			return getPageStructure();
		})()"""

		page = await self.get_current_page()
		structure = await page.evaluate(debug_script)
		return structure

	@time_execution_async('--get_state_summary')
	@require_initialization
	async def get_state_summary(self, cache_clickable_elements_hashes: bool) -> BrowserStateSummary:
		self.logger.debug('🔄 Starting get_state_summary...')
		"""Get a summary of the current browser state

		This method builds a BrowserStateSummary object that captures the current state
		of the browser, including url, title, tabs, screenshot, and DOM tree.

		Parameters:
		-----------
		cache_clickable_elements_hashes: bool
			If True, cache the clickable elements hashes for the current state.
			This is used to calculate which elements are new to the LLM since the last message,
			which helps reduce token usage.
		"""
		await self._wait_for_page_and_frames_load()
		updated_state = await self._get_updated_state()

		# Find out which elements are new
		# Do this only if url has not changed
		if cache_clickable_elements_hashes:
			# if we are on the same url as the last state, we can use the cached hashes
			if self._cached_clickable_element_hashes and self._cached_clickable_element_hashes.url == updated_state.url:
				# Pointers, feel free to edit in place
				updated_state_clickable_elements = ClickableElementProcessor.get_clickable_elements(updated_state.element_tree)

				for dom_element in updated_state_clickable_elements:
					dom_element.is_new = (
						ClickableElementProcessor.hash_dom_element(dom_element)
						not in self._cached_clickable_element_hashes.hashes  # see which elements are new from the last state where we cached the hashes
					)
			# in any case, we need to cache the new hashes
			self._cached_clickable_element_hashes = CachedClickableElementHashes(
				url=updated_state.url,
				hashes=ClickableElementProcessor.get_clickable_elements_hashes(updated_state.element_tree),
			)

		assert updated_state
		self._cached_browser_state_summary = updated_state

		return self._cached_browser_state_summary

	async def _get_updated_state(self, focus_element: int = -1) -> BrowserStateSummary:
		"""Update and return state."""

		page = await self.get_current_page()

		# Check if current page is still valid, if not switch to another available page
		try:
			# Test if page is still accessible
			await asyncio.wait_for(page.evaluate('1'), timeout=1.0)
		except Exception as e:
			self.logger.debug(f'👋 Current page is not accessible: {type(e).__name__}: {e}')
			raise BrowserError('Browser closed: no valid pages available')

		try:
			self.logger.debug('🧹 Removing highlights...')
			await self.remove_highlights()
			self.logger.debug('🌳 Starting DOM processing...')
			dom_service = DomService(page, logger=self.logger)
			try:
				content = await asyncio.wait_for(
					dom_service.get_clickable_elements(
						focus_element=focus_element,
						viewport_expansion=self.browser_profile.viewport_expansion,
						highlight_elements=self.browser_profile.highlight_elements,
					),
					timeout=45.0,  # 45 second timeout for DOM processing - generous for complex pages
				)
				self.logger.debug('✅ DOM processing completed')
			except TimeoutError:
				self.logger.warning(f'DOM processing timed out after 45 seconds for {page.url}')
				self.logger.warning('🔄 Falling back to minimal DOM state to allow basic navigation...')

				# Create minimal DOM state for basic navigation
				from browser_use.dom.views import DOMElementNode

				minimal_element_tree = DOMElementNode(
					tag_name='body',
					xpath='/body',
					attributes={},
					children=[],
					is_visible=True,
					parent=None,
				)

				from browser_use.dom.views import DOMState

				content = DOMState(element_tree=minimal_element_tree, selector_map={})

			self.logger.debug('📋 Getting tabs info...')
			tabs_info = await self.get_tabs_info()
			self.logger.debug('✅ Tabs info completed')

			# Get all cross-origin iframes within the page and open them in new tabs
			# mark the titles of the new tabs so the LLM knows to check them for additional content
			# unfortunately too buggy for now, too many sites use invisible cross-origin iframes for ads, tracking, youtube videos, social media, etc.
			# and it distracts the bot by opening a lot of new tabs
			# iframe_urls = await dom_service.get_cross_origin_iframes()
			# outer_page = self.agent_current_page
			# for url in iframe_urls:
			# 	if url in [tab.url for tab in tabs_info]:
			# 		continue  # skip if the iframe if we already have it open in a tab
			# 	new_page_id = tabs_info[-1].page_id + 1
			# 	self.logger.debug(f'Opening cross-origin iframe in new tab #{new_page_id}: {url}')
			# 	await self.create_new_tab(url)
			# 	tabs_info.append(
			# 		TabInfo(
			# 			page_id=new_page_id,
			# 			url=url,
			# 			title=f'iFrame opened as new tab, treat as if embedded inside page {outer_page.url}: {page.url}',
			# 			parent_page_url=outer_page.url,
			# 		)
			# 	)

			try:
				self.logger.debug('📸 Starting screenshot...')
				# Reasonable timeout for screenshot
				screenshot_b64 = await self.take_screenshot()
				self.logger.debug('✅ Screenshot completed')
			except Exception as e:
				self.logger.warning(f'Screenshot failed for {page.url}: {type(e).__name__}')
				screenshot_b64 = None

			try:
				self.logger.debug('📏 Getting scroll info...')
				pixels_above, pixels_below = await asyncio.wait_for(self.get_scroll_info(page), timeout=5.0)
				self.logger.debug('✅ Scroll info completed')
			except Exception as e:
				self.logger.warning(f'Failed to get scroll info: {type(e).__name__}')
				pixels_above, pixels_below = 0, 0

			try:
				title = await asyncio.wait_for(page.title(), timeout=5.0)
			except Exception:
				title = 'Title unavailable'

			# Check if this is a minimal fallback state
			browser_errors = []
			if not content.selector_map:  # Empty selector map indicates fallback state
				browser_errors.append(
					f'DOM processing timed out for {page.url} - using minimal state. Basic navigation still available via go_to_url, scroll, and search actions.'
				)

			self.browser_state_summary = BrowserStateSummary(
				element_tree=content.element_tree,
				selector_map=content.selector_map,
				url=page.url,
				title=title,
				tabs=tabs_info,
				screenshot=screenshot_b64,
				pixels_above=pixels_above,
				pixels_below=pixels_below,
				browser_errors=browser_errors,
			)

			self.logger.debug('✅ get_state_summary completed successfully')
			return self.browser_state_summary
		except Exception as e:
			self.logger.error(f'❌ Failed to update browser_state_summary: {type(e).__name__}: {e}')
			# Return last known good state if available
			if hasattr(self, 'browser_state_summary'):
				return self.browser_state_summary
			raise

	# region - Browser Actions
	@require_initialization
	@time_execution_async('--take_screenshot')
	async def take_screenshot(self, full_page: bool = False) -> str:
		"""
		Returns a base64 encoded screenshot of the current page.
		"""
		assert self.agent_current_page is not None, 'Agent current page is not set'

		# page has already loaded by this point, this is just extra for previous action animations/frame loads to settle
		page = await self.get_current_page()

		try:
			await page.wait_for_load_state(timeout=2000)  # 2 second aggressive timeout
		except Exception:
			pass

		try:
			# Check if browser process is still responsive
			if self.browser_pid:
				try:
					proc = psutil.Process(self.browser_pid)
					if not proc.is_running():
						self.logger.warning('🚨 Browser process died, restarting...')
						self._reset_connection_state()
						await self.start()
						page = await self.get_current_page()
				except psutil.NoSuchProcess:
					self.logger.warning('🚨 Browser process not found, restarting...')
					self._reset_connection_state()
					await self.start()
					page = await self.get_current_page()

			# Take screenshot with comprehensive crash detection
			return await self._take_screenshot_hybrid(page)
		except Exception as e:
			# Check for specific crash-related errors
			error_str = str(e).lower()
			if any(
				crash_indicator in error_str
				for crash_indicator in [
					'target crashed',
					'target closed',
					'context has been closed',
					'page has been closed',
					'crashed target',
					'page is closed',
				]
			):
				self.logger.warning(f'🚨 Detected crashed target during screenshot: {type(e).__name__}: {e}')
				self.logger.warning('🔄 Attempting browser restart...')
				try:
					self._reset_connection_state()
					await self.start()
					page = await self.get_current_page()
					return await self._take_screenshot_hybrid(page)
				except Exception as restart_error:
					self.logger.error(
						f'❌ Failed to restart browser after crash: {type(restart_error).__name__}: {restart_error}'
					)
					raise Exception(f'Browser crashed and restart failed: {restart_error}')
			else:
				self.logger.error(f'❌ Failed to take screenshot: {type(e).__name__}: {e}')
				raise

	# region - User Actions

	@staticmethod
	async def _get_unique_filename(directory: str | Path, filename: str) -> str:
		"""Generate a unique filename for downloads by appending (1), (2), etc., if a file already exists."""
		base, ext = os.path.splitext(filename)
		counter = 1
		new_filename = filename
		while os.path.exists(os.path.join(directory, new_filename)):
			new_filename = f'{base} ({counter}){ext}'
			counter += 1
		return new_filename

	async def _start_context_tracing(self):
		"""Start tracing on browser context if trace_path is configured."""
		if self.browser_profile.traces_dir and self.browser_context:
			try:
				self.logger.debug(f'📽️ Starting tracing (will save to: {self.browser_profile.traces_dir})')
				# Don't pass any path to start() - let Playwright handle internal temp files
				await self.browser_context.tracing.start(
					screenshots=True,
					snapshots=True,
					sources=False,  # Reduce trace size
				)
			except Exception as e:
				self.logger.warning(f'Failed to start tracing: {e}')

	@staticmethod
	def _convert_simple_xpath_to_css_selector(xpath: str) -> str:
		"""Converts simple XPath expressions to CSS selectors."""
		if not xpath:
			return ''

		# Remove leading slash if present
		xpath = xpath.lstrip('/')

		# Split into parts
		parts = xpath.split('/')
		css_parts = []

		for part in parts:
			if not part:
				continue

			# Handle custom elements with colons by escaping them
			if ':' in part and '[' not in part:
				base_part = part.replace(':', r'\:')
				css_parts.append(base_part)
				continue

			# Handle index notation [n]
			if '[' in part:
				base_part = part[: part.find('[')]
				# Handle custom elements with colons in the base part
				if ':' in base_part:
					base_part = base_part.replace(':', r'\:')
				index_part = part[part.find('[') :]

				# Handle multiple indices
				indices = [i.strip('[]') for i in index_part.split(']')[:-1]]

				for idx in indices:
					try:
						# Handle numeric indices
						if idx.isdigit():
							index = int(idx) - 1
							base_part += f':nth-of-type({index + 1})'
						# Handle last() function
						elif idx == 'last()':
							base_part += ':last-of-type'
						# Handle position() functions
						elif 'position()' in idx:
							if '>1' in idx:
								base_part += ':nth-of-type(n+2)'
					except ValueError:
						continue

				css_parts.append(base_part)
			else:
				css_parts.append(part)

		base_selector = ' > '.join(css_parts)
		return base_selector

	@classmethod
	@time_execution_sync('--enhanced_css_selector_for_element')
	def _enhanced_css_selector_for_element(cls, element: DOMElementNode, include_dynamic_attributes: bool = True) -> str:
		"""
		Creates a CSS selector for a DOM element, handling various edge cases and special characters.

		Args:
						element: The DOM element to create a selector for

		Returns:
						A valid CSS selector string
		"""
		try:
			# Get base selector from XPath
			css_selector = cls._convert_simple_xpath_to_css_selector(element.xpath)

			# Handle class attributes
			if 'class' in element.attributes and element.attributes['class'] and include_dynamic_attributes:
				# Define a regex pattern for valid class names in CSS
				valid_class_name_pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]*$')

				# Iterate through the class attribute values
				classes = element.attributes['class'].split()
				for class_name in classes:
					# Skip empty class names
					if not class_name.strip():
						continue

					# Check if the class name is valid
					if valid_class_name_pattern.match(class_name):
						# Append the valid class name to the CSS selector
						css_selector += f'.{class_name}'
					else:
						# Skip invalid class names
						continue

			# Expanded set of safe attributes that are stable and useful for selection
			SAFE_ATTRIBUTES = {
				# Data attributes (if they're stable in your application)
				'id',
				# Standard HTML attributes
				'name',
				'type',
				'placeholder',
				# Accessibility attributes
				'aria-label',
				'aria-labelledby',
				'aria-describedby',
				'role',
				# Common form attributes
				'for',
				'autocomplete',
				'required',
				'readonly',
				# Media attributes
				'alt',
				'title',
				'src',
				# Custom stable attributes (add any application-specific ones)
				'href',
				'target',
			}

			if include_dynamic_attributes:
				dynamic_attributes = {
					'data-id',
					'data-qa',
					'data-cy',
					'data-testid',
				}
				SAFE_ATTRIBUTES.update(dynamic_attributes)

			# Handle other attributes
			for attribute, value in element.attributes.items():
				if attribute == 'class':
					continue

				# Skip invalid attribute names
				if not attribute.strip():
					continue

				if attribute not in SAFE_ATTRIBUTES:
					continue

				# Escape special characters in attribute names
				safe_attribute = attribute.replace(':', r'\:')

				# Handle different value cases
				if value == '':
					css_selector += f'[{safe_attribute}]'
				elif any(char in value for char in '"\'<>`\n\r\t'):
					# Use contains for values with special characters
					# For newline-containing text, only use the part before the newline
					if '\n' in value:
						value = value.split('\n')[0]
					# Regex-substitute *any* whitespace with a single space, then strip.
					collapsed_value = re.sub(r'\s+', ' ', value).strip()
					# Escape embedded double-quotes.
					safe_value = collapsed_value.replace('"', '\\"')
					css_selector += f'[{safe_attribute}*="{safe_value}"]'
				else:
					css_selector += f'[{safe_attribute}="{value}"]'

			return css_selector

		except Exception:
			# Fallback to a more basic selector if something goes wrong
			tag_name = element.tag_name or '*'
			return f"{tag_name}[highlight_index='{element.highlight_index}']"

	@require_initialization
	@time_execution_async('--is_visible')
	async def _is_visible(self, element: ElementHandle) -> bool:
		"""
		Checks if an element is visible on the page.
		We use our own implementation instead of relying solely on Playwright's is_visible() because
		of edge cases with CSS frameworks like Tailwind. When elements use Tailwind's 'hidden' class,
		the computed style may return display as '' (empty string) instead of 'none', causing Playwright
		to incorrectly consider hidden elements as visible. By additionally checking the bounding box
		dimensions, we catch elements that have zero width/height regardless of how they were hidden.
		"""
		is_hidden = await element.is_hidden()
		bbox = await element.bounding_box()

		return not is_hidden and bbox is not None and bbox['width'] > 0 and bbox['height'] > 0

	@require_initialization
	@time_execution_async('--get_locate_element')
	async def get_locate_element(self, element: DOMElementNode) -> ElementHandle | None:
		page = await self.get_current_page()
		current_frame = page

		# Start with the target element and collect all parents
		parents: list[DOMElementNode] = []
		current = element
		while current.parent is not None:
			parent = current.parent
			parents.append(parent)
			current = parent

		# Reverse the parents list to process from top to bottom
		parents.reverse()

		# Process all iframe parents in sequence
		iframes = [item for item in parents if item.tag_name == 'iframe']
		for parent in iframes:
			css_selector = self._enhanced_css_selector_for_element(
				parent,
				include_dynamic_attributes=self.browser_profile.include_dynamic_attributes,
			)
			# Use CSS selector if available, otherwise fall back to XPath
			if css_selector:
				current_frame = current_frame.frame_locator(css_selector)
			else:
				self.logger.debug(f'Using XPath for iframe: {parent.xpath}')
				current_frame = current_frame.frame_locator(f'xpath={parent.xpath}')

		css_selector = self._enhanced_css_selector_for_element(
			element, include_dynamic_attributes=self.browser_profile.include_dynamic_attributes
		)

		try:
			if isinstance(current_frame, FrameLocator):
				if css_selector:
					element_handle = await current_frame.locator(css_selector).element_handle()
				else:
					# Fall back to XPath when CSS selector is empty
					self.logger.debug(f'CSS selector empty, falling back to XPath: {element.xpath}')
					element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
				return element_handle
			else:
				# Try CSS selector first if available
				if css_selector:
					element_handle = await current_frame.query_selector(css_selector)
				else:
					# Fall back to XPath
					self.logger.debug(f'CSS selector empty, falling back to XPath: {element.xpath}')
					element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
				if element_handle:
					is_visible = await self._is_visible(element_handle)
					if is_visible:
						await element_handle.scroll_into_view_if_needed()
					return element_handle
				return None
		except Exception as e:
			# If CSS selector failed, try XPath as fallback
			if css_selector and 'CSS.escape' not in str(e):
				try:
					self.logger.debug(f'CSS selector failed, trying XPath fallback: {element.xpath}')
					if isinstance(current_frame, FrameLocator):
						element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
					else:
						element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()

					if element_handle:
						is_visible = await self._is_visible(element_handle)
						if is_visible:
							await element_handle.scroll_into_view_if_needed()
						return element_handle
				except Exception as xpath_e:
					self.logger.error(
						f'❌ Failed to locate element with both CSS ({css_selector}) and XPath ({element.xpath}): {type(xpath_e).__name__}: {xpath_e}'
					)
					return None
			else:
				self.logger.error(
					f'❌ Failed to locate element {css_selector or element.xpath} on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}'
				)
				return None

	@require_initialization
	@time_execution_async('--get_locate_element_by_xpath')
	async def get_locate_element_by_xpath(self, xpath: str) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided XPath.
		"""
		page = await self.get_current_page()

		try:
			# Use XPath to locate the element
			element_handle = await page.query_selector(f'xpath={xpath}')
			if element_handle:
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed()
				return element_handle
			return None
		except Exception as e:
			self.logger.error(f'❌ Failed to locate xpath {xpath} on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}')
			return None

	@require_initialization
	@time_execution_async('--get_locate_element_by_css_selector')
	async def get_locate_element_by_css_selector(self, css_selector: str) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided CSS selector.
		"""
		page = await self.get_current_page()

		try:
			# Use CSS selector to locate the element
			element_handle = await page.query_selector(css_selector)
			if element_handle:
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed()
				return element_handle
			return None
		except Exception as e:
			self.logger.error(
				f'❌ Failed to locate element {css_selector} on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}'
			)
			return None

	@require_initialization
	@time_execution_async('--get_locate_element_by_text')
	async def get_locate_element_by_text(
		self, text: str, nth: int | None = 0, element_type: str | None = None
	) -> ElementHandle | None:
		"""
		Locates an element on the page using the provided text.
		If `nth` is provided, it returns the nth matching element (0-based).
		If `element_type` is provided, filters by tag name (e.g., 'button', 'span').
		"""
		page = await self.get_current_page()
		try:
			# handle also specific element type or use any type.
			selector = f'{element_type or "*"}:text("{text}")'
			elements = await page.query_selector_all(selector)
			# considering only visible elements
			elements = [el for el in elements if await self._is_visible(el)]

			if not elements:
				self.logger.error(f"❌ No visible element with text '{text}' found on page {_log_pretty_url(page.url)}.")
				return None

			if nth is not None:
				if 0 <= nth < len(elements):
					element_handle = elements[nth]
				else:
					self.logger.error(
						f"❌ Visible element with text '{text}' not found at index #{nth} on page {_log_pretty_url(page.url)}."
					)
					return None
			else:
				element_handle = elements[0]

			is_visible = await self._is_visible(element_handle)
			if is_visible:
				await element_handle.scroll_into_view_if_needed()
			return element_handle
		except Exception as e:
			self.logger.error(
				f"❌ Failed to locate element by text '{text}' on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}"
			)
			return None

	@require_initialization
	@time_execution_async('--input_text_element_node')
	async def _input_text_element_node(self, element_node: DOMElementNode, text: str):
		"""
		Input text into an element with proper error handling and state management.
		Handles different types of input fields and ensures proper element state before input.
		"""
		try:
			element_handle = await self.get_locate_element(element_node)

			if element_handle is None:
				raise BrowserError(f'Element: {repr(element_node)} not found')

			# Ensure element is ready for input
			try:
				await element_handle.wait_for_element_state('stable', timeout=1000)
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed(timeout=1000)
			except Exception:
				pass

			# let's first try to click and type
			try:
				await element_handle.evaluate('el => {el.textContent = ""; el.value = "";}')
				await element_handle.click()
				await asyncio.sleep(0.1)  # Increased sleep time
				page = await self.get_current_page()
				await page.keyboard.type(text)
				return
			except Exception as e:
				self.logger.debug(f'Input text with click and type failed, trying element handle method: {e}')
				pass

			# Get element properties to determine input method
			tag_handle = await element_handle.get_property('tagName')
			tag_name = (await tag_handle.json_value()).lower()
			is_contenteditable = await element_handle.get_property('isContentEditable')
			readonly_handle = await element_handle.get_property('readOnly')
			disabled_handle = await element_handle.get_property('disabled')

			readonly = await readonly_handle.json_value() if readonly_handle else False
			disabled = await disabled_handle.json_value() if disabled_handle else False

			try:
				if (await is_contenteditable.json_value() or tag_name == 'input') and not (readonly or disabled):
					await element_handle.evaluate('el => {el.textContent = ""; el.value = "";}')
					await element_handle.type(text, delay=5)
				else:
					await element_handle.fill(text)
			except Exception as e:
				self.logger.error(f'Error during input text into element: {type(e).__name__}: {e}')
				raise BrowserError(f'Failed to input text into element: {repr(element_node)}')

		except Exception as e:
			# Get current page URL safely for error message
			try:
				page = await self.get_current_page()
				page_url = _log_pretty_url(page.url)
			except Exception:
				page_url = 'unknown page'

			self.logger.debug(
				f'❌ Failed to input text into element: {repr(element_node)} on page {page_url}: {type(e).__name__}: {e}'
			)
			raise BrowserError(f'Failed to input text into index {element_node.highlight_index}')

	@require_initialization
	@time_execution_async('--switch_to_tab')
	async def switch_to_tab(self, page_id: int) -> Page:
		"""Switch to a specific tab by its page_id (aka tab index exposed to LLM)"""
		assert self.browser_context is not None, 'Browser context is not set'
		pages = self.browser_context.pages

		if page_id >= len(pages):
			raise BrowserError(f'No tab found with page_id: {page_id}')

		page = pages[page_id]

		# Check if the tab's URL is allowed before switching
		if not self._is_url_allowed(page.url):
			raise BrowserError(f'Cannot switch to tab with non-allowed URL: {page.url}')

		# Update both tab references - agent wants this tab, and it's now in the foreground
		self.agent_current_page = page
		await self.agent_current_page.bring_to_front()  # crucial for screenshot to work

		# in order for a human watching to be able to follow along with what the agent is doing
		# update the human's active tab to match the agent's
		if self.human_current_page != page:
			# TODO: figure out how to do this without bringing the entire window to the foreground and stealing foreground app focus
			# might require browser-use extension loaded into the browser so we can use chrome.tabs extension APIs
			# await page.bring_to_front()
			pass

		self.human_current_page = page

		# Invalidate cached state since we've switched to a different tab
		# The cached state contains DOM elements and selector map from the previous tab
		self._cached_browser_state_summary = None
		self._cached_clickable_element_hashes = None

		try:
			await page.wait_for_load_state()
		except Exception as e:
			self.logger.warning(f'⚠️ New page failed to fully load: {type(e).__name__}: {e}')

		# Set the viewport size for the tab
		if self.browser_profile.viewport:
			await page.set_viewport_size(self.browser_profile.viewport)

		return page

	@time_execution_async('--create_new_tab')
	async def create_new_tab(self, url: str | None = None) -> Page:
		"""Create a new tab and optionally navigate to a URL"""

		# Add https:// if there's no protocol
		normalized_url = url
		if url:
			normalized_url = normalize_url(url)

			if not self._is_url_allowed(normalized_url):
				raise BrowserError(f'Cannot create new tab with non-allowed URL: {normalized_url}')

		try:
			assert self.browser_context is not None, 'Browser context is not set'
			new_page = await self.browser_context.new_page()
		except Exception:
			self.initialized = False
			self.browser_context = None  # Clear the closed context

		if not self.initialized or not self.browser_context:
			# If we were initialized but lost connection, reset state first to avoid infinite loops
			if self.initialized and not self.browser_context:
				self.logger.warning(
					f'💔 Browser {self._connection_str} disconnected while trying to create a new tab, reconnecting...'
				)
				self._reset_connection_state()
			await self.start()
			assert self.browser_context, 'Browser context is not set'
			new_page = await self.browser_context.new_page()

		# Update agent tab reference
		self.agent_current_page = new_page

		# Update human tab reference if there is no human tab yet
		if (not self.human_current_page) or self.human_current_page.is_closed():
			self.human_current_page = new_page

		tab_idx = self.tabs.index(new_page)
		try:
			await new_page.wait_for_load_state()
		except Exception as e:
			self.logger.warning(
				f'⚠️ New page [{tab_idx}]{_log_pretty_url(new_page.url)} failed to fully load: {type(e).__name__}: {e}'
			)

		# Set the viewport size for the new tab
		if self.browser_profile.viewport:
			await new_page.set_viewport_size(self.browser_profile.viewport)

		if normalized_url:
			try:
				await new_page.goto(normalized_url, wait_until='domcontentloaded')
				await self._wait_for_page_and_frames_load(timeout_overwrite=1)
			except Exception as e:
				self.logger.error(f'❌ Error navigating to {normalized_url}: {type(e).__name__}: {e} (proceeding anyway...)')

		assert self.human_current_page is not None
		assert self.agent_current_page is not None
		# if url:  # sometimes this does not pass because JS or HTTP redirects the page really fast
		# 	assert self.agent_current_page.url == url
		# else:
		# 	assert self.agent_current_page.url == 'about:blank'

		# if there are any unused about:blank tabs after we open a new tab, close them to clean up unused tabs
		assert self.browser_context is not None, 'Browser context is not set'
		# hacky way to be sure we only close our own tabs, check the title of the tab for our BrowserSession name
		title_of_our_setup_tab = (
			f'Starting agent {str(self.id)[-4:]}...'  # set up by self._show_dvd_screensaver_loading_animation()
		)
		for page in self.browser_context.pages:
			page_title = await page.title()
			if page.url == 'about:blank' and page != self.agent_current_page and page_title == title_of_our_setup_tab:
				await page.close()
				self.human_current_page = (  # in case we just closed the human's tab, fix the refs
					self.human_current_page if not self.human_current_page.is_closed() else self.agent_current_page
				)
				break  # only close a maximum of one unused about:blank tab,
				# if multiple parallel agents share one BrowserSession
				# closing every new_page() tab (which start on about:blank) causes lots of problems
				# (the title check is not enough when they share a single BrowserSession)

		return new_page

	# region - Helper methods for easier access to the DOM

	@require_initialization
	async def get_selector_map(self) -> SelectorMap:
		if self._cached_browser_state_summary is None:
			return {}
		return self._cached_browser_state_summary.selector_map

	@require_initialization
	async def get_element_by_index(self, index: int) -> ElementHandle | None:
		selector_map = await self.get_selector_map()
		element_handle = await self.get_locate_element(selector_map[index])
		return element_handle

	async def is_file_input_by_index(self, index: int) -> bool:
		try:
			selector_map = await self.get_selector_map()
			node = selector_map[index]
			return self.is_file_input(node)
		except Exception as e:
			self.logger.debug(f'❌ Error in is_file_input(index={index}): {type(e).__name__}: {e}')
			return False

	@staticmethod
	def is_file_input(node: DOMElementNode) -> bool:
		return (
			isinstance(node, DOMElementNode)
			and getattr(node, 'tag_name', '').lower() == 'input'
			and node.attributes.get('type', '').lower() == 'file'
		)

	@require_initialization
	async def find_file_upload_element_by_index(
		self, index: int, max_height: int = 3, max_descendant_depth: int = 3
	) -> DOMElementNode | None:
		"""
		Find the closest file input to the selected element by traversing the DOM bottom-up.
		At each level (up to max_height ancestors):
		- Check the current node itself
		- Check all its children/descendants up to max_descendant_depth
		- Check all siblings (and their descendants up to max_descendant_depth)
		Returns the first file input found, or None if not found.
		"""
		try:
			selector_map = await self.get_selector_map()
			if index not in selector_map:
				return None

			candidate_element = selector_map[index]

			def find_file_input_in_descendants(node: DOMElementNode, depth: int) -> DOMElementNode | None:
				if depth < 0 or not isinstance(node, DOMElementNode):
					return None
				if self.is_file_input(node):
					return node
				for child in getattr(node, 'children', []):
					result = find_file_input_in_descendants(child, depth - 1)
					if result:
						return result
				return None

			current = candidate_element
			for _ in range(max_height + 1):  # include the candidate itself
				# 1. Check the current node itself
				if self.is_file_input(current):
					return current
				# 2. Check all descendants of the current node
				result = find_file_input_in_descendants(current, max_descendant_depth)
				if result:
					return result
				# 3. Check all siblings and their descendants
				parent = getattr(current, 'parent', None)
				if parent:
					for sibling in getattr(parent, 'children', []):
						if sibling is current:
							continue
						if self.is_file_input(sibling):
							return sibling
						result = find_file_input_in_descendants(sibling, max_descendant_depth)
						if result:
							return result
				current = parent
				if not current:
					break
			return None
		except Exception as e:
			page = await self.get_current_page()
			self.logger.debug(
				f'❌ Error in find_file_upload_element_by_index(index={index}) on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}'
			)
			return None

	@require_initialization
	async def get_scroll_info(self, page: Page) -> tuple[int, int]:
		"""Get scroll position information for the current page."""
		scroll_y = await page.evaluate('window.scrollY')
		viewport_height = await page.evaluate('window.innerHeight')
		total_height = await page.evaluate('document.documentElement.scrollHeight')
		pixels_above = scroll_y
		pixels_below = total_height - (scroll_y + viewport_height)
		return pixels_above, pixels_below

	@require_initialization
	async def _scroll_container(self, pixels: int) -> None:
		"""Scroll the element that truly owns vertical scroll.Starts at the focused node ➜ climbs to the first big, scroll-enabled ancestor otherwise picks the first scrollable element or the root, then calls `element.scrollBy` (or `window.scrollBy` for the root) by the supplied pixel value."""

		# An element can *really* scroll if: overflow-y is auto|scroll|overlay, it has more content than fits, its own viewport is not a postage stamp (more than 50 % of window).
		SMART_SCROLL_JS = """(dy) => {
			const bigEnough = el => el.clientHeight >= window.innerHeight * 0.5;
			const canScroll = el =>
				el &&
				/(auto|scroll|overlay)/.test(getComputedStyle(el).overflowY) &&
				el.scrollHeight > el.clientHeight &&
				bigEnough(el);

			let el = document.activeElement;
			while (el && !canScroll(el) && el !== document.body) el = el.parentElement;

			el = canScroll(el)
					? el
					: [...document.querySelectorAll('*')].find(canScroll)
					|| document.scrollingElement
					|| document.documentElement;

			if (el === document.scrollingElement ||
				el === document.documentElement ||
				el === document.body) {
				window.scrollBy(0, dy);
			} else {
				el.scrollBy({ top: dy, behavior: 'auto' });
			}
		}"""
		page = await self.get_current_page()
		await page.evaluate(SMART_SCROLL_JS, pixels)

	# --- DVD Screensaver Loading Animation Helper ---
	async def _show_dvd_screensaver_loading_animation(self, page: Page) -> None:
		"""
		Injects a DVD screensaver-style bouncing logo loading animation overlay into the given Playwright Page.
		This is used to visually indicate that the browser is setting up or waiting.
		"""
		if CONFIG.IS_IN_EVALS:
			# dont bother wasting CPU showing animations during evals
			return

		# we could enforce this, but maybe it's useful to be able to show it on other tabs?
		# assert page.url == 'about:blank', 'DVD screensaver loading animation should only be shown on about:blank tabs'

		# all in one JS function for speed, we want as few roundtrip CDP calls as possible
		# between opening the tab and showing the animation
		await page.evaluate(
			"""(browser_session_label) => {
			const animated_title = `Starting agent ${browser_session_label}...`;
			if (document.title === animated_title) {
				return;      // already run on this tab, dont run again
			}
			document.title = animated_title;

			// Create the main overlay
			const loadingOverlay = document.createElement('div');
			loadingOverlay.id = 'pretty-loading-animation';
			loadingOverlay.style.position = 'fixed';
			loadingOverlay.style.top = '0';
			loadingOverlay.style.left = '0';
			loadingOverlay.style.width = '100vw';
			loadingOverlay.style.height = '100vh';
			loadingOverlay.style.background = '#000';
			loadingOverlay.style.zIndex = '99999';
			loadingOverlay.style.overflow = 'hidden';

			// Create the image element
			const img = document.createElement('img');
			img.src = 'https://cf.browser-use.com/logo.svg';
			img.alt = 'Browser-Use';
			img.style.width = '200px';
			img.style.height = 'auto';
			img.style.position = 'absolute';
			img.style.left = '0px';
			img.style.top = '0px';
			img.style.zIndex = '2';
			img.style.opacity = '0.8';

			loadingOverlay.appendChild(img);
			document.body.appendChild(loadingOverlay);

			// DVD screensaver bounce logic
			let x = Math.random() * (window.innerWidth - 300);
			let y = Math.random() * (window.innerHeight - 300);
			let dx = 1.2 + Math.random() * 0.4; // px per frame
			let dy = 1.2 + Math.random() * 0.4;
			// Randomize direction
			if (Math.random() > 0.5) dx = -dx;
			if (Math.random() > 0.5) dy = -dy;

			function animate() {
				const imgWidth = img.offsetWidth || 300;
				const imgHeight = img.offsetHeight || 300;
				x += dx;
				y += dy;

				if (x <= 0) {
					x = 0;
					dx = Math.abs(dx);
				} else if (x + imgWidth >= window.innerWidth) {
					x = window.innerWidth - imgWidth;
					dx = -Math.abs(dx);
				}
				if (y <= 0) {
					y = 0;
					dy = Math.abs(dy);
				} else if (y + imgHeight >= window.innerHeight) {
					y = window.innerHeight - imgHeight;
					dy = -Math.abs(dy);
				}

				img.style.left = `${x}px`;
				img.style.top = `${y}px`;

				requestAnimationFrame(animate);
			}
			animate();

			// Responsive: update bounds on resize
			window.addEventListener('resize', () => {
				x = Math.min(x, window.innerWidth - img.offsetWidth);
				y = Math.min(y, window.innerHeight - img.offsetHeight);
			});

			// Add a little CSS for smoothness
			const style = document.createElement('style');
			style.innerHTML = `
				#pretty-loading-animation {
					/*backdrop-filter: blur(2px) brightness(0.9);*/
				}
				#pretty-loading-animation img {
					user-select: none;
					pointer-events: none;
				}
			`;
			document.head.appendChild(style);
		}""",
			str(self.id)[-4:],
		)
