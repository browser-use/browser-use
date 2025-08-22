from dataclasses import dataclass, field
from typing import Any

from bubus import BaseEvent
from cdp_use.cdp.target import TargetID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_serializer

from browser_use.dom.views import DOMInteractedElement, SerializedDOMState

# Known placeholder image data for about:blank pages - a 4x4 white PNG
PLACEHOLDER_4PX_SCREENSHOT = (
	'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGP8//8/AwwwMSAB3BwAlm4DBfIlvvkAAAAASUVORK5CYII='
)


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
	
	# Python-based highlighting fields
	highlighted_screenshot: str | None = field(default=None, repr=False)  # Screenshot with bounding boxes
	
	def get_highlighted_screenshot(
		self, 
		include_indices: set[int] | None = None,
		exclude_indices: set[int] | None = None,
		force_regenerate: bool = False
	) -> str | None:
		"""
		Get a highlighted screenshot with bounding boxes around interactive elements.
		
		Args:
			include_indices: Set of indices to include (if None, include all)
			exclude_indices: Set of indices to exclude
			force_regenerate: Whether to regenerate even if cached version exists
			
		Returns:
			Base64 encoded highlighted screenshot or None if screenshot unavailable
		"""
		if not self.screenshot:
			return None
			
		# Use cached version if available and no custom filters
		if (not force_regenerate and 
			include_indices is None and 
			exclude_indices is None and 
			self.highlighted_screenshot):
			return self.highlighted_screenshot
			
		# Generate highlighted screenshot
		try:
			from browser_use.dom.debug.python_highlights import create_highlighted_image
			
			highlighted = create_highlighted_image(
				screenshot_b64=self.screenshot,
				selector_map=self.dom_state.selector_map,
				include_indices=include_indices,
				exclude_indices=exclude_indices,
				show_index_labels=True,
				box_thickness=2,
			)
			
			# Cache if no custom filters were applied
			if include_indices is None and exclude_indices is None:
				self.highlighted_screenshot = highlighted
				
			return highlighted
			
		except Exception as e:
			# Fall back to original screenshot if highlighting fails
			return self.screenshot
	
	def get_image_pair(
		self,
		include_indices: set[int] | None = None,
		exclude_indices: set[int] | None = None,
	) -> tuple[str | None, str | None]:
		"""
		Get both unhighlighted and highlighted screenshots as a pair.
		
		This is optimized for quickly getting both versions for merging.
		
		Args:
			include_indices: Set of indices to include (if None, include all)
			exclude_indices: Set of indices to exclude
			
		Returns:
			Tuple of (unhighlighted_screenshot, highlighted_screenshot)
		"""
		if not self.screenshot:
			return None, None
			
		try:
			from browser_use.dom.debug.python_highlights import create_image_pair
			
			return create_image_pair(
				screenshot_b64=self.screenshot,
				selector_map=self.dom_state.selector_map,
				include_indices=include_indices,
				exclude_indices=exclude_indices,
			)
			
		except Exception:
			# Fall back to returning just the original screenshot
			return self.screenshot, self.screenshot


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
	"""Base class for all browser errors"""

	message: str
	details: dict[str, Any] | None = None
	while_handling_event: BaseEvent[Any] | None = None

	def __init__(self, message: str, details: dict[str, Any] | None = None, event: BaseEvent[Any] | None = None):
		self.message = message
		super().__init__(message)
		self.details = details
		self.while_handling_event = event

	def __str__(self) -> str:
		if self.details:
			return f'{self.message} ({self.details}) during: {self.while_handling_event}'
		elif self.while_handling_event:
			return f'{self.message} (while handling: {self.while_handling_event})'
		else:
			return self.message


class URLNotAllowedError(BrowserError):
	"""Error raised when a URL is not allowed"""
