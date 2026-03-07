"""Wire protocol models for the local Safari companion host."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from browser_use.browser.types import BrowserTargetId

SafariHostCommandName = Literal[
	'capabilities.get',
	'profiles.discover',
	'profiles.bind_label',
	'profiles.focus',
	'windows.list',
	'tabs.list',
	'tabs.open',
	'tabs.activate',
	'tabs.close',
	'page.navigate',
	'page.state',
	'page.screenshot',
	'page.eval',
	'page.go_back',
	'page.go_forward',
	'page.refresh',
	'element.click',
	'element.type',
	'element.select',
	'input.send_keys',
	'files.upload',
	'downloads.watch',
]

SafariHostEventName = Literal[
	'profile.discovered',
	'profile.changed',
	'tab.created',
	'tab.closed',
	'tab.focused',
	'navigation.started',
	'navigation.completed',
	'dialog.opened',
	'dialog.closed',
	'download.started',
	'download.completed',
	'download.failed',
	'permission.missing',
]


class SafariHostRequest(BaseModel):
	"""JSON-RPC-ish request sent to the Safari companion host."""

	id: str = Field(default_factory=uuid7str)
	command: SafariHostCommandName
	params: dict[str, Any] = Field(default_factory=dict)


class SafariHostResponse(BaseModel):
	"""Host response for a command request."""

	id: str
	ok: bool = True
	result: dict[str, Any] = Field(default_factory=dict)
	error: str | None = None


class SafariHostEvent(BaseModel):
	"""Async event emitted by the host."""

	event: SafariHostEventName
	payload: dict[str, Any] = Field(default_factory=dict)


class SafariRect(BaseModel):
	"""Simple rectangle payload."""

	x: float
	y: float
	width: float
	height: float


class SafariTabState(BaseModel):
	"""Backend-neutral tab description returned by the host."""

	target_id: BrowserTargetId
	url: str
	title: str
	parent_target_id: BrowserTargetId | None = None
	is_active: bool = False


class SafariPageMetrics(BaseModel):
	"""Viewport and scroll metrics for BrowserStateSummary."""

	viewport_width: int = 0
	viewport_height: int = 0
	page_width: int = 0
	page_height: int = 0
	scroll_x: int = 0
	scroll_y: int = 0
	pixels_above: int = 0
	pixels_below: int = 0
	pixels_left: int = 0
	pixels_right: int = 0


class SafariInteractiveNode(BaseModel):
	"""Interactive element snapshot returned by the host."""

	backend_node_id: int
	node_name: str = 'div'
	text: str | None = None
	attributes: dict[str, str] = Field(default_factory=dict)
	is_visible: bool | None = True
	is_scrollable: bool | None = None
	absolute_position: SafariRect | None = None
	frame_id: str | None = None
	target_id: BrowserTargetId | None = None


class SafariPageStateResult(BaseModel):
	"""State snapshot returned by `page.state`."""

	url: str
	title: str
	tabs: list[SafariTabState] = Field(default_factory=list)
	nodes: list[SafariInteractiveNode] = Field(default_factory=list)
	page_info: SafariPageMetrics | None = None
	screenshot: str | None = None
	recent_events: str | None = None
	browser_errors: list[str] = Field(default_factory=list)
	closed_popup_messages: list[str] = Field(default_factory=list)


class SafariTabsResult(BaseModel):
	"""Tab listing response returned by `tabs.list`."""

	tabs: list[SafariTabState] = Field(default_factory=list)


class SafariHostCapabilities(BaseModel):
	"""Capability report returned by the Safari host."""

	backend_name: str = 'safari'
	host_version: str | None = None
	safari_version: str | None = None
	extension_enabled: bool = False
	accessibility_permission: Literal['granted', 'missing', 'unknown'] = 'unknown'
	screen_recording_permission: Literal['granted', 'missing', 'unknown'] = 'unknown'
	supports_real_profile: bool = True
	supports_named_profile_selection: bool = True
	supports_dom_state: bool = True
	supports_screenshots: bool = True
	supports_downloads: bool = True
	supports_uploads: bool = True
	supports_cookie_access: bool = False
	issues: list[str] = Field(default_factory=list)
