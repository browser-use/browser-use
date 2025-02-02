import asyncio
import json
import logging
from typing import Callable, Dict, Optional, Type

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
	AddRowAction,
	ClickElementAction,
	DeleteRowAction,
	DoneAction,
	GoToUrlAction,
	InputTextAction,
	InsertFunctionAction,
	InsertValueAction,
	NoParamsAction,
	OpenGoogleSpreadsheetAction,
	OpenTabAction,
	ReadSpreadsheetAction,
	ScrollAction,
	SearchGoogleAction,
	SendKeysAction,
	SwitchTabAction,
)
from browser_use.utils import time_execution_async, time_execution_sync

logger = logging.getLogger(__name__)
from langchain_core.language_models.chat_models import BaseChatModel


class Controller:
	def __init__(
		self,
		exclude_actions: list[str] = [],
		output_model: Optional[Type[BaseModel]] = None,
	):
		self.exclude_actions = exclude_actions
		self.output_model = output_model
		self.registry = Registry(exclude_actions)
		self._register_default_actions()

	def _register_default_actions(self):
		"""Register all default browser actions"""

		if self.output_model is not None:

			@self.registry.action('Complete task', param_model=self.output_model)
			async def done(params: BaseModel):
				return ActionResult(is_done=True, extracted_content=params.model_dump_json())
		else:

			@self.registry.action('Complete task', param_model=DoneAction)
			async def done(params: DoneAction):
				return ActionResult(is_done=True, extracted_content=params.text)

		# Basic Navigation Actions
		@self.registry.action(
			'Search Google in the current tab',
			param_model=SearchGoogleAction,
		)
		async def search_google(params: SearchGoogleAction, browser: BrowserContext):
			page = await browser.get_current_page()
			await page.goto(f'https://www.google.com/search?q={params.query}&udm=14')
			await page.wait_for_load_state()
			msg = f'🔍  Searched for "{params.query}" in Google'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action('Navigate to URL in the current tab', param_model=GoToUrlAction)
		async def go_to_url(params: GoToUrlAction, browser: BrowserContext):
			page = await browser.get_current_page()
			await page.goto(params.url)
			await page.wait_for_load_state()
			msg = f'🔗  Navigated to {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action('Go back', param_model=NoParamsAction)
		async def go_back(_: NoParamsAction, browser: BrowserContext):
			await browser.go_back()
			msg = '🔙  Navigated back'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Element Interaction Actions
		@self.registry.action('Click element', param_model=ClickElementAction)
		async def click_element(params: ClickElementAction, browser: BrowserContext):
			session = await browser.get_session()
			state = session.cached_state

			if params.index not in state.selector_map:
				raise Exception(f'Element with index {params.index} does not exist - retry or use alternative actions')

			element_node = state.selector_map[params.index]
			initial_pages = len(session.context.pages)

			# if element has file uploader then dont click
			if await browser.is_file_uploader(element_node):
				msg = f'Index {params.index} - has an element which opens file upload dialog. To upload files please use a specific function to upload files '
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			msg = None

			try:
				download_path = await browser._click_element_node(element_node)
				if download_path:
					msg = f'💾  Downloaded file to {download_path}'
				else:
					msg = f'🖱️  Clicked button with index {params.index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'

				logger.info(msg)
				logger.debug(f'Element xpath: {element_node.xpath}')
				if len(session.context.pages) > initial_pages:
					new_tab_msg = 'New tab opened - switching to it'
					msg += f' - {new_tab_msg}'
					logger.info(new_tab_msg)
					await browser.switch_to_tab(-1)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				logger.warning(f'Element not clickable with index {params.index} - most likely the page changed')
				return ActionResult(error=str(e))

		@self.registry.action(
			'Input text into a input interactive element',
			param_model=InputTextAction,
		)
		async def input_text(params: InputTextAction, browser: BrowserContext):
			session = await browser.get_session()
			state = session.cached_state

			if params.index not in state.selector_map:
				raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')

			element_node = state.selector_map[params.index]
			await browser._input_text_element_node(element_node, params.text)
			msg = f'⌨️  Input {params.text} into index {params.index}'
			logger.info(msg)
			logger.debug(f'Element xpath: {element_node.xpath}')
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Tab Management Actions
		@self.registry.action('Switch tab', param_model=SwitchTabAction)
		async def switch_tab(params: SwitchTabAction, browser: BrowserContext):
			await browser.switch_to_tab(params.page_id)
			# Wait for tab to be ready
			page = await browser.get_current_page()
			await page.wait_for_load_state()
			msg = f'🔄  Switched to tab {params.page_id}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action('Open url in new tab', param_model=OpenTabAction)
		async def open_tab(params: OpenTabAction, browser: BrowserContext):
			await browser.create_new_tab(params.url)
			msg = f'🔗  Opened new tab with {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Google spreadsheet actions
		@self.registry.action(
			"Open Google Spreadsheet",
			param_model=OpenGoogleSpreadsheetAction,
		)
		async def open_google_spreadsheet(params: OpenGoogleSpreadsheetAction, browser: BrowserContext):
			"""
			Navigates to the provided Google Spreadsheet URL and waits until the sheet is loaded.
			It waits for a cell element (e.g. one with an aria-label containing "A1") to appear.
			"""
			await browser.navigate_to(params.url)
			# Wait for a known element that indicates the sheet is loaded.
			page = await browser.get_current_page()
			await page.wait_for_load_state()
			msg = f"Opened Google Spreadsheet: {params.url}"
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			"Read Spreadsheet",
			param_model=ReadSpreadsheetAction,  # This model can be empty or include optional parameters.
		)
		async def read_spreadsheet(params: ReadSpreadsheetAction, browser: BrowserContext):
			"""
			Reads the spreadsheet content from the active sheet via UI automation.
			
			This action:
			1. Waits for a reliable element (e.g. the formula bar) to ensure the sheet is loaded.
			2. Uses Ctrl+A to select all visible cells.
			3. Uses Ctrl+C to copy the selection.
			4. Uses the Clipboard API to read the copied text.
			5. Parses the text into a 2D list.
			"""
			page = await browser.get_current_page()

			# Necessary for reading the clipboard!
			await page.context.grant_permissions(['clipboard-read'])
			
			# Wait for the formula bar to be visible (indicating that the sheet is loaded)
			try:
				await page.wait_for_selector("#formula-bar", timeout=10000)
			except Exception as e:
				raise Exception("Timeout waiting for the formula bar (#formula-bar) to be visible. "
								"The spreadsheet may not have loaded correctly.") from e

			# Select all visible cells using Ctrl+A.
			await page.keyboard.down("Control")
			await page.keyboard.press("A")
			await page.keyboard.up("Control")
			await page.wait_for_timeout(500)

			# Copy the selected cells using Ctrl+C.
			await page.keyboard.down("Control")
			await page.keyboard.press("C")
			await page.keyboard.up("Control")
			await page.wait_for_timeout(500)

			# Read the clipboard text.
			clipboard_text = await page.evaluate("""async () => {
				return await navigator.clipboard.readText();
			}""")
			
			# Parse the clipboard text into rows and columns.
			rows = clipboard_text.strip().split("\n")
			data = [row.split("\t") for row in rows if row.strip()]
			
			msg = f"Read spreadsheet data: {data}"
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# --- Add Row ---
		@self.registry.action(
			"Add Row",
			param_model=AddRowAction,
		)
		async def add_row(params: AddRowAction, browser: BrowserContext):
			"""
			Inserts a new row below the currently selected row.
			This example simulates the keyboard shortcut Alt+I, then R.
			(Adjust the keys if needed based on your locale or Google Sheets version.)
			"""
			page = await browser.get_current_page()
			# Simulate the shortcut: Alt+I to open the Insert menu.
			await page.keyboard.press("Alt+I")
			await asyncio.sleep(0.2)  # Allow time for the menu to appear.
			# Press "R" to choose "Row below" (this shortcut may vary).
			await page.keyboard.press("R")
			await page.wait_for_load_state()
			msg = "Added a new row below the current selection."
			return ActionResult(extracted_content=msg, include_in_memory=True)


		@self.registry.action(
			"Insert Value",
			param_model=InsertValueAction,  # expects 'cell' (e.g., "B2") and 'value'
		)
		async def insert_value(params: InsertValueAction, browser: BrowserContext):
			"""
			Inserts a text value into the specified cell using the Google Sheets Name Box and Formula Bar.

			Steps:
			1. Locate the Name Box (the input with id "t-name-box"), click it, fill it with the target cell coordinate,
				and press Enter to select that cell.
			2. Wait for the formula bar input element (inside the element with id "t-formula-bar-input") to appear.
			3. Clear its content, type the new value, and press Enter to commit the change.
			"""
			page = await browser.get_current_page()

			# Step 1: Use the Name Box to select the target cell.
			name_box_selector = "input#t-name-box"
			try:
				name_box = await page.wait_for_selector(name_box_selector, timeout=5000)
			except Exception as e:
				raise Exception(f"Name Box not found using selector '{name_box_selector}'. Please inspect the DOM and update the selector accordingly.") from e

			await name_box.click()
			# Clear the name box before filling.
			await name_box.fill("")
			await name_box.fill(params.cell)
			await page.keyboard.press("Enter")
			await page.wait_for_timeout(500)  # Allow time for the active cell to update.

			# Step 2: Locate the formula bar input element.
			# In our DOM, the formula bar input is inside the element with id "t-formula-bar-input" and has class "cell-input".
			formula_input_selector = "#t-formula-bar-input .cell-input"
			try:
				formula_input = await page.wait_for_selector(formula_input_selector, timeout=5000)
			except Exception as e:
				raise Exception(f"Formula Bar Input not found using selector '{formula_input_selector}'. Please inspect the DOM and update the selector accordingly.") from e

			# Step 3: Clear the formula bar's content and type the new value.
			await formula_input.click()
			# Clear the contenteditable element. Since it's contenteditable, we set innerText to an empty string.
			await formula_input.evaluate("(el) => el.innerText = ''")
			await formula_input.type(params.value)
			await page.keyboard.press("Enter")
			await page.wait_for_timeout(500)  # Wait for the update to propagate.

			msg = f"Inserted value '{params.value}' into cell {params.cell} using the Formula Bar."
			return ActionResult(extracted_content=msg, include_in_memory=True)


		@self.registry.action(
			"Insert Function",
			param_model=InsertFunctionAction,
		)
		async def insert_function(params: InsertFunctionAction, browser: BrowserContext):
			"""
			Inserts a formula (function) into the specified cell using the Google Sheets Name Box and Formula Bar.

			Steps:
			1. Locate the Name Box (the input with id "t-name-box"), click it, fill it with the target cell coordinate (e.g., "B2"),
				and press Enter to select that cell.
			2. Wait for the formula bar input element (inside the container with id "t-formula-bar-input") to appear.
			3. Clear its content, type the new function (formula), and press Enter to commit the change.
			"""
			page = await browser.get_current_page()

			# Step 1: Use the Name Box to select the target cell.
			name_box_selector = "input#t-name-box"
			try:
				name_box = await page.wait_for_selector(name_box_selector, timeout=5000)
			except Exception as e:
				raise Exception(f"Name Box not found using selector '{name_box_selector}'. Please inspect the DOM and update the selector accordingly.") from e

			await name_box.click()
			# Clear the name box and type the target cell coordinate.
			await name_box.fill("")
			await name_box.fill(params.cell)
			await page.keyboard.press("Enter")
			await page.wait_for_timeout(500)  # Allow time for the active cell to update.

			# Step 2: Locate the formula bar input element.
			formula_input_selector = "#t-formula-bar-input .cell-input"
			try:
				formula_input = await page.wait_for_selector(formula_input_selector, timeout=5000)
			except Exception as e:
				raise Exception(f"Formula Bar Input not found using selector '{formula_input_selector}'. Please inspect the DOM and update the selector accordingly.") from e

			# Step 3: Clear the formula bar's content and type the new function.
			await formula_input.click()
			await formula_input.evaluate("(el) => el.innerText = ''")
			await formula_input.type(params.function)
			await page.keyboard.press("Enter")
			await page.wait_for_timeout(500)  # Wait for the update to propagate.

			msg = f"Inserted function '{params.function}' into cell {params.cell} using the Formula Bar."
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			"Delete Row",
			param_model=DeleteRowAction,
		)
		async def delete_row(params: DeleteRowAction, browser: BrowserContext):
			"""
			Deletes the specified row from the Google Sheet using the Name Box and keyboard shortcuts.

			Steps:
			1. Use the Name Box (input with id "t-name-box") to navigate to a cell in the target row.
				For example, for row 3, navigate to "A3".
			2. Wait for the active cell to update.
			3. Press Escape to ensure the cell is not in edit mode.
			4. Press Shift+Space to select the entire row.
			5. Attempt to delete the row using the keyboard shortcut Alt+E then D.
				If that fails, fall back to using Ctrl+–.
			"""
			page = await browser.get_current_page()

			# Step 1: Use the Name Box to select a cell in the target row (e.g. "A{row}")
			target_cell = f"A{params.row}"
			name_box_selector = "input#t-name-box"
			try:
				name_box = await page.wait_for_selector(name_box_selector, timeout=5000)
			except Exception as e:
				raise Exception(
					f"Name Box not found using selector '{name_box_selector}'. Please inspect the DOM and update the selector accordingly."
				) from e

			await name_box.click()
			await name_box.fill("")
			await name_box.fill(target_cell)
			await page.keyboard.press("Enter")
			await page.wait_for_timeout(500)  # Allow time for the active cell to update.

			# Step 2: Ensure we're not in edit mode.
			await page.keyboard.press("Escape")
			await page.wait_for_timeout(200)

			# Step 3: Select the entire row.
			await page.keyboard.press("Shift+Space")
			await page.wait_for_timeout(300)  # Wait for selection to register.

			# Step 4: Attempt to delete the row.
			try:
				# Attempt Alt+E then D sequence.
				await page.keyboard.press("Alt+E")
				await page.wait_for_timeout(200)
				await page.keyboard.press("D")
			except Exception:
				# Fallback: use Ctrl+- (Control + Minus)
				await page.keyboard.down("Control")
				await page.keyboard.press("-")
				await page.keyboard.up("Control")
			
			await page.wait_for_timeout(500)  # Allow time for the deletion to complete.

			msg = f"Deleted row {params.row} using keyboard shortcuts."
			return ActionResult(extracted_content=msg, include_in_memory=True)


		# Content Actions
		@self.registry.action(
			'Extract page content to retrieve specific information from the page, e.g. all company names, a specifc description, all information about, links with companies in structured format or simply links',
		)
		async def extract_content(goal: str, browser: BrowserContext, page_extraction_llm: BaseChatModel):
			page = await browser.get_current_page()
			import markdownify

			content = markdownify.markdownify(await page.content())

			prompt = 'Your task is to extract the content of the page. You will be given a page and a goal and you should extract all relevant information around this goal from the page. If the goal is vague, summarize the page. Respond in json format. Extraction goal: {goal}, Page: {page}'
			template = PromptTemplate(input_variables=['goal', 'page'], template=prompt)
			try:
				output = page_extraction_llm.invoke(template.format(goal=goal, page=content))
				msg = f'📄  Extracted from page\n: {output.content}\n'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)
			except Exception as e:
				logger.debug(f'Error extracting content: {e}')
				msg = f'📄  Extracted from page\n: {content}\n'
				logger.info(msg)
				return ActionResult(extracted_content=msg)

		@self.registry.action(
			'Scroll down the page by pixel amount - if no amount is specified, scroll down one page',
			param_model=ScrollAction,
		)
		async def scroll_down(params: ScrollAction, browser: BrowserContext):
			page = await browser.get_current_page()
			if params.amount is not None:
				await page.evaluate(f'window.scrollBy(0, {params.amount});')
			else:
				await page.keyboard.press('PageDown')

			amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍  Scrolled down the page by {amount}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
			)

		# scroll up
		@self.registry.action(
			'Scroll up the page by pixel amount - if no amount is specified, scroll up one page',
			param_model=ScrollAction,
		)
		async def scroll_up(params: ScrollAction, browser: BrowserContext):
			page = await browser.get_current_page()
			if params.amount is not None:
				await page.evaluate(f'window.scrollBy(0, -{params.amount});')
			else:
				await page.keyboard.press('PageUp')

			amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍  Scrolled up the page by {amount}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
			)

		# send keys
		@self.registry.action(
			'Send strings of special keys like Backspace, Insert, PageDown, Delete, Enter, Shortcuts such as `Control+o`, `Control+Shift+T` are supported as well. This gets used in keyboard.press. Be aware of different operating systems and their shortcuts',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser: BrowserContext):
			page = await browser.get_current_page()

			await page.keyboard.press(params.keys)
			msg = f'⌨️  Sent keys: {params.keys}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			description='If you dont find something which you want to interact with, scroll to it',
		)
		async def scroll_to_text(text: str, browser: BrowserContext):  # type: ignore
			page = await browser.get_current_page()
			try:
				# Try different locator strategies
				locators = [
					page.get_by_text(text, exact=False),
					page.locator(f'text={text}'),
					page.locator(f"//*[contains(text(), '{text}')]"),
				]

				for locator in locators:
					try:
						# First check if element exists and is visible
						if await locator.count() > 0 and await locator.first.is_visible():
							await locator.first.scroll_into_view_if_needed()
							await asyncio.sleep(0.5)  # Wait for scroll to complete
							msg = f'🔍  Scrolled to text: {text}'
							logger.info(msg)
							return ActionResult(extracted_content=msg, include_in_memory=True)
					except Exception as e:
						logger.debug(f'Locator attempt failed: {str(e)}')
						continue

				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				msg = f"Failed to scroll to text '{text}': {str(e)}"
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

		@self.registry.action(
			description='Get all options from a native dropdown',
		)
		async def get_dropdown_options(index: int, browser: BrowserContext) -> ActionResult:
			"""Get all options from a native dropdown"""
			page = await browser.get_current_page()
			selector_map = await browser.get_selector_map()
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
					return ActionResult(extracted_content=msg, include_in_memory=True)
				else:
					msg = 'No options found in any frame for dropdown'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True)

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
			browser: BrowserContext,
		) -> ActionResult:
			"""Select dropdown option by the text of the option you want to select"""
			page = await browser.get_current_page()
			selector_map = await browser.get_selector_map()
			dom_element = selector_map[index]

			# Validate that we're working with a select element
			if dom_element.tag_name != 'select':
				logger.error(f'Element is not a select! Tag: {dom_element.tag_name}, Attributes: {dom_element.attributes}')
				msg = f'Cannot select option: Element with index {index} is a {dom_element.tag_name}, not a select'
				return ActionResult(extracted_content=msg, include_in_memory=True)

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

							return ActionResult(extracted_content=msg, include_in_memory=True)

					except Exception as frame_e:
						logger.error(f'Frame {frame_index} attempt failed: {str(frame_e)}')
						logger.error(f'Frame type: {type(frame)}')
						logger.error(f'Frame URL: {frame.url}')

					frame_index += 1

				msg = f"Could not select option '{text}' in any frame"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				msg = f'Selection failed: {str(e)}'
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

	def action(self, description: str, **kwargs):
		"""Decorator for registering custom actions

		@param description: Describe the LLM what the function does (better description == better function calling)
		"""
		return self.registry.action(description, **kwargs)

	@time_execution_async('--multi-act')
	async def multi_act(
		self,
		actions: list[ActionModel],
		browser_context: BrowserContext,
		check_break_if_paused: Callable[[], bool],
		check_for_new_elements: bool = True,
		page_extraction_llm: Optional[BaseChatModel] = None,
		sensitive_data: Optional[Dict[str, str]] = None,
	) -> list[ActionResult]:
		"""Execute multiple actions"""
		results = []

		session = await browser_context.get_session()
		cached_selector_map = session.cached_state.selector_map
		cached_path_hashes = set(e.hash.branch_path_hash for e in cached_selector_map.values())

		check_break_if_paused()

		await browser_context.remove_highlights()

		for i, action in enumerate(actions):
			check_break_if_paused()

			if action.get_index() is not None and i != 0:
				new_state = await browser_context.get_state()
				new_path_hashes = set(e.hash.branch_path_hash for e in new_state.selector_map.values())
				if check_for_new_elements and not new_path_hashes.issubset(cached_path_hashes):
					# next action requires index but there are new elements on the page
					logger.info(f'Something new appeared after action {i} / {len(actions)}')
					break

			check_break_if_paused()

			results.append(await self.act(action, browser_context, page_extraction_llm, sensitive_data))

			logger.debug(f'Executed action {i + 1} / {len(actions)}')
			if results[-1].is_done or results[-1].error or i == len(actions) - 1:
				break

			await asyncio.sleep(browser_context.config.wait_between_actions)
			# hash all elements. if it is a subset of cached_state its fine - else break (new elements on page)

		return results

	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_context: BrowserContext,
		page_extraction_llm: Optional[BaseChatModel] = None,
		sensitive_data: Optional[Dict[str, str]] = None,
	) -> ActionResult:
		"""Execute an action"""
		try:
			for action_name, params in action.model_dump(exclude_unset=True).items():
				if params is not None:
					# remove highlights
					result = await self.registry.execute_action(
						action_name,
						params,
						browser=browser_context,
						page_extraction_llm=page_extraction_llm,
						sensitive_data=sensitive_data,
					)
					if isinstance(result, str):
						return ActionResult(extracted_content=result)
					elif isinstance(result, ActionResult):
						return result
					elif result is None:
						return ActionResult()
					else:
						raise ValueError(f'Invalid action result type: {type(result)} of {result}')
			return ActionResult()
		except Exception as e:
			raise e
