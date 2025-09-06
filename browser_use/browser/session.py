"""Event-driven browser session with backwards compatibility."""

import asyncio
import logging
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, Self, cast

import httpx
from bubus import EventBus
from cdp_use import CDPClient
from cdp_use.cdp.fetch import AuthRequiredEvent, RequestPausedEvent
from cdp_use.cdp.network import Cookie
from cdp_use.cdp.target import AttachedToTargetEvent, SessionID, TargetID
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from uuid_extensions import uuid7str

# CDP logging is now handled by setup_logging() in logging_config.py
# It automatically sets CDP logs to the same level as browser_use logs
from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserConnectedEvent,
	BrowserErrorEvent,
	BrowserLaunchEvent,
	BrowserLaunchResult,
	BrowserStartEvent,
	BrowserStateRequestEvent,
	BrowserStopEvent,
	BrowserStoppedEvent,
	CloseTabEvent,
	FileDownloadedEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	NavigationStartedEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TabCreatedEvent,
)
from browser_use.browser.profile import BrowserProfile, ProxySettings
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import EnhancedDOMTreeNode, TargetInfo
from browser_use.observability import observe_debug
from browser_use.utils import _log_pretty_url, is_new_tab_page

DEFAULT_BROWSER_PROFILE = BrowserProfile()

_LOGGED_UNIQUE_SESSION_IDS = set()  # track unique session IDs that have been logged to make sure we always assign a unique enough id to new sessions and avoid ambiguity in logs
red = '\033[91m'
reset = '\033[0m'


class CDPSession(BaseModel):
	"""Info about a single CDP session bound to a specific target.

	Can optionally use its own WebSocket connection for better isolation.
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True, revalidate_instances='never')

	cdp_client: CDPClient

	target_id: TargetID
	session_id: SessionID
	title: str = 'Unknown title'
	url: str = 'about:blank'

	# Track if this session owns its CDP client (for cleanup)
	owns_cdp_client: bool = False

	@classmethod
	async def for_target(
		cls,
		cdp_client: CDPClient,
		target_id: TargetID,
		new_socket: bool = False,
		cdp_url: str | None = None,
		domains: list[str] | None = None,
	):
		"""Create a CDP session for a target.

		Args:
			cdp_client: Existing CDP client to use (or just for reference if creating own)
			target_id: Target ID to attach to
			new_socket: If True, create a dedicated WebSocket connection for this target
			cdp_url: CDP URL (required if new_socket is True)
			domains: List of CDP domains to enable. If None, enables default domains.
		"""
		if new_socket:
			if not cdp_url:
				raise ValueError('cdp_url required when new_socket=True')
			# Create a new CDP client with its own WebSocket connection
			import logging

			logger = logging.getLogger(f'browser_use.CDPSession.{target_id[-4:]}')
			logger.debug(f'🔌 Creating new dedicated WebSocket connection for target 🅣 {target_id}')

			target_cdp_client = CDPClient(cdp_url)
			await target_cdp_client.start()

			cdp_session = cls(
				cdp_client=target_cdp_client,
				target_id=target_id,
				session_id='connecting',
				owns_cdp_client=True,
			)
		else:
			# Use shared CDP client
			cdp_session = cls(
				cdp_client=cdp_client,
				target_id=target_id,
				session_id='connecting',
				owns_cdp_client=False,
			)
		return await cdp_session.attach(domains=domains)

	async def attach(self, domains: list[str] | None = None) -> Self:
		result = await self.cdp_client.send.Target.attachToTarget(
			params={
				'targetId': self.target_id,
				'flatten': True,
				'filter': [  # type: ignore
					{'type': 'page', 'exclude': False},
					{'type': 'iframe', 'exclude': False},
				],
			}
		)
		self.session_id = result['sessionId']

		# Use specified domains or default domains
		domains = domains or ['Page', 'DOM', 'DOMSnapshot', 'Accessibility', 'Runtime', 'Inspector']

		# Enable all domains in parallel
		enable_tasks = []
		for domain in domains:
			# Get the enable method, e.g. self.cdp_client.send.Page.enable(session_id=self.session_id)
			domain_api = getattr(self.cdp_client.send, domain, None)
			# Browser and Target domains don't use session_id, dont pass it for those
			enable_kwargs = {} if domain in ['Browser', 'Target'] else {'session_id': self.session_id}
			assert domain_api and hasattr(domain_api, 'enable'), (
				f'{domain_api} is not a recognized CDP domain with a .enable() method'
			)
			enable_tasks.append(domain_api.enable(**enable_kwargs))

		results = await asyncio.gather(*enable_tasks, return_exceptions=True)
		if any(isinstance(result, Exception) for result in results):
			raise RuntimeError(f'Failed to enable requested CDP domain: {results}')

		# in case 'Debugger' domain is enabled, disable breakpoints on the page so it doesnt pause on crashes / debugger statements
		# also covered by Runtime.runIfWaitingForDebugger() calls in get_or_create_cdp_session()
		try:
			await self.cdp_client.send.Debugger.setSkipAllPauses(params={'skip': True}, session_id=self.session_id)
			# if 'Debugger' not in domains:
			# 	await self.cdp_client.send.Debugger.disable()
			# await cdp_session.cdp_client.send.EventBreakpoints.disable(session_id=cdp_session.session_id)
		except Exception:
			# self.logger.warning(f'Failed to disable page JS breakpoints: {e}')
			pass

		target_info = await self.get_target_info()
		self.title = target_info['title']
		self.url = target_info['url']
		return self

	async def disconnect(self) -> None:
		"""Disconnect and cleanup if this session owns its CDP client."""
		if self.owns_cdp_client and self.cdp_client:
			try:
				await self.cdp_client.stop()
			except Exception:
				pass  # Ignore errors during cleanup

	async def get_tab_info(self) -> TabInfo:
		target_info = await self.get_target_info()
		return TabInfo(
			target_id=target_info['targetId'],
			url=target_info['url'],
			title=target_info['title'],
		)

	async def get_target_info(self) -> TargetInfo:
		result = await self.cdp_client.send.Target.getTargetInfo(params={'targetId': self.target_id})
		return result['targetInfo']


class BrowserSession(BaseModel):
	"""Event-driven browser session with backwards compatibility.

	This class provides a 2-layer architecture:
	- High-level event handling for agents/tools
	- Direct CDP/Playwright calls for browser operations

	Supports both event-driven and imperative calling styles.

	Browser configuration is stored in the browser_profile, session identity in direct fields:
	```python
	# Direct settings (recommended for most users)
	session = BrowserSession(headless=True, user_data_dir='./profile')

	# Or use a profile (for advanced use cases)
	session = BrowserSession(browser_profile=BrowserProfile(...))

	# Access session fields directly, browser settings via profile or property
	print(session.id)  # Session field
	```
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True,
		validate_assignment=True,
		extra='forbid',
		revalidate_instances='never',  # resets private attrs on every model rebuild
	)

	def __init__(
		self,
		# Core configuration
		id: str | None = None,
		cdp_url: str | None = None,
		is_local: bool = False,
		browser_profile: BrowserProfile | None = None,
		# BrowserProfile fields that can be passed directly
		# From BrowserConnectArgs
		headers: dict[str, str] | None = None,
		# From BrowserLaunchArgs
		env: dict[str, str | float | bool] | None = None,
		executable_path: str | Path | None = None,
		headless: bool | None = None,
		args: list[str] | None = None,
		ignore_default_args: list[str] | Literal[True] | None = None,
		channel: str | None = None,
		chromium_sandbox: bool | None = None,
		devtools: bool | None = None,
		downloads_path: str | Path | None = None,
		traces_dir: str | Path | None = None,
		# From BrowserContextArgs
		accept_downloads: bool | None = None,
		permissions: list[str] | None = None,
		user_agent: str | None = None,
		screen: dict | None = None,
		viewport: dict | None = None,
		no_viewport: bool | None = None,
		device_scale_factor: float | None = None,
		record_har_content: str | None = None,
		record_har_mode: str | None = None,
		record_har_path: str | Path | None = None,
		record_video_dir: str | Path | None = None,
		record_video_framerate: int | None = None,
		record_video_size: dict | None = None,
		# From BrowserLaunchPersistentContextArgs
		user_data_dir: str | Path | None = None,
		# From BrowserNewContextArgs
		storage_state: str | Path | dict[str, Any] | None = None,
		# BrowserProfile specific fields
		disable_security: bool | None = None,
		deterministic_rendering: bool | None = None,
		allowed_domains: list[str] | None = None,
		keep_alive: bool | None = None,
		proxy: ProxySettings | None = None,
		enable_default_extensions: bool | None = None,
		window_size: dict | None = None,
		window_position: dict | None = None,
		cross_origin_iframes: bool | None = None,
		minimum_wait_page_load_time: float | None = None,
		wait_for_network_idle_page_load_time: float | None = None,
		wait_between_actions: float | None = None,
		highlight_elements: bool | None = None,
		filter_highlight_ids: bool | None = None,
		auto_download_pdfs: bool | None = None,
		profile_directory: str | None = None,
		cookie_whitelist_domains: list[str] | None = None,
	):
		# Following the same pattern as AgentSettings in service.py
		# Only pass non-None values to avoid validation errors
		profile_kwargs = {k: v for k, v in locals().items() if k not in ['self', 'browser_profile', 'id'] and v is not None}

		# if is_local is False but executable_path is provided, set is_local to True
		if is_local is False and executable_path is not None:
			profile_kwargs['is_local'] = True
		if not cdp_url:
			profile_kwargs['is_local'] = True

		# Create browser profile from direct parameters or use provided one
		if browser_profile is not None:
			# Merge any direct kwargs into the provided browser_profile (direct kwargs take precedence)
			merged_kwargs = {**browser_profile.model_dump(exclude_unset=True), **profile_kwargs}
			resolved_browser_profile = BrowserProfile(**merged_kwargs)
		else:
			resolved_browser_profile = BrowserProfile(**profile_kwargs)

		# Initialize the Pydantic model
		super().__init__(
			id=id or str(uuid7str()),
			browser_profile=resolved_browser_profile,
		)

	# Session configuration (session identity only)
	id: str = Field(default_factory=lambda: str(uuid7str()), description='Unique identifier for this browser session')

	# Browser configuration (reusable profile)
	browser_profile: BrowserProfile = Field(
		default_factory=lambda: DEFAULT_BROWSER_PROFILE,
		description='BrowserProfile() options to use for the session, otherwise a default profile will be used',
	)

	# Convenience properties for common browser settings
	@property
	def cdp_url(self) -> str | None:
		"""CDP URL from browser profile."""
		return self.browser_profile.cdp_url

	@property
	def is_local(self) -> bool:
		"""Whether this is a local browser instance from browser profile."""
		return self.browser_profile.is_local

	# Main shared event bus for all browser session + all watchdogs
	event_bus: EventBus = Field(default_factory=EventBus)

	# Mutable public state
	agent_focus: CDPSession | None = None

	# Mutable private state shared between watchdogs
	_cdp_client_root: CDPClient | None = PrivateAttr(default=None)
	_cdp_session_pool: dict[str, CDPSession] = PrivateAttr(default_factory=dict)
	_cached_browser_state_summary: Any = PrivateAttr(default=None)
	_cached_selector_map: dict[int, EnhancedDOMTreeNode] = PrivateAttr(default_factory=dict)
	_downloaded_files: list[str] = PrivateAttr(default_factory=list)  # Track files downloaded during this session

	# Watchdogs
	_crash_watchdog: Any | None = PrivateAttr(default=None)
	_downloads_watchdog: Any | None = PrivateAttr(default=None)
	_aboutblank_watchdog: Any | None = PrivateAttr(default=None)
	_security_watchdog: Any | None = PrivateAttr(default=None)
	_storage_state_watchdog: Any | None = PrivateAttr(default=None)
	_local_browser_watchdog: Any | None = PrivateAttr(default=None)
	_default_action_watchdog: Any | None = PrivateAttr(default=None)
	_dom_watchdog: Any | None = PrivateAttr(default=None)
	_screenshot_watchdog: Any | None = PrivateAttr(default=None)
	_permissions_watchdog: Any | None = PrivateAttr(default=None)
	_recording_watchdog: Any | None = PrivateAttr(default=None)

	_logger: Any = PrivateAttr(default=None)

	@property
	def logger(self) -> Any:
		"""Get instance-specific logger with session ID in the name"""
		# **regenerate it every time** because our id and str(self) can change as browser connection state changes
		# if self._logger is None or not self._cdp_client_root:
		# 	self._logger = logging.getLogger(f'browser_use.{self}')
		return logging.getLogger(f'browser_use.{self}')

	@cached_property
	def _id_for_logs(self) -> str:
		"""Get human-friendly semi-unique identifier for differentiating different BrowserSession instances in logs"""
		str_id = self.id[-4:]  # default to last 4 chars of truly random uuid, less helpful than cdp port but always unique enough
		port_number = (self.cdp_url or 'no-cdp').rsplit(':', 1)[-1].split('/', 1)[0].strip()
		port_is_random = not port_number.startswith('922')
		port_is_unique_enough = port_number not in _LOGGED_UNIQUE_SESSION_IDS
		if port_number and port_number.isdigit() and port_is_random and port_is_unique_enough:
			# if cdp port is random/unique enough to identify this session, use it as our id in logs
			_LOGGED_UNIQUE_SESSION_IDS.add(port_number)
			str_id = port_number
		return str_id

	@property
	def _tab_id_for_logs(self) -> str:
		return self.agent_focus.target_id[-2:] if self.agent_focus and self.agent_focus.target_id else f'{red}--{reset}'

	def __repr__(self) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs} (cdp_url={self.cdp_url}, profile={self.browser_profile})'

	def __str__(self) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs}'

	async def reset(self) -> None:
		"""Clear all cached CDP sessions with proper cleanup."""

		# TODO: clear the event bus queue here, implement this helper
		# await self.event_bus.wait_for_idle(timeout=5.0)
		# await self.event_bus.clear()

		# Disconnect sessions that own their WebSocket connections
		for session in self._cdp_session_pool.values():
			if hasattr(session, 'disconnect'):
				await session.disconnect()
		self._cdp_session_pool.clear()

		self._cdp_client_root = None  # type: ignore
		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self._downloaded_files.clear()

		self.agent_focus = None
		if self.is_local:
			self.browser_profile.cdp_url = None

		self._crash_watchdog = None
		self._downloads_watchdog = None
		self._aboutblank_watchdog = None
		self._security_watchdog = None
		self._storage_state_watchdog = None
		self._local_browser_watchdog = None
		self._default_action_watchdog = None
		self._dom_watchdog = None
		self._screenshot_watchdog = None
		self._permissions_watchdog = None
		self._recording_watchdog = None

	def model_post_init(self, __context) -> None:
		"""Register event handlers after model initialization."""
		# Check if handlers are already registered to prevent duplicates

		from browser_use.browser.watchdog_base import BaseWatchdog

		start_handlers = self.event_bus.handlers.get('BrowserStartEvent', [])
		start_handler_names = [getattr(h, '__name__', str(h)) for h in start_handlers]

		if any('on_BrowserStartEvent' in name for name in start_handler_names):
			raise RuntimeError(
				'[BrowserSession] Duplicate handler registration attempted! '
				'on_BrowserStartEvent is already registered. '
				'This likely means BrowserSession was initialized multiple times with the same EventBus.'
			)

		BaseWatchdog.attach_handler_to_session(self, BrowserStartEvent, self.on_BrowserStartEvent)
		BaseWatchdog.attach_handler_to_session(self, BrowserStopEvent, self.on_BrowserStopEvent)
		BaseWatchdog.attach_handler_to_session(self, NavigateToUrlEvent, self.on_NavigateToUrlEvent)
		BaseWatchdog.attach_handler_to_session(self, SwitchTabEvent, self.on_SwitchTabEvent)
		BaseWatchdog.attach_handler_to_session(self, TabCreatedEvent, self.on_TabCreatedEvent)
		BaseWatchdog.attach_handler_to_session(self, TabClosedEvent, self.on_TabClosedEvent)
		BaseWatchdog.attach_handler_to_session(self, AgentFocusChangedEvent, self.on_AgentFocusChangedEvent)
		BaseWatchdog.attach_handler_to_session(self, FileDownloadedEvent, self.on_FileDownloadedEvent)
		BaseWatchdog.attach_handler_to_session(self, CloseTabEvent, self.on_CloseTabEvent)

	async def start(self) -> None:
		"""Start the browser session."""
		start_event = self.event_bus.dispatch(BrowserStartEvent())
		await start_event
		# Ensure any exceptions from the event handler are propagated
		await start_event.event_result(raise_if_any=True, raise_if_none=False)

	async def kill(self) -> None:
		"""Kill the browser session and reset all state."""
		# First save storage state while CDP is still connected
		from browser_use.browser.events import SaveStorageStateEvent

		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		# Dispatch stop event to kill the browser
		await self.event_bus.dispatch(BrowserStopEvent(force=True))
		# Stop the event bus
		await self.event_bus.stop(clear=True, timeout=5)
		# Reset all state
		await self.reset()
		# Create fresh event bus
		self.event_bus = EventBus()

	async def stop(self) -> None:
		"""Stop the browser session without killing the browser process.

		This clears event buses and cached state but keeps the browser alive.
		Useful when you want to clean up resources but plan to reconnect later.
		"""
		# First save storage state while CDP is still connected
		from browser_use.browser.events import SaveStorageStateEvent

		save_event = self.event_bus.dispatch(SaveStorageStateEvent())
		await save_event

		# Now dispatch BrowserStopEvent to notify watchdogs
		await self.event_bus.dispatch(BrowserStopEvent(force=False))

		# Stop the event bus
		await self.event_bus.stop(clear=True, timeout=5)
		# Reset all state
		await self.reset()
		# Create fresh event bus
		self.event_bus = EventBus()

	async def on_BrowserStartEvent(self, event: BrowserStartEvent) -> dict[str, str]:
		"""Handle browser start request.

		Returns:
			Dict with 'cdp_url' key containing the CDP URL
		"""

		# await self.reset()

		# Initialize and attach all watchdogs FIRST so LocalBrowserWatchdog can handle BrowserLaunchEvent
		await self.attach_all_watchdogs()

		try:
			# If no CDP URL, launch local browser
			if not self.cdp_url:
				if self.is_local:
					# Launch local browser using event-driven approach
					launch_event = self.event_bus.dispatch(BrowserLaunchEvent())
					await launch_event

					# Get the CDP URL from LocalBrowserWatchdog handler result
					launch_result: BrowserLaunchResult = cast(
						BrowserLaunchResult, await launch_event.event_result(raise_if_none=True, raise_if_any=True)
					)
					self.browser_profile.cdp_url = launch_result.cdp_url
				else:
					raise ValueError('Got BrowserSession(is_local=False) but no cdp_url was provided to connect to!')

			assert self.cdp_url and '://' in self.cdp_url

			# Only connect if not already connected
			if self._cdp_client_root is None:
				# Setup browser via CDP (for both local and remote cases)
				await self.connect(cdp_url=self.cdp_url)
				assert self.cdp_client is not None

				# Notify that browser is connected (single place)
				self.event_bus.dispatch(BrowserConnectedEvent(cdp_url=self.cdp_url))
			else:
				self.logger.debug('Already connected to CDP, skipping reconnection')

			# Return the CDP URL for other components
			return {'cdp_url': self.cdp_url}

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='BrowserStartEventError',
					message=f'Failed to start browser: {type(e).__name__} {e}',
					details={'cdp_url': self.cdp_url, 'is_local': self.is_local},
				)
			)
			raise

	async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
		"""Handle navigation requests - core browser functionality."""
		self.logger.debug(f'[on_NavigateToUrlEvent] Received NavigateToUrlEvent: url={event.url}, new_tab={event.new_tab}')
		if not self.agent_focus:
			self.logger.warning('Cannot navigate - browser not connected')
			return

		target_id = None

		# If new_tab=True but we're already in a new tab, set new_tab=False
		if event.new_tab:
			try:
				current_url = await self.get_current_page_url()
				from browser_use.utils import is_new_tab_page

				if is_new_tab_page(current_url):
					self.logger.debug(f'[on_NavigateToUrlEvent] Already in new tab ({current_url}), setting new_tab=False')
					event.new_tab = False
			except Exception as e:
				self.logger.debug(f'[on_NavigateToUrlEvent] Could not check current URL: {e}')

		# check if the url is already open in a tab somewhere that we're not currently on, if so, short-circuit and just switch to it
		targets = await self._cdp_get_all_pages()
		for target in targets:
			if target.get('url') == event.url and target['targetId'] != self.agent_focus.target_id and not event.new_tab:
				target_id = target['targetId']
				event.new_tab = False
				# await self.event_bus.dispatch(SwitchTabEvent(target_id=target_id))

		try:
			# Find or create target for navigation

			self.logger.debug(f'[on_NavigateToUrlEvent] Processing new_tab={event.new_tab}')
			if event.new_tab:
				# Look for existing about:blank tab that's not the current one
				targets = await self._cdp_get_all_pages()
				self.logger.debug(f'[on_NavigateToUrlEvent] Found {len(targets)} existing tabs')
				current_target_id = self.agent_focus.target_id if self.agent_focus else None
				self.logger.debug(f'[on_NavigateToUrlEvent] Current target_id: {current_target_id}')

				for idx, target in enumerate(targets):
					self.logger.debug(
						f'[on_NavigateToUrlEvent] Tab {idx}: url={target.get("url")}, targetId={target["targetId"]}'
					)
					if target.get('url') == 'about:blank' and target['targetId'] != current_target_id:
						target_id = target['targetId']
						self.logger.debug(f'Reusing existing about:blank tab #{target_id[-4:]}')
						break

				# Create new tab if no reusable one found
				if not target_id:
					self.logger.debug('[on_NavigateToUrlEvent] No reusable about:blank tab found, creating new tab...')
					try:
						target_id = await self._cdp_create_new_page('about:blank')
						self.logger.debug(f'[on_NavigateToUrlEvent] Created new page with target_id: {target_id}')
						targets = await self._cdp_get_all_pages()

						self.logger.debug(f'Created new tab #{target_id[-4:]}')
						# Dispatch TabCreatedEvent for new tab
						await self.event_bus.dispatch(TabCreatedEvent(target_id=target_id, url='about:blank'))
					except Exception as e:
						self.logger.error(f'[on_NavigateToUrlEvent] Failed to create new tab: {type(e).__name__}: {e}')
						# Fall back to using current tab
						target_id = self.agent_focus.target_id
						self.logger.warning(f'[on_NavigateToUrlEvent] Falling back to current tab #{target_id[-4:]}')
			else:
				# Use current tab
				target_id = target_id or self.agent_focus.target_id

			# Only switch tab if we're not already on the target tab
			if self.agent_focus is None or self.agent_focus.target_id != target_id:
				self.logger.debug(
					f'[on_NavigateToUrlEvent] Switching to target tab {target_id[-4:]} (current: {self.agent_focus.target_id[-4:] if self.agent_focus else "none"})'
				)
				# Activate target (bring to foreground)
				await self.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
				# which does this for us:
				# self.agent_focus = await self.get_or_create_cdp_session(target_id)
			else:
				self.logger.debug(f'[on_NavigateToUrlEvent] Already on target tab {target_id[-4:]}, skipping SwitchTabEvent')

			assert self.agent_focus is not None and self.agent_focus.target_id == target_id, (
				'Agent focus not updated to new target_id after SwitchTabEvent should have switched to it'
			)

			# Dispatch navigation started
			await self.event_bus.dispatch(NavigationStartedEvent(target_id=target_id, url=event.url))

			# Navigate to URL
			await self.agent_focus.cdp_client.send.Page.navigate(
				params={
					'url': event.url,
					'transitionType': 'address_bar',
					# 'referrer': 'https://www.google.com',
				},
				session_id=self.agent_focus.session_id,
			)

			# # Wait a bit to ensure page starts loading
			# await asyncio.sleep(0.5)

			# Close any extension options pages that might have opened
			await self._close_extension_options_pages()

			# Dispatch navigation complete
			self.logger.debug(f'Dispatching NavigationCompleteEvent for {event.url} (tab #{target_id[-4:]})')
			await self.event_bus.dispatch(
				NavigationCompleteEvent(
					target_id=target_id,
					url=event.url,
					status=None,  # CDP doesn't provide status directly
				)
			)
			await self.event_bus.dispatch(
				AgentFocusChangedEvent(target_id=target_id, url=event.url)
			)  # do not await! AgentFocusChangedEvent calls SwitchTabEvent and it will deadlock, dispatch to enqueue and return

			# Note: These should be handled by dedicated watchdogs:
			# - Security checks (security_watchdog)
			# - Page health checks (crash_watchdog)
			# - Dialog handling (dialog_watchdog)
			# - Download handling (downloads_watchdog)
			# - DOM rebuilding (dom_watchdog)

		except Exception as e:
			self.logger.error(f'Navigation failed: {type(e).__name__}: {e}')
			if target_id:
				await self.event_bus.dispatch(
					NavigationCompleteEvent(
						target_id=target_id,
						url=event.url,
						error_message=f'{type(e).__name__}: {e}',
					)
				)
				await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=event.url))
			raise

	async def on_SwitchTabEvent(self, event: SwitchTabEvent) -> TargetID:
		"""Handle tab switching - core browser functionality."""
		if not self.agent_focus:
			raise RuntimeError('Cannot switch tabs - browser not connected')

		all_pages = await self._cdp_get_all_pages()
		if event.target_id is None:
			# most recently opened page
			if all_pages:
				# update the target id to be the id of the most recently opened page, then proceed to switch to it
				event.target_id = all_pages[-1]['targetId']
			else:
				# no pages open at all, create a new one (handles switching to it automatically)
				assert self._cdp_client_root is not None, 'CDP client root not initialized - browser may not be connected yet'
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				# do not await! these may circularly trigger SwitchTabEvent and could deadlock, dispatch to enqueue and return
				self.event_bus.dispatch(TabCreatedEvent(url='about:blank', target_id=target_id))
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url='about:blank'))
				return target_id

		# switch to the target
		self.agent_focus = await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)

		# dispatch focus changed event
		await self.event_bus.dispatch(
			AgentFocusChangedEvent(
				target_id=self.agent_focus.target_id,
				url=self.agent_focus.url,
			)
		)
		return self.agent_focus.target_id

	async def on_CloseTabEvent(self, event: CloseTabEvent) -> None:
		"""Handle tab closure - update focus if needed."""

		cdp_session = await self.get_or_create_cdp_session(target_id=None, focus=False)
		await self.event_bus.dispatch(TabClosedEvent(target_id=event.target_id))
		await cdp_session.cdp_client.send.Target.closeTarget(params={'targetId': event.target_id})

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Handle tab creation - apply viewport settings to new tab."""
		# Apply viewport settings if configured
		if self.browser_profile.viewport and not self.browser_profile.no_viewport:
			try:
				viewport_width = self.browser_profile.viewport.width
				viewport_height = self.browser_profile.viewport.height
				device_scale_factor = self.browser_profile.device_scale_factor or 1.0

				# Use the helper method with the new tab's target_id
				await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=event.target_id)

				self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {event.target_id[-8:]}')
			except Exception as e:
				self.logger.warning(f'Failed to set viewport for new tab {event.target_id[-8:]}: {e}')

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		if not self.agent_focus:
			return

		# Get current tab index
		current_target_id = self.agent_focus.target_id

		# If the closed tab was the current one, find a new target
		if current_target_id == event.target_id:
			await self.event_bus.dispatch(SwitchTabEvent(target_id=None))

	async def on_AgentFocusChangedEvent(self, event: AgentFocusChangedEvent) -> None:
		"""Handle agent focus change - update focus and clear cache."""
		self.logger.debug(f'🔄 AgentFocusChangedEvent received: target_id=...{event.target_id[-4:]} url={event.url}')

		# Clear cached DOM state since focus changed
		# self.logger.debug('🔄 Clearing DOM cache...')
		if self._dom_watchdog:
			self._dom_watchdog.clear_cache()
			# self.logger.debug('🔄 Cleared DOM cache after focus change')

		# Clear cached browser state
		# self.logger.debug('🔄 Clearing cached browser state...')
		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self.logger.debug('🔄 Cached browser state cleared')
		all_targets = await self._cdp_get_all_pages(include_chrome=True)

		# Update agent focus if a specific target_id is provided
		if event.target_id:
			self.agent_focus = await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)
			self.logger.debug(f'🔄 Updated agent focus to tab target_id=...{event.target_id[-4:]}')
		else:
			raise RuntimeError('AgentFocusChangedEvent received with no target_id for newly focused tab')

		# Test that the browser is responsive by evaluating a simple expression
		if self.agent_focus:
			self.logger.debug('🔄 Testing tab responsiveness...')
			try:
				test_result = await asyncio.wait_for(
					self.agent_focus.cdp_client.send.Runtime.evaluate(
						params={'expression': '1 + 1', 'returnByValue': True}, session_id=self.agent_focus.session_id
					),
					timeout=2.0,
				)
				if test_result.get('result', {}).get('value') == 2:
					# self.logger.debug('🔄 ✅ Browser is responsive after focus change')
					pass
				else:
					raise Exception('❌ Failed to execute test JS expression with Page.evaluate')
			except Exception as e:
				self.logger.error(
					f'🔄 ❌ Target {self.agent_focus.target_id} seems closed/crashed, switching to fallback page {all_targets[0]}: {type(e).__name__}: {e}'
				)
				all_pages = await self._cdp_get_all_pages()
				last_target_id = all_pages[-1]['targetId'] if all_pages else None
				self.agent_focus = await self.get_or_create_cdp_session(target_id=last_target_id, focus=True)
				raise

		# self.logger.debug('🔄 AgentFocusChangedEvent handler completed successfully')

	async def on_FileDownloadedEvent(self, event: FileDownloadedEvent) -> None:
		"""Track downloaded files during this session."""
		self.logger.debug(f'FileDownloadedEvent received: {event.file_name} at {event.path}')
		if event.path and event.path not in self._downloaded_files:
			self._downloaded_files.append(event.path)
			self.logger.info(f'📁 Tracked download: {event.file_name} ({len(self._downloaded_files)} total downloads in session)')
		else:
			if not event.path:
				self.logger.warning(f'FileDownloadedEvent has no path: {event}')
			else:
				self.logger.debug(f'File already tracked: {event.path}')

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Handle browser stop request."""

		try:
			# Check if we should keep the browser alive
			if self.browser_profile.keep_alive and not event.force:
				self.event_bus.dispatch(BrowserStoppedEvent(reason='Kept alive due to keep_alive=True'))
				return

			# Clear CDP session cache before stopping
			await self.reset()

			# Reset state
			if self.is_local:
				self.browser_profile.cdp_url = None

			# Notify stop and wait for all handlers to complete
			# LocalBrowserWatchdog listens for BrowserStopEvent and dispatches BrowserKillEvent
			stop_event = self.event_bus.dispatch(BrowserStoppedEvent(reason='Stopped by request'))
			await stop_event

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='BrowserStopEventError',
					message=f'Failed to stop browser: {type(e).__name__} {e}',
					details={'cdp_url': self.cdp_url, 'is_local': self.is_local},
				)
			)

	@property
	def cdp_client(self) -> CDPClient:
		"""Get the cached root CDP cdp_session.cdp_client. The client is created and started in self.connect()."""
		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		return self._cdp_client_root

	async def get_or_create_cdp_session(
		self, target_id: TargetID | None = None, focus: bool = True, new_socket: bool | None = None
	) -> CDPSession:
		"""Get or create a CDP session for a target.

		Args:
				target_id: Target ID to get session for. If None, uses current agent focus.
				focus: If True, switches agent focus to this target. If False, just returns session without changing focus.
				new_socket: If True, create a dedicated WebSocket connection. If None (default), creates new socket for new targets only.

		Returns:
				CDPSession for the specified target.
		"""
		assert self.cdp_url is not None, 'CDP URL not set - browser may not be configured or launched yet'
		assert self._cdp_client_root is not None, 'Root CDP client not initialized - browser may not be connected yet'
		assert self.agent_focus is not None, 'CDP session not initialized - browser may not be connected yet'

		# If no target_id specified, use the current target_id
		if target_id is None:
			target_id = self.agent_focus.target_id

		# Check if we already have a session for this target in the pool
		if target_id in self._cdp_session_pool:
			session = self._cdp_session_pool[target_id]
			if focus and self.agent_focus.target_id != target_id:
				self.logger.debug(
					f'[get_or_create_cdp_session] Switching agent focus from {self.agent_focus.target_id} to {target_id}'
				)
				self.agent_focus = session
			if focus:
				await session.cdp_client.send.Target.activateTarget(params={'targetId': session.target_id})
				await session.cdp_client.send.Runtime.runIfWaitingForDebugger(session_id=session.session_id)
			# else:
			# self.logger.debug(f'[get_or_create_cdp_session] Reusing existing session for {target_id} (focus={focus})')
			return session

		# If it's the current focus target, return that session
		if self.agent_focus.target_id == target_id:
			self._cdp_session_pool[target_id] = self.agent_focus
			return self.agent_focus

		# Create new session for this target
		# Default to True for new sessions (each new target gets its own WebSocket)
		should_use_new_socket = True if new_socket is None else new_socket
		self.logger.debug(
			f'[get_or_create_cdp_session] Creating new CDP session for target {target_id} (new_socket={should_use_new_socket})'
		)
		session = await CDPSession.for_target(
			self._cdp_client_root,
			target_id,
			new_socket=should_use_new_socket,
			cdp_url=self.cdp_url if should_use_new_socket else None,
		)
		self._cdp_session_pool[target_id] = session
		# log length of _cdp_session_pool
		self.logger.debug(f'[get_or_create_cdp_session] new _cdp_session_pool length: {len(self._cdp_session_pool)}')

		# Only change agent focus if requested
		if focus:
			self.logger.debug(
				f'[get_or_create_cdp_session] Switching agent focus from {self.agent_focus.target_id} to {target_id}'
			)
			self.agent_focus = session
			await session.cdp_client.send.Target.activateTarget(params={'targetId': session.target_id})
			await session.cdp_client.send.Runtime.runIfWaitingForDebugger(session_id=session.session_id)
		else:
			self.logger.debug(
				f'[get_or_create_cdp_session] Created session for {target_id} without changing focus (still on {self.agent_focus.target_id})'
			)

		return session

	@property
	def current_target_id(self) -> str | None:
		return self.agent_focus.target_id if self.agent_focus else None

	@property
	def current_session_id(self) -> str | None:
		return self.agent_focus.session_id if self.agent_focus else None

	# ========== Helper Methods ==========
	@observe_debug(ignore_input=True, ignore_output=True, name='get_browser_state_summary')
	async def get_browser_state_summary(
		self,
		cache_clickable_elements_hashes: bool = True,
		include_screenshot: bool = True,
		cached: bool = False,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		if cached and self._cached_browser_state_summary is not None and self._cached_browser_state_summary.dom_state:
			# Don't use cached state if it has 0 interactive elements
			selector_map = self._cached_browser_state_summary.dom_state.selector_map

			# Don't use cached state if we need a screenshot but the cached state doesn't have one
			if include_screenshot and not self._cached_browser_state_summary.screenshot:
				self.logger.debug('⚠️ Cached browser state has no screenshot, fetching fresh state with screenshot')
				# Fall through to fetch fresh state with screenshot
			elif selector_map and len(selector_map) > 0:
				self.logger.debug('🔄 Using pre-cached browser state summary for open tab')
				return self._cached_browser_state_summary
			else:
				self.logger.debug('⚠️ Cached browser state has 0 interactive elements, fetching fresh state')
				# Fall through to fetch fresh state

		# Dispatch the event and wait for result
		event: BrowserStateRequestEvent = cast(
			BrowserStateRequestEvent,
			self.event_bus.dispatch(
				BrowserStateRequestEvent(
					include_dom=True,
					include_screenshot=include_screenshot,
					cache_clickable_elements_hashes=cache_clickable_elements_hashes,
					include_recent_events=include_recent_events,
				)
			),
		)

		# The handler returns the BrowserStateSummary directly
		result = await event.event_result(raise_if_none=True, raise_if_any=True)
		assert result is not None and result.dom_state is not None
		return result

	async def attach_all_watchdogs(self) -> None:
		"""Initialize and attach all watchdogs with explicit handler registration."""
		# Prevent duplicate watchdog attachment
		if hasattr(self, '_watchdogs_attached') and self._watchdogs_attached:
			self.logger.debug('Watchdogs already attached, skipping duplicate attachment')
			return

		from browser_use.browser.watchdogs.aboutblank_watchdog import AboutBlankWatchdog

		# from browser_use.browser.crash_watchdog import CrashWatchdog
		from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
		from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog
		from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog
		from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
		from browser_use.browser.watchdogs.permissions_watchdog import PermissionsWatchdog
		from browser_use.browser.watchdogs.popups_watchdog import PopupsWatchdog
		from browser_use.browser.watchdogs.recording_watchdog import RecordingWatchdog
		from browser_use.browser.watchdogs.screenshot_watchdog import ScreenshotWatchdog
		from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog
		from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog

		# Initialize CrashWatchdog
		# CrashWatchdog.model_rebuild()
		# self._crash_watchdog = CrashWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserConnectedEvent, self._crash_watchdog.on_BrowserConnectedEvent)
		# self.event_bus.on(BrowserStoppedEvent, self._crash_watchdog.on_BrowserStoppedEvent)
		# self._crash_watchdog.attach_to_session()

		# Initialize DownloadsWatchdog
		DownloadsWatchdog.model_rebuild()
		self._downloads_watchdog = DownloadsWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserLaunchEvent, self._downloads_watchdog.on_BrowserLaunchEvent)
		# self.event_bus.on(TabCreatedEvent, self._downloads_watchdog.on_TabCreatedEvent)
		# self.event_bus.on(TabClosedEvent, self._downloads_watchdog.on_TabClosedEvent)
		# self.event_bus.on(BrowserStoppedEvent, self._downloads_watchdog.on_BrowserStoppedEvent)
		# self.event_bus.on(NavigationCompleteEvent, self._downloads_watchdog.on_NavigationCompleteEvent)
		self._downloads_watchdog.attach_to_session()
		if self.browser_profile.auto_download_pdfs:
			self.logger.debug('📄 PDF auto-download enabled for this session')

		# Initialize StorageStateWatchdog conditionally
		# Enable when user provides either storage_state or user_data_dir (indicating they want persistence)
		should_enable_storage_state = (
			self.browser_profile.storage_state is not None or self.browser_profile.user_data_dir is not None
		)

		if should_enable_storage_state:
			StorageStateWatchdog.model_rebuild()
			self._storage_state_watchdog = StorageStateWatchdog(
				event_bus=self.event_bus,
				browser_session=self,
				# More conservative defaults when auto-enabled
				auto_save_interval=60.0,  # 1 minute instead of 30 seconds
				save_on_change=False,  # Only save on shutdown by default
			)
			self._storage_state_watchdog.attach_to_session()
			self.logger.debug(
				f'🍪 StorageStateWatchdog enabled (storage_state: {bool(self.browser_profile.storage_state)}, user_data_dir: {bool(self.browser_profile.user_data_dir)})'
			)
		else:
			self.logger.debug('🍪 StorageStateWatchdog disabled (no storage_state or user_data_dir configured)')

		# Initialize LocalBrowserWatchdog
		LocalBrowserWatchdog.model_rebuild()
		self._local_browser_watchdog = LocalBrowserWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserLaunchEvent, self._local_browser_watchdog.on_BrowserLaunchEvent)
		# self.event_bus.on(BrowserKillEvent, self._local_browser_watchdog.on_BrowserKillEvent)
		# self.event_bus.on(BrowserStopEvent, self._local_browser_watchdog.on_BrowserStopEvent)
		self._local_browser_watchdog.attach_to_session()

		# Initialize SecurityWatchdog (hooks NavigationWatchdog and implements allowed_domains restriction)
		SecurityWatchdog.model_rebuild()
		self._security_watchdog = SecurityWatchdog(event_bus=self.event_bus, browser_session=self)
		# Core navigation is now handled in BrowserSession directly
		# SecurityWatchdog only handles security policy enforcement
		self._security_watchdog.attach_to_session()

		# Initialize AboutBlankWatchdog (handles about:blank pages and DVD loading animation on first load)
		AboutBlankWatchdog.model_rebuild()
		self._aboutblank_watchdog = AboutBlankWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserStopEvent, self._aboutblank_watchdog.on_BrowserStopEvent)
		# self.event_bus.on(BrowserStoppedEvent, self._aboutblank_watchdog.on_BrowserStoppedEvent)
		# self.event_bus.on(TabCreatedEvent, self._aboutblank_watchdog.on_TabCreatedEvent)
		# self.event_bus.on(TabClosedEvent, self._aboutblank_watchdog.on_TabClosedEvent)
		self._aboutblank_watchdog.attach_to_session()

		# Initialize PopupsWatchdog (handles accepting and dismissing JS dialogs, alerts, confirm, onbeforeunload, etc.)
		PopupsWatchdog.model_rebuild()
		self._popups_watchdog = PopupsWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(TabCreatedEvent, self._popups_watchdog.on_TabCreatedEvent)
		# self.event_bus.on(DialogCloseEvent, self._popups_watchdog.on_DialogCloseEvent)
		self._popups_watchdog.attach_to_session()

		# Initialize PermissionsWatchdog (handles granting and revoking browser permissions like clipboard, microphone, camera, etc.)
		PermissionsWatchdog.model_rebuild()
		self._permissions_watchdog = PermissionsWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserConnectedEvent, self._permissions_watchdog.on_BrowserConnectedEvent)
		self._permissions_watchdog.attach_to_session()

		# Initialize DefaultActionWatchdog (handles all default actions like click, type, scroll, go back, go forward, refresh, wait, send keys, upload file, scroll to text, etc.)
		DefaultActionWatchdog.model_rebuild()
		self._default_action_watchdog = DefaultActionWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(ClickElementEvent, self._default_action_watchdog.on_ClickElementEvent)
		# self.event_bus.on(TypeTextEvent, self._default_action_watchdog.on_TypeTextEvent)
		# self.event_bus.on(ScrollEvent, self._default_action_watchdog.on_ScrollEvent)
		# self.event_bus.on(GoBackEvent, self._default_action_watchdog.on_GoBackEvent)
		# self.event_bus.on(GoForwardEvent, self._default_action_watchdog.on_GoForwardEvent)
		# self.event_bus.on(RefreshEvent, self._default_action_watchdog.on_RefreshEvent)
		# self.event_bus.on(WaitEvent, self._default_action_watchdog.on_WaitEvent)
		# self.event_bus.on(SendKeysEvent, self._default_action_watchdog.on_SendKeysEvent)
		# self.event_bus.on(UploadFileEvent, self._default_action_watchdog.on_UploadFileEvent)
		# self.event_bus.on(ScrollToTextEvent, self._default_action_watchdog.on_ScrollToTextEvent)
		self._default_action_watchdog.attach_to_session()

		# Initialize ScreenshotWatchdog (handles taking screenshots of the browser)
		ScreenshotWatchdog.model_rebuild()
		self._screenshot_watchdog = ScreenshotWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(BrowserStartEvent, self._screenshot_watchdog.on_BrowserStartEvent)
		# self.event_bus.on(BrowserStoppedEvent, self._screenshot_watchdog.on_BrowserStoppedEvent)
		# self.event_bus.on(ScreenshotEvent, self._screenshot_watchdog.on_ScreenshotEvent)
		self._screenshot_watchdog.attach_to_session()

		# Initialize DOMWatchdog (handles building the DOM tree and detecting interactive elements, depends on ScreenshotWatchdog)
		DOMWatchdog.model_rebuild()
		self._dom_watchdog = DOMWatchdog(event_bus=self.event_bus, browser_session=self)
		# self.event_bus.on(TabCreatedEvent, self._dom_watchdog.on_TabCreatedEvent)
		# self.event_bus.on(BrowserStateRequestEvent, self._dom_watchdog.on_BrowserStateRequestEvent)
		self._dom_watchdog.attach_to_session()

		# Initialize RecordingWatchdog (handles video recording)
		RecordingWatchdog.model_rebuild()
		self._recording_watchdog = RecordingWatchdog(event_bus=self.event_bus, browser_session=self)
		self._recording_watchdog.attach_to_session()

		# Mark watchdogs as attached to prevent duplicate attachment
		self._watchdogs_attached = True

	async def connect(self, cdp_url: str | None = None) -> Self:
		"""Connect to a remote chromium-based browser via CDP using cdp-use.

		This MUST succeed or the browser is unusable. Fails hard on any error.
		"""

		self.browser_profile.cdp_url = cdp_url or self.cdp_url
		if not self.cdp_url:
			raise RuntimeError('Cannot setup CDP connection without CDP URL')

		if not self.cdp_url.startswith('ws'):
			# If it's an HTTP URL, fetch the WebSocket URL from /json/version endpoint
			url = self.cdp_url.rstrip('/')
			if not url.endswith('/json/version'):
				url = url + '/json/version'

			# Run a tiny HTTP client to query for the WebSocket URL from the /json/version endpoint
			async with httpx.AsyncClient() as client:
				headers = self.browser_profile.headers or {}
				version_info = await client.get(url, headers=headers)
				self.browser_profile.cdp_url = version_info.json()['webSocketDebuggerUrl']

		assert self.cdp_url is not None

		browser_location = 'local browser' if self.is_local else 'remote browser'
		self.logger.debug(f'🌎 Connecting to existing chromium-based browser via CDP: {self.cdp_url} -> ({browser_location})')

		try:
			# Import cdp-use client

			# Convert HTTP URL to WebSocket URL if needed

			# Create and store the CDP client for direct CDP communication
			self._cdp_client_root = CDPClient(self.cdp_url)
			assert self._cdp_client_root is not None
			await self._cdp_client_root.start()
			await self._cdp_client_root.send.Target.setAutoAttach(
				params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}
			)
			self.logger.debug('CDP client connected successfully')

			# Get browser targets to find available contexts/pages
			targets = await self._cdp_client_root.send.Target.getTargets()

			# Find main browser pages (avoiding iframes, workers, extensions, etc.)
			page_targets: list[TargetInfo] = [
				t
				for t in targets['targetInfos']
				if self._is_valid_target(
					t, include_http=True, include_about=True, include_pages=True, include_iframes=False, include_workers=False
				)
			]

			# Check for chrome://newtab pages and immediately redirect them
			# to about:blank to avoid JS issues from CDP on chrome://* urls
			from browser_use.utils import is_new_tab_page

			# Collect all targets that need redirection
			redirected_targets = []
			redirect_sessions = {}  # Store sessions created for redirection to potentially reuse
			for target in page_targets:
				target_url = target.get('url', '')
				if is_new_tab_page(target_url) and target_url != 'about:blank':
					# Redirect chrome://newtab to about:blank to avoid JS issues preventing driving chrome://newtab
					target_id = target['targetId']
					self.logger.debug(f'🔄 Redirecting {target_url} to about:blank for target {target_id}')
					try:
						# Create a CDP session for redirection (minimal domains to avoid duplicate event handlers)
						# Only enable Page domain for navigation, avoid duplicate event handlers
						redirect_session = await CDPSession.for_target(self._cdp_client_root, target_id, domains=['Page'])
						# Navigate to about:blank
						await redirect_session.cdp_client.send.Page.navigate(
							params={'url': 'about:blank'}, session_id=redirect_session.session_id
						)
						redirected_targets.append(target_id)
						redirect_sessions[target_id] = redirect_session  # Store for potential reuse
						# Update the target's URL in our list for later use
						target['url'] = 'about:blank'
						# Small delay to ensure navigation completes
						await asyncio.sleep(0.05)
					except Exception as e:
						self.logger.warning(f'Failed to redirect {target_url} to about:blank: {e}')

			# Log summary of redirections
			if redirected_targets:
				self.logger.debug(f'Redirected {len(redirected_targets)} chrome://newtab pages to about:blank')

			if not page_targets:
				# No pages found, create a new one
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				self.logger.debug(f'📄 Created new blank page with target ID: {target_id}')
			else:
				# Use the first available page
				target_id = [page for page in page_targets if page.get('type') == 'page'][0]['targetId']
				self.logger.debug(f'📄 Using existing page with target ID: {target_id}')

			# Store the current page target ID and add to pool
			# Reuse redirect session if available, otherwise create new one
			if target_id in redirect_sessions:
				self.logger.debug(f'Reusing redirect session for target {target_id}')
				self.agent_focus = redirect_sessions[target_id]
			else:
				# For the initial connection, we'll use the shared root WebSocket
				self.agent_focus = await CDPSession.for_target(self._cdp_client_root, target_id, new_socket=False)
			if self.agent_focus:
				self._cdp_session_pool[target_id] = self.agent_focus

			# Enable proxy authentication handling if configured
			await self._setup_proxy_auth()

			# Verify the session is working
			try:
				if self.agent_focus:
					assert self.agent_focus.title != 'Unknown title'
				else:
					raise RuntimeError('Failed to create CDP session')
			except Exception as e:
				self.logger.warning(f'Failed to create CDP session: {e}')
				raise

			# Dispatch TabCreatedEvent for all initial tabs (so watchdogs can initialize)
			# This replaces the duplicated logic from navigation_watchdog's _initialize_agent_focus
			for idx, target in enumerate(page_targets):
				target_url = target.get('url', '')
				self.logger.debug(f'Dispatching TabCreatedEvent for initial tab {idx}: {target_url}')
				self.event_bus.dispatch(TabCreatedEvent(url=target_url, target_id=target['targetId']))

			# Dispatch initial focus event
			if page_targets:
				initial_url = page_targets[0].get('url', '')
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=page_targets[0]['targetId'], url=initial_url))
				self.logger.debug(f'Initial agent focus set to tab 0: {initial_url}')

		except Exception as e:
			# Fatal error - browser is not usable without CDP connection
			self.logger.error(f'❌ FATAL: Failed to setup CDP connection: {e}')
			self.logger.error('❌ Browser cannot continue without CDP connection')
			# Clean up any partial state
			self._cdp_client_root = None
			self.agent_focus = None
			# Re-raise as a fatal error
			raise RuntimeError(f'Failed to establish CDP connection to browser: {e}') from e

		return self

	async def _setup_proxy_auth(self) -> None:
		"""Enable CDP Fetch auth handling for authenticated proxy, if credentials provided.

		Handles HTTP proxy authentication challenges (Basic/Proxy) by providing
		configured credentials from BrowserProfile.
		"""

		assert self._cdp_client_root

		try:
			proxy_cfg = self.browser_profile.proxy
			username = proxy_cfg.username if proxy_cfg else None
			password = proxy_cfg.password if proxy_cfg else None
			if not username or not password:
				self.logger.debug('Proxy credentials not provided; skipping proxy auth setup')
				return

			# Enable Fetch domain with auth handling (do not pause all requests)
			try:
				await self._cdp_client_root.send.Fetch.enable(params={'handleAuthRequests': True})
				self.logger.debug('Fetch.enable(handleAuthRequests=True) enabled on root client')
			except Exception as e:
				self.logger.debug(f'Fetch.enable on root failed: {type(e).__name__}: {e}')

			# Also enable on the focused session if available to ensure events are delivered
			try:
				if self.agent_focus:
					await self.agent_focus.cdp_client.send.Fetch.enable(
						params={'handleAuthRequests': True},
						session_id=self.agent_focus.session_id,
					)
					self.logger.debug('Fetch.enable(handleAuthRequests=True) enabled on focused session')
			except Exception as e:
				self.logger.debug(f'Fetch.enable on focused session failed: {type(e).__name__}: {e}')

			def _on_auth_required(event: AuthRequiredEvent, session_id: SessionID | None = None):
				# event keys may be snake_case or camelCase depending on generator; handle both
				request_id = event.get('requestId') or event.get('request_id')
				if not request_id:
					return

				challenge = event.get('authChallenge') or event.get('auth_challenge') or {}
				source = (challenge.get('source') or '').lower()
				# Only respond to proxy challenges
				if source == 'proxy' and request_id:

					async def _respond():
						assert self._cdp_client_root
						try:
							await self._cdp_client_root.send.Fetch.continueWithAuth(
								params={
									'requestId': request_id,
									'authChallengeResponse': {
										'response': 'ProvideCredentials',
										'username': username,
										'password': password,
									},
								},
								session_id=session_id,
							)
						except Exception as e:
							self.logger.debug(f'Proxy auth respond failed: {type(e).__name__}: {e}')

					# schedule
					asyncio.create_task(_respond())
				else:
					# Default behaviour for non-proxy challenges: let browser handle
					async def _default():
						assert self._cdp_client_root
						try:
							await self._cdp_client_root.send.Fetch.continueWithAuth(
								params={'requestId': request_id, 'authChallengeResponse': {'response': 'Default'}},
								session_id=session_id,
							)
						except Exception as e:
							self.logger.debug(f'Default auth respond failed: {type(e).__name__}: {e}')

					if request_id:
						asyncio.create_task(_default())

			def _on_request_paused(event: RequestPausedEvent, session_id: SessionID | None = None):
				# Continue all paused requests to avoid stalling the network
				request_id = event.get('requestId') or event.get('request_id')
				if not request_id:
					return

				async def _continue():
					assert self._cdp_client_root
					try:
						await self._cdp_client_root.send.Fetch.continueRequest(
							params={'requestId': request_id},
							session_id=session_id,
						)
					except Exception:
						pass

				asyncio.create_task(_continue())

			# Register event handler on root client
			try:
				self._cdp_client_root.register.Fetch.authRequired(_on_auth_required)
				self._cdp_client_root.register.Fetch.requestPaused(_on_request_paused)
				if self.agent_focus:
					self.agent_focus.cdp_client.register.Fetch.authRequired(_on_auth_required)
					self.agent_focus.cdp_client.register.Fetch.requestPaused(_on_request_paused)
				self.logger.debug('Registered Fetch.authRequired handlers')
			except Exception as e:
				self.logger.debug(f'Failed to register authRequired handlers: {type(e).__name__}: {e}')

			# Auto-enable Fetch on every newly attached target to ensure auth callbacks fire
			def _on_attached(event: AttachedToTargetEvent, session_id: SessionID | None = None):
				sid = event.get('sessionId') or event.get('session_id') or session_id
				if not sid:
					return

				async def _enable():
					assert self._cdp_client_root
					try:
						await self._cdp_client_root.send.Fetch.enable(
							params={'handleAuthRequests': True},
							session_id=sid,
						)
						self.logger.debug(f'Fetch.enable(handleAuthRequests=True) enabled on attached session {sid}')
					except Exception as e:
						self.logger.debug(f'Fetch.enable on attached session failed: {type(e).__name__}: {e}')

				asyncio.create_task(_enable())

			try:
				self._cdp_client_root.register.Target.attachedToTarget(_on_attached)
				self.logger.debug('Registered Target.attachedToTarget handler for Fetch.enable')
			except Exception as e:
				self.logger.debug(f'Failed to register attachedToTarget handler: {type(e).__name__}: {e}')

			# Ensure Fetch is enabled for the current focused session, too
			try:
				if self.agent_focus:
					await self.agent_focus.cdp_client.send.Fetch.enable(
						params={'handleAuthRequests': True, 'patterns': [{'urlPattern': '*'}]},
						session_id=self.agent_focus.session_id,
					)
			except Exception as e:
				self.logger.debug(f'Fetch.enable on focused session failed: {type(e).__name__}: {e}')
		except Exception as e:
			self.logger.debug(f'Skipping proxy auth setup: {type(e).__name__}: {e}')

	async def get_tabs(self) -> list[TabInfo]:
		"""Get information about all open tabs using CDP Target.getTargetInfo for speed."""
		tabs = []

		# Safety check - return empty list if browser not connected yet
		if not self._cdp_client_root:
			return tabs

		# Get all page targets using CDP
		pages = await self._cdp_get_all_pages()

		for i, page_target in enumerate(pages):
			target_id = page_target['targetId']
			url = page_target['url']

			# Try to get the title directly from Target.getTargetInfo - much faster!
			# The initial getTargets() doesn't include title, but getTargetInfo does
			try:
				target_info = await self.cdp_client.send.Target.getTargetInfo(params={'targetId': target_id})
				# The title is directly available in targetInfo
				title = target_info.get('targetInfo', {}).get('title', '')

				# Skip JS execution for chrome:// pages and new tab pages
				if is_new_tab_page(url) or url.startswith('chrome://'):
					# Use URL as title for chrome pages, or mark new tabs as unusable
					if is_new_tab_page(url):
						title = 'ignore this tab and do not use it'
					elif not title:
						# For chrome:// pages without a title, use the URL itself
						title = url

				# Special handling for PDF pages without titles
				if (not title or title == '') and (url.endswith('.pdf') or 'pdf' in url):
					# PDF pages might not have a title, use URL filename
					try:
						from urllib.parse import urlparse

						filename = urlparse(url).path.split('/')[-1]
						if filename:
							title = filename
					except Exception:
						pass

			except Exception as e:
				# Fallback to basic title handling
				self.logger.debug(f'⚠️ Failed to get target info for tab #{i}: {_log_pretty_url(url)} - {type(e).__name__}')

				if is_new_tab_page(url):
					title = 'ignore this tab and do not use it'
				elif url.startswith('chrome://'):
					title = url
				else:
					title = ''

			tab_info = TabInfo(
				target_id=target_id,
				url=url,
				title=title,
				parent_target_id=None,
			)
			tabs.append(tab_info)

		return tabs

	# ========== ID Lookup Methods ==========

	async def get_current_target_info(self) -> TargetInfo | None:
		"""Get info about the current active target using CDP."""
		if not self.agent_focus or not self.agent_focus.target_id:
			return None

		targets = await self.cdp_client.send.Target.getTargets()
		for target in targets.get('targetInfos', []):
			if target.get('targetId') == self.agent_focus.target_id:
				# Still return even if it's not a "valid" target since we're looking for a specific ID
				return target
		return None

	async def get_current_page_url(self) -> str:
		"""Get the URL of the current page using CDP."""
		target = await self.get_current_target_info()
		if target:
			return target.get('url', '')
		return 'about:blank'

	async def get_current_page_title(self) -> str:
		"""Get the title of the current page using CDP."""
		target_info = await self.get_current_target_info()
		if target_info:
			return target_info.get('title', 'Unknown page title')
		return 'Unknown page title'

	async def navigate_to(self, url: str, new_tab: bool = False) -> None:
		"""Navigate to a URL using the standard event system.

		Args:
			url: URL to navigate to
			new_tab: Whether to open in a new tab
		"""
		from browser_use.browser.events import NavigateToUrlEvent

		event = self.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=new_tab))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	# ========== DOM Helper Methods ==========

	async def get_dom_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element by index.

		Get element from cached selector map.

		Args:
			index: The element index from the serialized DOM

		Returns:
			EnhancedDOMTreeNode or None if index not found
		"""
		#  Check cached selector map
		if self._cached_selector_map and index in self._cached_selector_map:
			return self._cached_selector_map[index]

		return None

	def update_cached_selector_map(self, selector_map: dict[int, EnhancedDOMTreeNode]) -> None:
		"""Update the cached selector map with new DOM state.

		This should be called by the DOM watchdog after rebuilding the DOM.

		Args:
			selector_map: The new selector map from DOM serialization
		"""
		self._cached_selector_map = selector_map

	# Alias for backwards compatibility
	async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		"""Alias for get_dom_element_by_index for backwards compatibility."""
		return await self.get_dom_element_by_index(index)

	async def get_target_id_from_tab_id(self, tab_id: str) -> TargetID:
		"""Get the full-length TargetID from the truncated 4-char tab_id."""
		for full_target_id in self._cdp_session_pool.keys():
			if full_target_id.endswith(tab_id):
				return full_target_id

		# may not have a cached session, so we need to get all pages and find the target id
		all_targets = await self.cdp_client.send.Target.getTargets()
		# Filter for valid page/tab targets only
		for target in all_targets.get('targetInfos', []):
			if target['targetId'].endswith(tab_id):
				return target['targetId']

		raise ValueError(f'No TargetID found ending in tab_id=...{tab_id}')

	async def get_target_id_from_url(self, url: str) -> TargetID:
		"""Get the TargetID from a URL."""
		all_targets = await self.cdp_client.send.Target.getTargets()
		for target in all_targets.get('targetInfos', []):
			if target['url'] == url and target['type'] == 'page':
				return target['targetId']

		# still not found, try substring match as fallback
		for target in all_targets.get('targetInfos', []):
			if url in target['url'] and target['type'] == 'page':
				return target['targetId']

		raise ValueError(f'No TargetID found for url={url}')

	async def get_most_recently_opened_target_id(self) -> TargetID:
		"""Get the most recently opened target ID."""
		all_targets = await self.cdp_client.send.Target.getTargets()
		return (await self._cdp_get_all_pages())[-1]['targetId']

	def is_file_input(self, element: Any) -> bool:
		"""Check if element is a file input.

		Args:
			element: The DOM element to check

		Returns:
			True if element is a file input, False otherwise
		"""
		if self._dom_watchdog:
			return self._dom_watchdog.is_file_input(element)
		# Fallback if watchdog not available
		return (
			hasattr(element, 'node_name')
			and element.node_name.upper() == 'INPUT'
			and hasattr(element, 'attributes')
			and element.attributes.get('type', '').lower() == 'file'
		)

	async def get_selector_map(self) -> dict[int, EnhancedDOMTreeNode]:
		"""Get the current selector map from cached state or DOM watchdog.

		Returns:
			Dictionary mapping element indices to EnhancedDOMTreeNode objects
		"""
		# First try cached selector map
		if self._cached_selector_map:
			return self._cached_selector_map

		# Try to get from DOM watchdog
		if self._dom_watchdog and hasattr(self._dom_watchdog, 'selector_map'):
			return self._dom_watchdog.selector_map or {}

		# Return empty dict if nothing available
		return {}

	async def remove_highlights(self) -> None:
		"""Remove highlights from the page using CDP."""
		if not self.browser_profile.highlight_elements:
			return

		try:
			# Get cached session
			cdp_session = await self.get_or_create_cdp_session()

			# Remove highlights via JavaScript - be thorough
			script = """
			(function() {
				// Remove all browser-use highlight elements
				const highlights = document.querySelectorAll('[data-browser-use-highlight]');
				console.log('Removing', highlights.length, 'browser-use highlight elements');
				highlights.forEach(el => el.remove());
				
				// Also remove by ID in case selector missed anything
				const highlightContainer = document.getElementById('browser-use-debug-highlights');
				if (highlightContainer) {
					console.log('Removing highlight container by ID');
					highlightContainer.remove();
				}
				
				// Final cleanup - remove any orphaned tooltips
				const orphanedTooltips = document.querySelectorAll('[data-browser-use-highlight="tooltip"]');
				orphanedTooltips.forEach(el => el.remove());
				
				return { removed: highlights.length };
			})();
			"""
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

			# Log the result for debugging
			if result and 'result' in result and 'value' in result['result']:
				removed_count = result['result']['value'].get('removed', 0)
				self.logger.debug(f'Successfully removed {removed_count} highlight elements')
			else:
				self.logger.debug('Highlight removal completed')

		except Exception as e:
			self.logger.warning(f'Failed to remove highlights: {e}')

	async def _close_extension_options_pages(self) -> None:
		"""Close any extension options/welcome pages that have opened."""
		try:
			# Get all open pages
			targets = await self._cdp_get_all_pages()

			for target in targets:
				target_url = target.get('url', '')
				target_id = target.get('targetId', '')

				# Check if this is an extension options/welcome page
				if 'chrome-extension://' in target_url and (
					'options.html' in target_url or 'welcome.html' in target_url or 'onboarding.html' in target_url
				):
					self.logger.info(f'[BrowserSession] 🚫 Closing extension options page: {target_url}')
					try:
						await self._cdp_close_page(target_id)
					except Exception as e:
						self.logger.debug(f'[BrowserSession] Could not close extension page {target_id}: {e}')

		except Exception as e:
			self.logger.debug(f'[BrowserSession] Error closing extension options pages: {e}')

	@property
	def downloaded_files(self) -> list[str]:
		"""Get list of files downloaded during this browser session.

		Returns:
			list[str]: List of absolute file paths to downloaded files in this session
		"""
		return self._downloaded_files.copy()

	# ========== CDP-based replacements for browser_context operations ==========

	async def _cdp_get_all_pages(
		self,
		include_http: bool = True,
		include_about: bool = True,
		include_pages: bool = True,
		include_iframes: bool = False,
		include_workers: bool = False,
		include_chrome: bool = False,
		include_chrome_extensions: bool = False,
		include_chrome_error: bool = False,
	) -> list[TargetInfo]:
		"""Get all browser pages/tabs using CDP Target.getTargets."""
		# Safety check - return empty list if browser not connected yet
		if not self._cdp_client_root:
			return []
		targets = await self.cdp_client.send.Target.getTargets()
		# Filter for valid page/tab targets only
		return [
			t
			for t in targets.get('targetInfos', [])
			if self._is_valid_target(
				t,
				include_http=include_http,
				include_about=include_about,
				include_pages=include_pages,
				include_iframes=include_iframes,
				include_workers=include_workers,
				include_chrome=include_chrome,
				include_chrome_extensions=include_chrome_extensions,
				include_chrome_error=include_chrome_error,
			)
		]

	async def _cdp_create_new_page(self, url: str = 'about:blank', background: bool = False, new_window: bool = False) -> str:
		"""Create a new page/tab using CDP Target.createTarget. Returns target ID."""
		# Use the root CDP client to create tabs at the browser level
		if self._cdp_client_root:
			result = await self._cdp_client_root.send.Target.createTarget(
				params={'url': url, 'newWindow': new_window, 'background': background}
			)
		else:
			# Fallback to using cdp_client if root is not available
			result = await self.cdp_client.send.Target.createTarget(
				params={'url': url, 'newWindow': new_window, 'background': background}
			)
		return result['targetId']

	async def _cdp_close_page(self, target_id: TargetID) -> None:
		"""Close a page/tab using CDP Target.closeTarget."""
		await self.cdp_client.send.Target.closeTarget(params={'targetId': target_id})

	async def _cdp_get_cookies(self) -> list[Cookie]:
		"""Get cookies using CDP Network.getCookies."""
		cdp_session = await self.get_or_create_cdp_session(target_id=None, new_socket=False)
		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Storage.getCookies(session_id=cdp_session.session_id), timeout=8.0
		)
		return result.get('cookies', [])

	async def _cdp_set_cookies(self, cookies: list[Cookie]) -> None:
		"""Set cookies using CDP Storage.setCookies."""
		if not self.agent_focus or not cookies:
			return

		cdp_session = await self.get_or_create_cdp_session(target_id=None, new_socket=False)
		# Storage.setCookies expects params dict with 'cookies' key
		await cdp_session.cdp_client.send.Storage.setCookies(
			params={'cookies': cookies},  # type: ignore[arg-type]
			session_id=cdp_session.session_id,
		)

	async def _cdp_clear_cookies(self) -> None:
		"""Clear all cookies using CDP Network.clearBrowserCookies."""
		cdp_session = await self.get_or_create_cdp_session()
		await cdp_session.cdp_client.send.Storage.clearCookies(session_id=cdp_session.session_id)

	async def _cdp_set_extra_headers(self, headers: dict[str, str]) -> None:
		"""Set extra HTTP headers using CDP Network.setExtraHTTPHeaders."""
		if not self.agent_focus:
			return

		cdp_session = await self.get_or_create_cdp_session()
		# await cdp_session.cdp_client.send.Network.setExtraHTTPHeaders(params={'headers': headers}, session_id=cdp_session.session_id)
		raise NotImplementedError('Not implemented yet')

	async def _cdp_grant_permissions(self, permissions: list[str], origin: str | None = None) -> None:
		"""Grant permissions using CDP Browser.grantPermissions."""
		params = {'permissions': permissions}
		# if origin:
		# 	params['origin'] = origin
		cdp_session = await self.get_or_create_cdp_session()
		# await cdp_session.cdp_client.send.Browser.grantPermissions(params=params, session_id=cdp_session.session_id)
		raise NotImplementedError('Not implemented yet')

	async def _cdp_set_geolocation(self, latitude: float, longitude: float, accuracy: float = 100) -> None:
		"""Set geolocation using CDP Emulation.setGeolocationOverride."""
		await self.cdp_client.send.Emulation.setGeolocationOverride(
			params={'latitude': latitude, 'longitude': longitude, 'accuracy': accuracy}
		)

	async def _cdp_clear_geolocation(self) -> None:
		"""Clear geolocation override using CDP."""
		await self.cdp_client.send.Emulation.clearGeolocationOverride()

	async def _cdp_add_init_script(self, script: str) -> str:
		"""Add script to evaluate on new document using CDP Page.addScriptToEvaluateOnNewDocument."""
		assert self._cdp_client_root is not None
		cdp_session = await self.get_or_create_cdp_session()

		result = await cdp_session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
			params={'source': script, 'runImmediately': True}, session_id=cdp_session.session_id
		)
		return result['identifier']

	async def _cdp_remove_init_script(self, identifier: str) -> None:
		"""Remove script added with addScriptToEvaluateOnNewDocument."""
		cdp_session = await self.get_or_create_cdp_session(target_id=None)
		await cdp_session.cdp_client.send.Page.removeScriptToEvaluateOnNewDocument(
			params={'identifier': identifier}, session_id=cdp_session.session_id
		)

	async def _cdp_set_viewport(
		self, width: int, height: int, device_scale_factor: float = 1.0, mobile: bool = False, target_id: str | None = None
	) -> None:
		"""Set viewport using CDP Emulation.setDeviceMetricsOverride.

		Args:
			width: Viewport width
			height: Viewport height
			device_scale_factor: Device scale factor (default 1.0)
			mobile: Whether to emulate mobile device (default False)
			target_id: Optional target ID to set viewport for. If not provided, uses agent_focus.
		"""
		if target_id:
			# Set viewport for specific target
			cdp_session = await self.get_or_create_cdp_session(target_id, focus=False, new_socket=False)
		elif self.agent_focus:
			# Use current focus
			cdp_session = self.agent_focus
		else:
			self.logger.warning('Cannot set viewport: no target_id provided and agent_focus not initialized')
			return

		await cdp_session.cdp_client.send.Emulation.setDeviceMetricsOverride(
			params={'width': width, 'height': height, 'deviceScaleFactor': device_scale_factor, 'mobile': mobile},
			session_id=cdp_session.session_id,
		)

	async def _cdp_get_origins(self) -> list[dict[str, Any]]:
		"""Get origins with localStorage and sessionStorage using CDP."""
		origins = []
		cdp_session = await self.get_or_create_cdp_session(target_id=None, new_socket=False)

		try:
			# Enable DOMStorage domain to track storage
			await cdp_session.cdp_client.send.DOMStorage.enable(session_id=cdp_session.session_id)

			try:
				# Get all frames to find unique origins
				frames_result = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)

				# Extract unique origins from frames
				unique_origins = set()

				def _extract_origins(frame_tree):
					"""Recursively extract origins from frame tree."""
					frame = frame_tree.get('frame', {})
					origin = frame.get('securityOrigin')
					if origin and origin != 'null':
						unique_origins.add(origin)

					# Process child frames
					for child in frame_tree.get('childFrames', []):
						_extract_origins(child)

				async def _get_storage_items(origin: str, is_local_storage: bool) -> list[dict[str, str]] | None:
					"""Helper to get storage items for an origin."""
					storage_type = 'localStorage' if is_local_storage else 'sessionStorage'
					try:
						result = await cdp_session.cdp_client.send.DOMStorage.getDOMStorageItems(
							params={'storageId': {'securityOrigin': origin, 'isLocalStorage': is_local_storage}},
							session_id=cdp_session.session_id,
						)

						items = []
						for item in result.get('entries', []):
							if len(item) == 2:  # Each item is [key, value]
								items.append({'name': item[0], 'value': item[1]})

						return items if items else None
					except Exception as e:
						self.logger.debug(f'Failed to get {storage_type} for {origin}: {e}')
						return None

				_extract_origins(frames_result.get('frameTree', {}))

				# For each unique origin, get localStorage and sessionStorage
				for origin in unique_origins:
					origin_data = {'origin': origin}

					# Get localStorage
					local_storage = await _get_storage_items(origin, is_local_storage=True)
					if local_storage:
						origin_data['localStorage'] = local_storage

					# Get sessionStorage
					session_storage = await _get_storage_items(origin, is_local_storage=False)
					if session_storage:
						origin_data['sessionStorage'] = session_storage

					# Only add origin if it has storage data
					if 'localStorage' in origin_data or 'sessionStorage' in origin_data:
						origins.append(origin_data)

			finally:
				# Always disable DOMStorage tracking when done
				await cdp_session.cdp_client.send.DOMStorage.disable(session_id=cdp_session.session_id)

		except Exception as e:
			self.logger.warning(f'Failed to get origins: {e}')

		return origins

	async def _cdp_get_storage_state(self) -> dict:
		"""Get storage state (cookies, localStorage, sessionStorage) using CDP."""
		# Use the _cdp_get_cookies helper which handles session attachment
		cookies = await self._cdp_get_cookies()

		# Get origins with localStorage/sessionStorage
		origins = await self._cdp_get_origins()

		return {
			'cookies': cookies,
			'origins': origins,
		}

	async def _cdp_navigate(self, url: str, target_id: TargetID | None = None) -> None:
		"""Navigate to URL using CDP Page.navigate."""
		# Use provided target_id or fall back to current_target_id

		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		assert self.agent_focus is not None, 'CDP session not initialized - browser may not be connected yet'

		self.agent_focus = await self.get_or_create_cdp_session(target_id or self.agent_focus.target_id, focus=True)

		# Use helper to navigate on the target
		await self.agent_focus.cdp_client.send.Page.navigate(params={'url': url}, session_id=self.agent_focus.session_id)

	@staticmethod
	def _is_valid_target(
		target_info: TargetInfo,
		include_http: bool = True,
		include_chrome: bool = False,
		include_chrome_extensions: bool = False,
		include_chrome_error: bool = False,
		include_about: bool = True,
		include_iframes: bool = True,
		include_pages: bool = True,
		include_workers: bool = False,
	) -> bool:
		"""Check if a target should be processed.

		Args:
			target_info: Target info dict from CDP

		Returns:
			True if target should be processed, False if it should be skipped
		"""
		target_type = target_info.get('type', '')
		url = target_info.get('url', '')

		url_allowed, type_allowed = False, False

		# Always allow new tab pages (chrome://new-tab-page/, chrome://newtab/, about:blank)
		# so they can be redirected to about:blank in connect()
		from browser_use.utils import is_new_tab_page

		if is_new_tab_page(url):
			url_allowed = True

		if url.startswith('chrome-error://') and include_chrome_error:
			url_allowed = True

		if url.startswith('chrome://') and include_chrome:
			url_allowed = True

		if url.startswith('chrome-extension://') and include_chrome_extensions:
			url_allowed = True

		# dont allow about:srcdoc! there are also other rare about: pages that we want to avoid
		if url == 'about:blank' and include_about:
			url_allowed = True

		if (url.startswith('http://') or url.startswith('https://')) and include_http:
			url_allowed = True

		if target_type in ('service_worker', 'shared_worker', 'worker') and include_workers:
			type_allowed = True

		if target_type in ('page', 'tab') and include_pages:
			type_allowed = True

		if target_type in ('iframe', 'webview') and include_iframes:
			type_allowed = True

		return url_allowed and type_allowed

	async def get_all_frames(self) -> tuple[dict[str, dict], dict[str, str]]:
		"""Get a complete frame hierarchy from all browser targets.

		Returns:
			Tuple of (all_frames, target_sessions) where:
			- all_frames: dict mapping frame_id -> frame info dict with all metadata
			- target_sessions: dict mapping target_id -> session_id for active sessions
		"""
		all_frames = {}  # frame_id -> FrameInfo dict
		target_sessions = {}  # target_id -> session_id (keep sessions alive during collection)

		# Check if cross-origin iframe support is enabled
		include_cross_origin = self.browser_profile.cross_origin_iframes

		# Get all targets - only include iframes if cross-origin support is enabled
		targets = await self._cdp_get_all_pages(
			include_http=True,
			include_about=True,
			include_pages=True,
			include_iframes=include_cross_origin,  # Only include iframe targets if flag is set
			include_workers=False,
			include_chrome=False,
			include_chrome_extensions=False,
			include_chrome_error=include_cross_origin,  # Only include error pages if cross-origin is enabled
		)
		all_targets = targets

		# First pass: collect frame trees from ALL targets
		for target in all_targets:
			target_id = target['targetId']

			# Skip iframe targets if cross-origin support is disabled
			if not include_cross_origin and target.get('type') == 'iframe':
				continue

			# When cross-origin support is disabled, only process the current target
			if not include_cross_origin:
				# Only process the current focus target
				if self.agent_focus and target_id != self.agent_focus.target_id:
					continue
				# Use the existing agent_focus session
				cdp_session = self.agent_focus
			else:
				# Get cached session for this target (don't change focus - iterating frames)
				cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)

			if cdp_session:
				target_sessions[target_id] = cdp_session.session_id

				try:
					# Try to get frame tree (not all target types support this)
					frame_tree_result = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)

					# Process the frame tree recursively
					def process_frame_tree(node, parent_frame_id=None):
						"""Recursively process frame tree and add to all_frames."""
						frame = node.get('frame', {})
						current_frame_id = frame.get('id')

						if current_frame_id:
							# For iframe targets, check if the frame has a parentId field
							# This indicates it's an OOPIF with a parent in another target
							actual_parent_id = frame.get('parentId') or parent_frame_id

							# Create frame info with all CDP response data plus our additions
							frame_info = {
								**frame,  # Include all original frame data: id, url, parentId, etc.
								'frameTargetId': target_id,  # Target that can access this frame
								'parentFrameId': actual_parent_id,  # Use parentId from frame if available
								'childFrameIds': [],  # Will be populated below
								'isCrossOrigin': False,  # Will be determined based on context
								'isValidTarget': self._is_valid_target(
									target,
									include_http=True,
									include_about=True,
									include_pages=True,
									include_iframes=True,
									include_workers=False,
									include_chrome=False,  # chrome://newtab, chrome://settings, etc. are not valid frames we can control (for sanity reasons)
									include_chrome_extensions=False,  # chrome-extension://
									include_chrome_error=False,  # chrome-error://  (e.g. when iframes fail to load or are blocked by uBlock Origin)
								),
							}

							# Check if frame is cross-origin based on crossOriginIsolatedContextType
							cross_origin_type = frame.get('crossOriginIsolatedContextType')
							if cross_origin_type and cross_origin_type != 'NotIsolated':
								frame_info['isCrossOrigin'] = True

							# For iframe targets, the frame itself is likely cross-origin
							if target.get('type') == 'iframe':
								frame_info['isCrossOrigin'] = True

							# Skip cross-origin frames if support is disabled
							if not include_cross_origin and frame_info.get('isCrossOrigin'):
								return  # Skip this frame and its children

							# Add child frame IDs (note: OOPIFs won't appear here)
							child_frames = node.get('childFrames', [])
							for child in child_frames:
								child_frame = child.get('frame', {})
								child_frame_id = child_frame.get('id')
								if child_frame_id:
									frame_info['childFrameIds'].append(child_frame_id)

							# Store or merge frame info
							if current_frame_id in all_frames:
								# Frame already seen from another target, merge info
								existing = all_frames[current_frame_id]
								# If this is an iframe target, it has direct access to the frame
								if target.get('type') == 'iframe':
									existing['frameTargetId'] = target_id
									existing['isCrossOrigin'] = True
							else:
								all_frames[current_frame_id] = frame_info

							# Process child frames recursively (only if we're not skipping this frame)
							if include_cross_origin or not frame_info.get('isCrossOrigin'):
								for child in child_frames:
									process_frame_tree(child, current_frame_id)

					# Process the entire frame tree
					process_frame_tree(frame_tree_result.get('frameTree', {}))

				except Exception as e:
					# Target doesn't support Page domain or has no frames
					self.logger.debug(f'Failed to get frame tree for target {target_id}: {e}')

		# Second pass: populate backend node IDs and parent target IDs
		# Only do this if cross-origin support is enabled
		if include_cross_origin:
			await self._populate_frame_metadata(all_frames, target_sessions)

		return all_frames, target_sessions

	async def _populate_frame_metadata(self, all_frames: dict[str, dict], target_sessions: dict[str, str]) -> None:
		"""Populate additional frame metadata like backend node IDs and parent target IDs.

		Args:
			all_frames: Frame hierarchy dict to populate
			target_sessions: Active target sessions
		"""
		for frame_id_iter, frame_info in all_frames.items():
			parent_frame_id = frame_info.get('parentFrameId')

			if parent_frame_id and parent_frame_id in all_frames:
				parent_frame_info = all_frames[parent_frame_id]
				parent_target_id = parent_frame_info.get('frameTargetId')

				# Store parent target ID
				frame_info['parentTargetId'] = parent_target_id

				# Try to get backend node ID from parent context
				if parent_target_id in target_sessions:
					assert parent_target_id is not None
					parent_session_id = target_sessions[parent_target_id]
					try:
						# Enable DOM domain
						await self.cdp_client.send.DOM.enable(session_id=parent_session_id)

						# Get frame owner info to find backend node ID
						frame_owner = await self.cdp_client.send.DOM.getFrameOwner(
							params={'frameId': frame_id_iter}, session_id=parent_session_id
						)

						if frame_owner:
							frame_info['backendNodeId'] = frame_owner.get('backendNodeId')
							frame_info['nodeId'] = frame_owner.get('nodeId')

					except Exception:
						# Frame owner not available (likely cross-origin)
						pass

	async def find_frame_target(self, frame_id: str, all_frames: dict[str, dict] | None = None) -> dict | None:
		"""Find the frame info for a specific frame ID.

		Args:
			frame_id: The frame ID to search for
			all_frames: Optional pre-built frame hierarchy. If None, will call get_all_frames()

		Returns:
			Frame info dict if found, None otherwise
		"""
		if all_frames is None:
			all_frames, _ = await self.get_all_frames()

		return all_frames.get(frame_id)

	async def cdp_client_for_target(self, target_id: TargetID) -> CDPSession:
		return await self.get_or_create_cdp_session(target_id, focus=False)

	async def cdp_client_for_frame(self, frame_id: str) -> CDPSession:
		"""Get a CDP client attached to the target containing the specified frame.

		Builds a unified frame hierarchy from all targets to find the correct target
		for any frame, including OOPIFs (Out-of-Process iframes).

		Args:
			frame_id: The frame ID to search for

		Returns:
			Tuple of (cdp_cdp_session, target_id) for the target containing the frame

		Raises:
			ValueError: If the frame is not found in any target
		"""
		# If cross-origin iframes are disabled, just use the main session
		if not self.browser_profile.cross_origin_iframes:
			return await self.get_or_create_cdp_session()

		# Get complete frame hierarchy
		all_frames, target_sessions = await self.get_all_frames()

		# Find the requested frame
		frame_info = await self.find_frame_target(frame_id, all_frames)

		if frame_info:
			target_id = frame_info.get('frameTargetId')

			if target_id in target_sessions:
				assert target_id is not None
				# Use existing session
				session_id = target_sessions[target_id]
				# Return the client with session attached (don't change focus)
				return await self.get_or_create_cdp_session(target_id, focus=False)

		# Frame not found
		raise ValueError(f"Frame with ID '{frame_id}' not found in any target")

	async def cdp_client_for_node(self, node: EnhancedDOMTreeNode) -> CDPSession:
		"""Get CDP client for a specific DOM node based on its frame."""
		if node.frame_id:
			# # If cross-origin iframes are disabled, always use the main session
			# if not self.browser_profile.cross_origin_iframes:
			# 	assert self.agent_focus is not None, 'No active CDP session'
			# 	return self.agent_focus
			# Otherwise, try to get the frame-specific session
			try:
				cdp_session = await self.cdp_client_for_frame(node.frame_id)
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': node.backend_node_id},
					session_id=cdp_session.session_id,
				)
				object_id = result.get('object', {}).get('objectId')
				if not object_id:
					raise ValueError(
						f'Could not find #{node.element_index} backendNodeId={node.backend_node_id} in target_id={cdp_session.target_id}'
					)
				return cdp_session
			except (ValueError, Exception) as e:
				# Fall back to main session if frame not found
				self.logger.debug(f'Failed to get CDP client for frame {node.frame_id}: {e}, using main session')

		if node.target_id:
			try:
				cdp_session = await self.get_or_create_cdp_session(target_id=node.target_id, focus=False)
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': node.backend_node_id},
					session_id=cdp_session.session_id,
				)
				object_id = result.get('object', {}).get('objectId')
				if not object_id:
					raise ValueError(
						f'Could not find #{node.element_index} backendNodeId={node.backend_node_id} in target_id={cdp_session.target_id}'
					)
			except Exception as e:
				self.logger.debug(f'Failed to get CDP client for target {node.target_id}: {e}, using main session')

		return await self.get_or_create_cdp_session()
