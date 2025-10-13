"""Event definitions for browser communication."""

import inspect
import os
from typing import Any, Literal

from bubus import BaseEvent
from bubus.models import T_EventResultType
from cdp_use.cdp.target import TargetID
from pydantic import BaseModel, Field, field_validator

from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import EnhancedDOMTreeNode


def _get_timeout(env_var: str, default: float) -> float | None:
	"""
	Safely parse environment variable timeout values with robust error handling.

	Args:
		env_var: Environment variable name (e.g. 'TIMEOUT_NavigateToUrlEvent')
		default: Default timeout value as float (e.g. 15.0)

	Returns:
		Parsed float value or the default if parsing fails

	Raises:
		ValueError: Only if both env_var and default are invalid (should not happen with valid defaults)
	"""
	# Try environment variable first
	env_value = os.getenv(env_var)
	if env_value:
		try:
			parsed = float(env_value)
			if parsed < 0:
				print(f'Warning: {env_var}={env_value} is negative, using default {default}')
				return default
			return parsed
		except (ValueError, TypeError):
			print(f'Warning: {env_var}={env_value} is not a valid number, using default {default}')

	# Fall back to default
	return default


# ============================================================================
# Agent/Tools -> BrowserSession Events (High-level browser actions)
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
			# only used internally by the DOM service during DOM tree building process, not intended public API use
			content_document=None,
			shadow_root_type=None,
			shadow_roots=[],
			parent_node=None,
			children_nodes=[],
			ax_node=None,
			snapshot_node=None,
		)


# TODO: add page handle to events
# class PageHandle(share a base with browser.session.CDPSession?):
# 	url: str
# 	target_id: TargetID
#   @classmethod
#   def from_target_id(cls, target_id: TargetID) -> Self:
#     return cls(target_id=target_id)
#   @classmethod
#   def from_target_id(cls, target_id: TargetID) -> Self:
#     return cls(target_id=target_id)
#   @classmethod
#   def from_url(cls, url: str) -> Self:
#   @property
#   def root_frame_id(self) -> str:
#     return self.target_id
#   @property
#   def session_id(self) -> str:
#     return browser_session.get_or_create_cdp_session(self.target_id).session_id

# class PageSelectedEvent(BaseEvent[T_EventResultType]):
# 	"""An event like SwitchToTabEvent(page=PageHandle) or CloseTabEvent(page=PageHandle)"""
# 	page: PageHandle


class NavigateToUrlEvent(BaseEvent[None]):
	"""Navigate to a specific URL."""

	url: str
	wait_until: Literal['load', 'domcontentloaded', 'networkidle', 'commit'] = 'load'
	timeout_ms: int | None = None
	new_tab: bool = Field(
		default=False, description='Set True to leave the current tab alone and open a new tab in the foreground for the new URL'
	)
	# existing_tab: PageHandle | None = None  # TODO

	# time limits enforced by bubus, not exposed to LLM:
	event_timeout: float | None = _get_timeout('TIMEOUT_NavigateToUrlEvent', 15.0)  # seconds


class ClickElementEvent(ElementSelectedEvent[dict[str, Any] | None]):
	"""Click an element."""

	node: 'EnhancedDOMTreeNode'
	button: Literal['left', 'right', 'middle'] = 'left'
	# click_count: int = 1           # TODO
	# expect_download: bool = False  # moved to downloads_watchdog.py

	event_timeout: float | None = _get_timeout('TIMEOUT_ClickElementEvent', 15.0)  # seconds


class TypeTextEvent(ElementSelectedEvent[dict | None]):
	"""Type text into an element."""

	node: 'EnhancedDOMTreeNode'
	text: str
	clear: bool = True
	is_sensitive: bool = False  # Flag to indicate if text contains sensitive data
	sensitive_key_name: str | None = None  # Name of the sensitive key being typed (e.g., 'username', 'password')

	event_timeout: float | None = _get_timeout('TIMEOUT_TypeTextEvent', 15.0)  # seconds


class ScrollEvent(ElementSelectedEvent[None]):
	"""Scroll the page or element."""

	direction: Literal['up', 'down', 'left', 'right']
	amount: int  # pixels
	node: 'EnhancedDOMTreeNode | None' = None  # None means scroll page

	event_timeout: float | None = _get_timeout('TIMEOUT_ScrollEvent', 8.0)  # seconds


class SwitchTabEvent(BaseEvent[TargetID]):
	"""Switch to a different tab."""

	target_id: TargetID | None = Field(default=None, description='None means switch to the most recently opened tab')

	event_timeout: float | None = _get_timeout('TIMEOUT_SwitchTabEvent', 10.0)  # seconds


class CloseTabEvent(BaseEvent[None]):
	"""Close a tab."""

	target_id: TargetID

	event_timeout: float | None = _get_timeout('TIMEOUT_CloseTabEvent', 10.0)  # seconds


class ScreenshotEvent(BaseEvent[str]):
	"""Request to take a screenshot."""

	full_page: bool = False
	clip: dict[str, float] | None = None  # {x, y, width, height}

	event_timeout: float | None = _get_timeout('TIMEOUT_ScreenshotEvent', 8.0)  # seconds


class BrowserStateRequestEvent(BaseEvent[BrowserStateSummary]):
	"""Request current browser state."""

	include_dom: bool = True
	include_screenshot: bool = True
	include_recent_events: bool = False

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserStateRequestEvent', 30.0)  # seconds


# class WaitForConditionEvent(BaseEvent):
# 	"""Wait for a condition."""

# 	condition: Literal['navigation', 'selector', 'timeout', 'load_state']
# 	timeout: float = 30000
# 	selector: str | None = None
# 	state: Literal['attached', 'detached', 'visible', 'hidden'] | None = None


class GoBackEvent(BaseEvent[None]):
	"""Navigate back in browser history."""

	event_timeout: float | None = _get_timeout('TIMEOUT_GoBackEvent', 15.0)  # seconds


class GoForwardEvent(BaseEvent[None]):
	"""Navigate forward in browser history."""

	event_timeout: float | None = _get_timeout('TIMEOUT_GoForwardEvent', 15.0)  # seconds


class RefreshEvent(BaseEvent[None]):
	"""Refresh/reload the current page."""

	event_timeout: float | None = _get_timeout('TIMEOUT_RefreshEvent', 15.0)  # seconds


class WaitEvent(BaseEvent[None]):
	"""Wait for a specified number of seconds."""

	seconds: float = 3.0
	max_seconds: float = 10.0  # Safety cap

	event_timeout: float | None = _get_timeout('TIMEOUT_WaitEvent', 60.0)  # seconds


class SendKeysEvent(BaseEvent[None]):
	"""Send keyboard keys/shortcuts."""

	keys: str  # e.g., "ctrl+a", "cmd+c", "Enter"

	event_timeout: float | None = _get_timeout('TIMEOUT_SendKeysEvent', 15.0)  # seconds


class UploadFileEvent(ElementSelectedEvent[None]):
	"""Upload a file to an element."""

	node: 'EnhancedDOMTreeNode'
	file_path: str

	event_timeout: float | None = _get_timeout('TIMEOUT_UploadFileEvent', 30.0)  # seconds


class GetDropdownOptionsEvent(ElementSelectedEvent[dict[str, str]]):
	"""Get all options from any dropdown (native <select>, ARIA menus, or custom dropdowns).

	Returns a dict containing dropdown type, options list, and element metadata."""

	node: 'EnhancedDOMTreeNode'

	event_timeout: float | None = _get_timeout(
		'TIMEOUT_GetDropdownOptionsEvent',
		15.0,
	)  # some dropdowns lazy-load the list of options on first interaction, so we need to wait for them to load (e.g. table filter lists can have thousands of options)


class SelectDropdownOptionEvent(ElementSelectedEvent[dict[str, str]]):
	"""Select a dropdown option by exact text from any dropdown type.

	Returns a dict containing success status and selection details."""

	node: 'EnhancedDOMTreeNode'
	text: str  # The option text to select

	event_timeout: float | None = _get_timeout('TIMEOUT_SelectDropdownOptionEvent', 8.0)  # seconds


class ScrollToTextEvent(BaseEvent[None]):
	"""Scroll to specific text on the page. Raises exception if text not found."""

	text: str
	direction: Literal['up', 'down'] = 'down'

	event_timeout: float | None = _get_timeout('TIMEOUT_ScrollToTextEvent', 15.0)  # seconds


# ============================================================================


class BrowserStartEvent(BaseEvent):
	"""Start/connect to browser."""

	cdp_url: str | None = None
	launch_options: dict[str, Any] = Field(default_factory=dict)

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserStartEvent', 30.0)  # seconds


class BrowserStopEvent(BaseEvent):
	"""Stop/disconnect from browser."""

	force: bool = False

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserStopEvent', 45.0)  # seconds


class BrowserLaunchResult(BaseModel):
	"""Result of launching a browser."""

	# TODO: add browser executable_path, pid, version, latency, user_data_dir, X11 $DISPLAY, host IP address, etc.
	cdp_url: str


class BrowserLaunchEvent(BaseEvent[BrowserLaunchResult]):
	"""Launch a local browser process."""

	# TODO: add executable_path, proxy settings, preferences, extra launch args, etc.

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserLaunchEvent', 30.0)  # seconds


class BrowserKillEvent(BaseEvent):
	"""Kill local browser subprocess."""

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserKillEvent', 30.0)  # seconds


# TODO: replace all Runtime.evaluate() calls with this event
# class ExecuteJavaScriptEvent(BaseEvent):
# 	"""Execute JavaScript in page context."""

# 	target_id: TargetID
# 	expression: str
# 	await_promise: bool = True

# 	event_timeout: float | None = 60.0  # seconds

# TODO: add this and use the old BrowserProfile.viewport options to set it
# class SetViewportEvent(BaseEvent):
# 	"""Set the viewport size."""

# 	width: int
# 	height: int
# 	device_scale_factor: float = 1.0

# 	event_timeout: float | None = 15.0  # seconds


# Moved to storage state
# class SetCookiesEvent(BaseEvent):
# 	"""Set browser cookies."""

# 	cookies: list[dict[str, Any]]

# 	event_timeout: float | None = (
# 		30.0  # only long to support the edge case of restoring a big localStorage / on many origins (has to O(n) visit each origin to restore)
# 	)


# class GetCookiesEvent(BaseEvent):
# 	"""Get browser cookies."""

# 	urls: list[str] | None = None

# 	event_timeout: float | None = 30.0  # seconds


# ============================================================================
# DOM-related Events
# ============================================================================


class BrowserConnectedEvent(BaseEvent):
	"""Browser has started/connected."""

	cdp_url: str

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserConnectedEvent', 30.0)  # seconds


class BrowserStoppedEvent(BaseEvent):
	"""Browser has stopped/disconnected."""

	reason: str | None = None

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserStoppedEvent', 30.0)  # seconds


class TabCreatedEvent(BaseEvent):
	"""A new tab was created."""

	target_id: TargetID
	url: str

	event_timeout: float | None = _get_timeout('TIMEOUT_TabCreatedEvent', 30.0)  # seconds


class TabClosedEvent(BaseEvent):
	"""A tab was closed."""

	target_id: TargetID

	# TODO:
	# new_focus_target_id: int | None = None
	# new_focus_url: str | None = None

	event_timeout: float | None = _get_timeout('TIMEOUT_TabClosedEvent', 10.0)  # seconds


# TODO: emit this when DOM changes significantly, inner frame navigates, form submits, history.pushState(), etc.
# class TabUpdatedEvent(BaseEvent):
# 	"""Tab information updated (URL changed, etc.)."""

# 	target_id: TargetID
# 	url: str


class AgentFocusChangedEvent(BaseEvent):
	"""Agent focus changed to a different tab."""

	target_id: TargetID
	url: str

	event_timeout: float | None = _get_timeout('TIMEOUT_AgentFocusChangedEvent', 10.0)  # seconds


class TargetCrashedEvent(BaseEvent):
	"""A target has crashed."""

	target_id: TargetID
	error: str

	event_timeout: float | None = _get_timeout('TIMEOUT_TargetCrashedEvent', 10.0)  # seconds


class NavigationStartedEvent(BaseEvent):
	"""Navigation started."""

	target_id: TargetID
	url: str

	event_timeout: float | None = _get_timeout('TIMEOUT_NavigationStartedEvent', 30.0)  # seconds


class NavigationCompleteEvent(BaseEvent):
	"""Navigation completed."""

	target_id: TargetID
	url: str
	status: int | None = None
	error_message: str | None = None  # Error/timeout message if navigation had issues
	loading_status: str | None = None  # Detailed loading status (e.g., network timeout info)

	event_timeout: float | None = _get_timeout('TIMEOUT_NavigationCompleteEvent', 30.0)  # seconds


# ============================================================================
# Error Events
# ============================================================================


class BrowserErrorEvent(BaseEvent):
	"""An error occurred in the browser layer."""

	error_type: str
	message: str
	details: dict[str, Any] = Field(default_factory=dict)

	event_timeout: float | None = _get_timeout('TIMEOUT_BrowserErrorEvent', 30.0)  # seconds


# ============================================================================
# Storage State Events
# ============================================================================


class SaveStorageStateEvent(BaseEvent):
	"""Request to save browser storage state."""

	path: str | None = None  # Optional path, uses profile default if not provided

	event_timeout: float | None = _get_timeout('TIMEOUT_SaveStorageStateEvent', 45.0)  # seconds


class StorageStateSavedEvent(BaseEvent):
	"""Notification that storage state was saved."""

	path: str
	cookies_count: int
	origins_count: int

	event_timeout: float | None = _get_timeout('TIMEOUT_StorageStateSavedEvent', 30.0)  # seconds


class LoadStorageStateEvent(BaseEvent):
	"""Request to load browser storage state."""

	path: str | None = None  # Optional path, uses profile default if not provided

	event_timeout: float | None = _get_timeout('TIMEOUT_LoadStorageStateEvent', 45.0)  # seconds


# TODO: refactor this to:
# - on_BrowserConnectedEvent() -> dispatch(LoadStorageStateEvent()) -> _copy_storage_state_from_json_to_browser(json_file, new_cdp_session) + return storage_state from handler
# - on_BrowserStopEvent() -> dispatch(SaveStorageStateEvent()) -> _copy_storage_state_from_browser_to_json(new_cdp_session, json_file)
# and get rid of StorageStateSavedEvent and StorageStateLoadedEvent, have the original events + provide handler return values for any results
class StorageStateLoadedEvent(BaseEvent):
	"""Notification that storage state was loaded."""

	path: str
	cookies_count: int
	origins_count: int

	event_timeout: float | None = _get_timeout('TIMEOUT_StorageStateLoadedEvent', 30.0)  # seconds


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

	event_timeout: float | None = _get_timeout('TIMEOUT_FileDownloadedEvent', 30.0)  # seconds


class AboutBlankDVDScreensaverShownEvent(BaseEvent):
	"""AboutBlankWatchdog has shown DVD screensaver animation on an about:blank tab."""

	target_id: TargetID
	error: str | None = None


class DialogOpenedEvent(BaseEvent):
	"""Event dispatched when a JavaScript dialog is opened and handled."""

	dialog_type: str  # 'alert', 'confirm', 'prompt', or 'beforeunload'
	message: str
	url: str
	frame_id: str | None = None  # Can be None when frameId is not provided by CDP
	# target_id: TargetID   # TODO: add this to avoid needing target_id_from_frame() later


# Note: Model rebuilding for forward references is handled in the importing modules
# Events with 'EnhancedDOMTreeNode' forward references (ClickElementEvent, TypeTextEvent,
# ScrollEvent, UploadFileEvent) need model_rebuild() called after imports are complete


def _check_event_names_dont_overlap():
	"""
	check that event names defined in this file are valid and non-overlapping
	(naiively n^2 so it's pretty slow but ok for now, optimize when >20 events)
	"""
	event_names = {
		name.split('[')[0]
		for name in globals().keys()
		if not name.startswith('_')
		and inspect.isclass(globals()[name])
		and issubclass(globals()[name], BaseEvent)
		and name != 'BaseEvent'
	}
	for name_a in event_names:
		assert name_a.endswith('Event'), f'Event with name {name_a} does not end with "Event"'
		for name_b in event_names:
			if name_a != name_b:  # Skip self-comparison
				assert name_a not in name_b, (
					f'Event with name {name_a} is a substring of {name_b}, all events must be completely unique to avoid find-and-replace accidents'
				)


# overlapping event names are a nightmare to trace and rename later, dont do it!
# e.g. prevent ClickEvent and FailedClickEvent are terrible names because one is a substring of the other,
# must be ClickEvent and ClickFailedEvent to preserve the usefulnes of codebase grep/sed/awk as refactoring tools.
# at import time, we do a quick check that all event names defined above are valid and non-overlapping.
# this is hand written in blood by a human! not LLM slop. feel free to optimize but do not remove it without a good reason.
_check_event_names_dont_overlap()
