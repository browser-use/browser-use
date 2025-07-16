import asyncio
import enum
import json
import logging
import os
import re
from typing import Generic, TypeVar, cast

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore
from bubus.helpers import retry
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.types import Page
from browser_use.browser.views import BrowserError
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	ScrollAction,
	SearchGoogleAction,
	SendKeysAction,
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
)
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.observability import observe_debug
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


Context = TypeVar('Context')

T = TypeVar('T', bound=BaseModel)


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

			page = await browser_session.get_current_page()
			if page.url.strip('/') == 'https://www.google.com':
				# SECURITY FIX: Use browser_session.navigate_to() instead of direct page.goto()
				# This ensures URL validation against allowed_domains is performed
				await browser_session.navigate_to(search_url)
			else:
				# create_new_tab already includes proper URL validation
				page = await browser_session.create_new_tab(search_url)

			msg = f'🔍  Searched for "{params.query}" in Google'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg, include_in_memory=True, long_term_memory=f"Searched Google for '{params.query}'"
			)

		@self.registry.action(
			'Navigate to URL, set new_tab=True to open in new tab, False to navigate in current tab', param_model=GoToUrlAction
		)
		async def go_to_url(params: GoToUrlAction, browser_session: BrowserSession):
			try:
				if params.new_tab:
					# Open in new tab (logic from open_tab function)
					page = await browser_session.create_new_tab(params.url)
					tab_idx = browser_session.tabs.index(page)
					memory = f'Opened new tab with URL {params.url}'
					msg = f'🔗  Opened new tab #{tab_idx} with url {params.url}'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=memory)
				else:
					# Navigate in current tab (original logic)
					# SECURITY FIX: Use browser_session.navigate_to() instead of direct page.goto()
					# This ensures URL validation against allowed_domains is performed
					await browser_session.navigate_to(params.url)
					memory = f'Navigated to {params.url}'
					msg = f'🔗 {memory}'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=memory)
			except Exception as e:
				error_msg = str(e)
				# Check for network-related errors
				if any(
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
					logger.warning(site_unavailable_msg)
					raise BrowserError(site_unavailable_msg)
				else:
					# Re-raise non-network errors (including URLNotAllowedError for unauthorized domains)
					raise

		@self.registry.action('Go back', param_model=NoParamsAction)
		async def go_back(params: NoParamsAction, browser_session: BrowserSession):
			"""Navigate back in browser history using CDP directly."""
			try:
				# Get CDP client and session ID
				cdp_client = await browser_session.get_cdp_client()
				session_id = await browser_session.get_current_page_cdp_session_id()

				# Get navigation history
				history = await cdp_client.send.Page.getNavigationHistory(session_id=session_id)
				current_index = history['currentIndex']
				entries = history['entries']

				# Check if we can go back
				if current_index <= 0:
					msg = '⚠️  Cannot go back - no previous page in history'
					logger.warning(msg)
					return ActionResult(
						extracted_content=msg,
						include_in_memory=True,
						long_term_memory='Attempted to go back but no history available',
					)

				# Get the previous entry
				previous_entry = entries[current_index - 1]
				previous_entry_id = previous_entry['id']
				previous_url = previous_entry['url']

				# Navigate to the previous history entry
				await cdp_client.send.Page.navigateToHistoryEntry(params={'entryId': previous_entry_id}, session_id=session_id)

				# For SPAs using history.pushState, the URL changes immediately but no load event fires
				# For real navigations, we need to wait for the page to load
				# We'll use a hybrid approach: wait a bit, then check if URL changed

				await asyncio.sleep(0.3)  # Give browser time to start navigation

				# Check if we're on the expected URL now
				page = await browser_session.get_current_page()
				current_url = page.url

				if current_url != previous_url:
					# URL changed but might still be loading
					# For real navigations, wait a bit more for content to load
					# For SPAs, this gives time for the app to update
					await asyncio.sleep(1.0)
				else:
					# URL hasn't changed yet, likely a real navigation
					# Wait longer for the page to load
					try:
						# We'll just wait up to 10 seconds for the navigation to complete
						# checking periodically if the URL has changed
						for _ in range(20):  # 20 * 0.5 = 10 seconds max
							await asyncio.sleep(0.5)
							page = await browser_session.get_current_page()
							if page.url == previous_url:
								break
					except Exception as e:
						logger.debug(f'Error while waiting for navigation: {e}')

				msg = f'🔙  Navigated back to {previous_url}'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg, include_in_memory=True, long_term_memory=f'Navigated back to {previous_url}'
				)

			except Exception as e:
				# Fallback to browser_session method if CDP fails
				logger.debug(f'⚠️  CDP navigation failed: {type(e).__name__}: {e}, falling back to browser method')
				await browser_session.go_back()
				msg = '🔙  Navigated back'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory='Navigated back')

		# wait for x seconds

		@self.registry.action('Wait for x seconds default 3 (max 10 seconds)')
		async def wait(seconds: int = 3):
			# Cap wait time at maximum 10 seconds
			actual_seconds = min(max(seconds, 0), 10)
			if actual_seconds != seconds:
				msg = f'🕒  Waiting for {actual_seconds} seconds (capped from {seconds} seconds, max 10 seconds)'
			else:
				msg = f'🕒  Waiting for {actual_seconds} seconds'
			logger.info(msg)
			await asyncio.sleep(actual_seconds)
			return ActionResult(
				extracted_content=msg, include_in_memory=True, long_term_memory=f'Waited for {actual_seconds} seconds'
			)

		# Element Interaction Actions

		@self.registry.action('Click element by index', param_model=ClickElementAction)
		async def click_element_by_index(params: ClickElementAction, browser_session: BrowserSession):
			# Browser is now a BrowserSession itself

			# Check if element exists in current selector map
			selector_map = await browser_session.get_selector_map()
			if params.index not in selector_map:
				# Force a state refresh in case the cache is stale
				logger.info(f'Element with index {params.index} not found in selector map, refreshing state...')
				await browser_session.get_state_summary(
					cache_clickable_elements_hashes=True
				)  # This will refresh the cached state
				selector_map = await browser_session.get_selector_map()

				if params.index not in selector_map:
					# Return informative message with the new state instead of error
					max_index = max(selector_map.keys()) if selector_map else -1
					msg = f'Element with index {params.index} does not exist. Page has {len(selector_map)} interactive elements (indices 0-{max_index}). State has been refreshed - please use the updated element indices or scroll to see more elements'
					return ActionResult(extracted_content=msg, include_in_memory=True, success=False, long_term_memory=msg)

			element_node = await browser_session.get_dom_element_by_index(params.index)
			initial_pages = len(browser_session.tabs)

			# if element has file uploader then dont click
			# Check if element is actually a file input (not just contains file-related keywords)
			if element_node is not None and browser_session.is_file_input(element_node):
				msg = f'Index {params.index} - has an element which opens file upload dialog. To upload files please use a specific function to upload files '
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, success=False, long_term_memory=msg)

			msg = None

			try:
				assert element_node is not None, f'Element with index {params.index} does not exist'

				# Try CDP-based click first
				cdp_client = await browser_session.get_cdp_client()
				session_id = await browser_session.get_current_page_cdp_session_id()
				backend_node_id = element_node.backend_node_id

				# Check if element has bounds from snapshot
				if element_node.snapshot_node and element_node.snapshot_node.bounds:
					# We have cached bounds, use them
					center_x, center_y = element_node.snapshot_node.bounds.center
				else:
					# Get fresh bounds using CDP
					try:
						# Get the bounding box of the element
						box_model = await cdp_client.send.DOM.getBoxModel(
							params={'backendNodeId': backend_node_id}, session_id=session_id
						)

						if 'model' not in box_model or 'content' not in box_model['model']:
							raise Exception('Could not get element bounds')

						# Extract content quad (the actual visible area)
						content_quad = box_model['model']['content']
						if len(content_quad) < 8:
							raise Exception('Invalid content quad')

						# Calculate center point from quad (x1,y1, x2,y2, x3,y3, x4,y4)
						center_x = (content_quad[0] + content_quad[2] + content_quad[4] + content_quad[6]) / 4
						center_y = (content_quad[1] + content_quad[3] + content_quad[5] + content_quad[7]) / 4
					except Exception as e:
						logger.debug(f'Failed to get element bounds via CDP: {e}')
						# Fallback to browser_session method
						download_path = await browser_session._click_element_node(element_node)
						if download_path:
							emoji = '💾'
							msg = f'Downloaded file to {download_path}'
						else:
							emoji = '🖱️'
							msg = f'Clicked button with index {params.index}: {element_node.llm_representation()}'

						logger.info(f'{emoji} {msg}')
						logger.debug(f'Element xpath: {element_node.xpath}')
						if len(browser_session.tabs) > initial_pages:
							new_tab_msg = 'New tab opened - switching to it'
							msg += f' - {new_tab_msg}'
							emoji = '🔗'
							logger.info(f'{emoji} {new_tab_msg}')
							await browser_session.switch_to_tab(-1)
						return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

				# Scroll element into view first
				try:
					await cdp_client.send.DOM.scrollIntoViewIfNeeded(
						params={'backendNodeId': backend_node_id}, session_id=session_id
					)
					await asyncio.sleep(0.1)  # Wait for scroll to complete
				except Exception as e:
					logger.debug(f'Failed to scroll element into view: {e}')

				# Set up download detection if downloads are enabled
				download_path = None
				download_event = asyncio.Event()
				download_guid = None

				if browser_session.browser_profile.downloads_path:
					# Enable download events
					await cdp_client.send.Page.setDownloadBehavior(
						params={'behavior': 'allow', 'downloadPath': str(browser_session.browser_profile.downloads_path)},
						session_id=session_id,
					)

					# Set up download listener
					async def on_download_will_begin(event):
						nonlocal download_guid
						download_guid = event['guid']
						download_event.set()

					cdp_client.on('Page.downloadWillBegin', on_download_will_begin, session_id=session_id)  # type: ignore[attr-defined]

				# Perform the click using CDP
				try:
					# Move mouse to element
					await cdp_client.send.Input.dispatchMouseEvent(
						params={
							'type': 'mouseMoved',
							'x': center_x,
							'y': center_y,
						},
						session_id=session_id,
					)

					# Mouse down
					await cdp_client.send.Input.dispatchMouseEvent(
						params={
							'type': 'mousePressed',
							'x': center_x,
							'y': center_y,
							'button': 'left',
							'clickCount': 1,
						},
						session_id=session_id,
					)

					# Mouse up
					await cdp_client.send.Input.dispatchMouseEvent(
						params={
							'type': 'mouseReleased',
							'x': center_x,
							'y': center_y,
							'button': 'left',
							'clickCount': 1,
						},
						session_id=session_id,
					)

					# Check for download (wait up to 5 seconds)
					if browser_session.browser_profile.downloads_path:
						try:
							await asyncio.wait_for(download_event.wait(), timeout=5.0)
							if download_guid:
								# Get download progress
								async def on_download_progress(event):
									if event['guid'] == download_guid and event['state'] == 'completed':
										nonlocal download_path
										# Extract filename from receivedBytes/totalBytes event data
										suggested_filename = event.get('suggestedFilename', 'download')
										unique_filename = await browser_session._get_unique_filename(
											str(browser_session.browser_profile.downloads_path), suggested_filename
										)
										download_path = os.path.join(
											str(browser_session.browser_profile.downloads_path), unique_filename
										)
										# Track the downloaded file
										browser_session._downloaded_files.append(download_path)
										logger.info(f'⬇️ Downloaded file to: {download_path}')
										logger.info(
											f'📁 Added download to session tracking (total: {len(browser_session._downloaded_files)} files)'
										)

								cdp_client.on('Page.downloadProgress', on_download_progress, session_id=session_id)  # type: ignore[attr-defined]
								# Wait a bit for download to complete
								await asyncio.sleep(2.0)
						except TimeoutError:
							# No download triggered
							pass

					# If no download, wait for potential navigation
					if not download_path:
						await asyncio.sleep(0.5)  # Give time for navigation to start
						page = await browser_session.get_current_page()
						try:
							await page.wait_for_load_state(state='domcontentloaded', timeout=5000)
						except Exception:
							pass  # Page might not navigate

				except Exception as e:
					# CDP click failed, fallback to browser_session method
					logger.debug(f'CDP click failed: {e}, falling back to browser method')
					download_path = await browser_session._click_element_node(element_node)

				if download_path:
					emoji = '💾'
					msg = f'Downloaded file to {download_path}'
				else:
					emoji = '🖱️'
					msg = f'Clicked button with index {params.index}: {element_node.llm_representation()}'

				logger.info(f'{emoji} {msg}')
				logger.debug(f'Element xpath: {element_node.xpath}')
				if len(browser_session.tabs) > initial_pages:
					new_tab_msg = 'New tab opened - switching to it'
					msg += f' - {new_tab_msg}'
					emoji = '🔗'
					logger.info(f'{emoji} {new_tab_msg}')
					await browser_session.switch_to_tab(-1)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)
			except Exception as e:
				error_msg = str(e)
				if 'Execution context was destroyed' in error_msg or 'Cannot find context with specified id' in error_msg:
					# Page navigated during click - refresh state and return it
					logger.info('Page context changed during click, refreshing state...')
					await browser_session.get_state_summary(cache_clickable_elements_hashes=True)
					raise BrowserError('Page navigated during click. Refreshed state provided.')
				else:
					logger.warning(f'Element not clickable with index {params.index} - most likely the page changed')
					raise BrowserError(error_msg)

		@self.registry.action(
			'Click and input text into a input interactive element',
			param_model=InputTextAction,
		)
		async def input_text(params: InputTextAction, browser_session: BrowserSession, has_sensitive_data: bool = False):
			if params.index not in await browser_session.get_selector_map():
				raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')

			element_node = await browser_session.get_dom_element_by_index(params.index)
			assert element_node is not None, f'Element with index {params.index} does not exist'
			try:
				# Try CDP-based input first
				cdp_client = await browser_session.get_cdp_client()
				session_id = await browser_session.get_current_page_cdp_session_id()

				# Get the backend node ID for the element
				backend_node_id = element_node.backend_node_id

				# First focus the element using CDP
				await cdp_client.send.DOM.focus(params={'backendNodeId': backend_node_id}, session_id=session_id)

				# Wait a bit for focus to take effect
				await asyncio.sleep(0.1)

				# Clear existing text by selecting all and deleting
				# First, resolve the node to get its object ID for direct manipulation
				object_id = None
				try:
					resolved_node = await cdp_client.send.DOM.resolveNode(
						params={'backendNodeId': backend_node_id}, session_id=session_id
					)
					object_id = resolved_node['object'].get('objectId')
					if not object_id:
						raise Exception('No objectId in resolved node')

					# Select all text in the input field directly via JavaScript
					await cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': """
								function() {
									// Select all text for different element types
									if (this.select) {
										// For input and textarea elements
										this.select();
									} else if (this.setSelectionRange) {
										// Alternative for input elements
										this.setSelectionRange(0, this.value.length);
									} else if (window.getSelection && this.contentEditable === 'true') {
										// For contenteditable elements
										const selection = window.getSelection();
										const range = document.createRange();
										range.selectNodeContents(this);
										selection.removeAllRanges();
										selection.addRange(range);
									}
								}
							""",
							'objectId': object_id,
						},
						session_id=session_id,
					)

					# Small delay to ensure selection is processed
					await asyncio.sleep(0.05)

				except Exception as e:
					logger.debug(f'Failed to select text via JavaScript: {e}, trying keyboard shortcut')
					# Fallback to keyboard shortcut
					import platform

					modifiers = 4 if platform.system() == 'Darwin' else 2  # Meta/Cmd on Mac, Ctrl on others
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'a',
							'code': 'KeyA',
							'modifiers': modifiers,
						},
						session_id=session_id,
					)
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'a',
							'code': 'KeyA',
							'modifiers': modifiers,
						},
						session_id=session_id,
					)

				# Delete selected text
				await cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': 'Backspace',
						'code': 'Backspace',
					},
					session_id=session_id,
				)
				await cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': 'Backspace',
						'code': 'Backspace',
					},
					session_id=session_id,
				)

				# Small delay after clearing
				await asyncio.sleep(0.05)

				# Insert the new text using CDP
				await cdp_client.send.Input.insertText(params={'text': params.text}, session_id=session_id)

				# Dispatch input and change events
				try:
					if object_id is None:
						# Need to resolve the node if we didn't already
						resolved_node = await cdp_client.send.DOM.resolveNode(
							params={'backendNodeId': backend_node_id}, session_id=session_id
						)
						object_id = resolved_node['object'].get('objectId')
						if not object_id:
							raise Exception('No objectId in resolved node')

					# Dispatch input and change events using the resolved node
					await cdp_client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': """
								function() {
									this.dispatchEvent(new Event('input', { bubbles: true }));
									this.dispatchEvent(new Event('change', { bubbles: true }));
								}
							""",
							'objectId': object_id,
						},
						session_id=session_id,
					)
				except Exception as e:
					# If resolveNode fails (e.g., element in iframe), try a more generic approach
					logger.debug(f'Failed to resolve node for events: {e}, using generic approach')
					# Use Runtime.evaluate to find and trigger events on the focused element
					await cdp_client.send.Runtime.evaluate(
						params={
							'expression': """
								(() => {
									const activeElement = document.activeElement;
									if (activeElement && (activeElement.tagName === 'INPUT' || 
										activeElement.tagName === 'TEXTAREA' || 
										activeElement.contentEditable === 'true')) {
										activeElement.dispatchEvent(new Event('input', { bubbles: true }));
										activeElement.dispatchEvent(new Event('change', { bubbles: true }));
									}
								})()
							"""
						},
						session_id=session_id,
					)

			except Exception as e:
				# Fallback to browser_session method if CDP fails
				logger.debug(f'CDP input failed: {type(e).__name__}: {e}, falling back to browser method')
				try:
					await browser_session._input_text_element_node(element_node, params.text)
				except Exception:
					msg = f'Failed to input text into element {params.index}.'
					raise BrowserError(msg)

			if not has_sensitive_data:
				msg = f'⌨️  Input {params.text} into index {params.index}'
			else:
				msg = f'⌨️  Input sensitive data into index {params.index}'
			logger.info(msg)
			logger.debug(f'Element xpath: {element_node.xpath}')
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
				long_term_memory=f"Input '{params.text}' into element {params.index}.",
			)

		@self.registry.action('Upload file to interactive element with file path', param_model=UploadFileAction)
		async def upload_file(params: UploadFileAction, browser_session: BrowserSession, available_file_paths: list[str]):
			if params.path not in available_file_paths:
				raise BrowserError(f'File path {params.path} is not available')

			if not os.path.exists(params.path):
				raise BrowserError(f'File {params.path} does not exist')

			file_upload_dom_el = await browser_session.find_file_upload_element_by_index(
				params.index, max_height=3, max_descendant_depth=3
			)

			if file_upload_dom_el is None:
				msg = f'No file upload element found at index {params.index}'
				logger.info(msg)
				raise BrowserError(msg)

			file_upload_el = await browser_session.get_locate_element(file_upload_dom_el)

			if file_upload_el is None:
				msg = f'No file upload element found at index {params.index}'
				logger.info(msg)
				raise BrowserError(msg)

			try:
				await file_upload_el.set_input_files(params.path)
				msg = f'📁 Successfully uploaded file to index {params.index}'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					long_term_memory=f'Uploaded file {params.path} to element {params.index}',
				)
			except Exception as e:
				msg = f'Failed to upload file to index {params.index}: {str(e)}'
				logger.info(msg)
				raise BrowserError(msg)

		# Tab Management Actions

		@self.registry.action('Switch tab', param_model=SwitchTabAction)
		async def switch_tab(params: SwitchTabAction, browser_session: BrowserSession):
			# Get the extension bridge from browser session
			extension_bridge = browser_session.extension_bridge
			if not extension_bridge:
				# Fallback to Playwright method if extension bridge is not available
				logger.warning('Extension bridge not available, falling back to Playwright method')
				await browser_session.switch_to_tab(params.page_id)
				page = await browser_session.get_current_page()
				try:
					await page.wait_for_load_state(state='domcontentloaded', timeout=5_000)
				except Exception as e:
					pass
				msg = f'🔄  Switched to tab #{params.page_id} with url {page.url}'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg, include_in_memory=True, long_term_memory=f'Switched to tab {params.page_id}'
				)

			try:
				# Get all tabs to find the target tab by index
				all_tabs = await extension_bridge.call('chrome.tabs.query', [{}])
				logger.debug(f'Found {len(all_tabs)} tabs via extension bridge')

				if params.page_id >= len(all_tabs):
					raise BrowserError(f'Tab index {params.page_id} out of range (only {len(all_tabs)} tabs)')

				target_tab = all_tabs[params.page_id]

				# Switch to the target tab
				await extension_bridge.call('chrome.tabs.update', [target_tab['id'], {'active': True}])

				# Also focus the window containing the tab
				await extension_bridge.call('chrome.windows.update', [target_tab['windowId'], {'focused': True}])

				# Update browser session's current page reference
				await browser_session._sync_current_tab_from_extension(target_tab['id'])
				page = await browser_session.get_current_page()

				try:
					await page.wait_for_load_state(state='domcontentloaded', timeout=5_000)
					# page was already loaded when we first navigated, this is additional to wait for onfocus/onblur animations/ajax to settle
				except Exception as e:
					pass

				msg = f'🔄  Switched to tab #{params.page_id} with url {target_tab["url"]}'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg, include_in_memory=True, long_term_memory=f'Switched to tab {params.page_id}'
				)
			except Exception as e:
				logger.error(f'Extension bridge error in switch_tab: {e}')
				# Fallback to Playwright method
				await browser_session.switch_to_tab(params.page_id)
				page = await browser_session.get_current_page()
				try:
					await page.wait_for_load_state(state='domcontentloaded', timeout=5_000)
				except Exception as e:
					pass
				msg = f'🔄  Switched to tab #{params.page_id} with url {page.url} (fallback)'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg, include_in_memory=True, long_term_memory=f'Switched to tab {params.page_id}'
				)

		@self.registry.action('Close an existing tab', param_model=CloseTabAction)
		async def close_tab(params: CloseTabAction, browser_session: BrowserSession):
			# Get the extension bridge from browser session
			extension_bridge = browser_session.extension_bridge
			if not extension_bridge:
				raise BrowserError('Extension bridge not initialized')

			# Get all tabs to find the target tab by index
			all_tabs = await extension_bridge.call('chrome.tabs.query', [{}])
			if params.page_id >= len(all_tabs):
				raise BrowserError(f'Tab index {params.page_id} out of range (only {len(all_tabs)} tabs)')

			target_tab = all_tabs[params.page_id]
			tab_url = target_tab['url']
			tab_id = target_tab['id']

			# Close the tab
			await extension_bridge.call('chrome.tabs.remove', [tab_id])

			# Get the newly active tab
			query_options = {'active': True, 'lastFocusedWindow': True}
			active_tabs = await extension_bridge.call('chrome.tabs.query', [query_options])
			if not active_tabs:
				raise BrowserError('No active tab after closing')

			new_active_tab = active_tabs[0]

			# Find the index of the new active tab
			updated_tabs = await extension_bridge.call('chrome.tabs.query', [{}])
			new_page_idx = next((i for i, tab in enumerate(updated_tabs) if tab['id'] == new_active_tab['id']), 0)

			# Update browser session's current page reference
			await browser_session._sync_current_tab_from_extension(new_active_tab['id'])

			msg = f'❌  Closed tab #{params.page_id} with {tab_url}, now focused on tab #{new_page_idx} with url {new_active_tab["url"]}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
				long_term_memory=f'Closed tab {params.page_id} with url {tab_url}, now focused on tab {new_page_idx} with url {new_active_tab["url"]}.',
			)

		# Content Actions

		@self.registry.action(
			"""Extract structured, semantic data (e.g. product description, price, all information about XYZ) from the current webpage based on a textual query.
This tool takes the entire markdown of the page and extracts the query from it. 
Set extract_links=True ONLY if your query requires extracting links/URLs from the page. 
Only use this for specific queries for information retrieval from the page. Don't use this to get interactive elements - the tool does not see HTML elements, only the markdown.
""",
		)
		async def extract_structured_data(
			query: str,
			extract_links: bool,
			page: Page,
			page_extraction_llm: BaseChatModel,
			file_system: FileSystem,
		):
			from functools import partial

			import markdownify

			strip = []

			if not extract_links:
				strip = ['a', 'img']

			# Run markdownify in a thread pool to avoid blocking the event loop
			loop = asyncio.get_event_loop()

			# Aggressive timeout for page content
			try:
				page_html_result = await asyncio.wait_for(page.content(), timeout=10.0)  # 5 second aggressive timeout
			except TimeoutError:
				raise RuntimeError('Page content extraction timed out after 5 seconds')
			except Exception as e:
				raise RuntimeError(f"Couldn't extract page content: {e}")

			page_html = page_html_result

			markdownify_func = partial(markdownify.markdownify, strip=strip)

			try:
				content = await asyncio.wait_for(
					loop.run_in_executor(None, markdownify_func, page_html), timeout=5.0
				)  # 5 second aggressive timeout
			except Exception as e:
				logger.warning(f'Markdownify failed: {type(e).__name__}')
				raise RuntimeError(f'Could not convert html to markdown: {type(e).__name__}')

			# manually append iframe text into the content so it's readable by the LLM (includes cross-origin iframes)
			for iframe in page.frames:
				try:
					await iframe.wait_for_load_state(timeout=1000)  # 1 second aggressive timeout for iframe load
				except Exception:
					pass

				if iframe.url != page.url and not iframe.url.startswith('data:') and not iframe.url.startswith('about:'):
					content += f'\n\nIFRAME {iframe.url}:\n'
					# Run markdownify in a thread pool for iframe content as well
					try:
						# Aggressive timeouts for iframe content
						iframe_html = await asyncio.wait_for(iframe.content(), timeout=2.0)  # 2 second aggressive timeout
						iframe_markdown = await asyncio.wait_for(
							loop.run_in_executor(None, markdownify_func, iframe_html),
							timeout=2.0,  # 2 second aggressive timeout for iframe markdownify
						)
					except Exception:
						iframe_markdown = ''  # Skip failed iframes
					content += iframe_markdown
			# replace multiple sequential \n with a single \n
			content = re.sub(r'\n+', '\n', content)

			# limit to 30000 characters - remove text in the middle (≈15000 tokens)
			max_chars = 30000
			if len(content) > max_chars:
				logger.info(f'Content is too long, removing middle {len(content) - max_chars} characters')
				content = (
					content[: max_chars // 2]
					+ '\n... left out the middle because it was too long ...\n'
					+ content[-max_chars // 2 :]
				)

			prompt = """You convert websites into structured information. Extract information from this webpage based on the query. Focus only on content relevant to the query. If 
1. The query is vague
2. Does not make sense for the page
3. Some/all of the information is not available

Explain the content of the page and that the requested information is not available in the page. Respond in JSON format.\nQuery: {query}\n Website:\n{page}"""
			try:
				formatted_prompt = prompt.format(query=query, page=content)
				# Aggressive timeout for LLM call
				response = await asyncio.wait_for(
					page_extraction_llm.ainvoke([UserMessage(content=formatted_prompt)]),
					timeout=120.0,  # 120 second aggressive timeout for LLM call
				)

				extracted_content = f'Page Link: {page.url}\nQuery: {query}\nExtracted Content:\n{response.completion}'

				# if content is small include it to memory
				MAX_MEMORY_SIZE = 600
				if len(extracted_content) < MAX_MEMORY_SIZE:
					memory = extracted_content
					include_extracted_content_only_once = False
				else:
					# find lines until MAX_MEMORY_SIZE
					lines = extracted_content.splitlines()
					display = ''
					display_lines_count = 0
					for line in lines:
						if len(display) + len(line) < MAX_MEMORY_SIZE:
							display += line + '\n'
							display_lines_count += 1
						else:
							break
					save_result = await file_system.save_extracted_content(extracted_content)
					memory = f'Extracted content from {page.url}\n<query>{query}\n</query>\n<extracted_content>\n{display}{len(lines) - display_lines_count} more lines...\n</extracted_content>\n<file_system>{save_result}</file_system>'
					include_extracted_content_only_once = True
				logger.info(f'📄 {memory}')
				return ActionResult(
					extracted_content=extracted_content,
					include_extracted_content_only_once=include_extracted_content_only_once,
					long_term_memory=memory,
				)
			except TimeoutError:
				error_msg = f'LLM call timed out for query: {query}'
				logger.warning(error_msg)
				raise RuntimeError(error_msg)
			except Exception as e:
				logger.debug(f'Error extracting content: {e}')
				msg = f'📄  Extracted from page\n: {content}\n'
				logger.info(msg)
				raise RuntimeError(str(e))

		# @self.registry.action(
		# 	'Get the accessibility tree of the page in the format "role name" with the number_of_elements to return',
		# )
		# async def get_ax_tree(number_of_elements: int, page: Page):
		# 	node = await page.accessibility.snapshot(interesting_only=True)

		# 	def flatten_ax_tree(node, lines):
		# 		if not node:
		# 			return
		# 		role = node.get('role', '')
		# 		name = node.get('name', '')
		# 		lines.append(f'{role} {name}')
		# 		for child in node.get('children', []):
		# 			flatten_ax_tree(child, lines)

		# 	lines = []
		# 	flatten_ax_tree(node, lines)
		# 	msg = '\n'.join(lines)
		# 	logger.info(msg)
		# 	return ActionResult(
		# 		extracted_content=msg,
		# 		include_in_memory=False,
		# 		long_term_memory='Retrieved accessibility tree',
		# 		include_extracted_content_only_once=True,
		# 	)

		@self.registry.action(
			'Scroll the page by specified number of pages (set down=True to scroll down, down=False to scroll up, num_pages=number of pages to scroll like 0.5 for half page, 1.0 for one page, etc.). Optional index parameter to scroll within a specific element or its scroll container (works well for dropdowns and custom UI components).',
			param_model=ScrollAction,
		)
		async def scroll(params: ScrollAction, browser_session: BrowserSession):
			"""
			(a) If index is provided, find scrollable containers in the element hierarchy and scroll directly.
			(b) If no index or no container found, use browser._scroll_container for container-aware scrolling.
			(c) If that JavaScript throws, fall back to window.scrollBy().
			"""
			page = await browser_session.get_current_page()

			# Helper function to get window height with retry decorator
			@retry(wait=1, retries=3, timeout=5)
			async def get_window_height():
				return await page.evaluate('() => window.innerHeight')

			# Get window height with retries
			try:
				window_height = await get_window_height()
			except Exception as e:
				raise RuntimeError(f'Scroll failed due to an error: {e}')
			window_height = window_height or 0

			# Determine scroll amount based on num_pages
			scroll_amount = int(window_height * params.num_pages)
			pages_scrolled = params.num_pages

			# Set direction based on down parameter
			dy = scroll_amount if params.down else -scroll_amount

			# Initialize result message components
			direction = 'down' if params.down else 'up'
			scroll_target = 'the page'
			pages_text = f'{pages_scrolled} pages' if pages_scrolled != 1.0 else 'one page'

			# Element-specific scrolling if index is provided
			if params.index is not None:
				try:
					# Check if element exists in current selector map
					selector_map = await browser_session.get_selector_map()
					element_node = None  # Initialize to avoid undefined variable

					if params.index not in selector_map:
						# Force a state refresh in case the cache is stale
						logger.info(f'Element with index {params.index} not found in selector map, refreshing state...')
						await browser_session.get_state_summary(cache_clickable_elements_hashes=True)
						selector_map = await browser_session.get_selector_map()

						if params.index not in selector_map:
							# Return informative message about invalid index
							max_index = max(selector_map.keys()) if selector_map else -1
							msg = f'❌ Element with index {params.index} does not exist. Page has {len(selector_map)} interactive elements (indices 0-{max_index}). Using page-level scroll instead.'
							logger.warning(msg)
							scroll_target = 'the page'
							# Skip element-specific scrolling
						else:
							element_node = await browser_session.get_dom_element_by_index(params.index)
					else:
						element_node = await browser_session.get_dom_element_by_index(params.index)

					if element_node is not None and params.index in selector_map:
						# Try direct container scrolling (no events that might close dropdowns)
						container_scroll_js = """
						(params) => {
							const { dy, elementXPath } = params;
							
							// Get the target element by XPath
							const targetElement = document.evaluate(elementXPath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
							if (!targetElement) {
								return { success: false, reason: 'Element not found by XPath' };
							}

							console.log('[SCROLL DEBUG] Starting direct container scroll for element:', targetElement.tagName);
							
							// Try to find scrollable containers in the hierarchy (starting from element itself)
							let currentElement = targetElement;
							let scrollSuccess = false;
							let scrolledElement = null;
							let scrollDelta = 0;
							let attempts = 0;
							
							// Check up to 10 elements in hierarchy (including the target element itself)
							while (currentElement && attempts < 10) {
								const computedStyle = window.getComputedStyle(currentElement);
								const hasScrollableY = /(auto|scroll|overlay)/.test(computedStyle.overflowY);
								const canScrollVertically = currentElement.scrollHeight > currentElement.clientHeight;
								
								console.log('[SCROLL DEBUG] Checking element:', currentElement.tagName, 
									'hasScrollableY:', hasScrollableY, 
									'canScrollVertically:', canScrollVertically,
									'scrollHeight:', currentElement.scrollHeight,
									'clientHeight:', currentElement.clientHeight);
								
								if (hasScrollableY && canScrollVertically) {
									const beforeScroll = currentElement.scrollTop;
									const maxScroll = currentElement.scrollHeight - currentElement.clientHeight;
									
									// Calculate scroll amount (1/3 of provided dy for gentler scrolling)
									let scrollAmount = dy / 3;
									
									// Ensure we don't scroll beyond bounds
									if (scrollAmount > 0) {
										scrollAmount = Math.min(scrollAmount, maxScroll - beforeScroll);
									} else {
										scrollAmount = Math.max(scrollAmount, -beforeScroll);
									}
									
									// Try direct scrollTop manipulation (most reliable)
									currentElement.scrollTop = beforeScroll + scrollAmount;
									
									const afterScroll = currentElement.scrollTop;
									const actualScrollDelta = afterScroll - beforeScroll;
									
									console.log('[SCROLL DEBUG] Scroll attempt:', currentElement.tagName, 
										'before:', beforeScroll, 'after:', afterScroll, 'delta:', actualScrollDelta);
									
									if (Math.abs(actualScrollDelta) > 0.5) {
										scrollSuccess = true;
										scrolledElement = currentElement;
										scrollDelta = actualScrollDelta;
										console.log('[SCROLL DEBUG] Successfully scrolled container:', currentElement.tagName, 'delta:', actualScrollDelta);
										break;
									}
								}
								
								// Move to parent (but don't go beyond body for dropdown case)
								if (currentElement === document.body || currentElement === document.documentElement) {
									break;
								}
								currentElement = currentElement.parentElement;
								attempts++;
							}
							
							if (scrollSuccess) {
								// Successfully scrolled a container
								return { 
									success: true, 
									method: 'direct_container_scroll',
									containerType: 'element', 
									containerTag: scrolledElement.tagName.toLowerCase(),
									containerClass: scrolledElement.className || '',
									containerId: scrolledElement.id || '',
									scrollDelta: scrollDelta
								};
							} else {
								// No container found or could scroll
								console.log('[SCROLL DEBUG] No scrollable container found for element');
								return { 
									success: false, 
									reason: 'No scrollable container found',
									needsPageScroll: true
								};
							}
						}
						"""

						# Pass parameters as a single object
						scroll_params = {'dy': dy, 'elementXPath': element_node.xpath}
						result = await page.evaluate(container_scroll_js, scroll_params)

						if result['success']:
							if result['containerType'] == 'element':
								container_info = f'{result["containerTag"]}'
								if result['containerId']:
									container_info += f'#{result["containerId"]}'
								elif result['containerClass']:
									container_info += f'.{result["containerClass"].split()[0]}'
								scroll_target = f"element {params.index}'s scroll container ({container_info})"
								# Don't do additional page scrolling since we successfully scrolled the container
							else:
								scroll_target = f'the page (fallback from element {params.index})'
						else:
							# Container scroll failed, need page-level scrolling
							logger.debug(f'Container scroll failed for element {params.index}: {result.get("reason", "Unknown")}')
							scroll_target = f'the page (no container found for element {params.index})'
							# This will trigger page-level scrolling below

				except Exception as e:
					logger.debug(f'Element-specific scrolling failed for index {params.index}: {e}')
					scroll_target = f'the page (fallback from element {params.index})'
					# Fall through to page-level scrolling

			# Page-level scrolling (default or fallback)
			if (
				scroll_target == 'the page'
				or 'fallback' in scroll_target
				or 'no container found' in scroll_target
				or 'mouse wheel failed' in scroll_target
			):
				logger.debug(f'🔄 Performing page-level scrolling. Reason: {scroll_target}')
				try:
					await browser_session._scroll_container(cast(int, dy))
				except Exception as e:
					# Hard fallback: always works on root scroller
					await page.evaluate('(y) => window.scrollBy(0, y)', dy)
					logger.debug('Smart scroll failed; used window.scrollBy fallback', exc_info=e)

			# Create descriptive message
			if pages_scrolled == 1.0:
				long_term_memory = f'Scrolled {direction} {scroll_target} by one page'
			else:
				long_term_memory = f'Scrolled {direction} {scroll_target} by {pages_scrolled} pages'

			msg = f'🔍 {long_term_memory}'

			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=long_term_memory)

		# send keys

		@self.registry.action(
			'Send strings of special keys to use Playwright page.keyboard.press - examples include Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser_session: BrowserSession):
			"""Send keyboard keys/shortcuts using CDP directly."""
			try:
				# Get CDP client and session ID
				cdp_client = await browser_session.get_cdp_client()
				session_id = await browser_session.get_current_page_cdp_session_id()

				# Parse the key string to handle modifiers and special keys
				keys_to_send = params.keys

				# Check if it's a keyboard shortcut with modifiers
				modifiers = 0
				parts = keys_to_send.split('+')

				# Check if it's a special key or shortcut
				is_special_key = False
				if len(parts) > 1:
					# Handle shortcuts like Control+o, Control+Shift+T
					is_special_key = True
					for part in parts[:-1]:  # All but the last part are modifiers
						part_lower = part.lower()
						if part_lower in ['ctrl', 'control']:
							modifiers |= 2  # Ctrl
						elif part_lower == 'shift':
							modifiers |= 8  # Shift
						elif part_lower == 'alt':
							modifiers |= 1  # Alt
						elif part_lower in ['meta', 'command', 'cmd']:
							modifiers |= 4  # Meta/Command
						elif part_lower == 'controlormeta':
							# Use Control on non-Mac, Meta on Mac
							import platform

							if platform.system() == 'Darwin':
								modifiers |= 4  # Meta/Command on Mac
							else:
								modifiers |= 2  # Control on Windows/Linux

					# The last part is the actual key
					main_key = parts[-1]
				else:
					# Check if it's a single special key (Tab, Enter, etc.) or regular text
					special_keys = [
						'Tab',
						'Enter',
						'Escape',
						'Backspace',
						'Delete',
						'PageDown',
						'PageUp',
						'Home',
						'End',
						'ArrowUp',
						'ArrowDown',
						'ArrowLeft',
						'ArrowRight',
						'F1',
						'F2',
						'F3',
						'F4',
						'F5',
						'F6',
						'F7',
						'F8',
						'F9',
						'F10',
						'F11',
						'F12',
					]
					if keys_to_send in special_keys:
						is_special_key = True
						main_key = keys_to_send
					else:
						# It's regular text to type - handle each character
						for char in keys_to_send:
							# Determine key and code for each character
							if char == ' ':
								key = ' '
								code = 'Space'
							elif char == '\n':
								key = 'Enter'
								code = 'Enter'
							elif char.isalpha():
								key = char
								code = f'Key{char.upper()}'
							elif char.isdigit():
								key = char
								code = f'Digit{char}'
							else:
								key = char
								code = char

							# Send keyDown
							keydown_params = {'type': 'keyDown', 'key': key, 'code': code, 'modifiers': 0}
							# Include text for regular characters, and '\r' for Enter
							if char == '\n':
								keydown_params['text'] = '\r'
							else:
								keydown_params['text'] = char
							await cdp_client.send.Input.dispatchKeyEvent(params=keydown_params, session_id=session_id)  # type: ignore[arg-type]

							# Send keyUp
							await cdp_client.send.Input.dispatchKeyEvent(
								params={
									'type': 'keyUp',
									'key': key,
									'code': code,
									'modifiers': 0,
								},
								session_id=session_id,
							)
						# We've handled all characters, return early
						msg = f'⌨️  Sent keys: {params.keys}'
						logger.info(msg)
						return ActionResult(
							extracted_content=msg, include_in_memory=True, long_term_memory=f'Sent keys: {params.keys}'
						)

				# If we get here, it's a special key or shortcut
				if is_special_key:
					# Determine key and code values
					if main_key == ' ':
						key = ' '
						code = 'Space'
					elif len(main_key) == 1:
						# Single character with modifier
						key = main_key
						code = (
							f'Key{main_key.upper()}'
							if main_key.isalpha()
							else f'Digit{main_key}'
							if main_key.isdigit()
							else main_key
						)
					else:
						# Multi-character keys like Enter, Escape, F1, etc.
						key = main_key
						code = main_key

					# Send keyDown event
					keydown_params = {
						'type': 'keyDown',
						'key': key,
						'code': code,
						'modifiers': modifiers,
					}
					# Only include text for single character keys without modifiers
					if len(key) == 1 and modifiers == 0:
						keydown_params['text'] = key

					# Add commands for common keyboard shortcuts
					if modifiers > 0 and len(key) == 1:
						# Check for common shortcuts that need commands
						if key.lower() == 'a' and (modifiers & 2 or modifiers & 4):  # Ctrl+A or Cmd+A
							keydown_params['commands'] = ['selectAll']
						elif key.lower() == 'c' and (modifiers & 2 or modifiers & 4):  # Ctrl+C or Cmd+C
							keydown_params['commands'] = ['copy']
						elif key.lower() == 'v' and (modifiers & 2 or modifiers & 4):  # Ctrl+V or Cmd+V
							keydown_params['commands'] = ['paste']
						elif key.lower() == 'x' and (modifiers & 2 or modifiers & 4):  # Ctrl+X or Cmd+X
							keydown_params['commands'] = ['cut']
						elif key.lower() == 'z' and (modifiers & 2 or modifiers & 4):  # Ctrl+Z or Cmd+Z
							keydown_params['commands'] = ['undo']

					await cdp_client.send.Input.dispatchKeyEvent(params=keydown_params, session_id=session_id)  # type: ignore[arg-type]

					# Small delay for modifier key combinations
					if modifiers > 0:
						await asyncio.sleep(0.05)

					# Send keyUp event
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': key,
							'code': code,
							'modifiers': modifiers,
						},
						session_id=session_id,
					)

			except Exception as e:
				# Fallback to playwright method if CDP fails
				logger.debug(f'CDP send_keys failed: {type(e).__name__}: {e}, falling back to browser method')
				page = await browser_session.get_current_page()
				try:
					await page.keyboard.press(params.keys)
				except Exception as e2:
					if 'Unknown key' in str(e2):
						# loop over the keys and try to send each one
						for key in params.keys:
							try:
								await page.keyboard.press(key)
							except Exception as e3:
								logger.debug(f'Error sending key {key}: {str(e3)}')
								raise e3
					else:
						raise e2

			msg = f'⌨️  Sent keys: {params.keys}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=f'Sent keys: {params.keys}')

		@self.registry.action(
			description='Scroll to a text in the current page',
		)
		async def scroll_to_text(text: str, browser_session: BrowserSession):  # type: ignore
			try:
				# Get CDP client and session
				cdp_client = await browser_session.get_cdp_client()
				session_id = await browser_session.get_current_page_cdp_session_id()

				# Enable DOM domain
				await cdp_client.send.DOM.enable(params={}, session_id=session_id)

				# Get the document and populate DOM tree
				doc = await cdp_client.send.DOM.getDocument(params={'depth': -1}, session_id=session_id)
				root_node_id = doc['root']['nodeId']

				# Request child nodes to ensure DOM is populated
				await cdp_client.send.DOM.requestChildNodes(params={'nodeId': root_node_id, 'depth': -1}, session_id=session_id)

				# Small delay to ensure DOM is fully populated
				await asyncio.sleep(0.1)

				# Try different search queries
				search_queries = [
					f'//*[contains(text(), "{text}")]',  # XPath search for direct text content
					f'//*[contains(., "{text}")]',  # XPath with . for all text content
					text,  # Plain text search as fallback
				]

				for query in search_queries:
					try:
						# Perform search
						search_result = await cdp_client.send.DOM.performSearch(
							params={'query': query, 'includeUserAgentShadowDOM': False}, session_id=session_id
						)

						logger.debug(f'CDP search for query "{query}" found {search_result["resultCount"]} results')

						if search_result['resultCount'] == 0:
							continue

						# Get search results
						results = await cdp_client.send.DOM.getSearchResults(
							params={
								'searchId': search_result['searchId'],
								'fromIndex': 0,
								'toIndex': min(search_result['resultCount'], 10),  # Check first 10 results
							},
							session_id=session_id,
						)

						# Get current scroll position to convert viewport coordinates to absolute
						scroll_result = await cdp_client.send.Runtime.evaluate(
							params={'expression': 'window.pageYOffset', 'returnByValue': True}, session_id=session_id
						)
						current_scroll_y = scroll_result.get('result', {}).get('value', 0)

						# Find the best matching node among all results
						best_node_id = None
						best_y_position = None

						for node_id in results['nodeIds']:
							if node_id == 0:  # Skip invalid node IDs
								logger.debug(f'Skipping invalid node ID: {node_id}')
								continue

							try:
								# Get node info to check if it's visible
								box_model = await cdp_client.send.DOM.getBoxModel(
									params={'nodeId': node_id}, session_id=session_id
								)

								# Check if element has dimensions
								if box_model.get('model') and box_model['model'].get('content'):
									# Get the element's position
									content_quad = box_model['model']['content']
									# Content quad is [x1,y1, x2,y1, x2,y2, x1,y2]
									viewport_y = content_quad[1]  # y1 coordinate (viewport relative)
									# Convert to absolute page coordinates
									element_y = viewport_y + current_scroll_y

									# For XPath queries, use the first valid match
									# For plain text queries, prefer elements lower on the page
									if query.startswith('//') or best_y_position is None:
										best_node_id = node_id
										best_y_position = element_y
										if query.startswith('//'):
											break  # Use first match for XPath
									elif element_y > best_y_position:
										# For plain text search, prefer elements further down
										best_node_id = node_id
										best_y_position = element_y

							except Exception as e:
								logger.debug(f'Failed to get box model for node {node_id}: {str(e)}')
								continue

						# Scroll to the best match if found
						if best_node_id and best_y_position is not None:
							# Scroll to the element using JavaScript
							scroll_target = max(0, best_y_position - 100)  # Ensure we don't scroll to negative
							logger.debug(f'Scrolling to Y position {scroll_target} (element at {best_y_position})')

							await cdp_client.send.Runtime.evaluate(
								params={
									'expression': f'window.scrollTo(0, {scroll_target})',  # Scroll with 100px offset from top
									'userGesture': True,
								},
								session_id=session_id,
							)
							await asyncio.sleep(0.5)  # Wait for scroll to complete

							# Discard search results to free memory
							await cdp_client.send.DOM.discardSearchResults(
								params={'searchId': search_result['searchId']}, session_id=session_id
							)

							msg = f'🔍  Scrolled to text: {text}'
							logger.info(msg)
							return ActionResult(
								extracted_content=msg,
								include_in_memory=True,
								long_term_memory=f'Scrolled to text: {text}',
							)

						# Discard search results if we didn't find a visible element
						await cdp_client.send.DOM.discardSearchResults(
							params={'searchId': search_result['searchId']}, session_id=session_id
						)

					except Exception as e:
						logger.debug(f'CDP search with query "{query}" failed: {str(e)}')
						continue

				# If CDP fails, fallback to playwright
				logger.debug('CDP scroll_to_text failed, falling back to playwright')
				page = await browser_session.get_current_page()

				# Try different locator strategies
				locators = [
					page.get_by_text(text, exact=False),
					page.locator(f'text={text}'),
					page.locator(f"//*[contains(text(), '{text}')]"),
				]

				for locator in locators:
					try:
						if await locator.count() == 0:
							continue

						element = locator.first
						is_visible = await element.is_visible()
						bbox = await element.bounding_box()

						if is_visible and bbox is not None and bbox['width'] > 0 and bbox['height'] > 0:
							await element.scroll_into_view_if_needed()
							await asyncio.sleep(0.5)  # Wait for scroll to complete
							msg = f'🔍  Scrolled to text: {text}'
							logger.info(msg)
							return ActionResult(
								extracted_content=msg, include_in_memory=True, long_term_memory=f'Scrolled to text: {text}'
							)

					except Exception as e:
						logger.debug(f'Locator attempt failed: {str(e)}')
						continue

				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					long_term_memory=f"Tried scrolling to text '{text}' but it was not found",
				)

			except Exception as e:
				msg = f"Failed to scroll to text '{text}': {str(e)}"
				logger.error(msg)
				raise BrowserError(msg)

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

		@self.registry.action(
			description='Get all options from a native dropdown',
		)
		async def get_dropdown_options(index: int, browser_session: BrowserSession) -> ActionResult:
			"""Get all options from a native dropdown"""
			page = await browser_session.get_current_page()
			selector_map = await browser_session.get_selector_map()
			dom_element = selector_map[index]

			try:
				# Frame-aware approach since we know it works
				all_options = []
				frame_index = 0

				for frame in page.frames:
					try:
						options = await frame.evaluate(
							"""
							(xpath) => {
								const select = document.evaluate(xpath, document, null,
									XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
								if (!select) return null;

								return {
									options: Array.from(select.options).map(opt => ({
										text: opt.text, //do not trim, because we are doing exact match in select_dropdown_option
										value: opt.value,
										index: opt.index
									})),
									id: select.id,
									name: select.name
								};
							}
						""",
							dom_element.xpath,
						)

						if options:
							logger.debug(f'Found dropdown in frame {frame_index}')
							logger.debug(f'Dropdown ID: {options["id"]}, Name: {options["name"]}')

							formatted_options = []
							for opt in options['options']:
								# encoding ensures AI uses the exact string in select_dropdown_option
								encoded_text = json.dumps(opt['text'])
								formatted_options.append(f'{opt["index"]}: text={encoded_text}')

							all_options.extend(formatted_options)

					except Exception as frame_e:
						logger.debug(f'Frame {frame_index} evaluation failed: {str(frame_e)}')

					frame_index += 1

				if all_options:
					msg = '\n'.join(all_options)
					msg += '\nUse the exact text string in select_dropdown_option'
					logger.info(msg)
					return ActionResult(
						extracted_content=msg,
						include_in_memory=True,
						long_term_memory=f'Found dropdown options for index {index}.',
						include_extracted_content_only_once=True,
					)
				else:
					msg = 'No options found in any frame for dropdown'
					logger.info(msg)
					return ActionResult(
						extracted_content=msg, include_in_memory=True, long_term_memory='No dropdown options found'
					)

			except Exception as e:
				logger.error(f'Failed to get dropdown options: {str(e)}')
				msg = f'Error getting options: {str(e)}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			description='Select dropdown option for interactive element index by the text of the option you want to select',
		)
		async def select_dropdown_option(
			index: int,
			text: str,
			browser_session: BrowserSession,
		) -> ActionResult:
			"""Select dropdown option by the text of the option you want to select"""
			page = await browser_session.get_current_page()
			selector_map = await browser_session.get_selector_map()
			dom_element = selector_map[index]

			# Validate that we're working with a select element
			if dom_element.tag_name != 'select':
				logger.error(f'Element is not a select! Tag: {dom_element.tag_name}, Attributes: {dom_element.attributes}')
				msg = f'Cannot select option: Element with index {index} is a {dom_element.tag_name}, not a select'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			logger.debug(f"Attempting to select '{text}' using xpath: {dom_element.xpath}")
			logger.debug(f'Element attributes: {dom_element.attributes}')
			logger.debug(f'Element tag: {dom_element.tag_name}')

			xpath = '//' + dom_element.xpath

			try:
				frame_index = 0
				for frame in page.frames:
					try:
						logger.debug(f'Trying frame {frame_index} URL: {frame.url}')

						# First verify we can find the dropdown in this frame
						find_dropdown_js = """
							(xpath) => {
								try {
									const select = document.evaluate(xpath, document, null,
										XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
									if (!select) return null;
									if (select.tagName.toLowerCase() !== 'select') {
										return {
											error: `Found element but it's a ${select.tagName}, not a SELECT`,
											found: false
										};
									}
									return {
										id: select.id,
										name: select.name,
										found: true,
										tagName: select.tagName,
										optionCount: select.options.length,
										currentValue: select.value,
										availableOptions: Array.from(select.options).map(o => o.text.trim())
									};
								} catch (e) {
									return {error: e.toString(), found: false};
								}
							}
						"""

						dropdown_info = await frame.evaluate(find_dropdown_js, dom_element.xpath)

						if dropdown_info:
							if not dropdown_info.get('found'):
								logger.error(f'Frame {frame_index} error: {dropdown_info.get("error")}')
								continue

							logger.debug(f'Found dropdown in frame {frame_index}: {dropdown_info}')

							# "label" because we are selecting by text
							# nth(0) to disable error thrown by strict mode
							# timeout=1000 because we are already waiting for all network events, therefore ideally we don't need to wait a lot here (default 30s)
							selected_option_values = (
								await frame.locator('//' + dom_element.xpath).nth(0).select_option(label=text, timeout=1000)
							)

							msg = f'selected option {text} with value {selected_option_values}'
							logger.info(msg + f' in frame {frame_index}')

							return ActionResult(
								extracted_content=msg, include_in_memory=True, long_term_memory=f"Selected option '{text}'"
							)

					except Exception as frame_e:
						logger.error(f'Frame {frame_index} attempt failed: {str(frame_e)}')
						logger.error(f'Frame type: {type(frame)}')
						logger.error(f'Frame URL: {frame.url}')

					frame_index += 1

				msg = f"Could not select option '{text}' in any frame"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			except Exception as e:
				msg = f'Selection failed: {str(e)}'
				logger.error(msg)
				raise BrowserError(msg)

		@self.registry.action('Google Sheets: Get the contents of the entire sheet', domains=['https://docs.google.com'])
		async def read_sheet_contents(page: Page):
			# select all cells
			await page.keyboard.press('Enter')
			await page.keyboard.press('Escape')
			await page.keyboard.press('ControlOrMeta+A')
			await page.keyboard.press('ControlOrMeta+C')

			extracted_tsv = await page.evaluate('() => navigator.clipboard.readText()')
			return ActionResult(
				extracted_content=extracted_tsv,
				include_in_memory=True,
				long_term_memory='Retrieved sheet contents',
				include_extracted_content_only_once=True,
			)

		@self.registry.action('Google Sheets: Get the contents of a cell or range of cells', domains=['https://docs.google.com'])
		async def read_cell_contents(cell_or_range: str, browser_session: BrowserSession):
			page = await browser_session.get_current_page()

			await select_cell_or_range(cell_or_range=cell_or_range, page=page)

			await page.keyboard.press('ControlOrMeta+C')
			await asyncio.sleep(0.1)
			extracted_tsv = await page.evaluate('() => navigator.clipboard.readText()')
			return ActionResult(
				extracted_content=extracted_tsv,
				include_in_memory=True,
				long_term_memory=f'Retrieved contents from {cell_or_range}',
				include_extracted_content_only_once=True,
			)

		@self.registry.action(
			'Google Sheets: Update the content of a cell or range of cells', domains=['https://docs.google.com']
		)
		async def update_cell_contents(cell_or_range: str, new_contents_tsv: str, browser_session: BrowserSession):
			page = await browser_session.get_current_page()

			await select_cell_or_range(cell_or_range=cell_or_range, page=page)

			# simulate paste event from clipboard with TSV content
			await page.evaluate(f"""
				const clipboardData = new DataTransfer();
				clipboardData.setData('text/plain', `{new_contents_tsv}`);
				document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData}}));
			""")

			return ActionResult(
				extracted_content=f'Updated cells: {cell_or_range} = {new_contents_tsv}',
				include_in_memory=False,
				long_term_memory=f'Updated cells {cell_or_range} with {new_contents_tsv}',
			)

		@self.registry.action('Google Sheets: Clear whatever cells are currently selected', domains=['https://docs.google.com'])
		async def clear_cell_contents(cell_or_range: str, browser_session: BrowserSession):
			page = await browser_session.get_current_page()

			await select_cell_or_range(cell_or_range=cell_or_range, page=page)

			await page.keyboard.press('Backspace')
			return ActionResult(
				extracted_content=f'Cleared cells: {cell_or_range}',
				include_in_memory=False,
				long_term_memory=f'Cleared cells {cell_or_range}',
			)

		@self.registry.action('Google Sheets: Select a specific cell or range of cells', domains=['https://docs.google.com'])
		async def select_cell_or_range(cell_or_range: str, page: Page):
			await page.keyboard.press('Enter')  # make sure we dont delete current cell contents if we were last editing
			await page.keyboard.press('Escape')  # to clear current focus (otherwise select range popup is additive)
			await asyncio.sleep(0.1)
			await page.keyboard.press('Home')  # move cursor to the top left of the sheet first
			await page.keyboard.press('ArrowUp')
			await asyncio.sleep(0.1)
			await page.keyboard.press('Control+G')  # open the goto range popup
			await asyncio.sleep(0.2)
			await page.keyboard.type(cell_or_range, delay=0.05)
			await asyncio.sleep(0.2)
			await page.keyboard.press('Enter')
			await asyncio.sleep(0.2)
			await page.keyboard.press('Escape')  # to make sure the popup still closes in the case where the jump failed
			return ActionResult(
				extracted_content=f'Selected cells: {cell_or_range}',
				include_in_memory=False,
				long_term_memory=f'Selected cells {cell_or_range}',
			)

		@self.registry.action(
			'Google Sheets: Fallback method to type text into (only one) currently selected cell',
			domains=['https://docs.google.com'],
		)
		async def fallback_input_into_single_selected_cell(text: str, page: Page):
			await page.keyboard.type(text, delay=0.1)
			await page.keyboard.press('Enter')  # make sure to commit the input so it doesn't get overwritten by the next action
			await page.keyboard.press('ArrowUp')
			return ActionResult(
				extracted_content=f'Inputted text {text}',
				include_in_memory=False,
				long_term_memory=f"Inputted text '{text}' into cell",
			)

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
