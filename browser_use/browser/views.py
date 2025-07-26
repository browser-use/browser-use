from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from browser_use.dom.history_tree_processor.service import DOMHistoryElement
from browser_use.dom.views import DOMState

# Known placeholder image data for about:blank pages - a 4x4 white PNG
PLACEHOLDER_4PX_SCREENSHOT = (
	'iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGP8//8/AwwwMSAB3BwAlm4DBfIlvvkAAAAASUVORK5CYII='
)


# Pydantic
class TabInfo(BaseModel):
	"""Represents information about a browser tab"""

	page_id: int
	url: str
	title: str
	parent_page_id: int | None = None  # parent page that contains this popup or cross-origin iframe


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
class BrowserStateSummary(DOMState):
	"""The summary of the browser's current state designed for an LLM to process"""

	# provided by DOMState:
	# element_tree: DOMElementNode
	# selector_map: SelectorMap

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


@dataclass
class BrowserStateHistory:
	"""The summary of the browser's state at a past point in time to usse in LLM message history"""

	url: str
	title: str
	tabs: list[TabInfo]
	interacted_element: list[DOMHistoryElement | None] | list[None]
	screenshot: str | None = None

	def to_dict(self) -> dict[str, Any]:
		data = {}
		data['tabs'] = [tab.model_dump() for tab in self.tabs]
		data['screenshot'] = self.screenshot
		data['interacted_element'] = [el.to_dict() if el else None for el in self.interacted_element]
		data['url'] = self.url
		data['title'] = self.title
		return data


class BrowserError(Exception):
	"""Base class for all browser errors"""


class URLNotAllowedError(BrowserError):
	"""Error raised when a URL is not allowed"""
