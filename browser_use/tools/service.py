import asyncio
import enum
import json
import logging
import os
from typing import Any, Generic, TypeVar

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.events import (
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
from browser_use.observability import observe_debug
from browser_use.tools.registry.service import Registry
from browser_use.tools.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	GetDropdownOptionsAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	ScrollAction,
	SearchGoogleAction,
	SelectDropdownOptionAction,
	SendKeysAction,
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
)
from browser_use.utils import _log_pretty_url, time_execution_sync

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
		exclude_actions: list[str] = [],
		output_model: type[T] | None = None,
		display_files_in_done_text: bool = True,
	):
		self.registry = Registry[Context](exclude_actions)
		self.display_files_in_done_text = display_files_in_done_text

		"""Register all default browser actions"""

		self._register_done_action(output_model)

		# Basic Navigation Actions
		@self.registry.action(
			'Search the query in Google, the query should be a search query like humans search in Google, concrete and not vague or super long.',
			param_model=SearchGoogleAction,
		)
		async def search_google(params: SearchGoogleAction, browser_session: BrowserSession):
			search_url = f'https://www.google.com/search?q={params.query}&udm=14'

			# Check if there's already a tab open on Google or agent's about:blank
			use_new_tab = True
			try:
				tabs = await browser_session.get_tabs()
				# Get last 4 chars of browser session ID to identify agent's tabs
				browser_session_label = str(browser_session.id)[-4:]
				logger.debug(f'Checking {len(tabs)} tabs for reusable tab (browser_session_label: {browser_session_label})')

				for i, tab in enumerate(tabs):
					logger.debug(f'Tab {i}: url="{tab.url}", title="{tab.title}"')
					# Check if tab is on Google domain
					if tab.url and tab.url.strip('/').lower() in ('https://www.google.com', 'https://google.com'):
						# Found existing Google tab, navigate in it
						logger.debug(f'Found existing Google tab at index {i}: {tab.url}, reusing it')

						# Switch to this tab first if it's not the current one
						from browser_use.browser.events import SwitchTabEvent

						if browser_session.agent_focus and tab.target_id != browser_session.agent_focus.target_id:
							try:
								switch_event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=tab.target_id))
								await switch_event
								await switch_event.event_result(raise_if_none=False)
							except Exception as e:
								logger.warning(f'Failed to switch to existing Google tab: {e}, will use new tab')
								continue

						use_new_tab = False
						break
					# Check if it's an agent-owned about:blank page (has "Starting agent XXXX..." title)
					# IMPORTANT: about:blank is also used briefly for new tabs the agent is trying to open, dont take over those!
					elif tab.url == 'about:blank' and tab.title:
						# Check if this is our agent's about:blank page with DVD animation
						# The title should be "Starting agent XXXX..." where XXXX is the browser_session_label
						if browser_session_label in tab.title:
							# This is our agent's about:blank page
							logger.debug(f'Found agent-owned about:blank tab at index {i} with title: "{tab.title}", reusing it')

							# Switch to this tab first
							from browser_use.browser.events import SwitchTabEvent

							if browser_session.agent_focus and tab.target_id != browser_session.agent_focus.target_id:
								try:
									switch_event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=tab.target_id))
									await switch_event
									await switch_event.event_result()
								except Exception as e:
									logger.warning(f'Failed to switch to agent-owned tab: {e}, will use new tab')
									continue

							use_new_tab = False
							break
			except Exception as e:
				logger.debug(f'Could not check for existing tabs: {e}, using new tab')

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
				memory = f"Searched Google for '{params.query}'"
				msg = f'🔍  {memory}'
				logger.info(msg)
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to search Google: {e}')
				return ActionResult(error=f'Failed to search Google for "{params.query}": {str(e)}')

		@self.registry.action(
			'Navigate to URL, set new_tab=True to open in new tab, False to navigate in current tab', param_model=GoToUrlAction
		)
		async def go_to_url(params: GoToUrlAction, browser_session: BrowserSession):
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

		@self.registry.action(
			'Wait for x seconds (default 3) (max 30 seconds). This can be used to wait until the page is fully loaded.'
		)
		async def wait(seconds: int = 3):
			# Cap wait time at maximum 30 seconds
			# Reduce the wait time by 3 seconds to account for the llm call which takes at least 3 seconds
			# So if the model decides to wait for 5 seconds, the llm call took at least 3 seconds, so we only need to wait for 2 seconds
			# Note by Mert: the above doesnt make sense because we do the LLM call right after this or this could be followed by another action after which we would like to wait
			# so I revert this.
			actual_seconds = min(max(seconds - 3, 0), 30)
			memory = f'Waited for {seconds} seconds'
			logger.info(f'🕒 waited for {actual_seconds} seconds + 3 seconds for LLM call')
			await asyncio.sleep(actual_seconds)
			return ActionResult(extracted_content=memory, long_term_memory=memory)

		# Element Interaction Actions

		@self.registry.action(
			'Click element by index. Only indices from your browser_state are allowed. Never use an index that is not inside your current browser_state. Set while_holding_ctrl=True to open any resulting navigation in a new tab.',
			param_model=ClickElementAction,
		)
		async def click_element_by_index(params: ClickElementAction, browser_session: BrowserSession):
			# Dispatch click event with node
			try:
				assert params.index != 0, (
					'Cannot click on element with index 0. If there are no interactive elements use scroll(), wait(), refresh(), etc. to troubleshoot'
				)

				# Look up the node from the selector map
				node = await browser_session.get_element_by_index(params.index)
				if node is None:
					raise ValueError(f'Element index {params.index} not found in browser state')

				event = browser_session.event_bus.dispatch(
					ClickElementEvent(node=node, while_holding_ctrl=params.while_holding_ctrl or False)
				)
				await event
				# Wait for handler to complete and get any exception or metadata
				click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = 'Clicked element'

				if params.while_holding_ctrl:
					memory += ' and opened in new tab'

				# Check if a new tab was opened (from watchdog metadata)
				elif isinstance(click_metadata, dict) and click_metadata.get('new_tab_opened'):
					memory += ' - which opened a new tab'

				msg = f'🖱️ {memory}'
				logger.info(msg)

				# Include click coordinates in metadata if available
				return ActionResult(
					extracted_content=memory,
					metadata=click_metadata if isinstance(click_metadata, dict) else None,
				)
			except BrowserError as e:
				if 'Cannot click on <select> elements.' in str(e):
					try:
						return await get_dropdown_options(
							params=GetDropdownOptionsAction(index=params.index), browser_session=browser_session
						)
					except Exception as dropdown_error:
						logger.error(
							f'Failed to get dropdown options as shortcut during click_element_by_index on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
						)
					return ActionResult(error='Can not click on select elements.')

				return handle_browser_error(e)
			except Exception as e:
				error_msg = f'Failed to click element {params.index}: {str(e)}'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'Input text into an input interactive element. Only input text into indices that are inside your current browser_state. Never input text into indices that are not inside your current browser_state.',
			param_model=InputTextAction,
		)
		async def input_text(
			params: InputTextAction,
			browser_session: BrowserSession,
			has_sensitive_data: bool = False,
			sensitive_data: dict[str, str | dict[str, str]] | None = None,
		):
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				raise ValueError(f'Element index {params.index} not found in browser state')

			# Dispatch type text event with node
			try:
				# Detect which sensitive key is being used
				sensitive_key_name = None
				if has_sensitive_data and sensitive_data:
					sensitive_key_name = _detect_sensitive_key_name(params.text, sensitive_data)

				event = browser_session.event_bus.dispatch(
					TypeTextEvent(
						node=node,
						text=params.text,
						clear_existing=params.clear_existing,
						is_sensitive=has_sensitive_data,
						sensitive_key_name=sensitive_key_name,
					)
				)
				await event
				input_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)

				# Create message with sensitive data handling
				if has_sensitive_data:
					if sensitive_key_name:
						msg = f'Input {sensitive_key_name} into element {params.index}.'
						log_msg = f'Input <{sensitive_key_name}> into element {params.index}.'
					else:
						msg = f'Input sensitive data into element {params.index}.'
						log_msg = f'Input <sensitive> into element {params.index}.'
				else:
					msg = f"Input '{params.text}' into element {params.index}."
					log_msg = msg

				logger.debug(log_msg)

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
				logger.error(f'Failed to dispatch TypeTextEvent: {type(e).__name__}: {e}')
				error_msg = f'Failed to input text into element {params.index}: {e}'
				return ActionResult(error=error_msg)

		@self.registry.action('Upload file to interactive element with file path', param_model=UploadFileAction)
		async def upload_file_to_element(
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
							params = UploadFileAction(index=params.index, path=file_system_path)
						else:
							# If browser is remote, allow passing a remote-accessible absolute path
							if not browser_session.is_local:
								pass
							else:
								msg = f'File path {params.path} is not available. Upload files must be in available_file_paths, downloaded_files, or a file managed by file_system.'
								logger.error(f'❌ {msg}')
								return ActionResult(error=msg)
					else:
						# If browser is remote, allow passing a remote-accessible absolute path
						if not browser_session.is_local:
							pass
						else:
							msg = f'File path {params.path} is not available. Upload files must be in available_file_paths, downloaded_files, or a file managed by file_system.'
							raise BrowserError(message=msg, long_term_memory=msg)

			# For local browsers, ensure the file exists on the local filesystem
			if browser_session.is_local:
				if not os.path.exists(params.path):
					msg = f'File {params.path} does not exist'
					return ActionResult(error=msg)

			# Get the selector map to find the node
			selector_map = await browser_session.get_selector_map()
			if params.index not in selector_map:
				msg = f'Element with index {params.index} does not exist.'
				return ActionResult(error=msg)

			node = selector_map[params.index]

			# Helper function to find file input near the selected element
			def find_file_input_near_element(
				node: EnhancedDOMTreeNode, max_height: int = 3, max_descendant_depth: int = 3
			) -> EnhancedDOMTreeNode | None:
				"""Find the closest file input to the selected element."""

				def find_file_input_in_descendants(n: EnhancedDOMTreeNode, depth: int) -> EnhancedDOMTreeNode | None:
					if depth < 0:
						return None
					if browser_session.is_file_input(n):
						return n
					for child in n.children_nodes or []:
						result = find_file_input_in_descendants(child, depth - 1)
						if result:
							return result
					return None

				current = node
				for _ in range(max_height + 1):
					# Check the current node itself
					if browser_session.is_file_input(current):
						return current
					# Check all descendants of the current node
					result = find_file_input_in_descendants(current, max_descendant_depth)
					if result:
						return result
					# Check all siblings and their descendants
					if current.parent_node:
						for sibling in current.parent_node.children_nodes or []:
							if sibling is current:
								continue
							if browser_session.is_file_input(sibling):
								return sibling
							result = find_file_input_in_descendants(sibling, max_descendant_depth)
							if result:
								return result
					current = current.parent_node
					if not current:
						break
				return None

			# Try to find a file input element near the selected element
			file_input_node = find_file_input_near_element(node)

			# If not found near the selected element, fallback to finding the closest file input to current scroll position
			if file_input_node is None:
				logger.info(
					f'No file upload element found near index {params.index}, searching for closest file input to scroll position'
				)

				# Get current scroll position
				cdp_session = await browser_session.get_or_create_cdp_session()
				try:
					scroll_info = await cdp_session.cdp_client.send.Runtime.evaluate(
						params={'expression': 'window.scrollY || window.pageYOffset || 0'}, session_id=cdp_session.session_id
					)
					current_scroll_y = scroll_info.get('result', {}).get('value', 0)
				except Exception:
					current_scroll_y = 0

				# Find all file inputs in the selector map and pick the closest one to scroll position
				closest_file_input = None
				min_distance = float('inf')

				for idx, element in selector_map.items():
					if browser_session.is_file_input(element):
						# Get element's Y position
						if element.absolute_position:
							element_y = element.absolute_position.y
							distance = abs(element_y - current_scroll_y)
							if distance < min_distance:
								min_distance = distance
								closest_file_input = element

				if closest_file_input:
					file_input_node = closest_file_input
					logger.info(f'Found file input closest to scroll position (distance: {min_distance}px)')
				else:
					msg = 'No file upload element found on the page'
					logger.error(msg)
					raise BrowserError(msg)
					# TODO: figure out why this fails sometimes + add fallback hail mary, just look for any file input on page

			# Dispatch upload file event with the file input node
			try:
				event = browser_session.event_bus.dispatch(UploadFileEvent(node=file_input_node, file_path=params.path))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				msg = f'Successfully uploaded file to index {params.index}'
				logger.info(f'📁 {msg}')
				return ActionResult(
					extracted_content=msg,
					long_term_memory=f'Uploaded file {params.path} to element {params.index}',
				)
			except Exception as e:
				logger.error(f'Failed to upload file: {e}')
				raise BrowserError(f'Failed to upload file: {e}')

		# Tab Management Actions

		@self.registry.action('Switch tab', param_model=SwitchTabAction)
		async def switch_tab(params: SwitchTabAction, browser_session: BrowserSession):
			# Dispatch switch tab event
			try:
				target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)

				event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
				await event
				new_target_id = await event.event_result(raise_if_any=True, raise_if_none=False)
				assert new_target_id, 'SwitchTabEvent did not return a TargetID for the new tab that was switched to'
				memory = f'Switched to Tab with ID {new_target_id[-4:]}'
				logger.info(f'🔄  {memory}')
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to switch tab: {type(e).__name__}: {e}')
				return ActionResult(error=f'Failed to switch to tab {params.tab_id}.')

		@self.registry.action('Close an existing tab', param_model=CloseTabAction)
		async def close_tab(params: CloseTabAction, browser_session: BrowserSession):
			# Dispatch close tab event
			try:
				target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)
				cdp_session = await browser_session.get_or_create_cdp_session()
				target_info = await cdp_session.cdp_client.send.Target.getTargetInfo(
					params={'targetId': target_id}, session_id=cdp_session.session_id
				)
				tab_url = target_info['targetInfo']['url']
				event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=target_id))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = f'Closed tab # {params.tab_id} ({_log_pretty_url(tab_url)})'
				logger.info(f'🗑️  {memory}')
				return ActionResult(
					extracted_content=memory,
					long_term_memory=memory,
				)
			except Exception as e:
				logger.error(f'Failed to close tab: {e}')
				return ActionResult(error=f'Failed to close tab {params.tab_id}.')

		@self.registry.action(
			"""Scroll the page by specified number of pages (set down=True to scroll down, down=False to scroll up, num_pages=number of pages to scroll like 0.5 for half page, 10.0 for ten pages, etc.). 
			Default behavior is to scroll the entire page. This is enough for most cases.
			Optional if there are multiple scroll containers, use frame_element_index parameter with an element inside the container you want to scroll in. For that you must use indices that exist in your browser_state (works well for dropdowns and custom UI components). 
			Instead of scrolling step after step, use a high number of pages at once like 10 to get to the bottom of the page.
			If you know where you want to scroll to, use scroll_to_text instead of this tool.
			""",
			param_model=ScrollAction,
		)
		async def scroll(params: ScrollAction, browser_session: BrowserSession):
			try:
				# Look up the node from the selector map if index is provided
				# Special case: index 0 means scroll the whole page (root/body element)
				node = None
				if params.frame_element_index is not None and params.frame_element_index != 0:
					node = await browser_session.get_element_by_index(params.frame_element_index)
					if node is None:
						# Element does not exist
						msg = f'Element index {params.frame_element_index} not found in browser state'
						return ActionResult(error=msg)

				# Dispatch scroll event with node - the complex logic is handled in the event handler
				# Convert pages to pixels (assuming 1000px per page as standard viewport height)
				pixels = int(params.num_pages * 1000)
				event = browser_session.event_bus.dispatch(
					ScrollEvent(direction='down' if params.down else 'up', amount=pixels, node=node)
				)
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				direction = 'down' if params.down else 'up'

				# If index is 0 or None, we're scrolling the page
				target = (
					'the page'
					if params.frame_element_index is None or params.frame_element_index == 0
					else f'element {params.frame_element_index}'
				)

				if params.num_pages == 1.0:
					long_term_memory = f'Scrolled {direction} {target} by one page'
				else:
					long_term_memory = f'Scrolled {direction} {target} by {params.num_pages} pages'

				msg = f'🔍 {long_term_memory}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, long_term_memory=long_term_memory)
			except Exception as e:
				logger.error(f'Failed to dispatch ScrollEvent: {type(e).__name__}: {e}')
				error_msg = 'Failed to execute scroll action.'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'Send strings of special keys to use e.g. Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`',
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

		@self.registry.action(
			description='Scroll to a text in the current page. This helps you to be efficient. Prefer this tool over scrolling step by step.',
		)
		async def scroll_to_text(text: str, browser_session: BrowserSession):  # type: ignore
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

		# Dropdown Actions

		@self.registry.action(
			'Get list of values for a dropdown input field. Only works on dropdown-style form elements (<select>, Semantic UI/aria-labeled select, etc.). Do not use this tool for none dropdown elements.',
			param_model=GetDropdownOptionsAction,
		)
		async def get_dropdown_options(params: GetDropdownOptionsAction, browser_session: BrowserSession):
			"""Get all options from a native dropdown or ARIA menu"""
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				raise ValueError(f'Element index {params.index} not found in browser state')

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
			'Select dropdown option by exact text from any dropdown type (native <select>, ARIA menus, or custom dropdowns). Searches target element and children to find selectable options.',
			param_model=SelectDropdownOptionAction,
		)
		async def select_dropdown_option(params: SelectDropdownOptionAction, browser_session: BrowserSession):
			"""Select dropdown option by the text of the option you want to select"""
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				raise ValueError(f'Element index {params.index} not found in browser state')

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
					long_term_memory=f"Selected dropdown option '{params.text}' at index {params.index}",
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
			'Write or append content to file_name in file system. Allowed extensions are .md, .txt, .json, .csv, .pdf. For .pdf files, write the content in markdown format and it will automatically be converted to a properly formatted PDF document.'
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
			logger.info(f'💾 {result}')
			return ActionResult(extracted_content=result, long_term_memory=result)

		@self.registry.action(
			'Replace old_str with new_str in file_name. old_str must exactly match the string to replace in original text. Recommended tool to mark completed items in todo.md or change specific contents in a file.'
		)
		async def replace_file_str(file_name: str, old_str: str, new_str: str, file_system: FileSystem):
			result = await file_system.replace_file_str(file_name, old_str, new_str)
			logger.info(f'💾 {result}')
			return ActionResult(extracted_content=result, long_term_memory=result)

		@self.registry.action('Read file_name from file system')
		async def read_file(file_name: str, available_file_paths: list[str], file_system: FileSystem):
			if available_file_paths and file_name in available_file_paths:
				result = await file_system.read_file(file_name, external_file=True)
			else:
				result = await file_system.read_file(file_name)

			MAX_MEMORY_SIZE = 1000
			if len(result) > MAX_MEMORY_SIZE:
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
				include_extracted_content_only_once=True,
			)

		@self.registry.action(
			"""This JavaScript code gets executed with Runtime.evaluate and 'returnByValue': True, 'awaitPromise': True

SYNTAX RULES - FAILURE TO FOLLOW CAUSES "Uncaught at line 0" ERRORS:
- ALWAYS wrap your code in IIFE: (function(){ ... })() or (async function(){ ... })() for async code
- ALWAYS add try-catch blocks to prevent execution errors
- ALWAYS use proper semicolons and valid JavaScript syntax
- NEVER write multiline code without proper IIFE wrapping
- NEVER use inline comments (//) - they cause parsing errors in single-line execution
- ALWAYS validate elements exist before accessing them

INDEXED ELEMENT ACCESS:
You have access to getElement(index) and getElements([indices]) functions that map browser_state 
indices to actual DOM elements using reliable selectors.

EXTRACTION STRATEGY - USE IN THIS ORDER:
1. Try getElement(index) for interactive elements visible in browser_state
2. If getElement returns null, use semantic selectors for non-interactive content  
3. If JavaScript extraction fails 2+ times, read browser_state text directly
4. NEVER repeat the same failing selector more than twice

// ✅ CORRECT: Access elements by their browser_state index
const signInButton = getElement(7);  // Gets [7] from browser_state
if (signInButton) {
  return signInButton.textContent.trim();
}

// ✅ CORRECT: Get multiple elements efficiently with validation
const indices = [6, 7, 11, 13];
const elements = getElements(indices);
return elements.map((el, i) => ({
  index: indices[i],
  text: el.textContent.trim(),
  tag: el.tagName.toLowerCase()
}));

// ✅ CORRECT: Check element exists before extraction
const available = getAvailableIndices();
const validElements = getElements(available.slice(0, 5));
return validElements.map(el => el.textContent.trim());

// ✅ CORRECT: Get full element info including coordinates, attributes, visibility, etc.
const elementInfo = getElementInfo(7);
return elementInfo; // Returns complete node.__json__(): coordinates, attributes, visibility, scrollable, etc.

// ✅ CORRECT: Fallback to semantic selectors if getElement fails
const element = getElement(6);
if (element) {
  return element.textContent.trim();
} else {
  // Fallback for non-interactive content
  const articles = document.querySelectorAll('article h1, .headline, [data-testid*="title"]');
  return Array.from(articles).slice(0, 3).map(el => el.textContent.trim());
}

// ✅ CORRECT: Extract non-interactive elements with semantic selectors
const articles = document.querySelectorAll('article, .article, [data-testid*="post"]');
return Array.from(articles).slice(0, 3).map(el => el.textContent.trim());

// ✅ CORRECT: Click on element by index (alternative to click_element_by_index tool)
const element = getElement(7);
if (element) {
  element.click();
  return 'Clicked element';
} else {
  return 'Element not found';
}

EXAMPLES:
Use this tool when other tools do not work on the first try as expected or when a more general tool is needed, e.g. for filling a form all at once, hovering, dragging, extracting only links, extracting content from the page, press and hold, hovering, clicking on coordinates, zooming, use this if the user provides custom selectors which you can otherwise not interact with ....
You can also use it to explore the website.
- Write code to solve problems you could not solve with other tools.
- Don't write inline comments (//) - they cause execution errors.
- Write only valid js code.
- use this to e.g. extract + filter links, convert the page to json into the format you need etc...

- limit the output otherwise your context will explode
- think if you deal with special elements like iframes / shadow roots etc
- Adopt your strategy for React Native Web, React, Angular, Vue, MUI pages etc.
- e.g. with  synthetic events, keyboard simulation, shadow DOM, etc.

PROPER SYNTAX EXAMPLES:
CORRECT: (function(){ try { const el = getElement(7); return el ? el.value : 'not found'; } catch(e) { return 'Error: ' + e.message; } })()
CORRECT: (async function(){ try { await new Promise(r => setTimeout(r, 100)); return 'done'; } catch(e) { return 'Error: ' + e.message; } })()

CRITICAL STOP CONDITIONS - WHEN TO ABANDON JAVASCRIPT:
- If getElement(index) returns null 2+ times → Read browser_state text directly
- If extraction returns empty arrays 3+ times → Switch to manual reading
- If you're repeating similar selectors → Stop and use different approach
- If over 5 failed attempts → The data is visible in browser_state, read it manually

// ✅ CORRECT: Stop trying JavaScript if it fails repeatedly
let attempts = 0;
const maxAttempts = 2;
while (attempts < maxAttempts) {
  const element = getElement(7);
  if (element && element.textContent.trim()) {
    return element.textContent.trim();
  }
  attempts++;
}
// After failures, advise: "Read browser_state directly - text is visible there"
return 'JavaScript failed - read browser_state text manually';

// ✅ CORRECT: Use semantic selectors for non-interactive content
const articles = document.querySelectorAll('article h1, .headline, [data-testid*="title"]');
return Array.from(articles).slice(0, 3).map(el => el.textContent.trim());

WRONG: const el = document.querySelector('#id'); el ? el.value : '';
WRONG: document.querySelector('#id').value  
WRONG: Repeating the same failing selector 10+ times
WRONG: (function(){ // This comment causes parsing errors

SHADOW DOM ACCESS EXAMPLE:
(function(){
    try {
        const hosts = document.querySelectorAll('*');
        for (let host of hosts) {
            if (host.shadowRoot) {
                const el = host.shadowRoot.querySelector('#target');
                if (el) return el.textContent;
            }
        }
        return 'Not found';
    } catch(e) {
        return 'Error: ' + e.message;
    }
})()

WHEN JAVASCRIPT FAILS - READ BROWSER_STATE DIRECTLY:
If your JavaScript extraction returns empty/null repeatedly, the data is visible in browser_state.
Stop trying JavaScript and advise: "Data visible in browser_state - read it manually"

Example browser_state content you can read directly:
[61]<a />
  Climate change demands more blood (April 18th 2025, 10:31:46 pm)
[65]<a />  
  Are cyclones worsening with climate change? (April 12th 2025, 9:31:11 pm)

When you see this, immediately tell the agent to read these titles and dates directly.

## Return values:
- Async functions (with await, promises, timeouts) are automatically handled
- Returns strings, numbers, booleans, and serialized objects/arrays
- Use JSON.stringify() for complex objects: JSON.stringify(Array.from(document.querySelectorAll('a')).map(el => el.textContent.trim()))

""",
		)
		async def execute_js(code: str, browser_session: BrowserSession):
			# Execute JavaScript with proper error handling and promise support

			cdp_session = await browser_session.get_or_create_cdp_session()

			try:
				# Get the selector map from browser session
				selector_map_data = {}
				element_info_data = {}
				try:
					selector_map = await browser_session.get_selector_map()
					for index, node in selector_map.items():
						# Generate specific CSS selector for getElement()
						css_selector = node.tag_name

						# Build specific selector to target exact element
						if 'id' in node.attributes and node.attributes['id']:
							css_selector += f'#{node.attributes["id"]}'
						else:
							# Use multiple attributes to make selector more specific
							if 'class' in node.attributes and node.attributes['class']:
								css_selector += f'.{node.attributes["class"].split()[0]}'

							# Add additional specificity with common attributes
							for attr in ['role', 'type', 'href', 'aria-label']:
								if attr in node.attributes and node.attributes[attr]:
									css_selector += f'[{attr}="{node.attributes[attr]}"]'
									break

							# As last resort, use xpath-style nth-child selector
							if node.element_index is not None:
								css_selector += f':nth-of-type({node.element_index + 1})'

						selector_map_data[str(index)] = css_selector
						# Store full node info for getElementInfo()
						element_info_data[str(index)] = node
				except Exception as e:
					logger.debug(f'Could not get selector map: {e}')
					selector_map_data = {}
					element_info_data = {}

				# Store element info for getElementInfo() - use the node's __json__ method
				element_info_json = {}
				for index, node in element_info_data.items():
					try:
						# Use the node's built-in serialization method
						element_info_json[index] = node.__json__()
					except Exception as e:
						logger.debug(f'Could not serialize node info for index {index}: {e}')
						element_info_json[index] = {'error': f'Could not serialize: {e}'}

				# Inject helper functions and maps into the execution context
				helper_code = f"""
				// Inject simple selector map and full element info
				window.__ELEMENT_MAP__ = {json.dumps(selector_map_data)};
				window.__ELEMENT_INFO__ = {json.dumps(element_info_json)};
				
				// Helper function to get element by index
				function getElement(index) {{
					try {{
						const selectorMap = window.__ELEMENT_MAP__ || {{}};
						const elementData = selectorMap[String(index)];
						
						if (!elementData) {{
							return null;
						}}
						
						const element = document.querySelector(elementData);
						if (!element) {{
							console.warn('Element not found for selector: ' + elementData);
							return null;
						}}
						
						return element;
					}} catch(e) {{
						console.error('Error getting element ' + index + ':', e.message);
						return null;
					}}
				}}
				
				// Helper function to get multiple elements
				function getElements(indices) {{
					if (!Array.isArray(indices)) {{
						console.error('getElements expects an array of indices');
						return [];
					}}
					return indices.map(i => getElement(i)).filter(Boolean);
				}}
				
				// Helper function to get full element info including coordinates, attributes, etc.
				function getElementInfo(index) {{
					try {{
						const elementInfo = window.__ELEMENT_INFO__ || {{}};
						const info = elementInfo[String(index)];
						
						if (!info) {{
							return {{ error: 'No data found for index ' + index }};
						}}
						
						return {{ index: index, ...info }};
					}} catch(e) {{
						return {{ error: 'Error getting element info: ' + e.message }};
					}}
				}}
				
				// Helper function to get all available element indices
				function getAvailableIndices() {{
					const selectorMap = window.__ELEMENT_MAP__ || {{}};
					return Object.keys(selectorMap).map(k => parseInt(k)).sort((a, b) => a - b);
				}}
				"""

				# Execute helper code first
				await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': helper_code, 'returnByValue': False},
					session_id=cdp_session.session_id,
				)

				# Now execute the user's code
				# Always use awaitPromise=True - it's ignored for non-promises
				result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': code, 'returnByValue': True, 'awaitPromise': True},
					session_id=cdp_session.session_id,
				)

				# Check for JavaScript execution errors
				if result.get('exceptionDetails'):
					exception = result['exceptionDetails']
					error_msg = f'JavaScript execution error: {exception.get("text", "Unknown error")}'
					if 'lineNumber' in exception:
						error_msg += f' at line {exception["lineNumber"]}'
					msg = f'Code: {code}\n\nError: {error_msg}'
					logger.info(msg)
					return ActionResult(error=msg)

				# Get the result data
				result_data = result.get('result', {})

				# Check for wasThrown flag (backup error detection)
				if result_data.get('wasThrown'):
					msg = f'Code: {code}\n\nError: JavaScript execution failed (wasThrown=true)'
					logger.info(msg)
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

				# Apply length limit with better truncation
				if len(result_text) > 20000:
					result_text = result_text[:19950] + '\n... [Truncated after 20000 characters]'
				msg = f'Code: {code}\n\nResult: {result_text}'
				logger.info(msg)
				return ActionResult(extracted_content=f'Code: {code}\n\nResult: {result_text}')

			except Exception as e:
				# CDP communication or other system errors
				error_msg = f'Code: {code}\n\nError: Failed to execute JavaScript: {type(e).__name__}: {e}'
				logger.info(error_msg)
				return ActionResult(error=error_msg)

	# Custom done action for structured output
	@observe_debug(ignore_input=True, ignore_output=True, name='extract_clean_markdown')
	async def extract_clean_markdown(
		self, browser_session: BrowserSession, extract_links: bool = False
	) -> tuple[str, dict[str, Any]]:
		"""Extract clean markdown from the current page.

		Args:
			browser_session: Browser session to extract content from
			extract_links: Whether to preserve links in markdown

		Returns:
			tuple: (clean_markdown_content, content_statistics)
		"""
		import re

		# Get HTML content from current page
		cdp_session = await browser_session.get_or_create_cdp_session()
		try:
			body_id = await cdp_session.cdp_client.send.DOM.getDocument(session_id=cdp_session.session_id)
			page_html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
				params={'backendNodeId': body_id['root']['backendNodeId']}, session_id=cdp_session.session_id
			)
			page_html = page_html_result['outerHTML']
			current_url = await browser_session.get_current_page_url()
		except Exception as e:
			raise RuntimeError(f"Couldn't extract page content: {e}")

		original_html_length = len(page_html)

		# Use html2text for clean markdown conversion
		import html2text

		h = html2text.HTML2Text()
		h.ignore_links = not extract_links
		h.ignore_images = True
		h.ignore_emphasis = False
		h.body_width = 0  # Don't wrap lines
		h.unicode_snob = True
		h.skip_internal_links = True
		content = h.handle(page_html)

		initial_markdown_length = len(content)

		# Minimal cleanup - html2text already does most of the work
		content = re.sub(r'%[0-9A-Fa-f]{2}', '', content)  # Remove any remaining URL encoding

		# Apply light preprocessing to clean up excessive whitespace
		content, chars_filtered = self._preprocess_markdown_content(content)

		final_filtered_length = len(content)

		# Content statistics
		stats = {
			'url': current_url,
			'original_html_chars': original_html_length,
			'initial_markdown_chars': initial_markdown_length,
			'filtered_chars_removed': chars_filtered,
			'final_filtered_chars': final_filtered_length,
		}

		return content, stats

	def _preprocess_markdown_content(self, content: str, max_newlines: int = 3) -> tuple[str, int]:
		"""
		Light preprocessing of html2text output - minimal cleanup since html2text is already clean.

		Args:
			content: Markdown content from html2text to lightly filter
			max_newlines: Maximum consecutive newlines to allow

		Returns:
			tuple: (filtered_content, chars_filtered)
		"""
		import re

		original_length = len(content)

		# Compress consecutive newlines (4+ newlines become max_newlines)
		content = re.sub(r'\n{4,}', '\n' * max_newlines, content)

		# Remove lines that are only whitespace or very short (likely artifacts)
		lines = content.split('\n')
		filtered_lines = []
		for line in lines:
			stripped = line.strip()
			# Keep lines with substantial content (html2text output is already clean)
			if len(stripped) > 2:
				filtered_lines.append(line)

		content = '\n'.join(filtered_lines)
		content = content.strip()

		chars_filtered = original_length - len(content)
		return content, chars_filtered

	def _register_done_action(self, output_model: type[T] | None, display_files_in_done_text: bool = True):
		if output_model is not None:
			self.display_files_in_done_text = display_files_in_done_text

			@self.registry.action(
				'Complete task - with return text and if the task is finished (success=True) or not yet completely finished (success=False), because last step is reached',
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
				'Complete task - provide a summary of results for the user. Set success=True if task completed successfully, false otherwise. Text should be your response to the user summarizing results. Include files you would like to display to the user in files_to_display.',
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
							if file_name == 'todo.md':
								continue
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
							if file_name == 'todo.md':
								continue
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

	# Act --------------------------------------------------------------------
	@observe_debug(ignore_input=True, ignore_output=True, name='act')
	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_session: BrowserSession,
		#
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
	) -> ActionResult:
		"""Execute an action"""

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
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
						result = await self.registry.execute_action(
							action_name=action_name,
							params=params,
							browser_session=browser_session,
							page_extraction_llm=page_extraction_llm,
							file_system=file_system,
							sensitive_data=sensitive_data,
							available_file_paths=available_file_paths,
						)
					except BrowserError as e:
						logger.error(f'❌ Action {action_name} failed with BrowserError: {str(e)}')
						result = handle_browser_error(e)
					except TimeoutError as e:
						logger.error(f'❌ Action {action_name} failed with TimeoutError: {str(e)}')
						result = ActionResult(error=f'{action_name} was not executed due to timeout.')
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
		return ActionResult()


# Alias for backwards compatibility
Controller = Tools
