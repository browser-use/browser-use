from __future__ import annotations

import asyncio
import atexit
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

import anyio
from typing_extensions import deprecated

from browser_use.config import CONFIG
from browser_use.observability import observe_debug
from browser_use.utils import _log_pretty_path, _log_pretty_url

from .utils import normalize_url

os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'  # https://github.com/microsoft/playwright/issues/35972

import psutil
from bubus.helpers import retry
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
	PageInfo,
	TabInfo,
	URLNotAllowedError,
)
from browser_use.dom.clickable_element_processor.service import ClickableElementProcessor
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, SelectorMap
from browser_use.utils import (
	is_new_tab_page,
	match_url_with_domain_pattern,
	merge_dicts,
	time_execution_async,
	time_execution_sync,
)

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


def require_healthy_browser(usable_page=True, reopen_page=True):
	"""Decorator for BrowserSession methods to ensure browser/page is healthy before execution.

	This ridiculous overengineered logic is necessary to work around playwright's completely broken handling of crashed pages.
	- When a page is loading, playwright calls will hang indefinitely.
	- When a page is blocked by a JS while(true){}, playwright calls will hang indefinitely.
	- When a page is unresponsive because the system is out of CPU or Memory, playwright calls will hang indefinitely.
	asyncio.wait(...) is the most extreme method available to try and terminate asyncio tasks in python, but even this does not work
	because it's likely the underlying playwright node.js process that's crashing and synchronously blocking the python side.
	This is why we must use CDP directly and skip playwright eventually.

	Args:
		usable_page: If True, check that the agent_current_page is valid and responsive before executing the method, if invalid log it but continue anyway
		reopen_page: If True, attempt to reopen the page if it's crashed, invalid, or unresponsive (only applies if usable_page=True)
	"""

	def decorator(func):
		assert asyncio.iscoroutinefunction(func), '@require_healthy_browser only supports async methods'

		@wraps(func)
		async def wrapper(self: BrowserSession, *args, **kwargs):
			try:
				if not self.initialized or not self.browser_context:
					# raise RuntimeError('BrowserSession(...).start() must be called first to launch or connect to the browser')
					await self.start()  # just start it automatically if not already started

				if not self.agent_current_page or self.agent_current_page.is_closed():
					self.agent_current_page = (
						self.browser_context.pages[0] if (self.browser_context and len(self.browser_context.pages) > 0) else None
					)

				# always require at least one tab to be open for the context to be considered usable, dont check responsiveness unless usable_page=True
				if not self.agent_current_page or self.agent_current_page.is_closed():
					# Create new page directly to avoid circular dependency
					assert self.browser_context is not None, 'Browser context is not set'
					new_page = await self.browser_context.new_page()
					self.agent_current_page = new_page
					if (not self.human_current_page) or self.human_current_page.is_closed():
						self.human_current_page = new_page
					if self.browser_profile.viewport:
						await new_page.set_viewport_size(self.browser_profile.viewport)

				assert self.agent_current_page and not self.agent_current_page.is_closed()

				if not hasattr(self, '_cached_browser_state_summary'):
					raise RuntimeError('BrowserSession(...).start() must be called first to initialize the browser session')

				# Check page responsiveness if usable_page=True
				if usable_page:
					# Skip if already in recovery to prevent infinite recursion
					if hasattr(self, '_in_recovery') and self._in_recovery:
						# self.logger.debug('Already in recovery, skipping responsiveness check')
						return await func(self, *args, **kwargs)

					# Skip responsiveness check for about:blank pages - they're always responsive (I hope, otherwise something is very wrong)
					if self.agent_current_page and is_new_tab_page(self.agent_current_page.url):
						# self.logger.debug('Skipping responsiveness check for about:blank page')
						return await func(self, *args, **kwargs)

					# Check if page is responsive
					# self.logger.debug(f'Checking page responsiveness for {func.__name__}...')
					if await self._is_page_responsive(self.agent_current_page):
						# self.logger.debug('✅ Confirmed page is responsive')
						pass
					else:
						# Page is unresponsive - handle recovery
						if not reopen_page:
							self.logger.warning(
								'⚠️ Page unresponsive but @require_healthy_browser(reopen_page=False), attempting to continue anyway...'
							)
						else:
							try:
								await self._recover_unresponsive_page(
									func.__name__, timeout_ms=int(self.browser_profile.default_navigation_timeout or 5000) + 5_000
								)
								self.logger.debug(
									f'🤕 Crashed page recovery finished, attempting to continue with {func.__name__}() on {_log_pretty_url(self.agent_current_page.url)}...'
								)
							except Exception as e:
								self.logger.warning(
									f'❌ Crashed page recovery failed, could not run {func.__name__}(), page is stuck unresponsive on {_log_pretty_url(self.agent_current_page.url)}...'
								)
								raise  # Re-raise to let retry decorator / callsite handle it

				return await func(self, *args, **kwargs)

			except Exception as e:
				# Check if this is a TargetClosedError or similar connection error
				if 'TargetClosedError' in str(type(e)) or 'browser has been closed' in str(e):
					self.logger.warning(
						f'✂️ Browser {self._connection_str} disconnected before BrowserSession.{func.__name__}() could run... (error: {type(e).__name__}: {e})'
					)
					self._reset_connection_state()
				# Re-raise all hard errors so the caller can handle them appropriately
				raise

		return wrapper

	return decorator


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
	_auto_download_pdfs: bool = PrivateAttr(default=True)  # Auto-download PDFs when detected
	_subprocess: Any = PrivateAttr(default=None)  # Chrome subprocess reference for error handling

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
		if (
			self._logger is None or self.browser_context is None
		):  # keep updating the name pre-init because our id and str(self) can change
			self._logger = logging.getLogger(f'browser_use.{self}')
		return self._logger

	def __repr__(self) -> str:
		is_copy = '©' if self._original_browser_session else '#'
		port_number_or_pid = (
			(self.cdp_url or self.wss_url or str(self.browser_pid) or 'playwright').rsplit(':', 1)[-1].split('/', 1)[0]
		)
		return f'BrowserSession🆂 {self.id[-4:]}:{port_number_or_pid} {is_copy}{str(id(self))[-2:]} ({self._connection_str}, profile={self.browser_profile})'

	def __str__(self) -> str:
		is_copy = '©' if self._original_browser_session else '#'
		port_number_or_pid = (
			(self.cdp_url or self.wss_url or str(self.browser_pid) or 'playwright').rsplit(':', 1)[-1].split('/', 1)[0]
		)
		return f'BrowserSession🆂 {self.id[-4:]}:{port_number_or_pid} {is_copy}{str(id(self))[-2:]}'  # ' 🅟 {str(id(self.agent_current_page))[-2:]}'

	# better to force people to get it from the right object, "only one way to do it" is better python
	# def __getattr__(self, key: str) -> Any:
	# 	"""
	# 	fall back to getting any attrs from the underlying self.browser_profile when not defined on self.
	# 	(extra kwargs passed e.g. BrowserSession(extra_kwarg=124) on init get saved into self.browser_profile on validation,
	# 	so this also allows you to read those: browser_session.extra_kwarg => browser_session.browser_profile.extra_kwarg)
	# 	"""
	# 	return getattr(self.browser_profile, key)

	@observe_debug(name='browser.session.start')
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
			# Note: prepare_user_data_dir() is called later in _unsafe_setup_new_browser_context()
			# after the temp directory is created. Calling it here is premature.

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
					self.logger.debug(f'🍂 Killed browser subprocess gracefully browser_pid={self.browser_pid} {_hint}')
				except (psutil.NoSuchProcess, psutil.AccessDenied, TimeoutError):
					pass

				# Kill all child processes first (recursive)
				for child in browser_proc.children(recursive=True):
					try:
						# self.logger.debug(f'Force killing child process: {child.pid} ({child.name()})')
						child.kill()
						self.logger.debug(f'☠️ Force-killed hung browser helper subprocess pid={child.pid} {_hint}')
					except (psutil.NoSuchProcess, psutil.AccessDenied):
						pass

				# Kill the main browser process
				# self.logger.debug(f'Force killing browser process: {self.browser_pid}')
				browser_proc.kill()
				self.logger.debug(f'☠️ Force-killed hung browser subprocess browser_pid={self.browser_pid} {_hint}')
			except psutil.NoSuchProcess:
				pass
			except Exception as e:
				self.logger.warning(f'⚠️ Error force-killing browser in BrowserSession.__del__: {type(e).__name__}: {e}')

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

			self.logger.info(f'🎥 Saving browser_context trace to {final_trace_path}...')
			await self.browser_context.tracing.stop(path=str(final_trace_path))

	@observe_debug(name='connect_or_launch_browser')
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

	# Removed _take_screenshot_hybrid - merged into take_screenshot

	@observe_debug(name='setup_playwright')
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
		# self.logger.debug(f'👾 Found Chrome subprocess browser_pid={self.browser_pid} open CDP port: --remote-debugging-port={debug_port}')
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

		self.cdp_url = self.cdp_url or f'http://127.0.0.1:{debug_port}/'

		# Wait for CDP port to become available (Chrome might still be starting)
		import httpx

		# Add initial delay to give Chrome time to start up before first check
		await asyncio.sleep(2)

		async with httpx.AsyncClient() as client:
			for i in range(30):  # 30 second timeout
				# First check if the Chrome process has exited
				try:
					chrome_process = psutil.Process(pid=self.browser_pid)
					if not chrome_process.is_running():
						# If we have a subprocess reference, try to get stderr
						if hasattr(self, '_subprocess') and self._subprocess:
							stderr_output = ''
							if self._subprocess.stderr:
								try:
									stderr_bytes = await self._subprocess.stderr.read()
									stderr_output = stderr_bytes.decode('utf-8', errors='replace')
								except Exception:
									pass
							if 'Failed parsing extensions' in stderr_output:
								self.logger.error(f'❌ Chrome process {self.browser_pid} exited: Failed parsing extensions')
								raise RuntimeError('Failed parsing extensions: Chrome profile incompatibility detected')
							elif 'SingletonLock' in stderr_output or 'ProcessSingleton' in stderr_output:
								# Chrome exited due to singleton lock
								self._fallback_to_temp_profile('Chrome process exit due to SingletonLock')
								# Kill the subprocess and retry with new profile
								try:
									self._subprocess.terminate()
									await self._subprocess.wait()
								except Exception:
									pass
								self.browser_pid = None
								# Retry with the new temp directory
								await self._unsafe_setup_new_browser_context()
								return
							else:
								# Chrome exited for unknown reason, try fallback to temp profile
								self.logger.warning(
									f'⚠️ Chrome process {self.browser_pid} exited unexpectedly. Error: {stderr_output[:500] if stderr_output else "No error output"}'
								)
								self._fallback_to_temp_profile('Chrome process exit with unknown error')
								# Kill the subprocess and retry with new profile
								try:
									self._subprocess.terminate()
									await self._subprocess.wait()
								except Exception:
									pass
								self.browser_pid = None
								# Retry with the new temp directory
								await self._unsafe_setup_new_browser_context()
								return
						self.logger.error(f'❌ Chrome process {self.browser_pid} exited unexpectedly')
						self.browser_pid = None
						return
				except psutil.NoSuchProcess:
					self.logger.error(f'❌ Chrome process {self.browser_pid} no longer exists')
					self.browser_pid = None
					return

				try:
					response = await client.get(f'{self.cdp_url}json/version', timeout=1.0)
					if response.status_code == 200:
						# self.logger.debug(f'✅ Chrome CDP port {debug_port} is ready')
						break
				except (httpx.ConnectError, httpx.TimeoutException):
					if i == 0:
						self.logger.debug(f'⏳ Waiting for Chrome CDP port {debug_port} to become available...')
					await asyncio.sleep(1)
			else:
				self.logger.error(f'❌ Chrome CDP port {debug_port} did not become available after 30 seconds')
				self.browser_pid = None
				return

		# Determine if this is a newly spawned subprocess or an existing process
		if hasattr(self, '_subprocess') and self._subprocess and self._subprocess.pid == self.browser_pid:
			self.logger.info(
				f'🌎 Connecting to newly spawned browser via CDP {self.cdp_url} -> browser_pid={self.browser_pid} (local)'
			)
		else:
			self.logger.info(
				f'🌎 Connecting to existing browser via CDP  {self.cdp_url} -> browser_pid={self.browser_pid} (local)'
			)
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

		self.logger.info(
			f'🌎 Connecting to existing playwright node.js browser server over WSS: {self.wss_url} -> (remote playwright)'
		)
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

		self.logger.info(f'🌎 Connecting to existing chromium-based browser via CDP: {self.cdp_url} -> (remote browser)')
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
					# self.logger.debug('Browser context already exists after semaphore acquisition, skipping launch')
					return
			except Exception:
				# If we can't check pages, assume context is invalid and continue with launch
				pass
		await self._unsafe_setup_new_browser_context()

	async def _unsafe_setup_new_browser_context(self) -> None:
		"""Unsafe browser context setup without retry protection."""

		# if we have a browser object but no browser_context, use the first context discovered or make a new one
		if self.browser and not self.browser_context:
			# If HAR recording is requested, we need to create a new context with recording enabled
			# Cannot reuse existing context as HAR recording must be configured at context creation
			if self.browser_profile.record_har_path and self.browser.contexts:
				self.logger.info('🎥 Creating new browser_context with HAR recording enabled (cannot reuse existing context)')
				self.browser_context = await self.browser.new_context(
					**self.browser_profile.kwargs_for_new_context().model_dump(mode='json')
				)
			elif self.browser.contexts:
				self.browser_context = self.browser.contexts[0]
				# Check if this is a newly spawned subprocess
				if hasattr(self, '_subprocess') and self._subprocess and self._subprocess.pid == self.browser_pid:
					self.logger.debug(f'👤 Using default browser_context opened in newly spawned browser: {self.browser_context}')
				else:
					self.logger.info(f'👤 Using first browser_context found in existing browser: {self.browser_context}')
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
				f'🎭 Launching new local browser '
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
			# If we're reconnecting and using a temp directory, create a new one
			# This avoids conflicts with the previous browser process that might still be shutting down
			elif self.browser_profile.user_data_dir and Path(self.browser_profile.user_data_dir).name.startswith(
				'browseruse-tmp-'
			):
				old_dir = self.browser_profile.user_data_dir
				self.browser_profile.user_data_dir = Path(tempfile.mkdtemp(prefix='browseruse-tmp-'))
				self.logger.debug(
					f'🗑️ Cleaning up old tmp user_data_dir= {_log_pretty_path(old_dir)} and using fresh one:{_log_pretty_path(self.browser_profile.user_data_dir)}'
				)
				try:
					shutil.rmtree(old_dir)
				except Exception:
					self.logger.warning(f'🗑️ Failed to cleanup old tmp user_data_dir= {_log_pretty_path(old_dir)}')

			# user data dir was provided, prepare it for use (handles conflicts automatically)
			self.prepare_user_data_dir()

			# if a user_data_dir is provided, launch Chrome as subprocess then connect via CDP
			try:
				async with asyncio.timeout(self.browser_profile.timeout / 1000):
					try:
						assert self.playwright is not None, 'playwright instance is None'

						# Find an available port for remote debugging
						import socket

						with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
							s.bind(('127.0.0.1', 0))
							s.listen(1)
							debug_port = s.getsockname()[1]

						# Get chromium executable path from browser profile or fall back to to playwright default
						chromium_path = self.browser_profile.executable_path or self.playwright.chromium.executable_path

						# Build chrome launch command with all args
						chrome_args = self.browser_profile.get_args()

						# Add/replace remote-debugging-port with our chosen port
						final_args = []
						for arg in chrome_args:
							if not arg.startswith('--remote-debugging-port='):
								final_args.append(arg)
						final_args.extend(
							[
								f'--remote-debugging-port={debug_port}',
								f'--user-data-dir={self.browser_profile.user_data_dir}',
							]
						)

						# Build final command
						chrome_launch_cmd = [chromium_path] + final_args

						# Launch chrome as subprocess
						self.logger.info(
							f' ↳ Spawning Chrome subprocess listening on CDP http://127.0.0.1:{debug_port}/ with user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir)}'
						)
						process = await asyncio.create_subprocess_exec(
							*chrome_launch_cmd,
							stdout=asyncio.subprocess.PIPE,
							stderr=asyncio.subprocess.PIPE,
						)

						# Store the subprocess reference for error handling
						self._subprocess = process

						# Store the browser PID
						self.browser_pid = process.pid
						self._set_browser_keep_alive(False)  # We launched it, so we should close it
						# self.logger.debug(f'👶 Chrome subprocess launched with browser_pid={process.pid}')

						# Use the existing setup_browser_via_browser_pid method to connect
						# It will wait for the CDP port to become available
						await self.setup_browser_via_browser_pid()

						# If connection failed, browser will be None
						if not self.browser:
							# Try to get error info from the process
							if process.returncode is not None:
								# Chrome exited, try to read stderr for error message
								stderr_output = ''
								if process.stderr:
									try:
										stderr_bytes = await process.stderr.read()
										stderr_output = stderr_bytes.decode('utf-8', errors='replace')
									except Exception:
										pass

								# Check for common Chrome errors
								if 'Failed parsing extensions' in stderr_output:
									raise RuntimeError(
										f'Failed parsing extensions: Chrome profile incompatibility detected. Chrome exited with code {process.returncode}'
									)
								elif 'SingletonLock' in stderr_output or 'ProcessSingleton' in stderr_output:
									raise RuntimeError(f'SingletonLock error: {stderr_output[:500]}')
								else:
									# For any other error, log it and raise to trigger fallback
									self.logger.warning(
										f'⚠️ Chrome subprocess exited with code {process.returncode}. Error: {stderr_output[:500] if stderr_output else "No error output"}'
									)
									raise RuntimeError(
										f'Chrome subprocess exited with code {process.returncode}. Error output: {stderr_output[:500] if stderr_output else "No error output"}'
									)
							else:
								# Kill the subprocess if it's still running but we couldn't connect
								try:
									process.terminate()
									await process.wait()
								except Exception:
									pass
								raise RuntimeError(f'Failed to connect to Chrome subprocess on port {debug_port}')

					except Exception as e:
						# Check if it's a SingletonLock error or Chrome subprocess exit error
						if (
							'SingletonLock' in str(e)
							or 'ProcessSingleton' in str(e)
							or 'Chrome subprocess exited' in str(e)
							or isinstance(e, RuntimeError)
						):
							# Fall back to temporary directory
							reason = (
								'Chrome launch error due to SingletonLock'
								if 'SingletonLock' in str(e)
								else 'Chrome subprocess failed to start'
							)
							self._fallback_to_temp_profile(reason)
							# Kill the failed subprocess if it exists
							if hasattr(self, '_subprocess') and self._subprocess:
								try:
									self._subprocess.terminate()
									await self._subprocess.wait()
								except Exception:
									pass
							# Retry the launch with the new temporary directory
							await self._unsafe_setup_new_browser_context()
							return
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
				# Retry the whole subprocess launch
				await self._unsafe_setup_new_browser_context()
				return
			except Exception as e:
				# Check if it's a SingletonLock error from the subprocess
				if 'SingletonLock' in str(e) or 'ProcessSingleton' in str(e):
					# Fall back to temporary directory
					self._fallback_to_temp_profile('Chrome launch error due to SingletonLock')
					# Retry the launch with the new temporary directory
					await self._unsafe_setup_new_browser_context()
					return

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

		# PID detection is no longer needed since we get PIDs directly from subprocesses or passed objects

		if self.browser:
			assert self.browser.is_connected(), (
				f'Browser is not connected, did the browser process crash or get killed? (connection method: {self._connection_str})'
			)
			# Only log final connection if we didn't already log it via setup_browser_via_browser_pid
			if not (hasattr(self, '_subprocess') and self._subprocess and self._subprocess.pid == self.browser_pid):
				self.logger.debug(f'🪢 Browser {self._connection_str} connected {self.browser or self.browser_context}')
		elif self.browser_context and not self.browser:
			# For launch_persistent_context case where we don't get a browser object
			self.logger.debug(f'🪢 Browser context {self._connection_str} connected {self.browser_context}')

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

	@observe_debug(name='setup_current_page_change_listeners')
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
				f'👁️‍🗨️ Found {len(pages)} existing tabs in browser, Agent 🅰 {self.id[-4:]} is on Page 🅟 {str(id(foreground_page))[-2:]}: {_log_pretty_url(foreground_page.url)}'  # type: ignore
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
			# Skip new tab pages as they can hang when evaluating scripts
			if is_new_tab_page(page.url):
				continue

			try:
				await page.evaluate(update_tab_focus_script)
				# self.logger.debug(f'👁️ Added visibility listener to existing tab: {page.url}')
			except Exception as e:
				page_idx = self.browser_context.pages.index(page)  # type: ignore
				self.logger.debug(
					f'⚠️ Failed to add visibility listener to existing tab, is it crashed or ignoring CDP commands?: [{page_idx}]{page.url}: {type(e).__name__}: {e}'
				)

	@observe_debug(name='setup_viewports', metadata={'browser_profile': '{{browser_profile}}'})
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

			# show browser-use dvd screensaver-style bouncing loading animation on any new tab pages
			if is_new_tab_page(page.url):
				# Navigate to about:blank if we're on chrome://new-tab-page to avoid security restrictions
				if page.url.startswith('chrome://new-tab-page'):
					try:
						# can raise exception if nav is interrupted by another agent nav or human, harmless but annoying
						await page.goto('about:blank', wait_until='load', timeout=5000)
					except Exception:
						pass
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
				try:
					await asyncio.wait_for(cdp_session.detach(), timeout=1.0)
				except (TimeoutError, Exception):
					pass
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
					f'⚠️ Failed to resize browser window to {_log_size(self.browser_profile.window_size)} via CDP setWindowBounds: {type(e).__name__}: {e}'
				)

	def _set_browser_keep_alive(self, keep_alive: bool | None) -> None:
		"""set the keep_alive flag on the browser_profile, defaulting to True if keep_alive is None"""
		if self.browser_profile.keep_alive is None:
			self.browser_profile.keep_alive = keep_alive

	@observe_debug(name='is_connected')
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
				# Create new page directly to avoid using decorated methods
				new_page = await self.browser_context.new_page()
				self.agent_current_page = new_page
				if (not self.human_current_page) or self.human_current_page.is_closed():
					self.human_current_page = new_page
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
		# Reset CDP connection info when browser is stopped
		self.cdp_url = None
		self.browser_pid = None
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

	def _check_for_singleton_lock_conflict(self) -> bool:
		"""Check if the user data directory has a conflicting browser process.

		Returns:
			True if there's a conflict (active process using this profile), False otherwise
		"""
		if not self.browser_profile.user_data_dir:
			return False

		# Normalize the path for comparison
		target_dir = str(Path(self.browser_profile.user_data_dir).expanduser().resolve())

		# Check for running processes using this user data dir
		for proc in psutil.process_iter(['pid', 'cmdline']):
			# Skip our own browser process
			if hasattr(self, 'browser_pid') and self.browser_pid and proc.info['pid'] == self.browser_pid:
				continue

			cmdline = proc.info['cmdline'] or []

			# Check both formats: --user-data-dir=/path and --user-data-dir /path
			for i, arg in enumerate(cmdline):
				# Combined format: --user-data-dir=/path
				if arg.startswith('--user-data-dir='):
					try:
						cmd_path = str(Path(arg.split('=', 1)[1]).expanduser().resolve())
						if cmd_path == target_dir:
							self.logger.debug(
								f'🔍 Found conflicting Chrome process PID {proc.info["pid"]} using profile {_log_pretty_path(self.browser_profile.user_data_dir)}'
							)
							return True
					except Exception:
						# Fallback to string comparison if path resolution fails
						if arg.split('=', 1)[1] == str(self.browser_profile.user_data_dir):
							self.logger.debug(
								f'🔍 Found conflicting Chrome process PID {proc.info["pid"]} using profile {_log_pretty_path(self.browser_profile.user_data_dir)}'
							)
							return True
				# Separate format: --user-data-dir /path
				elif arg == '--user-data-dir' and i + 1 < len(cmdline):
					try:
						cmd_path = str(Path(cmdline[i + 1]).expanduser().resolve())
						if cmd_path == target_dir:
							self.logger.debug(
								f'🔍 Found conflicting Chrome process PID {proc.info["pid"]} using profile {_log_pretty_path(self.browser_profile.user_data_dir)}'
							)
							return True
					except Exception:
						# Fallback to string comparison if path resolution fails
						if cmdline[i + 1] == str(self.browser_profile.user_data_dir):
							self.logger.debug(
								f'🔍 Found conflicting Chrome process PID {proc.info["pid"]} using profile {_log_pretty_path(self.browser_profile.user_data_dir)}'
							)
							return True

		# Note: We don't consider a SingletonLock file alone as a conflict
		# because it might be stale. Only actual running processes count as conflicts.
		return False

	def _fallback_to_temp_profile(self, reason: str = 'SingletonLock conflict') -> None:
		"""Fallback to a temporary profile directory when the current one is locked.

		Args:
			reason: Human-readable reason for the fallback
		"""
		old_dir = self.browser_profile.user_data_dir
		self.browser_profile.user_data_dir = Path(tempfile.mkdtemp(prefix='browseruse-tmp-singleton-'))
		self.logger.warning(
			f'⚠️ {reason} detected. Profile at {_log_pretty_path(old_dir)} is locked. '
			f'Using temporary profile instead: {_log_pretty_path(self.browser_profile.user_data_dir)}'
		)

	@observe_debug(name='prepare_user_data_dir')
	def prepare_user_data_dir(self, check_conflicts: bool = True) -> None:
		"""Create and prepare the user data dir, handling conflicts if needed.

		Args:
			check_conflicts: Whether to check for and handle singleton lock conflicts
		"""
		if self.browser_profile.user_data_dir:
			try:
				self.browser_profile.user_data_dir = Path(self.browser_profile.user_data_dir).expanduser().resolve()
				self.browser_profile.user_data_dir.mkdir(parents=True, exist_ok=True)
				(self.browser_profile.user_data_dir / '.browseruse_profile_id').write_text(self.browser_profile.id)
			except Exception as e:
				raise ValueError(
					f'Unusable path provided for user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir)} (check for typos/permissions issues)'
				) from e

			# Remove stale singleton lock file ONLY if no process is using this profile
			# This must happen BEFORE checking for conflicts to avoid false positives
			singleton_lock = self.browser_profile.user_data_dir / 'SingletonLock'
			if singleton_lock.exists():
				# Check if any process is actually using this user_data_dir
				has_active_process = False
				target_dir = str(self.browser_profile.user_data_dir)
				for proc in psutil.process_iter(['pid', 'cmdline']):
					# Skip our own browser process
					if hasattr(self, 'browser_pid') and self.browser_pid and proc.info['pid'] == self.browser_pid:
						continue

					cmdline = proc.info['cmdline'] or []
					# Check both formats: --user-data-dir=/path and --user-data-dir /path
					for i, arg in enumerate(cmdline):
						if arg.startswith('--user-data-dir='):
							try:
								if str(Path(arg.split('=', 1)[1]).expanduser().resolve()) == target_dir:
									has_active_process = True
									break
							except Exception:
								if arg.split('=', 1)[1] == str(self.browser_profile.user_data_dir):
									has_active_process = True
									break
						elif arg == '--user-data-dir' and i + 1 < len(cmdline):
							try:
								if str(Path(cmdline[i + 1]).expanduser().resolve()) == target_dir:
									has_active_process = True
									break
							except Exception:
								if cmdline[i + 1] == str(self.browser_profile.user_data_dir):
									has_active_process = True
									break
					if has_active_process:
						break

				if not has_active_process:
					# No active process, safe to remove stale lock
					try:
						# Handle both regular files and symlinks
						if singleton_lock.is_symlink() or singleton_lock.exists():
							singleton_lock.unlink()
							self.logger.debug(
								f'🧹 Removed stale SingletonLock file from {_log_pretty_path(self.browser_profile.user_data_dir)} (no active Chrome process found)'
							)
					except Exception:
						pass  # Ignore errors removing lock file

			# Check for conflicts and fallback if needed (AFTER cleaning stale locks)
			if check_conflicts and self._check_for_singleton_lock_conflict():
				self._fallback_to_temp_profile()
				# Recursive call without conflict checking to prepare the new temp dir
				return self.prepare_user_data_dir(check_conflicts=False)

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
	@observe_debug(name='get_current_page', ignore_input=True)
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
				new_page = await self.browser_context.new_page()
				self.agent_current_page = new_page
				self.human_current_page = new_page
				if self.browser_profile.viewport:
					await new_page.set_viewport_size(self.browser_profile.viewport)

		assert self.agent_current_page is not None, f'{self} Failed to find or create a new page for the agent'
		assert self.human_current_page is not None, f'{self} Failed to find or create a new page for the human'

		return self.agent_current_page

	@property
	def tabs(self) -> list[Page]:
		if not self.browser_context:
			return []
		return list(self.browser_context.pages)

	@require_healthy_browser(usable_page=False, reopen_page=False)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def wait_for_element(self, selector: str, timeout: int = 10000) -> None:
		page = await self.get_current_page()
		await page.wait_for_selector(selector, state='visible', timeout=timeout)

	@observe_debug(name='remove_highlights', ignore_output=True, ignore_input=True)
	@require_healthy_browser(usable_page=True, reopen_page=True)
	@time_execution_async('--remove_highlights')
	@retry(timeout=2, retries=0)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def get_dom_element_by_index(self, index: int) -> DOMElementNode | None:
		"""Get DOM element by index."""
		selector_map = await self.get_selector_map()
		return selector_map.get(index)

	@require_healthy_browser(usable_page=True, reopen_page=True)
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
						async with page.expect_download(timeout=5_000) as download_info:
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
				return await perform_click(lambda: element_handle and element_handle.click(timeout=1_500))
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
						return await perform_click(lambda: element_handle.click(timeout=1_500))
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

	@time_execution_async('--get_tabs_info')
	@retry(timeout=6, retries=1)
	@require_healthy_browser(usable_page=False, reopen_page=False)
	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""
		assert self.browser_context is not None, 'BrowserContext is not set up'
		tabs_info = []
		for page_id, page in enumerate(self.browser_context.pages):
			try:
				title = await asyncio.wait_for(page.title(), timeout=3.0)
				tab_info = TabInfo(page_id=page_id, url=page.url, title=title)
			except Exception:
				# page.title() can hang forever on tabs that are crashed/disappeared/about:blank
				# but we should preserve the real URL and not mislead the LLM about tab availability
				self.logger.debug(
					f'⚠️ Failed to get tab info for tab #{page_id}: {_log_pretty_url(page.url)} (using fallback title)'
				)

				# Only mark as unusable if it's actually about:blank, otherwise preserve the real URL
				if page.url == 'about:blank':
					tab_info = TabInfo(page_id=page_id, url='about:blank', title='ignore this tab and do not use it')
				else:
					# Preserve the real URL and use a descriptive fallback title
					# fallback_title = '(title unavailable, page possibly crashed / unresponsive)'
					# tab_info = TabInfo(page_id=page_id, url=page.url, title=fallback_title)

					# harsh but good, just close the page here because if we cant get the title then we certainly cant do anything else useful with it, no point keeping it open
					try:
						await page.close()
						self.logger.debug(
							f'🪓 Force-closed 🅟 {str(id(page))[-2:]} because its JS engine is unresponsive via CDP: {_log_pretty_url(page.url)}'
						)
					except Exception:
						pass
					continue

			tabs_info.append(tab_info)

		return tabs_info

	@retry(timeout=20, retries=1, semaphore_limit=1, semaphore_scope='self')
	async def _set_viewport_size(self, page: Page, viewport: dict[str, int] | ViewportSize) -> None:
		"""Set viewport size with timeout protection."""
		if isinstance(viewport, dict):
			await page.set_viewport_size(ViewportSize(width=viewport['width'], height=viewport['height']))
		else:
			await page.set_viewport_size(viewport)

	@require_healthy_browser(usable_page=False, reopen_page=False)
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
	@observe_debug()
	@retry(retries=0, timeout=30, wait=1, semaphore_timeout=10, semaphore_limit=1, semaphore_scope='self', semaphore_lax=True)
	@require_healthy_browser(usable_page=False, reopen_page=False)
	async def navigate(self, url: str = 'about:blank', new_tab: bool = False, timeout_ms: int | None = None) -> Page:
		"""
		Universal navigation method that handles all navigation scenarios.

		Args:
			url: URL to navigate to (defaults to 'about:blank')
			new_tab: If True, creates a new tab for navigation

		Returns:
			Page: The page that was navigated
		"""
		# Normalize the URL
		normalized_url = normalize_url(url)

		# Check if URL is allowed
		if not self._is_url_allowed(normalized_url):
			raise BrowserError(f'⛔️ Navigation to non-allowed URL: {normalized_url}')

		timeout_ms = min(3000, int(timeout_ms or self.browser_profile.default_navigation_timeout or 12000))

		# Handle new tab creation
		if new_tab:
			# Create new tab
			assert self.browser_context is not None, 'Browser context is not set'
			self.agent_current_page = await self.browser_context.new_page()

			# Update human tab reference if there is no human tab yet
			if (not self.human_current_page) or self.human_current_page.is_closed():
				self.human_current_page = self.agent_current_page

			# Set viewport for new tab
			if self.browser_profile.viewport:
				await self.agent_current_page.set_viewport_size(self.browser_profile.viewport)

			page = self.agent_current_page
		else:
			# Use existing page
			page = await self.get_current_page()

		# Navigate to URL
		try:
			# Use asyncio.wait to prevent hanging on slow page loads
			# Don't cap the timeout - respect what was requested
			self.logger.debug(f'🧭 Starting navigation to {_log_pretty_url(normalized_url)} with timeout {timeout_ms}ms')
			nav_task = asyncio.create_task(page.goto(normalized_url, wait_until='load', timeout=timeout_ms))
			done, pending = await asyncio.wait([nav_task], timeout=(timeout_ms + 500) / 1000)

			if nav_task in pending:
				# Navigation timed out
				self.logger.warning(
					f"⚠️ Loading {_log_pretty_url(normalized_url)} didn't finish after {timeout_ms / 1000}s, continuing anyway..."
				)
				nav_task.cancel()
				try:
					await nav_task
				except asyncio.CancelledError:
					pass

				# Check if page is still usable after timeout
				if page and not page.is_closed():
					current_url = page.url
					# self.logger.debug(f'🤌 Checking responsiveness after navigation timeout (current URL: {current_url})')
					is_responsive = await self._is_page_responsive(page, timeout=3.0)
					if is_responsive:
						self.logger.debug(
							f'✅ Page is responsive and usable despite navigation loading timeout on: {_log_pretty_url(current_url)})'
						)
					else:
						self.logger.error(
							f'❌ Page is unresponsive after navigation stalled on: {_log_pretty_url(current_url)} WARNING! Subsequent operations will likely fail on this page, it must be reset...'
						)
						# Don't try complex recovery during navigate - just raise the error
						# The retry decorator will handle retries, and other methods with
						# @require_healthy_browser(reopen_page=True) will trigger proper recovery
						raise RuntimeError(
							f'Page JS engine is unresponsive after navigation / loading issue on: {_log_pretty_url(current_url)}). Agent cannot proceed with this page because its JS event loop is unresponsive.'
						)
			elif nav_task in done:
				# Navigation completed, check if it succeeded
				await nav_task  # This will raise if navigation failed
		except Exception as e:
			if 'timeout' in str(e).lower():
				# self.logger.warning(
				# 	f"⚠️ Loading {_log_pretty_url(normalized_url)} didn't finish and further operations may fail on this page..."
				# )
				pass  # allow agent to attempt to continue without raising hard error, it can use tools to work around it
			else:
				raise

		# Show DVD animation on new tab pages if no URL specified
		if new_tab and is_new_tab_page(page.url):
			# Navigate to about:blank if we're on chrome://new-tab-page to avoid security restrictions
			if page.url.startswith('chrome://new-tab-page'):
				try:
					await page.goto('about:blank', wait_until='load', timeout=timeout_ms)
				except Exception:
					pass
			await self._show_dvd_screensaver_loading_animation(page)

		return page

	@deprecated('Use BrowserSession.navigate(url) instead of .navigate_to(url)')
	async def navigate_to(self, url: str) -> Page:
		"""Backward compatibility alias for navigate()"""
		return await self.navigate(url=url, new_tab=False)

	@deprecated('Use BrowserSession.navigate(url=url, new_tab=True) instead of .create_new_tab(url)')
	async def create_new_tab(self, url: str | None = None) -> Page:
		"""Backward compatibility alias for navigate()"""
		return await self.navigate(url=url or 'about:blank', new_tab=True)

	@deprecated('Use BrowserSession.navigate(url=url, new_tab=True) instead of .new_tab(url)')
	async def new_tab(self, url: str | None = None) -> Page:
		"""Backward compatibility alias for navigate()"""
		return await self.navigate(url=url or 'about:blank', new_tab=True)

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def refresh(self) -> None:
		if self.agent_current_page and not self.agent_current_page.is_closed():
			await self.agent_current_page.reload()
		else:
			# Create new page directly
			assert self.browser_context is not None, 'Browser context is not set'
			new_page = await self.browser_context.new_page()
			self.agent_current_page = new_page
			if (not self.human_current_page) or self.human_current_page.is_closed():
				self.human_current_page = new_page
			if self.browser_profile.viewport:
				await new_page.set_viewport_size(self.browser_profile.viewport)

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def execute_javascript(self, script: str) -> Any:
		page = await self.get_current_page()
		return await page.evaluate(script)

	async def get_cookies(self) -> list[dict[str, Any]]:
		if self.browser_context:
			return [dict(x) for x in await self.browser_context.cookies()]
		return []

	@deprecated('Use BrowserSession.save_storage_state() instead')
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

	@retry(
		timeout=5, retries=1, semaphore_limit=1, semaphore_scope='self'
	)  # users can share JSON between browsers, this should really be 'multiprocess' not 'self
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

	def set_auto_download_pdfs(self, enabled: bool) -> None:
		"""
		Enable or disable automatic PDF downloading when PDFs are encountered.

		Args:
		    enabled: Whether to automatically download PDFs
		"""
		self._auto_download_pdfs = enabled
		self.logger.info(f'📄 PDF auto-download {"enabled" if enabled else "disabled"}')

	@property
	def auto_download_pdfs(self) -> bool:
		"""Get current PDF auto-download setting."""
		return self._auto_download_pdfs

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

	@observe_debug(name='wait_for_page_and_frames_load')
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

		# Special case: Always allow new tab pages
		if is_new_tab_page(url):
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
				# This would only happen if a new tab page is passed to match_url_with_domain_pattern,
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

	@observe_debug()
	async def refresh_page(self):
		"""Refresh the agent's current page"""

		page = await self.get_current_page()
		await page.reload()
		try:
			await page.wait_for_load_state()
		except Exception as e:
			self.logger.warning(f'⚠️ Page {_log_pretty_url(page.url)} failed to fully load after refresh: {type(e).__name__}: {e}')
			assert await page.evaluate('1'), (
				f'Page {page.url} crashed after {type(e).__name__} and can no longer be used via CDP: {e}'
			)

	async def go_back(self):
		"""Navigate the agent's tab back in browser history"""
		try:
			# 10 ms timeout
			page = await self.get_current_page()
			await page.go_back(timeout=10_000, wait_until='load')

			# await self._wait_for_page_and_frames_load(timeout_overwrite=1.0)
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			self.logger.debug(f'⏮️ Error during go_back: {type(e).__name__}: {e}')
			# Verify page is still usable after navigation error
			if 'timeout' in str(e).lower():
				try:
					assert await page.evaluate('1'), (
						f'Page {page.url} crashed after go_back {type(e).__name__} and can no longer be used via CDP: {e}'
					)
				except Exception as eval_error:
					self.logger.error(f'❌ Page crashed after go_back timeout: {eval_error}')

	async def go_forward(self):
		"""Navigate the agent's tab forward in browser history"""
		try:
			page = await self.get_current_page()
			await page.go_forward(timeout=10_000, wait_until='load')
		except Exception as e:
			# Continue even if its not fully loaded, because we wait later for the page to load
			self.logger.debug(f'⏭️ Error during go_forward: {type(e).__name__}: {e}')
			# Verify page is still usable after navigation error
			if 'timeout' in str(e).lower():
				try:
					assert await page.evaluate('1'), (
						f'Page {page.url} crashed after go_forward {type(e).__name__} and can no longer be used via CDP: {e}'
					)
				except Exception as eval_error:
					self.logger.error(f'❌ Page crashed after go_forward timeout: {eval_error}')

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

	@observe_debug(ignore_output=True)
	@time_execution_async('--get_state_summary')
	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@observe_debug(name='get_minimal_state_summary', ignore_output=True)
	@require_healthy_browser(usable_page=True, reopen_page=True)
	@time_execution_async('--get_minimal_state_summary')
	async def get_minimal_state_summary(self) -> BrowserStateSummary:
		"""Get basic page info without DOM processing, but try to capture screenshot"""
		from browser_use.browser.views import BrowserStateSummary
		from browser_use.dom.views import DOMElementNode

		page = await self.get_current_page()

		# Get basic info - no DOM parsing to avoid errors
		url = getattr(page, 'url', 'unknown')

		# Try to get title safely
		try:
			# timeout after 2 seconds
			title = await asyncio.wait_for(page.title(), timeout=2.0)
		except Exception:
			title = 'Page Load Error'

		# Try to get tabs info safely
		try:
			# timeout after 2 seconds
			tabs_info = await retry(timeout=2, retries=0)(self.get_tabs_info)()
		except Exception:
			tabs_info = []

		# Create minimal DOM element for error state
		minimal_element_tree = DOMElementNode(
			tag_name='body',
			xpath='/body',
			attributes={},
			children=[],
			is_visible=True,
			parent=None,
		)

		return BrowserStateSummary(
			element_tree=minimal_element_tree,  # Minimal DOM tree
			selector_map={},  # Empty selector map
			url=url,
			title=title,
			tabs=tabs_info,
			pixels_above=0,
			pixels_below=0,
			browser_errors=[f'Page state retrieval failed, minimal recovery applied for {url}'],
		)

	@observe_debug(name='get_updated_state', ignore_output=True)
	async def _get_updated_state(self, focus_element: int = -1) -> BrowserStateSummary:
		"""Update and return state."""

		# Check if current page is still valid, if not switch to another available page
		page = await self.get_current_page()

		try:
			# Test if page is still accessible
			# NOTE: This also happens on invalid urls like www.sadfdsafdssdafd.com
			await asyncio.wait_for(page.evaluate('1'), timeout=2.5)
		except Exception as e:
			self.logger.debug(f'👋 Current page is not accessible: {type(e).__name__}: {e}')
			raise BrowserError('Page is not accessible')

		try:
			self.logger.debug('🧹 Removing highlights...')
			try:
				await self.remove_highlights()
			except TimeoutError:
				self.logger.debug('Timeout to remove highlights')

			# Check for PDF and auto-download if needed
			try:
				pdf_path = await self._auto_download_pdf_if_needed(page)
				if pdf_path:
					self.logger.info(f'📄 PDF auto-downloaded: {pdf_path}')
			except Exception as e:
				self.logger.debug(f'PDF auto-download check failed: {type(e).__name__}: {e}')

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
				self.logger.debug('📸 Capturing screenshot...')
				# Reasonable timeout for screenshot
				screenshot_b64 = await self.take_screenshot()
				# self.logger.debug('✅ Screenshot completed')
			except Exception as e:
				self.logger.warning(f'❌ Screenshot failed for {_log_pretty_url(page.url)}: {type(e).__name__} {e}')
				screenshot_b64 = None

			# Get comprehensive page information
			page_info = await self.get_page_info(page)
			try:
				self.logger.debug('📏 Getting scroll info...')
				pixels_above, pixels_below = await asyncio.wait_for(self.get_scroll_info(page), timeout=5.0)
				self.logger.debug('✅ Scroll info completed')
			except Exception as e:
				self.logger.warning(f'Failed to get scroll info: {type(e).__name__}')
				pixels_above, pixels_below = 0, 0

			try:
				title = await asyncio.wait_for(page.title(), timeout=3.0)
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
				page_info=page_info,
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

	# region - Page Health Check Helpers

	async def _is_page_responsive(self, page: Page, timeout: float = 5.0) -> bool:
		"""Check if a page is responsive by trying to evaluate simple JavaScript."""
		eval_task = None
		try:
			eval_task = asyncio.create_task(page.evaluate('1'))
			done, pending = await asyncio.wait([eval_task], timeout=timeout)

			if eval_task in done:
				try:
					await eval_task  # This will raise if the evaluation failed
					return True
				except Exception:
					return False
			else:
				# Timeout - the page is unresponsive
				return False
		except Exception:
			return False
		finally:
			# Always clean up the eval task
			if eval_task and not eval_task.done():
				eval_task.cancel()
				try:
					await eval_task
				except (asyncio.CancelledError, Exception):
					pass

	async def _force_close_page_via_cdp(self, page_url: str) -> bool:
		"""Force close a crashed page using CDP from a clean temporary page."""
		try:
			# self.logger.info('🔨 Creating temporary page for CDP force-close...')

			# Create a clean page for CDP operations
			assert self.browser_context, 'Browser context is not set up yet'
			temp_page = await asyncio.wait_for(self.browser_context.new_page(), timeout=5.0)
			await asyncio.wait_for(temp_page.goto('about:blank'), timeout=2.0)

			# Create CDP session from the clean page
			cdp_session = await asyncio.wait_for(self.browser_context.new_cdp_session(temp_page), timeout=5.0)  # type: ignore

			try:
				# Get all browser targets
				targets = await asyncio.wait_for(cdp_session.send('Target.getTargets'), timeout=2.0)

				# Find the crashed page target
				blocked_target_id = None
				for target in targets.get('targetInfos', []):
					if target.get('type') == 'page' and target.get('url') == page_url:
						blocked_target_id = target.get('targetId')
						# self.logger.debug(f'Found target to close: {page_url}')
						break

				if blocked_target_id:
					# Force close the target
					self.logger.warning(
						f'🪓 Force-closing crashed page target_id={blocked_target_id} via CDP: {_log_pretty_url(page_url)}...'
					)
					await asyncio.wait_for(cdp_session.send('Target.closeTarget', {'targetId': blocked_target_id}), timeout=2.0)
					# self.logger.debug(f'☠️ Successfully force-closed crashed page target_id={blocked_target_id} via CDP: {_log_pretty_url(page_url)}')
					return True
				else:
					self.logger.debug(
						f'❌ Could not find CDP page target_id to force-close: {_log_pretty_url(page_url)} (concurrency issues?)'
					)
					return False

			finally:
				# Clean up
				try:
					await asyncio.wait_for(cdp_session.detach(), timeout=1.0)
				except Exception:
					pass
				await temp_page.close()

		except Exception as e:
			self.logger.error(f'❌ Using raw CDP to force-close crashed page failed: {type(e).__name__}: {e}')
			return False

	async def _try_reopen_url(self, url: str, timeout_ms: int | None = None) -> bool:
		"""Try to reopen a URL in a new page and check if it's responsive."""
		if not url or is_new_tab_page(url):
			return False

		timeout_ms = int(timeout_ms or self.browser_profile.default_navigation_timeout or 6000)

		try:
			self.logger.debug(f'🔄 Attempting to reload URL that crashed: {_log_pretty_url(url)}')

			# Create new page directly to avoid circular dependency
			assert self.browser_context is not None, 'Browser context is not set'
			new_page = await self.browser_context.new_page()
			self.agent_current_page = new_page

			# Update human tab reference if there is no human tab yet
			if (not self.human_current_page) or self.human_current_page.is_closed():
				self.human_current_page = new_page

			# Set viewport for new tab
			if self.browser_profile.viewport:
				await new_page.set_viewport_size(self.browser_profile.viewport)

			# Navigate with timeout using asyncio.wait
			nav_task = asyncio.create_task(new_page.goto(url, wait_until='load', timeout=timeout_ms))
			done, pending = await asyncio.wait([nav_task], timeout=(timeout_ms + 500) / 1000)

			if nav_task in pending:
				# Navigation timed out
				self.logger.debug(
					f'⚠️ Attempting to reload previously crashed URL {_log_pretty_url(url)} failed again, timed out again after {timeout_ms / 1000}s'
				)
				nav_task.cancel()
				try:
					await nav_task
				except asyncio.CancelledError:
					pass
			elif nav_task in done:
				try:
					await nav_task  # This will raise if navigation failed
				except Exception as e:
					self.logger.debug(
						f'⚠️ Attempting to reload previously crashed URL {_log_pretty_url(url)} failed again: {type(e).__name__}'
					)

			# Wait a bit for any transient blocking to resolve
			await asyncio.sleep(1.0)

			# Check if the reopened page is responsive
			# self.logger.debug('Checking if reopened page is responsive...')
			is_responsive = await self._is_page_responsive(new_page, timeout=2.0)

			if is_responsive:
				self.logger.info(f'✅ Page recovered and is now responsive after reopening on: {_log_pretty_url(url)}')
				return True
			else:
				self.logger.warning(f'⚠️ Reopened page {_log_pretty_url(url)} is still unresponsive')
				# Close the unresponsive page before returning
				# This is critical to prevent the recovery flow from hanging
				try:
					await self._force_close_page_via_cdp(new_page.url)
				except Exception as e:
					self.logger.error(
						f'❌ Failed to close crashed page {_log_pretty_url(url)} via CDP: {type(e).__name__}: {e} (something is very wrong or system is extremely overloaded)'
					)
				self.agent_current_page = None  # Clear reference to closed page
				return False

		except Exception as e:
			self.logger.error(f'❌ Retrying crashed page {_log_pretty_url(url)} failed: {type(e).__name__}: {e}')
			return False

	async def _create_blank_fallback_page(self, url: str) -> None:
		"""Create a new blank page as a fallback when recovery fails."""
		self.logger.warning(
			f'⚠️ Resetting to about:blank as fallback because browser is unable to load the original URL without crashing: {_log_pretty_url(url)}'
		)
		# self.logger.debug(f'Current agent_current_page: {self.agent_current_page}')

		# Close any existing broken page
		if self.agent_current_page and not self.agent_current_page.is_closed():
			try:
				await self.agent_current_page.close()
			except Exception:
				pass

		# Create fresh page directly (avoid decorated methods to prevent circular dependency)
		assert self.browser_context is not None, 'Browser context is not set'
		new_page = await self.browser_context.new_page()
		self.agent_current_page = new_page

		# Update human tab reference if there is no human tab yet
		if (not self.human_current_page) or self.human_current_page.is_closed():
			self.human_current_page = new_page

		# Set viewport for new tab
		if self.browser_profile.viewport:
			await new_page.set_viewport_size(self.browser_profile.viewport)

		# Navigate to blank
		try:
			await new_page.goto('about:blank', wait_until='load', timeout=5000)
		except Exception as e:
			self.logger.error(
				f'❌ Failed to navigate to about:blank: {type(e).__name__}: {e} (something is very wrong or system is extremely overloaded)'
			)
			raise

		# Verify it's responsive
		if not await self._is_page_responsive(new_page, timeout=1.0):
			raise BrowserError(
				'Browser is unable to load any new about:blank pages (something is very wrong or browser is extremely overloaded)'
			)

	async def _recover_unresponsive_page(self, calling_method: str, timeout_ms: int | None = None) -> None:
		"""Recover from an unresponsive page by closing and reopening it."""
		self.logger.warning(f'⚠️ Page JS engine became unresponsive in {calling_method}(), attempting recovery...')
		timeout_ms = min(3000, int(timeout_ms or self.browser_profile.default_navigation_timeout or 5000))

		# Prevent re-entrance
		self._in_recovery = True
		try:
			# Get current URL before recovery
			assert self.agent_current_page, 'Agent current page is not set'
			current_url = self.agent_current_page.url
			# self.logger.debug(f'Current URL: {current_url}')

			# Clear page references
			blocked_page = self.agent_current_page
			self.agent_current_page = None
			if blocked_page == self.human_current_page:
				self.human_current_page = None

			# Force-close the crashed page via CDP
			self.logger.debug('🪓 Page Recovery Step 1/3: Force-closing crashed page via CDP...')
			await self._force_close_page_via_cdp(current_url)

			# Remove the closed page from browser_context.pages by forcing a refresh
			# This prevents TargetClosedError when iterating through pages later
			if self.browser_context and self.browser_context.pages:
				# Additional cleanup: close any page objects that have the same url as the crashed page
				# (could close too many pages by accident if we have a few different tabs on the same URL)
				# Sometimes playwright doesn't immediately remove force-closed pages from the list
				for page in self.browser_context.pages[:]:  # Use slice to avoid modifying list during iteration
					if page.url == current_url and not page.is_closed() and not is_new_tab_page(page.url):
						try:
							# Try to close it via playwright as well
							await page.close()
							self.logger.debug(
								f'🪓 Closed 🅟 {str(id(page))[-2:]} because it has a known crash-causing URL: {_log_pretty_url(page.url)}'
							)
						except Exception:
							pass  # Page might already be closed via CDP

			# Try to reopen the URL (in case blocking was transient)
			self.logger.debug('🍼 Page Recovery Step 2/3: Trying to reopen the URL again...')
			if await self._try_reopen_url(current_url, timeout_ms=timeout_ms):
				self.logger.debug('✅ Page Recovery Step 3/3: Page loading succeeded after 2nd attempt!')
				return  # Success!

			# If that failed, fall back to blank page
			self.logger.debug(
				'❌ Page Recovery Step 3/3: Loading the page a 2nd time failed as well, browser seems unable to load this URL without getting stuck, retreating to a safe page...'
			)
			await self._create_blank_fallback_page(current_url)

		finally:
			# Always clear recovery flag
			self._in_recovery = False

	# region - Browser Actions
	@observe_debug(name='take_screenshot', ignore_output=True)
	@retry(
		retries=1,  # try up to 1 time to take the screenshot (2 total attempts)
		timeout=30,  # allow up to 30s for each attempt (includes recovery time)
		wait=1,  # wait 1s between each attempt
		semaphore_limit=2,  # Allow 2 screenshots at a time to better utilize resources
		semaphore_name='screenshot_global',
		semaphore_scope='multiprocess',
		semaphore_lax=True,  # Continue without semaphore if it can't be acquired
		semaphore_timeout=15,  # Wait up to 15s for semaphore acquisition
	)
	@require_healthy_browser(usable_page=True, reopen_page=True)
	@time_execution_async('--take_screenshot')
	async def take_screenshot(self, full_page: bool = False) -> str | None:
		"""
		Returns a base64 encoded screenshot of the current page using CDP.

		The decorator order ensures:
		1. @retry runs first (outer decorator)
		2. @require_healthy_browser runs on each retry attempt
		3. Page responsiveness is checked before each screenshot attempt
		4. If page is unresponsive, it's recovered and the method is retried
		"""
		assert self.agent_current_page is not None, 'Agent current page is not set'
		assert self.browser_context, 'Browser context is not set'

		page = self.agent_current_page

		if is_new_tab_page(page.url):
			self.logger.warning(
				f'▫️ Sending LLM 1px placeholder instead of real screenshot of: {_log_pretty_url(page.url)} (page empty)'
			)
			# not an exception because there's no point in retrying if we hit this, its always pointless to screenshot about:blank
			# raise ValueError('Refusing to take unneeded screenshot of empty new tab page')
			# return a 1px*1px white png to avoid wasting tokens
			return 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='

		# Always bring page to front before rendering, otherwise it crashes in some cases, not sure why
		try:
			await page.bring_to_front()
		except Exception:
			pass

		# Take screenshot using CDP to get around playwright's unnecessary slowness and weird behavior
		cdp_session = None
		try:
			# Create CDP session for the screenshot
			self.logger.debug(
				f'📸 Taking viewport-only PNG screenshot of page via fresh CDP session: {_log_pretty_url(page.url)}'
			)
			cdp_session = await self.browser_context.new_cdp_session(page)  # type: ignore

			# Capture screenshot via CDP
			screenshot_response = await cdp_session.send(
				'Page.captureScreenshot',
				{
					'captureBeyondViewport': False,
					'fromSurface': True,
					'format': 'png',
				},
			)

			screenshot_b64 = screenshot_response.get('data')
			if not screenshot_b64:
				raise Exception(
					f'CDP returned empty screenshot data for page {_log_pretty_url(page.url)}? (expected png base64)'
				)  # have never seen this happen in practice

			return screenshot_b64

		except Exception as err:
			error_str = f'{type(err).__name__}: {err}'
			if 'timeout' in error_str.lower():
				self.logger.warning(f'⏱️ Screenshot timed out on page {_log_pretty_url(page.url)} (possibly crashed): {error_str}')
			else:
				self.logger.error(f'❌ Screenshot failed on page {_log_pretty_url(page.url)} (possibly crashed): {error_str}')
			raise
		finally:
			if cdp_session:
				try:
					await asyncio.wait_for(cdp_session.detach(), timeout=1.0)
				except Exception:
					pass

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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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
				await element_handle.wait_for_element_state('stable', timeout=1_000)
				is_visible = await self._is_visible(element_handle)
				if is_visible:
					await element_handle.scroll_into_view_if_needed(timeout=1_000)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	# region - Helper methods for easier access to the DOM
	@observe_debug(name='get_selector_map')
	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def get_selector_map(self) -> SelectorMap:
		if self._cached_browser_state_summary is None:
			return {}
		return self._cached_browser_state_summary.selector_map

	@observe_debug(name='get_element_by_index')
	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def get_element_by_index(self, index: int) -> ElementHandle | None:
		selector_map = await self.get_selector_map()
		element_handle = await self.get_locate_element(selector_map[index])
		return element_handle

	@observe_debug(name='is_file_input_by_index')
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
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

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def get_scroll_info(self, page: Page) -> tuple[int, int]:
		"""Get scroll position information for the current page."""
		scroll_y = await page.evaluate('window.scrollY')
		viewport_height = await page.evaluate('window.innerHeight')
		total_height = await page.evaluate('document.documentElement.scrollHeight')
		# Convert to int to handle fractional pixels
		pixels_above = int(scroll_y)
		pixels_below = int(max(0, total_height - (scroll_y + viewport_height)))
		return pixels_above, pixels_below

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def get_page_info(self, page: Page) -> PageInfo:
		"""Get comprehensive page size and scroll information."""
		# Get all page dimensions and scroll info in one JavaScript call for efficiency
		page_data = await page.evaluate("""() => {
			return {
				// Current viewport dimensions
				viewport_width: window.innerWidth,
				viewport_height: window.innerHeight,
				
				// Total page dimensions
				page_width: Math.max(
					document.documentElement.scrollWidth,
					document.body.scrollWidth || 0
				),
				page_height: Math.max(
					document.documentElement.scrollHeight,
					document.body.scrollHeight || 0
				),
				
				// Current scroll position
				scroll_x: window.scrollX || window.pageXOffset || document.documentElement.scrollLeft || 0,
				scroll_y: window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0
			};
		}""")

		# Calculate derived values (convert to int to handle fractional pixels)
		viewport_width = int(page_data['viewport_width'])
		viewport_height = int(page_data['viewport_height'])
		page_width = int(page_data['page_width'])
		page_height = int(page_data['page_height'])
		scroll_x = int(page_data['scroll_x'])
		scroll_y = int(page_data['scroll_y'])

		# Calculate scroll information
		pixels_above = scroll_y
		pixels_below = max(0, page_height - (scroll_y + viewport_height))
		pixels_left = scroll_x
		pixels_right = max(0, page_width - (scroll_x + viewport_width))

		# Create PageInfo object with comprehensive information
		page_info = PageInfo(
			viewport_width=viewport_width,
			viewport_height=viewport_height,
			page_width=page_width,
			page_height=page_height,
			scroll_x=scroll_x,
			scroll_y=scroll_y,
			pixels_above=pixels_above,
			pixels_below=pixels_below,
			pixels_left=pixels_left,
			pixels_right=pixels_right,
		)

		return page_info

	async def _scroll_with_cdp_gesture(self, page: Page, pixels: int) -> bool:
		"""
		Scroll using CDP Input.synthesizeScrollGesture for universal compatibility.

		Args:
			page: The page to scroll
			pixels: Number of pixels to scroll (positive = up, negative = down)

		Returns:
			True if successful, False if failed
		"""
		try:
			# Use CDP to synthesize scroll gesture - works in all contexts including PDFs
			cdp_session = await page.context.new_cdp_session(page)  # type: ignore

			# Get viewport center for scroll origin
			viewport = await page.evaluate("""
				() => ({
					width: window.innerWidth,
					height: window.innerHeight
				})
			""")

			center_x = viewport['width'] // 2
			center_y = viewport['height'] // 2

			await cdp_session.send(
				'Input.synthesizeScrollGesture',
				{
					'x': center_x,
					'y': center_y,
					'xDistance': 0,
					'yDistance': -pixels,  # Negative = scroll down, Positive = scroll up
					'gestureSourceType': 'mouse',  # Use mouse gestures for better compatibility
					'speed': 3000,  # Pixels per second
				},
			)

			try:
				await asyncio.wait_for(cdp_session.detach(), timeout=1.0)
			except (TimeoutError, Exception):
				pass
			self.logger.debug(f'📄 Scrolled via CDP Input.synthesizeScrollGesture: {pixels}px')
			return True

		except Exception as e:
			self.logger.warning(f'❌ Scrolling via CDP Input.synthesizeScrollGesture failed: {type(e).__name__}: {e}')
			return False

	@require_healthy_browser(usable_page=True, reopen_page=True)
	async def _scroll_container(self, pixels: int) -> None:
		"""Scroll using CDP gesture synthesis with JavaScript fallback."""

		page = await self.get_current_page()

		# Try CDP scroll gesture first (works universally including PDFs)
		if await self._scroll_with_cdp_gesture(page, pixels):
			return

		# Fallback to JavaScript for older browsers or when CDP fails
		self.logger.debug('Falling back to JavaScript scrolling')
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
		# assert is_new_tab_page(page.url), 'DVD screensaver loading animation should only be shown on new tab pages'

		# all in one JS function for speed, we want as few roundtrip CDP calls as possible
		# between opening the tab and showing the animation
		try:
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
				style.textContent = `
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
		except Exception as e:
			self.logger.debug(f'❌ Failed to show 📀 DVD loading animation: {type(e).__name__}: {e}')

	@observe_debug(name='get_state_summary_with_fallback', ignore_output=True)
	@require_healthy_browser(usable_page=True, reopen_page=True)
	@time_execution_async('--get_state_summary_with_fallback')
	async def get_state_summary_with_fallback(self, cache_clickable_elements_hashes: bool = True) -> BrowserStateSummary:
		"""Get browser state with fallback to minimal state on errors

		This method first tries to get a full state summary. If that fails,
		it falls back to a minimal state summary to allow basic navigation.

		Parameters:
		-----------
		cache_clickable_elements_hashes: bool
			If True, cache the clickable elements hashes for the current state.

		Returns:
		--------
		BrowserStateSummary: Either full state or minimal fallback state
		"""
		# Try 1: Full state summary (current implementation)
		try:
			return await self.get_state_summary(cache_clickable_elements_hashes)
		except Exception as e:
			self.logger.warning(f'Full state retrieval failed: {type(e).__name__}: {e}')
			self.logger.warning('🔄 Falling back to minimal state summary')

		# Try 2: Minimal state summary as fallback
		return await self.get_minimal_state_summary()

	async def _is_pdf_viewer(self, page: Page) -> bool:
		"""
		Check if the current page is displaying a PDF in Chrome's PDF viewer.
		Returns True if PDF is detected, False otherwise.
		"""
		try:
			is_pdf_viewer = await page.evaluate("""
				() => {
					// Check for Chrome's built-in PDF viewer (updated selector)
					const pdfEmbed = document.querySelector('embed[type="application/x-google-chrome-pdf"]') ||
									 document.querySelector('embed[type="application/pdf"]');
					const isPdfViewer = !!pdfEmbed;
					
					// Also check if the URL ends with .pdf or has PDF content-type
					const url = window.location.href;
					const isPdfUrl = url.toLowerCase().includes('.pdf') || 
									document.contentType === 'application/pdf';
					
					return isPdfViewer || isPdfUrl;
				}
			""")
			return is_pdf_viewer
		except Exception as e:
			self.logger.debug(f'Error checking PDF viewer: {type(e).__name__}: {e}')
			return False

	async def _auto_download_pdf_if_needed(self, page: Page) -> str | None:
		"""
		Check if the current page is a PDF viewer and automatically download the PDF if so.
		Returns the download path if a PDF was downloaded, None otherwise.
		"""
		if not self.browser_profile.downloads_path or not self._auto_download_pdfs:
			return None

		try:
			# Check if we're in a PDF viewer
			is_pdf_viewer = await self._is_pdf_viewer(page)
			self.logger.debug(f'is_pdf_viewer: {is_pdf_viewer}')

			if not is_pdf_viewer:
				return None

			# Get the PDF URL
			pdf_url = page.url

			# Check if we've already downloaded this PDF
			pdf_filename = os.path.basename(pdf_url.split('?')[0])  # Remove query params
			if not pdf_filename or not pdf_filename.endswith('.pdf'):
				# Generate filename from URL
				from urllib.parse import urlparse

				parsed = urlparse(pdf_url)
				pdf_filename = os.path.basename(parsed.path) or 'document.pdf'
				if not pdf_filename.endswith('.pdf'):
					pdf_filename += '.pdf'

			# Check if already downloaded
			expected_path = os.path.join(self.browser_profile.downloads_path, pdf_filename)
			if any(os.path.basename(downloaded) == pdf_filename for downloaded in self._downloaded_files):
				self.logger.debug(f'📄 PDF already downloaded: {pdf_filename}')
				return None

			self.logger.info(f'📄 Auto-downloading PDF from: {pdf_url}')

			# Download the actual PDF file using JavaScript fetch
			# Note: This should hit the browser cache since Chrome already downloaded the PDF to display it
			try:
				self.logger.debug(f'Downloading PDF from URL: {pdf_url}')

				# Properly escape the URL to prevent JavaScript injection
				escaped_pdf_url = json.dumps(pdf_url)

				download_result = await page.evaluate(f"""
					async () => {{
						try {{
							// Use fetch with cache: 'force-cache' to prioritize cached version
							const response = await fetch({escaped_pdf_url}, {{
								cache: 'force-cache'
							}});
							if (!response.ok) {{
								throw new Error(`HTTP error! status: ${{response.status}}`);
							}}
							const blob = await response.blob();
							const arrayBuffer = await blob.arrayBuffer();
							const uint8Array = new Uint8Array(arrayBuffer);
							
							// Log whether this was served from cache
							const fromCache = response.headers.has('age') || 
											 !response.headers.has('date') ||
											 performance.getEntriesByName({escaped_pdf_url}).some(entry => 
												 entry.transferSize === 0 || entry.transferSize < entry.encodedBodySize
											 );
											 
							return {{ 
								data: Array.from(uint8Array),
								fromCache: fromCache,
								responseSize: uint8Array.length,
								transferSize: response.headers.get('content-length') || 'unknown'
							}};
						}} catch (error) {{
							throw new Error(`Fetch failed: ${{error.message}}`);
						}}
					}}
				""")

				if download_result and download_result.get('data') and len(download_result['data']) > 0:
					# Ensure unique filename
					unique_filename = await self._get_unique_filename(self.browser_profile.downloads_path, pdf_filename)
					download_path = os.path.join(self.browser_profile.downloads_path, unique_filename)

					# Save the PDF asynchronously
					async with await anyio.open_file(download_path, 'wb') as f:
						await f.write(bytes(download_result['data']))

					# Track the downloaded file
					self._downloaded_files.append(download_path)

					# Log cache information
					cache_status = 'from cache' if download_result.get('fromCache') else 'from network'
					response_size = download_result.get('responseSize', 0)
					self.logger.info(f'📄 Auto-downloaded PDF ({cache_status}, {response_size:,} bytes): {download_path}')

					return download_path
				else:
					self.logger.warning(f'⚠️ No data received when downloading PDF from {pdf_url}')
					return None

			except Exception as e:
				self.logger.warning(f'⚠️ Failed to auto-download PDF from {pdf_url}: {type(e).__name__}: {e}')
				return None

		except Exception as e:
			self.logger.warning(f'⚠️ Error in PDF auto-download check: {type(e).__name__}: {e}')
			return None
