from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ClickCoordinatesInput(BaseModel):
	"""Click a viewport coordinate directly."""

	coordinate_x: int = Field(description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int = Field(description='Vertical coordinate relative to viewport top edge')


class CdpCommandInput(BaseModel):
	"""Send a raw Chrome DevTools Protocol command."""

	method: str = Field(description='CDP method name, for example Runtime.evaluate or DOM.describeNode')
	params: dict[str, Any] = Field(default_factory=dict, description='CDP command parameters')
	session_id: str | None = Field(default=None, description='Optional CDP session id')
	target_id: str | None = Field(default=None, description='Optional CDP target id')


class GetStateInput(BaseModel):
	"""Request fresh browser state."""

	include_screenshot: bool = True
	include_dom: bool = True


class HtmlInput(BaseModel):
	"""Read raw page HTML or one selected element's HTML."""

	selector: str | None = Field(default=None, description='Optional CSS selector for a specific element')
	max_chars: int = Field(default=50_000, ge=1, le=1_000_000, description='Maximum HTML characters to return')


class MarkdownInput(BaseModel):
	"""Read the current page as cleaned markdown."""

	extract_links: bool = Field(default=False, description='Preserve link URLs in markdown')
	extract_images: bool = Field(default=False, description='Preserve image source URLs in markdown')
	max_chars: int = Field(default=50_000, ge=1, le=1_000_000, description='Maximum markdown characters to return')


class AccessibilityTreeInput(BaseModel):
	"""Read the Chrome accessibility tree for the focused page."""

	max_nodes: int = Field(default=250, ge=1, le=5000, description='Maximum accessibility nodes to return')
	include_ignored: bool = Field(default=False, description='Include ignored accessibility nodes')


class InspectElementInput(BaseModel):
	"""Inspect an element by Browser Use index, CSS selector, or backend node id."""

	index: int | None = Field(default=None, description='Browser Use element index/backendNodeId')
	selector: str | None = Field(default=None, description='CSS selector')
	backend_node_id: int | None = Field(default=None, description='Raw CDP backendNodeId')
	include_html: bool = True
	max_html_chars: int = Field(default=20_000, ge=1, le=1_000_000)

	@model_validator(mode='after')
	def _exactly_one_locator(self) -> InspectElementInput:
		locators = [self.index is not None, self.selector is not None, self.backend_node_id is not None]
		if sum(locators) != 1:
			raise ValueError('Provide exactly one of index, selector, or backend_node_id')
		return self


class NetworkStateInput(BaseModel):
	"""Read pending and recent browser network activity."""

	max_entries: int = Field(default=100, ge=1, le=1000, description='Maximum recent performance entries to return')
	include_performance_entries: bool = True


class HttpFetchInput(BaseModel):
	"""Run a browser-context fetch request with page credentials available."""

	url: str
	method: str = 'GET'
	headers: dict[str, str] = Field(default_factory=dict)
	body: str | None = None
	credentials: Literal['include', 'same-origin', 'omit'] = 'include'
	max_chars: int = Field(default=100_000, ge=1, le=1_000_000, description='Maximum response body characters to return')


class WorkspaceReadFileInput(BaseModel):
	"""Read a file from the configured workspace root."""

	path: str
	max_chars: int = Field(default=100_000, ge=1, le=1_000_000)


class WorkspaceWriteFileInput(BaseModel):
	"""Write a file inside the configured workspace root."""

	path: str
	content: str
	append: bool = False
	create_parent_dirs: bool = False


class WorkspaceListFilesInput(BaseModel):
	"""List files inside the configured workspace root."""

	path: str = '.'
	pattern: str = '*'
	recursive: bool = False
	max_entries: int = Field(default=200, ge=1, le=5000)


class WorkspaceImportArtifactsInput(BaseModel):
	"""Copy downloaded, generated, or explicitly listed files into the workspace."""

	paths: list[str] = Field(default_factory=list, description='Explicit file paths to import')
	include_available_file_paths: bool = True
	include_downloads: bool = True
	include_artifacts: bool = True
	destination_dir: str = 'artifacts'
	overwrite: bool = False
	max_files: int = Field(default=100, ge=1, le=1000)


class ShellRunInput(BaseModel):
	"""Run a command in the configured workspace root."""

	command: list[str] = Field(min_length=1)
	cwd: str = '.'
	timeout_s: float = Field(default=30, gt=0, le=300)
	max_output_chars: int = Field(default=50_000, ge=1, le=1_000_000)
