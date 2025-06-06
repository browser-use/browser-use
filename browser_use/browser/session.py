from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

from browser_use.utils import _log_pretty_path, _log_pretty_url

os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'  # https://github.com/microsoft/playwright/issues/35972

import anyio
import psutil
from patchright.async_api import Browser as PatchrightBrowser
from patchright.async_api import BrowserContext as PatchrightBrowserContext
from patchright.async_api import ElementHandle as PatchrightElementHandle
from patchright.async_api import FrameLocator as PatchrightFrameLocator
from patchright.async_api import Page as PatchrightPage
from patchright.async_api import Playwright as Patchright
from patchright.async_api import async_playwright as async_patchright
from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import BrowserContext as PlaywrightBrowserContext
from playwright.async_api import ElementHandle as PlaywrightElementHandle
from playwright.async_api import FrameLocator as PlaywrightFrameLocator
from playwright.async_api import Page as PlaywrightPage
from playwright.async_api import Playwright, async_playwright
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, InstanceOf, PrivateAttr, model_validator
from uuid_extensions import uuid7str

from browser_use.browser.profile import BROWSERUSE_DEFAULT_CHANNEL, BrowserChannel, BrowserProfile
from browser_use.browser.views import (
	BrowserError,
	BrowserStateSummary,
	TabInfo,
	URLNotAllowedError,
)
from browser_use.dom.clickable_element_processor.service import ClickableElementProcessor
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, SelectorMap
from browser_use.utils import match_url_with_domain_pattern, merge_dicts, time_execution_async, time_execution_sync

# Define types to be Union[Patchright, Playwright]
Browser = PatchrightBrowser | PlaywrightBrowser
BrowserContext = PatchrightBrowserContext | PlaywrightBrowserContext
Page = PatchrightPage | PlaywrightPage
ElementHandle = PatchrightElementHandle | PlaywrightElementHandle
FrameLocator = PatchrightFrameLocator | PlaywrightFrameLocator


# Check if running in Docker
IN_DOCKER = os.environ.get('IN_DOCKER', 'false').lower()[0] in 'ty1'

logger = logging.getLogger('browser_use.browser.session')


_GLOB_WARNING_SHOWN = False  # used inside _is_url_allowed to avoid spamming the logs with the same warning multiple times


def _log_glob_warning(domain: str, glob: str):
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
					self.browser_context.pages[0] if (self.browser_context and self.browser_context.pages) else None
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
				self.logger.debug(f'Detected closed browser connection in {func.__name__}, resetting connection state')
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
		populate_by_name=True,
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
	playwright: Playwright | Patchright | None = Field(
		default=None,
		description='Playwright library object returned by: await (playwright or patchright).async_playwright().start()',
		exclude=True,
	)
	browser: InstanceOf[Browser] | None = Field(
		default=None,
		description='playwright Browser object to use (optional)',
		validation_alias=AliasChoices('playwright_browser'),
		exclude=True,
	)
	browser_context: InstanceOf[BrowserContext] | None = Field(
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
	agent_current_page: InstanceOf[Page] | None = Field(  # mutated by self.create_new_tab(url)
		default=None,
		description='Foreground Page that the agent is focused on',
		validation_alias=AliasChoices('current_page', 'page'),  # alias page= allows passing in a playwright Page object easily
		exclude=True,
	)
	human_current_page: InstanceOf[Page] | None = Field(  # mutated by self._setup_current_page_change_listeners()
		default=None,
		description='Foreground Page that the human is focused on',
		exclude=True,
	)

	_cached_browser_state_summary: BrowserStateSummary | None = PrivateAttr(default=None)
	_cached_clickable_element_hashes: CachedClickableElementHashes | None = PrivateAttr(default=None)
	_start_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
	_tab_visibility_callback: Any = PrivateAttr(default=None)
	_logger: logging.Logger | None = PrivateAttr(default=None)

	@model_validator(mode='after')
	def apply_session_overrides_to_profile(self) -> Self:
		"""Apply any extra **kwargs passed to BrowserSession(...) as config overrides on top of browser_profile"""
		session_own_fields = type(self).model_fields.keys()

		# get all the extra kwarg overrides passed to BrowserSession(...) that are actually
		# config Fields tracked by BrowserProfile, instead of BrowserSession's own args
		profile_overrides = self.model_dump(exclude=set(session_own_fields))

		# FOR REPL DEBUGGING ONLY, NEVER ALLOW CIRCULAR REFERENCES IN REAL CODE:
		# self.browser_profile._in_use_by_session = self

		# Only create a copy if there are actual overrides to apply
		if profile_overrides:
			# replace browser_profile with patched version
			self.browser_profile = self.browser_profile.model_copy(update=profile_overrides)

		# FOR REPL DEBUGGING ONLY, NEVER ALLOW CIRCULAR REFERENCES IN REAL CODE:
		# self.browser_profile._in_use_by_session = self

		return self

	@property
	def logger(self) -> logging.Logger:
		"""Get instance-specific logger with session ID in the name"""
		if self._logger is None:
			# Create a child logger with the session ID
			self._logger = logging.getLogger(f'browser_use.BrowserSession[{self.id[-4:]}]')
		return self._logger

	def __repr__(self) -> str:
		return f'BrowserSession[{self.id[-4:]}](profile={self.browser_profile}, {self._connection_str})'

	def __str__(self) -> str:
		return f'BrowserSession[{self.id[-4:]}]'

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

		async with asyncio.timeout(30):  # 30 second timeout for launching
			async with self._start_lock:
				if self.initialized:
					if self.is_connected():
						return self
					else:
						next_step = (
							'attempting to re-connect'
							if self.cdp_url or self.wss_url or self.browser_pid
							else 'launching a new browser'
						)
						self.logger.warning(f'♻️ Browser {self._connection_str} has gone away, {next_step}...')
						# only reset connection state if we expected to be already connected but we're not
						# avoid calling this on *first* start() as it just immediately clears many
						# of the params passed in to BrowserSession(...) init, which the .setup_...() methods below expect
						self._reset_connection_state()

				self.initialized = True  # set this first to ensure two parallel calls to start() don't clash with each other

				try:
					# apply last-minute runtime-computed options to the the browser_profile, validate profile, set up folders on disk
					assert isinstance(self.browser_profile, BrowserProfile)
					self.browser_profile.prepare_user_data_dir()  # create/unlock the <user_data_dir>/SingletonLock
					self.browser_profile.detect_display_configuration()  # adjusts config values, must come before launch/connect

					# launch/connect to the browser:
					# setup playwright library client, Browser, and BrowserContext objects
					await self.setup_playwright()
					await self.setup_browser_via_passed_objects()
					await self.setup_browser_via_browser_pid()
					await self.setup_browser_via_wss_url()
					await self.setup_browser_via_cdp_url()
					await (
						self.setup_new_browser_context()
					)  # creates a new context in existing browser or launches a new persistent context
					assert self.browser_context, f'Failed to connect to or create a new BrowserContext for browser={self.browser}'

					# resize the existing pages and set up foreground tab detection
					await self._setup_viewports()
					await self._setup_current_page_change_listeners()
				except BaseException:
					self.initialized = False
					raise

		# self.logger.debug(f'🎭 started successfully')

		return self

	@property
	def _connection_str(self) -> str:
		"""Get a logging-ready string describing the connection method e.g. browser=playwright+google-chrome-canary (local)"""
		binary_name = (
			Path(self.browser_profile.executable_path).name.lower().replace(' ', '-').replace('.exe', '')
			if self.browser_profile.executable_path
			else (self.browser_profile.channel or BROWSERUSE_DEFAULT_CHANNEL).name.lower().replace('_', '-').replace(' ', '-')
		)  # Google Chrome Canary.exe -> google-chrome-canary
		driver_name = 'playwright'
		if (
			isinstance(self.playwright, Patchright)
			or isinstance(self.browser_context, PatchrightBrowserContext)
			or self.browser_profile.stealth
		):
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

	async def stop(self) -> None:
		"""Shuts down the BrowserSession, killing the browser process (only works if keep_alive=False)"""

		# trying to launch/kill browsers at the same time is an easy way to trash an entire user_data_dir
		# it's worth the 1s or 2s of delay in the worst case to avoid race conditions, user_data_dir can be a few GBs
		# Use timeout to prevent indefinite waiting on lock acquisition
		async with asyncio.timeout(15):  # 15 second timeout for stop operations
			async with self._start_lock:
				# save cookies to disk if cookies_file or storage_state is configured
				# but only if the browser context is still connected
				if self.is_connected():
					try:
						await self.save_storage_state()
					except Exception as e:
						self.logger.debug(f'Failed to save storage state before stopping: {type(e).__name__}: {e}')

				if self.browser_profile.keep_alive:
					self.logger.info(
						f'🕊️ {self}.stop() called but keep_alive=True, leaving the browser running. Use .kill() to force close.'
					)
					return  # nothing to do if keep_alive=True, leave the browser running

				if self.browser_context or self.browser:
					try:
						self.logger.info(
							f'🛑 Closing {self._connection_str} {self.browser_profile.channel.name.lower()} context with '
							f'user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"}'
							f'storage_state= {_log_pretty_path(self.browser_profile.storage_state_path or self.browser_profile.cookies_file) or "<none>"}'
						)
						# Add timeout to prevent hanging on close if context is already closed
						try:
							async with asyncio.timeout(5):  # 5 second timeout for close operation
								await (self.browser or self.browser_context.browser).close()
						except TimeoutError:
							self.logger.warning('⏱️ Timeout while closing browser/context - it may already be closed')
					except Exception as e:
						self.logger.debug(
							f'❌ Error closing playwright browser_context={self.browser_context}: {type(e).__name__}: {e}'
						)
					finally:
						# Always clear references to ensure a fresh start next time
						self.browser_context = None
						self.browser = None

				# kill the chrome subprocess if we were the ones that started it
				if self.browser_pid:
					try:
						proc = psutil.Process(pid=self.browser_pid)
						executable_path = proc.cmdline()[0]
						self.logger.info(f' ↳ Killing browser_pid={self.browser_pid} {_log_pretty_path(executable_path)}')
						# Add timeout for process termination
						try:
							async with asyncio.timeout(5):  # 5 second timeout
								proc.terminate()
								self._kill_child_processes()
								await asyncio.to_thread(proc.wait, timeout=4)
						except (TimeoutError, psutil.TimeoutExpired):
							self.logger.warning(
								f'⏱️ Process did not terminate gracefully, force killing browser_pid={self.browser_pid}'
							)
							proc.kill()  # Force kill if terminate didn't work
						self.browser_pid = None
					except Exception as e:
						if 'NoSuchProcess' not in type(e).__name__:
							self.logger.debug(
								f'❌ Error terminating subprocess with browser_pid={self.browser_pid}: {type(e).__name__}: {e}'
							)

					# Close playwright if we own it
					if self.playwright:
						try:
							# Add timeout to prevent hanging
							async with asyncio.timeout(5):
								await self.playwright.stop()
							self.playwright = None
						except TimeoutError:
							self.logger.warning('⏱️ Timeout while stopping playwright')
							self.playwright = None
						except Exception as e:
							self.logger.debug(f'Error stopping playwright: {type(e).__name__}: {e}')
							self.playwright = None

				self._reset_connection_state()

				# Cancel any remaining background tasks to prevent hanging on exit
				if hasattr(self, '_background_tasks'):
					for task in list(self._background_tasks):
						if not task.done():
							task.cancel()
					self._background_tasks.clear()

	async def close(self) -> None:
		"""Deprecated: Provides backwards-compatibility with old method Browser().close() and playwright BrowserContext.close()"""
		await self.stop()

	async def kill(self) -> None:
		"""Stop the BrowserSession even if keep_alive=True"""
		self.keep_alive = False
		# self.logger.debug(
		# 	f'⏹️ Browser browser_pid={self.browser_pid} user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"} keep_alive={self.browser_profile.keep_alive} (close() called)'
		# )
		await self.stop()

	async def new_context(self, **kwargs):
		"""Deprecated: Provides backwards-compatibility with old class method Browser().new_context()."""
		# TODO: remove this after >=0.3.0
		return self

	async def __aenter__(self) -> BrowserSession:
		await self.start()
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		# self.logger.debug(
		# 	f'⏹️ Stopping gracefully browser_pid={self.browser_pid} user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"} keep_alive={self.browser_profile.keep_alive} (context manager exit)'
		# )
		await self.stop()

	def __del__(self):
		# Avoid keeping references in __del__ that might prevent garbage collection
		try:
			profile = getattr(self, 'browser_profile', None)
			keep_alive = getattr(profile, 'keep_alive', None)
			user_data_dir = getattr(profile, 'user_data_dir', None)
			self.logger.debug(
				f'🛑 Stopping (garbage collected) keep_alive={keep_alive} user_data_dir= {_log_pretty_path(user_data_dir) or "<incognito>"}'
			)

			self._kill_child_processes()

		except BaseException:
			# Never let __del__ raise exceptions
			pass

	def _kill_child_processes(self) -> None:
		"""Kill any child processes that might be related to the browser"""

		if not self.browser_profile.keep_alive and self.browser_pid:
			try:
				browser_proc = psutil.Process(self.browser_pid)

				# Kill all child processes first (recursive)
				for child in browser_proc.children(recursive=True):
					try:
						# self.logger.debug(f'Force killing child process: {child.pid} ({child.name()})')
						child.kill()
					except (psutil.NoSuchProcess, psutil.AccessDenied):
						pass

				# Kill the main browser process
				try:
					# self.logger.debug(f'Force killing browser process: {self.browser_pid}')
					browser_proc.kill()
				except (psutil.NoSuchProcess, psutil.AccessDenied):
					pass
			except Exception as e:
				self.logger.warning(f'Error force-killing browser in BrowserSession.__del__: {type(e).__name__}: {e}')

	async def setup_playwright(self) -> None:
		"""
		Set up playwright library client object: usually the result of (await async_playwright().start())
		Override to customize the set up of the playwright or patchright library object
		"""
		if self.browser_profile.stealth:
			# use patchright instead of playwright
			self.playwright = self.playwright or (await async_patchright().start())
			self.browser_profile.channel = self.browser_profile.channel or BrowserChannel.CHROME
			self.logger.info(f'🕶️ Activated stealth mode using patchright {self.browser_profile.channel.name.lower()} browser...')

			# check for stealth best-practices
			if self.browser_profile.channel and self.browser_profile.channel != BrowserChannel.CHROME:
				self.logger.info(' 🪄 For maximum stealth, (...) should be passed channel=None or BrowserChannel.CHROME')
			if not self.browser_profile.user_data_dir:
				self.logger.info(' 🪄 For maximum stealth, (...) should be passed a persistent user_data_dir=...')
			if self.browser_profile.headless or not self.browser_profile.no_viewport:
				self.logger.info(' 🪄 For maximum stealth, (...) should be passed headless=False & viewport=None')
		else:
			# default is standard playwright chromium (headful, or headless=new)
			self.playwright = self.playwright or (await async_playwright().start())
			self.browser_profile.channel = self.browser_profile.channel or BrowserChannel.CHROMIUM

		# return self.playwright

	async def setup_browser_via_passed_objects(self) -> None:
		"""Override to customize the set up of the connection to an existing browser"""

		# 1. check for a passed Page object, if present, it always takes priority, set browser_context = page.context
		self.browser_context = (self.agent_current_page and self.agent_current_page.context) or self.browser_context or None

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

		chrome_process = psutil.Process(pid=self.browser_pid)
		assert chrome_process.is_running(), 'Chrome process is not running'
		args = chrome_process.cmdline()
		debug_port = next((arg for arg in args if arg.startswith('--remote-debugging-port=')), '').split('=')[-1].strip()
		assert debug_port, (
			f'Could not find --remote-debugging-port=... to connect to in browser launch args: browser_pid={self.browser_pid} {args}'
		)
		# we could automatically relaunch the browser process with that arg added here, but they may have tabs open they dont want to lose
		self.cdp_url = self.cdp_url or f'http://localhost:{debug_port}/'
		self.logger.info(f'🌎 Connecting to existing local browser process: browser_pid={self.browser_pid} on {self.cdp_url}')
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
		self.browser = self.browser or await self.playwright.chromium.connect_over_cdp(
			self.cdp_url,
			**self.browser_profile.kwargs_for_connect().model_dump(),
		)
		self._set_browser_keep_alive(True)  # we connected to an existing browser, dont kill it at the end

	async def setup_new_browser_context(self) -> None:
		"""Launch a new browser and browser_context"""
		current_process = psutil.Process(os.getpid())
		child_pids_before_launch = {child.pid for child in current_process.children(recursive=True)}

		# if we have a browser object but no browser_context, use the first context discovered or make a new one
		if self.browser and not self.browser_context:
			if self.browser.contexts:
				self.browser_context = self.browser.contexts[0]
				self.logger.info(f'🌎 Using first browser_context available in existing browser: {self.browser_context}')
			else:
				self.browser_context = await self.browser.new_context(
					**self.browser_profile.kwargs_for_new_context().model_dump()
				)
				storage_info = (
					f' + loaded storage_state={len(self.browser_profile.storage_state.cookies) if self.browser_profile.storage_state else 0} cookies'
					if self.browser_profile.storage_state
					else ''
				)
				self.logger.info(
					f'🌎 Created new empty browser_context in existing browser{storage_info}: {self.browser_context}'
				)

		# if we still have no browser_context by now, launch a new local one using launch_persistent_context()
		if not self.browser_context:
			self.logger.info(
				f'🌎 Launching new local browser '
				f'{str(type(self.playwright).__module__).split(".")[0]}:{self.browser_profile.channel.name.lower()} keep_alive={self.browser_profile.keep_alive or False} '
				f'user_data_dir= {_log_pretty_path(self.browser_profile.user_data_dir) or "<incognito>"}'
			)
			if not self.browser_profile.user_data_dir:
				# self.logger.debug('🌎 Launching local browser in incognito mode')
				# if no user_data_dir is provided, launch an incognito context with no persistent user_data_dir
				self.browser = self.browser or await self.playwright.chromium.launch(
					**self.browser_profile.kwargs_for_launch().model_dump()
				)
				# self.logger.debug('🌎 Launching new incognito context in browser')
				self.browser_context = await self.browser.new_context(
					**self.browser_profile.kwargs_for_new_context().model_dump()
				)
				# self.logger.debug('🌎 Created new incognito context in browser')
			else:
				# user data dir was provided, prepare it for use
				self.browser_profile.prepare_user_data_dir()

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
						user_data_dir_chrome_version = (self.browser_profile.user_data_dir / 'Last Version').read_text().strip()
					except Exception:
						pass  # let the logger below handle it
					try:
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
		try:
			child_pids_after_launch = {child.pid for child in current_process.children(recursive=True)}
			new_child_pids = child_pids_after_launch - child_pids_before_launch
			new_child_procs = [psutil.Process(pid) for pid in new_child_pids]
			new_chrome_procs = [proc for proc in new_child_procs if 'Helper' not in proc.name() and proc.status() == 'running']
		except Exception as e:
			self.logger.debug(
				f'❌ Error trying to find child chrome processes after launching new browser: {type(e).__name__}: {e}'
			)
			new_chrome_procs = []

		if new_chrome_procs and not self.browser_pid:
			self.browser_pid = new_chrome_procs[0].pid
			self.logger.info(f' ↳ Spawned browser_pid={self.browser_pid} {_log_pretty_path(new_chrome_procs[0].cmdline()[0])}')
			self.logger.debug(' '.join(new_chrome_procs[0].cmdline()))  # print the entire launch command for debugging
			self._set_browser_keep_alive(False)  # close the browser at the end because we launched it

		if self.browser:
			assert self.browser.is_connected(), (
				f'Browser is not connected, did the browser process crash or get killed? (connection method: {self._connection_str})'
			)
			self.logger.debug(f'🌎 browser connected: v{self.browser.version} {self._connection_str}')

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
		await self.browser_context.add_init_script(init_script)

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
				f'📜 Found {len(pages)} existing tabs in browser, agent will start focused on Tab [{pages.index(foreground_page)}]: {foreground_page.url}'
			)
		else:
			foreground_page = await self.browser_context.new_page()
			pages = [foreground_page]
			self.logger.debug('➕ Opened new tab in empty browser context...')

		self.agent_current_page = self.agent_current_page or foreground_page
		self.human_current_page = self.human_current_page or foreground_page
		# self.logger.debug('About to define _BrowserUseonTabVisibilityChange callback')

		def _BrowserUseonTabVisibilityChange(source: dict[str, str]):
			"""hook callback fired when init script injected into a page detects a focus event"""
			new_page = source['page']

			# Update human foreground tab state
			old_foreground = self.human_current_page
			assert self.browser_context is not None, 'BrowserContext object is not set'
			assert old_foreground is not None, 'Old foreground page is not set'
			old_tab_idx = self.browser_context.pages.index(old_foreground)
			self.human_current_page = new_page
			new_tab_idx = self.browser_context.pages.index(new_page)

			# Log before and after for debugging
			old_url = old_foreground and old_foreground.url or 'about:blank'
			new_url = new_page and new_page.url or 'about:blank'
			agent_url = self.agent_current_page and self.agent_current_page.url or 'about:blank'
			agent_tab_idx = self.browser_context.pages.index(self.agent_current_page)
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
			self.logger.debug(f'⚠️ Failed to register init script for tab focus detection: {e}')

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
				page_idx = self.browser_context.pages.index(page)
				self.logger.debug(
					f'⚠️ Failed to add visibility listener to existing tab, is it crashed or ignoring CDP commands?: [{page_idx}]{page.url}: {type(e).__name__}: {e}'
				)

	async def _setup_viewports(self) -> None:
		"""Resize any existing page viewports to match the configured size, set up storage_state, permissions, geolocation, etc."""

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
			+ f'storage_state={_log_pretty_path(self.browser_profile.storage_state or self.browser_profile.cookies_file) or "<none>"} '
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
				await self.browser_context.set_default_timeout(self.browser_profile.default_timeout)
			if self.browser_profile.default_navigation_timeout:
				await self.browser_context.set_default_navigation_timeout(self.browser_profile.default_navigation_timeout)
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
				cdp_session = await page.context.new_cdp_session(page)
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
						**self.browser_profile.window_size,
					)
					return
				except Exception as e:
					pass

				self.logger.warning(
					f'⚠️ Failed to resize browser window to {_log_size(self.browser_profile.window_size)} using CDP setWindowBounds: {type(e).__name__}: {e}'
				)

	def _set_browser_keep_alive(self, keep_alive: bool | None) -> None:
		"""set the keep_alive flag on the browser_profile, defaulting to True if keep_alive is None"""
		if self.browser_profile.keep_alive is None:
			self.browser_profile.keep_alive = keep_alive

	def is_connected(self) -> bool:
		"""
		Check if the browser session has valid, connected browser and context objects.
		Returns False if any of the following conditions are met:
		- No browser_context exists
		- Browser exists but is disconnected
		- Browser_context's browser exists but is disconnected
		- Browser_context itself is closed/unusable
		"""
		# Check if browser_context is missing
		if not self.browser_context:
			return False

		# Check if browser exists but is disconnected
		if self.browser and not self.browser.is_connected():
			return False

		# Check if browser_context's browser exists but is disconnected
		if self.browser_context.browser and not self.browser_context.browser.is_connected():
			return False

		# Check if the browser_context itself is closed/unusable
		try:
			# Try to access a property that would fail if the context is closed
			_ = self.browser_context.pages
			# Additional check: try to access the browser property which might fail if context is closed
			if self.browser_context.browser and not self.browser_context.browser.is_connected():
				return False
			return True
		except Exception:
			return False

	def _reset_connection_state(self) -> None:
		"""Reset the browser connection state when disconnection is detected"""
		self.initialized = False
		self.browser = None
		self.browser_context = None
		self.agent_current_page = None
		self.human_current_page = None
		self._cached_clickable_element_hashes = None
		self._cached_browser_state_summary = None
		# Don't set playwright to None here - it should be explicitly stopped with playwright.stop()

		# Cancel any background tasks to prevent hanging
		if hasattr(self, '_background_tasks'):
			for task in list(self._background_tasks):
				if not task.done():
					task.cancel()
			self._background_tasks.clear()
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
				self.logger.info(f'⚰️ Browser browser_pid={self.browser_pid} has gone away or crashed')
				# process has gone away or crashed, pid is no longer valid so we clear it
				self.browser_pid = None

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
				# if all tabs are closed, open a new one
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
		pages = self.browser_context.pages
		if not pages or tab_index >= len(pages):
			raise IndexError('Tab index out of range')
		page = pages[tab_index]
		self.agent_current_page = page

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
	async def get_dom_element_by_index(self, index: int) -> Any | None:
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
						self.logger.debug(f'⬇️ Download triggered. Saved file to: {download_path}')
						return download_path
					except Exception:
						# If no download is triggered, treat as normal click
						self.logger.debug('No download triggered within timeout. Checking navigation...')
						await page.wait_for_load_state()
						await self._check_and_handle_navigation(page)
				else:
					# If downloads are disabled, just perform the click
					await click_func()
					await page.wait_for_load_state()
					await self._check_and_handle_navigation(page)

			try:
				return await perform_click(lambda: element_handle.click(timeout=1500))
			except URLNotAllowedError as e:
				raise e
			except Exception:
				try:
					return await perform_click(lambda: page.evaluate('(el) => el.click()', element_handle))
				except URLNotAllowedError as e:
					raise e
				except Exception as e:
					raise Exception(f'Failed to click element: {type(e).__name__}: {e}')

		except URLNotAllowedError as e:
			raise e
		except Exception as e:
			raise Exception(f'Failed to click element: {repr(element_node)}. Error: {str(e)}')

	@require_initialization
	@time_execution_async('--get_tabs_info')
	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all tabs"""

		tabs_info = []
		for page_id, page in enumerate(self.browser_context.pages):
			try:
				tab_info = TabInfo(page_id=page_id, url=page.url, title=await asyncio.wait_for(page.title(), timeout=1))
			except TimeoutError:
				# page.title() can hang forever on tabs that are crashed/disappeared/about:blank
				# we dont want to try automating those tabs because they will hang the whole script
				self.logger.debug(f'⚠️ Failed to get tab info for tab #{page_id}: {_log_pretty_url(page.url)} (ignoring)')
				tab_info = TabInfo(page_id=page_id, url='about:blank', title='ignore this tab and do not use it')
			tabs_info.append(tab_info)

		return tabs_info

	@require_initialization
	async def close_tab(self, tab_index: int | None = None) -> None:
		pages = self.browser_context.pages
		if not pages:
			return

		if tab_index is None:
			# to tab_index passed, just close the current agent page
			page = await self.get_current_page()
		else:
			# otherwise close the tab at the given index
			page = pages[tab_index]

		await page.close()

		# reset the self.agent_current_page and self.human_current_page references to first available tab
		await self.get_current_page()

	# --- Page navigation ---
	@require_initialization
	async def navigate(self, url: str) -> None:
		if self.agent_current_page:
			await self.agent_current_page.goto(url)
		else:
			await self.create_new_tab(url)

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
			return await self.browser_context.cookies()
		return []

	async def save_cookies(self, *args, **kwargs) -> None:
		"""
		Old name for the new save_storage_state() function.
		"""
		await self.save_storage_state(*args, **kwargs)

	async def _save_cookies_to_file(self, path: Path, cookies: list[dict[str, Any]] | None) -> None:
		try:
			cookies_file_path = Path(path or self.browser_profile.cookies_file).expanduser().resolve()
			cookies_file_path.parent.mkdir(parents=True, exist_ok=True)

			# Write to a temporary file first
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

	async def _save_storage_state_to_file(self, path: Path, storage_state: dict[str, Any] | None) -> None:
		try:
			json_path = Path(path).expanduser().resolve()
			json_path.parent.mkdir(parents=True, exist_ok=True)
			storage_state = storage_state or await self.browser_context.storage_state()

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

			self.logger.info(f'🍪 Saved {len(storage_state["cookies"])} cookies to storage_state= {_log_pretty_path(json_path)}')
		except Exception as e:
			self.logger.warning(f'❌ Failed to save cookies to storage_state= {_log_pretty_path(path)}: {type(e).__name__}: {e}')

	@require_initialization
	async def save_storage_state(self, path: Path | None = None) -> None:
		"""
		Save cookies to the specified path or the configured cookies_file and/or storage_state.
		"""
		storage_state = await self.browser_context.storage_state()
		cookies = storage_state['cookies']

		# they passed an explicit path, only save to that path and return
		if path:
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
			await self._save_cookies_to_file(path or self.browser_profile.cookies_file, cookies)
			await self._save_storage_state_to_file(path.parent / 'storage_state.json', storage_state)
			new_path = path.parent / 'storage_state.json'
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

			cookies_path = Path(self.browser_profile.cookies_file)
			if not cookies_path.is_absolute():
				cookies_path = Path(self.browser_profile.downloads_path or '.') / cookies_path

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
					storage_state = json.loads(storage_state_text)
				except Exception as e:
					self.logger.warning(
						f'❌ Failed to load cookies from storage_state= {_log_pretty_path(self.browser_profile.storage_state)}: {type(e).__name__}: {e}'
					)
					return

			try:
				assert isinstance(storage_state, dict), f'Got unexpected type for storage_state: {type(storage_state)}'
				await self.browser_context.add_cookies(storage_state['cookies'])
				# TODO: also handle localStroage, IndexedDB, SessionStorage
				# playwright doesn't provide an API for setting these before launch
				# https://playwright.dev/python/docs/auth#session-storage
				# await self.browser_context.add_local_storage(storage_state['localStorage'])
				self.logger.info(
					f'🍪 Loaded {len(storage_state["cookies"])} cookies from storage_state= {_log_pretty_path(self.browser_profile.storage_state)}'
				)
			except Exception as e:
				self.logger.warning(
					f'❌ Failed to load cookies from storage_state= {_log_pretty_path(self.browser_profile.storage_state)}: {type(e).__name__}: {e}'
				)
				return

	async def load_cookies_from_file(self, *args, **kwargs) -> None:
		"""
		Old name for the new load_storage_state() function.
		"""
		await self.load_storage_state(*args, **kwargs)

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

		# just for logging, calculate how much data was downloaded
		try:
			bytes_used = await page.evaluate("""
				() => {
					let total = 0;
					for (const entry of performance.getEntriesByType('resource')) {
						total += entry.transferSize || 0;
					}
					for (const nav of performance.getEntriesByType('navigation')) {
						total += nav.transferSize || 0;
					}
					return total;
				}
			""")
		except Exception:
			bytes_used = None

		tab_idx = self.tabs.index(page)
		if bytes_used is not None:
			self.logger.debug(
				f'➡️ Page navigation [{tab_idx}]{_log_pretty_url(page.url, 40)} used {bytes_used / 1024:.1f} KB in {elapsed:.2f}s, waiting +{remaining:.2f}s for all frames to finish'
			)
		else:
			self.logger.debug(
				f'➡️ Page navigation [{tab_idx}]{_log_pretty_url(page.url, 40)} took {elapsed:.2f}s, waiting +{remaining:.2f}s for all frames to finish'
			)

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
						_log_glob_warning(domain, allowed_domain)
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
		if not self._is_url_allowed(url):
			raise BrowserError(f'Navigation to non-allowed URL: {url}')

		page = await self.get_current_page()
		await page.goto(url)
		await page.wait_for_load_state()

	async def refresh_page(self):
		"""Refresh the agent's current page"""

		page = await self.get_current_page()
		await page.reload()
		await page.wait_for_load_state()

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

	@time_execution_sync('--get_state_summary')  # This decorator might need to be updated to handle async
	async def get_state_summary(self, cache_clickable_elements_hashes: bool) -> BrowserStateSummary:
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

		# Save cookies if a file is specified
		if self.browser_profile.cookies_file:
			# Use create_task but store reference to allow cleanup
			task = asyncio.create_task(self.save_cookies())
			# Set task name for debugging
			task.set_name(f'save_cookies_{self.id[-4:]}')
			# Fire and forget, but the task will complete quickly

		return self._cached_browser_state_summary

	async def _get_updated_state(self, focus_element: int = -1) -> BrowserStateSummary:
		"""Update and return state."""

		page = await self.get_current_page()

		# Check if current page is still valid, if not switch to another available page
		try:
			# Test if page is still accessible
			await page.evaluate('1')
		except Exception as e:
			self.logger.debug(f'👋 Current page is no longer accessible: {type(e).__name__}: {e}')
			raise BrowserError('Browser closed: no valid pages available')

		try:
			await self.remove_highlights()
			dom_service = DomService(page)
			content = await dom_service.get_clickable_elements(
				focus_element=focus_element,
				viewport_expansion=self.browser_profile.viewport_expansion,
				highlight_elements=self.browser_profile.highlight_elements,
			)

			tabs_info = await self.get_tabs_info()

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

			screenshot_b64 = await self.take_screenshot()
			pixels_above, pixels_below = await self.get_scroll_info(page)

			self.browser_state_summary = BrowserStateSummary(
				element_tree=content.element_tree,
				selector_map=content.selector_map,
				url=page.url,
				title=await page.title(),
				tabs=tabs_info,
				screenshot=screenshot_b64,
				pixels_above=pixels_above,
				pixels_below=pixels_below,
			)

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

		page = await self.get_current_page()
		await page.wait_for_load_state(
			timeout=5000,
		)  # page has already loaded by this point, this is extra for previous action animations/frame loads to settle

		# 0. Attempt full-page screenshot (sometimes times out for huge pages)
		try:
			screenshot = await page.screenshot(
				full_page=full_page,
				scale='css',
				timeout=15000,
				animations='disabled',
				caret='initial',
			)

			screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
			return screenshot_b64
		except Exception as e:
			self.logger.error(
				f'❌ Failed to take full-page screenshot: {type(e).__name__}: {e} falling back to viewport-only screenshot'
			)

		# Fallback method: manually expand the viewport and take a screenshot of the entire viewport

		# 1. Get current page dimensions
		dimensions = await page.evaluate("""() => {
			return {
				width: window.innerWidth,
				height: window.innerHeight,
				devicePixelRatio: window.devicePixelRatio || 1
			};
		}""")

		# 2. Save current viewport state and calculate expanded dimensions
		original_viewport = page.viewport_size
		viewport_expansion = self.browser_profile.viewport_expansion if self.browser_profile.viewport_expansion else 0

		expanded_width = dimensions['width']  # Keep width unchanged
		expanded_height = dimensions['height'] + viewport_expansion

		# 3. Expand the viewport if we are using one
		if original_viewport:
			await page.set_viewport_size({'width': expanded_width, 'height': expanded_height})

		try:
			# 4. Take full-viewport screenshot
			screenshot = await page.screenshot(
				full_page=False,
				scale='css',
				timeout=30000,
				clip={'x': 0, 'y': 0, 'width': expanded_width, 'height': expanded_height},
				# animations='disabled',   # these can cause CSP errors on some pages, leading to a red herring "waiting for fonts to load" error
				# caret='initial',
			)
			# TODO: manually take multiple clipped screenshots to capture the full height and stitch them together?

			screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
			return screenshot_b64

		finally:
			# 5. Restore original viewport state if we expanded it
			if original_viewport:
				# Viewport was originally enabled, restore to original dimensions
				await page.set_viewport_size(original_viewport)
			else:
				# Viewport was originally disabled, no need to restore it
				# await page.set_viewport_size(None)  # unfortunately this is not supported by playwright
				pass

	# region - User Actions

	@staticmethod
	async def _get_unique_filename(directory: str, filename: str) -> str:
		"""Generate a unique filename for downloads by appending (1), (2), etc., if a file already exists."""
		base, ext = os.path.splitext(filename)
		counter = 1
		new_filename = filename
		while os.path.exists(os.path.join(directory, new_filename)):
			new_filename = f'{base} ({counter}){ext}'
			counter += 1
		return new_filename

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
			current_frame = current_frame.frame_locator(css_selector)

		css_selector = self._enhanced_css_selector_for_element(
			element, include_dynamic_attributes=self.browser_profile.include_dynamic_attributes
		)

		try:
			if isinstance(current_frame, FrameLocator):
				element_handle = await current_frame.locator(css_selector).element_handle()
				return element_handle
			else:
				# Try to scroll into view if hidden
				element_handle = await current_frame.query_selector(css_selector)
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
			# Highlight before typing
			# if element_node.highlight_index is not None:
			# 	await self._update_state(focus_element=element_node.highlight_index)

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

			# Get element properties to determine input method
			tag_handle = await element_handle.get_property('tagName')
			tag_name = (await tag_handle.json_value()).lower()
			is_contenteditable = await element_handle.get_property('isContentEditable')
			readonly_handle = await element_handle.get_property('readOnly')
			disabled_handle = await element_handle.get_property('disabled')

			readonly = await readonly_handle.json_value() if readonly_handle else False
			disabled = await disabled_handle.json_value() if disabled_handle else False

			# always click the element first to make sure it's in the focus
			await element_handle.click()
			await asyncio.sleep(0.1)

			try:
				if (await is_contenteditable.json_value() or tag_name == 'input') and not (readonly or disabled):
					await element_handle.evaluate('el => {el.textContent = ""; el.value = "";}')
					await element_handle.type(text, delay=5)
				else:
					await element_handle.fill(text)
			except Exception:
				# last resort fallback, assume it's already focused after we clicked on it,
				# just simulate keypresses on the entire page
				page = await self.get_current_page()
				await page.keyboard.type(text)

		except Exception as e:
			self.logger.debug(
				f'❌ Failed to input text into element: {repr(element_node)} on page {_log_pretty_url(page.url)}: {type(e).__name__}: {e}'
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
		self.human_current_page = page

		# Bring tab to front and wait for it to load
		await page.bring_to_front()
		await page.wait_for_load_state()

		# Set the viewport size for the tab
		if self.browser_profile.viewport:
			await page.set_viewport_size(self.browser_profile.viewport)

		return page

	@time_execution_async('--create_new_tab')
	async def create_new_tab(self, url: str | None = None) -> Page:
		"""Create a new tab and optionally navigate to a URL"""

		if url and not self._is_url_allowed(url):
			raise BrowserError(f'Cannot create new tab with non-allowed URL: {url}')

		if not self.initialized or not self.is_connected():
			# If we were initialized but lost connection, reset state first to avoid infinite loops
			if self.initialized and not self.is_connected():
				self.logger.warning('Browser was initialized but lost connection, resetting state before restart')
				self._reset_connection_state()
			await self.start()
			assert self.browser_context, 'Browser context is not set'

		new_page = await self.browser_context.new_page()

		# Update agent tab reference
		self.agent_current_page = new_page

		# Update human tab reference if there is no human tab yet
		if (not self.human_current_page) or self.human_current_page.is_closed():
			self.human_current_page = new_page

		await new_page.wait_for_load_state()

		# Set the viewport size for the new tab
		if self.browser_profile.viewport:
			await new_page.set_viewport_size(self.browser_profile.viewport)

		if url:
			try:
				await new_page.goto(url, wait_until='domcontentloaded')
				await self._wait_for_page_and_frames_load(timeout_overwrite=1)
			except Exception as e:
				self.logger.error(f'❌ Error navigating to {url}: {type(e).__name__}: {e}')

		assert self.human_current_page is not None
		assert self.agent_current_page is not None
		# if url:  # sometimes this does not pass because JS or HTTP redirects the page really fast
		# 	assert self.agent_current_page.url == url
		# else:
		# 	assert self.agent_current_page.url == 'about:blank'

		# if there are any unused about:blank tabs after we open a new tab, close them to clean up unused tabs
		for page in self.browser_context.pages:
			if page.url == 'about:blank' and page != self.agent_current_page:
				await page.close()
				self.human_current_page = (  # in case we just closed the human's tab, fix the refs
					self.human_current_page if not self.human_current_page.is_closed() else self.agent_current_page
				)

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

	@require_initialization
	async def find_file_upload_element_by_index(self, index: int) -> DOMElementNode | None:
		"""
		Find a file upload element related to the element at the given index:
		- Check if the element itself is a file input
		- Check if it's a label pointing to a file input
		- Recursively search children for file inputs
		- Check siblings for file inputs

		Args:
			index: The index of the candidate element (could be a file input, label, or parent element)

		Returns:
			The DOM element for the file input if found, None otherwise
		"""
		try:
			selector_map = await self.get_selector_map()
			if index not in selector_map:
				return None

			candidate_element = selector_map[index]

			def is_file_input(node: DOMElementNode) -> bool:
				return isinstance(node, DOMElementNode) and node.tag_name == 'input' and node.attributes.get('type') == 'file'

			def find_element_by_id(node: DOMElementNode, element_id: str) -> DOMElementNode | None:
				if isinstance(node, DOMElementNode):
					if node.attributes.get('id') == element_id:
						return node
					for child in node.children:
						result = find_element_by_id(child, element_id)
						if result:
							return result
				return None

			def get_root(node: DOMElementNode) -> DOMElementNode:
				root = node
				while root.parent:
					root = root.parent
				return root

			# Recursively search for file input in node and its children
			def find_file_input_recursive(
				node: DOMElementNode, max_depth: int = 3, current_depth: int = 0
			) -> DOMElementNode | None:
				if current_depth > max_depth or not isinstance(node, DOMElementNode):
					return None

				# Check current element
				if is_file_input(node):
					return node

				# Recursively check children
				if node.children and current_depth < max_depth:
					for child in node.children:
						if isinstance(child, DOMElementNode):
							result = find_file_input_recursive(child, max_depth, current_depth + 1)
							if result:
								return result
				return None

			# Check if current element is a file input
			if is_file_input(candidate_element):
				return candidate_element

			# Check if it's a label pointing to a file input
			if candidate_element.tag_name == 'label' and candidate_element.attributes.get('for'):
				input_id = candidate_element.attributes.get('for')
				root_element = get_root(candidate_element)

				target_input = find_element_by_id(root_element, input_id)
				if target_input and is_file_input(target_input):
					return target_input

			# Recursively check children
			child_result = find_file_input_recursive(candidate_element)
			if child_result:
				return child_result

			# Check siblings
			if candidate_element.parent:
				for sibling in candidate_element.parent.children:
					if sibling is not candidate_element and isinstance(sibling, DOMElementNode):
						if is_file_input(sibling):
							return sibling
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
		await page.evaluate("""() => {
			document.title = 'Setting up...';

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
			img.src = 'https://github.com/browser-use.png';
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
		}""")
