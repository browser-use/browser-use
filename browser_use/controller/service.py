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
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
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
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.observability import observe_debug
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


def extract_llm_error_message(error: Exception) -> str:
	"""
	Extract the clean error message from an exception that may contain <llm_error_msg> tags.

	If the tags are found, returns the content between them.
	Otherwise, returns the original error string.
	"""
	import re

	error_str = str(error)

	# Look for content between <llm_error_msg> tags
	pattern = r'<llm_error_msg>(.*?)</llm_error_msg>'
	match = re.search(pattern, error_str, re.DOTALL)

	if match:
		return match.group(1).strip()

	# Fallback: return the original error string
	return error_str


class Controller(Generic[Context]):
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
				return ActionResult(extracted_content=memory, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to search Google: {e}')
				clean_msg = extract_llm_error_message(e)
				return ActionResult(error=f'Failed to search Google for "{params.query}": {clean_msg}')

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
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				error_msg = str(e)
				# Always log the actual error first for debugging
				browser_session.logger.error(f'❌ Navigation failed: {error_msg}')
				clean_msg = extract_llm_error_message(e)

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
					site_unavailable_msg = f'Site unavailable: {params.url} - {error_msg}'
					browser_session.logger.warning(f'⚠️ {site_unavailable_msg}')
					return ActionResult(error=site_unavailable_msg)
				else:
					# Return error in ActionResult instead of re-raising
					return ActionResult(error=f'Navigation failed: {clean_msg}')

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
				clean_msg = extract_llm_error_message(e)
				error_msg = f'Failed to go back: {clean_msg}'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'Wait for x seconds default 3 (max 10 seconds). This can be used to wait until the page is fully loaded.'
		)
		async def wait(seconds: int = 3):
			# Cap wait time at maximum 10 seconds
			# Reduce the wait time by 3 seconds to account for the llm call which takes at least 3 seconds
			# So if the model decides to wait for 5 seconds, the llm call took at least 3 seconds, so we only need to wait for 2 seconds
			# Note by Mert: the above doesnt make sense because we do the LLM call right after this or this could be followed by another action after which we would like to wait
			# so I revert this.
			actual_seconds = min(max(seconds, 0), 10)
			memory = f'Waited for {actual_seconds} seconds'
			logger.info(f'🕒 {memory}')
			await asyncio.sleep(actual_seconds)
			return ActionResult(extracted_content=memory, long_term_memory=memory)

		# Element Interaction Actions

		@self.registry.action(
			'Click element by index, set while_holding_ctrl=True to open any resulting navigation in a new tab. Only click on indices that are inside your current browser_state. Never click or assume not existing indices.',
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
					raise ValueError(f'Element index {params.index} not found in DOM')

				event = browser_session.event_bus.dispatch(
					ClickElementEvent(node=node, while_holding_ctrl=params.while_holding_ctrl)
				)
				await event
				# Wait for handler to complete and get any exception or metadata
				click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
				memory = f'Clicked element with index {params.index}'
				msg = f'🖱️ {memory}'
				logger.info(msg)

				# Include click coordinates in metadata if available
				return ActionResult(
					extracted_content=memory,
					include_in_memory=True,
					long_term_memory=memory,
					metadata=click_metadata if isinstance(click_metadata, dict) else None,
				)
			except Exception as e:
				logger.error(f'Failed to execute ClickElementEvent: {type(e).__name__}: {e}')
				clean_msg = extract_llm_error_message(e)
				error_msg = f'Failed to click element {params.index}: {clean_msg}'

				# If it's a select dropdown error, automatically get the dropdown options
				if 'dropdown' in str(e) and node:
					try:
						return await get_dropdown_options(
							params=GetDropdownOptionsAction(index=params.index), browser_session=browser_session
						)
					except Exception as dropdown_error:
						logger.error(
							f'Failed to get dropdown options as shortcut during click_element_by_index on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
						)

				return ActionResult(error=error_msg)

		@self.registry.action(
			'Click and input text into a input interactive element. Only input text into indices that are inside your current browser_state. Never input text into indices that are not inside your current browser_state.',
			param_model=InputTextAction,
		)
		async def input_text(params: InputTextAction, browser_session: BrowserSession, has_sensitive_data: bool = False):
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				raise ValueError(f'Element index {params.index} not found in DOM')

			# Dispatch type text event with node
			try:
				event = browser_session.event_bus.dispatch(
					TypeTextEvent(node=node, text=params.text, clear_existing=params.clear_existing)
				)
				await event
				input_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
				msg = f"Input '{params.text}' into element {params.index}."
				logger.info(msg)

				# Include input coordinates in metadata if available
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					long_term_memory=f"Input '{params.text}' into element {params.index}.",
					metadata=input_metadata if isinstance(input_metadata, dict) else None,
				)
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
							raise BrowserError(
								f'File path {params.path} is not available. Must be in available_file_paths, downloaded_files, or a file managed by file_system.'
							)
					else:
						raise BrowserError(
							f'File path {params.path} is not available. Must be in available_file_paths or downloaded_files.'
						)

			if not os.path.exists(params.path):
				raise BrowserError(f'File {params.path} does not exist')

			# Get the selector map to find the node
			selector_map = await browser_session.get_selector_map()
			if params.index not in selector_map:
				raise BrowserError(f'Element with index {params.index} not found in selector map')

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
					include_in_memory=True,
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
				if params.tab_id:
					target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)
				elif params.url:
					target_id = await browser_session.get_target_id_from_url(params.url)
				else:
					target_id = await browser_session.get_most_recently_opened_target_id()

				event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
				await event
				new_target_id = await event.event_result(raise_if_any=True, raise_if_none=False)
				assert new_target_id, 'SwitchTabEvent did not return a TargetID for the new tab that was switched to'
				memory = f'Switched to Tab with ID {new_target_id[-4:]}'
				logger.info(f'🔄  {memory}')
				return ActionResult(extracted_content=memory, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to switch tab: {type(e).__name__}: {e}')
				clean_msg = extract_llm_error_message(e)
				return ActionResult(error=f'Failed to switch to tab {params.tab_id or params.url}: {clean_msg}')

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
					include_in_memory=True,
					long_term_memory=memory,
				)
			except Exception as e:
				logger.error(f'Failed to close tab: {e}')
				clean_msg = extract_llm_error_message(e)
				return ActionResult(error=f'Failed to close tab {params.tab_id}: {clean_msg}')

		# Content Actions

		# TODO: Refactor to use events instead of direct page access
		# This action is temporarily disabled as it needs refactoring to use events

		@self.registry.action(
			"""Extract structured, semantic data (e.g. product description, price, all information about XYZ) from the current webpage based on a textual query.
		This tool takes the entire markdown of the page and extracts the query from it.
		Set extract_links=True ONLY if your query requires extracting links/URLs from the page.
		Only use this for specific queries for information retrieval from the page. Don't use this to get interactive elements - the tool does not see HTML elements, only the markdown.
		Note: Extracting from the same page will yield the same results unless more content is loaded (e.g., through scrolling for dynamic content, or new page is loaded) - so one extraction per page state is sufficient. If you want to scrape a listing of many elements always first scroll a lot until the page end to load everything and then call this tool in the end.
		If you called extract_structured_data in the last step and the result was not good (e.g. because of antispam protection), use the current browser state and scrolling to get the information, dont call extract_structured_data again.
		""",
		)
		async def extract_structured_data(
			query: str,
			extract_links: bool,
			browser_session: BrowserSession,
			page_extraction_llm: BaseChatModel,
			file_system: FileSystem,
		):
			cdp_session = await browser_session.get_or_create_cdp_session()

			# Wait for the page to be ready (same pattern used in DOM service)
			try:
				ready_state = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': 'document.readyState'}, session_id=cdp_session.session_id
				)
			except Exception:
				pass  # Page might not be ready yet

			try:
				# Get the HTML content
				body_id = await cdp_session.cdp_client.send.DOM.getDocument(session_id=cdp_session.session_id)
				page_html_result = await cdp_session.cdp_client.send.DOM.getOuterHTML(
					params={'backendNodeId': body_id['root']['backendNodeId']}, session_id=cdp_session.session_id
				)
			except Exception as e:
				raise RuntimeError(f"Couldn't extract page content: {e}")

			page_html = page_html_result['outerHTML']

			# Simple markdown conversion
			try:
				import re

				import markdownify

				if extract_links:
					content = markdownify.markdownify(page_html, heading_style='ATX', bullets='-')
				else:
					content = markdownify.markdownify(page_html, heading_style='ATX', bullets='-', strip=['a'])
					# Remove all markdown links and images, keep only the text
					content = re.sub(r'!\[.*?\]\([^)]*\)', '', content, flags=re.MULTILINE | re.DOTALL)  # Remove images
					content = re.sub(
						r'\[([^\]]*)\]\([^)]*\)', r'\1', content, flags=re.MULTILINE | re.DOTALL
					)  # Convert [text](url) -> text

				# Remove weird positioning artifacts

				content = re.sub(r'❓\s*\[\d+\]\s*\w+.*?Position:.*?Size:.*?\n?', '', content, flags=re.MULTILINE | re.DOTALL)
				content = re.sub(r'Primary: UNKNOWN\n\nNo specific evidence found', '', content, flags=re.MULTILINE | re.DOTALL)
				content = re.sub(r'UNKNOWN CONFIDENCE', '', content, flags=re.MULTILINE | re.DOTALL)
				content = re.sub(r'!\[\]\(\)', '', content, flags=re.MULTILINE | re.DOTALL)
			except Exception as e:
				raise RuntimeError(f'Could not convert html to markdown: {type(e).__name__}')

			# Simple truncation to 30k characters
			if len(content) > 30000:
				content = content[:30000] + '\n\n... [Content truncated at 30k characters] ...'

			# Simple prompt
			prompt = f"""Extract the requested information from this webpage content.
			
Query: {query}

Webpage Content:
{content}

Provide the extracted information in a clear, structured format."""

			try:
				response = await asyncio.wait_for(
					page_extraction_llm.ainvoke([UserMessage(content=prompt)]),
					timeout=120.0,
				)

				extracted_content = f'Query: {query}\n Result:\n{response.completion}'

				# Simple memory handling
				if len(extracted_content) < 1000:
					memory = extracted_content
					include_extracted_content_only_once = False
				else:
					save_result = await file_system.save_extracted_content(extracted_content)
					current_url = await browser_session.get_current_page_url()
					memory = (
						f'Extracted content from {current_url} for query: {query}\nContent saved to file system: {save_result}'
					)
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
			'Scroll the page by specified number of pages (set down=True to scroll down, down=False to scroll up, num_pages=number of pages to scroll like 0.5 for half page, 1.0 for one page, etc.). Optional index parameter to scroll within a specific element or its scroll container (works well for dropdowns and custom UI components). Use index=0 or omit index to scroll the entire page.',
			param_model=ScrollAction,
		)
		async def scroll(params: ScrollAction, browser_session: BrowserSession):
			try:
				# Look up the node from the selector map if index is provided
				# Special case: index 0 means scroll the whole page (root/body element)
				node = None
				if params.frame_element_index is not None and params.frame_element_index != 0:
					try:
						node = await browser_session.get_element_by_index(params.frame_element_index)
						if node is None:
							# Element not found - return error
							raise ValueError(f'Element index {params.frame_element_index} not found in DOM')
					except Exception as e:
						# Error getting element - return error
						raise ValueError(f'Failed to get element {params.frame_element_index}: {e}') from e

				# Dispatch scroll event with node - the complex logic is handled in the event handler
				# Convert pages to pixels (assuming 800px per page as standard viewport height)
				pixels = int(params.num_pages * 800)
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
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=long_term_memory)
			except Exception as e:
				logger.error(f'Failed to dispatch ScrollEvent: {type(e).__name__}: {e}')
				clean_msg = extract_llm_error_message(e)
				error_msg = f'Failed to scroll: {clean_msg}'
				return ActionResult(error=error_msg)

		@self.registry.action(
			'Send strings of special keys to use Playwright page.keyboard.press - examples include Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`',
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
				return ActionResult(extracted_content=memory, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				logger.error(f'Failed to dispatch SendKeysEvent: {type(e).__name__}: {e}')
				clean_msg = extract_llm_error_message(e)
				error_msg = f'Failed to send keys: {clean_msg}'
				return ActionResult(error=error_msg)

		@self.registry.action(
			description='Scroll to a text in the current page',
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
				return ActionResult(extracted_content=memory, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				# Text not found
				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					long_term_memory=f"Tried scrolling to text '{text}' but it was not found",
				)

		# Dropdown Actions

		@self.registry.action(
			'Get list of option values exposed by a specific dropdown input field. Only works on dropdown-style form elements (<select>, Semantic UI/aria-labeled select, etc.).',
			param_model=GetDropdownOptionsAction,
		)
		async def get_dropdown_options(params: GetDropdownOptionsAction, browser_session: BrowserSession):
			"""Get all options from a native dropdown or ARIA menu"""
			# Look up the node from the selector map
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				raise ValueError(f'Element index {params.index} not found in DOM')

			# Dispatch GetDropdownOptionsEvent to the event handler
			import json

			event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
			dropdown_data = await event.event_result(timeout=3.0, raise_if_none=True, raise_if_any=True)

			if not dropdown_data:
				raise ValueError('Failed to get dropdown options - no data returned')

			# Extract the message from the returned data
			msg = dropdown_data.get('message', '')
			options_count = len(json.loads(dropdown_data.get('options', '[]')))  # Parse the string back to list to get count

			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
				long_term_memory=f'Found {options_count} dropdown options for index {params.index}',
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
				raise ValueError(f'Element index {params.index} not found in DOM')

			# Dispatch SelectDropdownOptionEvent to the event handler
			from browser_use.browser.events import SelectDropdownOptionEvent

			event = browser_session.event_bus.dispatch(SelectDropdownOptionEvent(node=node, text=params.text))
			selection_data = await event.event_result()

			if not selection_data:
				raise ValueError('Failed to select dropdown option - no data returned')

			# Extract the message from the returned data
			msg = selection_data.get('message', f'Selected option: {params.text}')

			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
				long_term_memory=f"Selected dropdown option '{params.text}' at index {params.index}",
			)

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
			return ActionResult(extracted_content=result, include_in_memory=True, long_term_memory=result)

		@self.registry.action(
			'Replace old_str with new_str in file_name. old_str must exactly match the string to replace in original text. Recommended tool to mark completed items in todo.md or change specific contents in a file.'
		)
		async def replace_file_str(file_name: str, old_str: str, new_str: str, file_system: FileSystem):
			result = await file_system.replace_file_str(file_name, old_str, new_str)
			logger.info(f'💾 {result}')
			return ActionResult(extracted_content=result, include_in_memory=True, long_term_memory=result)

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
				include_in_memory=True,
				long_term_memory=memory,
				include_extracted_content_only_once=True,
			)

	# @self.registry.action('Google Sheets: Get the contents of the entire sheet', domains=['https://docs.google.com'])
	# async def read_sheet_contents(browser_session: BrowserSession):
	# 	# Use send keys events to select and copy all cells
	# 	for key in ['Enter', 'Escape', 'ControlOrMeta+A', 'ControlOrMeta+C']:
	# 		event = browser_session.event_bus.dispatch(SendKeysEvent(keys=key))
	# 		await event

	# 	# Get page to evaluate clipboard
	# 	page = await browser_session.get_current_page()
	# 	extracted_tsv = await page.evaluate('() => navigator.clipboard.readText()')
	# 	return ActionResult(
	# 		extracted_content=extracted_tsv,
	# 		include_in_memory=True,
	# 		long_term_memory='Retrieved sheet contents',
	# 		include_extracted_content_only_once=True,
	# 	)

	# @self.registry.action('Google Sheets: Get the contents of a cell or range of cells', domains=['https://docs.google.com'])
	# async def read_cell_contents(cell_or_range: str, browser_session: BrowserSession):
	# 	page = await browser_session.get_current_page()

	# 	await select_cell_or_range(cell_or_range=cell_or_range, page=page)

	# 	await page.keyboard.press('ControlOrMeta+C')
	# 	await asyncio.sleep(0.1)
	# 	extracted_tsv = await page.evaluate('() => navigator.clipboard.readText()')
	# 	return ActionResult(
	# 		extracted_content=extracted_tsv,
	# 		include_in_memory=True,
	# 		long_term_memory=f'Retrieved contents from {cell_or_range}',
	# 		include_extracted_content_only_once=True,
	# 	)

	# @self.registry.action(
	# 	'Google Sheets: Update the content of a cell or range of cells', domains=['https://docs.google.com']
	# )
	# async def update_cell_contents(cell_or_range: str, new_contents_tsv: str, browser_session: BrowserSession):
	# 	page = await browser_session.get_current_page()

	# 	await select_cell_or_range(cell_or_range=cell_or_range, page=page)

	# 	# simulate paste event from clipboard with TSV content
	# 	await page.evaluate(f"""
	# 		const clipboardData = new DataTransfer();
	# 		clipboardData.setData('text/plain', `{new_contents_tsv}`);
	# 		document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData}}));
	# 	""")

	# 	return ActionResult(
	# 		extracted_content=f'Updated cells: {cell_or_range} = {new_contents_tsv}',
	# 		include_in_memory=False,
	# 		long_term_memory=f'Updated cells {cell_or_range} with {new_contents_tsv}',
	# 	)

	# @self.registry.action('Google Sheets: Clear whatever cells are currently selected', domains=['https://docs.google.com'])
	# async def clear_cell_contents(cell_or_range: str, browser_session: BrowserSession):
	# 	page = await browser_session.get_current_page()

	# 	await select_cell_or_range(cell_or_range=cell_or_range, page=page)

	# 	await page.keyboard.press('Backspace')
	# 	return ActionResult(
	# 		extracted_content=f'Cleared cells: {cell_or_range}',
	# 		include_in_memory=False,
	# 		long_term_memory=f'Cleared cells {cell_or_range}',
	# 	)

	# @self.registry.action('Google Sheets: Select a specific cell or range of cells', domains=['https://docs.google.com'])
	# async def select_cell_or_range(cell_or_range: str, browser_session: BrowserSession):
	# 	# Use send keys events for navigation
	# 	for key in ['Enter', 'Escape']:
	# 		event = browser_session.event_bus.dispatch(SendKeysEvent(keys=key))
	# 		await event
	# 	await asyncio.sleep(0.1)
	# 	for key in ['Home', 'ArrowUp']:
	# 		event = browser_session.event_bus.dispatch(SendKeysEvent(keys=key))
	# 		await event
	# 	await asyncio.sleep(0.1)
	# 	event = browser_session.event_bus.dispatch(SendKeysEvent(keys='Control+G'))
	# 	await event
	# 	await asyncio.sleep(0.2)
	# 	# Get page to type the cell range
	# 	page = await browser_session.get_current_page()
	# 	await page.keyboard.type(cell_or_range, delay=0.05)
	# 	await asyncio.sleep(0.2)
	# 	for key in ['Enter', 'Escape']:
	# 		event = browser_session.event_bus.dispatch(SendKeysEvent(keys=key))
	# 		await event
	# 		await asyncio.sleep(0.2)
	# 	return ActionResult(
	# 		extracted_content=f'Selected cells: {cell_or_range}',
	# 		include_in_memory=False,
	# 		long_term_memory=f'Selected cells {cell_or_range}',
	# 	)

	# @self.registry.action(
	# 	'Google Sheets: Fallback method to type text into (only one) currently selected cell',
	# 	domains=['https://docs.google.com'],
	# )
	# async def fallback_input_into_single_selected_cell(text: str, browser_session: BrowserSession):
	# 	# Get page to type text
	# 	page = await browser_session.get_current_page()
	# 	await page.keyboard.type(text, delay=0.1)
	# 	# Use send keys for Enter and ArrowUp
	# 	for key in ['Enter', 'ArrowUp']:
	# 		event = browser_session.event_bus.dispatch(SendKeysEvent(keys=key))
	# 		await event
	# 	return ActionResult(
	# 		extracted_content=f'Inputted text {text}',
	# 		include_in_memory=False,
	# 		long_term_memory=f"Inputted text '{text}' into cell",
	# 	)

	# Custom done action for structured output
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
					extracted_content=json.dumps(output_dict),
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
		#
		context: Context | None = None,
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
							context=context,
						)
					except Exception as e:
						# Log the original exception with traceback for observability
						logger.error(f"Action '{action_name}' failed")
						# Extract clean error message from llm_error_msg tags if present
						clean_msg = extract_llm_error_message(e)
						result = ActionResult(error=clean_msg)

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
