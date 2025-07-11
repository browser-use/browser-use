import asyncio
import base64
import enum
import json
import logging
import os
import re
from io import BytesIO
from typing import Generic, TypeVar, cast

try:
	from lmnr import Laminar  # type: ignore
except ImportError:
	Laminar = None  # type: ignore

try:
	from openai import AsyncOpenAI  # type: ignore
except ImportError:
	AsyncOpenAI = None  # type: ignore

try:
	from PIL import Image  # type: ignore
except ImportError:
	Image = None  # type: ignore

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
	OpenAICUAAction,
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


async def handle_model_action(page, action) -> ActionResult:
	"""
	Given a computer action (e.g., click, double_click, scroll, etc.),
	execute the corresponding operation on the Playwright page.
	"""
	action_type = action.type
	ERROR_MSG: str = 'Could not execute the CUA action.'

	try:
		match action_type:
			case 'click':
				x, y = action.x, action.y
				button = action.button
				logger.debug(f"CUA Action: click at ({x}, {y}) with button '{button}'")
				# Not handling things like middle click, etc.
				if button != 'left' and button != 'right':
					button = 'left'
				await page.mouse.click(x, y, button=button)
				msg = f'🖱️ CUA clicked at ({x}, {y}) with button {button}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'scroll':
				x, y = action.x, action.y
				scroll_x, scroll_y = action.scroll_x, action.scroll_y
				logger.debug(f'CUA Action: scroll at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})')
				await page.mouse.move(x, y)
				await page.evaluate(f'window.scrollBy({scroll_x}, {scroll_y})')
				msg = f'🔍 CUA scrolled at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'keypress':
				keys = action.keys
				for k in keys:
					logger.debug(f"CUA Action: keypress '{k}'")
					# A simple mapping for common keys; expand as needed.
					if k.lower() == 'enter':
						await page.keyboard.press('Enter')
					elif k.lower() == 'space':
						await page.keyboard.press(' ')
					else:
						await page.keyboard.press(k)
				msg = f'⌨️ CUA pressed keys: {keys}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'type':
				text = action.text
				logger.debug(f'CUA Action: type text: {text}')
				await page.keyboard.type(text)
				msg = f'⌨️ CUA typed text: {text}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'wait':
				logger.debug('CUA Action: wait')
				await asyncio.sleep(2)
				msg = '🕒 CUA waited for 2 seconds'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'screenshot':
				# Nothing to do as screenshot is taken at each turn
				logger.debug('CUA Action: screenshot')
				return ActionResult(error=ERROR_MSG)
			# Handle other actions here

			case _:
				logger.warning(f'Unrecognized CUA action: {action}')
				return ActionResult(error=ERROR_MSG)

	except Exception as e:
		logger.error(f'Error handling CUA action {action}: {e}')
		return ActionResult(error=ERROR_MSG)


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
		async def go_back(_: NoParamsAction, browser_session: BrowserSession):
			await browser_session.go_back()
			msg = '🔙  Navigated back'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory='Navigated back')

		# wait for x seconds

		@self.registry.action('Wait for x seconds default 3')
		async def wait(seconds: int = 3):
			msg = f'🕒  Waiting for {seconds} seconds'
			logger.info(msg)
			await asyncio.sleep(seconds)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=f'Waited for {seconds} seconds')

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
				download_path = await browser_session._click_element_node(element_node)
				if download_path:
					emoji = '💾'
					msg = f'Downloaded file to {download_path}'
				else:
					emoji = '🖱️'
					msg = f'Clicked button with index {params.index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'

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
			await browser_session.switch_to_tab(params.page_id)
			page = await browser_session.get_current_page()
			try:
				await page.wait_for_load_state(state='domcontentloaded', timeout=5_000)
				# page was already loaded when we first navigated, this is additional to wait for onfocus/onblur animations/ajax to settle
			except Exception as e:
				pass
			msg = f'🔄  Switched to tab #{params.page_id} with url {page.url}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg, include_in_memory=True, long_term_memory=f'Switched to tab {params.page_id}'
			)

		@self.registry.action('Close an existing tab', param_model=CloseTabAction)
		async def close_tab(params: CloseTabAction, browser_session: BrowserSession):
			await browser_session.switch_to_tab(params.page_id)
			page = await browser_session.get_current_page()
			url = page.url
			await page.close()
			new_page = await browser_session.get_current_page()
			new_page_idx = browser_session.tabs.index(new_page)
			msg = f'❌  Closed tab #{params.page_id} with {url}, now focused on tab #{new_page_idx} with url {new_page.url}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
				long_term_memory=f'Closed tab {params.page_id} with url {url}, now focused on tab {new_page_idx} with url {new_page.url}.',
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
		async def send_keys(params: SendKeysAction, page: Page):
			try:
				await page.keyboard.press(params.keys)
			except Exception as e:
				if 'Unknown key' in str(e):
					# loop over the keys and try to send each one
					for key in params.keys:
						try:
							await page.keyboard.press(key)
						except Exception as e:
							logger.debug(f'Error sending key {key}: {str(e)}')
							raise e
				else:
					raise e
			msg = f'⌨️  Sent keys: {params.keys}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=f'Sent keys: {params.keys}')

		@self.registry.action(
			description='Scroll to a text in the current page',
		)
		async def scroll_to_text(text: str, page: Page):  # type: ignore
			try:
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
			'Write content to file_name in file system. Allowed extensions are .md, .txt, .json, .csv, .pdf. For .pdf files, write the content in markdown format and it will automatically be converted to a properly formatted PDF document.'
		)
		async def write_file(file_name: str, content: str, file_system: FileSystem):
			result = await file_system.write_file(file_name, content)
			logger.info(f'💾 {result}')
			return ActionResult(extracted_content=result, include_in_memory=True, long_term_memory=result)

		@self.registry.action('Append content to file_name in file system')
		async def append_file(file_name: str, content: str, file_system: FileSystem):
			result = await file_system.append_file(file_name, content)
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

		# OpenAI Computer Use Assistant (CUA) Action
		@self.registry.action(
			'Use a Computer Use Assistant (CUA) to execute action that you cannot achieve with standard browser actions. This action sends a screenshot and description to OpenAI CUA and executes the returned actions such as clicking or scrolling on a coordinate. Use this only as a fallback.',
			param_model=OpenAICUAAction,
		)
		async def openai_cua_fallback(params: OpenAICUAAction, browser_session: BrowserSession):
			"""
			Fallback action that uses OpenAI's Computer Use Assistant to perform complex
			computer interactions when standard browser actions are insufficient.
			"""
			logger.info(f'🎯 CUA Action Starting - Goal: {params.description}')

			# Check if required dependencies are available
			if AsyncOpenAI is None:
				error_msg = 'OpenAI library not available. Install with: pip install openai'
				logger.error(error_msg)
				return ActionResult(error=error_msg)

			if Image is None:
				error_msg = 'PIL library not available. Install with: pip install Pillow'
				logger.error(error_msg)
				return ActionResult(error=error_msg)

			# Check if OpenAI API key is available
			if not os.getenv('OPENAI_API_KEY'):
				error_msg = 'OPENAI_API_KEY environment variable not set'
				logger.error(error_msg)
				return ActionResult(error=error_msg)

			try:
				page = await browser_session.get_current_page()
				page_info = browser_session.browser_state_summary.page_info
				if not page_info:
					raise Exception('Page info not found - cannot execute CUA action')

				logger.debug(f'📐 Viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

				screenshot_b64 = browser_session.browser_state_summary.screenshot
				if not screenshot_b64:
					raise Exception('Screenshot not found - cannot execute CUA action')

				logger.debug(f'📸 Screenshot captured (base64 length: {len(screenshot_b64)} chars)')

				# Debug: Check screenshot dimensions
				image = Image.open(BytesIO(base64.b64decode(screenshot_b64)))
				logger.debug(f'📏 Screenshot actual dimensions: {image.size[0]}x{image.size[1]}')

				# rescale the screenshot to the viewport size
				image = image.resize((page_info.viewport_width, page_info.viewport_height))
				# Save as PNG to bytes buffer
				buffer = BytesIO()
				image.save(buffer, format='PNG')
				buffer.seek(0)
				# Convert to base64
				screenshot_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
				logger.debug(f'📸 Rescaled screenshot to viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

				client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
				logger.debug('🔄 Sending request to OpenAI CUA...')

				prompt = f"""
				You will be given an action to execute and screenshot of the current screen. 
				Output one computer_call object that will achieve this goal.
				Goal: {params.description}
				"""
				response = await client.responses.create(
					model='computer-use-preview',
					tools=[
						{
							'type': 'computer_use_preview',
							'display_width': page_info.viewport_width,
							'display_height': page_info.viewport_height,
							'environment': 'browser',
						}
					],
					input=[
						{
							'role': 'user',
							'content': [
								{'type': 'input_text', 'text': prompt},
								{
									'type': 'input_image',
									'detail': 'auto',
									'image_url': f'data:image/png;base64,{screenshot_b64}',
								},
							],
						}
					],
					truncation='auto',
					temperature=0.1,
				)

				logger.debug(f'📥 CUA response received: {response}')
				computer_calls = [item for item in response.output if item.type == 'computer_call']
				computer_call = computer_calls[0] if computer_calls else None
				if not computer_call:
					raise Exception('No computer calls found in CUA response')

				action = computer_call.action
				logger.debug(f'🎬 Executing CUA action: {action.type} - {action}')

				action_result = await handle_model_action(page, action)
				await asyncio.sleep(0.1)

				logger.info('✅ CUA action completed successfully')
				return action_result

			except Exception as e:
				msg = f'Error executing CUA action: {e}'
				logger.error(msg)
				return ActionResult(error=msg)

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
	@observe_debug(name='act')
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
