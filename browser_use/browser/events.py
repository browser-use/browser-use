"""Event definitions for browser communication."""

from typing import Any, Literal

from bubus import BaseEvent
from pydantic import Field

# ============================================================================
# Agent/Controller -> BrowserSession Events (High-level browser actions)
# ============================================================================


class NavigateToUrlEvent(BaseEvent):
	"""Navigate to a specific URL."""

	url: str
	wait_until: Literal['load', 'domcontentloaded', 'networkidle', 'commit'] = 'load'
	new_tab: bool = False
	timeout_ms: int | None = None


class ClickElementEvent(BaseEvent):
	"""Click an element by index."""

	index: int
	button: Literal['left', 'right', 'middle'] = 'left'
	click_count: int = 1
	expect_download: bool = False
	new_tab: bool = False


class TypeTextEvent(BaseEvent):
	"""Type text into an element."""

	index: int
	text: str
	clear_existing: bool = True


class ScrollEvent(BaseEvent):
	"""Scroll the page or element."""

	direction: Literal['up', 'down', 'left', 'right']
	amount: int  # pixels
	element_index: int | None = None  # None means scroll page


class SwitchTabEvent(BaseEvent):
	"""Switch to a different tab."""

	tab_index: int


class CloseTabEvent(BaseEvent):
	"""Close a tab."""

	tab_index: int


class ScreenshotRequestEvent(BaseEvent):
	"""Request to take a screenshot."""

	full_page: bool = False
	clip: dict[str, float] | None = None  # {x, y, width, height}


class BrowserStateRequestEvent(BaseEvent):
	"""Request current browser state."""

	include_dom: bool = True
	include_screenshot: bool = False
	cache_clickable_elements_hashes: bool = True


class WaitForConditionEvent(BaseEvent):
	"""Wait for a condition."""

	condition: Literal['navigation', 'selector', 'timeout', 'load_state']
	timeout: float = 30000
	selector: str | None = None
	state: Literal['attached', 'detached', 'visible', 'hidden'] | None = None


# ============================================================================


class StartBrowserEvent(BaseEvent):
	"""Start/connect to browser."""

	cdp_url: str | None = None
	launch_options: dict[str, Any] = Field(default_factory=dict)


class StopBrowserEvent(BaseEvent):
	"""Stop/disconnect from browser."""

	force: bool = False


class TabsInfoRequestEvent(BaseEvent):
	"""Get information about all open tabs."""

	pass


class GetPageInfoEvent(BaseEvent):
	"""Get information about a specific page."""

	tab_index: int


class ExecuteJavaScriptEvent(BaseEvent):
	"""Execute JavaScript in page context."""

	tab_index: int
	expression: str
	await_promise: bool = True


class SetViewportEvent(BaseEvent):
	"""Set the viewport size."""

	width: int
	height: int
	device_scale_factor: float = 1.0


class SetCookiesEvent(BaseEvent):
	"""Set browser cookies."""

	cookies: list[dict[str, Any]]


class GetCookiesEvent(BaseEvent):
	"""Get browser cookies."""

	urls: list[str] | None = None


# ============================================================================


class BrowserStartedEvent(BaseEvent):
	"""Browser has started/connected."""

	cdp_url: str
	browser_pid: int | None = None


class BrowserStoppedEvent(BaseEvent):
	"""Browser has stopped/disconnected."""

	reason: str | None = None


class TabCreatedEvent(BaseEvent):
	"""A new tab was created."""

	tab_index: int
	url: str


class TabClosedEvent(BaseEvent):
	"""A tab was closed."""

	tab_index: int


class TabUpdatedEvent(BaseEvent):
	"""Tab information updated (URL changed, etc.)."""

	tab_index: int
	url: str


class AgentFocusChangedEvent(BaseEvent):
	"""Agent focus changed to a different tab."""

	tab_index: int
	url: str


class PageCrashedEvent(BaseEvent):
	"""A page has crashed."""

	tab_index: int
	error: str


class NavigationStartedEvent(BaseEvent):
	"""Navigation started."""

	tab_index: int
	url: str


class NavigationCompleteEvent(BaseEvent):
	"""Navigation completed."""

	tab_index: int
	url: str
	status: int | None = None
	error_message: str | None = None  # Error/timeout message if navigation had issues
	loading_status: str | None = None  # Detailed loading status (e.g., network timeout info)


# ============================================================================
# Error Events
# ============================================================================


class BrowserErrorEvent(BaseEvent):
	"""An error occurred in the browser layer."""

	error_type: str
	message: str
	details: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Response Events (for request-response pattern)
# ============================================================================


class BrowserStateResponseEvent(BaseEvent):
	"""Response to BrowserStateRequestEvent."""

	state: Any  # BrowserStateSummary object


class ScreenshotResponseEvent(BaseEvent):
	"""Response to ScreenshotRequestEvent."""

	screenshot: str  # base64 encoded
	error: str | None = None


class TabsInfoResponseEvent(BaseEvent):
	"""Response to TabsInfoRequestEvent."""

	tabs: list[dict[str, Any]]


# ============================================================================
# Storage State Events
# ============================================================================


class SaveStorageStateEvent(BaseEvent):
	"""Request to save browser storage state."""

	path: str | None = None  # Optional path, uses profile default if not provided


class StorageStateSavedEvent(BaseEvent):
	"""Notification that storage state was saved."""

	path: str
	cookies_count: int
	origins_count: int


class LoadStorageStateEvent(BaseEvent):
	"""Request to load browser storage state."""

	path: str | None = None  # Optional path, uses profile default if not provided


class StorageStateLoadedEvent(BaseEvent):
	"""Notification that storage state was loaded."""

	path: str
	cookies_count: int
	origins_count: int


# ============================================================================
# File Download Events
# ============================================================================


class FileDownloadedEvent(BaseEvent):
	"""A file has been downloaded."""

	url: str
	path: str
	file_name: str
	file_size: int
	file_type: str | None = None  # e.g., 'pdf', 'zip', 'docx', etc.
	mime_type: str | None = None  # e.g., 'application/pdf'
	from_cache: bool = False
	auto_download: bool = False  # Whether this was an automatic download (e.g., PDF auto-download)
