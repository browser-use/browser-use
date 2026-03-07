"""Browser backend interfaces and capability reporting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from browser_use.browser.views import BrowserStateSummary, TabInfo

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.dom.views import EnhancedDOMTreeNode


class BackendCapabilityReport(BaseModel):
	"""Runtime capability report for a browser backend."""

	model_config = ConfigDict(extra='forbid')

	backend: str
	available: bool = True
	reason: str | None = None
	details: dict[str, Any] = Field(default_factory=dict)


class BrowserBackendCapabilities(BaseModel):
	"""Stable browser capability contract exposed on BrowserSession."""

	model_config = ConfigDict(extra='forbid')

	backend_name: str
	browser_name: str
	browser_version: str | None = None
	supported: bool = True
	requires_native_host: bool = False
	supports_real_profile: bool = False
	supports_named_profile_selection: bool = False
	supports_dom_state: bool = True
	supports_screenshots: bool = True
	supports_downloads: bool = True
	supports_uploads: bool = True
	supports_cookie_access: bool = True
	accessibility_permission: str = 'unknown'
	screen_recording_permission: str = 'unknown'
	issues: list[str] = Field(default_factory=list)


class BrowserBackend(ABC):
	"""Abstract backend contract for non-agent browser operations."""

	name: str

	def __init__(self, browser_session: BrowserSession) -> None:
		self.browser_session = browser_session

	@property
	def logger(self):
		"""Reuse the session logger for consistent output."""
		return self.browser_session.logger

	@abstractmethod
	async def start(self) -> BackendCapabilityReport:
		"""Start or attach to the browser backend."""

	@abstractmethod
	async def stop(self, force: bool = False) -> None:
		"""Stop or detach from the backend."""

	@abstractmethod
	async def get_tabs(self) -> list[TabInfo]:
		"""List tabs visible to the current backend context."""

	@abstractmethod
	async def get_current_page_url(self) -> str:
		"""Return the current page URL."""

	@abstractmethod
	async def get_current_page_title(self) -> str:
		"""Return the current page title."""

	@abstractmethod
	async def navigate_to(self, url: str, new_tab: bool = False) -> None:
		"""Navigate to a URL."""

	@abstractmethod
	async def evaluate_javascript(self, expression: str) -> Any:
		"""Evaluate JavaScript in the active page."""

	@abstractmethod
	async def take_screenshot(
		self,
		path: str | None = None,
		full_page: bool = False,
		format: str = 'png',
		quality: int | None = None,
		clip: dict[str, Any] | None = None,
	) -> bytes:
		"""Capture a screenshot."""

	@abstractmethod
	async def get_browser_state_summary(
		self,
		include_screenshot: bool = True,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		"""Build an agent-facing browser state summary."""

	@abstractmethod
	async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		"""Resolve an indexed DOM element from the latest state snapshot."""

	async def highlight_interaction_element(self, node: EnhancedDOMTreeNode) -> None:
		"""Optional visual highlight hook."""
		return None

	async def highlight_coordinate_click(self, x: int, y: int) -> None:
		"""Optional coordinate highlight hook."""
		return None
