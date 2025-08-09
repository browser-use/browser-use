"""Event definitions for browser communication."""

from typing import Any, Literal

from bubus import BaseEvent
from bubus.models import T_EventResultType
from pydantic import Field, field_validator

from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import EnhancedDOMTreeNode

# ============================================================================
# Agent/Controller -> BrowserSession Events (High-level browser actions)
# ============================================================================


class ElementSelectedEvent(BaseEvent[T_EventResultType]):
	"""An element was selected."""

	node: EnhancedDOMTreeNode

	@field_validator('node', mode='before')
	@classmethod
	def serialize_node(cls, data: EnhancedDOMTreeNode | None) -> EnhancedDOMTreeNode | None:
		if data is None:
			return None
		return EnhancedDOMTreeNode(
			element_index=data.element_index,
			node_id=data.node_id,
			backend_node_id=data.backend_node_id,
			session_id=data.session_id,
			frame_id=data.frame_id,
			target_id=data.target_id,
			node_type=data.node_type,
			node_name=data.node_name,
			node_value=data.node_value,
			attributes=data.attributes,
			is_scrollable=data.is_scrollable,
			is_visible=data.is_visible,
			absolute_position=data.absolute_position,
			# override the circular reference fields in EnhancedDOMTreeNode as they cant be serialized and aren't needed by event handlers
			content_document=None,
			shadow_root_type=None,
			shadow_roots=[],
			parent_node=None,
			children_nodes=[],
			ax_node=None,
			snapshot_node=None,
		)


class NavigateToUrlEvent(BaseEvent):
	"""Navigate to a specific URL."""

	url: str
	wait_until: Literal['load', 'domcontentloaded', 'networkidle', 'commit'] = 'load'
	new_tab: bool = False
	timeout_ms: int | None = None


class ClickElementEvent(ElementSelectedEvent[dict[str, str] | None]):
	"""Click an element."""

	node: 'EnhancedDOMTreeNode'
	button: Literal['left', 'right', 'middle'] = 'left'
	new_tab: bool = False
	# click_count: int = 1           # TODO
	# expect_download: bool = False  # moved to downloads_watchdog.py


class TypeTextEvent(ElementSelectedEvent):
	"""Type text into an element."""

	node: 'EnhancedDOMTreeNode'
	text: str
	clear_existing: bool = True


class ScrollEvent(ElementSelectedEvent):
	"""Scroll the page or element."""

	direction: Literal['up', 'down', 'left', 'right']
	amount: int  # pixels
	node: 'EnhancedDOMTreeNode | None' = None  # None means scroll page


class SwitchTabEvent(BaseEvent):
	"""Switch to a different tab."""

	tab_index: int


class CloseTabEvent(BaseEvent):
	"""Close a tab."""

	tab_index: int


class ScreenshotEvent(BaseEvent):
	"""Request to take a screenshot."""

	full_page: bool = False
	clip: dict[str, float] | None = None  # {x, y, width, height}


class BrowserStateRequestEvent(BaseEvent[BrowserStateSummary]):
	"""Request current browser state."""

	include_dom: bool = True
	include_screenshot: bool = False
	cache_clickable_elements_hashes: bool = True
	include_recent_events: bool = False


# class WaitForConditionEvent(BaseEvent):
# 	"""Wait for a condition."""

# 	condition: Literal['navigation', 'selector', 'timeout', 'load_state']
# 	timeout: float = 30000
# 	selector: str | None = None
# 	state: Literal['attached', 'detached', 'visible', 'hidden'] | None = None


class GoBackEvent(BaseEvent):
	"""Navigate back in browser history."""

	pass


class GoForwardEvent(BaseEvent):
	"""Navigate forward in browser history."""

	pass


class RefreshEvent(BaseEvent):
	"""Refresh/reload the current page."""

	pass


class WaitEvent(BaseEvent):
	"""Wait for a specified number of seconds."""

	seconds: float = 3.0
	max_seconds: float = 10.0  # Safety cap


class SendKeysEvent(BaseEvent):
	"""Send keyboard keys/shortcuts."""

	keys: str  # e.g., "ctrl+a", "cmd+c", "Enter"


class UploadFileEvent(ElementSelectedEvent):
	"""Upload a file to an element."""

	node: 'EnhancedDOMTreeNode'
	file_path: str


class ScrollToTextEvent(BaseEvent):
	"""Scroll to specific text on the page."""

	text: str
	direction: Literal['up', 'down'] = 'down'


# ============================================================================


class BrowserStartEvent(BaseEvent):
	"""Start/connect to browser."""

	cdp_url: str | None = None
	launch_options: dict[str, Any] = Field(default_factory=dict)


class BrowserStopEvent(BaseEvent):
	"""Stop/disconnect from browser."""

	force: bool = False


class BrowserLaunchEvent(BaseEvent[dict[str, str]]):
	"""Launch a local browser process."""

	pass


class BrowserKillEvent(BaseEvent):
	"""Kill local browser subprocess."""

	pass


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
# DOM-related Events
# ============================================================================


class BrowserConnectedEvent(BaseEvent):
	"""Browser has started/connected."""

	cdp_url: str


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


class TargetCrashedEvent(BaseEvent):
	"""A target has crashed."""

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


class AboutBlankDVDScreensaverShownEvent(BaseEvent):
	"""AboutBlankWatchdog has shown DVD screensaver animation on an about:blank tab."""

	tab_index: int
	error: str | None = None


# Note: Model rebuilding for forward references is handled in the importing modules
# Events with 'EnhancedDOMTreeNode' forward references (ClickElementEvent, TypeTextEvent,
# ScrollEvent, UploadFileEvent) need model_rebuild() called after imports are complete

# check that event names are valid and non-overlapping (naiively n^2 so it's pretty slow but ok for now, optimize when >20 events)
event_names = {
	name.split('[')[0]
	for name in globals().keys()
	if not name.startswith('_') and issubclass(globals()[name], BaseEvent) and name != 'BaseEvent'
}
for name_a in event_names:
	assert name_a.endswith('Event'), f'Event with name {name_a} does not end with "Event"'
	for name_b in event_names:
		if name_a != name_b:  # Skip self-comparison
			assert name_a not in name_b, (
				f'Event with name {name_a} is a substring of {name_b}, all events must be completely unique to avoid find-and-replace accidents'
			)
