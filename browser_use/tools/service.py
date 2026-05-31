import asyncio
import logging
import math
import os
from typing import Any, Generic, TypeVar

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.services import BrowserServiceBundle
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.observability import observe_debug
from browser_use.tools.done_result import build_done_result as build_done_action_result
from browser_use.tools.dropdown import dropdown_options_action, select_dropdown_action
from browser_use.tools.evaluate import execute_evaluate_action
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
from browser_use.tools.utils import get_click_description
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
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
	WaitAction,
	WriteFileAction,
)
from browser_use.utils import create_task_with_error_handling, time_execution_sync

logger = logging.getLogger(__name__)

# Import EnhancedDOMTreeNode and rebuild event models that have forward references to it
# This must be done after all imports are complete

Context = TypeVar('Context')

T = TypeVar('T', bound=BaseModel)


# Global per-action timeout: last-resort guard against hung event handlers.
# Individual CDP calls (Page.navigate etc.) have their own shorter timeouts,
# but event-bus `await event` and `event_result()` calls have none — if a
# watchdog handler blocks on a dead CDP WebSocket, the action can hang past
# any agent-level watchdog. This cap ensures every action returns within a
# bounded window with an ActionResult(error=...) instead of hanging silently.
#
# The default (180s) sits above the longest built-in inner timeout — the extract
# action's page_extraction_llm.ainvoke at 120s — plus comfortable grace, so
# slow-but-valid LLM-backed actions aren't truncated. Override per-call via
# BROWSER_USE_ACTION_TIMEOUT_S env var or tools.act(action_timeout=...).
_ACTION_TIMEOUT_FALLBACK_S = 180.0


def _parse_env_action_timeout(raw: str | None) -> float:
	"""Parse BROWSER_USE_ACTION_TIMEOUT_S defensively.

	Accepts only finite positive values. Empty, non-numeric, inf, nan, or
	non-positive values fall back to the hardcoded default with a warning
	— these would otherwise make every action time out immediately (nan)
	or disable the hang guard entirely (inf / negative / zero).
	"""
	if raw is None or raw == '':
		return _ACTION_TIMEOUT_FALLBACK_S
	try:
		parsed = float(raw)
	except ValueError:
		logging.getLogger(__name__).warning(
			'Invalid BROWSER_USE_ACTION_TIMEOUT_S=%r; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	if not math.isfinite(parsed) or parsed <= 0:
		logging.getLogger(__name__).warning(
			'BROWSER_USE_ACTION_TIMEOUT_S=%r is not a finite positive number; falling back to %.0fs',
			raw,
			_ACTION_TIMEOUT_FALLBACK_S,
		)
		return _ACTION_TIMEOUT_FALLBACK_S
	return parsed


_DEFAULT_ACTION_TIMEOUT_S = _parse_env_action_timeout(os.getenv('BROWSER_USE_ACTION_TIMEOUT_S'))


def _coerce_valid_action_timeout(value: float | None) -> float:
	"""Normalize a caller-supplied action_timeout to a finite positive value.

	Mirrors the env-var guard so the public `tools.act(action_timeout=...)`
	override path has the same defenses: nan / inf / <=0 make actions either
	time out immediately or never, which would silently defeat the hang
	guard this module exists to provide. Fall back to the env-derived
	default with a warning instead.
	"""
	if value is None:
		return _DEFAULT_ACTION_TIMEOUT_S
	if not math.isfinite(value) or value <= 0:
		logging.getLogger(__name__).warning(
			'action_timeout=%r is not a finite positive number; falling back to %.0fs',
			value,
			_DEFAULT_ACTION_TIMEOUT_S,
		)
		return _DEFAULT_ACTION_TIMEOUT_S
	return float(value)


def _detect_sensitive_key_name(text: str, sensitive_data: dict[str, str | dict[str, str]] | None) -> str | None:
	"""Detect which sensitive key name corresponds to the given text value."""
	if not sensitive_data or not text:
		return None

	# Collect all sensitive values and their keys
	for domain_or_key, content in sensitive_data.items():
		if isinstance(content, dict):
			# New format: {domain: {key: value}}
			for key, value in content.items():
				if value and value == text:
					return key
		elif content:  # Old format: {key: value}
			if content == text:
				return domain_or_key

	return None


def handle_browser_error(e: BrowserError) -> ActionResult:
	if e.long_term_memory is not None:
		if e.short_term_memory is not None:
			return ActionResult(
				extracted_content=e.short_term_memory, error=e.long_term_memory, include_extracted_content_only_once=True
			)
		else:
			return ActionResult(error=e.long_term_memory)
	# Fallback to original error handling if long_term_memory is None
	logger.warning(
		'⚠️ A BrowserError was raised without long_term_memory - always set long_term_memory when raising BrowserError to propagate right messages to LLM.'
	)
	raise e


def _is_autocomplete_field(node: EnhancedDOMTreeNode) -> bool:
	"""Detect if a node is an autocomplete/combobox field from its attributes."""
	attrs = node.attributes or {}
	if attrs.get('role') == 'combobox':
		return True
	aria_ac = attrs.get('aria-autocomplete', '')
	if aria_ac and aria_ac != 'none':
		return True
	if attrs.get('list'):
		return True
	haspopup = attrs.get('aria-haspopup', '')
	if haspopup and haspopup != 'false' and (attrs.get('aria-controls') or attrs.get('aria-owns')):
		return True
	return False


class Tools(Generic[Context]):
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

		# Helper function for coordinate conversion
		def _convert_llm_coordinates_to_viewport(llm_x: int, llm_y: int, browser_session: BrowserSession) -> tuple[int, int]:
			"""Convert coordinates from LLM screenshot size to original viewport size."""
			if browser_session.llm_screenshot_size and browser_session._original_viewport_size:
				original_width, original_height = browser_session._original_viewport_size
				llm_width, llm_height = browser_session.llm_screenshot_size

				# Convert coordinates using fractions
				actual_x = int((llm_x / llm_width) * original_width)
				actual_y = int((llm_y / llm_height) * original_height)

				logger.info(
					f'🔄 Converting coordinates: LLM ({llm_x}, {llm_y}) @ {llm_width}x{llm_height} '
					f'→ Viewport ({actual_x}, {actual_y}) @ {original_width}x{original_height}'
				)
				return actual_x, actual_y
			return llm_x, llm_y

		# Element Interaction Actions
		async def _detect_new_tab_opened(
			browser_session: BrowserSession,
			tabs_before: set[str],
		) -> str:
			"""Detect if a click opened a new tab and automatically switch to it."""
			try:
				# Brief delay to allow CDP Target.attachedToTarget events to propagate
				# and be processed by SessionManager._handle_target_attached
				await asyncio.sleep(0.05)

				tabs_after = await browser_session.get_tabs()
				new_tabs = [t for t in tabs_after if t.target_id not in tabs_before]
				if new_tabs:
					new_tab = new_tabs[0]
					new_tab_id = new_tab.target_id[-4:]
					# Auto-switch to the new tab so the agent can immediately interact with it
					try:
						await BrowserServiceBundle.from_session(browser_session).tabs.switch(new_tab.target_id)
						return f'. Automatically switched to new tab (tab_id: {new_tab_id}).'
					except Exception:
						return f'. Note: This opened a new tab (tab_id: {new_tab_id}) - switch to it if you need to interact with the new page.'
			except Exception:
				pass
			return ''

		async def _click_by_coordinate(params: ClickElementAction, browser_session: BrowserSession) -> ActionResult:
			# Ensure coordinates are provided (type safety)
			if params.coordinate_x is None or params.coordinate_y is None:
				return ActionResult(error='Both coordinate_x and coordinate_y must be provided')

			try:
				# Convert coordinates from LLM size to original viewport size if resizing was used
				actual_x, actual_y = _convert_llm_coordinates_to_viewport(
					params.coordinate_x, params.coordinate_y, browser_session
				)

				# Capture tab IDs before click to detect new tabs
				tabs_before = {t.target_id for t in await browser_session.get_tabs()}

				# Highlight the coordinate being clicked (truly non-blocking)
				asyncio.create_task(browser_session.highlight_coordinate_click(actual_x, actual_y))

				click_metadata = await BrowserServiceBundle.from_session(browser_session).actions.click.click_coordinates(
					actual_x,
					actual_y,
					force=True,
				)

				# Check for validation errors (only happens when force=False)
				if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
					error_msg = click_metadata['validation_error']
					return ActionResult(error=error_msg)

				memory = f'Clicked on coordinate {params.coordinate_x}, {params.coordinate_y}'
				memory += await _detect_new_tab_opened(browser_session, tabs_before)
				logger.info(f'🖱️ {memory}')

				return ActionResult(
					extracted_content=memory,
					metadata={'click_x': actual_x, 'click_y': actual_y},
				)
			except BrowserError as e:
				return handle_browser_error(e)
			except Exception as e:
				error_msg = f'Failed to click at coordinates ({params.coordinate_x}, {params.coordinate_y}).'
				return ActionResult(error=error_msg)

		async def _click_by_index(
			params: ClickElementAction | ClickElementActionIndexOnly, browser_session: BrowserSession
		) -> ActionResult:
			assert params.index is not None
			try:
				assert params.index != 0, (
					'Cannot click on element with index 0. If there are no interactive elements use wait(), refresh(), etc. to troubleshoot'
				)

				# Look up the node from the selector map
				node = await browser_session.get_element_by_index(params.index)
				if node is None:
					msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
					logger.warning(f'⚠️ {msg}')
					return ActionResult(extracted_content=msg)

				# Get description of clicked element
				element_desc = get_click_description(node)

				# Capture tab IDs before click to detect new tabs
				tabs_before = {t.target_id for t in await browser_session.get_tabs()}

				# Highlight the element being clicked (truly non-blocking)
				create_task_with_error_handling(
					browser_session.highlight_interaction_element(node), name='highlight_click_element', suppress_exceptions=True
				)

				click_metadata = await BrowserServiceBundle.from_session(browser_session).actions.click.click_index(params.index)

				# Check if result contains validation error (e.g., trying to click <select> or file input)
				if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
					error_msg = click_metadata['validation_error']
					# If it's a select element, try to get dropdown options as a helpful shortcut
					if 'Cannot click on <select> elements.' in error_msg:
						try:
							return await dropdown_options(
								params=GetDropdownOptionsAction(index=params.index), browser_session=browser_session
							)
						except Exception as dropdown_error:
							logger.debug(
								f'Failed to get dropdown options as shortcut during click on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
							)
					return ActionResult(error=error_msg)

				# Build memory with element info
				memory = f'Clicked {element_desc}'
				memory += await _detect_new_tab_opened(browser_session, tabs_before)
				logger.info(f'🖱️ {memory}')

				# Include click coordinates in metadata if available
				return ActionResult(
					extracted_content=memory,
					metadata=click_metadata if isinstance(click_metadata, dict) else None,
				)
			except BrowserError as e:
				return handle_browser_error(e)
			except Exception as e:
				error_msg = f'Failed to click element {params.index}: {str(e)}'
				return ActionResult(error=error_msg)

		# Store click handlers for re-registration
		self._click_by_index = _click_by_index
		self._click_by_coordinate = _click_by_coordinate

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
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
				logger.warning(f'⚠️ {msg}')
				return ActionResult(extracted_content=msg)

			# Highlight the element being typed into (truly non-blocking)
			create_task_with_error_handling(
				browser_session.highlight_interaction_element(node), name='highlight_type_element', suppress_exceptions=True
			)

			# Dispatch type text event with node
			try:
				# Detect which sensitive key is being used
				sensitive_key_name = None
				if has_sensitive_data and sensitive_data:
					sensitive_key_name = _detect_sensitive_key_name(params.text, sensitive_data)

				input_metadata = await BrowserServiceBundle.from_session(browser_session).actions.type.type_index(
					params.index,
					params.text,
					clear=params.clear,
					is_sensitive=has_sensitive_data,
					sensitive_key_name=sensitive_key_name,
				)

				# Create message with sensitive data handling
				if has_sensitive_data:
					if sensitive_key_name:
						msg = f'Typed {sensitive_key_name}'
						log_msg = f'Typed <{sensitive_key_name}>'
					else:
						msg = 'Typed sensitive data'
						log_msg = 'Typed <sensitive>'
				else:
					msg = f"Typed '{params.text}'"
					log_msg = f"Typed '{params.text}'"

				logger.debug(log_msg)

				# Check for value mismatch (non-sensitive only)
				actual_value = None
				if isinstance(input_metadata, dict):
					actual_value = input_metadata.pop('actual_value', None)

				if not has_sensitive_data and actual_value is not None and actual_value != params.text:
					msg += f"\n⚠️ Note: the field's actual value '{actual_value}' differs from typed text '{params.text}'. The page may have reformatted or autocompleted your input."

				# Check for autocomplete/combobox field — add mechanical delay for dropdown
				if _is_autocomplete_field(node):
					msg += '\n💡 This is an autocomplete field. Wait for suggestions to appear, then click the correct suggestion instead of pressing Enter.'
					# Only delay for true JS-driven autocomplete (combobox / aria-autocomplete),
					# not native <datalist> or loose aria-haspopup which the browser handles instantly
					attrs = node.attributes or {}
					if attrs.get('role') == 'combobox' or (attrs.get('aria-autocomplete', '') not in ('', 'none')):
						await asyncio.sleep(0.4)  # let JS dropdown populate before next action

				# Include input coordinates in metadata if available
				return ActionResult(
					extracted_content=msg,
					long_term_memory=msg,
					metadata=input_metadata if isinstance(input_metadata, dict) else None,
				)
			except BrowserError as e:
				return handle_browser_error(e)
			except Exception as e:
				# Log the full error for debugging
				logger.error(f'Failed to type through direct browser service: {type(e).__name__}: {e}')
				error_msg = f'Failed to type text into element {params.index}: {e}'
				return ActionResult(error=error_msg)

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
			try:
				# Look up the node from the selector map if index is provided
				# Special case: index 0 means scroll the whole page (root/body element)
				node = None
				if params.index is not None and params.index != 0:
					node = await browser_session.get_element_by_index(params.index)
					if node is None:
						# Element does not exist
						msg = f'Element index {params.index} not found in browser state'
						return ActionResult(error=msg)

				direction = 'down' if params.down else 'up'
				target = f'element {params.index}' if params.index is not None and params.index != 0 else ''

				scroll_metadata = await BrowserServiceBundle.from_session(browser_session).actions.scroll.scroll_pages_with_node(
					params.pages,
					direction=direction,
					node=node,
				)
				completed_pages = scroll_metadata['completed_pages']
				viewport_height = scroll_metadata['viewport_height']
				if params.pages == 1.0:
					long_term_memory = f'Scrolled {direction} {target} {viewport_height}px'.replace('  ', ' ')
				else:
					long_term_memory = f'Scrolled {direction} {target} {completed_pages:.1f} pages'.replace('  ', ' ')

				msg = f'🔍 {long_term_memory}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, long_term_memory=long_term_memory)
			except Exception as e:
				logger.error(f'Failed to scroll through direct browser service: {type(e).__name__}: {e}')
				error_msg = 'Failed to execute scroll action.'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser_session: BrowserSession):
			return await send_keys_action(params, browser_session)

		@self.registry.action('Scroll to text.', param_model=FindTextAction)
		async def find_text(params: FindTextAction, browser_session: BrowserSession):  # type: ignore
			try:
				await BrowserServiceBundle.from_session(browser_session).actions.scroll.scroll_to_text(params.text)
				memory = f'Scrolled to text: {params.text}'
				msg = f'🔍  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				# Text not found
				msg = f"Text '{params.text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					long_term_memory=f"Tried scrolling to text '{params.text}' but it was not found",
				)

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
		params: DoneAction | StructuredOutputAction[Any],
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
					return await self._click_by_index(params, browser_session)
				# Coordinate-based clicking when index is not provided
				else:
					return await self._click_by_coordinate(params, browser_session)
		else:
			# Register click action WITHOUT coordinate support (index only)
			@self.registry.action(
				'Click element by index.',
				param_model=ClickElementActionIndexOnly,
			)
			async def click(params: ClickElementActionIndexOnly, browser_session: BrowserSession):
				return await self._click_by_index(params, browser_session)

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

	# Act --------------------------------------------------------------------
	async def _execute_registered_action_result(
		self,
		*,
		action_name: str,
		params: dict,
		browser_session: BrowserSession | None,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
		extraction_schema: dict | None = None,
		action_timeout: float | None = None,
	) -> ActionResult:
		timeout_s = _coerce_valid_action_timeout(action_timeout)

		# Use Laminar span if available, otherwise use no-op context manager
		if Laminar is not None:
			span_context = Laminar.start_as_current_span(
				name=action_name,
				input={
					'action': action_name,
					'params': params,
				},
				span_type='TOOL',
			)
		else:
			# No-op context manager when lmnr is not available
			from contextlib import nullcontext

			span_context = nullcontext()

		with span_context:
			try:
				result = await asyncio.wait_for(
					self.registry.execute_action(
						action_name=action_name,
						params=params,
						browser_session=browser_session,
						page_extraction_llm=page_extraction_llm,
						file_system=file_system,
						sensitive_data=sensitive_data,
						available_file_paths=available_file_paths,
						extraction_schema=extraction_schema,
					),
					timeout=timeout_s,
				)
			except BrowserError as e:
				logger.error(f'❌ Action {action_name} failed with BrowserError: {str(e)}')
				result = handle_browser_error(e)
			except TimeoutError:
				# Covers both the per-action asyncio.wait_for cap and any inner
				# TimeoutError that bubbled out of the handler.
				logger.error(
					f'❌ Action {action_name} hit the per-action timeout ({timeout_s:.0f}s) '
					f'— likely an unresponsive CDP connection. Returning error so the agent can recover.'
				)
				result = ActionResult(
					error=(
						f'Action {action_name} timed out after {timeout_s:.0f}s. '
						f'The browser may be unresponsive (dead CDP WebSocket). '
						f'Try again or a different approach.'
					)
				)
			except Exception as e:
				# Log the original exception with traceback for observability
				logger.error(f"Action '{action_name}' failed with error: {str(e)}")
				result = ActionResult(error=str(e))

			if Laminar is not None:
				Laminar.set_span_output(result)

		if isinstance(result, str):
			return ActionResult(extracted_content=result)
		elif isinstance(result, ActionResult):
			return result
		elif result is None:
			return ActionResult()
		else:
			raise ValueError(f'Invalid action result type: {type(result)} of {result}')

	@observe_debug(ignore_input=True, ignore_output=True, name='act')
	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_session: BrowserSession,
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
		extraction_schema: dict | None = None,
		action_timeout: float | None = None,
	) -> ActionResult:
		"""Execute an action.

		action_timeout: per-action wall-clock cap (seconds). Prevents actions from hanging
		indefinitely when a CDP WebSocket goes silent — a common failure mode with remote
		browsers where internal CDP calls (tab switches, lifecycle waits) have no timeouts.
		Defaults to BROWSER_USE_ACTION_TIMEOUT_S env var or 180s (above the 120s
		page_extraction_llm cap used by the `extract` action).
		"""

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
				return await self._execute_registered_action_result(
					action_name=action_name,
					params=params,
					browser_session=browser_session,
					page_extraction_llm=page_extraction_llm,
					file_system=file_system,
					sensitive_data=sensitive_data,
					available_file_paths=available_file_paths,
					extraction_schema=extraction_schema,
					action_timeout=action_timeout,
				)
		return ActionResult()

	def __getattr__(self, name: str):
		"""
		Enable direct action calls like tools.navigate(url=..., browser_session=...).
		This provides a simpler API for tests and direct usage while maintaining backward compatibility.
		"""
		# Check if this is a registered action
		if name in self.registry.registry.actions:
			action = self.registry.registry.actions[name]

			# Create a wrapper that uses the same execution path as act() without building a dynamic ActionModel.
			async def action_wrapper(**kwargs):
				# Extract browser_session (required by actions that interact with the browser)
				browser_session = kwargs.get('browser_session')

				# Separate action params from special params (injected dependencies)
				special_param_names = {
					'browser_session',
					'page_extraction_llm',
					'file_system',
					'available_file_paths',
					'sensitive_data',
					'extraction_schema',
					'action_timeout',
				}

				# Extract action params (params for the action itself)
				action_params = {k: v for k, v in kwargs.items() if k not in special_param_names}

				# Extract special params (injected dependencies)
				special_kwargs = {k: v for k, v in kwargs.items() if k in special_param_names}

				# Preserve the old direct-call behavior: validate kwargs before execution.
				validated_params = action.param_model(**action_params)

				return await self._execute_registered_action_result(
					action_name=name,
					params=validated_params.model_dump(),
					browser_session=browser_session,
					page_extraction_llm=special_kwargs.get('page_extraction_llm'),
					file_system=special_kwargs.get('file_system'),
					sensitive_data=special_kwargs.get('sensitive_data'),
					available_file_paths=special_kwargs.get('available_file_paths'),
					extraction_schema=special_kwargs.get('extraction_schema'),
					action_timeout=special_kwargs.get('action_timeout'),
				)

			return action_wrapper

		# If not an action, raise AttributeError for normal Python behavior
		raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


# Alias for backwards compatibility
Controller = Tools
