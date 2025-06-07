import asyncio
import enum
import json
import logging
import re
from typing import Generic, TypeVar, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from playwright.async_api import ElementHandle, Page

# from lmnr.sdk.laminar import Laminar
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	DragDropAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	OpenTabAction,
	Position,
	ScrollAction,
	SearchGoogleAction,
	SendKeysAction,
	SwitchTabAction,
)
from browser_use.filesystem.file_system import FileSystem
from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)


Context = TypeVar('Context')


class Controller(Generic[Context]):
	def __init__(
		self,
		exclude_actions: list[str] = [],
		output_model: type[BaseModel] | None = None,
	):
		self.registry = Registry[Context](exclude_actions)

		"""Register all default browser actions"""

		if output_model is not None:
			# Create a new model that extends the output model with success parameter
			class ExtendedOutputModel(BaseModel):  # type: ignore
				success: bool = True
				data: output_model  # type: ignore

			@self.registry.action(
				'Complete task - with return text and if the task is finished (success=True) or not yet completely finished (success=False), because last step is reached',
				param_model=ExtendedOutputModel,
			)
			async def done(params: ExtendedOutputModel):
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
					memory=f'Task completed. Success Status: {params.success}',
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

				if params.files_to_display:
					user_message += '\n\nBelow are the files I saved for you:'
					for file_name in params.files_to_display:
						if file_name == 'todo.md':
							continue
						file_content = file_system.display_file(file_name)
						if file_content:
							user_message += f'\n\n{file_name}:\n{file_content}'

				return ActionResult(is_done=True, success=params.success, extracted_content=user_message, memory=memory)

		# Basic Navigation Actions
		@self.registry.action(
			'Search the query in Google, the query should be a search query like humans search in Google, concrete and not vague or super long.',
			param_model=SearchGoogleAction,
		)
		async def search_google(params: SearchGoogleAction, browser_session: BrowserSession):
			search_url = f'https://www.google.com/search?q={params.query}&udm=14'

			page = await browser_session.get_current_page()
			if page.url in ('about:blank', 'https://www.google.com'):
				await page.goto(search_url)
				await page.wait_for_load_state()
			else:
				page = await browser_session.create_new_tab(search_url)

			msg = f'🔍  Searched for "{params.query}" in Google'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f"Searched Google for '{params.query}'")

		@self.registry.action('Navigate to URL in the current tab', param_model=GoToUrlAction)
		async def go_to_url(params: GoToUrlAction, browser_session: BrowserSession):
			page = await browser_session.get_current_page()
			if page:
				await page.goto(params.url)
				await page.wait_for_load_state()
			else:
				page = await browser_session.create_new_tab(params.url)
			msg = f'🔗  Navigated to {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Navigated to {params.url}')

		@self.registry.action('Go back', param_model=NoParamsAction)
		async def go_back(params: NoParamsAction, browser_session: BrowserSession):
			await browser_session.go_back()
			msg = '🔙  Navigated back'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory='Navigated back')

		# wait for x seconds
		@self.registry.action('Wait for x seconds default 3')
		async def wait(seconds: int = 3):
			msg = f'🕒  Waiting for {seconds} seconds'
			logger.info(msg)
			await asyncio.sleep(seconds)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Waited for {seconds} seconds')

		# Element Interaction Actions
		@self.registry.action('Click element by index', param_model=ClickElementAction)
		async def click_element_by_index(params: ClickElementAction, browser_session: BrowserSession):
			# Browser is now a BrowserSession itself

			if params.index not in await browser_session.get_selector_map():
				raise Exception(f'Element with index {params.index} does not exist - retry or use alternative actions')

			element_node = await browser_session.get_dom_element_by_index(params.index)
			initial_pages = len(browser_session.tabs)

			# if element has file uploader then dont click
			if await browser_session.find_file_upload_element_by_index(params.index) is not None:
				msg = f'Index {params.index} - has an element which opens file upload dialog. To upload files please use a specific function to upload files '
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Clicked element {params.index}')

			msg = None

			try:
				download_path = await browser_session._click_element_node(element_node)
				if download_path:
					msg = f'💾  Downloaded file to {download_path}'
				else:
					msg = f'🖱️  Clicked button with index {params.index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'

				logger.info(msg)
				logger.debug(f'Element xpath: {element_node.xpath}')
				if len(browser_session.tabs) > initial_pages:
					new_tab_msg = 'New tab opened - switching to it'
					msg += f' - {new_tab_msg}'
					logger.info(new_tab_msg)
					await browser_session.switch_to_tab(-1)
				return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Clicked element {params.index}')
			except Exception as e:
				logger.warning(f'Element not clickable with index {params.index} - most likely the page changed')
				return ActionResult(error=str(e))

		@self.registry.action(
			'Input text into a input interactive element',
			param_model=InputTextAction,
		)
		async def input_text(params: InputTextAction, browser_session: BrowserSession, has_sensitive_data: bool = False):
			if params.index not in await browser_session.get_selector_map():
				raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')

			element_node = await browser_session.get_dom_element_by_index(params.index)
			await browser_session._input_text_element_node(element_node, params.text)
			if not has_sensitive_data:
				msg = f'⌨️  Input {params.text} into index {params.index}'
			else:
				msg = f'⌨️  Input sensitive data into index {params.index}'
			logger.info(msg)
			logger.debug(f'Element xpath: {element_node.xpath}')
			return ActionResult(
				extracted_content=msg, include_in_memory=True, memory=f"Input '{params.text}' into element {params.index}."
			)

		# Save PDF
		@self.registry.action('Save the current page as a PDF file')
		async def save_pdf(page: Page):
			short_url = re.sub(r'^https?://(?:www\.)?|/$', '', page.url)
			slug = re.sub(r'[^a-zA-Z0-9]+', '-', short_url).strip('-').lower()
			sanitized_filename = f'{slug}.pdf'

			await page.emulate_media(media='screen')
			await page.pdf(path=sanitized_filename, format='A4', print_background=False)
			msg = f'Saving page with URL {page.url} as PDF to ./{sanitized_filename}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Saved PDF to {sanitized_filename}')

		# Tab Management Actions
		@self.registry.action('Switch tab', param_model=SwitchTabAction)
		async def switch_tab(params: SwitchTabAction, browser_session: BrowserSession):
			await browser_session.switch_to_tab(params.page_id)
			# Wait for tab to be ready and ensure references are synchronized
			page = await browser_session.get_current_page()
			await page.wait_for_load_state()
			msg = f'🔄  Switched to tab {params.page_id}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Switched to tab {params.page_id}')

		@self.registry.action('Open a specific url in new tab', param_model=OpenTabAction)
		async def open_tab(params: OpenTabAction, browser_session: BrowserSession):
			await browser_session.create_new_tab(params.url)
			msg = f'🔗  Opened new tab with {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Opened new tab with URL {params.url}')

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
				memory=f'Closed tab {params.page_id} with url {url}, now focused on tab {new_page_idx} with url {new_page.url}.',
			)

		# Content Actions
		@self.registry.action(
			'Extract specific information from the current webpage. Provide a clear, detailed description of what you want to extract in the "content_to_extract" field. Be extremely specific about the data you need. Set include_links=True if you need to preserve links.',
		)
		async def extract_content(
			content_to_extract: str,
			page: Page,
			page_extraction_llm: BaseChatModel,
			include_links: bool = False,
		):
			import markdownify

			strip = []
			if not include_links:
				strip = ['a', 'img']

			content = markdownify.markdownify(await page.content(), strip=strip)

			# manually append iframe text into the content so it's readable by the LLM (includes cross-origin iframes)
			for iframe in page.frames:
				if iframe.url != page.url and not iframe.url.startswith('data:'):
					content += f'\n\nIFRAME {iframe.url}:\n'
					content += markdownify.markdownify(await iframe.content())

			prompt = 'Extract information from this webpage based on the query. Focus only on content relevant to the query. If the query is vague, provide a brief summary of the page. Respond in JSON format.\nQuery: {content_to_extract}\nPage content:\n{page}'
			template = PromptTemplate(input_variables=['content_to_extract', 'page'], template=prompt)
			try:
				output = await page_extraction_llm.ainvoke(template.format(content_to_extract=content_to_extract, page=content))
				msg = f'📄  Extracted from page\n: {output.content}\n'
				logger.info(msg)
				return ActionResult(
					extracted_content=msg,
					include_in_memory=True,
					memory=f"Extracted '{content_to_extract}' from page",
					update_read_state=True,
				)
			except Exception as e:
				logger.debug(f'Error extracting content: {e}')
				msg = f'📄  Extracted from page\n: {content}\n'
				logger.info(msg)
				return ActionResult(extracted_content=msg)

		@self.registry.action(
			'Get the accessibility tree of the page in the format "role name" with the number_of_elements to return',
		)
		async def get_ax_tree(number_of_elements: int, page: Page):
			node = await page.accessibility.snapshot(interesting_only=True)

			def flatten_ax_tree(node, lines):
				if not node:
					return
				role = node.get('role', '')
				name = node.get('name', '')
				lines.append(f'{role} {name}')
				for child in node.get('children', []):
					flatten_ax_tree(child, lines)

			lines = []
			flatten_ax_tree(node, lines)
			msg = '\n'.join(lines)
			logger.info(msg)
			return ActionResult(
				extracted_content=msg, include_in_memory=False, memory='Retrieved accessibility tree', update_read_state=True
			)

		@self.registry.action(
			'Scroll down the page by pixel amount - if none is given, scroll one page',
			param_model=ScrollAction,
		)
		async def scroll_down(params: ScrollAction, browser_session: BrowserSession):
			"""
			(a) Use browser._scroll_container for container-aware scrolling.
			(b) If that JavaScript throws, fall back to window.scrollBy().
			"""
			page = await browser_session.get_current_page()
			dy = params.amount or await page.evaluate('() => window.innerHeight')

			try:
				await browser_session._scroll_container(dy)
			except Exception as e:
				# Hard fallback: always works on root scroller
				await page.evaluate('(y) => window.scrollBy(0, y)', dy)
				logger.debug('Smart scroll failed; used window.scrollBy fallback', exc_info=e)

			amount_str = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍 Scrolled down the page by {amount_str}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Scrolled down the page by {amount_str}')

		@self.registry.action(
			'Scroll up the page by pixel amount - if none is given, scroll one page',
			param_model=ScrollAction,
		)
		async def scroll_up(params: ScrollAction, browser_session: BrowserSession):
			page = await browser_session.get_current_page()
			dy = -(params.amount or await page.evaluate('() => window.innerHeight'))

			try:
				await browser_session._scroll_container(dy)
			except Exception as e:
				await page.evaluate('(y) => window.scrollBy(0, y)', dy)
				logger.debug('Smart scroll failed; used window.scrollBy fallback', exc_info=e)

			amount_str = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍 Scrolled up the page by {amount_str}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Scrolled up the page by{amount_str}')

		# send keys
		@self.registry.action(
			'Send strings of special keys like Escape,Backspace, Insert, PageDown, Delete, Enter, Shortcuts such as `Control+o`, `Control+Shift+T` are supported as well. This gets used in keyboard.press. ',
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
			return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Sent keys: {params.keys}')

		@self.registry.action(
			description='If you dont find something which you want to interact with, scroll to it',
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
							return ActionResult(extracted_content=msg, include_in_memory=True, memory=f'Scrolled to text: {text}')

					except Exception as e:
						logger.debug(f'Locator attempt failed: {str(e)}')
						continue

				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(
					extracted_content=msg, include_in_memory=True, memory=f"Tried scrolling to text '{text}' but it was not found"
				)

			except Exception as e:
				msg = f"Failed to scroll to text '{text}': {str(e)}"
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

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
						memory=f'Found dropdown options for index {index}.',
						update_read_state=True,
					)
				else:
					msg = 'No options found in any frame for dropdown'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True, memory='No dropdown options found')

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
				return ActionResult(extracted_content=msg, include_in_memory=True, memory=msg)

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

							return ActionResult(extracted_content=msg, include_in_memory=True, memory=f"Selected option '{text}'")

					except Exception as frame_e:
						logger.error(f'Frame {frame_index} attempt failed: {str(frame_e)}')
						logger.error(f'Frame type: {type(frame)}')
						logger.error(f'Frame URL: {frame.url}')

					frame_index += 1

				msg = f"Could not select option '{text}' in any frame"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, memory=msg)

			except Exception as e:
				msg = f'Selection failed: {str(e)}'
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

		@self.registry.action(
			'Drag and drop elements or between coordinates on the page - useful for canvas drawing, sortable lists, sliders, file uploads, and UI rearrangement',
			param_model=DragDropAction,
		)
		async def drag_drop(params: DragDropAction, page: Page) -> ActionResult:
			"""
			Performs a precise drag and drop operation between elements or coordinates.
			"""

			async def get_drag_elements(
				page: Page,
				source_selector: str,
				target_selector: str,
			) -> tuple[ElementHandle | None, ElementHandle | None]:
				"""Get source and target elements with appropriate error handling."""
				source_element = None
				target_element = None

				try:
					# page.locator() auto-detects CSS and XPath
					source_locator = page.locator(source_selector)
					target_locator = page.locator(target_selector)

					# Check if elements exist
					source_count = await source_locator.count()
					target_count = await target_locator.count()

					if source_count > 0:
						source_element = await source_locator.first.element_handle()
						logger.debug(f'Found source element with selector: {source_selector}')
					else:
						logger.warning(f'Source element not found: {source_selector}')

					if target_count > 0:
						target_element = await target_locator.first.element_handle()
						logger.debug(f'Found target element with selector: {target_selector}')
					else:
						logger.warning(f'Target element not found: {target_selector}')

				except Exception as e:
					logger.error(f'Error finding elements: {str(e)}')

				return source_element, target_element

			async def get_element_coordinates(
				source_element: ElementHandle,
				target_element: ElementHandle,
				source_position: Position | None,
				target_position: Position | None,
			) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
				"""Get coordinates from elements with appropriate error handling."""
				source_coords = None
				target_coords = None

				try:
					# Get source coordinates
					if source_position:
						source_coords = (source_position.x, source_position.y)
					else:
						source_box = await source_element.bounding_box()
						if source_box:
							source_coords = (
								int(source_box['x'] + source_box['width'] / 2),
								int(source_box['y'] + source_box['height'] / 2),
							)

					# Get target coordinates
					if target_position:
						target_coords = (target_position.x, target_position.y)
					else:
						target_box = await target_element.bounding_box()
						if target_box:
							target_coords = (
								int(target_box['x'] + target_box['width'] / 2),
								int(target_box['y'] + target_box['height'] / 2),
							)
				except Exception as e:
					logger.error(f'Error getting element coordinates: {str(e)}')

				return source_coords, target_coords

			async def execute_drag_operation(
				page: Page,
				source_x: int,
				source_y: int,
				target_x: int,
				target_y: int,
				steps: int,
				delay_ms: int,
			) -> tuple[bool, str]:
				"""Execute the drag operation with comprehensive error handling."""
				try:
					# Try to move to source position
					try:
						await page.mouse.move(source_x, source_y)
						logger.debug(f'Moved to source position ({source_x}, {source_y})')
					except Exception as e:
						logger.error(f'Failed to move to source position: {str(e)}')
						return False, f'Failed to move to source position: {str(e)}'

					# Press mouse button down
					await page.mouse.down()

					# Move to target position with intermediate steps
					for i in range(1, steps + 1):
						ratio = i / steps
						intermediate_x = int(source_x + (target_x - source_x) * ratio)
						intermediate_y = int(source_y + (target_y - source_y) * ratio)

						await page.mouse.move(intermediate_x, intermediate_y)

						if delay_ms > 0:
							await asyncio.sleep(delay_ms / 1000)

					# Move to final target position
					await page.mouse.move(target_x, target_y)

					# Move again to ensure dragover events are properly triggered
					await page.mouse.move(target_x, target_y)

					# Release mouse button
					await page.mouse.up()

					return True, 'Drag operation completed successfully'

				except Exception as e:
					return False, f'Error during drag operation: {str(e)}'

			try:
				# Initialize variables
				source_x: int | None = None
				source_y: int | None = None
				target_x: int | None = None
				target_y: int | None = None

				# Normalize parameters
				steps = max(1, params.steps or 10)
				delay_ms = max(0, params.delay_ms or 5)

				# Case 1: Element selectors provided
				if params.element_source and params.element_target:
					logger.debug('Using element-based approach with selectors')

					source_element, target_element = await get_drag_elements(
						page,
						params.element_source,
						params.element_target,
					)

					if not source_element or not target_element:
						error_msg = f'Failed to find {"source" if not source_element else "target"} element'
						return ActionResult(error=error_msg, include_in_memory=True)

					source_coords, target_coords = await get_element_coordinates(
						source_element, target_element, params.element_source_offset, params.element_target_offset
					)

					if not source_coords or not target_coords:
						error_msg = f'Failed to determine {"source" if not source_coords else "target"} coordinates'
						return ActionResult(error=error_msg, include_in_memory=True)

					source_x, source_y = source_coords
					target_x, target_y = target_coords

				# Case 2: Coordinates provided directly
				elif all(
					coord is not None
					for coord in [params.coord_source_x, params.coord_source_y, params.coord_target_x, params.coord_target_y]
				):
					logger.debug('Using coordinate-based approach')
					source_x = params.coord_source_x
					source_y = params.coord_source_y
					target_x = params.coord_target_x
					target_y = params.coord_target_y
				else:
					error_msg = 'Must provide either source/target selectors or source/target coordinates'
					return ActionResult(error=error_msg, include_in_memory=True)

				# Validate coordinates
				if any(coord is None for coord in [source_x, source_y, target_x, target_y]):
					error_msg = 'Failed to determine source or target coordinates'
					return ActionResult(error=error_msg, include_in_memory=True)

				# Perform the drag operation
				success, message = await execute_drag_operation(
					page,
					cast(int, source_x),
					cast(int, source_y),
					cast(int, target_x),
					cast(int, target_y),
					steps,
					delay_ms,
				)

				if not success:
					logger.error(f'Drag operation failed: {message}')
					return ActionResult(error=message, include_in_memory=True)

				# Create descriptive message
				if params.element_source and params.element_target:
					msg = f"🖱️ Dragged element '{params.element_source}' to '{params.element_target}'"
				else:
					msg = f'🖱️ Dragged from ({source_x}, {source_y}) to ({target_x}, {target_y})'

				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True, memory=msg)

			except Exception as e:
				error_msg = f'Failed to perform drag and drop: {str(e)}'
				logger.error(error_msg)
				return ActionResult(error=error_msg, include_in_memory=True)

		@self.registry.action('Google Sheets: Get the contents of the entire sheet', domains=['https://docs.google.com'])
		async def read_sheet_contents(page: Page):
			# select all cells
			await page.keyboard.press('Enter')
			await page.keyboard.press('Escape')
			await page.keyboard.press('ControlOrMeta+A')
			await page.keyboard.press('ControlOrMeta+C')

			extracted_tsv = await page.evaluate('() => navigator.clipboard.readText()')
			return ActionResult(
				extracted_content=extracted_tsv, include_in_memory=True, memory='Retrieved sheet contents', update_read_state=True
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
				memory=f'Retrieved contents from {cell_or_range}',
				update_read_state=True,
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
				memory=f'Updated cells {cell_or_range} with {new_contents_tsv}',
			)

		@self.registry.action('Google Sheets: Clear whatever cells are currently selected', domains=['https://docs.google.com'])
		async def clear_cell_contents(cell_or_range: str, browser_session: BrowserSession):
			page = await browser_session.get_current_page()

			await select_cell_or_range(cell_or_range=cell_or_range, page=page)

			await page.keyboard.press('Backspace')
			return ActionResult(
				extracted_content=f'Cleared cells: {cell_or_range}',
				include_in_memory=False,
				memory=f'Cleared cells {cell_or_range}',
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
				memory=f'Selected cells {cell_or_range}',
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
				extracted_content=f'Inputted text {text}', include_in_memory=False, memory=f"Inputted text '{text}' into cell"
			)

	# Register ---------------------------------------------------------------

	def action(self, description: str, **kwargs):
		"""Decorator for registering custom actions

		@param description: Describe the LLM what the function does (better description == better function calling)
		"""
		return self.registry.action(description, **kwargs)

	# Act --------------------------------------------------------------------

	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_session: BrowserSession,
		#
		page_extraction_llm: BaseChatModel | None = None,
		sensitive_data: dict[str, str] | None = None,
		available_file_paths: list[str] | None = None,
		file_system: FileSystem | None = None,
		#
		context: Context | None = None,
	) -> ActionResult:
		"""Execute an action"""

		for action_name, params in action.model_dump(exclude_unset=True).items():
			if params is not None:
				# with Laminar.start_as_current_span(
				# 	name=action_name,
				# 	input={
				# 		'action': action_name,
				# 		'params': params,
				# 	},
				# 	span_type='TOOL',
				# ):
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

				# Laminar.set_span_output(result)

				if isinstance(result, str):
					return ActionResult(extracted_content=result)
				elif isinstance(result, ActionResult):
					return result
				elif result is None:
					return ActionResult()
				else:
					raise ValueError(f'Invalid action result type: {type(result)} of {result}')
		return ActionResult()
