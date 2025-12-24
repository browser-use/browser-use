"""Event-driven browser session with backwards compatibility."""

import asyncio
import logging
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, Union, cast, overload
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx
from bubus import EventBus
from cdp_use import CDPClient
from cdp_use.cdp.fetch import AuthRequiredEvent, RequestPausedEvent
from cdp_use.cdp.network import Cookie
from cdp_use.cdp.target import AttachedToTargetEvent, SessionID, TargetID
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from uuid_extensions import uuid7str

from browser_use.browser.cloud.cloud import CloudBrowserAuthError, CloudBrowserClient, CloudBrowserError

# CDP logging is now handled by setup_logging() in logging_config.py
# It automatically sets CDP logs to the same level as browser_use logs
from browser_use.browser.cloud.views import CloudBrowserParams, CreateBrowserRequest, ProxyCountryCode
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
from browser_use.dom.views import DOMRect, EnhancedDOMTreeNode, TargetInfo
from browser_use.observability import observe_debug
from browser_use.utils import _log_pretty_url, create_task_with_error_handling, is_new_tab_page

if TYPE_CHECKING:
	from browser_use.actor.page import Page
	from browser_use.browser.demo_mode import DemoMode

DEFAULT_BROWSER_PROFILE = BrowserProfile()

_LOGGED_UNIQUE_SESSION_IDS = set()  # track unique session IDs that have been logged to make sure we always assign a unique enough id to new sessions and avoid ambiguity in logs
red = '\033[91m'
reset = '\033[0m'


class Target(BaseModel):
	"""Browser target (page, iframe, worker) - the actual entity being controlled.

	A target represents a browsing context with its own URL, title, and type.
	Multiple CDP sessions can attach to the same target for communication.
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True, revalidate_instances='never')

	target_id: TargetID
	target_type: str  # 'page', 'iframe', 'worker', etc.
	url: str = 'about:blank'
	title: str = 'Unknown title'


class CDPSession(BaseModel):
	"""CDP communication channel to a target.

	A session is a connection that allows sending CDP commands to a specific target.
	Multiple sessions can attach to the same target.
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True, revalidate_instances='never')

	cdp_client: CDPClient
	target_id: TargetID
	session_id: SessionID

	# Lifecycle monitoring (populated by SessionManager)
	_lifecycle_events: Any = PrivateAttr(default=None)
	_lifecycle_lock: Any = PrivateAttr(default=None)


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

	# Overload 1: Cloud browser mode (use cloud-specific params)
	@overload
	def __init__(
		self,
		*,
		# Cloud browser params - use these for cloud mode
		cloud_profile_id: UUID | str | None = None,
		cloud_proxy_country_code: ProxyCountryCode | None = None,
		cloud_timeout: int | None = None,
		# Backward compatibility aliases
		profile_id: UUID | str | None = None,
		proxy_country_code: ProxyCountryCode | None = None,
		timeout: int | None = None,
		use_cloud: bool | None = None,
		cloud_browser: bool | None = None,  # Backward compatibility alias
		cloud_browser_params: CloudBrowserParams | None = None,
		# Common params that work with cloud
		id: str | None = None,
		headers: dict[str, str] | None = None,
		allowed_domains: list[str] | None = None,
		prohibited_domains: list[str] | None = None,
		keep_alive: bool | None = None,
		minimum_wait_page_load_time: float | None = None,
		wait_for_network_idle_page_load_time: float | None = None,
		wait_between_actions: float | None = None,
		auto_download_pdfs: bool | None = None,
		cookie_whitelist_domains: list[str] | None = None,
		cross_origin_iframes: bool | None = None,
		highlight_elements: bool | None = None,
		dom_highlight_elements: bool | None = None,
		paint_order_filtering: bool | None = None,
		max_iframes: int | None = None,
		max_iframe_depth: int | None = None,
	) -> None: ...

	# Overload 2: Local browser mode (use local browser params)
	@overload
	def __init__(
		self,
		*,
		# Core configuration for local
		id: str | None = None,
		cdp_url: str | None = None,
		browser_profile: BrowserProfile | None = None,
		# Local browser launch params
		executable_path: str | Path | None = None,
		headless: bool | None = None,
		user_data_dir: str | Path | None = None,
		args: list[str] | None = None,
		downloads_path: str | Path | None = None,
		# Common params
		headers: dict[str, str] | None = None,
		allowed_domains: list[str] | None = None,
		prohibited_domains: list[str] | None = None,
		keep_alive: bool | None = None,
		minimum_wait_page_load_time: float | None = None,
		wait_for_network_idle_page_load_time: float | None = None,
		wait_between_actions: float | None = None,
		auto_download_pdfs: bool | None = None,
		cookie_whitelist_domains: list[str] | None = None,
		cross_origin_iframes: bool | None = None,
		highlight_elements: bool | None = None,
		dom_highlight_elements: bool | None = None,
		paint_order_filtering: bool | None = None,
		max_iframes: int | None = None,
		max_iframe_depth: int | None = None,
		# All other local params
		env: dict[str, str | float | bool] | None = None,
		ignore_default_args: list[str] | Literal[True] | None = None,
		channel: str | None = None,
		chromium_sandbox: bool | None = None,
		devtools: bool | None = None,
		traces_dir: str | Path | None = None,
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
		storage_state: str | Path | dict[str, Any] | None = None,
		disable_security: bool | None = None,
		deterministic_rendering: bool | None = None,
		proxy: ProxySettings | None = None,
		enable_default_extensions: bool | None = None,
		window_size: dict | None = None,
		window_position: dict | None = None,
		filter_highlight_ids: bool | None = None,
		profile_directory: str | None = None,
	) -> None: ...

	def __init__(
		self,
		# Core configuration
		id: str | None = None,
		cdp_url: str | None = None,
		is_local: bool = False,
		browser_profile: BrowserProfile | None = None,
		# Cloud browser params (don't mix with local browser params)
		cloud_profile_id: UUID | str | None = None,
		cloud_proxy_country_code: ProxyCountryCode | None = None,
		cloud_timeout: int | None = None,
		# Backward compatibility aliases for cloud params
		profile_id: UUID | str | None = None,
		proxy_country_code: ProxyCountryCode | None = None,
		timeout: int | None = None,
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
		## Cloud Browser Fields
		use_cloud: bool | None = None,
		cloud_browser: bool | None = None,  # Backward compatibility alias
		cloud_browser_params: CloudBrowserParams | None = None,
		## Other params
		disable_security: bool | None = None,
		deterministic_rendering: bool | None = None,
		allowed_domains: list[str] | None = None,
		prohibited_domains: list[str] | None = None,
		keep_alive: bool | None = None,
		proxy: ProxySettings | None = None,
		enable_default_extensions: bool | None = None,
		window_size: dict | None = None,
		window_position: dict | None = None,
		minimum_wait_page_load_time: float | None = None,
		wait_for_network_idle_page_load_time: float | None = None,
		wait_between_actions: float | None = None,
		filter_highlight_ids: bool | None = None,
		auto_download_pdfs: bool | None = None,
		profile_directory: str | None = None,
		cookie_whitelist_domains: list[str] | None = None,
		# DOM extraction layer configuration
		cross_origin_iframes: bool | None = None,
		highlight_elements: bool | None = None,
		dom_highlight_elements: bool | None = None,
		paint_order_filtering: bool | None = None,
		# Iframe processing limits
		max_iframes: int | None = None,
		max_iframe_depth: int | None = None,
	):
		# Following the same pattern as AgentSettings in service.py
		# Only pass non-None values to avoid validation errors
		profile_kwargs = {
			k: v
			for k, v in locals().items()
			if k
			not in [
				'self',
				'browser_profile',
				'id',
				'cloud_profile_id',
				'cloud_proxy_country_code',
				'cloud_timeout',
				'profile_id',
				'proxy_country_code',
				'timeout',
			]
			and v is not None
		}

		# Handle backward compatibility: prefer cloud_* params over old names
		final_profile_id = cloud_profile_id if cloud_profile_id is not None else profile_id
		final_proxy_country_code = cloud_proxy_country_code if cloud_proxy_country_code is not None else proxy_country_code
		final_timeout = cloud_timeout if cloud_timeout is not None else timeout

		# If any cloud params are provided, create cloud_browser_params
		if final_profile_id is not None or final_proxy_country_code is not None or final_timeout is not None:
			cloud_params = CreateBrowserRequest(
				cloud_profile_id=final_profile_id,
				cloud_proxy_country_code=final_proxy_country_code,
				cloud_timeout=final_timeout,
			)
			profile_kwargs['cloud_browser_params'] = cloud_params
			profile_kwargs['use_cloud'] = True

		# Handle backward compatibility: map cloud_browser to use_cloud
		if 'cloud_browser' in profile_kwargs:
			profile_kwargs['use_cloud'] = profile_kwargs.pop('cloud_browser')

		# If cloud_browser_params is set, force use_cloud=True
		if cloud_browser_params is not None:
			profile_kwargs['use_cloud'] = True

		# if is_local is False but executable_path is provided, set is_local to True
		if is_local is False and executable_path is not None:
			profile_kwargs['is_local'] = True
		# Only set is_local=True when cdp_url is missing if we're not using cloud browser
		# (cloud browser will provide cdp_url later)
		use_cloud = profile_kwargs.get('use_cloud') or profile_kwargs.get('cloud_browser')
		if not cdp_url and not use_cloud:
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

	# LLM screenshot resizing configuration
	llm_screenshot_size: tuple[int, int] | None = Field(
		default=None,
		description='Target size (width, height) to resize screenshots before sending to LLM. Coordinates from LLM will be scaled back to original viewport size.',
	)

	# Cache of original viewport size for coordinate conversion (set when browser state is captured)
	_original_viewport_size: tuple[int, int] | None = PrivateAttr(default=None)

	# Convenience properties for common browser settings
	@property
	def cdp_url(self) -> str | None:
		"""CDP URL from browser profile."""
		return self.browser_profile.cdp_url

	@property
	def is_local(self) -> bool:
		"""Whether this is a local browser instance from browser profile."""
		return self.browser_profile.is_local

	@property
	def cloud_browser(self) -> bool:
		"""Whether to use cloud browser service from browser profile."""
		return self.browser_profile.use_cloud

	@property
	def demo_mode(self) -> 'DemoMode | None':
		"""Lazy init demo mode helper when enabled."""
		if not self.browser_profile.demo_mode:
			return None
		if self._demo_mode is None:
			from browser_use.browser.demo_mode import DemoMode

			self._demo_mode = DemoMode(self)
		return self._demo_mode

	# Main shared event bus for all browser session + all watchdogs
	event_bus: EventBus = Field(default_factory=EventBus)

	# Mutable public state - which target has agent focus
	agent_focus_target_id: TargetID | None = None

	# Mutable private state shared between watchdogs
	_cdp_client_root: CDPClient | None = PrivateAttr(default=None)
	_connection_lock: Any = PrivateAttr(default=None)  # asyncio.Lock for preventing concurrent connections

	# PUBLIC: SessionManager instance (OWNS all targets and sessions)
	session_manager: Any = Field(default=None, exclude=True)  # SessionManager

	_cached_browser_state_summary: Any = PrivateAttr(default=None)
	_cached_selector_map: dict[int, EnhancedDOMTreeNode] = PrivateAttr(default_factory=dict)
	_downloaded_files: list[str] = PrivateAttr(default_factory=list)  # Track files downloaded during this session
	_closed_popup_messages: list[str] = PrivateAttr(default_factory=list)  # Store messages from auto-closed JavaScript dialogs

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

	_cloud_browser_client: CloudBrowserClient = PrivateAttr(default_factory=lambda: CloudBrowserClient())
	_demo_mode: 'DemoMode | None' = PrivateAttr(default=None)

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
		return self.agent_focus_target_id[-2:] if self.agent_focus_target_id else f'{red}--{reset}'

	def __repr__(self) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs} (cdp_url={self.cdp_url}, profile={self.browser_profile})'

	def __str__(self) -> str:
		return f'BrowserSession🅑 {self._id_for_logs} 🅣 {self._tab_id_for_logs}'

	async def reset(self) -> None:
		"""Clear all cached CDP sessions with proper cleanup."""

		cdp_status = 'connected' if self._cdp_client_root else 'not connected'
		session_mgr_status = 'exists' if self.session_manager else 'None'
		self.logger.debug(
			f'🔄 Resetting browser session (CDP: {cdp_status}, SessionManager: {session_mgr_status}, '
			f'focus: {self.agent_focus_target_id[-4:] if self.agent_focus_target_id else "None"})'
		)

		# Clear session manager (which owns _targets, _sessions, _target_sessions)
		if self.session_manager:
			await self.session_manager.clear()
			self.session_manager = None

		# Close CDP WebSocket before clearing to prevent stale event handlers
		if self._cdp_client_root:
			try:
				await self._cdp_client_root.stop()
				self.logger.debug('Closed CDP client WebSocket during reset')
			except Exception as e:
				self.logger.debug(f'Error closing CDP client during reset: {e}')

		self._cdp_client_root = None  # type: ignore
		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self._downloaded_files.clear()

		self.agent_focus_target_id = None
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
		if self._demo_mode:
			self._demo_mode.reset()
			self._demo_mode = None

		self.logger.info('✅ Browser session reset complete')

	def model_post_init(self, __context) -> None:
		"""Register event handlers after model initialization."""
		self._connection_lock = asyncio.Lock()

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

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_session_start')
	async def start(self) -> None:
		"""Start the browser session."""
		start_event = self.event_bus.dispatch(BrowserStartEvent())
		await start_event
		# Ensure any exceptions from the event handler are propagated
		await start_event.event_result(raise_if_any=True, raise_if_none=False)

	async def kill(self) -> None:
		"""Kill the browser session and reset all state."""
		self.logger.debug('🛑 kill() called - stopping browser with force=True and resetting state')

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
		self.logger.debug('⏸️  stop() called - stopping browser gracefully (force=False) and resetting state')

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

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_start_event_handler')
	async def on_BrowserStartEvent(self, event: BrowserStartEvent) -> dict[str, str]:
		"""Handle browser start request.

		Returns:
			Dict with 'cdp_url' key containing the CDP URL

		Note: This method is idempotent - calling start() multiple times is safe.
		- If already connected, it skips reconnection
		- If you need to reset state, call stop() or kill() first
		"""

		# Initialize and attach all watchdogs FIRST so LocalBrowserWatchdog can handle BrowserLaunchEvent
		await self.attach_all_watchdogs()

		try:
			# If no CDP URL, launch local browser or cloud browser
			if not self.cdp_url:
				if self.browser_profile.use_cloud or self.browser_profile.cloud_browser_params is not None:
					# Use cloud browser service
					try:
						# Use cloud_browser_params if provided, otherwise create empty request
						cloud_params = self.browser_profile.cloud_browser_params or CreateBrowserRequest()
						cloud_browser_response = await self._cloud_browser_client.create_browser(cloud_params)
						self.browser_profile.cdp_url = cloud_browser_response.cdpUrl
						self.browser_profile.is_local = False
						self.logger.info('🌤️ Successfully connected to cloud browser service')
					except CloudBrowserAuthError:
						raise CloudBrowserAuthError(
							'Authentication failed for cloud browser service. Set BROWSER_USE_API_KEY environment variable. You can also create an API key at https://cloud.browser-use.com/new-api-key'
						)
					except CloudBrowserError as e:
						raise CloudBrowserError(f'Failed to create cloud browser: {e}')
				elif self.is_local:
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

			# Use lock to prevent concurrent connection attempts (race condition protection)
			async with self._connection_lock:
				# Only connect if not already connected
				if self._cdp_client_root is None:
					# Setup browser via CDP (for both local and remote cases)
					await self.connect(cdp_url=self.cdp_url)
					assert self.cdp_client is not None

					# Notify that browser is connected (single place)
					self.event_bus.dispatch(BrowserConnectedEvent(cdp_url=self.cdp_url))

					if self.browser_profile.demo_mode:
						try:
							demo = self.demo_mode
							if demo:
								await demo.ensure_ready()
						except Exception as exc:
							self.logger.warning(f'[DemoMode] Failed to inject demo overlay: {exc}')
				else:
					self.logger.debug('Already connected to CDP, skipping reconnection')
					if self.browser_profile.demo_mode:
						try:
							demo = self.demo_mode
							if demo:
								await demo.ensure_ready()
						except Exception as exc:
							self.logger.warning(f'[DemoMode] Failed to inject demo overlay: {exc}')

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
		if not self.agent_focus_target_id:
			self.logger.warning('Cannot navigate - browser not connected')
			return

		target_id = None
		current_target_id = self.agent_focus_target_id

		# If new_tab=True but we're already in a new tab, set new_tab=False
		current_target = self.session_manager.get_target(current_target_id)
		if event.new_tab and is_new_tab_page(current_target.url):
			self.logger.debug(f'[on_NavigateToUrlEvent] Already on blank tab ({current_target.url}), reusing')
			event.new_tab = False

		try:
			# Find or create target for navigation
			self.logger.debug(f'[on_NavigateToUrlEvent] Processing new_tab={event.new_tab}')

			if event.new_tab:
				page_targets = self.session_manager.get_all_page_targets()
				self.logger.debug(f'[on_NavigateToUrlEvent] Found {len(page_targets)} existing tabs')

				# Look for existing about:blank tab that's not the current one
				for idx, target in enumerate(page_targets):
					self.logger.debug(f'[on_NavigateToUrlEvent] Tab {idx}: url={target.url}, targetId={target.target_id}')
					if target.url == 'about:blank' and target.target_id != current_target_id:
						target_id = target.target_id
						self.logger.debug(f'Reusing existing about:blank tab #{target_id[-4:]}')
						break

				# Create new tab if no reusable one found
				if not target_id:
					self.logger.debug('[on_NavigateToUrlEvent] No reusable about:blank tab found, creating new tab...')
					try:
						target_id = await self._cdp_create_new_page('about:blank')
						self.logger.debug(f'Created new tab #{target_id[-4:]}')
						# Dispatch TabCreatedEvent for new tab
						await self.event_bus.dispatch(TabCreatedEvent(target_id=target_id, url='about:blank'))
					except Exception as e:
						self.logger.error(f'[on_NavigateToUrlEvent] Failed to create new tab: {type(e).__name__}: {e}')
						# Fall back to using current tab
						target_id = current_target_id
						self.logger.warning(f'[on_NavigateToUrlEvent] Falling back to current tab #{target_id[-4:]}')
			else:
				# Use current tab
				target_id = target_id or current_target_id

			# Switch to target tab if needed (for both new_tab=True and new_tab=False)
			if self.agent_focus_target_id is None or self.agent_focus_target_id != target_id:
				self.logger.debug(
					f'[on_NavigateToUrlEvent] Switching to target tab {target_id[-4:]} (current: {self.agent_focus_target_id[-4:] if self.agent_focus_target_id else "none"})'
				)
				# Activate target (bring to foreground)
				await self.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
			else:
				self.logger.debug(f'[on_NavigateToUrlEvent] Already on target tab {target_id[-4:]}, skipping SwitchTabEvent')

			assert self.agent_focus_target_id is not None and self.agent_focus_target_id == target_id, (
				'Agent focus not updated to new target_id after SwitchTabEvent should have switched to it'
			)

			# Dispatch navigation started
			await self.event_bus.dispatch(NavigationStartedEvent(target_id=target_id, url=event.url))

			# Navigate to URL with proper lifecycle waiting
			await self._navigate_and_wait(event.url, target_id)

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
			await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=event.url))

			# Note: These should be handled by dedicated watchdogs:
			# - Security checks (security_watchdog)
			# - Page health checks (crash_watchdog)
			# - Dialog handling (dialog_watchdog)
			# - Download handling (downloads_watchdog)
			# - DOM rebuilding (dom_watchdog)

		except Exception as e:
			self.logger.error(f'Navigation failed: {type(e).__name__}: {e}')
			# target_id might be unbound if exception happens early
			if 'target_id' in locals() and target_id:
				await self.event_bus.dispatch(
					NavigationCompleteEvent(
						target_id=target_id,
						url=event.url,
						error_message=f'{type(e).__name__}: {e}',
					)
				)
				await self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url=event.url))
			raise

	async def _navigate_and_wait(self, url: str, target_id: str, timeout: float | None = None) -> None:
		"""Navigate to URL and wait for page readiness using CDP lifecycle events.

		Two-strategy approach optimized for speed with robust fallback:
		1. networkIdle - Returns ASAP when no network activity (~50-200ms for cached pages)
		2. load - Fallback when page has ongoing network activity (all resources loaded)

		This gives us instant returns for cached content while being robust for dynamic pages.

		NO handler registration here - handlers are registered ONCE per session in SessionManager.
		We poll stored events instead to avoid handler accumulation.
		"""
		cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)

		if timeout is None:
			target = self.session_manager.get_target(target_id)
			current_url = target.url
			same_domain = (
				url.split('/')[2] == current_url.split('/')[2]
				if url.startswith('http') and current_url.startswith('http')
				else False
			)
			timeout = 2.0 if same_domain else 4.0

		# Start performance tracking
		nav_start_time = asyncio.get_event_loop().time()

		nav_result = await cdp_session.cdp_client.send.Page.navigate(
			params={'url': url, 'transitionType': 'address_bar'},
			session_id=cdp_session.session_id,
		)

		# Check for immediate navigation errors
		if nav_result.get('errorText'):
			raise RuntimeError(f'Navigation failed: {nav_result["errorText"]}')

		# Track this specific navigation
		navigation_id = nav_result.get('loaderId')
		start_time = asyncio.get_event_loop().time()

		# Poll stored lifecycle events
		seen_events = []  # Track events for timeout diagnostics

		# Check if session has lifecycle monitoring enabled
		if not hasattr(cdp_session, '_lifecycle_events'):
			raise RuntimeError(
				f'❌ Lifecycle monitoring not enabled for {cdp_session.target_id[:8]}! '
				f'This is a bug - SessionManager should have initialized it. '
				f'Session: {cdp_session}'
			)

		# Poll for lifecycle events until timeout
		poll_interval = 0.05  # Poll every 50ms
		while (asyncio.get_event_loop().time() - start_time) < timeout:
			# Check stored events
			try:
				# Get recent events matching our navigation
				for event_data in list(cdp_session._lifecycle_events):
					event_name = event_data.get('name')
					event_loader_id = event_data.get('loaderId')

					# Track events
					event_str = f'{event_name}(loader={event_loader_id[:8] if event_loader_id else "none"})'
					if event_str not in seen_events:
						seen_events.append(event_str)

					# Only respond to events from our navigation (or accept all if no loaderId)
					if event_loader_id and navigation_id and event_loader_id != navigation_id:
						continue

					if event_name == 'networkIdle':
						duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
						self.logger.debug(f'✅ Page ready for {url} (networkIdle, {duration_ms:.0f}ms)')
						return

					elif event_name == 'load':
						duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
						self.logger.debug(f'✅ Page ready for {url} (load, {duration_ms:.0f}ms)')
						return

			except Exception as e:
				self.logger.debug(f'Error polling lifecycle events: {e}')

			# Wait before next poll
			await asyncio.sleep(poll_interval)

		# Timeout - continue anyway with detailed diagnostics
		duration_ms = (asyncio.get_event_loop().time() - nav_start_time) * 1000
		if not seen_events:
			self.logger.error(
				f'❌ No lifecycle events received for {url} after {duration_ms:.0f}ms! '
				f'Monitoring may have failed. Target: {cdp_session.target_id[:8]}'
			)
		else:
			self.logger.warning(f'⚠️ Page readiness timeout ({timeout}s, {duration_ms:.0f}ms) for {url}')

	async def on_SwitchTabEvent(self, event: SwitchTabEvent) -> TargetID:
		"""Handle tab switching - core browser functionality."""
		if not self.agent_focus_target_id:
			raise RuntimeError('Cannot switch tabs - browser not connected')

		# Get all page targets
		page_targets = self.session_manager.get_all_page_targets()
		if event.target_id is None:
			# Most recently opened page
			if page_targets:
				# Update the target id to be the id of the most recently opened page, then proceed to switch to it
				event.target_id = page_targets[-1].target_id
			else:
				# No pages open at all, create a new one (handles switching to it automatically)
				assert self._cdp_client_root is not None, 'CDP client root not initialized - browser may not be connected yet'
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				# Don't await, these may circularly trigger SwitchTabEvent and could deadlock, dispatch to enqueue and return
				self.event_bus.dispatch(TabCreatedEvent(url='about:blank', target_id=target_id))
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=target_id, url='about:blank'))
				return target_id

		# Switch to the target
		assert event.target_id is not None, 'target_id must be set at this point'
		# Ensure session exists and update agent focus (only for page/tab targets)
		cdp_session = await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)

		# Visually switch to the tab in the browser
		# The Force Background Tab extension prevents Chrome from auto-switching when links create new tabs,
		# but we still want the agent to be able to explicitly switch tabs when needed
		await cdp_session.cdp_client.send.Target.activateTarget(params={'targetId': event.target_id})

		# Get target to access url
		target = self.session_manager.get_target(event.target_id)

		# dispatch focus changed event
		await self.event_bus.dispatch(
			AgentFocusChangedEvent(
				target_id=target.target_id,
				url=target.url,
			)
		)
		return target.target_id

	async def on_CloseTabEvent(self, event: CloseTabEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		try:
			# Dispatch tab closed event
			await self.event_bus.dispatch(TabClosedEvent(target_id=event.target_id))

			# Try to close the target, but don't fail if it's already closed
			try:
				cdp_session = await self.get_or_create_cdp_session(target_id=None, focus=False)
				await cdp_session.cdp_client.send.Target.closeTarget(params={'targetId': event.target_id})
			except Exception as e:
				self.logger.debug(f'Target may already be closed: {e}')
		except Exception as e:
			self.logger.warning(f'Error during tab close cleanup: {e}')

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Handle tab creation - apply viewport settings to new tab."""
		# Note: Tab switching prevention is handled by the Force Background Tab extension
		# The extension automatically keeps focus on the current tab when new tabs are created

		# Apply viewport settings if configured
		if self.browser_profile.viewport and not self.browser_profile.no_viewport:
			try:
				viewport_width = self.browser_profile.viewport.width
				viewport_height = self.browser_profile.viewport.height
				device_scale_factor = self.browser_profile.device_scale_factor or 1.0

				self.logger.info(
					f'Setting viewport to {viewport_width}x{viewport_height} with device scale factor {device_scale_factor} whereas original device scale factor was {self.browser_profile.device_scale_factor}'
				)
				# Use the helper method with the new tab's target_id
				await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=event.target_id)

				self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {event.target_id[-8:]}')
			except Exception as e:
				self.logger.warning(f'Failed to set viewport for new tab {event.target_id[-8:]}: {e}')

	async def on_TabClosedEvent(self, event: TabClosedEvent) -> None:
		"""Handle tab closure - update focus if needed."""
		if not self.agent_focus_target_id:
			return

		# Get current tab index
		current_target_id = self.agent_focus_target_id

		# If the closed tab was the current one, find a new target
		if current_target_id == event.target_id:
			await self.event_bus.dispatch(SwitchTabEvent(target_id=None))

	async def on_AgentFocusChangedEvent(self, event: AgentFocusChangedEvent) -> None:
		"""Handle agent focus change - update focus and clear cache."""
		self.logger.debug(f'🔄 AgentFocusChangedEvent received: target_id=...{event.target_id[-4:]} url={event.url}')

		# Clear cached DOM state since focus changed
		if self._dom_watchdog:
			self._dom_watchdog.clear_cache()

		# Clear cached browser state
		self._cached_browser_state_summary = None
		self._cached_selector_map.clear()
		self.logger.debug('🔄 Cached browser state cleared')

		# Update agent focus if a specific target_id is provided (only for page/tab targets)
		if event.target_id:
			# Ensure session exists and update agent focus (validates target_type internally)
			await self.get_or_create_cdp_session(target_id=event.target_id, focus=True)

			# Apply viewport settings to the newly focused tab
			if self.browser_profile.viewport and not self.browser_profile.no_viewport:
				try:
					viewport_width = self.browser_profile.viewport.width
					viewport_height = self.browser_profile.viewport.height
					device_scale_factor = self.browser_profile.device_scale_factor or 1.0

					# Use the helper method with the current tab's target_id
					await self._cdp_set_viewport(viewport_width, viewport_height, device_scale_factor, target_id=event.target_id)

					self.logger.debug(f'Applied viewport {viewport_width}x{viewport_height} to tab {event.target_id[-8:]}')
				except Exception as e:
					self.logger.warning(f'Failed to set viewport for tab {event.target_id[-8:]}: {e}')
		else:
			raise RuntimeError('AgentFocusChangedEvent received with no target_id for newly focused tab')

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

			# Clean up cloud browser session if using cloud browser
			if self.browser_profile.use_cloud:
				try:
					await self._cloud_browser_client.stop_browser()
					self.logger.info('🌤️ Cloud browser session cleaned up')
				except Exception as e:
					self.logger.debug(f'Failed to cleanup cloud browser session: {e}')

			# Clear CDP session cache before stopping
			self.logger.info(
				f'📢 on_BrowserStopEvent - Calling reset() (force={event.force}, keep_alive={self.browser_profile.keep_alive})'
			)
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

	# region - ========== CDP-based replacements for browser_context operations ==========
	@property
	def cdp_client(self) -> CDPClient:
		"""Get the cached root CDP cdp_session.cdp_client. The client is created and started in self.connect()."""
		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		return self._cdp_client_root

	async def new_page(self, url: str | None = None) -> 'Page':
		"""Create a new page (tab)."""
		from cdp_use.cdp.target.commands import CreateTargetParameters

		params: CreateTargetParameters = {'url': url or 'about:blank'}
		result = await self.cdp_client.send.Target.createTarget(params)

		target_id = result['targetId']

		# Import here to avoid circular import
		from browser_use.actor.page import Page as Target

		return Target(self, target_id)

	async def get_current_page(self) -> 'Page | None':
		"""Get the current page as an actor Page."""
		target_info = await self.get_current_target_info()

		if not target_info:
			return None

		from browser_use.actor.page import Page as Target

		return Target(self, target_info['targetId'])

	async def must_get_current_page(self) -> 'Page':
		"""Get the current page as an actor Page."""
		page = await self.get_current_page()
		if not page:
			raise RuntimeError('No current target found')

		return page

	async def get_pages(self) -> list['Page']:
		"""Get all available pages using SessionManager (source of truth)."""
		# Import here to avoid circular import
		from browser_use.actor.page import Page as PageActor

		page_targets = self.session_manager.get_all_page_targets() if self.session_manager else []

		targets = []
		for target in page_targets:
			targets.append(PageActor(self, target.target_id))

		return targets

	def get_focused_target(self) -> 'Target | None':
		"""Get the target that currently has agent focus.

		Returns:
			Target object if agent has focus, None otherwise.
		"""
		if not self.session_manager:
			return None
		return self.session_manager.get_focused_target()

	def get_page_targets(self) -> list['Target']:
		"""Get all page/tab targets (excludes iframes, workers, etc.).

		Returns:
			List of Target objects for all page/tab targets.
		"""
		if not self.session_manager:
			return []
		return self.session_manager.get_all_page_targets()

	async def close_page(self, page: 'Union[Page, str]') -> None:
		"""Close a page by Page object or target ID."""
		from cdp_use.cdp.target.commands import CloseTargetParameters

		# Import here to avoid circular import
		from browser_use.actor.page import Page as Target

		if isinstance(page, Target):
			target_id = page._target_id
		else:
			target_id = str(page)

		params: CloseTargetParameters = {'targetId': target_id}
		await self.cdp_client.send.Target.closeTarget(params)

	async def cookies(self) -> list['Cookie']:
		"""Get cookies, optionally filtered by URLs."""

		result = await self.cdp_client.send.Storage.getCookies()
		return result['cookies']

	async def clear_cookies(self) -> None:
		"""Clear all cookies."""
		await self.cdp_client.send.Network.clearBrowserCookies()

	async def export_storage_state(self, output_path: str | Path | None = None) -> dict[str, Any]:
		"""Export all browser cookies and storage to storage_state format.

		Extracts decrypted cookies via CDP, bypassing keychain encryption.

		Args:
			output_path: Optional path to save storage_state.json. If None, returns dict only.

		Returns:
			Storage state dict with cookies in Playwright format.

		"""
		from pathlib import Path

		# Get all cookies using Storage.getCookies (returns decrypted cookies from all domains)
		cookies = await self._cdp_get_cookies()

		# Convert CDP cookie format to Playwright storage_state format
		storage_state = {
			'cookies': [
				{
					'name': c['name'],
					'value': c['value'],
					'domain': c['domain'],
					'path': c['path'],
					'expires': c.get('expires', -1),
					'httpOnly': c.get('httpOnly', False),
					'secure': c.get('secure', False),
					'sameSite': c.get('sameSite', 'Lax'),
				}
				for c in cookies
			],
			'origins': [],  # Could add localStorage/sessionStorage extraction if needed
		}

		if output_path:
			import json

			output_file = Path(output_path).expanduser().resolve()
			output_file.parent.mkdir(parents=True, exist_ok=True)
			output_file.write_text(json.dumps(storage_state, indent=2))
			self.logger.info(f'💾 Exported {len(cookies)} cookies to {output_file}')

		return storage_state

	async def get_or_create_cdp_session(self, target_id: TargetID | None = None, focus: bool = True) -> CDPSession:
		"""Get CDP session for a target from the event-driven pool.

		With autoAttach=True, sessions are created automatically by Chrome and added
		to the pool via Target.attachedToTarget events. This method retrieves them.

		Args:
			target_id: Target ID to get session for. If None, uses current agent focus.
			focus: If True, switches agent focus to this target (page targets only).

		Returns:
			CDPSession for the specified target.

		Raises:
			ValueError: If target doesn't exist or session is not available.
		"""
		assert self._cdp_client_root is not None, 'Root CDP client not initialized'
		assert self.session_manager is not None, 'SessionManager not initialized'

		# If no target_id specified, ensure current agent focus is valid and wait for recovery if needed
		if target_id is None:
			# Validate and wait for focus recovery if stale (centralized protection)
			focus_valid = await self.session_manager.ensure_valid_focus(timeout=5.0)
			if not focus_valid:
				raise ValueError(
					'No valid agent focus available - target may have detached and recovery failed. '
					'This indicates browser is in an unstable state.'
				)

			assert self.agent_focus_target_id is not None, 'Focus validation passed but agent_focus_target_id is None'
			target_id = self.agent_focus_target_id

		session = self.session_manager._get_session_for_target(target_id)

		if not session:
			# Session not in pool yet - wait for attach event
			self.logger.debug(f'[SessionManager] Waiting for target {target_id[:8]}... to attach...')

			# Wait up to 2 seconds for the attach event
			for attempt in range(20):
				await asyncio.sleep(0.1)
				session = self.session_manager._get_session_for_target(target_id)
				if session:
					self.logger.debug(f'[SessionManager] Target appeared after {attempt * 100}ms')
					break

			if not session:
				# Timeout - target doesn't exist
				raise ValueError(f'Target {target_id} not found - may have detached or never existed')

		# Validate session is still active
		is_valid = await self.session_manager.validate_session(target_id)
		if not is_valid:
			raise ValueError(f'Target {target_id} has detached - no active sessions')

		# Update focus if requested
		# CRITICAL: Only allow focus change to 'page' type targets, not iframes/workers
		if focus and self.agent_focus_target_id != target_id:
			# Get target type from SessionManager
			target = self.session_manager.get_target(target_id)
			target_type = target.target_type if target else 'unknown'

			if target_type == 'page':
				# Format current focus safely (could be None after detach)
				current_focus = self.agent_focus_target_id[:8] if self.agent_focus_target_id else 'None'
				self.logger.debug(f'[SessionManager] Switching focus: {current_focus}... → {target_id[:8]}...')
				self.agent_focus_target_id = target_id
			else:
				# Ignore focus request for non-page targets (iframes, workers, etc.)
				# These can detach at any time, causing agent_focus to point to dead target
				current_focus = self.agent_focus_target_id[:8] if self.agent_focus_target_id else 'None'
				self.logger.debug(
					f'[SessionManager] Ignoring focus request for {target_type} target {target_id[:8]}... '
					f'(agent_focus stays on {current_focus}...)'
				)

		# Resume if waiting for debugger
		if focus:
			try:
				await session.cdp_client.send.Runtime.runIfWaitingForDebugger(session_id=session.session_id)
			except Exception:
				pass  # May fail if not waiting

		return session

	# endregion - ========== CDP-based ... ==========

	# region - ========== Helper Methods ==========
	@observe_debug(ignore_input=True, ignore_output=True, name='get_browser_state_summary')
	async def get_browser_state_summary(
		self,
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
					include_recent_events=include_recent_events,
				)
			),
		)

		# The handler returns the BrowserStateSummary directly
		result = await event.event_result(raise_if_none=True, raise_if_any=True)
		assert result is not None and result.dom_state is not None
		return result

	async def get_state_as_text(self) -> str:
		"""Get the browser state as text."""
		state = await self.get_browser_state_summary()
		assert state.dom_state is not None
		dom_state = state.dom_state
		return dom_state.llm_representation()

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

		# Prevent duplicate connections - clean up existing connection first
		if self._cdp_client_root is not None:
			self.logger.warning(
				'⚠️ connect() called but CDP client already exists! Cleaning up old connection before creating new one.'
			)
			try:
				await self._cdp_client_root.stop()
			except Exception as e:
				self.logger.debug(f'Error stopping old CDP client: {e}')
			self._cdp_client_root = None

		if not self.cdp_url.startswith('ws'):
			# If it's an HTTP URL, fetch the WebSocket URL from /json/version endpoint
			parsed_url = urlparse(self.cdp_url)
			path = parsed_url.path.rstrip('/')

			if not path.endswith('/json/version'):
				path = path + '/json/version'

			url = urlunparse(
				(parsed_url.scheme, parsed_url.netloc, path, parsed_url.params, parsed_url.query, parsed_url.fragment)
			)

			# Run a tiny HTTP client to query for the WebSocket URL from the /json/version endpoint
			async with httpx.AsyncClient() as client:
				headers = self.browser_profile.headers or {}
				version_info = await client.get(url, headers=headers)
				self.logger.debug(f'Raw version info: {str(version_info)}')
				self.browser_profile.cdp_url = version_info.json()['webSocketDebuggerUrl']

		assert self.cdp_url is not None, 'CDP URL is None.'

		browser_location = 'local browser' if self.is_local else 'remote browser'
		self.logger.debug(f'🌎 Connecting to existing chromium-based browser via CDP: {self.cdp_url} -> ({browser_location})')

		try:
			# Create and store the CDP client for direct CDP communication
			headers = getattr(self.browser_profile, 'headers', None)
			self._cdp_client_root = CDPClient(
				self.cdp_url,
				additional_headers=headers,
				max_ws_frame_size=200 * 1024 * 1024,  # Use 200MB limit to handle pages with very large DOMs
			)
			assert self._cdp_client_root is not None
			await self._cdp_client_root.start()

			# Initialize event-driven session manager FIRST (before enabling autoAttach)
			# SessionManager will:
			# 1. Register attach/detach event handlers
			# 2. Discover and attach to all existing targets
			# 3. Initialize sessions and enable lifecycle monitoring
			# 4. Enable autoAttach for future targets
			from browser_use.browser.session_manager import SessionManager

			self.session_manager = SessionManager(self)
			await self.session_manager.start_monitoring()
			self.logger.debug('Event-driven session manager started')

			# Enable auto-attach so Chrome automatically notifies us when NEW targets attach/detach
			# This is the foundation of event-driven session management
			await self._cdp_client_root.send.Target.setAutoAttach(
				params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}
			)
			self.logger.debug('CDP client connected with auto-attach enabled')

			# Get browser targets from SessionManager (source of truth)
			# SessionManager has already discovered all targets via start_monitoring()
			page_targets_from_manager = self.session_manager.get_all_page_targets()

			# Check for chrome://newtab pages and redirect them to about:blank
			from browser_use.utils import is_new_tab_page

			for target in page_targets_from_manager:
				target_url = target.url
				if is_new_tab_page(target_url) and target_url != 'about:blank':
					target_id = target.target_id
					self.logger.debug(f'🔄 Redirecting {target_url} to about:blank for target {target_id}')
					try:
						# Use public API with focus=False to avoid changing focus during init
						session = await self.get_or_create_cdp_session(target_id, focus=False)
						await session.cdp_client.send.Page.navigate(params={'url': 'about:blank'}, session_id=session.session_id)
						# Update target url
						target.url = 'about:blank'
					except Exception as e:
						self.logger.warning(f'Failed to redirect {target_url}: {e}')

			# Ensure we have at least one page
			if not page_targets_from_manager:
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				self.logger.debug(f'📄 Created new blank page: {target_id}')
			else:
				target_id = page_targets_from_manager[0].target_id
				self.logger.debug(f'📄 Using existing page: {target_id}')

			# Set up initial focus using the public API
			# Note: get_or_create_cdp_session() will wait for attach event and set focus
			try:
				await self.get_or_create_cdp_session(target_id, focus=True)
				# agent_focus_target_id is now set by get_or_create_cdp_session
				self.logger.debug(f'📄 Agent focus set to {target_id[:8]}...')
			except ValueError as e:
				raise RuntimeError(f'Failed to get session for initial target {target_id}: {e}') from e

			# Note: Lifecycle monitoring is enabled automatically in SessionManager._handle_target_attached()
			# when targets attach, so no manual enablement needed!

			# Enable proxy authentication handling if configured
			await self._setup_proxy_auth()

			# Verify the target is working
			if self.agent_focus_target_id:
				target = self.session_manager.get_target(self.agent_focus_target_id)
				if target.title == 'Unknown title':
					self.logger.warning('Target created but title is unknown (may be normal for about:blank)')

			# Dispatch TabCreatedEvent for all initial tabs (so watchdogs can initialize)
			for idx, target in enumerate(page_targets_from_manager):
				target_url = target.url
				self.logger.debug(f'Dispatching TabCreatedEvent for initial tab {idx}: {target_url}')
				self.event_bus.dispatch(TabCreatedEvent(url=target_url, target_id=target.target_id))

			# Dispatch initial focus event
			if page_targets_from_manager:
				initial_url = page_targets_from_manager[0].url
				self.event_bus.dispatch(AgentFocusChangedEvent(target_id=page_targets_from_manager[0].target_id, url=initial_url))
				self.logger.debug(f'Initial agent focus set to tab 0: {initial_url}')

		except Exception as e:
			# Fatal error - browser is not usable without CDP connection
			self.logger.error(f'❌ FATAL: Failed to setup CDP connection: {e}')
			self.logger.error('❌ Browser cannot continue without CDP connection')

			# Clear SessionManager state
			if self.session_manager:
				try:
					await self.session_manager.clear()
					self.logger.debug('Cleared SessionManager state after initialization failure')
				except Exception as cleanup_error:
					self.logger.debug(f'Error clearing SessionManager: {cleanup_error}')

			# Close CDP client WebSocket and unregister handlers
			if self._cdp_client_root:
				try:
					await self._cdp_client_root.stop()  # Close WebSocket and unregister handlers
					self.logger.debug('Closed CDP client WebSocket after initialization failure')
				except Exception as cleanup_error:
					self.logger.debug(f'Error closing CDP client: {cleanup_error}')

			self.session_manager = None
			self._cdp_client_root = None
			self.agent_focus_target_id = None
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

			# Also enable on the focused target's session if available to ensure events are delivered
			try:
				if self.agent_focus_target_id:
					cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
					await cdp_session.cdp_client.send.Fetch.enable(
						params={'handleAuthRequests': True},
						session_id=cdp_session.session_id,
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
					create_task_with_error_handling(
						_respond(), name='auth_respond', logger_instance=self.logger, suppress_exceptions=True
					)
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
						create_task_with_error_handling(
							_default(), name='auth_default', logger_instance=self.logger, suppress_exceptions=True
						)

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

				create_task_with_error_handling(
					_continue(), name='request_continue', logger_instance=self.logger, suppress_exceptions=True
				)

			# Register event handler on root client
			try:
				self._cdp_client_root.register.Fetch.authRequired(_on_auth_required)
				self._cdp_client_root.register.Fetch.requestPaused(_on_request_paused)
				if self.agent_focus_target_id:
					cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
					cdp_session.cdp_client.register.Fetch.authRequired(_on_auth_required)
					cdp_session.cdp_client.register.Fetch.requestPaused(_on_request_paused)
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

				create_task_with_error_handling(
					_enable(), name='fetch_enable_attached', logger_instance=self.logger, suppress_exceptions=True
				)

			try:
				self._cdp_client_root.register.Target.attachedToTarget(_on_attached)
				self.logger.debug('Registered Target.attachedToTarget handler for Fetch.enable')
			except Exception as e:
				self.logger.debug(f'Failed to register attachedToTarget handler: {type(e).__name__}: {e}')

			# Ensure Fetch is enabled for the current focused target's session, too
			try:
				if self.agent_focus_target_id:
					# Use safe API with focus=False to avoid changing focus
					cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
					await cdp_session.cdp_client.send.Fetch.enable(
						params={'handleAuthRequests': True, 'patterns': [{'urlPattern': '*'}]},
						session_id=cdp_session.session_id,
					)
			except Exception as e:
				self.logger.debug(f'Fetch.enable on focused session failed: {type(e).__name__}: {e}')
		except Exception as e:
			self.logger.debug(f'Skipping proxy auth setup: {type(e).__name__}: {e}')

	async def get_tabs(self) -> list[TabInfo]:
		"""Get information about all open tabs using cached target data."""
		tabs = []

		# Safety check - return empty list if browser not connected yet
		if not self.session_manager:
			return tabs

		# Get all page targets from SessionManager
		page_targets = self.session_manager.get_all_page_targets()

		for i, target in enumerate(page_targets):
			target_id = target.target_id
			url = target.url
			title = target.title

			try:
				# Skip JS execution for chrome:// pages and new tab pages
				if is_new_tab_page(url) or url.startswith('chrome://'):
					# Use URL as title for chrome pages, or mark new tabs as unusable
					if is_new_tab_page(url):
						title = ''
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
					title = ''
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

	# endregion - ========== Helper Methods ==========

	# region - ========== ID Lookup Methods ==========
	async def get_current_target_info(self) -> TargetInfo | None:
		"""Get info about the current active target using cached session data."""
		if not self.agent_focus_target_id:
			return None

		target = self.session_manager.get_target(self.agent_focus_target_id)

		return {
			'targetId': target.target_id,
			'url': target.url,
			'title': target.title,
			'type': target.target_type,
			'attached': True,
			'canAccessOpener': False,
		}

	async def get_current_page_url(self) -> str:
		"""Get the URL of the current page."""
		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			return target.url
		return 'about:blank'

	async def get_current_page_title(self) -> str:
		"""Get the title of the current page."""
		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			return target.title
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

	# endregion - ========== ID Lookup Methods ==========

	# region - ========== DOM Helper Methods ==========

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

	async def get_dom_element_at_coordinates(self, x: int, y: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element at coordinates as EnhancedDOMTreeNode.

		First checks the cached selector_map for a matching element, then falls back
		to CDP DOM.describeNode if not found. This ensures safety checks (e.g., for
		<select> elements and file inputs) work correctly.

		Args:
			x: X coordinate relative to viewport
			y: Y coordinate relative to viewport

		Returns:
			EnhancedDOMTreeNode at the coordinates, or None if no element found
		"""
		from browser_use.dom.views import NodeType

		# Get current page to access CDP session
		page = await self.get_current_page()
		if page is None:
			raise RuntimeError('No active page found')

		# Get session ID for CDP call
		session_id = await page._ensure_session()

		try:
			# Call CDP DOM.getNodeForLocation to get backend_node_id
			result = await self.cdp_client.send.DOM.getNodeForLocation(
				params={
					'x': x,
					'y': y,
					'includeUserAgentShadowDOM': False,
					'ignorePointerEventsNone': False,
				},
				session_id=session_id,
			)

			backend_node_id = result.get('backendNodeId')
			if backend_node_id is None:
				self.logger.debug(f'No element found at coordinates ({x}, {y})')
				return None

			# Try to find element in cached selector_map (avoids extra CDP call)
			if self._cached_selector_map:
				for node in self._cached_selector_map.values():
					if node.backend_node_id == backend_node_id:
						self.logger.debug(f'Found element at ({x}, {y}) in cached selector_map')
						return node

			# Not in cache - fall back to CDP DOM.describeNode to get actual node info
			try:
				describe_result = await self.cdp_client.send.DOM.describeNode(
					params={'backendNodeId': backend_node_id},
					session_id=session_id,
				)
				node_info = describe_result.get('node', {})
				node_name = node_info.get('nodeName', '')

				# Parse attributes from flat list [key1, val1, key2, val2, ...] to dict
				attrs_list = node_info.get('attributes', [])
				attributes = {attrs_list[i]: attrs_list[i + 1] for i in range(0, len(attrs_list), 2)}

				return EnhancedDOMTreeNode(
					node_id=result.get('nodeId', 0),
					backend_node_id=backend_node_id,
					node_type=NodeType(node_info.get('nodeType', NodeType.ELEMENT_NODE.value)),
					node_name=node_name,
					node_value=node_info.get('nodeValue', '') or '',
					attributes=attributes,
					is_scrollable=None,
					frame_id=result.get('frameId'),
					session_id=session_id,
					target_id=self.agent_focus_target_id or '',
					content_document=None,
					shadow_root_type=None,
					shadow_roots=None,
					parent_node=None,
					children_nodes=None,
					ax_node=None,
					snapshot_node=None,
					is_visible=None,
					absolute_position=None,
				)
			except Exception as e:
				self.logger.debug(f'DOM.describeNode failed for backend_node_id={backend_node_id}: {e}')
				# Fall back to minimal node if describeNode fails
				return EnhancedDOMTreeNode(
					node_id=result.get('nodeId', 0),
					backend_node_id=backend_node_id,
					node_type=NodeType.ELEMENT_NODE,
					node_name='',
					node_value='',
					attributes={},
					is_scrollable=None,
					frame_id=result.get('frameId'),
					session_id=session_id,
					target_id=self.agent_focus_target_id or '',
					content_document=None,
					shadow_root_type=None,
					shadow_roots=None,
					parent_node=None,
					children_nodes=None,
					ax_node=None,
					snapshot_node=None,
					is_visible=None,
					absolute_position=None,
				)

		except Exception as e:
			self.logger.warning(f'Failed to get DOM element at coordinates ({x}, {y}): {e}')
			return None

	async def get_target_id_from_tab_id(self, tab_id: str) -> TargetID:
		"""Get the full-length TargetID from the truncated 4-char tab_id using SessionManager."""
		if not self.session_manager:
			raise RuntimeError('SessionManager not initialized')

		for full_target_id in self.session_manager.get_all_target_ids():
			if full_target_id.endswith(tab_id):
				if await self.session_manager.is_target_valid(full_target_id):
					return full_target_id
				# Stale target - Chrome should have sent detach event
				# If we're here, event listener will clean it up
				self.logger.debug(f'Found stale target {full_target_id}, skipping')

		raise ValueError(f'No TargetID found ending in tab_id=...{tab_id}')

	async def get_target_id_from_url(self, url: str) -> TargetID:
		"""Get the TargetID from a URL using SessionManager (source of truth)."""
		if not self.session_manager:
			raise RuntimeError('SessionManager not initialized')

		# Search in SessionManager targets (exact match first)
		for target_id, target in self.session_manager.get_all_targets().items():
			if target.target_type in ('page', 'tab') and target.url == url:
				return target_id

		# Still not found, try substring match as fallback
		for target_id, target in self.session_manager.get_all_targets().items():
			if target.target_type in ('page', 'tab') and url in target.url:
				return target_id

		raise ValueError(f'No TargetID found for url={url}')

	async def get_most_recently_opened_target_id(self) -> TargetID:
		"""Get the most recently opened target ID using SessionManager."""
		# Get all page targets from SessionManager
		page_targets = self.session_manager.get_all_page_targets()
		if not page_targets:
			raise RuntimeError('No page targets available')
		return page_targets[-1].target_id

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

	async def get_index_by_id(self, element_id: str) -> int | None:
		"""Find element index by its id attribute.

		Args:
			element_id: The id attribute value to search for

		Returns:
			Index of the element, or None if not found
		"""
		selector_map = await self.get_selector_map()
		for idx, element in selector_map.items():
			if element.attributes and element.attributes.get('id') == element_id:
				return idx
		return None

	async def get_index_by_class(self, class_name: str) -> int | None:
		"""Find element index by its class attribute (matches if class contains the given name).

		Args:
			class_name: The class name to search for

		Returns:
			Index of the first matching element, or None if not found
		"""
		selector_map = await self.get_selector_map()
		for idx, element in selector_map.items():
			if element.attributes:
				element_class = element.attributes.get('class', '')
				if class_name in element_class.split():
					return idx
		return None

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

	@observe_debug(ignore_input=True, ignore_output=True, name='get_element_coordinates')
	async def get_element_coordinates(self, backend_node_id: int, cdp_session: CDPSession) -> DOMRect | None:
		"""Get element coordinates for a backend node ID using multiple methods.

		This method tries DOM.getContentQuads first, then falls back to DOM.getBoxModel,
		and finally uses JavaScript getBoundingClientRect as a last resort.

		Args:
			backend_node_id: The backend node ID to get coordinates for
			cdp_session: The CDP session to use

		Returns:
			DOMRect with coordinates or None if element not found/no bounds
		"""
		session_id = cdp_session.session_id
		quads = []

		# Method 1: Try DOM.getContentQuads first (best for inline elements and complex layouts)
		try:
			content_quads_result = await cdp_session.cdp_client.send.DOM.getContentQuads(
				params={'backendNodeId': backend_node_id}, session_id=session_id
			)
			if 'quads' in content_quads_result and content_quads_result['quads']:
				quads = content_quads_result['quads']
				self.logger.debug(f'Got {len(quads)} quads from DOM.getContentQuads')
			else:
				self.logger.debug(f'No quads found from DOM.getContentQuads {content_quads_result}')
		except Exception as e:
			self.logger.debug(f'DOM.getContentQuads failed: {e}')

		# Method 2: Fall back to DOM.getBoxModel
		if not quads:
			try:
				box_model = await cdp_session.cdp_client.send.DOM.getBoxModel(
					params={'backendNodeId': backend_node_id}, session_id=session_id
				)
				if 'model' in box_model and 'content' in box_model['model']:
					content_quad = box_model['model']['content']
					if len(content_quad) >= 8:
						# Convert box model format to quad format
						quads = [
							[
								content_quad[0],
								content_quad[1],  # x1, y1
								content_quad[2],
								content_quad[3],  # x2, y2
								content_quad[4],
								content_quad[5],  # x3, y3
								content_quad[6],
								content_quad[7],  # x4, y4
							]
						]
						self.logger.debug('Got quad from DOM.getBoxModel')
			except Exception as e:
				self.logger.debug(f'DOM.getBoxModel failed: {e}')

		# Method 3: Fall back to JavaScript getBoundingClientRect
		if not quads:
			try:
				result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': backend_node_id},
					session_id=session_id,
				)
				if 'object' in result and 'objectId' in result['object']:
					object_id = result['object']['objectId']
					js_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'objectId': object_id,
							'functionDeclaration': """
							function() {
								const rect = this.getBoundingClientRect();
								return {
									x: rect.x,
									y: rect.y,
									width: rect.width,
									height: rect.height
								};
							}
							""",
							'returnByValue': True,
						},
						session_id=session_id,
					)
					if 'result' in js_result and 'value' in js_result['result']:
						rect_data = js_result['result']['value']
						if rect_data['width'] > 0 and rect_data['height'] > 0:
							return DOMRect(
								x=rect_data['x'], y=rect_data['y'], width=rect_data['width'], height=rect_data['height']
							)
			except Exception as e:
				self.logger.debug(f'JavaScript getBoundingClientRect failed: {e}')

		# Convert quads to bounding rectangle if we have them
		if quads:
			# Use the first quad (most relevant for the element)
			quad = quads[0]
			if len(quad) >= 8:
				# Calculate bounding rect from quad points
				x_coords = [quad[i] for i in range(0, 8, 2)]
				y_coords = [quad[i] for i in range(1, 8, 2)]

				min_x = min(x_coords)
				min_y = min(y_coords)
				max_x = max(x_coords)
				max_y = max(y_coords)

				width = max_x - min_x
				height = max_y - min_y

				if width > 0 and height > 0:
					return DOMRect(x=min_x, y=min_y, width=width, height=height)

		return None

	async def highlight_interaction_element(self, node: 'EnhancedDOMTreeNode') -> None:
		"""Temporarily highlight an element during interaction for user visibility.

		This creates a visual highlight on the browser that shows the user which element
		is being interacted with. The highlight automatically fades after the configured duration.

		Args:
			node: The DOM node to highlight with backend_node_id for coordinate lookup
		"""
		if not self.browser_profile.highlight_elements:
			return

		try:
			import json

			cdp_session = await self.get_or_create_cdp_session()

			# Get current coordinates
			rect = await self.get_element_coordinates(node.backend_node_id, cdp_session)

			color = self.browser_profile.interaction_highlight_color
			duration_ms = int(self.browser_profile.interaction_highlight_duration * 1000)

			if not rect:
				self.logger.debug(f'No coordinates found for backend node {node.backend_node_id}')
				return

			# Create animated corner brackets that start offset and animate inward
			script = f"""
			(function() {{
				const rect = {json.dumps({'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height})};
				const color = {json.dumps(color)};
				const duration = {duration_ms};

				// Scale corner size based on element dimensions to ensure gaps between corners
				const maxCornerSize = 20;
				const minCornerSize = 8;
				const cornerSize = Math.max(
					minCornerSize,
					Math.min(maxCornerSize, Math.min(rect.width, rect.height) * 0.35)
				);
				const borderWidth = 3;
				const startOffset = 10; // Starting offset in pixels
				const finalOffset = -3; // Final position slightly outside the element

				// Get current scroll position
				const scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0;
				const scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;

				// Create container for all corners
				const container = document.createElement('div');
				container.setAttribute('data-browser-use-interaction-highlight', 'true');
				container.style.cssText = `
					position: absolute;
					left: ${{rect.x + scrollX}}px;
					top: ${{rect.y + scrollY}}px;
					width: ${{rect.width}}px;
					height: ${{rect.height}}px;
					pointer-events: none;
					z-index: 2147483647;
				`;

				// Create 4 corner brackets
				const corners = [
					{{ pos: 'top-left', startX: -startOffset, startY: -startOffset, finalX: finalOffset, finalY: finalOffset }},
					{{ pos: 'top-right', startX: startOffset, startY: -startOffset, finalX: -finalOffset, finalY: finalOffset }},
					{{ pos: 'bottom-left', startX: -startOffset, startY: startOffset, finalX: finalOffset, finalY: -finalOffset }},
					{{ pos: 'bottom-right', startX: startOffset, startY: startOffset, finalX: -finalOffset, finalY: -finalOffset }}
				];

				corners.forEach(corner => {{
					const bracket = document.createElement('div');
					bracket.style.cssText = `
						position: absolute;
						width: ${{cornerSize}}px;
						height: ${{cornerSize}}px;
						pointer-events: none;
						transition: all 0.15s ease-out;
					`;

					// Position corners
					if (corner.pos === 'top-left') {{
						bracket.style.top = '0';
						bracket.style.left = '0';
						bracket.style.borderTop = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderLeft = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'top-right') {{
						bracket.style.top = '0';
						bracket.style.right = '0';
						bracket.style.borderTop = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderRight = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'bottom-left') {{
						bracket.style.bottom = '0';
						bracket.style.left = '0';
						bracket.style.borderBottom = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderLeft = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}} else if (corner.pos === 'bottom-right') {{
						bracket.style.bottom = '0';
						bracket.style.right = '0';
						bracket.style.borderBottom = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.borderRight = `${{borderWidth}}px solid ${{color}}`;
						bracket.style.transform = `translate(${{corner.startX}}px, ${{corner.startY}}px)`;
					}}

					container.appendChild(bracket);

					// Animate to final position slightly outside the element
					setTimeout(() => {{
						bracket.style.transform = `translate(${{corner.finalX}}px, ${{corner.finalY}}px)`;
					}}, 10);
				}});

				document.body.appendChild(container);

				// Auto-remove after duration
				setTimeout(() => {{
					container.style.opacity = '0';
					container.style.transition = 'opacity 0.3s ease-out';
					setTimeout(() => container.remove(), 300);
				}}, duration);

				return {{ created: true }};
			}})();
			"""

			# Fire and forget - don't wait for completion

			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

		except Exception as e:
			# Don't fail the action if highlighting fails
			self.logger.debug(f'Failed to highlight interaction element: {e}')

	async def highlight_coordinate_click(self, x: int, y: int) -> None:
		"""Temporarily highlight a coordinate click position for user visibility.

		This creates a visual highlight at the specified coordinates showing where
		the click action occurred. The highlight automatically fades after the configured duration.

		Args:
			x: Horizontal coordinate relative to viewport left edge
			y: Vertical coordinate relative to viewport top edge
		"""
		if not self.browser_profile.highlight_elements:
			return

		try:
			import json

			cdp_session = await self.get_or_create_cdp_session()

			color = self.browser_profile.interaction_highlight_color
			duration_ms = int(self.browser_profile.interaction_highlight_duration * 1000)

			# Create animated crosshair and circle at the click coordinates
			script = f"""
			(function() {{
				const x = {x};
				const y = {y};
				const color = {json.dumps(color)};
				const duration = {duration_ms};

				// Get current scroll position
				const scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0;
				const scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;

				// Create container
				const container = document.createElement('div');
				container.setAttribute('data-browser-use-coordinate-highlight', 'true');
				container.style.cssText = `
					position: absolute;
					left: ${{x + scrollX}}px;
					top: ${{y + scrollY}}px;
					width: 0;
					height: 0;
					pointer-events: none;
					z-index: 2147483647;
				`;

				// Create outer circle
				const outerCircle = document.createElement('div');
				outerCircle.style.cssText = `
					position: absolute;
					left: -15px;
					top: -15px;
					width: 30px;
					height: 30px;
					border: 3px solid ${{color}};
					border-radius: 50%;
					opacity: 0;
					transform: scale(0.3);
					transition: all 0.2s ease-out;
				`;
				container.appendChild(outerCircle);

				// Create center dot
				const centerDot = document.createElement('div');
				centerDot.style.cssText = `
					position: absolute;
					left: -4px;
					top: -4px;
					width: 8px;
					height: 8px;
					background: ${{color}};
					border-radius: 50%;
					opacity: 0;
					transform: scale(0);
					transition: all 0.15s ease-out;
				`;
				container.appendChild(centerDot);

				document.body.appendChild(container);

				// Animate in
				setTimeout(() => {{
					outerCircle.style.opacity = '0.8';
					outerCircle.style.transform = 'scale(1)';
					centerDot.style.opacity = '1';
					centerDot.style.transform = 'scale(1)';
				}}, 10);

				// Animate out and remove
				setTimeout(() => {{
					outerCircle.style.opacity = '0';
					outerCircle.style.transform = 'scale(1.5)';
					centerDot.style.opacity = '0';
					setTimeout(() => container.remove(), 300);
				}}, duration);

				return {{ created: true }};
			}})();
			"""

			# Fire and forget - don't wait for completion
			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

		except Exception as e:
			# Don't fail the action if highlighting fails
			self.logger.debug(f'Failed to highlight coordinate click: {e}')

	async def add_highlights(self, selector_map: dict[int, 'EnhancedDOMTreeNode']) -> None:
		"""Add visual highlights to the browser DOM for user visibility."""
		if not self.browser_profile.dom_highlight_elements or not selector_map:
			return

		try:
			import json

			# Convert selector_map to the format expected by the highlighting script
			elements_data = []
			for _, node in selector_map.items():
				# Get bounding box using absolute position (includes iframe translations) if available
				if node.absolute_position:
					# Use absolute position which includes iframe coordinate translations
					rect = node.absolute_position
					bbox = {'x': rect.x, 'y': rect.y, 'width': rect.width, 'height': rect.height}

					# Only include elements with valid bounding boxes
					if bbox and bbox.get('width', 0) > 0 and bbox.get('height', 0) > 0:
						element = {
							'x': bbox['x'],
							'y': bbox['y'],
							'width': bbox['width'],
							'height': bbox['height'],
							'element_name': node.node_name,
							'is_clickable': node.snapshot_node.is_clickable if node.snapshot_node else True,
							'is_scrollable': getattr(node, 'is_scrollable', False),
							'attributes': node.attributes or {},
							'frame_id': getattr(node, 'frame_id', None),
							'node_id': node.node_id,
							'backend_node_id': node.backend_node_id,
							'xpath': node.xpath,
							'text_content': node.get_all_children_text()[:50]
							if hasattr(node, 'get_all_children_text')
							else node.node_value[:50],
						}
						elements_data.append(element)

			if not elements_data:
				self.logger.debug('⚠️ No valid elements to highlight')
				return

			self.logger.debug(f'📍 Creating highlights for {len(elements_data)} elements')

			# Always remove existing highlights first
			await self.remove_highlights()

			# Add a small delay to ensure removal completes
			import asyncio

			await asyncio.sleep(0.05)

			# Get CDP session
			cdp_session = await self.get_or_create_cdp_session()

			# Create the proven highlighting script from v0.6.0 with fixed positioning
			script = f"""
			(function() {{
				// Interactive elements data
				const interactiveElements = {json.dumps(elements_data)};

				console.log('=== BROWSER-USE HIGHLIGHTING ===');
				console.log('Highlighting', interactiveElements.length, 'interactive elements');

				// Double-check: Remove any existing highlight container first
				const existingContainer = document.getElementById('browser-use-debug-highlights');
				if (existingContainer) {{
					console.log('⚠️ Found existing highlight container, removing it first');
					existingContainer.remove();
				}}

				// Also remove any stray highlight elements
				const strayHighlights = document.querySelectorAll('[data-browser-use-highlight]');
				if (strayHighlights.length > 0) {{
					console.log('⚠️ Found', strayHighlights.length, 'stray highlight elements, removing them');
					strayHighlights.forEach(el => el.remove());
				}}

				// Use maximum z-index for visibility
				const HIGHLIGHT_Z_INDEX = 2147483647;

				// Create container for all highlights - use FIXED positioning (key insight from v0.6.0)
				const container = document.createElement('div');
				container.id = 'browser-use-debug-highlights';
				container.setAttribute('data-browser-use-highlight', 'container');

				container.style.cssText = `
					position: absolute;
					top: 0;
					left: 0;
					width: 100vw;
					height: 100vh;
					pointer-events: none;
					z-index: ${{HIGHLIGHT_Z_INDEX}};
					overflow: visible;
					margin: 0;
					padding: 0;
					border: none;
					outline: none;
					box-shadow: none;
					background: none;
					font-family: inherit;
				`;

				// Helper function to create text elements safely
				function createTextElement(tag, text, styles) {{
					const element = document.createElement(tag);
					element.textContent = text;
					if (styles) element.style.cssText = styles;
					return element;
				}}

				// Add highlights for each element
				interactiveElements.forEach((element, index) => {{
					const highlight = document.createElement('div');
					highlight.setAttribute('data-browser-use-highlight', 'element');
					highlight.setAttribute('data-element-id', element.backend_node_id);
					highlight.style.cssText = `
						position: absolute;
						left: ${{element.x}}px;
						top: ${{element.y}}px;
						width: ${{element.width}}px;
						height: ${{element.height}}px;
						outline: 2px dashed #4a90e2;
						outline-offset: -2px;
						background: transparent;
						pointer-events: none;
						box-sizing: content-box;
						transition: outline 0.2s ease;
						margin: 0;
						padding: 0;
						border: none;
					`;

					// Enhanced label with backend node ID
					const label = createTextElement('div', element.backend_node_id, `
						position: absolute;
						top: -20px;
						left: 0;
						background-color: #4a90e2;
						color: white;
						padding: 2px 6px;
						font-size: 11px;
						font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
						font-weight: bold;
						border-radius: 3px;
						white-space: nowrap;
						z-index: ${{HIGHLIGHT_Z_INDEX + 1}};
						box-shadow: 0 2px 4px rgba(0,0,0,0.3);
						border: none;
						outline: none;
						margin: 0;
						line-height: 1.2;
					`);

					highlight.appendChild(label);
					container.appendChild(highlight);
				}});

				// Add container to document
				document.body.appendChild(container);

				console.log('Highlighting complete - added', interactiveElements.length, 'highlights');
				return {{ added: interactiveElements.length }};
			}})();
			"""

			# Execute the script
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'returnByValue': True}, session_id=cdp_session.session_id
			)

			# Log the result
			if result and 'result' in result and 'value' in result['result']:
				added_count = result['result']['value'].get('added', 0)
				self.logger.debug(f'Successfully added {added_count} highlight elements to browser DOM')
			else:
				self.logger.debug('Browser highlight injection completed')

		except Exception as e:
			self.logger.warning(f'Failed to add browser highlights: {e}')
			import traceback

			self.logger.debug(f'Browser highlight traceback: {traceback.format_exc()}')

	async def _close_extension_options_pages(self) -> None:
		"""Close any extension options/welcome pages that have opened."""
		try:
			# Get all page targets from SessionManager
			page_targets = self.session_manager.get_all_page_targets()

			for target in page_targets:
				target_url = target.url
				target_id = target.target_id

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

	async def send_demo_mode_log(self, message: str, level: str = 'info', metadata: dict[str, Any] | None = None) -> None:
		"""Send a message to the in-browser demo panel if enabled."""
		if not self.browser_profile.demo_mode:
			return
		demo = self.demo_mode
		if not demo:
			return
		try:
			await demo.send_log(message=message, level=level, metadata=metadata or {})
		except Exception as exc:
			self.logger.debug(f'[DemoMode] Failed to send log: {exc}')

	@property
	def downloaded_files(self) -> list[str]:
		"""Get list of files downloaded during this browser session.

		Returns:
			list[str]: List of absolute file paths to downloaded files in this session
		"""
		return self._downloaded_files.copy()

	# endregion - ========== Helper Methods ==========

	# region - ========== CDP-based replacements for browser_context operations ==========

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
		"""Get all browser pages/tabs using SessionManager (source of truth)."""
		# Safety check - return empty list if browser not connected yet
		if not self.session_manager:
			return []

		# Build TargetInfo dicts from SessionManager owned data (crystal clear ownership)
		result = []
		for target_id, target in self.session_manager.get_all_targets().items():
			# Create TargetInfo dict
			target_info: TargetInfo = {
				'targetId': target.target_id,
				'type': target.target_type,
				'title': target.title,
				'url': target.url,
				'attached': True,
				'canAccessOpener': False,
			}

			# Apply filters
			if self._is_valid_target(
				target_info,
				include_http=include_http,
				include_about=include_about,
				include_pages=include_pages,
				include_iframes=include_iframes,
				include_workers=include_workers,
				include_chrome=include_chrome,
				include_chrome_extensions=include_chrome_extensions,
				include_chrome_error=include_chrome_error,
			):
				result.append(target_info)

		return result

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
		cdp_session = await self.get_or_create_cdp_session(target_id=None)
		result = await asyncio.wait_for(
			cdp_session.cdp_client.send.Storage.getCookies(session_id=cdp_session.session_id), timeout=8.0
		)
		return result.get('cookies', [])

	async def _cdp_set_cookies(self, cookies: list[Cookie]) -> None:
		"""Set cookies using CDP Storage.setCookies."""
		if not self.agent_focus_target_id or not cookies:
			return

		cdp_session = await self.get_or_create_cdp_session(target_id=None)
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
		if not self.agent_focus_target_id:
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
			cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)
		elif self.agent_focus_target_id:
			# Use current focus - use safe API with focus=False to avoid changing focus
			try:
				cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
			except ValueError:
				self.logger.warning('Cannot set viewport: focused target has no sessions')
				return
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
		cdp_session = await self.get_or_create_cdp_session(target_id=None)

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
		# Use provided target_id or fall back to agent_focus_target_id

		assert self._cdp_client_root is not None, 'CDP client not initialized - browser may not be connected yet'
		assert self.agent_focus_target_id is not None, 'Agent focus not initialized - browser may not be connected yet'

		target_id_to_use = target_id or self.agent_focus_target_id
		cdp_session = await self.get_or_create_cdp_session(target_id_to_use, focus=True)

		# Use helper to navigate on the target
		await cdp_session.cdp_client.send.Page.navigate(params={'url': url}, session_id=cdp_session.session_id)

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
				if self.agent_focus_target_id and target_id != self.agent_focus_target_id:
					continue
				# Use the existing agent_focus target's session - use safe API with focus=False
				try:
					cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
				except ValueError:
					continue  # Skip if no session available
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
		"""Get CDP client for a specific DOM node based on its frame.

		IMPORTANT: backend_node_id is only valid in the session where the DOM was captured.
		We trust the node's session_id/frame_id/target_id instead of searching all sessions.
		"""

		# Strategy 1: If node has session_id, try to use that exact session (most specific)
		if node.session_id and self.session_manager:
			try:
				# Find the CDP session by session_id from SessionManager
				cdp_session = self.session_manager.get_session(node.session_id)
				if cdp_session:
					# Get target to log URL
					target = self.session_manager.get_target(cdp_session.target_id)
					self.logger.debug(f'✅ Using session from node.session_id for node {node.backend_node_id}: {target.url}')
					return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session by session_id {node.session_id}: {e}')

		# Strategy 2: If node has frame_id, use that frame's session
		if node.frame_id:
			try:
				cdp_session = await self.cdp_client_for_frame(node.frame_id)
				target = self.session_manager.get_target(cdp_session.target_id)
				self.logger.debug(f'✅ Using session from node.frame_id for node {node.backend_node_id}: {target.url}')
				return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session for frame {node.frame_id}: {e}')

		# Strategy 3: If node has target_id, use that target's session
		if node.target_id:
			try:
				cdp_session = await self.get_or_create_cdp_session(target_id=node.target_id, focus=False)
				target = self.session_manager.get_target(cdp_session.target_id)
				self.logger.debug(f'✅ Using session from node.target_id for node {node.backend_node_id}: {target.url}')
				return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session for target {node.target_id}: {e}')

		# Strategy 4: Fallback to agent_focus_target_id (the page where agent is currently working)
		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			try:
				# Use safe API with focus=False to avoid changing focus
				cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
				if target:
					self.logger.warning(
						f'⚠️ Node {node.backend_node_id} has no session/frame/target info. Using agent_focus session: {target.url}'
					)
				return cdp_session
			except ValueError:
				pass  # Fall through to last resort

		# Last resort: use main session
		self.logger.error(f'❌ No session info for node {node.backend_node_id} and no agent_focus available. Using main session.')
		return await self.get_or_create_cdp_session()

	@observe_debug(ignore_input=True, ignore_output=True, name='take_screenshot')
	async def take_screenshot(
		self,
		path: str | None = None,
		full_page: bool = False,
		format: str = 'png',
		quality: int | None = None,
		clip: dict | None = None,
	) -> bytes:
		"""Take a screenshot using CDP.

		Args:
			path: Optional file path to save screenshot
			full_page: Capture entire scrollable page beyond viewport
			format: Image format ('png', 'jpeg', 'webp')
			quality: Quality 0-100 for JPEG format
			clip: Region to capture {'x': int, 'y': int, 'width': int, 'height': int}

		Returns:
			Screenshot data as bytes
		"""
		import base64

		from cdp_use.cdp.page import CaptureScreenshotParameters

		cdp_session = await self.get_or_create_cdp_session()

		# Build parameters dict explicitly to satisfy TypedDict expectations
		params: CaptureScreenshotParameters = {
			'format': format,
			'captureBeyondViewport': full_page,
		}

		if quality is not None and format == 'jpeg':
			params['quality'] = quality

		if clip:
			params['clip'] = {
				'x': clip['x'],
				'y': clip['y'],
				'width': clip['width'],
				'height': clip['height'],
				'scale': 1,
			}

		params = CaptureScreenshotParameters(**params)

		result = await cdp_session.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp_session.session_id)

		if not result or 'data' not in result:
			raise Exception('Screenshot failed - no data returned')

		screenshot_data = base64.b64decode(result['data'])

		if path:
			Path(path).write_bytes(screenshot_data)

		return screenshot_data

	async def screenshot_element(
		self,
		selector: str,
		path: str | None = None,
		format: str = 'png',
		quality: int | None = None,
	) -> bytes:
		"""Take a screenshot of a specific element.

		Args:
			selector: CSS selector for the element
			path: Optional file path to save screenshot
			format: Image format ('png', 'jpeg', 'webp')
			quality: Quality 0-100 for JPEG format

		Returns:
			Screenshot data as bytes
		"""

		bounds = await self._get_element_bounds(selector)
		if not bounds:
			raise ValueError(f"Element '{selector}' not found or has no bounds")

		return await self.take_screenshot(
			path=path,
			format=format,
			quality=quality,
			clip=bounds,
		)

	async def _get_element_bounds(self, selector: str) -> dict | None:
		"""Get element bounding box using CDP."""

		cdp_session = await self.get_or_create_cdp_session()

		# Get document
		doc = await cdp_session.cdp_client.send.DOM.getDocument(params={'depth': 1}, session_id=cdp_session.session_id)

		# Query selector
		node_result = await cdp_session.cdp_client.send.DOM.querySelector(
			params={'nodeId': doc['root']['nodeId'], 'selector': selector}, session_id=cdp_session.session_id
		)

		node_id = node_result.get('nodeId')
		if not node_id:
			return None

		# Get bounding box
		box_result = await cdp_session.cdp_client.send.DOM.getBoxModel(
			params={'nodeId': node_id}, session_id=cdp_session.session_id
		)

		box_model = box_result.get('model')
		if not box_model:
			return None

		content = box_model['content']
		return {
			'x': min(content[0], content[2], content[4], content[6]),
			'y': min(content[1], content[3], content[5], content[7]),
			'width': max(content[0], content[2], content[4], content[6]) - min(content[0], content[2], content[4], content[6]),
			'height': max(content[1], content[3], content[5], content[7]) - min(content[1], content[3], content[5], content[7]),
		}
