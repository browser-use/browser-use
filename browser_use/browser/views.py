from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from browser_use.dom.history_tree_processor.service import DOMHistoryElement
from browser_use.dom.views import DOMState


# Pydantic
class TabInfo(BaseModel):
	"""Represents information about a browser tab"""

	page_id: int
	url: str
	title: str
	parent_page_id: Optional[int] = None  # parent page that contains this popup or cross-origin iframe


class GroupTabsAction(BaseModel):
	tab_ids: list[int]
	title: str
	color: Optional[str] = 'blue'


class UngroupTabsAction(BaseModel):
	tab_ids: list[int]


@dataclass
class BrowserState(DOMState):
	url: str
	title: str
	tabs: list[TabInfo]
	screenshot: Optional[str] = None
	pixels_above: int = 0
	pixels_below: int = 0
	browser_errors: list[str] = field(default_factory=list)


@dataclass
class BrowserStateHistory:
	url: str
	title: str
	tabs: list[TabInfo]
	interacted_element: list[DOMHistoryElement | None] | list[None]
	screenshot: Optional[str] = None

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


class ClickStatus(Enum):
	SUCCESS = 'success'
	NAVgitIGATION_SUCCESS = 'navigation_success'
	ERROR = 'error'
	DOWNLOAD_SUCCESS = 'download_success'
	NAVIGATION_DISALLOWED = 'navigation_disallowed'


@dataclass
class ClickConfig:
	timeouts: dict[str, int] = field(default_factory=lambda: {'click': 2, 'download': 5, 'navigation': 5, 'popup': 2})
	max_retries: int = 1
	initial_retry_delay: float = 1.0


@dataclass
class ClickResult:
	status: ClickStatus
	message: Optional[str] = None
	download_path: Optional[str] = None
	navigated_url: Optional[str] = None
