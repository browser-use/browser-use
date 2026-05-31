"""Event-driven browser session with backwards compatibility."""

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast, overload
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import httpx
from bubus import EventBus
from cdp_use import CDPClient
from cdp_use.cdp.fetch import AuthRequiredEvent, RequestPausedEvent
from cdp_use.cdp.target import SessionID, TargetID
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from uuid_extensions import uuid7str

from browser_use.browser._cdp_timeout import TimeoutWrappedCDPClient
from browser_use.browser.cloud.cloud import CloudBrowserAuthError, CloudBrowserClient, CloudBrowserError

# CDP logging is now handled by setup_logging() in logging_config.py
# It automatically sets CDP logs to the same level as browser_use logs
from browser_use.browser.cloud.views import CloudBrowserParams, CreateBrowserRequest, ProxyCountryCode

# Sentinel to distinguish "not passed" from "explicitly None" for proxy params.
# When a user passes proxy_country_code=None, they mean "disable the proxy".
# When they don't pass it at all, the server applies its default (US proxy).
_UNSET: Any = object()
from browser_use.browser.events import (
	AgentFocusChangedEvent,
	BrowserConnectedEvent,
	BrowserErrorEvent,
	BrowserLaunchEvent,
	BrowserLaunchResult,
	BrowserReconnectedEvent,
	BrowserReconnectingEvent,
	BrowserStartEvent,
	TabCreatedEvent,
)
from browser_use.browser.profile import BrowserProfile, ProxySettings
from browser_use.browser.session_actor_api import BrowserSessionActorAPIMixin
from browser_use.browser.session_cdp import BrowserSessionCDPMixin
from browser_use.browser.session_dom import BrowserSessionDOMMixin
from browser_use.browser.session_frames import BrowserSessionFramesMixin
from browser_use.browser.session_highlights import BrowserSessionHighlightMixin
from browser_use.browser.session_lifecycle import BrowserSessionLifecycleMixin
from browser_use.browser.session_navigation import BrowserSessionNavigationMixin
from browser_use.browser.session_screenshots import BrowserSessionScreenshotMixin
from browser_use.browser.session_state import BrowserSessionStateMixin
from browser_use.browser.session_tab_events import BrowserSessionTabEventsMixin
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import EnhancedDOMTreeNode
from browser_use.observability import observe_debug
from browser_use.utils import create_task_with_error_handling

if TYPE_CHECKING:
	from browser_use.browser.demo_mode import DemoMode

DEFAULT_BROWSER_PROFILE = BrowserProfile()


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


class BrowserSession(
	BrowserSessionActorAPIMixin,
	BrowserSessionCDPMixin,
	BrowserSessionDOMMixin,
	BrowserSessionFramesMixin,
	BrowserSessionHighlightMixin,
	BrowserSessionLifecycleMixin,
	BrowserSessionNavigationMixin,
	BrowserSessionScreenshotMixin,
	BrowserSessionTabEventsMixin,
	BrowserSessionStateMixin,
	BaseModel,
):
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
		captcha_solver: bool | None = None,
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
		captcha_solver: bool | None = None,
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
		cloud_proxy_country_code: ProxyCountryCode | None = _UNSET,  # type: ignore[assignment]
		cloud_timeout: int | None = None,
		# Backward compatibility aliases for cloud params
		profile_id: UUID | str | None = None,
		proxy_country_code: ProxyCountryCode | None = _UNSET,  # type: ignore[assignment]
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
		captcha_solver: bool | None = None,
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
		# Also filter _UNSET sentinel values (used for proxy params)
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
			and v is not _UNSET
		}

		# Handle backward compatibility: prefer cloud_* params over old names.
		# _UNSET means "not passed" while None means "explicitly disable proxy".
		final_profile_id = cloud_profile_id if cloud_profile_id is not None else profile_id
		final_proxy_country_code = (
			cloud_proxy_country_code
			if cloud_proxy_country_code is not _UNSET
			else proxy_country_code
			if proxy_country_code is not _UNSET
			else _UNSET
		)
		final_timeout = cloud_timeout if cloud_timeout is not None else timeout

		# If any cloud params are provided, create cloud_browser_params.
		# Use "is not _UNSET" for proxy so that explicit None (disable proxy) is respected.
		if final_profile_id is not None or final_proxy_country_code is not _UNSET or final_timeout is not None:
			cloud_kwargs: dict[str, Any] = {}
			if final_profile_id is not None:
				cloud_kwargs['cloud_profile_id'] = final_profile_id
			if final_proxy_country_code is not _UNSET:
				cloud_kwargs['cloud_proxy_country_code'] = final_proxy_country_code
			if final_timeout is not None:
				cloud_kwargs['cloud_timeout'] = final_timeout
			cloud_params = CreateBrowserRequest(**cloud_kwargs)
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

	@classmethod
	def from_system_chrome(cls, profile_directory: str | None = None, **kwargs: Any) -> Self:
		"""Create a BrowserSession using system's Chrome installation and profile"""
		from browser_use.skill_cli.utils import find_chrome_executable, get_chrome_profile_path, list_chrome_profiles

		executable_path = find_chrome_executable()
		if executable_path is None:
			raise RuntimeError(
				'Chrome not found. Please install Chrome or use Browser() with explicit executable_path.\n'
				'Expected locations:\n'
				'  macOS: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n'
				'  Linux: /usr/bin/google-chrome or /usr/bin/chromium\n'
				'  Windows: C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
			)

		user_data_dir = get_chrome_profile_path(None)
		if user_data_dir is None:
			raise RuntimeError(
				'Could not detect Chrome profile directory for your platform.\n'
				'Expected locations:\n'
				'  macOS: ~/Library/Application Support/Google/Chrome\n'
				'  Linux: ~/.config/google-chrome or ~/.config/chromium\n'
				'  Windows: %LocalAppData%\\Google\\Chrome\\User Data'
			)

		# Auto-select profile if not specified
		profiles = list_chrome_profiles()
		if profile_directory is None:
			if profiles:
				# Use first available profile
				profile_directory = profiles[0]['directory']
				logging.getLogger('browser_use').info(
					f'Auto-selected Chrome profile: {profiles[0]["name"]} ({profile_directory})'
				)
			else:
				profile_directory = 'Default'

		return cls(
			executable_path=executable_path,
			user_data_dir=user_data_dir,
			profile_directory=profile_directory,
			**kwargs,
		)

	@classmethod
	def list_chrome_profiles(cls) -> list[dict[str, str]]:
		"""List available Chrome profiles on the system"""
		from browser_use.skill_cli.utils import list_chrome_profiles

		return list_chrome_profiles()

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
	_captcha_watchdog: Any | None = PrivateAttr(default=None)
	_watchdogs_attached: bool = PrivateAttr(default=False)

	_cloud_browser_client: CloudBrowserClient = PrivateAttr(default_factory=lambda: CloudBrowserClient())
	_demo_mode: 'DemoMode | None' = PrivateAttr(default=None)

	# WebSocket reconnection state
	# Max wait = attempts * timeout_per_attempt + sum(delays) + small buffer
	# Default: 3 * 15s + (1+2+4)s + 2s = 54s
	RECONNECT_WAIT_TIMEOUT: float = 54.0
	_reconnecting: bool = PrivateAttr(default=False)
	_reconnect_event: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
	_reconnect_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
	_reconnect_task: asyncio.Task | None = PrivateAttr(default=None)
	_intentional_stop: bool = PrivateAttr(default=False)

	_logger: Any = PrivateAttr(default=None)

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
						raise
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
					# Global timeout prevents connect() from hanging indefinitely on
					# slow/broken WebSocket connections (common on Lambda → remote browser)
					try:
						await asyncio.wait_for(self.connect(cdp_url=self.cdp_url), timeout=15.0)
					except TimeoutError:
						# Timeout cancels connect() via CancelledError, which bypasses
						# connect()'s `except Exception` cleanup (CancelledError is BaseException).
						# Clean up the partially-initialized client so future start attempts
						# don't skip reconnection due to _cdp_client_root being non-None.
						cdp_client = cast(CDPClient | None, self._cdp_client_root)
						if cdp_client is not None:
							try:
								await cdp_client.stop()
							except Exception:
								pass
							self._cdp_client_root = None
						manager = self.session_manager
						if manager is not None:
							try:
								await manager.clear()
							except Exception:
								pass
							self.session_manager = None
						self.agent_focus_target_id = None
						raise RuntimeError(
							f'connect() timed out after 15s — CDP connection to {self.cdp_url} is too slow or unresponsive'
						)
					assert self.cdp_client is not None

					# Notify that browser is connected (single place)
					# Ensure BrowserConnected handlers (storage_state restore) complete before
					# start() returns so cookies/storage are applied before navigation.
					await self.event_bus.dispatch(BrowserConnectedEvent(cdp_url=self.cdp_url))

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
			if self.is_local and not isinstance(e, (CloudBrowserAuthError, CloudBrowserError)):
				self.logger.warning(
					'Local browser failed to start. Cloud browsers require no local install and work out of the box.\n'
					'         Try: Browser(use_cloud=True)  |  Get an API key: https://cloud.browser-use.com?utm_source=oss&utm_medium=browser_launch_failure'
				)
			raise

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

		# Resume if waiting for debugger (non-essential, don't let it block connect)
		if focus:
			try:
				await asyncio.wait_for(
					session.cdp_client.send.Runtime.runIfWaitingForDebugger(session_id=session.session_id),
					timeout=3.0,
				)
			except Exception:
				pass  # May fail if not waiting, or timeout — either is fine

		return session

	async def set_extra_headers(self, headers: dict[str, str], target_id: TargetID | None = None) -> None:
		"""Set extra HTTP headers using CDP Network.setExtraHTTPHeaders.

		These headers will be sent with every HTTP request made by the target.
		Network domain must be enabled first (done automatically for page targets
		in SessionManager._enable_page_monitoring).

		Args:
			headers: Dictionary of header name -> value pairs to inject into every request.
			target_id: Target to set headers on. Defaults to the current agent focus target.
		"""
		if target_id is None:
			if not self.agent_focus_target_id:
				return
			target_id = self.agent_focus_target_id

		cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)
		# Ensure Network domain is enabled (idempotent - safe to call multiple times)
		await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)
		await cdp_session.cdp_client.send.Network.setExtraHTTPHeaders(
			params={'headers': cast(Any, headers)}, session_id=cdp_session.session_id
		)

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

		dom_watchdog = self._dom_watchdog
		if dom_watchdog is None:
			await self.attach_all_watchdogs()
			dom_watchdog = self._dom_watchdog
		if dom_watchdog is None:
			raise RuntimeError('DOM state service is not attached to this browser session.')

		result = await dom_watchdog.get_browser_state_summary(
			include_dom=True,
			include_screenshot=include_screenshot,
			include_recent_events=include_recent_events,
		)
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
		from browser_use.browser.watchdogs.attachment import attach_all_watchdogs

		await attach_all_watchdogs(self)

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
			# Default httpx timeout is 5s which can race the global wait_for(connect(), 15s).
			# Use 30s as a safety net for direct connect() callers; the wait_for is the real deadline.
			# For localhost/127.0.0.1, disable trust_env to prevent proxy env vars (HTTP_PROXY, HTTPS_PROXY)
			# from routing local requests through a proxy, which causes 502 errors on Windows.
			# Remote CDP URLs should still respect proxy settings.
			is_localhost = parsed_url.hostname in ('localhost', '127.0.0.1', '::1')
			async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=not is_localhost) as client:
				headers = dict(self.browser_profile.headers or {})
				from browser_use.utils import get_browser_use_version

				headers.setdefault('User-Agent', f'browser-use/{get_browser_use_version()}')
				version_info = await client.get(url, headers=headers)
				self.logger.debug(f'Raw version info: {str(version_info)}')
				self.browser_profile.cdp_url = version_info.json()['webSocketDebuggerUrl']

		assert self.cdp_url is not None, 'CDP URL is None.'

		browser_location = 'local browser' if self.is_local else 'remote browser'
		self.logger.debug(f'🌎 Connecting to existing chromium-based browser via CDP: {self.cdp_url} -> ({browser_location})')

		try:
			# Create and store the CDP client for direct CDP communication
			headers = dict(getattr(self.browser_profile, 'headers', None) or {})
			if not self.is_local:
				from browser_use.utils import get_browser_use_version

				headers.setdefault('User-Agent', f'browser-use/{get_browser_use_version()}')
			self._cdp_client_root = TimeoutWrappedCDPClient(
				self.cdp_url,
				additional_headers=headers or None,
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

			# Check for chrome://newtab pages and redirect them to about:blank (in parallel)
			from browser_use.utils import is_new_tab_page

			async def _redirect_newtab(target):
				target_url = target.url
				target_id = target.target_id
				self.logger.debug(f'🔄 Redirecting {target_url} to about:blank for target {target_id}')
				try:
					session = await self.get_or_create_cdp_session(target_id, focus=False)
					await session.cdp_client.send.Page.navigate(params={'url': 'about:blank'}, session_id=session.session_id)
					target.url = 'about:blank'
				except Exception as e:
					self.logger.warning(f'Failed to redirect {target_url}: {e}')

			redirect_tasks = [
				_redirect_newtab(target)
				for target in page_targets_from_manager
				if is_new_tab_page(target.url) and target.url != 'about:blank'
			]
			if redirect_tasks:
				await asyncio.gather(*redirect_tasks, return_exceptions=True)

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

			# Attach WS drop detection callback for auto-reconnection
			self._intentional_stop = False
			self._attach_ws_drop_callback()

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

	async def reconnect(self) -> None:
		"""Re-establish the CDP WebSocket connection to an already-running browser.

		This is a lightweight reconnection that:
		1. Stops the old CDPClient (WS already dead, just clean state)
		2. Clears SessionManager (all CDP sessions are invalid post-disconnect)
		3. Creates a new CDPClient with the same cdp_url
		4. Re-initializes SessionManager and re-enables autoAttach
		5. Re-discovers page targets and restores agent focus
		6. Re-enables proxy auth if configured
		"""
		assert self.cdp_url, 'Cannot reconnect without a CDP URL'

		old_focus_target_id = self.agent_focus_target_id

		# 1. Stop old CDPClient (WS is already dead, this just cleans internal state)
		if self._cdp_client_root:
			try:
				await self._cdp_client_root.stop()
			except Exception as e:
				self.logger.debug(f'Error stopping old CDP client during reconnect: {e}')
			self._cdp_client_root = None

		# 2. Clear SessionManager (all sessions are stale)
		if self.session_manager:
			try:
				await self.session_manager.clear()
			except Exception as e:
				self.logger.debug(f'Error clearing SessionManager during reconnect: {e}')
			self.session_manager = None

		self.agent_focus_target_id = None

		# 3. Create new CDPClient with the same cdp_url
		headers = dict(getattr(self.browser_profile, 'headers', None) or {})
		if not self.is_local:
			from browser_use.utils import get_browser_use_version

			headers.setdefault('User-Agent', f'browser-use/{get_browser_use_version()}')
		self._cdp_client_root = TimeoutWrappedCDPClient(
			self.cdp_url,
			additional_headers=headers or None,
			max_ws_frame_size=200 * 1024 * 1024,
		)
		await self._cdp_client_root.start()

		# 4. Re-initialize SessionManager
		from browser_use.browser.session_manager import SessionManager

		self.session_manager = SessionManager(self)
		await self.session_manager.start_monitoring()

		# 5. Re-enable autoAttach
		await self._cdp_client_root.send.Target.setAutoAttach(
			params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}
		)

		# 6. Re-discover page targets and restore focus
		page_targets = self.session_manager.get_all_page_targets()

		# Prefer the old focus target if it still exists
		restored = False
		if old_focus_target_id:
			for target in page_targets:
				if target.target_id == old_focus_target_id:
					await self.get_or_create_cdp_session(old_focus_target_id, focus=True)
					restored = True
					self.logger.debug(f'🔄 Restored agent focus to previous target {old_focus_target_id[:8]}...')
					break

		if not restored:
			if page_targets:
				fallback_id = page_targets[0].target_id
				await self.get_or_create_cdp_session(fallback_id, focus=True)
				self.logger.debug(f'🔄 Agent focus set to fallback target {fallback_id[:8]}...')
			else:
				# No pages exist — create one
				new_target = await self._cdp_client_root.send.Target.createTarget(params={'url': 'about:blank'})
				target_id = new_target['targetId']
				await self.get_or_create_cdp_session(target_id, focus=True)
				self.logger.debug(f'🔄 Created new blank page during reconnect: {target_id[:8]}...')

		# 7. Re-enable proxy auth if configured
		await self._setup_proxy_auth()

		# 8. Attach the WS drop detection callback to the new client
		self._attach_ws_drop_callback()

	async def _auto_reconnect(self, max_attempts: int = 3) -> None:
		"""Attempt to reconnect with exponential backoff.

		Dispatches BrowserReconnectingEvent before each attempt and
		BrowserReconnectedEvent on success.
		"""
		async with self._reconnect_lock:
			if self._reconnecting:
				return  # already in progress from another caller
			self._reconnecting = True
			self._reconnect_event.clear()

		start_time = time.time()
		delays = [1.0, 2.0, 4.0]

		try:
			for attempt in range(1, max_attempts + 1):
				self.event_bus.dispatch(
					BrowserReconnectingEvent(
						cdp_url=self.cdp_url or '',
						attempt=attempt,
						max_attempts=max_attempts,
					)
				)
				self.logger.warning(f'🔄 WebSocket reconnection attempt {attempt}/{max_attempts}...')

				try:
					await asyncio.wait_for(self.reconnect(), timeout=15.0)
					# Success
					downtime = time.time() - start_time
					self.event_bus.dispatch(
						BrowserReconnectedEvent(
							cdp_url=self.cdp_url or '',
							attempt=attempt,
							downtime_seconds=downtime,
						)
					)
					self.logger.info(f'🔄 WebSocket reconnected after {downtime:.1f}s (attempt {attempt})')
					return
				except Exception as e:
					self.logger.warning(f'🔄 Reconnection attempt {attempt} failed: {type(e).__name__}: {e}')
					if attempt < max_attempts:
						delay = delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1]
						await asyncio.sleep(delay)

			# All attempts exhausted
			self.logger.error(f'🔄 All {max_attempts} reconnection attempts failed')
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='ReconnectionFailed',
					message=f'Failed to reconnect after {max_attempts} attempts ({time.time() - start_time:.1f}s)',
					details={'cdp_url': self.cdp_url or '', 'max_attempts': max_attempts},
				)
			)
		finally:
			self._reconnecting = False
			self._reconnect_event.set()  # wake up all waiters regardless of outcome

	def _attach_ws_drop_callback(self) -> None:
		"""Attach a done callback to the CDPClient's message handler task to detect WS drops."""
		if not self._cdp_client_root or not hasattr(self._cdp_client_root, '_message_handler_task'):
			return

		task = self._cdp_client_root._message_handler_task
		if task is None or task.done():
			return

		def _on_message_handler_done(fut: asyncio.Future) -> None:
			# Guard: skip if intentionally stopped, already reconnecting, or no cdp_url
			if self._intentional_stop or self._reconnecting or not self.cdp_url:
				return

			# The message handler task exiting means the WS connection dropped
			exc = fut.exception() if not fut.cancelled() else None
			self.logger.warning(
				f'🔌 CDP WebSocket message handler exited unexpectedly'
				f'{f": {type(exc).__name__}: {exc}" if exc else " (connection closed)"}'
			)

			# Fire auto-reconnect as an asyncio task
			try:
				loop = asyncio.get_running_loop()
				self._reconnect_task = loop.create_task(self._auto_reconnect())
			except RuntimeError:
				# No running event loop — can't reconnect
				self.logger.error('🔌 No event loop available for auto-reconnect')

		task.add_done_callback(_on_message_handler_done)

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
