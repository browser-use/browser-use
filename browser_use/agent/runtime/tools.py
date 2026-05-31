from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from uuid_extensions import uuid7str

from browser_use.agent.runtime.context import ToolResultItem
from browser_use.agent.runtime.views import BrowserRuntimeEventTypes, ToolContext
from browser_use.agent.views import ActionResult
from browser_use.browser.services import BrowserServiceBundle
from browser_use.browser.views import BrowserError
from browser_use.tools.registry.views import RegisteredAction
from browser_use.tools.service import Tools, _coerce_valid_action_timeout, handle_browser_error
from browser_use.tools.views import ClickElementAction


def _api_safe_tool_name(name: str) -> str:
	"""Convert canonical dotted tool names to provider-safe function names."""
	return re.sub(r'[^a-zA-Z0-9_-]', '_', name)


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


class ShellRunInput(BaseModel):
	"""Run a command in the configured workspace root."""

	command: list[str] = Field(min_length=1)
	cwd: str = '.'
	timeout_s: float = Field(default=30, gt=0, le=300)
	max_output_chars: int = Field(default=50_000, ge=1, le=1_000_000)


class NativeToolDefinition(BaseModel):
	"""Native tool definition backed by a Pydantic input model."""

	model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

	name: str
	description: str
	input_model: type[BaseModel] = Field(exclude=True)
	api_name: str | None = None
	source_action: str | None = None
	terminates_sequence: bool = False
	executable: bool = True

	@model_validator(mode='after')
	def _set_api_name(self) -> NativeToolDefinition:
		if self.api_name is None:
			self.api_name = _api_safe_tool_name(self.name)
		return self

	@property
	def input_schema(self) -> dict[str, Any]:
		return self.input_model.model_json_schema()

	def as_function_tool(self) -> dict[str, Any]:
		"""Return an OpenAI-compatible function tool schema."""
		return {
			'type': 'function',
			'function': {
				'name': self.api_name,
				'description': self.description,
				'parameters': self.input_schema,
			},
		}

	@classmethod
	def from_registered_action(cls, *, native_name: str, action: RegisteredAction) -> NativeToolDefinition:
		return cls(
			name=native_name,
			description=action.description,
			input_model=action.param_model,
			source_action=action.name,
			terminates_sequence=action.terminates_sequence,
			executable=True,
		)


class NativeToolCall(BaseModel):
	"""A model-requested native tool call."""

	tool_name: str
	arguments: dict[str, Any] = Field(default_factory=dict)
	call_id: str = Field(default_factory=uuid7str)


class NativeToolResult(BaseModel):
	"""Structured result returned from a native tool call."""

	tool_name: str
	call_id: str
	is_error: bool = False
	content: str | None = None
	structured_content: dict[str, Any] = Field(default_factory=dict)
	artifact_ids: list[str] = Field(default_factory=list)
	action_result: ActionResult | None = Field(default=None, exclude=True)

	@classmethod
	def from_action_result(cls, *, call: NativeToolCall, result: ActionResult) -> NativeToolResult:
		content = result.error or result.long_term_memory or result.extracted_content
		return cls(
			tool_name=call.tool_name,
			call_id=call.call_id,
			is_error=bool(result.error),
			content=content,
			structured_content=result.model_dump(exclude_none=True),
			action_result=result,
		)

	def to_context_item(self) -> ToolResultItem:
		return ToolResultItem(
			tool_name=self.tool_name,
			call_id=self.call_id,
			content=None if self.is_error else self.content,
			error=self.content if self.is_error else None,
			structured_content=self.structured_content,
			artifact_ids=self.artifact_ids,
		)


_ACTION_TO_NATIVE_TOOL = {
	'search': 'browser.search',
	'navigate': 'browser.navigate',
	'go_back': 'browser.go_back',
	'wait': 'browser.wait',
	'click': 'browser.click',
	'input': 'browser.type',
	'upload_file': 'browser.upload_file',
	'switch': 'browser.switch_tab',
	'close': 'browser.close_tab',
	'extract': 'browser.extract',
	'search_page': 'browser.search_page',
	'find_elements': 'browser.find_elements',
	'scroll': 'browser.scroll',
	'send_keys': 'browser.send_keys',
	'screenshot': 'browser.screenshot',
	'save_as_pdf': 'browser.save_as_pdf',
	'get_dropdown_options': 'browser.get_dropdown_options',
	'select_dropdown_option': 'browser.select_dropdown_option',
	'evaluate': 'browser.evaluate',
	'done': 'browser.done',
}


def _experimental_definitions() -> list[NativeToolDefinition]:
	return [
		NativeToolDefinition(
			name='browser.click_coordinates',
			description='Click a viewport coordinate directly. Use when screenshot reasoning is more reliable than a DOM index.',
			input_model=ClickCoordinatesInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.cdp',
			description='Send a raw Chrome DevTools Protocol command using full runtime CDP handles.',
			input_model=CdpCommandInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.get_state',
			description='Request a fresh browser state snapshot.',
			input_model=GetStateInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.html',
			description='Read raw HTML for the full page or a CSS selector. Use when cleaned DOM/markdown omits needed structure.',
			input_model=HtmlInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.markdown',
			description='Read the current page as cleaned markdown. Use for dense text extraction before reaching for raw HTML.',
			input_model=MarkdownInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.accessibility',
			description='Read the accessibility tree. Use for roles/names when DOM indexes or screenshots are ambiguous.',
			input_model=AccessibilityTreeInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.inspect_element',
			description='Inspect one element by Browser Use index/backendNodeId, CSS selector, or raw backendNodeId.',
			input_model=InspectElementInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.network',
			description='Inspect pending and recent network requests for the current page.',
			input_model=NetworkStateInput,
			executable=True,
		),
		NativeToolDefinition(
			name='browser.http_fetch',
			description='Fetch a URL from inside the browser context with page credentials. Use for APIs or page-adjacent data.',
			input_model=HttpFetchInput,
			executable=True,
		),
	]


def _workspace_definitions() -> list[NativeToolDefinition]:
	return [
		NativeToolDefinition(
			name='workspace.read_file',
			description='Read a text file from the configured workspace root. Requires allow_file_tools metadata.',
			input_model=WorkspaceReadFileInput,
			executable=True,
		),
		NativeToolDefinition(
			name='workspace.write_file',
			description='Write or append a text file inside the configured workspace root. Requires allow_file_tools metadata.',
			input_model=WorkspaceWriteFileInput,
			executable=True,
		),
		NativeToolDefinition(
			name='workspace.list_files',
			description='List files inside the configured workspace root. Requires allow_file_tools metadata.',
			input_model=WorkspaceListFilesInput,
			executable=True,
		),
		NativeToolDefinition(
			name='shell.run',
			description='Run an argv-style command in the configured workspace root. Requires allow_shell_tools metadata.',
			input_model=ShellRunInput,
			executable=True,
		),
	]


class NativeToolRouter(BaseModel):
	"""Routes native tool calls to Browser Use actions during migration."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	definitions: dict[str, NativeToolDefinition] = Field(default_factory=dict)

	@classmethod
	def from_tools(
		cls,
		tools: Tools,
		*,
		include_actions: list[str] | None = None,
		page_url: str | None = None,
		include_experimental: bool = True,
		include_workspace_tools: bool = False,
	) -> NativeToolRouter:
		definitions: dict[str, NativeToolDefinition] = {}

		for action_name, action in tools.registry.registry.actions.items():
			if include_actions is not None and action_name not in include_actions:
				continue
			if page_url is None:
				if action.domains is not None:
					continue
			elif not tools.registry.registry._match_domains(action.domains, page_url):
				continue

			native_name = _ACTION_TO_NATIVE_TOOL.get(action_name, f'browser.{action_name}')
			definition = NativeToolDefinition.from_registered_action(native_name=native_name, action=action)
			definitions[definition.name] = definition

		if include_experimental:
			for definition in _experimental_definitions():
				definitions.setdefault(definition.name, definition)

		if include_workspace_tools:
			for definition in _workspace_definitions():
				definitions.setdefault(definition.name, definition)

		return cls(definitions=definitions)

	def resolve(self, tool_name: str) -> NativeToolDefinition:
		if tool_name in self.definitions:
			return self.definitions[tool_name]

		for definition in self.definitions.values():
			if definition.api_name == tool_name:
				return definition

		raise KeyError(f'Native tool {tool_name} is not registered')

	def tool_schemas(self) -> list[dict[str, Any]]:
		return [definition.as_function_tool() for definition in self.definitions.values()]

	def guidance(self) -> str:
		return (
			'Prefer browser.click/type/scroll on DOM indexes for ordinary interaction. '
			'Use browser.get_state to refresh DOM, screenshot, targetId, and sessionId handles. '
			'Use browser.click_coordinates when visual placement is clearer than a DOM index. '
			'Use browser.markdown for readable page text, browser.html for raw structure, and browser.inspect_element for one element. '
			'Use browser.accessibility for roles/names, browser.network for request debugging, browser.http_fetch for API/data reads, '
			'and browser.cdp only when lower-level CDP handles or browser primitives are needed.'
		)

	def validate_call(self, call: NativeToolCall) -> BaseModel:
		definition = self.resolve(call.tool_name)
		try:
			return definition.input_model.model_validate(call.arguments)
		except ValidationError as e:
			raise ValueError(f'Invalid arguments for native tool {call.tool_name}: {e}') from e

	async def execute(self, call: NativeToolCall, context: ToolContext) -> NativeToolResult:
		definition = self.resolve(call.tool_name)
		if definition.name == 'browser.click_coordinates':
			params = cast(ClickCoordinatesInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._click_coordinates(params, context))

		if definition.name == 'browser.cdp':
			params = cast(CdpCommandInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._send_cdp(params, context))

		if definition.name == 'browser.get_state':
			params = cast(GetStateInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._get_state(params, context))

		if definition.name == 'browser.html':
			params = cast(HtmlInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._get_html(params, context))

		if definition.name == 'browser.markdown':
			params = cast(MarkdownInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._get_markdown(params, context))

		if definition.name == 'browser.accessibility':
			params = cast(AccessibilityTreeInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._get_accessibility(params, context))

		if definition.name == 'browser.inspect_element':
			params = cast(InspectElementInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._inspect_element(params, context))

		if definition.name == 'browser.network':
			params = cast(NetworkStateInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._get_network(params, context))

		if definition.name == 'browser.http_fetch':
			params = cast(HttpFetchInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._http_fetch(params, context))

		if definition.name == 'workspace.read_file':
			params = cast(WorkspaceReadFileInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._workspace_read_file(params, context))

		if definition.name == 'workspace.write_file':
			params = cast(WorkspaceWriteFileInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._workspace_write_file(params, context))

		if definition.name == 'workspace.list_files':
			params = cast(WorkspaceListFilesInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._workspace_list_files(params, context))

		if definition.name == 'shell.run':
			params = cast(ShellRunInput, self.validate_call(call))
			return await self._execute_direct_tool(call, context, definition, lambda: self._shell_run(params, context))

		if not definition.executable or not definition.source_action:
			return NativeToolResult(
				tool_name=call.tool_name,
				call_id=call.call_id,
				is_error=True,
				content=f'Native tool {definition.name} is defined but not executable in this runtime yet.',
			)

		if not isinstance(context.tools, Tools):
			return NativeToolResult(
				tool_name=call.tool_name,
				call_id=call.call_id,
				is_error=True,
				content='Native tool execution requires ToolContext.tools to be a browser_use Tools instance.',
			)

		params = self.validate_call(call)
		context.emit_tool_event(
			BrowserRuntimeEventTypes.TOOL_STARTED,
			{
				'tool_name': definition.name,
				'api_name': definition.api_name,
				'source_action': definition.source_action,
			},
		)

		timeout_s = _coerce_valid_action_timeout(context.action_timeout)
		try:
			raw_result = await asyncio.wait_for(
				context.tools.registry.execute_action(
					action_name=definition.source_action,
					params=params.model_dump(),
					browser_session=context.browser_session,
					page_extraction_llm=context.page_extraction_llm or context.llm,
					file_system=context.file_system,
					sensitive_data=context.sensitive_data,
					available_file_paths=context.available_file_paths,
					extraction_schema=context.extraction_schema,
				),
				timeout=timeout_s,
			)
		except BrowserError as e:
			result = handle_browser_error(e)
		except TimeoutError:
			result = ActionResult(error=f'Action {definition.source_action} timed out after {timeout_s:.0f}s.')
		except Exception as e:
			result = ActionResult(error=str(e))
		else:
			if isinstance(raw_result, ActionResult):
				result = raw_result
			elif isinstance(raw_result, str):
				result = ActionResult(extracted_content=raw_result)
			elif raw_result is None:
				result = ActionResult()
			else:
				result = ActionResult(extracted_content=str(raw_result))

		native_result = NativeToolResult.from_action_result(call=call, result=result)
		context.emit_tool_event(
			BrowserRuntimeEventTypes.TOOL_COMPLETED if not native_result.is_error else BrowserRuntimeEventTypes.TOOL_FAILED,
			{
				'tool_name': definition.name,
				'api_name': definition.api_name,
				'source_action': definition.source_action,
				'is_error': native_result.is_error,
			},
		)
		return native_result

	async def _execute_direct_tool(
		self,
		call: NativeToolCall,
		context: ToolContext,
		definition: NativeToolDefinition,
		operation: Callable[[], Awaitable[NativeToolResult]],
	) -> NativeToolResult:
		context.emit_tool_event(
			BrowserRuntimeEventTypes.TOOL_STARTED,
			{
				'tool_name': definition.name,
				'api_name': definition.api_name,
				'source_action': definition.source_action,
			},
		)

		timeout_s = _coerce_valid_action_timeout(context.action_timeout)
		try:
			native_result = await asyncio.wait_for(operation(), timeout=timeout_s)
		except BrowserError as e:
			native_result = NativeToolResult.from_action_result(call=call, result=handle_browser_error(e))
		except TimeoutError:
			native_result = NativeToolResult(
				tool_name=call.tool_name,
				call_id=call.call_id,
				is_error=True,
				content=f'Native tool {definition.name} timed out after {timeout_s:.0f}s.',
			)
		except Exception as e:
			native_result = NativeToolResult(tool_name=call.tool_name, call_id=call.call_id, is_error=True, content=str(e))

		native_result.tool_name = call.tool_name
		native_result.call_id = call.call_id
		context.emit_tool_event(
			BrowserRuntimeEventTypes.TOOL_COMPLETED if not native_result.is_error else BrowserRuntimeEventTypes.TOOL_FAILED,
			{
				'tool_name': definition.name,
				'api_name': definition.api_name,
				'source_action': definition.source_action,
				'is_error': native_result.is_error,
			},
		)
		return native_result

	async def _click_coordinates(self, params: ClickCoordinatesInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.click_coordinates',
				call_id='',
				is_error=True,
				content='browser.click_coordinates requires ToolContext.browser_session.',
			)

		services = BrowserServiceBundle.from_session(context.browser_session)
		await services.actions.click.click_coordinates(params.coordinate_x, params.coordinate_y)
		return NativeToolResult(
			tool_name='browser.click_coordinates',
			call_id='',
			content=f'Clicked coordinates ({params.coordinate_x}, {params.coordinate_y})',
			structured_content=click_coordinates_as_click_arguments(params),
		)

	async def _send_cdp(self, params: CdpCommandInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.cdp',
				call_id='',
				is_error=True,
				content='browser.cdp requires ToolContext.browser_session.',
			)

		target_id = cast(Any, params.target_id) if params.target_id is not None else None
		cdp_session = await context.browser_session.get_or_create_cdp_session(
			target_id=target_id,
			focus=params.target_id is None,
		)
		session_id = params.session_id or cdp_session.session_id
		response = await cdp_session.cdp_client.send_raw(params.method, params.params, session_id=session_id)
		return NativeToolResult(
			tool_name='browser.cdp',
			call_id='',
			content=f'CDP command {params.method} completed',
			structured_content={
				'method': params.method,
				'params': params.params,
				'target_id': params.target_id or str(cdp_session.target_id),
				'session_id': session_id,
				'response': response,
			},
		)

	async def _get_state(self, params: GetStateInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.get_state',
				call_id='',
				is_error=True,
				content='browser.get_state requires ToolContext.browser_session.',
			)

		services = BrowserServiceBundle.from_session(context.browser_session)
		state = await services.state.get_state(include_screenshot=params.include_screenshot)
		cdp_session = await context.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		context.emit_tool_event(
			BrowserRuntimeEventTypes.BROWSER_STATE_REFRESHED,
			{
				'url': state.url,
				'title': state.title,
				'include_screenshot': params.include_screenshot,
				'include_dom': params.include_dom,
			},
		)

		tabs = [
			{
				'url': tab.url,
				'title': tab.title,
				'target_id': str(tab.target_id),
				'parent_target_id': str(tab.parent_target_id) if tab.parent_target_id is not None else None,
			}
			for tab in state.tabs
		]
		structured_content: dict[str, Any] = {
			'url': state.url,
			'title': state.title,
			'tabs': tabs,
			'pixels_above': state.pixels_above,
			'pixels_below': state.pixels_below,
			'is_pdf_viewer': state.is_pdf_viewer,
			'browser_errors': state.browser_errors,
			'closed_popup_messages': state.closed_popup_messages,
			'pending_network_requests': [
				{
					'url': request.url,
					'method': request.method,
					'resource_type': request.resource_type,
					'loading_duration_ms': request.loading_duration_ms,
				}
				for request in state.pending_network_requests
			],
			'runtime_handles': {
				'agent_focus_target_id': str(context.browser_session.agent_focus_target_id)
				if context.browser_session.agent_focus_target_id is not None
				else None,
				'current_target_id': str(cdp_session.target_id),
				'current_session_id': cdp_session.session_id,
				'tab_target_ids': [tab['target_id'] for tab in tabs],
			},
		}

		if params.include_dom:
			structured_content['dom'] = state.dom_state.llm_representation()
			structured_content['selector_count'] = len(state.dom_state.selector_map)

		if params.include_screenshot:
			structured_content['screenshot'] = state.screenshot

		return NativeToolResult(
			tool_name='browser.get_state',
			call_id='',
			content=f'Browser state captured for {state.url}',
			structured_content=structured_content,
		)

	async def _get_html(self, params: HtmlInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.html',
				call_id='',
				is_error=True,
				content='browser.html requires ToolContext.browser_session.',
			)

		expression = (
			f'(function(){{ const el = document.querySelector({json.dumps(params.selector)}); return el ? el.outerHTML : null; }})()'
			if params.selector
			else 'document.documentElement.outerHTML'
		)
		response = await self._runtime_evaluate(expression, context)
		html = response.get('result', {}).get('value')
		if html is None:
			return NativeToolResult(
				tool_name='browser.html',
				call_id='',
				is_error=True,
				content=f'No element found for selector: {params.selector}' if params.selector else 'Could not read page HTML.',
			)

		truncated = _truncate_text(str(html), params.max_chars)
		return NativeToolResult(
			tool_name='browser.html',
			call_id='',
			content=f'Read {truncated["returned_chars"]} HTML characters',
			structured_content={'selector': params.selector, 'html': truncated['text'], **truncated},
		)

	async def _get_markdown(self, params: MarkdownInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.markdown',
				call_id='',
				is_error=True,
				content='browser.markdown requires ToolContext.browser_session.',
			)

		from browser_use.dom.markdown_extractor import extract_clean_markdown

		markdown, stats = await extract_clean_markdown(
			browser_session=context.browser_session,
			extract_links=params.extract_links,
			extract_images=params.extract_images,
		)
		truncated = _truncate_text(markdown, params.max_chars)
		return NativeToolResult(
			tool_name='browser.markdown',
			call_id='',
			content=f'Read {truncated["returned_chars"]} markdown characters',
			structured_content={
				'markdown': truncated['text'],
				'stats': stats,
				'extract_links': params.extract_links,
				'extract_images': params.extract_images,
				**truncated,
			},
		)

	async def _get_accessibility(self, params: AccessibilityTreeInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.accessibility',
				call_id='',
				is_error=True,
				content='browser.accessibility requires ToolContext.browser_session.',
			)

		cdp_session = await context.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		response = await cdp_session.cdp_client.send_raw(
			'Accessibility.getFullAXTree',
			{},
			session_id=cdp_session.session_id,
		)
		nodes = response.get('nodes', [])
		if not params.include_ignored:
			nodes = [node for node in nodes if not node.get('ignored')]
		return NativeToolResult(
			tool_name='browser.accessibility',
			call_id='',
			content=f'Read {min(len(nodes), params.max_nodes)} accessibility nodes',
			structured_content={
				'nodes': nodes[: params.max_nodes],
				'total_nodes': len(nodes),
				'returned_nodes': min(len(nodes), params.max_nodes),
				'truncated': len(nodes) > params.max_nodes,
				'target_id': str(cdp_session.target_id),
				'session_id': cdp_session.session_id,
			},
		)

	async def _inspect_element(self, params: InspectElementInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.inspect_element',
				call_id='',
				is_error=True,
				content='browser.inspect_element requires ToolContext.browser_session.',
			)

		if params.index is not None:
			node = await context.browser_session.get_element_by_index(params.index)
			if node is None:
				return NativeToolResult(
					tool_name='browser.inspect_element',
					call_id='',
					is_error=True,
					content=f'Element index {params.index} was not found.',
				)
			content: dict[str, Any] = {
				'locator': {'index': params.index},
				'tag_name': node.tag_name,
				'backend_node_id': node.backend_node_id,
				'node_id': node.node_id,
				'attributes': node.attributes,
				'text': node.get_all_children_text(max_depth=10),
				'is_visible': node.is_visible,
				'is_scrollable': node.is_scrollable,
				'target_id': str(node.target_id),
				'session_id': node.session_id,
				'frame_id': node.frame_id,
				'absolute_position': node.absolute_position.to_dict() if node.absolute_position else None,
			}
			if node.ax_node:
				content['accessibility'] = {
					'role': getattr(node.ax_node, 'role', None),
					'name': getattr(node.ax_node, 'name', None),
					'description': getattr(node.ax_node, 'description', None),
				}
			if params.include_html:
				html_result = await self._html_for_backend_node(
					node.backend_node_id, node.session_id, context, params.max_html_chars
				)
				content.update(html_result)
			return NativeToolResult(
				tool_name='browser.inspect_element',
				call_id='',
				content=f'Inspected element index {params.index}',
				structured_content=content,
			)

		if params.selector is not None:
			expression = f"""
(function() {{
	const el = document.querySelector({json.dumps(params.selector)});
	if (!el) return null;
	const rect = el.getBoundingClientRect();
	const attrs = Object.fromEntries(Array.from(el.attributes || []).map((attr) => [attr.name, attr.value]));
	return {{
		tag_name: el.tagName.toLowerCase(),
		attributes: attrs,
		text: el.innerText || el.textContent || '',
		absolute_position: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
		html: {str(params.include_html).lower()} ? el.outerHTML : null,
	}};
}})()
"""
			response = await self._runtime_evaluate(expression, context)
			value = response.get('result', {}).get('value')
			if value is None:
				return NativeToolResult(
					tool_name='browser.inspect_element',
					call_id='',
					is_error=True,
					content=f'No element found for selector: {params.selector}',
				)
			if params.include_html and value.get('html') is not None:
				value['html'] = _truncate_text(str(value['html']), params.max_html_chars)
			return NativeToolResult(
				tool_name='browser.inspect_element',
				call_id='',
				content=f'Inspected selector {params.selector}',
				structured_content={'locator': {'selector': params.selector}, **value},
			)

		assert params.backend_node_id is not None
		cdp_session = await context.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		response = await cdp_session.cdp_client.send_raw(
			'DOM.describeNode',
			{'backendNodeId': params.backend_node_id, 'depth': 1, 'pierce': True},
			session_id=cdp_session.session_id,
		)
		content = {
			'locator': {'backend_node_id': params.backend_node_id},
			'target_id': str(cdp_session.target_id),
			'session_id': cdp_session.session_id,
			'node': response.get('node'),
		}
		if params.include_html:
			content.update(
				await self._html_for_backend_node(params.backend_node_id, cdp_session.session_id, context, params.max_html_chars)
			)
		return NativeToolResult(
			tool_name='browser.inspect_element',
			call_id='',
			content=f'Inspected backendNodeId {params.backend_node_id}',
			structured_content=content,
		)

	async def _get_network(self, params: NetworkStateInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.network',
				call_id='',
				is_error=True,
				content='browser.network requires ToolContext.browser_session.',
			)

		state = await context.browser_session.get_browser_state_summary(include_screenshot=False)
		pending = [
			{
				'url': request.url,
				'method': request.method,
				'resource_type': request.resource_type,
				'loading_duration_ms': request.loading_duration_ms,
			}
			for request in state.pending_network_requests
		]
		performance_entries: list[dict[str, Any]] = []
		if params.include_performance_entries:
			expression = f"""
performance.getEntriesByType('resource').slice(-{params.max_entries}).map((entry) => ({{
	name: entry.name,
	initiatorType: entry.initiatorType,
	startTime: Math.round(entry.startTime),
	duration: Math.round(entry.duration),
	transferSize: entry.transferSize || 0,
	encodedBodySize: entry.encodedBodySize || 0,
	decodedBodySize: entry.decodedBodySize || 0
}}))
"""
			response = await self._runtime_evaluate(expression, context)
			performance_entries = response.get('result', {}).get('value') or []
		return NativeToolResult(
			tool_name='browser.network',
			call_id='',
			content=f'Read {len(pending)} pending requests and {len(performance_entries)} recent entries',
			structured_content={
				'pending_requests': pending,
				'performance_entries': performance_entries,
				'url': state.url,
			},
		)

	async def _http_fetch(self, params: HttpFetchInput, context: ToolContext) -> NativeToolResult:
		if context.browser_session is None:
			return NativeToolResult(
				tool_name='browser.http_fetch',
				call_id='',
				is_error=True,
				content='browser.http_fetch requires ToolContext.browser_session.',
			)

		expression = f"""
(async () => {{
	const response = await fetch({json.dumps(params.url)}, {{
		method: {json.dumps(params.method.upper())},
		headers: {json.dumps(params.headers)},
		body: {json.dumps(params.body)},
		credentials: {json.dumps(params.credentials)}
	}});
	const body = await response.text();
	return {{
		url: response.url,
		status: response.status,
		statusText: response.statusText,
		ok: response.ok,
		headers: Object.fromEntries(response.headers.entries()),
		body,
	}};
}})()
"""
		response = await self._runtime_evaluate(expression, context, await_promise=True)
		value = response.get('result', {}).get('value')
		if value is None:
			return NativeToolResult(
				tool_name='browser.http_fetch',
				call_id='',
				is_error=True,
				content=f'Fetch failed for {params.url}',
				structured_content={'cdp_response': response},
			)

		truncated = _truncate_text(str(value.get('body', '')), params.max_chars)
		value['body'] = truncated['text']
		value.update(truncated)
		return NativeToolResult(
			tool_name='browser.http_fetch',
			call_id='',
			is_error=not bool(value.get('ok')),
			content=f'Fetched {value.get("status")} {value.get("url")}',
			structured_content=value,
		)

	async def _runtime_evaluate(
		self,
		expression: str,
		context: ToolContext,
		*,
		await_promise: bool = False,
	) -> dict[str, Any]:
		assert context.browser_session is not None
		cdp_session = await context.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		return await cdp_session.cdp_client.send_raw(
			'Runtime.evaluate',
			{'expression': expression, 'returnByValue': True, 'awaitPromise': await_promise},
			session_id=cdp_session.session_id,
		)

	async def _html_for_backend_node(
		self,
		backend_node_id: int,
		session_id: str | None,
		context: ToolContext,
		max_chars: int,
	) -> dict[str, Any]:
		assert context.browser_session is not None
		cdp_session = await context.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		resolved = await cdp_session.cdp_client.send_raw(
			'DOM.resolveNode',
			{'backendNodeId': backend_node_id},
			session_id=session_id or cdp_session.session_id,
		)
		object_id = resolved.get('object', {}).get('objectId')
		if object_id is None:
			return {'html_error': f'Could not resolve backendNodeId {backend_node_id}'}
		html_response = await cdp_session.cdp_client.send_raw(
			'Runtime.callFunctionOn',
			{
				'objectId': object_id,
				'functionDeclaration': 'function() { return this.outerHTML; }',
				'returnByValue': True,
			},
			session_id=session_id or cdp_session.session_id,
		)
		html = html_response.get('result', {}).get('value')
		if html is None:
			return {'html_error': f'Could not read HTML for backendNodeId {backend_node_id}'}
		return {'html': _truncate_text(str(html), max_chars)}

	async def _workspace_read_file(self, params: WorkspaceReadFileInput, context: ToolContext) -> NativeToolResult:
		try:
			root = _workspace_root(context, permission='file')
			path = _resolve_workspace_path(root, params.path)
		except ValueError as e:
			return NativeToolResult(tool_name='workspace.read_file', call_id='', is_error=True, content=str(e))

		if not path.exists() or not path.is_file():
			return NativeToolResult(
				tool_name='workspace.read_file',
				call_id='',
				is_error=True,
				content=f'File not found: {params.path}',
			)

		content = path.read_text(encoding='utf-8', errors='replace')
		truncated = _truncate_text(content, params.max_chars)
		return NativeToolResult(
			tool_name='workspace.read_file',
			call_id='',
			content=f'Read {truncated["returned_chars"]} characters from {params.path}',
			structured_content={'path': str(path), 'content': truncated['text'], **truncated},
		)

	async def _workspace_write_file(self, params: WorkspaceWriteFileInput, context: ToolContext) -> NativeToolResult:
		try:
			root = _workspace_root(context, permission='file')
			path = _resolve_workspace_path(root, params.path)
		except ValueError as e:
			return NativeToolResult(tool_name='workspace.write_file', call_id='', is_error=True, content=str(e))

		if not path.parent.exists():
			if params.create_parent_dirs:
				path.parent.mkdir(parents=True, exist_ok=True)
			else:
				return NativeToolResult(
					tool_name='workspace.write_file',
					call_id='',
					is_error=True,
					content=f'Parent directory does not exist: {path.parent}',
				)

		mode = 'a' if params.append else 'w'
		with path.open(mode, encoding='utf-8') as file:
			file.write(params.content)
		return NativeToolResult(
			tool_name='workspace.write_file',
			call_id='',
			content=f'Wrote {len(params.content)} characters to {params.path}',
			structured_content={
				'path': str(path),
				'bytes': path.stat().st_size,
				'appended': params.append,
			},
		)

	async def _workspace_list_files(self, params: WorkspaceListFilesInput, context: ToolContext) -> NativeToolResult:
		try:
			root = _workspace_root(context, permission='file')
			path = _resolve_workspace_path(root, params.path)
		except ValueError as e:
			return NativeToolResult(tool_name='workspace.list_files', call_id='', is_error=True, content=str(e))

		if not path.exists() or not path.is_dir():
			return NativeToolResult(
				tool_name='workspace.list_files',
				call_id='',
				is_error=True,
				content=f'Directory not found: {params.path}',
			)

		iterator = path.rglob(params.pattern) if params.recursive else path.glob(params.pattern)
		entries = []
		for entry in iterator:
			try:
				resolved = entry.resolve()
				if resolved == root or root not in resolved.parents:
					continue
				relative = resolved.relative_to(root)
				entries.append(
					{
						'path': str(relative),
						'type': 'directory' if resolved.is_dir() else 'file',
						'bytes': resolved.stat().st_size if resolved.is_file() else None,
					}
				)
			except OSError:
				continue
			if len(entries) >= params.max_entries:
				break

		return NativeToolResult(
			tool_name='workspace.list_files',
			call_id='',
			content=f'Listed {len(entries)} workspace entries',
			structured_content={
				'root': str(root),
				'path': str(path),
				'entries': entries,
				'max_entries': params.max_entries,
				'truncated': len(entries) >= params.max_entries,
			},
		)

	async def _shell_run(self, params: ShellRunInput, context: ToolContext) -> NativeToolResult:
		try:
			root = _workspace_root(context, permission='shell')
			cwd = _resolve_workspace_path(root, params.cwd)
		except ValueError as e:
			return NativeToolResult(tool_name='shell.run', call_id='', is_error=True, content=str(e))

		if not cwd.exists() or not cwd.is_dir():
			return NativeToolResult(
				tool_name='shell.run', call_id='', is_error=True, content=f'cwd is not a directory: {params.cwd}'
			)

		allowed_commands = context.metadata.get('allowed_shell_commands')
		if allowed_commands is not None and params.command[0] not in set(allowed_commands):
			return NativeToolResult(
				tool_name='shell.run',
				call_id='',
				is_error=True,
				content=f'Shell command is not allowed: {params.command[0]}',
			)

		process = await asyncio.create_subprocess_exec(
			*params.command,
			cwd=str(cwd),
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)
		try:
			stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=params.timeout_s)
			timed_out = False
		except TimeoutError:
			process.kill()
			stdout_bytes, stderr_bytes = await process.communicate()
			timed_out = True

		stdout = stdout_bytes.decode('utf-8', errors='replace')
		stderr = stderr_bytes.decode('utf-8', errors='replace')
		stdout_truncated = _truncate_text(stdout, params.max_output_chars)
		stderr_truncated = _truncate_text(stderr, params.max_output_chars)
		return NativeToolResult(
			tool_name='shell.run',
			call_id='',
			is_error=timed_out or process.returncode != 0,
			content=f'Shell command exited with code {process.returncode}',
			structured_content={
				'command': params.command,
				'cwd': str(cwd),
				'exit_code': process.returncode,
				'timed_out': timed_out,
				'stdout': stdout_truncated['text'],
				'stderr': stderr_truncated['text'],
				'stdout_original_chars': stdout_truncated['original_chars'],
				'stderr_original_chars': stderr_truncated['original_chars'],
				'stdout_truncated': stdout_truncated['truncated'],
				'stderr_truncated': stderr_truncated['truncated'],
			},
		)


def click_coordinates_as_click_arguments(params: ClickCoordinatesInput) -> dict[str, Any]:
	"""Translate coordinate-only input to the current click action shape."""
	return ClickElementAction(
		index=None,
		coordinate_x=params.coordinate_x,
		coordinate_y=params.coordinate_y,
	).model_dump(exclude_none=True)


def _truncate_text(value: str, max_chars: int) -> dict[str, Any]:
	truncated = len(value) > max_chars
	text = value[:max_chars]
	return {
		'text': text,
		'original_chars': len(value),
		'returned_chars': len(text),
		'truncated': truncated,
	}


def _workspace_root(context: ToolContext, *, permission: Literal['file', 'shell']) -> Path:
	permission_key = 'allow_file_tools' if permission == 'file' else 'allow_shell_tools'
	if context.metadata.get(permission_key) is not True:
		raise ValueError(f'{permission_key} metadata must be true to use {permission} workspace tools.')

	root_value = context.metadata.get('workspace_root')
	if root_value is None:
		get_dir = getattr(context.file_system, 'get_dir', None)
		if callable(get_dir):
			root_value = get_dir()

	if root_value is None:
		raise ValueError('workspace_root metadata is required for workspace tools.')

	root = Path(cast(str | Path, root_value)).expanduser().resolve()
	root.mkdir(parents=True, exist_ok=True)
	return root


def _resolve_workspace_path(root: Path, path: str) -> Path:
	requested = Path(path).expanduser()
	candidate = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
	if candidate != root and root not in candidate.parents:
		raise ValueError(f'Path escapes workspace root: {path}')
	return candidate
