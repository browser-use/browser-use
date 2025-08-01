"""Event-driven browser session with backwards compatibility."""

import asyncio
import base64
import json
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from bubus import EventBus
from playwright.async_api import Browser, BrowserContext, FloatRect, Page, Playwright, async_playwright
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from browser_use.browser.events import (
	BrowserErrorEvent,
	BrowserStartedEvent,
	BrowserStateRequestEvent,
	BrowserStateResponseEvent,
	BrowserStoppedEvent,
	ClickElementEvent,
	CloseTabEvent,
	ExecuteJavaScriptEvent,
	FileDownloadedEvent,
	LoadStorageStateEvent,
	NavigateToUrlEvent,
	NavigationCompleteEvent,
	SaveStorageStateEvent,
	ScreenshotRequestEvent,
	ScreenshotResponseEvent,
	ScrollEvent,
	StartBrowserEvent,
	StopBrowserEvent,
	SwitchTabEvent,
	TabClosedEvent,
	TabCreatedEvent,
	TabsInfoRequestEvent,
	TabsInfoResponseEvent,
	TypeTextEvent,
)
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.views import TabInfo
from browser_use.utils import logger

if TYPE_CHECKING:
	pass

# Default browser profile for convenience
DEFAULT_BROWSER_PROFILE = BrowserProfile()

# Common new tab page URLs
NEW_TAB_URLS = ['about:blank', 'chrome://new-tab-page/', 'chrome://newtab/']


class BrowserSession(BaseModel):
	"""Event-driven browser session with backwards compatibility.

	This class provides a 2-layer architecture:
	- High-level event handling for agents/controllers
	- Direct CDP/Playwright calls for browser operations

	Supports both event-driven and imperative calling styles.
	"""

	model_config = ConfigDict(
		arbitrary_types_allowed=True,
		validate_assignment=True,
		extra='forbid',
	)

	# Core configuration
	browser_profile: BrowserProfile = Field(default_factory=lambda: DEFAULT_BROWSER_PROFILE)
	id: str = Field(default_factory=lambda: uuid7str())

	# Connection info (for backwards compatibility)
	cdp_url: str | None = None
	is_local: bool = Field(default=True)

	# Event bus
	event_bus: EventBus = Field(default_factory=EventBus)

	# Browser state
	_playwright: Playwright | None = PrivateAttr(default=None)
	_browser: Browser | None = PrivateAttr(default=None)
	_browser_context: BrowserContext | None = PrivateAttr(default=None)

	# Local browser state (only used when cdp_url is None)
	_subprocess: Any = PrivateAttr(default=None)  # psutil.Process
	_owns_browser_resources: bool = PrivateAttr(default=True)

	# PDF handling
	_auto_download_pdfs: bool = PrivateAttr(default=True)

	# Watchdogs
	_crash_watchdog: Any = PrivateAttr(default=None)
	_downloads_watchdog: Any = PrivateAttr(default=None)
	_aboutblank_watchdog: Any = PrivateAttr(default=None)
	_navigation_watchdog: Any = PrivateAttr(default=None)
	_storage_state_watchdog: Any = PrivateAttr(default=None)

	# Navigation tracking now handled by watchdogs

	# Cached browser state for synchronous access
	_cached_browser_state_summary: Any = PrivateAttr(default=None)
	_logger: Any = PrivateAttr(default=None)

	@property
	def logger(self) -> Any:
		"""Get instance-specific logger with session ID in the name"""
		if (
			self._logger is None or self._browser_context is None
		):  # keep updating the name pre-init because our id and str(self) can change
			import logging

			self._logger = logging.getLogger(f'browser_use.{self}')
		return self._logger

	def __init__(
		self,
		browser_profile: BrowserProfile | None = None,
		cdp_url: str | None = None,
		browser_pid: int | None = None,
		**kwargs: Any,
	):
		"""Initialize a browser session.

		Args:
			browser_profile: Browser configuration profile (defaults to DEFAULT_BROWSER_PROFILE)
			cdp_url: CDP URL for connecting to existing browser
			browser_pid: Process ID of existing browser (DEPRECATED)
			**kwargs: Additional arguments
		"""

		# Use default profile if none provided
		if browser_profile is None:
			browser_profile = DEFAULT_BROWSER_PROFILE

		# Initialize base model
		super().__init__(
			browser_profile=browser_profile,
			cdp_url=cdp_url,
			**kwargs,
		)

		# Create event bus with unique name
		self.event_bus = EventBus(name=f'BrowserSession_{self.id[-4:]}')

		# Set is_local based on cdp_url
		self.is_local = cdp_url is None

		# Handle deprecated browser_pid
		if browser_pid is not None:
			warnings.warn(
				'Passing browser_pid to BrowserSession is deprecated. Use from_existing_pid() class method instead.',
				DeprecationWarning,
				stacklevel=2,
			)
			if not cdp_url:
				raise ValueError('cdp_url is required when browser_pid is provided')

			# Convert PID to psutil.Process
			try:
				import psutil

				self._subprocess = psutil.Process(browser_pid)
				self._owns_browser_resources = False
			except ImportError:
				raise ImportError('psutil is required for process management')
		else:
			# Set ownership based on whether we're connecting to existing browser
			self._owns_browser_resources = cdp_url is None

		# Register event handlers
		self._register_handlers()

	@classmethod
	def from_existing_pid(
		cls,
		browser_profile: BrowserProfile,
		pid: int,
		cdp_url: str,
		**kwargs: Any,
	) -> Self:
		"""Create a session from an existing browser process.

		Args:
			browser_profile: Browser configuration profile
			pid: Process ID of the existing browser
			cdp_url: CDP URL to connect to the browser
			**kwargs: Additional arguments
		"""
		session = cls(
			browser_profile=browser_profile,
			cdp_url=cdp_url,
			**kwargs,
		)
		# Convert PID to psutil.Process
		try:
			import psutil

			session._subprocess = psutil.Process(pid)
			session._owns_browser_resources = False
		except ImportError:
			raise ImportError('psutil is required for process management')
		return session

	def _register_handlers(self) -> None:
		"""Register event handlers for browser control."""
		# Browser lifecycle
		self.event_bus.on(StartBrowserEvent, self.on_StartBrowserEvent)
		self.event_bus.on(StopBrowserEvent, self.on_StopBrowserEvent)

		# Navigation is handled by NavigationWatchdog
		# Interaction
		self.event_bus.on(ClickElementEvent, self.on_ClickElementEvent)
		self.event_bus.on(TypeTextEvent, self.on_TypeTextEvent)
		self.event_bus.on(ScrollEvent, self.on_ScrollEvent)

		# Tab management - handled by watchdogs
		self.event_bus.on(CloseTabEvent, self.on_CloseTabEvent)

		# Browser state
		self.event_bus.on(BrowserStateRequestEvent, self.on_BrowserStateRequestEvent)
		self.event_bus.on(ScreenshotRequestEvent, self.on_ScreenshotRequestEvent)
		self.event_bus.on(TabsInfoRequestEvent, self.on_TabsInfoRequestEvent)
		self.event_bus.on(ExecuteJavaScriptEvent, self.on_ExecuteJavaScriptEvent)

		# Storage state is handled by StorageStateWatchdog

	# ========== Event Handlers ==========

	async def on_StartBrowserEvent(self, event: StartBrowserEvent) -> None:
		"""Handle browser start request."""
		if self._browser and self._browser.is_connected():
			# Already started
			if not self.cdp_url:
				raise ValueError('No CDP URL available for browser connection')
			self.event_bus.dispatch(
				BrowserStartedEvent(
					cdp_url=self.cdp_url,
					browser_pid=self._subprocess.pid if self._subprocess else None,
				)
			)
			return

		try:
			if self.is_local and not self.cdp_url:
				# Launch local browser
				from browser_use.browser.local import LocalBrowserHelpers

				self._subprocess, self.cdp_url = await LocalBrowserHelpers.launch_browser(self.browser_profile)

			# Ensure we have a CDP URL at this point
			if not self.cdp_url:
				raise ValueError('No CDP URL available for browser connection')

			# Connect via CDP
			self._playwright = await async_playwright().start()
			self._browser = await self._playwright.chromium.connect_over_cdp(
				self.cdp_url,
				**self.browser_profile.kwargs_for_cdp_connection(),
			)

			# Set up browser context
			contexts = self._browser.contexts
			if contexts:
				self._browser_context = contexts[0]
			else:
				# Get context kwargs
				new_context_args = self.browser_profile.kwargs_for_new_context()
				context_kwargs = new_context_args.model_dump(exclude_none=True)

				# Ensure accept_downloads is True when downloads are enabled
				if self.browser_profile.downloads_path:
					# Ensure downloads directory exists
					downloads_dir = Path(self.browser_profile.downloads_path)
					downloads_dir.mkdir(parents=True, exist_ok=True)
					context_kwargs['accept_downloads'] = True
					# Note: downloads_path is NOT a valid parameter for new_context()
					# Downloads will be handled by the downloads watchdog using download.save_as()
					logger.info(f'Downloads enabled, target directory: {downloads_dir.absolute()}')
					logger.info(f'Accept downloads: {context_kwargs["accept_downloads"]}')

				# Log storage state info
				logger.info(f'BrowserProfile storage_state: {self.browser_profile.storage_state}')
				logger.info(f'NewContextArgs storage_state: {new_context_args.storage_state}')
				logger.info(f'Context kwargs keys: {list(context_kwargs.keys())}')
				logger.info(f'Context kwargs storage_state: {context_kwargs.get("storage_state")}')
				logger.info(f'Context kwargs accept_downloads: {context_kwargs.get("accept_downloads")}')

				self._browser_context = await self._browser.new_context(**context_kwargs)

			# Set initial page if exists
			pages = self._browser_context.pages
			# Agent focus will be initialized by the watchdog

			# Initialize and attach all watchdogs FIRST
			await self.attach_all_watchdogs()

			# THEN notify success - watchdogs are now ready to receive events
			logger.info('[Session] !!!! DISPATCHING BrowserStartedEvent !!!!')
			self.event_bus.dispatch(
				BrowserStartedEvent(
					cdp_url=self.cdp_url,
					browser_pid=self._subprocess.pid if self._subprocess else None,
				)
			)
			logger.info('[Session] !!!! BrowserStartedEvent dispatched !!!!')

			# Emit TabCreatedEvent and NavigationCompleteEvent for all existing pages
			if self._browser_context:
				for idx, page in enumerate(self._browser_context.pages):
					# Emit TabCreatedEvent
					self.event_bus.dispatch(
						TabCreatedEvent(
							tab_index=idx,
							url=page.url,
						)
					)
					logger.info(f'[Session] Emitted TabCreatedEvent for existing tab {idx}: {page.url}')

					# Emit NavigationCompleteEvent for the current page state
					self.event_bus.dispatch(
						NavigationCompleteEvent(
							tab_index=idx,
							url=page.url,
							status=200,  # Assume existing pages loaded successfully
							error_message=None,
							loading_status='Existing page, found already open',
						)
					)
					logger.info(f'[Session] Emitted NavigationCompleteEvent for existing tab {idx}: {page.url}')

			# Automatically load storage state after browser start
			self.event_bus.dispatch(LoadStorageStateEvent())

		except Exception as e:
			# Clean up on failure
			if self._playwright:
				await self._playwright.stop()
				self._playwright = None

			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='StartFailed',
					message=f'Failed to start browser: {str(e)}',
					details={'cdp_url': self.cdp_url},
				)
			)
			raise

	async def on_StopBrowserEvent(self, event: StopBrowserEvent) -> None:
		"""Handle browser stop request."""
		if not self._browser:
			self.event_bus.dispatch(
				BrowserStoppedEvent(
					reason='Browser was not started',
				)
			)
			return

		try:
			# Check if we should keep the browser alive
			if self.browser_profile.keep_alive and not event.force:
				# Keep browser alive, just notify stop
				self.event_bus.dispatch(
					BrowserStoppedEvent(
						reason='Kept alive due to keep_alive=True',
					)
				)
				return

			# Network monitoring now handled by watchdogs

			# Automatically save storage state before stopping and wait for completion
			save_event = self.event_bus.dispatch(SaveStorageStateEvent())
			await save_event

			# Close context if we created it
			if self._browser_context and not self._browser_context.pages:
				await self._browser_context.close()

			# Clean up playwright
			if self._playwright:
				await self._playwright.stop()
				self._playwright = None

			# Stop local browser process if we own it
			if self.is_local and self._owns_browser_resources and self._subprocess:
				from browser_use.browser.local import LocalBrowserHelpers

				await LocalBrowserHelpers.cleanup_process(self._subprocess)

				# Clean up temp directory if one was created
				if self.browser_profile.user_data_dir and 'browseruse-tmp-' in str(self.browser_profile.user_data_dir):
					LocalBrowserHelpers.cleanup_temp_dir(self.browser_profile.user_data_dir)

			# Reset state
			self._browser = None
			self._browser_context = None

			# Clear CDP URL for local browsers since the process is gone
			if self.is_local and self._owns_browser_resources:
				self.cdp_url = None

			# Notify stop and wait for all handlers to complete
			stop_event = self.event_bus.dispatch(
				BrowserStoppedEvent(
					reason='Stopped by request',
				)
			)
			# Wait for all watchdog cleanup handlers to complete
			await stop_event

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='StopFailed',
					message=f'Failed to stop browser: {str(e)}',
				)
			)

	# ========== Backwards Compatibility Methods ==========
	# These all just dispatch events internally

	async def start(self) -> Self:
		"""Start the browser session."""
		event = self.event_bus.dispatch(StartBrowserEvent())
		# Wait for event to complete
		await event

		# Check if any handler had an error
		for event_result in event.event_results.values():
			if event_result.status == 'error' and event_result.error:
				raise event_result.error

		return self

	async def stop(self) -> None:
		"""Stop the browser session."""
		event = self.event_bus.dispatch(StopBrowserEvent())
		await event

	async def on_ClickElementEvent(self, event: ClickElementEvent) -> None:
		"""Handle click request."""
		try:
			page = await self.get_current_page()
		except ValueError:
			self.event_bus.dispatch(BrowserErrorEvent(error_type='NoActivePage', message='No active page for click', details={}))
			return

		try:
			# Get the DOM element by index
			element_node = await self.get_dom_element_by_index(event.index)
			if element_node is None:
				raise Exception(f'Element index {event.index} does not exist - retry or use alternative actions')

			# Track initial number of tabs to detect new tab opening
			initial_pages = len(self.pages)

			# Check if element is a file input (should not be clicked)
			if self.is_file_input(element_node):
				msg = f'Index {event.index} - has an element which opens file upload dialog. To upload files please use a specific function to upload files'
				logger.info(msg)
				self.event_bus.dispatch(
					BrowserErrorEvent(
						error_type='FileInputElement',
						message=msg,
						details={'index': event.index},
					)
				)
				return

			# Perform the actual click
			download_path = await self._click_element_node(
				element_node, expect_download=event.expect_download, new_tab=event.new_tab
			)

			# Build success message
			if download_path:
				msg = f'Downloaded file to {download_path}'
				logger.info(f'💾 {msg}')
			else:
				msg = f'Clicked button with index {event.index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'
				logger.info(f'🖱️ {msg}')

			logger.debug(f'Element xpath: {element_node.xpath}')

			# Check if a new tab was opened
			if len(self.pages) > initial_pages:
				new_tab_msg = 'New tab opened - switching to it'
				msg += f' - {new_tab_msg}'
				logger.info(f'🔗 {new_tab_msg}')
				# Switch to the last tab (newly created tab)
				last_tab_index = len(self.pages) - 1
				await self.switch_to_tab(last_tab_index)

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='ClickFailed',
					message=str(e),
					details={'index': event.index},
				)
			)

	async def on_TypeTextEvent(self, event: TypeTextEvent) -> None:
		"""Handle text input request."""
		try:
			page = await self.get_current_page()
		except ValueError:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NoActivePage',
					message='No active page for text input',
				)
			)
			return

		try:
			# Get the DOM element by index
			element_node = await self.get_dom_element_by_index(event.index)
			if element_node is None:
				raise Exception(f'Element index {event.index} does not exist - retry or use alternative actions')

			# Perform the actual text input
			await self._input_text_element_node(element_node, event.text)

			# Log success
			logger.info(f'⌨️ Typed "{event.text}" into element with index {event.index}')
			logger.debug(f'Element xpath: {element_node.xpath}')

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='InputTextFailed',
					message=str(e),
					details={'index': event.index, 'text': event.text},
				)
			)

	async def on_ScrollEvent(self, event: ScrollEvent) -> None:
		"""Handle scroll request."""
		try:
			page = await self.get_current_page()
		except ValueError:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='NoActivePage',
					message='No active page for scrolling',
				)
			)
			return

		try:
			# Convert direction and amount to pixels
			# Positive pixels = scroll down, negative = scroll up
			pixels = event.amount if event.direction == 'down' else -event.amount

			# Perform the scroll
			await self._scroll_container(pixels)

			# Log success
			logger.info(f'📜 Scrolled {event.direction} by {event.amount} pixels')

		except Exception as e:
			self.event_bus.dispatch(
				BrowserErrorEvent(
					error_type='ScrollFailed',
					message=str(e),
					details={'direction': event.direction, 'amount': event.amount},
				)
			)

	async def on_CloseTabEvent(self, event: CloseTabEvent) -> None:
		"""Handle tab close request."""
		if 0 <= event.tab_index < len(self.pages):
			await self.pages[event.tab_index].close()
			# Dispatch tab closed event for watchdogs
			self.event_bus.dispatch(TabClosedEvent(tab_index=event.tab_index))

	async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> None:
		"""Handle browser state request."""
		try:
			# Use the internal method directly to avoid infinite loop
			state = await self._get_browser_state_with_recovery(
				cache_clickable_elements_hashes=event.cache_clickable_elements_hashes, include_screenshot=event.include_screenshot
			)
			# Cache the state for the property
			self._cached_browser_state_summary = state
			self.event_bus.dispatch(BrowserStateResponseEvent(state=state))
		except Exception as e:
			# Fall back to minimal state on error
			minimal_state = await self.get_minimal_state_summary()
			self.event_bus.dispatch(BrowserStateResponseEvent(state=minimal_state))

	async def on_ScreenshotRequestEvent(self, event: ScreenshotRequestEvent) -> None:
		"""Handle screenshot request."""
		try:
			page = await self.get_current_page()
		except ValueError:
			return

		# Convert clip dict to FloatRect if provided
		clip_rect: FloatRect | None = None
		if event.clip:
			clip_rect = FloatRect(
				x=event.clip['x'],
				y=event.clip['y'],
				width=event.clip['width'],
				height=event.clip['height'],
			)

		# Add timeout protection to prevent hanging on unresponsive pages
		try:
			screenshot_bytes = await asyncio.wait_for(
				page.screenshot(
					full_page=event.full_page,
					clip=clip_rect,
				),
				timeout=10.0,  # 10 second timeout for screenshots
			)
		except TimeoutError:
			logger.warning(f'[Session] Screenshot timed out after 10 seconds for page: {page.url}')
			# Return empty response or could dispatch error event
			self.event_bus.dispatch(ScreenshotResponseEvent(screenshot='', error='Screenshot timed out'))
			return
		screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
		self.event_bus.dispatch(ScreenshotResponseEvent(screenshot=screenshot_b64))

	async def on_TabsInfoRequestEvent(self, event: TabsInfoRequestEvent) -> None:
		"""Handle tabs info request."""
		from browser_use.browser.views import TabInfo

		# Auto-start if not initialized
		if not self.initialized:
			start_event = self.event_bus.dispatch(StartBrowserEvent())
			await start_event

		tabs = []
		for i, page in enumerate(self.pages):
			if not page.is_closed():
				tab_info = TabInfo(
					page_id=i,
					url=page.url,
					title=await page.title(),
					parent_page_id=None,
					id=f'tab_{i}',
					index=i,
				)
				tabs.append(tab_info.model_dump())
		# Dispatch the response event
		self.event_bus.dispatch(TabsInfoResponseEvent(tabs=tabs))

	async def on_ExecuteJavaScriptEvent(self, event: ExecuteJavaScriptEvent) -> Any:
		"""Handle JavaScript evaluation request."""
		# Get the correct page by tab index
		if 0 <= event.tab_index < len(self.pages):
			page = self.pages[event.tab_index]
		else:
			page = await self.get_current_page()

		# Execute the JavaScript and return result directly
		result = await page.evaluate(event.expression)
		return result

	def _generate_recent_events_summary(self, max_events: int = 10) -> str:
		"""Generate a JSON summary of recent browser events."""

		# Get recent events from the event bus history (it's a dict of UUID -> Event)
		all_events = list(self.event_bus.event_history.values())
		recent_events = all_events[-max_events:] if all_events else []

		if not recent_events:
			return '[]'

		# Convert events to JSON
		events_data = []
		for event in recent_events:
			# Exclude fields that might cause circular references
			# BrowserStateResponseEvent has 'state' which can be circular
			event_dict = event.model_dump(mode='json', exclude={'state'})
			events_data.append(event_dict)

		return json.dumps(events_data, indent=2)

	# ========== Backwards Compatibility Methods ==========

	async def kill(self) -> None:
		"""Alias for stop() for backwards compatibility."""
		await self.stop()

	async def close(self) -> None:
		"""Alias for stop() for backwards compatibility."""
		await self.stop()

	async def __aenter__(self) -> Self:
		"""Async context manager entry."""
		return await self.start()

	async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
		"""Async context manager exit."""
		await self.stop()

	# Browser properties
	@property
	def initialized(self) -> bool:
		"""Check if the browser session is initialized."""
		return self._browser is not None and self._browser.is_connected()

	@property
	def browser_pid(self) -> int | None:
		"""Get the browser process ID."""
		if self._subprocess:
			return self._subprocess.pid
		return None

	@property
	def browser(self) -> Browser | None:
		"""Get the browser instance."""
		return self._browser

	@property
	def browser_context(self) -> BrowserContext | None:
		"""Get the browser context."""
		return self._browser_context

	@property
	def page(self) -> Page | None:
		"""Get the agent's current page."""
		if self._navigation_watchdog and hasattr(self._navigation_watchdog, 'current_agent_page'):
			page = self._navigation_watchdog.current_agent_page
			if page is not None:
				return page

		# Fallback: return the first available page if browser context is ready
		if self._browser_context and self._browser_context.pages:
			return self._browser_context.pages[0]

		return None

	@property
	def downloaded_files(self) -> list[str]:
		"""Get list of downloaded files from the downloads directory, sorted by date (newest first)."""
		if not self.browser_profile.downloads_path:
			return []

		downloads_dir = self.browser_profile.downloads_path
		if not os.path.exists(downloads_dir):
			return []

		# List all files in the downloads directory with their modification times
		try:
			files_with_time = []
			for filename in os.listdir(downloads_dir):
				filepath = os.path.join(downloads_dir, filename)
				if os.path.isfile(filepath):
					# Get modification time
					mtime = os.path.getmtime(filepath)
					files_with_time.append((filepath, mtime))

			# Sort by modification time (newest first)
			files_with_time.sort(key=lambda x: x[1], reverse=True)

			# Return just the file paths
			return [filepath for filepath, _ in files_with_time]
		except Exception as e:
			logger.warning(f'Failed to list downloaded files: {e}')
			return []

	@property
	def tabs(self) -> list[Page]:
		"""Get all open tabs/pages."""
		if self._browser_context:
			return self._browser_context.pages
		return []

	@property
	def pages(self) -> list[Page]:
		"""Get all open pages."""
		if self._browser_context:
			return self._browser_context.pages
		return []

	def get_page_by_tab_index(self, tab_index: int) -> Page | None:
		"""Get page by tab index."""
		if 0 <= tab_index < len(self.pages):
			return self.pages[tab_index]
		return None

	def get_tab_index(self, page: Page) -> int:
		"""Get tab index for a page."""
		if page in self.pages:
			return self.pages.index(page)
		return -1

	@property
	def browser_state_summary(self) -> Any:
		"""Get the cached browser state summary (synchronous access)."""
		# This is a compatibility property for code that expects synchronous access
		# For new code, use get_browser_state_with_recovery() instead
		return getattr(self, '_cached_browser_state_summary', None)

	# Page management
	async def get_current_page(self) -> Page:
		"""Get the current active page."""
		if self._navigation_watchdog:
			return await self._navigation_watchdog.get_or_create_page()
		# Fallback if watchdog not initialized
		if self.pages:
			return self.pages[0]
		raise ValueError('No active page available')

	async def new_page(self, url: str | None = None) -> Page:
		"""Create a new page."""
		if url:
			event = self.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=True))
		else:
			event = self.event_bus.dispatch(NavigateToUrlEvent(url='about:blank', new_tab=True))
		await event
		return self.pages[-1]  # Return the newly created page

	async def create_new_tab(self, url: str | None = None) -> Page:
		"""Create a new tab."""
		return await self.new_page(url)

	async def new_tab(self, url: str | None = None) -> Page:
		"""Alias for create_new_tab for backward compatibility."""
		return await self.new_page(url)

	async def switch_to_tab(self, tab_index: int) -> None:
		"""Switch to a tab by index."""
		event = self.event_bus.dispatch(SwitchTabEvent(tab_index=tab_index))
		await event

	async def close_tab(self, tab_index: int | None = None) -> None:
		"""Close a tab by index. If no index provided, closes current tab."""
		if tab_index is None:
			# Close current tab - get the current page and close it
			current_page = await self.get_current_page()
			await current_page.close()
		else:
			# Close specific tab
			event = self.event_bus.dispatch(CloseTabEvent(tab_index=tab_index))
			await event

	async def navigate_to(self, url: str) -> Page:
		"""Navigate the current page to a URL."""
		event = self.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event
		return await self.get_current_page()

	async def navigate(self, url: str, timeout_ms: int | None = None, new_tab: bool = False) -> Page:
		"""Navigate with optional timeout and new tab support."""
		event = self.event_bus.dispatch(NavigateToUrlEvent(url=url, timeout_ms=timeout_ms, new_tab=new_tab))
		await event
		return await self.get_current_page()

	async def go_to_url(self, url: str) -> None:
		"""Alias for navigate_to."""
		event = self.event_bus.dispatch(NavigateToUrlEvent(url=url))
		await event

	async def go_back(self) -> None:
		"""Go back in the browser history."""
		page = await self.get_current_page()
		if page:
			await page.go_back()

	async def go_forward(self) -> None:
		"""Go forward in the browser history."""
		page = await self.get_current_page()
		if page:
			await page.go_forward()

	async def refresh(self) -> None:
		"""Refresh the current page."""
		page = await self.get_current_page()
		if page:
			await page.reload()

	async def take_screenshot(self, full_page: bool = False, clip: dict | None = None) -> str | None:
		"""Take a screenshot."""
		# Dispatch the request event
		self.event_bus.dispatch(ScreenshotRequestEvent(full_page=full_page, clip=clip))
		# Wait for the response event
		try:
			event_result = await self.event_bus.expect(ScreenshotResponseEvent, timeout=10.0)
			response: ScreenshotResponseEvent = event_result  # type: ignore
			return response.screenshot  # Return base64 string directly
		except TimeoutError:
			# No screenshot received
			return None

	async def click_element(self, index: int, expect_download: bool = False, new_tab: bool = False) -> None:
		"""Click element by index."""
		event = self.event_bus.dispatch(ClickElementEvent(index=index, expect_download=expect_download, new_tab=new_tab))
		await event

	async def input_text(self, index: int, text: str) -> None:
		"""Input text into element."""
		event = self.event_bus.dispatch(TypeTextEvent(index=index, text=text))
		await event

	async def scroll(self, direction: Literal['up', 'down', 'left', 'right'], amount: int) -> None:
		"""Scroll the page."""
		event = self.event_bus.dispatch(ScrollEvent(direction=direction, amount=amount))
		await event

	# Model copy support
	def model_copy(self, **kwargs) -> Self:
		"""Create a copy of this session."""
		# Create a new instance sharing the same browser resources
		copy = self.__class__(
			browser_profile=self.browser_profile,
			cdp_url=self.cdp_url,
			**kwargs,
		)
		# Share the browser state
		copy._playwright = self._playwright
		copy._browser = self._browser
		copy._browser_context = self._browser_context
		copy._subprocess = self._subprocess
		copy._owns_browser_resources = False  # Copy doesn't own resources
		return copy

	# Additional compatibility methods
	async def is_connected(self, restart: bool = True) -> bool:
		"""Check if connected to browser."""
		# The restart parameter is for backward compatibility but is ignored
		# in the current implementation since restart behavior is now handled automatically
		return self._browser is not None and self._browser.is_connected()

	async def save_storage_state(self, path: str | None = None) -> None:
		"""Save browser storage state."""
		# Use event-based approach
		self.event_bus.dispatch(SaveStorageStateEvent(path=path))

	async def get_tabs_info(self) -> list[TabInfo]:
		"""Get information about all open tabs."""
		# Dispatch the request event
		self.event_bus.dispatch(TabsInfoRequestEvent())
		# Wait for the response event
		try:
			event_result = await self.event_bus.expect(TabsInfoResponseEvent, timeout=5.0)
			response: TabsInfoResponseEvent = event_result  # type: ignore
			# Convert dictionaries to TabInfo models
			tab_infos = []
			for tab_dict in response.tabs:
				tab_info = TabInfo(**tab_dict)
				tab_infos.append(tab_info)
			return tab_infos
		except TimeoutError:
			# No response received
			return []

	# DOM element methods
	async def get_browser_state_with_recovery(
		self, cache_clickable_elements_hashes: bool = True, include_screenshot: bool = True
	) -> Any:
		"""Get browser state with multiple fallback strategies for error recovery

		Parameters:
		-----------
		cache_clickable_elements_hashes: bool
			If True, cache the clickable elements hashes for the current state.
		include_screenshot: bool
			If True, include screenshot in the state summary. Set to False to improve performance
			when screenshots are not needed (e.g., in multi_act element validation).
		"""
		# Dispatch request event
		self.event_bus.dispatch(
			BrowserStateRequestEvent(
				include_dom=True,
				include_screenshot=include_screenshot,
				cache_clickable_elements_hashes=cache_clickable_elements_hashes,
			)
		)

		# Wait for response
		try:
			event_result = await self.event_bus.expect(BrowserStateResponseEvent, timeout=60.0)
			response: BrowserStateResponseEvent = event_result  # type: ignore
			return response.state
		except TimeoutError:
			# Fall back to minimal state
			return await self.get_minimal_state_summary()

	async def _get_browser_state_with_recovery(
		self, cache_clickable_elements_hashes: bool = True, include_screenshot: bool = True
	) -> Any:
		"""Internal method to get browser state with recovery logic."""
		# Try 1: Full state summary
		try:
			await self.get_current_page()  # Ensure we have a page
			return await self.get_state_summary(cache_clickable_elements_hashes, include_screenshot=include_screenshot)
		except Exception as e:
			logger.warning(f'Full state retrieval failed: {type(e).__name__}: {e}')

		logger.warning('🔄 Falling back to minimal state summary')
		return await self.get_minimal_state_summary()

	async def get_state_summary(self, cache_clickable_elements_hashes: bool, include_screenshot: bool = True) -> Any:
		"""Get a summary of the current browser state"""
		from browser_use.browser.views import BrowserStateSummary, PageInfo
		from browser_use.dom.service import DomService

		# Auto-start if needed
		if not self.initialized:
			await self.start()

		page = await self.get_current_page()

		# Use DomService to get DOM content like the original implementation
		dom_service = DomService(page, logger=logger)
		try:
			content = await asyncio.wait_for(
				dom_service.get_clickable_elements(
					focus_element=-1,
					viewport_expansion=self.browser_profile.viewport_expansion,
					highlight_elements=self.browser_profile.highlight_elements,
				),
				timeout=45.0,
			)
		except TimeoutError:
			logger.warning(f'DOM processing timed out after 45 seconds for {page.url}')
			# Fall back to minimal DOM
			from browser_use.dom.views import DOMElementNode, DOMState

			minimal_element_tree = DOMElementNode(
				tag_name='body',
				xpath='/body',
				attributes={},
				children=[],
				is_visible=True,
				parent=None,
			)
			content = DOMState(element_tree=minimal_element_tree, selector_map={})

		# Get tabs info
		tabs_info = await self.get_tabs_info()

		# Get screenshot if requested
		screenshot_b64 = None
		if include_screenshot:
			try:
				screenshot_bytes = await asyncio.wait_for(
					page.screenshot(),
					timeout=10.0,  # 10 second timeout for screenshots
				)
				screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
			except (Exception, TimeoutError) as e:
				logger.debug(f'[Session] Screenshot failed: {e}')
				pass

		# Get page dimensions
		try:
			page_dimensions = await page.evaluate("""
				() => ({
					viewport_width: window.innerWidth,
					viewport_height: window.innerHeight,
					page_width: document.documentElement.scrollWidth,
					page_height: document.documentElement.scrollHeight,
					scroll_x: window.scrollX,
					scroll_y: window.scrollY
				})
			""")

			page_info = PageInfo(
				viewport_width=page_dimensions['viewport_width'],
				viewport_height=page_dimensions['viewport_height'],
				page_width=page_dimensions['page_width'],
				page_height=page_dimensions['page_height'],
				scroll_x=page_dimensions['scroll_x'],
				scroll_y=page_dimensions['scroll_y'],
				pixels_above=page_dimensions['scroll_y'],
				pixels_below=max(
					0, page_dimensions['page_height'] - page_dimensions['scroll_y'] - page_dimensions['viewport_height']
				),
				pixels_left=page_dimensions['scroll_x'],
				pixels_right=max(
					0, page_dimensions['page_width'] - page_dimensions['scroll_x'] - page_dimensions['viewport_width']
				),
			)
		except Exception:
			# Fallback page info
			viewport = page.viewport_size or {'width': 1280, 'height': 720}
			page_info = PageInfo(
				viewport_width=viewport['width'],
				viewport_height=viewport['height'],
				page_width=viewport['width'],
				page_height=viewport['height'],
				scroll_x=0,
				scroll_y=0,
				pixels_above=0,
				pixels_below=0,
				pixels_left=0,
				pixels_right=0,
			)

		# Check for PDF viewer status from downloads watchdog
		is_pdf_viewer = False
		if self._downloads_watchdog:
			is_pdf_viewer = await self._downloads_watchdog.check_for_pdf_viewer(page)

		return BrowserStateSummary(
			element_tree=content.element_tree,
			selector_map=content.selector_map,
			url=page.url,
			title=await page.title(),
			tabs=tabs_info,
			screenshot=screenshot_b64,
			page_info=page_info,
			pixels_above=page_info.pixels_above,
			pixels_below=page_info.pixels_below,
			is_pdf_viewer=is_pdf_viewer,
			recent_events=self._generate_recent_events_summary(),
		)

	async def get_minimal_state_summary(self) -> Any:
		"""Get basic page info without DOM processing"""
		from browser_use.browser.views import BrowserStateSummary
		from browser_use.dom.views import DOMElementNode

		page = await self.get_current_page()

		# Get basic info
		url = getattr(page, 'url', 'unknown')

		try:
			title = await asyncio.wait_for(page.title(), timeout=2.0)
		except Exception:
			title = 'Page Load Error'

		try:
			tabs_info = await self.get_tabs_info()
		except Exception:
			tabs_info = []

		# Create minimal DOM element
		minimal_element_tree = DOMElementNode(
			tag_name='body',
			xpath='/body',
			attributes={},
			children=[],
			is_visible=True,
			parent=None,
		)

		# Check if current page is a PDF viewer
		is_pdf_viewer = False
		if self._downloads_watchdog:
			try:
				is_pdf_viewer = await self._downloads_watchdog.check_for_pdf_viewer(page)
			except Exception:
				pass

		return BrowserStateSummary(
			element_tree=minimal_element_tree,
			selector_map={},
			url=url,
			title=title,
			tabs=tabs_info,
			pixels_above=0,
			pixels_below=0,
			is_pdf_viewer=is_pdf_viewer,
			recent_events=self._generate_recent_events_summary(),
		)

	async def get_selector_map(self) -> dict:
		"""Get selector map from the current browser state."""
		state = await self.get_browser_state_with_recovery()
		return state.selector_map if hasattr(state, 'selector_map') else {}

	async def find_file_upload_element_by_index(self, index: int) -> Any:
		"""Find file upload element by index."""
		element = await self.get_dom_element_by_index(index)
		if element and self.is_file_input(element):
			return element
		return None

	async def get_locate_element_by_xpath(self, xpath: str) -> Any:
		"""Get playwright ElementHandle for an element by XPath."""
		page = await self.get_current_page()
		if not page:
			return None

		try:
			return await page.locator(f'xpath={xpath}').element_handle()
		except Exception:
			return None

	async def get_locate_element_by_css_selector(self, selector: str) -> Any:
		"""Get playwright ElementHandle for an element by CSS selector."""
		page = await self.get_current_page()
		if not page:
			return None

		try:
			return await page.locator(selector).element_handle()
		except Exception:
			return None

	async def get_locate_element(self, element: Any) -> Any:
		"""Get playwright ElementHandle for a DOM element."""
		if not element or not hasattr(element, 'xpath'):
			return None

		page = await self.get_current_page()
		if not page:
			return None

		current_frame = page

		# Start with the target element and collect all parents
		parents = []
		current = element
		while hasattr(current, 'parent') and current.parent is not None:
			parent = current.parent
			parents.append(parent)
			current = parent

		# Reverse the parents list to process from top to bottom
		parents.reverse()

		# Process all iframe parents in sequence
		iframes = [item for item in parents if hasattr(item, 'tag_name') and item.tag_name == 'iframe']
		for parent in iframes:
			css_selector = self._enhanced_css_selector_for_element(
				parent,
				include_dynamic_attributes=self.browser_profile.include_dynamic_attributes,
			)
			# Use CSS selector if available, otherwise fall back to XPath
			if css_selector:
				current_frame = current_frame.frame_locator(css_selector)
			else:
				logger.debug(f'Using XPath for iframe: {parent.xpath}')
				current_frame = current_frame.frame_locator(f'xpath={parent.xpath}')

		css_selector = self._enhanced_css_selector_for_element(
			element, include_dynamic_attributes=self.browser_profile.include_dynamic_attributes
		)

		try:
			if hasattr(current_frame, 'locator'):
				if css_selector:
					element_handle = await current_frame.locator(css_selector).element_handle()
				else:
					# Fall back to XPath when CSS selector is empty
					logger.debug(f'CSS selector empty, falling back to XPath: {element.xpath}')
					element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
				return element_handle
			else:
				# FrameLocator doesn't have query_selector, use locator instead
				if css_selector:
					element_handle = await current_frame.locator(css_selector).element_handle()
				else:
					# Fall back to XPath
					logger.debug(f'CSS selector empty, falling back to XPath: {element.xpath}')
					element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
				if element_handle:
					is_visible = await self._is_visible(element_handle)
					if is_visible:
						await element_handle.scroll_into_view_if_needed(timeout=1_000)
					return element_handle
				return None
		except Exception as e:
			# If CSS selector failed, try XPath as fallback
			if css_selector and 'CSS.escape' not in str(e):
				try:
					logger.debug(f'CSS selector failed ({css_selector}), falling back to XPath: {element.xpath}')
					if hasattr(current_frame, 'locator'):
						element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
					else:
						element_handle = await current_frame.locator(f'xpath={element.xpath}').element_handle()
					if element_handle:
						is_visible = await self._is_visible(element_handle)
						if is_visible:
							await element_handle.scroll_into_view_if_needed(timeout=1_000)
						return element_handle
					return None
				except Exception:
					return None
			return None

	def is_file_input(self, element: Any) -> bool:
		"""Check if element is a file input."""
		if not element or not hasattr(element, 'tag_name') or not hasattr(element, 'attributes'):
			return False

		# Check if it's an input element with type="file"
		if element.tag_name.lower() == 'input':
			input_type = element.attributes.get('type', '').lower()
			if input_type == 'file':
				return True

		# Check for file-related attributes or classes that might indicate file upload
		# This is a more conservative check to avoid false positives
		return False

	async def _is_visible(self, element) -> bool:
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
		is_visible = not is_hidden and bbox is not None and bbox['width'] > 0 and bbox['height'] > 0
		return is_visible

	@classmethod
	def _enhanced_css_selector_for_element(cls, element: Any, include_dynamic_attributes: bool = True) -> str:
		"""
		Creates a CSS selector for a DOM element, handling various edge cases and special characters.

		Args:
						element: The DOM element to create a selector for

		Returns:
						A valid CSS selector string
		"""
		try:
			import re

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
			# Fallback to empty string
			return ''

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
				# Handle custom elements with colons
				if ':' in part:
					part = part.replace(':', r'\:')
				css_parts.append(part)

		return ' > '.join(css_parts) if css_parts else ''

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

	async def _click_element_node(self, element: Any, expect_download: bool = False, new_tab: bool = False) -> str | None:
		"""Click an element node and handle potential downloads.

		Args:
			element: The DOM element to click
			expect_download: If True, wait for download and handle it inline. If False, let page-level handler catch it.
			new_tab: If True, open any resulting navigation in a new tab.

		Returns the download path if a download was triggered, None otherwise.
		"""
		if not element:
			raise ValueError('No element provided to click')

		page = await self.get_current_page()
		if not page:
			raise ValueError('No current page available')

		# Get the playwright locator for the element
		locator = await self.get_locate_element(element)
		if not locator:
			raise ValueError(f'Could not locate element with xpath: {element.xpath}')

		download_path = None

		if expect_download and self.browser_profile.downloads_path:
			# When expecting a download, click and wait for FileDownloadedEvent from downloads watchdog
			# The downloads watchdog page-level listener will handle the actual download
			try:
				# Click the element (with new tab modifier if requested)
				if new_tab:
					import sys

					modifier = 'Meta' if sys.platform == 'darwin' else 'Control'
					await locator.click(modifiers=[modifier])
				else:
					await locator.click()

				# Wait for download event from downloads watchdog with timeout
				# The watchdog's page.on('download') handler will save_as() and dispatch FileDownloadedEvent
				download_event = cast(FileDownloadedEvent, await self.event_bus.expect(FileDownloadedEvent, timeout=10.0))
				download_path = download_event.path
				logger.info(f'⬇️ Downloaded file via watchdog: {download_path}')

			except TimeoutError:
				logger.warning('Expected download but no FileDownloadedEvent received within timeout')
			except Exception as e:
				logger.warning(f'Error while waiting for download: {e}')
		else:
			# Normal click or new tab click - let downloads watchdog handle any downloads in background
			if new_tab:
				import sys

				# Track initial tab count before clicking
				initial_tab_count = len(self.pages)

				modifier = 'Meta' if sys.platform == 'darwin' else 'Control'
				await locator.click(modifiers=[modifier])

				# Wait for new tab to be created (up to 5 seconds)
				try:
					await asyncio.wait_for(self._wait_for_new_tab(initial_tab_count), timeout=5.0)
					logger.debug(f'New tab opened, tab count: {len(self.pages)}')
				except TimeoutError:
					logger.debug('No new tab opened within 5 seconds')
			else:
				await locator.click()

		return download_path

	async def _wait_for_new_tab(self, initial_tab_count: int) -> None:
		"""Wait for a new tab to be created."""
		# Wait for TabCreatedEvent instead of polling
		from browser_use.browser.events import TabCreatedEvent

		try:
			await self.event_bus.expect(TabCreatedEvent, timeout=5.0)
		except TimeoutError:
			# No new tab was created within timeout
			pass

	async def _input_text_element_node(self, element: Any, text: str) -> None:
		"""Input text into an element node."""
		if not element:
			raise ValueError('No element provided for text input')

		page = await self.get_current_page()
		if not page:
			raise ValueError('No current page available')

		# Get the playwright locator for the element
		locator = await self.get_locate_element(element)
		if not locator:
			raise ValueError(f'Could not locate element with xpath: {element.xpath}')

		# Clear existing text and type new text
		await locator.fill(text)

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
				# Detach may timeout on some CDP implementations
				pass

			return True
		except Exception as e:
			logger.debug(f'CDP scroll gesture failed: {e}')
			return False

	async def _scroll_container(self, pixels: int) -> None:
		"""Scroll using CDP gesture synthesis with JavaScript fallback."""

		page = await self.get_current_page()

		# Try CDP scroll gesture first (works universally including PDFs)
		if await self._scroll_with_cdp_gesture(page, pixels):
			return

		# Fallback to JavaScript for older browsers or when CDP fails
		logger.debug('Falling back to JavaScript scrolling')
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

	def _is_url_allowed(self, url: str) -> bool:
		"""Check if a URL is allowed based on the allowed_domains configuration.

		Args:
			url: The URL to check

		Returns:
			True if the URL is allowed, False otherwise
		"""
		# If no allowed_domains specified, allow all URLs
		if not self.browser_profile.allowed_domains:
			return True

		# Always allow internal browser pages
		if url in ['about:blank', 'chrome://new-tab-page/', 'chrome://new-tab-page', 'chrome://newtab/']:
			return True

		# Parse the URL to extract components
		from urllib.parse import urlparse

		try:
			parsed = urlparse(url)
		except Exception:
			# Invalid URL
			return False

		# Get the actual host (domain)
		host = parsed.hostname
		if not host:
			return False

		# Full URL for matching (scheme + host)
		full_url_pattern = f'{parsed.scheme}://{host}'

		# Check each allowed domain pattern
		for pattern in self.browser_profile.allowed_domains:
			# Handle glob patterns
			if '*' in pattern:
				import fnmatch

				# Check if pattern matches the host
				if pattern.startswith('*.'):
					# Pattern like *.example.com should match subdomains and main domain
					# But only for http/https URLs unless scheme is specified
					domain_part = pattern[2:]  # Remove *.
					if host == domain_part or host.endswith('.' + domain_part):
						# Only match http/https URLs for domain-only patterns
						if parsed.scheme in ['http', 'https']:
							return True
				elif pattern.endswith('/*'):
					# Pattern like brave://* should match any brave:// URL
					prefix = pattern[:-1]  # Remove the * at the end
					if url.startswith(prefix):
						return True
				elif '://*.' in pattern:
					# Pattern like http://*.example.com should match http://sub.example.com
					scheme_and_wildcard, domain_part = pattern.split('://*.')
					expected_scheme = scheme_and_wildcard
					if parsed.scheme == expected_scheme and (host == domain_part or host.endswith('.' + domain_part)):
						return True
				else:
					# Use fnmatch for other glob patterns
					if fnmatch.fnmatch(host, pattern):
						return True
			else:
				# Exact match
				if pattern.startswith(('http://', 'https://', 'chrome://', 'brave://', 'file://')):
					# Full URL pattern
					if url.startswith(pattern):
						return True
				else:
					# Domain-only pattern
					if host == pattern:
						return True

		return False

	# ========== Helper Methods ==========

	async def attach_all_watchdogs(self) -> None:
		"""Initialize and attach all watchdogs in one go."""
		from browser_use.browser.aboutblank_watchdog import AboutBlankWatchdog
		from browser_use.browser.crash_watchdog import CrashWatchdog
		from browser_use.browser.downloads_watchdog import DownloadsWatchdog
		from browser_use.browser.navigation_watchdog import NavigationWatchdog
		from browser_use.browser.storage_state_watchdog import StorageStateWatchdog

		watchdog_configs = [
			('_crash_watchdog', CrashWatchdog),
			('_downloads_watchdog', DownloadsWatchdog),
			('_navigation_watchdog', NavigationWatchdog),
			('_storage_state_watchdog', StorageStateWatchdog),
			('_aboutblank_watchdog', AboutBlankWatchdog),
		]

		for attr_name, watchdog_class in watchdog_configs:
			if not hasattr(self, attr_name) or getattr(self, attr_name) is None:
				try:
					watchdog = watchdog_class(event_bus=self.event_bus, browser_session=self)
					await watchdog.attach_to_session()
					setattr(self, attr_name, watchdog)
					logger.info(f'[Session] Initialized and attached {watchdog_class.__name__}')
				except Exception as e:
					logger.warning(f'[Session] Failed to initialize {watchdog_class.__name__}: {e}')
			else:
				# Watchdog already exists, don't re-initialize to avoid duplicate handlers
				logger.debug(f'[Session] {watchdog_class.__name__} already initialized, skipping')

	# ========== Navigation Helper Methods (merged from NavigationWatchdog) ==========

	# ========== Compatibility Methods for Old API ==========

	async def click(self, selector: str) -> None:
		"""Click an element by CSS selector (compatibility method)."""
		page = await self.get_current_page()
		await page.click(selector)

	async def get_dom_element_by_index(self, index: int) -> Any | None:
		"""Get DOM element by index (compatibility method)."""
		selector_map = await self.get_selector_map()
		return selector_map.get(index)

	async def execute_javascript(self, script: str) -> Any:
		"""Execute JavaScript in the current page (compatibility method)."""
		# Get current tab index
		current_page = await self.get_current_page()
		tab_index = self.get_tab_index(current_page) if current_page else 0

		# Dispatch the event and await the result
		event = self.event_bus.dispatch(ExecuteJavaScriptEvent(tab_index=tab_index, expression=script))
		result = await event.event_result()
		return result

	async def get_scroll_info(self, page: Page) -> tuple[int, int]:
		"""Get scroll position information for the current page (compatibility method)."""
		scroll_y = await page.evaluate('window.scrollY')
		viewport_height = await page.evaluate('window.innerHeight')
		total_height = await page.evaluate('document.documentElement.scrollHeight')
		# Convert to int to handle fractional pixels
		pixels_above = int(scroll_y)
		pixels_below = int(max(0, total_height - (scroll_y + viewport_height)))
		return pixels_above, pixels_below

	async def remove_highlights(self):
		"""
		Removes all highlight overlays and labels created by the highlightElement function (compatibility method).
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
			logger.debug(f'⚠️ Failed to remove highlights (this is usually ok): {type(e).__name__}: {e}')
			# Don't raise the error since this is not critical functionality

	# ========== PDF API Methods ==========

	def set_auto_download_pdfs(self, enabled: bool) -> None:
		"""
		Enable or disable automatic PDF downloading when PDFs are encountered.

		Args:
		    enabled: Whether to automatically download PDFs
		"""
		self._auto_download_pdfs = enabled
		logger.info(f'📄 PDF auto-download {"enabled" if enabled else "disabled"}')

	@property
	def auto_download_pdfs(self) -> bool:
		"""Get current PDF auto-download setting."""
		return self._auto_download_pdfs


# Import uuid7str for ID generation
try:
	from uuid_extensions import uuid7str
except ImportError:
	import uuid

	def uuid7str() -> str:
		return str(uuid.uuid4())


# Fix Pydantic circular dependency for all watchdogs
# This must be called after BrowserSession class is fully defined
_watchdog_modules = [
	'browser_use.browser.crash_watchdog.CrashWatchdog',
	'browser_use.browser.downloads_watchdog.DownloadsWatchdog',
	'browser_use.browser.storage_state_watchdog.StorageStateWatchdog',
	'browser_use.browser.navigation_watchdog.NavigationWatchdog',
	'browser_use.browser.aboutblank_watchdog.AboutBlankWatchdog',
]

for module_path in _watchdog_modules:
	try:
		module_name, class_name = module_path.rsplit('.', 1)
		module = __import__(module_name, fromlist=[class_name])
		watchdog_class = getattr(module, class_name)
		watchdog_class.model_rebuild()
	except Exception:
		pass  # Ignore if watchdog can't be imported or rebuilt
