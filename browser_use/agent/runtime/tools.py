from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any, cast

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


def click_coordinates_as_click_arguments(params: ClickCoordinatesInput) -> dict[str, Any]:
	"""Translate coordinate-only input to the current click action shape."""
	return ClickElementAction(
		index=None,
		coordinate_x=params.coordinate_x,
		coordinate_y=params.coordinate_y,
	).model_dump(exclude_none=True)
