import logging
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.tools.done_result import build_done_result as build_done_action_result
from browser_use.tools.dropdown import dropdown_options_action, select_dropdown_action
from browser_use.tools.element_actions import (
	click_by_coordinate_action,
	click_by_index_action,
	find_text_action,
	input_text_action,
	scroll_action,
)
from browser_use.tools.evaluate import execute_evaluate_action
from browser_use.tools.execution import (
	_DEFAULT_ACTION_TIMEOUT_S as _DEFAULT_ACTION_TIMEOUT_S,
)
from browser_use.tools.execution import (
	ToolsExecutionMixin,
)
from browser_use.tools.execution import (
	_coerce_valid_action_timeout as _coerce_valid_action_timeout,
)
from browser_use.tools.extraction.action import extract_action
from browser_use.tools.file_actions import (
	read_file_action,
	replace_file_action,
	save_as_pdf_action,
	take_screenshot_action,
	write_file_action,
)
from browser_use.tools.navigation import (
	close_tab_action,
	go_back_action,
	navigate_action,
	search_action,
	send_keys_action,
	switch_tab_action,
	wait_action,
)
from browser_use.tools.page_query import find_elements_action, search_page_action
from browser_use.tools.registry.service import Registry
from browser_use.tools.upload import upload_file_action
from browser_use.tools.views import (
	ClickElementAction,
	ClickElementActionIndexOnly,
	CloseTabAction,
	DoneAction,
	EvaluateAction,
	ExtractAction,
	FindElementsAction,
	FindTextAction,
	GetDropdownOptionsAction,
	InputTextAction,
	NavigateAction,
	NoParamsAction,
	ReadFileAction,
	ReplaceFileAction,
	SaveAsPdfAction,
	ScreenshotAction,
	ScrollAction,
	SearchAction,
	SearchPageAction,
	SelectDropdownOptionAction,
	SendKeysAction,
	StructuredDoneInput,
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
	WaitAction,
	WriteFileAction,
)

logger = logging.getLogger(__name__)

Context = TypeVar('Context')

T = TypeVar('T', bound=BaseModel)


class Tools(ToolsExecutionMixin, Generic[Context]):
	def __init__(
		self,
		exclude_actions: list[str] | None = None,
		output_model: type[T] | None = None,
		display_files_in_done_text: bool = True,
	):
		self.registry = Registry[Context](exclude_actions if exclude_actions is not None else [])
		self.display_files_in_done_text = display_files_in_done_text
		self._output_model: type[BaseModel] | None = output_model
		self._coordinate_clicking_enabled: bool = False

		"""Register all default browser actions"""

		self._register_done_action(output_model)

		# Basic Navigation Actions
		@self.registry.action(
			'',
			param_model=SearchAction,
			terminates_sequence=True,
		)
		async def search(params: SearchAction, browser_session: BrowserSession):
			return await search_action(params, browser_session)

		@self.registry.action(
			'',
			param_model=NavigateAction,
			terminates_sequence=True,
		)
		async def navigate(params: NavigateAction, browser_session: BrowserSession):
			return await navigate_action(params, browser_session)

		@self.registry.action('Go back', param_model=NoParamsAction, terminates_sequence=True)
		async def go_back(_: NoParamsAction, browser_session: BrowserSession):
			return await go_back_action(browser_session)

		@self.registry.action('Wait for x seconds.', param_model=WaitAction)
		async def wait(params: WaitAction):
			return await wait_action(params)

		# Register click action (index-only by default)
		self._register_click_action()

		@self.registry.action(
			'Input text into element by index. Clears existing text by default; pass text="" to clear only, or clear=False to append.',
			param_model=InputTextAction,
		)
		async def input(
			params: InputTextAction,
			browser_session: BrowserSession,
			has_sensitive_data: bool = False,
			sensitive_data: dict[str, str | dict[str, str]] | None = None,
		):
			return await input_text_action(
				params,
				browser_session,
				has_sensitive_data=has_sensitive_data,
				sensitive_data=sensitive_data,
			)

		@self.registry.action(
			'',
			param_model=UploadFileAction,
		)
		async def upload_file(
			params: UploadFileAction, browser_session: BrowserSession, available_file_paths: list[str], file_system: FileSystem
		):
			return await upload_file_action(
				params,
				browser_session=browser_session,
				available_file_paths=available_file_paths,
				file_system=file_system,
			)

		# Tab Management Actions

		@self.registry.action(
			'Switch to another open tab by tab_id. Tab IDs are shown in browser state tabs list (last 4 chars of target_id). Use when you need to work with content in a different tab.',
			param_model=SwitchTabAction,
			terminates_sequence=True,
		)
		async def switch(params: SwitchTabAction, browser_session: BrowserSession):
			return await switch_tab_action(params, browser_session)

		@self.registry.action(
			'Close a tab by tab_id. Tab IDs are shown in browser state tabs list (last 4 chars of target_id). Use to clean up tabs you no longer need.',
			param_model=CloseTabAction,
		)
		async def close(params: CloseTabAction, browser_session: BrowserSession):
			return await close_tab_action(params, browser_session)

		@self.registry.action(
			"""LLM extracts structured data from page markdown. Use when: on right page, know what to extract, haven't called before on same page+query. Can't get interactive elements. Set extract_links=True for URLs. Set extract_images=True for image src URLs. Use start_from_char if previous extraction was truncated to extract data further down the page. When paginating across pages, pass already_collected with item identifiers (names/URLs) from prior pages to avoid duplicates.""",
			param_model=ExtractAction,
		)
		async def extract(
			params: ExtractAction,
			browser_session: BrowserSession,
			page_extraction_llm: BaseChatModel,
			file_system: FileSystem,
			extraction_schema: dict | None = None,
		):
			return await extract_action(
				params,
				browser_session=browser_session,
				page_extraction_llm=page_extraction_llm,
				file_system=file_system,
				extraction_schema=extraction_schema,
			)

		# --- Page search and exploration tools (zero LLM cost) ---

		@self.registry.action(
			"""Search page text for a pattern (like grep). Zero LLM cost, instant. Returns matches with surrounding context. Use to find specific text, verify content exists, or locate data on the page. Set regex=True for regex patterns. Use css_scope to search within a specific section.""",
			param_model=SearchPageAction,
		)
		async def search_page(params: SearchPageAction, browser_session: BrowserSession):
			return await search_page_action(params, browser_session)

		@self.registry.action(
			"""Query DOM elements by CSS selector (like find). Zero LLM cost, instant. Returns matching elements with tag, text, and attributes. Use to explore page structure, count items, get links/attributes. Use attributes=["href","src"] to extract specific attributes.""",
			param_model=FindElementsAction,
		)
		async def find_elements(params: FindElementsAction, browser_session: BrowserSession):
			return await find_elements_action(params, browser_session)

		@self.registry.action(
			"""Scroll by pages. REQUIRED: down=True/False (True=scroll down, False=scroll up, default=True). Optional: pages=0.5-10.0 (default 1.0). Use index for scroll elements (dropdowns/custom UI). High pages (10) reaches bottom. Multi-page scrolls sequentially. Viewport-based height, fallback 1000px/page.""",
			param_model=ScrollAction,
		)
		async def scroll(params: ScrollAction, browser_session: BrowserSession):
			return await scroll_action(params, browser_session)

		@self.registry.action(
			'',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser_session: BrowserSession):
			return await send_keys_action(params, browser_session)

		@self.registry.action('Scroll to text.', param_model=FindTextAction)
		async def find_text(params: FindTextAction, browser_session: BrowserSession):  # type: ignore
			return await find_text_action(params, browser_session)

		@self.registry.action(
			'Take a screenshot of the current viewport. If file_name is provided, saves to that file and returns the path. '
			'Otherwise, screenshot is included in the next browser_state observation.',
			param_model=ScreenshotAction,
		)
		async def screenshot(
			params: ScreenshotAction,
			browser_session: BrowserSession,
			file_system: FileSystem,
		):
			return await take_screenshot_action(params, browser_session=browser_session, file_system=file_system)

		# PDF Actions

		@self.registry.action(
			'Save the current page as a PDF file. Returns the file path of the saved PDF. '
			'Use this to capture the full page content (including content below the fold) as a printable document.',
			param_model=SaveAsPdfAction,
		)
		async def save_as_pdf(
			params: SaveAsPdfAction,
			browser_session: BrowserSession,
			file_system: FileSystem,
		):
			return await save_as_pdf_action(params, browser_session=browser_session, file_system=file_system)

		# Dropdown Actions

		@self.registry.action(
			'',
			param_model=GetDropdownOptionsAction,
		)
		async def dropdown_options(params: GetDropdownOptionsAction, browser_session: BrowserSession):
			return await dropdown_options_action(params, browser_session)

		@self.registry.action(
			'Set the option of a <select> element.',
			param_model=SelectDropdownOptionAction,
		)
		async def select_dropdown(params: SelectDropdownOptionAction, browser_session: BrowserSession):
			return await select_dropdown_action(params, browser_session)

		# File System Actions

		@self.registry.action(
			'Write content to a file. By default this OVERWRITES the entire file - use append=true to add to an existing file, or use replace_file for targeted edits within a file. '
			'FILENAME RULES: Use only letters, numbers, underscores, hyphens, dots, parentheses. Spaces are auto-converted to hyphens. '
			'SUPPORTED EXTENSIONS: .txt, .md, .json, .jsonl, .csv, .html, .xml, .pdf, .docx. '
			'CANNOT write binary/image files (.png, .jpg, .mp4, etc.) - do not attempt to save screenshots as files. '
			'For PDF files, write content in markdown format and it will be auto-converted to PDF.',
			param_model=WriteFileAction,
		)
		async def write_file(params: WriteFileAction, file_system: FileSystem):
			return await write_file_action(params, file_system)

		@self.registry.action(
			'Replace specific text within a file by searching for old_str and replacing with new_str. Use this for targeted edits like updating todo checkboxes or modifying specific lines without rewriting the entire file.',
			param_model=ReplaceFileAction,
		)
		async def replace_file(params: ReplaceFileAction, file_system: FileSystem):
			return await replace_file_action(params, file_system)

		@self.registry.action(
			'Read the complete content of a file. Use this to view file contents before editing or to retrieve data from files. Supports text files (txt, md, json, csv, jsonl), documents (pdf, docx), and images (jpg, png).',
			param_model=ReadFileAction,
		)
		async def read_file(params: ReadFileAction, available_file_paths: list[str], file_system: FileSystem):
			return await read_file_action(params, available_file_paths=available_file_paths, file_system=file_system)

		@self.registry.action(
			"""Execute browser JavaScript. Best practice: wrap in IIFE (function(){...})() with try-catch for safety. Use ONLY browser APIs (document, window, DOM). NO Node.js APIs (fs, require, process). Example: (function(){try{const el=document.querySelector('#id');return el?el.value:'not found'}catch(e){return 'Error: '+e.message}})() Avoid comments. Use for hover, drag, zoom, custom selectors, extract/filter links, or analysing page structure. IMPORTANT: Shadow DOM elements with [index] markers can be clicked directly with click(index) — do NOT use evaluate() to click them. Only use evaluate for shadow DOM elements that are NOT indexed. Limit output size.""",
			param_model=EvaluateAction,
			terminates_sequence=True,
		)
		async def evaluate(params: EvaluateAction, browser_session: BrowserSession):
			return await execute_evaluate_action(params, browser_session)

	def _register_done_action(self, output_model: type[T] | None, display_files_in_done_text: bool = True):
		if output_model is not None:
			self.display_files_in_done_text = display_files_in_done_text

			@self.registry.action(
				'Complete task with structured output.',
				param_model=StructuredOutputAction[output_model],
			)
			async def done(params: StructuredOutputAction, file_system: FileSystem, browser_session: BrowserSession):
				return self.build_done_result(params, file_system=file_system, browser_session=browser_session)

		else:

			@self.registry.action(
				'Complete task. Only report actions you performed and data you extracted in this session.',
				param_model=DoneAction,
			)
			async def done(params: DoneAction, file_system: FileSystem):
				return self.build_done_result(params, file_system=file_system)

	def build_done_result(
		self,
		params: DoneAction | StructuredDoneInput[Any],
		*,
		file_system: FileSystem,
		browser_session: BrowserSession | None = None,
	) -> ActionResult:
		"""Build the terminal result for legacy and native done paths."""
		return build_done_action_result(
			params,
			file_system=file_system,
			browser_session=browser_session,
			display_files_in_done_text=self.display_files_in_done_text,
		)

	def use_structured_output_action(self, output_model: type[T]):
		self._output_model = output_model
		self._register_done_action(output_model)

	def get_output_model(self) -> type[BaseModel] | None:
		"""Get the output model if structured output is configured."""
		return self._output_model

	# Register ---------------------------------------------------------------

	def action(self, description: str, **kwargs):
		"""Decorator for registering custom actions

		@param description: Describe the LLM what the function does (better description == better function calling)
		"""
		return self.registry.action(description, **kwargs)

	def exclude_action(self, action_name: str) -> None:
		"""Exclude an action from the tools registry.

		This method can be used to remove actions after initialization,
		useful for enforcing constraints like disabling screenshot when use_vision != 'auto'.

		Args:
			action_name: Name of the action to exclude (e.g., 'screenshot')
		"""
		self.registry.exclude_action(action_name)

	def _register_click_action(self) -> None:
		"""Register the click action with or without coordinate support based on current setting."""
		# Remove existing click action if present
		if 'click' in self.registry.registry.actions:
			del self.registry.registry.actions['click']

		if self._coordinate_clicking_enabled:
			# Register click action WITH coordinate support
			@self.registry.action(
				'Click element by index or coordinates. Use coordinates only if the index is not available. Either provide coordinates or index.',
				param_model=ClickElementAction,
			)
			async def click(params: ClickElementAction, browser_session: BrowserSession):
				# Validate that either index or coordinates are provided
				if params.index is None and (params.coordinate_x is None or params.coordinate_y is None):
					return ActionResult(error='Must provide either index or both coordinate_x and coordinate_y')

				# Try index-based clicking first if index is provided
				if params.index is not None:
					return await click_by_index_action(params, browser_session)
				# Coordinate-based clicking when index is not provided
				else:
					return await click_by_coordinate_action(params, browser_session)
		else:
			# Register click action WITHOUT coordinate support (index only)
			@self.registry.action(
				'Click element by index.',
				param_model=ClickElementActionIndexOnly,
			)
			async def click(params: ClickElementActionIndexOnly, browser_session: BrowserSession):
				return await click_by_index_action(params, browser_session)

	def set_coordinate_clicking(self, enabled: bool) -> None:
		"""Enable or disable coordinate-based clicking.

		When enabled, the click action accepts both index and coordinate parameters.
		When disabled (default), only index-based clicking is available.

		This is automatically enabled for models that support coordinate clicking:
		- claude-sonnet-4-5
		- claude-opus-4-5
		- gemini-3-pro
		- browser-use/* models

		Args:
			enabled: True to enable coordinate clicking, False to disable
		"""
		if enabled == self._coordinate_clicking_enabled:
			return  # No change needed

		self._coordinate_clicking_enabled = enabled
		self._register_click_action()
		logger.debug(f'Coordinate clicking {"enabled" if enabled else "disabled"}')


# Alias for backwards compatibility
Controller = Tools
