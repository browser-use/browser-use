from dataclasses import dataclass, field
from typing import Any

from bubus import BaseEvent
from cdp_use.cdp.target import TargetID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_serializer

from browser_use.dom.views import DOMInteractedElement, SerializedDOMState

# about:blank pages yield a 4x4 blank image carrying no information, so it is filtered out of
# prompts and GIFs. Size is the test rather than an exact byte match: the encoding is whatever
# SCREENSHOT_FORMAT is, and the bytes also vary with the Chrome build. A 4x4 image is a few
# hundred bytes in any codec while a real viewport capture is tens of kilobytes, so the
# threshold sits two orders of magnitude clear of both.
PLACEHOLDER_SCREENSHOT_MAX_BYTES = 1024


def is_placeholder_screenshot(screenshot_b64: str | None) -> bool:
	"""True if a base64 screenshot is the blank placeholder rather than a real capture."""
	if not screenshot_b64:
		return True
	# base64 encodes 3 bytes per 4 chars; compare on the encoded length to avoid decoding.
	return len(screenshot_b64) * 3 // 4 <= PLACEHOLDER_SCREENSHOT_MAX_BYTES


# Screenshots go to the model as WebP, not PNG. At identical dimensions WebP is ~60%
# smaller on average and ~5x smaller at the tail (p99 957KB -> 176KB on real agent
# traces), which cuts upload time on the client -> gateway hop. Chrome encodes WebP
# natively via CDP, so this is cheaper than capturing PNG and re-encoding.
# Resolution is unchanged - only the encoding differs.
SCREENSHOT_FORMAT = 'webp'
SCREENSHOT_QUALITY = 90
SCREENSHOT_MEDIA_TYPE = 'image/webp'


# Pydantic
class TabInfo(BaseModel):
	"""Represents information about a browser tab"""

	model_config = ConfigDict(
		extra='forbid',
		validate_by_name=True,
		validate_by_alias=True,
		populate_by_name=True,
	)

	# Original fields
	url: str
	title: str
	target_id: TargetID = Field(serialization_alias='tab_id', validation_alias=AliasChoices('tab_id', 'target_id'))
	parent_target_id: TargetID | None = Field(
		default=None, serialization_alias='parent_tab_id', validation_alias=AliasChoices('parent_tab_id', 'parent_target_id')
	)  # parent page that contains this popup or cross-origin iframe

	@field_serializer('target_id')
	def serialize_target_id(self, target_id: TargetID, _info: Any) -> str:
		return target_id[-4:]

	@field_serializer('parent_target_id')
	def serialize_parent_target_id(self, parent_target_id: TargetID | None, _info: Any) -> str | None:
		return parent_target_id[-4:] if parent_target_id else None


class PageInfo(BaseModel):
	"""Comprehensive page size and scroll information"""

	# Current viewport dimensions
	viewport_width: int
	viewport_height: int

	# Total page dimensions
	page_width: int
	page_height: int

	# Current scroll position
	scroll_x: int
	scroll_y: int

	# Calculated scroll information
	pixels_above: int
	pixels_below: int
	pixels_left: int
	pixels_right: int

	# Page statistics are now computed dynamically instead of stored


@dataclass
class NetworkRequest:
	"""Information about a pending network request"""

	url: str
	method: str = 'GET'
	loading_duration_ms: float = 0.0  # How long this request has been loading (ms since request started, max 10s)
	resource_type: str | None = None  # e.g., 'Document', 'Stylesheet', 'Image', 'Script', 'XHR', 'Fetch'


@dataclass
class PaginationButton:
	"""Information about a pagination button detected on the page"""

	button_type: str  # 'next', 'prev', 'first', 'last', 'page_number'
	backend_node_id: int  # Backend node ID for clicking
	text: str  # Button text/label
	selector: str  # XPath or other selector to locate the element
	selector_index: int | None = None  # Model-visible selector index
	is_disabled: bool = False  # Whether the button appears disabled


@dataclass
class BrowserStateSummary:
	"""The summary of the browser's current state designed for an LLM to process"""

	# provided by SerializedDOMState:
	dom_state: SerializedDOMState

	url: str
	title: str
	tabs: list[TabInfo]
	screenshot: str | None = field(default=None, repr=False)
	page_info: PageInfo | None = None  # Enhanced page information

	# Keep legacy fields for backward compatibility
	pixels_above: int = 0
	pixels_below: int = 0
	browser_errors: list[str] = field(default_factory=list)
	is_pdf_viewer: bool = False  # Whether the current page is a PDF viewer
	recent_events: str | None = None  # Text summary of recent browser events
	pending_network_requests: list[NetworkRequest] = field(default_factory=list)  # Currently loading network requests
	pagination_buttons: list[PaginationButton] = field(default_factory=list)  # Detected pagination buttons
	closed_popup_messages: list[str] = field(default_factory=list)  # Messages from auto-closed JavaScript dialogs
	state_error: str | None = None  # Safe, model-visible explanation when the current state could not be captured


@dataclass
class BrowserStateHistory:
	"""The summary of the browser's state at a past point in time to usse in LLM message history"""

	url: str
	title: str
	tabs: list[TabInfo]
	interacted_element: list[DOMInteractedElement | None] | list[None]
	screenshot_path: str | None = None

	def get_screenshot(self) -> str | None:
		"""Load screenshot from disk and return as base64 string"""
		if not self.screenshot_path:
			return None

		import base64
		from pathlib import Path

		path_obj = Path(self.screenshot_path)
		if not path_obj.exists():
			return None

		try:
			with open(path_obj, 'rb') as f:
				screenshot_data = f.read()
			return base64.b64encode(screenshot_data).decode('utf-8')
		except Exception:
			return None

	def to_dict(self) -> dict[str, Any]:
		data = {}
		data['tabs'] = [tab.model_dump() for tab in self.tabs]
		data['screenshot_path'] = self.screenshot_path
		data['interacted_element'] = [el.to_dict() if el else None for el in self.interacted_element]
		data['url'] = self.url
		data['title'] = self.title
		return data


class BrowserError(Exception):
	"""Browser error with structured memory for LLM context management.

	This exception class provides separate memory contexts for browser actions:
	- short_term_memory: Immediate context shown once to the LLM for the next action
	- long_term_memory: Persistent error information stored across steps
	"""

	message: str
	short_term_memory: str | None = None
	long_term_memory: str | None = None
	details: dict[str, Any] | None = None
	while_handling_event: BaseEvent[Any] | None = None

	def __init__(
		self,
		message: str,
		short_term_memory: str | None = None,
		long_term_memory: str | None = None,
		details: dict[str, Any] | None = None,
		event: BaseEvent[Any] | None = None,
	):
		"""Initialize a BrowserError with structured memory contexts.

		Args:
			message: Technical error message for logging and debugging
			short_term_memory: Context shown once to LLM (e.g., available actions, options)
			long_term_memory: Persistent error info stored in agent memory
			details: Additional metadata for debugging
			event: The browser event that triggered this error
		"""
		self.message = message
		self.short_term_memory = short_term_memory
		self.long_term_memory = long_term_memory
		self.details = details
		self.while_handling_event = event
		super().__init__(message)

	def __str__(self) -> str:
		parts = [self.message]
		if self.details:
			parts.append(f'({self.details})')
		if self.while_handling_event:
			parts.append(f'during: {self.while_handling_event}')
		return ' '.join(parts)


class URLNotAllowedError(BrowserError):
	"""Error raised when a URL is not allowed"""
