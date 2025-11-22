import asyncio
import enum
import json
import logging
import os
from typing import Generic, TypeVar

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.events import (
	ClickCoordinateEvent,
	ClickElementEvent,
	CloseTabEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	NavigateToUrlEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SendKeysEvent,
	SwitchTabEvent,
	TypeTextEvent,
	UploadFileEvent,
)
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.observability import observe_debug
from browser_use.tools.registry.service import Registry
from browser_use.tools.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	ExtractAction,
	GetDropdownOptionsAction,
	InputTextAction,
	NavigateAction,
	NoParamsAction,
	ScrollAction,
	SearchAction,
	SelectDropdownOptionAction,
	SendKeysAction,
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
)
from browser_use.utils import create_task_with_error_handling, sanitize_surrogates, time_execution_sync

logger = logging.getLogger(__name__)

# Import EnhancedDOMTreeNode and rebuild event models that have forward references to it
# This must be done after all imports are complete
ClickElementEvent.model_rebuild()
TypeTextEvent.model_rebuild()
ScrollEvent.model_rebuild()
UploadFileEvent.model_rebuild()

Context = TypeVar('Context')

T = TypeVar('T', bound=BaseModel)


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


class Tools(Generic[Context]):
	def __init__(
		self,
		exclude_actions: list[str] | None = None,
		output_model: type[T] | None = None,
		display_files_in_done_text: bool = True,
	):
		self.registry = Registry[Context](exclude_actions if exclude_actions is not None else [])
		self.display_files_in_done_text = display_files_in_done_text

		"""Register all default browser actions"""

		self._register_done_action(output_model)

		# Basic Navigation Actions
		@self.registry.action(
			'',
			param_model=SearchAction,
		)
		async def search(params: SearchAction, browser_session: BrowserSession):
			import urllib.parse

			# Encode query for URL safety
			encoded_query = urllib.parse.quote_plus(params.query)

			# Build search URL based on search engine
			search_engines = {
				'duckduckgo': f'https://duckduckgo.com/?q={encoded_query}',
				'google': f'https://www.google.com/search?q={encoded_query}&udm=14',
				'bing': f'https://www.bing.com/search?q={encoded_query}',
			}

			if params.engine.lower() not in search_engines:
				return ActionResult(error=f'Unsupported search engine: {params.engine}. Options: duckduckgo, google, bing')

			search_url = search_engines[params.engine.lower()]

			# Simple tab logic: use current tab by default
			use_new_tab = False

			# Dispatch navigation event
			try:
				event = browser_session.event_bus.dispatch(
					NavigateToUrlEvent(
						url=search_url,
						new_tab=use_new_tab,
					)
				)
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = f"Searched {params.engine.title()} for '{params.query}'"
				msg = f'🔍  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to search {params.engine}: {e}')
				return ActionResult(error=f'Failed to search {params.engine} for "{params.query}": {str(e)}')

		@self.registry.action(
			'',
			param_model=NavigateAction,
		)
		async def navigate(params: NavigateAction, browser_session: BrowserSession):
			try:
				# Dispatch navigation event
				event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=params.url, new_tab=params.new_tab))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)

				if params.new_tab:
					memory = f'Opened new tab with URL {params.url}'
					msg = f'🔗  Opened new tab with url {params.url}'
				else:
					memory = f'Navigated to {params.url}'
					msg = f'🔗 {memory}'

				logger.info(msg)
				return ActionResult(extracted_content=msg, long_term_memory=memory)
			except Exception as e:
				error_msg = str(e)
				# Always log the actual error first for debugging
				browser_session.logger.error(f'❌ Navigation failed: {error_msg}')

				# Check if it's specifically a RuntimeError about CDP client
				if isinstance(e, RuntimeError) and 'CDP client not initialized' in error_msg:
					browser_session.logger.error('❌ Browser connection failed - CDP client not properly initialized')
					return ActionResult(error=f'Browser connection error: {error_msg}')
				# Check for network-related errors
				elif any(
					err in error_msg
					for err in [
						'ERR_NAME_NOT_RESOLVED',
						'ERR_INTERNET_DISCONNECTED',
						'ERR_CONNECTION_REFUSED',
						'ERR_TIMED_OUT',
						'net::',
					]
				):
					site_unavailable_msg = f'Navigation failed - site unavailable: {params.url}'
					browser_session.logger.warning(f'⚠️ {site_unavailable_msg} - {error_msg}')
					return ActionResult(error=site_unavailable_msg)
				else:
					# Return error in ActionResult instead of re-raising
					return ActionResult(error=f'Navigation failed: {str(e)}')

		@self.registry.action('Go back', param_model=NoParamsAction)
		async def go_back(_: NoParamsAction, browser_session: BrowserSession):
			try:
				event = browser_session.event_bus.dispatch(GoBackEvent())
				await event
				memory = 'Navigated back'
				msg = f'🔙  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory)
			except Exception as e:
				logger.error(f'Failed to dispatch GoBackEvent: {type(e).__name__}: {e}')
				error_msg = f'Failed to go back: {str(e)}'
				return ActionResult(error=error_msg)

		@self.registry.action('Wait for x seconds.')
		async def wait(seconds: int = 3):
			# Cap wait time at maximum 30 seconds
			# Reduce the wait time by 3 seconds to account for the llm call which takes at least 3 seconds
			# So if the model decides to wait for 5 seconds, the llm call took at least 3 seconds, so we only need to wait for 2 seconds
			# Note by Mert: the above doesnt make sense because we do the LLM call right after this or this could be followed by another action after which we would like to wait
			# so I revert this.
			actual_seconds = min(max(seconds - 1, 0), 30)
			memory = f'Waited for {seconds} seconds'
			logger.info(f'🕒 waited for {seconds} second{"" if seconds == 1 else "s"}')
			await asyncio.sleep(actual_seconds)
			return ActionResult(extracted_content=memory, long_term_memory=memory)

		# Helper function to find file input near element using CDP traversal
		async def _find_file_input_near_element(
			node: EnhancedDOMTreeNode, browser_session: BrowserSession
		) -> EnhancedDOMTreeNode | None:
			"""Find file input near element using CDP DOM traversal.

			Searches in order:
			1. Children of the clicked element
			2. Siblings (parent's children)
			3. Entire page (fallback)

			Returns minimal EnhancedDOMTreeNode with backend_node_id, or None if not found.
			"""
			from browser_use.dom.views import NodeType

			page = await browser_session.get_current_page()
			if page is None:
				return None

			try:
				session_id = await page._ensure_session()
				found_file_input_node_id = None

				# Get node info to access nodeId and parentId
				describe_result = await browser_session.cdp_client.send.DOM.describeNode(
					params={'backendNodeId': node.backend_node_id}, session_id=session_id
				)
				node_id = describe_result['node']['nodeId']
				parent_id = describe_result['node'].get('parentId')

				# Strategy 1: Check children of clicked element
				try:
					result = await browser_session.cdp_client.send.DOM.querySelectorAll(
						params={'nodeId': node_id, 'selector': 'input[type="file"]'}, session_id=session_id
					)
					if result['nodeIds']:
						found_file_input_node_id = result['nodeIds'][0]
						logger.info('Found file input in children of clicked element')
				except Exception as e:
					logger.debug(f'No file input in children: {e}')

				# Strategy 2: Check siblings (query parent's children)
				if not found_file_input_node_id and parent_id:
					try:
						result = await browser_session.cdp_client.send.DOM.querySelectorAll(
							params={'nodeId': parent_id, 'selector': 'input[type="file"]'}, session_id=session_id
						)
						if result['nodeIds']:
							found_file_input_node_id = result['nodeIds'][0]
							logger.info('Found file input in siblings of clicked element')
					except Exception as e:
						logger.debug(f'No file input in siblings: {e}')

				# Strategy 3: Fallback to page-wide search
				if not found_file_input_node_id:
					logger.info('No file input found nearby, searching entire page...')
					file_inputs = await page.get_elements_by_css_selector('input[type="file"]')
					if file_inputs:
						element_info = await file_inputs[0].get_basic_info()
						found_file_input_node_id = element_info['nodeId']
						logger.info('Found file input on page (fallback)')
					else:
						logger.warning('No file input found on the page')
						return None

				# Get backend node ID for the found file input
				if found_file_input_node_id is not None:
					describe_result = await browser_session.cdp_client.send.DOM.describeNode(
						params={'nodeId': found_file_input_node_id}, session_id=session_id
					)
					file_input_backend_node_id = describe_result['node']['backendNodeId']
				else:
					return None

				# Create minimal node for the file input
				return EnhancedDOMTreeNode(
					node_id=found_file_input_node_id,
					backend_node_id=file_input_backend_node_id,
					node_type=NodeType.ELEMENT_NODE,
					node_name='INPUT',
					node_value='',
					attributes={'type': 'file'},
					is_scrollable=None,
					frame_id=node.frame_id,
					session_id=session_id,
					target_id=browser_session.agent_focus_target_id or '',
					content_document=None,
					shadow_root_type=None,
					shadow_roots=None,
					parent_node=None,
					children_nodes=None,
					ax_node=None,
					snapshot_node=None,
					is_visible=None,
					absolute_position=None,
				)

			except Exception as e:
				logger.error(f'Failed to find file input: {e}')
				return None

		# Helper functions for coordinate and scroll delta conversion
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

		def _convert_llm_scroll_deltas_to_viewport(
			llm_scroll_x: int, llm_scroll_y: int, browser_session: BrowserSession
		) -> tuple[int, int]:
			"""Convert scroll deltas from LLM screenshot size to original viewport size."""
			if browser_session.llm_screenshot_size and browser_session._original_viewport_size:
				original_width, original_height = browser_session._original_viewport_size
				llm_width, llm_height = browser_session.llm_screenshot_size

				# Scale scroll deltas using the same ratio as coordinates
				actual_scroll_x = int((llm_scroll_x / llm_width) * original_width)
				actual_scroll_y = int((llm_scroll_y / llm_height) * original_height)

				logger.info(
					f'🔄 Scaling scroll deltas: LLM ({llm_scroll_x}, {llm_scroll_y}) @ {llm_width}x{llm_height} '
					f'→ Viewport ({actual_scroll_x}, {actual_scroll_y}) @ {original_width}x{original_height}'
				)
				return actual_scroll_x, actual_scroll_y
			return llm_scroll_x, llm_scroll_y

		# Element Interaction Actions
		async def _click_by_coordinate(params: ClickElementAction, browser_session: BrowserSession) -> ActionResult:
			# Ensure coordinates are provided (type safety)
			logger.debug(
				f'🔍 [CLICK DEBUG] Starting click at ({params.coordinate_x}, {params.coordinate_y}), force={params.force}'
			)
			if params.coordinate_x is None or params.coordinate_y is None:
				return ActionResult(error='Both coordinate_x and coordinate_y must be provided')

			try:
				# Convert coordinates from LLM size to original viewport size if resizing was used
				logger.debug('🔍 [CLICK DEBUG] Converting coordinates...')
				actual_x, actual_y = _convert_llm_coordinates_to_viewport(
					params.coordinate_x, params.coordinate_y, browser_session
				)
				logger.debug(f'🔍 [CLICK DEBUG] Converted to actual coordinates: ({actual_x}, {actual_y})')

				# Highlight the coordinate being clicked (truly non-blocking)
				logger.debug('🔍 [CLICK DEBUG] Creating highlight task...')
				asyncio.create_task(browser_session.highlight_coordinate_click(actual_x, actual_y))

				# Dispatch ClickCoordinateEvent - handler will check for safety and click
				# Pass force parameter from params (defaults to False for safety)
				logger.debug('🔍 [CLICK DEBUG] Dispatching ClickCoordinateEvent...')
				event = browser_session.event_bus.dispatch(
					ClickCoordinateEvent(coordinate_x=actual_x, coordinate_y=actual_y, force=params.force)
				)
				logger.debug('🔍 [CLICK DEBUG] Event dispatched, awaiting event...')
				await event
				logger.debug('🔍 [CLICK DEBUG] Event completed, getting result...')
				click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
				logger.debug(f'🔍 [CLICK DEBUG] Got click_metadata: {type(click_metadata).__name__}')

				# Check for validation errors (only happens when force=False)
				if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
					logger.debug(f'🔍 [CLICK DEBUG] Validation error found: {click_metadata["validation_error"]}')
					return ActionResult(error=click_metadata['validation_error'])

				logger.debug('🔍 [CLICK DEBUG] Building success message...')
				force_msg = ' (forced)' if params.force else ''
				memory = f'Clicked on coordinate {params.coordinate_x}, {params.coordinate_y}{force_msg}'
				msg = f'🖱️ {memory}'
				logger.info(msg)

				logger.debug('🔍 [CLICK DEBUG] Creating ActionResult...')
				result = ActionResult(
					extracted_content=memory,
					metadata=click_metadata if isinstance(click_metadata, dict) else {'click_x': actual_x, 'click_y': actual_y},
				)
				logger.debug('🔍 [CLICK DEBUG] ActionResult created successfully')
				return result
			except BrowserError as e:
				logger.debug(f'🔍 [CLICK DEBUG] BrowserError caught: {type(e).__name__}: {e}')
				return handle_browser_error(e)
			except Exception as e:
				# want to see the error
				import traceback

				logger.debug(f'🔍 [CLICK DEBUG] Exception caught: {type(e).__name__}: {e}')
				logger.debug(f'🔍 [CLICK DEBUG] Full traceback:\n{traceback.format_exc()}')
				error_msg = f'Failed to click at coordinates ({params.coordinate_x}, {params.coordinate_y}): {str(e)}'
				return ActionResult(error=error_msg)

		# async def _click_by_index(index: int, browser_session: BrowserSession) -> ActionResult:
		# 	try:
		# 		assert index != 0, (
		# 			'Cannot click on element with index 0. If there are no interactive elements use wait(), refresh(), etc. to troubleshoot'
		# 		)
		# 		# Look up the node from the selector map
		# 		node = await browser_session.get_element_by_index(index)
		# 		if node is None:
		# 			msg = f'Element index {index} not available - page may have changed. Try refreshing browser state.'
		# 			logger.warning(f'⚠️ {msg}')
		# 			return ActionResult(extracted_content=msg)

		# 		# Get description of clicked element
		# 		element_desc = get_click_description(node)

		# 		# Highlight the element being clicked (truly non-blocking)
		# 		create_task_with_error_handling(
		# 			browser_session.highlight_interaction_element(node), name='highlight_click_element', suppress_exceptions=True
		# 		)

		# 		event = browser_session.event_bus.dispatch(ClickElementEvent(node=node))
		# 		await event
		# 		# Wait for handler to complete and get any exception or metadata
		# 		click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)

		# 		# Check if result contains validation error (e.g., trying to click <select> or file input)
		# 		if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
		# 			error_msg = click_metadata['validation_error']
		# 			# If it's a select element, try to get dropdown options as a helpful shortcut
		# 			if 'Cannot click on <select> elements.' in error_msg:
		# 				try:
		# 					# Get element center coordinates from its bounding box
		# 					if node.absolute_position:
		# 						center_x = int(node.absolute_position.x + node.absolute_position.width / 2)
		# 						center_y = int(node.absolute_position.y + node.absolute_position.height / 2)
		# 						return await dropdown_options(
		# 							params=GetDropdownOptionsAction(coordinate_x=center_x, coordinate_y=center_y),
		# 							browser_session=browser_session
		# 						)
		# 				except Exception as dropdown_error:
		# 					logger.debug(
		# 						f'Failed to get dropdown options as shortcut during click on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
		# 					)
		# 			return ActionResult(error=error_msg)

		# 		# Build memory with element info
		# 		memory = f'Clicked {element_desc}'
		# 		logger.info(f'🖱️ {memory}')

		# 		# Include click coordinates in metadata if available
		# 		return ActionResult(
		# 			extracted_content=memory,
		# 			metadata=click_metadata if isinstance(click_metadata, dict) else None,
		# 		)
		# 	except BrowserError as e:
		# 		return handle_browser_error(e)
		# 	except Exception as e:
		# 		error_msg = f'Failed to click element {index}: {str(e)}'
		# 		return ActionResult(error=error_msg)

		@self.registry.action(
			'Click on coordinates in the viewport. By default (force=False), performs safety checks: prevents clicking file inputs (use upload_file instead), print buttons (auto-generates PDF), and select dropdowns (use dropdown_options instead). Set force=True to bypass these checks - NOT RECOMMENDED unless absolutely necessary.',
			param_model=ClickElementAction,
		)
		async def click(params: ClickElementAction, browser_session: BrowserSession):
			return await _click_by_coordinate(params, browser_session)

		@self.registry.action(
			'Input text at coordinates by clicking then typing.',
			param_model=InputTextAction,
		)
		async def input(
			params: InputTextAction,
			browser_session: BrowserSession,
			has_sensitive_data: bool = False,
			sensitive_data: dict[str, str | dict[str, str]] | None = None,
		):
			try:
				# Convert coordinates from LLM size to original viewport size if resizing was used
				actual_x, actual_y = _convert_llm_coordinates_to_viewport(
					params.coordinate_x, params.coordinate_y, browser_session
				)

				# Highlight the coordinate being clicked (truly non-blocking)
				asyncio.create_task(browser_session.highlight_coordinate_click(actual_x, actual_y))

				# Step 1: Click at the coordinates to focus the input
				# Use force=True to bypass safety checks - we just want to focus for typing
				click_event = browser_session.event_bus.dispatch(
					ClickCoordinateEvent(coordinate_x=actual_x, coordinate_y=actual_y, force=True)
				)
				await click_event
				await click_event.event_result(raise_if_any=True, raise_if_none=False)

				# Step 2: Type the text using SendKeysEvent
				# Detect which sensitive key is being used
				sensitive_key_name = None
				if has_sensitive_data and sensitive_data:
					sensitive_key_name = _detect_sensitive_key_name(params.text, sensitive_data)

				# Use SendKeysEvent to type the text
				event = browser_session.event_bus.dispatch(SendKeysEvent(keys=params.text))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)

				# Create message with sensitive data handling
				if has_sensitive_data:
					if sensitive_key_name:
						msg = f'Typed {sensitive_key_name} at coordinates ({params.coordinate_x}, {params.coordinate_y})'
						log_msg = f'⌨️ Typed <{sensitive_key_name}> at ({params.coordinate_x}, {params.coordinate_y})'
					else:
						msg = f'Typed sensitive data at coordinates ({params.coordinate_x}, {params.coordinate_y})'
						log_msg = f'⌨️ Typed <sensitive> at ({params.coordinate_x}, {params.coordinate_y})'
				else:
					msg = f"Typed '{params.text}' at coordinates ({params.coordinate_x}, {params.coordinate_y})"
					log_msg = f"⌨️ Typed '{params.text}' at ({params.coordinate_x}, {params.coordinate_y})"

				logger.info(log_msg)

				return ActionResult(
					extracted_content=msg,
					long_term_memory=msg,
					metadata={'input_x': actual_x, 'input_y': actual_y},
				)
			except Exception as e:
				error_msg = f'Failed to type text at coordinates ({params.coordinate_x}, {params.coordinate_y}): {str(e)}'
				logger.error(f'❌ {error_msg}')
				return ActionResult(error=error_msg)

		@self.registry.action(
			'Upload a file to a file input element at coordinates.',
			param_model=UploadFileAction,
		)
		async def upload_file(
			params: UploadFileAction, browser_session: BrowserSession, available_file_paths: list[str], file_system: FileSystem
		):
			# Check if file is in available_file_paths (user-provided or downloaded files)
			# For remote browsers (is_local=False), we allow absolute remote paths even if not tracked locally
			if params.path not in available_file_paths:
				# Also check if it's a recently downloaded file that might not be in available_file_paths yet
				downloaded_files = browser_session.downloaded_files
				if params.path not in downloaded_files:
					# Finally, check if it's a file in the FileSystem service
					if file_system and file_system.get_dir():
						# Check if the file is actually managed by the FileSystem service
						# The path should be just the filename for FileSystem files
						file_obj = file_system.get_file(params.path)
						if file_obj:
							# File is managed by FileSystem, construct the full path
							file_system_path = str(file_system.get_dir() / params.path)
							params = UploadFileAction(
								coordinate_x=params.coordinate_x, coordinate_y=params.coordinate_y, path=file_system_path
							)
						else:
							# If browser is remote, allow passing a remote-accessible absolute path
							if not browser_session.is_local:
								pass
							else:
								msg = f'File path {params.path} is not available. To fix: The user must add this file path to the available_file_paths parameter when creating the Agent. Example: Agent(task="...", llm=llm, browser=browser, available_file_paths=["{params.path}"])'
								logger.error(f'❌ {msg}')
								return ActionResult(error=msg)
					else:
						# If browser is remote, allow passing a remote-accessible absolute path
						if not browser_session.is_local:
							pass
						else:
							msg = f'File path {params.path} is not available. To fix: The user must add this file path to the available_file_paths parameter when creating the Agent. Example: Agent(task="...", llm=llm, browser=browser, available_file_paths=["{params.path}"])'
							raise BrowserError(message=msg, long_term_memory=msg)

			# For local browsers, ensure the file exists on the local filesystem
			if browser_session.is_local:
				if not os.path.exists(params.path):
					msg = f'File {params.path} does not exist'
					return ActionResult(error=msg)

			# Convert coordinates from LLM size to viewport size
			actual_x, actual_y = _convert_llm_coordinates_to_viewport(params.coordinate_x, params.coordinate_y, browser_session)

			# Get element at coordinates first
			node = await browser_session.get_dom_element_at_coordinates(actual_x, actual_y)
			if node is None:
				msg = f'No element found at coordinates ({params.coordinate_x}, {params.coordinate_y})'
				logger.warning(f'⚠️ {msg}')
				return ActionResult(error=msg)

			# Check if the element at coordinates is already a file input
			if browser_session.is_file_input(node):
				logger.info('Element at coordinates is a file input - using it directly')
				file_input_node = node
			else:
				# Element at coordinates is not a file input - traverse DOM to find nearby file input
				logger.info(
					f'Element at coordinates is <{node.node_name}>, searching for nearby file input using CDP traversal...'
				)

				file_input_node = await _find_file_input_near_element(node, browser_session)
				if file_input_node is None:
					msg = 'No file input found on the page'
					logger.warning(f'⚠️ {msg}')
					return ActionResult(error=msg)

			# Highlight the file input element (truly non-blocking)
			create_task_with_error_handling(
				browser_session.highlight_interaction_element(file_input_node),
				name='highlight_file_input',
				suppress_exceptions=True,
			)

			# Dispatch upload file event with the file input node
			try:
				event = browser_session.event_bus.dispatch(UploadFileEvent(node=file_input_node, file_path=params.path))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				msg = f'Successfully uploaded file at coordinates ({params.coordinate_x}, {params.coordinate_y})'
				logger.info(f'📁 {msg}')
				return ActionResult(
					extracted_content=msg,
					long_term_memory=f'Uploaded file {params.path} to element at ({params.coordinate_x}, {params.coordinate_y})',
				)
			except Exception as e:
				logger.error(f'Failed to upload file: {e}')
				raise BrowserError(f'Failed to upload file: {e}')

		# Tab Management Actions

		@self.registry.action(
			'Switch to another open tab by tab_id. Tab IDs are shown in browser state tabs list (last 4 chars of target_id). Use when you need to work with content in a different tab.',
			param_model=SwitchTabAction,
		)
		async def switch(params: SwitchTabAction, browser_session: BrowserSession):
			# Simple switch tab logic
			try:
				target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)

				event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
				await event
				new_target_id = await event.event_result(raise_if_any=False, raise_if_none=False)  # Don't raise on errors

				if new_target_id:
					memory = f'Switched to tab #{new_target_id[-4:]}'
				else:
					memory = f'Switched to tab #{params.tab_id}'

				logger.info(f'🔄  {memory}')
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				logger.warning(f'Tab switch may have failed: {e}')
				memory = f'Attempted to switch to tab #{params.tab_id}'
				return ActionResult(extracted_content=memory, long_term_memory=memory)

		@self.registry.action(
			'Close a tab by tab_id. Tab IDs are shown in browser state tabs list (last 4 chars of target_id). Use to clean up tabs you no longer need.',
			param_model=CloseTabAction,
		)
		async def close(params: CloseTabAction, browser_session: BrowserSession):
			# Simple close tab logic
			try:
				target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)

				# Dispatch close tab event - handle stale target IDs gracefully
				event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=target_id))
				await event
				await event.event_result(raise_if_any=False, raise_if_none=False)  # Don't raise on errors

				memory = f'Closed tab #{params.tab_id}'
				logger.info(f'🗑️  {memory}')
				return ActionResult(
					extracted_content=memory,
					long_term_memory=memory,
				)
			except Exception as e:
				# Handle stale target IDs gracefully
				logger.warning(f'Tab {params.tab_id} may already be closed: {e}')
				memory = f'Tab #{params.tab_id} closed (was already closed or invalid)'
				return ActionResult(
					extracted_content=memory,
					long_term_memory=memory,
				)

		@self.registry.action(
			"""LLM extracts structured data from page markdown. Use when: on right page, know what to extract, haven't called before on same page+query. Can't get interactive elements. Set extract_links=True for URLs. Use start_from_char if previous extraction was truncated to extract data further down the page.""",
			param_model=ExtractAction,
		)
		async def extract(
			params: ExtractAction,
			browser_session: BrowserSession,
			page_extraction_llm: BaseChatModel,
			file_system: FileSystem,
		):
			# Constants
			MAX_CHAR_LIMIT = 30000
			query = params['query'] if isinstance(params, dict) else params.query
			extract_links = params['extract_links'] if isinstance(params, dict) else params.extract_links
			start_from_char = params['start_from_char'] if isinstance(params, dict) else params.start_from_char

			# Extract clean markdown using the unified method
			try:
				from browser_use.dom.markdown_extractor import extract_clean_markdown

				content, content_stats = await extract_clean_markdown(
					browser_session=browser_session, extract_links=extract_links
				)
			except Exception as e:
				raise RuntimeError(f'Could not extract clean markdown: {type(e).__name__}')

			# Original content length for processing
			final_filtered_length = content_stats['final_filtered_chars']

			if start_from_char > 0:
				if start_from_char >= len(content):
					return ActionResult(
						error=f'start_from_char ({start_from_char}) exceeds content length {final_filtered_length} characters.'
					)
				content = content[start_from_char:]
				content_stats['started_from_char'] = start_from_char

			# Smart truncation with context preservation
			truncated = False
			if len(content) > MAX_CHAR_LIMIT:
				# Try to truncate at a natural break point (paragraph, sentence)
				truncate_at = MAX_CHAR_LIMIT

				# Look for paragraph break within last 500 chars of limit
				paragraph_break = content.rfind('\n\n', MAX_CHAR_LIMIT - 500, MAX_CHAR_LIMIT)
				if paragraph_break > 0:
					truncate_at = paragraph_break
				else:
					# Look for sentence break within last 200 chars of limit
					sentence_break = content.rfind('.', MAX_CHAR_LIMIT - 200, MAX_CHAR_LIMIT)
					if sentence_break > 0:
						truncate_at = sentence_break + 1

				content = content[:truncate_at]
				truncated = True
				next_start = (start_from_char or 0) + truncate_at
				content_stats['truncated_at_char'] = truncate_at
				content_stats['next_start_char'] = next_start

			# Add content statistics to the result
			original_html_length = content_stats['original_html_chars']
			initial_markdown_length = content_stats['initial_markdown_chars']
			chars_filtered = content_stats['filtered_chars_removed']

			stats_summary = f"""Content processed: {original_html_length:,} HTML chars → {initial_markdown_length:,} initial markdown → {final_filtered_length:,} filtered markdown"""
			if start_from_char > 0:
				stats_summary += f' (started from char {start_from_char:,})'
			if truncated:
				stats_summary += f' → {len(content):,} final chars (truncated, use start_from_char={content_stats["next_start_char"]} to continue)'
			elif chars_filtered > 0:
				stats_summary += f' (filtered {chars_filtered:,} chars of noise)'

			system_prompt = """
You are an expert at extracting data from the markdown of a webpage.

<input>
You will be given a query and the markdown of a webpage that has been filtered to remove noise and advertising content.
</input>

<instructions>
- You are tasked to extract information from the webpage that is relevant to the query.
- You should ONLY use the information available in the webpage to answer the query. Do not make up information or provide guess from your own knowledge.
- If the information relevant to the query is not available in the page, your response should mention that.
- If the query asks for all items, products, etc., make sure to directly list all of them.
- If the content was truncated and you need more information, note that the user can use start_from_char parameter to continue from where truncation occurred.
</instructions>

<output>
- Your output should present ALL the information relevant to the query in a concise way.
- Do not answer in conversational format - directly output the relevant information or that the information is unavailable.
</output>
""".strip()

			# Sanitize surrogates from content to prevent UTF-8 encoding errors
			content = sanitize_surrogates(content)
			query = sanitize_surrogates(query)

			prompt = f'<query>\n{query}\n</query>\n\n<content_stats>\n{stats_summary}\n</content_stats>\n\n<webpage_content>\n{content}\n</webpage_content>'

			try:
				response = await asyncio.wait_for(
					page_extraction_llm.ainvoke([SystemMessage(content=system_prompt), UserMessage(content=prompt)]),
					timeout=120.0,
				)

				current_url = await browser_session.get_current_page_url()
				extracted_content = (
					f'<url>\n{current_url}\n</url>\n<query>\n{query}\n</query>\n<result>\n{response.completion}\n</result>'
				)

				# Simple memory handling
				MAX_MEMORY_LENGTH = 1000
				if len(extracted_content) < MAX_MEMORY_LENGTH:
					memory = extracted_content
					include_extracted_content_only_once = False
				else:
					file_name = await file_system.save_extracted_content(extracted_content)
					memory = f'Query: {query}\nContent in {file_name} and once in <read_state>.'
					include_extracted_content_only_once = True

				logger.info(f'📄 {memory}')
				return ActionResult(
					extracted_content=extracted_content,
					include_extracted_content_only_once=include_extracted_content_only_once,
					long_term_memory=memory,
				)
			except Exception as e:
				logger.debug(f'Error extracting content: {e}')
				raise RuntimeError(str(e))

		@self.registry.action(
			"""Scroll at specific coordinates by pixels. Provide coordinate_x, coordinate_y (position to scroll at), scroll_x (horizontal pixels, default 0), and scroll_y (vertical pixels, positive=down, negative=up). Example: scroll 500px down at position (400, 300).""",
			param_model=ScrollAction,
		)
		async def scroll(params: ScrollAction, browser_session: BrowserSession):
			try:
				# Convert coordinates from LLM size to original viewport size if resizing was used
				actual_x, actual_y = _convert_llm_coordinates_to_viewport(
					params.coordinate_x, params.coordinate_y, browser_session
				)

				# Scale scroll deltas proportionally if resizing was used
				actual_scroll_x, actual_scroll_y = _convert_llm_scroll_deltas_to_viewport(
					params.scroll_x, params.scroll_y, browser_session
				)

				# Highlight the scroll coordinate (truly non-blocking)
				asyncio.create_task(browser_session.highlight_coordinate_click(actual_x, actual_y))

				# Use CDP Input.dispatchMouseEvent with mouseWheel for scrolling
				cdp_session = await browser_session.get_or_create_cdp_session()

				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseWheel',
						'x': actual_x,
						'y': actual_y,
						'deltaX': actual_scroll_x,
						'deltaY': actual_scroll_y,
					},
					session_id=cdp_session.session_id,
				)

				# Build descriptive memory using original LLM values for consistency
				direction_parts = []
				if params.scroll_y > 0:
					direction_parts.append(f'{params.scroll_y}px down')
				elif params.scroll_y < 0:
					direction_parts.append(f'{abs(params.scroll_y)}px up')
				if params.scroll_x > 0:
					direction_parts.append(f'{params.scroll_x}px right')
				elif params.scroll_x < 0:
					direction_parts.append(f'{abs(params.scroll_x)}px left')

				direction_str = ' and '.join(direction_parts) if direction_parts else '0px'
				memory = f'Scrolled {direction_str} at coordinate ({params.coordinate_x}, {params.coordinate_y})'
				msg = f'🔍 {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to scroll: {type(e).__name__}: {e}')
				error_msg = f'Failed to execute scroll action: {str(e)}'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser_session: BrowserSession):
			# Dispatch send keys event
			try:
				event = browser_session.event_bus.dispatch(SendKeysEvent(keys=params.keys))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = f'Sent keys: {params.keys}'
				msg = f'⌨️  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to dispatch SendKeysEvent: {type(e).__name__}: {e}')
				error_msg = f'Failed to send keys: {str(e)}'
				return ActionResult(error=error_msg)

		@self.registry.action('Scroll to text.')
		async def find_text(text: str, browser_session: BrowserSession):  # type: ignore
			# Dispatch scroll to text event
			event = browser_session.event_bus.dispatch(ScrollToTextEvent(text=text))

			try:
				# The handler returns None on success or raises an exception if text not found
				await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = f'Scrolled to text: {text}'
				msg = f'🔍  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				# Text not found
				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					long_term_memory=f"Tried scrolling to text '{text}' but it was not found",
				)

		@self.registry.action(
			'Get a screenshot of the current viewport. Use when: visual inspection needed, layout unclear, element positions uncertain, debugging UI issues, or verifying page state. Screenshot is included in the next browser_state No parameters are needed.',
			param_model=NoParamsAction,
		)
		async def screenshot(_: NoParamsAction):
			"""Request that a screenshot be included in the next observation"""
			memory = 'Requested screenshot for next observation'
			msg = f'📸 {memory}'
			logger.info(msg)

			# Return flag in metadata to signal that screenshot should be included
			return ActionResult(
				extracted_content=memory,
				metadata={'include_screenshot': True},
			)

		# Dropdown Actions

		@self.registry.action(
			'Get all options from a dropdown at coordinates.',
			param_model=GetDropdownOptionsAction,
		)
		async def dropdown_options(params: GetDropdownOptionsAction, browser_session: BrowserSession):
			"""Get all options from a native dropdown or ARIA menu"""
			# Convert coordinates from LLM size to viewport size
			actual_x, actual_y = _convert_llm_coordinates_to_viewport(params.coordinate_x, params.coordinate_y, browser_session)

			# Get element at coordinates (no DOM tree needed!)
			node = await browser_session.get_dom_element_at_coordinates(actual_x, actual_y)
			if node is None:
				msg = f'No element found at coordinates ({params.coordinate_x}, {params.coordinate_y})'
				logger.warning(f'⚠️ {msg}')
				return ActionResult(extracted_content=msg)

			# Dispatch GetDropdownOptionsEvent to the event handler
			event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
			dropdown_data = await event.event_result(timeout=3.0, raise_if_none=True, raise_if_any=True)

			if not dropdown_data:
				raise ValueError('Failed to get dropdown options - no data returned')

			# Use structured memory from the handler
			return ActionResult(
				extracted_content=dropdown_data['short_term_memory'],
				long_term_memory=dropdown_data['long_term_memory'],
				include_extracted_content_only_once=True,
			)

		@self.registry.action(
			'Set the option of a dropdown element at coordinates.',
			param_model=SelectDropdownOptionAction,
		)
		async def select_dropdown(params: SelectDropdownOptionAction, browser_session: BrowserSession):
			"""Select dropdown option by the text of the option you want to select"""
			# Convert coordinates from LLM size to viewport size
			actual_x, actual_y = _convert_llm_coordinates_to_viewport(params.coordinate_x, params.coordinate_y, browser_session)

			# Get element at coordinates (no DOM tree needed!)
			node = await browser_session.get_dom_element_at_coordinates(actual_x, actual_y)
			if node is None:
				msg = f'No element found at coordinates ({params.coordinate_x}, {params.coordinate_y})'
				logger.warning(f'⚠️ {msg}')
				return ActionResult(extracted_content=msg)

			# Dispatch SelectDropdownOptionEvent to the event handler
			from browser_use.browser.events import SelectDropdownOptionEvent

			event = browser_session.event_bus.dispatch(SelectDropdownOptionEvent(node=node, text=params.text))
			selection_data = await event.event_result()

			if not selection_data:
				raise ValueError('Failed to select dropdown option - no data returned')

			# Check if the selection was successful
			if selection_data.get('success') == 'true':
				# Extract the message from the returned data
				msg = selection_data.get('message', f'Selected option: {params.text}')
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					long_term_memory=f"Selected dropdown option '{params.text}' at coordinates ({params.coordinate_x}, {params.coordinate_y})",
				)
			else:
				# Handle structured error response
				# TODO: raise BrowserError instead of returning ActionResult
				if 'short_term_memory' in selection_data and 'long_term_memory' in selection_data:
					return ActionResult(
						extracted_content=selection_data['short_term_memory'],
						long_term_memory=selection_data['long_term_memory'],
						include_extracted_content_only_once=True,
					)
				else:
					# Fallback to regular error
					error_msg = selection_data.get('error', f'Failed to select option: {params.text}')
					return ActionResult(error=error_msg)

		# File System Actions

		@self.registry.action(
			'Write content to a file in the local file system. Use this to create new files or overwrite entire file contents. For targeted edits within existing files, use replace_file instead. Supports alphanumeric filename and file extension formats: .txt, .md, .json, .jsonl, .csv, .pdf. For PDF files, write content in markdown format and it will be automatically converted to a properly formatted PDF document.'
		)
		async def write_file(
			file_name: str,
			content: str,
			file_system: FileSystem,
			append: bool = False,
			trailing_newline: bool = True,
			leading_newline: bool = False,
		):
			if trailing_newline:
				content += '\n'
			if leading_newline:
				content = '\n' + content
			if append:
				result = await file_system.append_file(file_name, content)
			else:
				result = await file_system.write_file(file_name, content)

			# Log the full path where the file is stored
			file_path = file_system.get_dir() / file_name
			logger.info(f'💾 {result} File location: {file_path}')

			return ActionResult(extracted_content=result, long_term_memory=result)

		@self.registry.action(
			'Replace specific text within a file by searching for old_str and replacing with new_str. Use this for targeted edits like updating todo checkboxes or modifying specific lines without rewriting the entire file.'
		)
		async def replace_file(file_name: str, old_str: str, new_str: str, file_system: FileSystem):
			result = await file_system.replace_file_str(file_name, old_str, new_str)
			logger.info(f'💾 {result}')
			return ActionResult(extracted_content=result, long_term_memory=result)

		@self.registry.action(
			'Read the complete content of a file. Use this to view file contents before editing or to retrieve data from files. Supports text files (txt, md, json, csv, jsonl), documents (pdf, docx), and images (jpg, png).'
		)
		async def read_file(file_name: str, available_file_paths: list[str], file_system: FileSystem):
			if available_file_paths and file_name in available_file_paths:
				structured_result = await file_system.read_file_structured(file_name, external_file=True)
			else:
				structured_result = await file_system.read_file_structured(file_name)

			result = structured_result['message']
			images = structured_result.get('images')

			MAX_MEMORY_SIZE = 1000
			# For images, create a shorter memory message
			if images:
				memory = f'Read image file {file_name}'
			elif len(result) > MAX_MEMORY_SIZE:
				lines = result.splitlines()
				display = ''
				lines_count = 0
				for line in lines:
					if len(display) + len(line) < MAX_MEMORY_SIZE:
						display += line + '\n'
						lines_count += 1
					else:
						break
				remaining_lines = len(lines) - lines_count
				memory = f'{display}{remaining_lines} more lines...' if remaining_lines > 0 else display
			else:
				memory = result
			logger.info(f'💾 {memory}')
			return ActionResult(
				extracted_content=result,
				long_term_memory=memory,
				images=images,
				include_extracted_content_only_once=True,
			)

		@self.registry.action(
			"""Execute browser JavaScript. Best practice: wrap in IIFE (function(){...})() with try-catch for safety. Use ONLY browser APIs (document, window, DOM). NO Node.js APIs (fs, require, process). Example: (function(){try{const el=document.querySelector('#id');return el?el.value:'not found'}catch(e){return 'Error: '+e.message}})() Avoid comments. Use for hover, drag, zoom, custom selectors, extract/filter links, shadow DOM, or analysing page structure. Limit output size.""",
		)
		async def evaluate(code: str, browser_session: BrowserSession):
			# Execute JavaScript with proper error handling and promise support

			cdp_session = await browser_session.get_or_create_cdp_session()

			try:
				# Validate and potentially fix JavaScript code before execution
				validated_code = self._validate_and_fix_javascript(code)

				# Always use awaitPromise=True - it's ignored for non-promises
				result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': validated_code, 'returnByValue': True, 'awaitPromise': True},
					session_id=cdp_session.session_id,
				)

				# Check for JavaScript execution errors
				if result.get('exceptionDetails'):
					exception = result['exceptionDetails']
					error_msg = f'JavaScript execution error: {exception.get("text", "Unknown error")}'

					# Enhanced error message with debugging info
					enhanced_msg = f"""JavaScript Execution Failed:
{error_msg}

Validated Code (after quote fixing):
{validated_code[:500]}{'...' if len(validated_code) > 500 else ''}
"""

					logger.debug(enhanced_msg)
					return ActionResult(error=enhanced_msg)

				# Get the result data
				result_data = result.get('result', {})

				# Check for wasThrown flag (backup error detection)
				if result_data.get('wasThrown'):
					msg = f'JavaScript code: {code} execution failed (wasThrown=true)'
					logger.debug(msg)
					return ActionResult(error=msg)

				# Get the actual value
				value = result_data.get('value')

				# Handle different value types
				if value is None:
					# Could be legitimate null/undefined result
					result_text = str(value) if 'value' in result_data else 'undefined'
				elif isinstance(value, (dict, list)):
					# Complex objects - should be serialized by returnByValue
					try:
						result_text = json.dumps(value, ensure_ascii=False)
					except (TypeError, ValueError):
						# Fallback for non-serializable objects
						result_text = str(value)
				else:
					# Primitive values (string, number, boolean)
					result_text = str(value)

				import re

				image_pattern = r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)'
				found_images = re.findall(image_pattern, result_text)

				metadata = None
				if found_images:
					# Store images in metadata so they can be added as ContentPartImageParam
					metadata = {'images': found_images}

					# Replace image data in result text with shorter placeholder
					modified_text = result_text
					for i, img_data in enumerate(found_images, 1):
						placeholder = '[Image]'
						modified_text = modified_text.replace(img_data, placeholder)
					result_text = modified_text

				# Apply length limit with better truncation (after image extraction)
				if len(result_text) > 20000:
					result_text = result_text[:19950] + '\n... [Truncated after 20000 characters]'

				# Don't log the code - it's already visible in the user's cell
				logger.debug(f'JavaScript executed successfully, result length: {len(result_text)}')

				# Memory handling: keep full result in extracted_content for current step,
				# but use truncated version in long_term_memory if too large
				MAX_MEMORY_LENGTH = 1000
				if len(result_text) < MAX_MEMORY_LENGTH:
					memory = result_text
					include_extracted_content_only_once = False
				else:
					memory = f'JavaScript executed successfully, result length: {len(result_text)} characters.'
					include_extracted_content_only_once = True

				# Return only the result, not the code (code is already in user's cell)
				return ActionResult(
					extracted_content=result_text,
					long_term_memory=memory,
					include_extracted_content_only_once=include_extracted_content_only_once,
					metadata=metadata,
				)

			except Exception as e:
				# CDP communication or other system errors
				error_msg = f'Failed to execute JavaScript: {type(e).__name__}: {e}'
				logger.debug(f'JavaScript code that failed: {code[:200]}...')
				return ActionResult(error=error_msg)

	def _validate_and_fix_javascript(self, code: str) -> str:
		"""Validate and fix common JavaScript issues before execution"""

		import re

		# Pattern 1: Fix double-escaped quotes (\\\" → \")
		fixed_code = re.sub(r'\\"', '"', code)

		# Pattern 2: Fix over-escaped regex patterns (\\\\d → \\d)
		# Common issue: regex gets double-escaped during parsing
		fixed_code = re.sub(r'\\\\([dDsSwWbBnrtfv])', r'\\\1', fixed_code)
		fixed_code = re.sub(r'\\\\([.*+?^${}()|[\]])', r'\\\1', fixed_code)

		# Pattern 3: Fix XPath expressions with mixed quotes
		xpath_pattern = r'document\.evaluate\s*\(\s*"([^"]*)"\s*,'

		def fix_xpath_quotes(match):
			xpath_with_quotes = match.group(1)
			return f'document.evaluate(`{xpath_with_quotes}`,'

		fixed_code = re.sub(xpath_pattern, fix_xpath_quotes, fixed_code)

		# Pattern 4: Fix querySelector/querySelectorAll with mixed quotes
		selector_pattern = r'(querySelector(?:All)?)\s*\(\s*"([^"]*)"\s*\)'

		def fix_selector_quotes(match):
			method_name = match.group(1)
			selector_with_quotes = match.group(2)
			return f'{method_name}(`{selector_with_quotes}`)'

		fixed_code = re.sub(selector_pattern, fix_selector_quotes, fixed_code)

		# Pattern 5: Fix closest() calls with mixed quotes
		closest_pattern = r'\.closest\s*\(\s*"([^"]*)"\s*\)'

		def fix_closest_quotes(match):
			selector_with_quotes = match.group(1)
			return f'.closest(`{selector_with_quotes}`)'

		fixed_code = re.sub(closest_pattern, fix_closest_quotes, fixed_code)

		# Pattern 6: Fix .matches() calls with mixed quotes (similar to closest)
		matches_pattern = r'\.matches\s*\(\s*"([^"]*)"\s*\)'

		def fix_matches_quotes(match):
			selector_with_quotes = match.group(1)
			return f'.matches(`{selector_with_quotes}`)'

		fixed_code = re.sub(matches_pattern, fix_matches_quotes, fixed_code)

		# Note: Removed getAttribute fix - attribute names rarely have mixed quotes
		# getAttribute typically uses simple names like "data-value", not complex selectors

		# Log changes made
		changes_made = []
		if r'\"' in code and r'\"' not in fixed_code:
			changes_made.append('fixed escaped quotes')
		if '`' in fixed_code and '`' not in code:
			changes_made.append('converted mixed quotes to template literals')

		if changes_made:
			logger.debug(f'JavaScript fixes applied: {", ".join(changes_made)}')

		return fixed_code

	def _register_done_action(self, output_model: type[T] | None, display_files_in_done_text: bool = True):
		if output_model is not None:
			self.display_files_in_done_text = display_files_in_done_text

			@self.registry.action(
				'Complete task with structured output.',
				param_model=StructuredOutputAction[output_model],
			)
			async def done(params: StructuredOutputAction):
				# Exclude success from the output JSON since it's an internal parameter
				output_dict = params.data.model_dump()

				# Enums are not serializable, convert to string
				for key, value in output_dict.items():
					if isinstance(value, enum.Enum):
						output_dict[key] = value.value

				return ActionResult(
					is_done=True,
					success=params.success,
					extracted_content=json.dumps(output_dict, ensure_ascii=False),
					long_term_memory=f'Task completed. Success Status: {params.success}',
				)

		else:

			@self.registry.action(
				'Complete task.',
				param_model=DoneAction,
			)
			async def done(params: DoneAction, file_system: FileSystem):
				user_message = params.text

				len_text = len(params.text)
				len_max_memory = 100
				memory = f'Task completed: {params.success} - {params.text[:len_max_memory]}'
				if len_text > len_max_memory:
					memory += f' - {len_text - len_max_memory} more characters'

				attachments = []
				if params.files_to_display:
					if self.display_files_in_done_text:
						file_msg = ''
						for file_name in params.files_to_display:
							file_content = file_system.display_file(file_name)
							if file_content:
								file_msg += f'\n\n{file_name}:\n{file_content}'
								attachments.append(file_name)
						if file_msg:
							user_message += '\n\nAttachments:'
							user_message += file_msg
						else:
							logger.warning('Agent wanted to display files but none were found')
					else:
						for file_name in params.files_to_display:
							file_content = file_system.display_file(file_name)
							if file_content:
								attachments.append(file_name)

				attachments = [str(file_system.get_dir() / file_name) for file_name in attachments]

				return ActionResult(
					is_done=True,
					success=params.success,
					extracted_content=user_message,
					long_term_memory=memory,
					attachments=attachments,
				)

	def use_structured_output_action(self, output_model: type[T]):
		self._register_done_action(output_model)

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

	# Act --------------------------------------------------------------------
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
	) -> ActionResult:
		"""Execute an action"""
		logger.debug(f'🔍 [ACT DEBUG] Starting act with action type: {type(action).__name__}')
		logger.debug(f'🔍 [ACT DEBUG] Action model dump: {action.model_dump(exclude_unset=True)}')

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
				logger.debug(f'🔍 [ACT DEBUG] Processing action: {action_name} with params type: {type(params).__name__}')
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
						logger.debug(f'🔍 [ACT DEBUG] Calling registry.execute_action for {action_name}...')
						result = await self.registry.execute_action(
							action_name=action_name,
							params=params,
							browser_session=browser_session,
							page_extraction_llm=page_extraction_llm,
							file_system=file_system,
							sensitive_data=sensitive_data,
							available_file_paths=available_file_paths,
						)
						logger.debug(f'🔍 [ACT DEBUG] registry.execute_action returned: {type(result).__name__}')
					except BrowserError as e:
						logger.debug(f'🔍 [ACT DEBUG] BrowserError caught in act: {type(e).__name__}: {e}')
						logger.error(f'❌ Action {action_name} failed with BrowserError: {str(e)}')
						result = handle_browser_error(e)
					except TimeoutError as e:
						logger.debug(f'🔍 [ACT DEBUG] TimeoutError caught in act: {type(e).__name__}: {e}')
						logger.error(f'❌ Action {action_name} failed with TimeoutError: {str(e)}')
						result = ActionResult(error=f'{action_name} was not executed due to timeout.')
					except Exception as e:
						# Log the original exception with traceback for observability
						logger.debug(f'🔍 [ACT DEBUG] Exception caught in act: {type(e).__name__}: {e}')
						import traceback

						logger.debug(f'🔍 [ACT DEBUG] Full traceback:\n{traceback.format_exc()}')
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
		return ActionResult()

	def __getattr__(self, name: str):
		"""
		Enable direct action calls like tools.navigate(url=..., browser_session=...).
		This provides a simpler API for tests and direct usage while maintaining backward compatibility.
		"""
		# Check if this is a registered action
		if name in self.registry.registry.actions:
			from typing import Union

			from pydantic import create_model

			action = self.registry.registry.actions[name]

			# Create a wrapper that calls act() to ensure consistent error handling and result normalization
			async def action_wrapper(**kwargs):
				# Extract browser_session (required positional argument for act())
				browser_session = kwargs.get('browser_session')

				# Separate action params from special params (injected dependencies)
				special_param_names = {
					'browser_session',
					'page_extraction_llm',
					'file_system',
					'available_file_paths',
					'sensitive_data',
				}

				# Extract action params (params for the action itself)
				action_params = {k: v for k, v in kwargs.items() if k not in special_param_names}

				# Extract special params (injected dependencies) - exclude browser_session as it's positional
				special_kwargs = {k: v for k, v in kwargs.items() if k in special_param_names and k != 'browser_session'}

				# Create the param instance
				params_instance = action.param_model(**action_params)

				# Dynamically create an ActionModel with this action
				# Use Union for type compatibility with create_model
				DynamicActionModel = create_model(
					'DynamicActionModel',
					__base__=ActionModel,
					**{name: (Union[action.param_model, None], None)},  # type: ignore
				)

				# Create the action model instance
				action_model = DynamicActionModel(**{name: params_instance})

				# Call act() which has all the error handling, result normalization, and observability
				# browser_session is passed as positional argument (required by act())
				return await self.act(action=action_model, browser_session=browser_session, **special_kwargs)  # type: ignore

			return action_wrapper

		# If not an action, raise AttributeError for normal Python behavior
		raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


# Alias for backwards compatibility
Controller = Tools
