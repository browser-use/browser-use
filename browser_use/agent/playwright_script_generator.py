# import json
# import logging
# from pathlib import Path
# from typing import Any

# from browser_use.browser import BrowserConfig, BrowserContextConfig

# logger = logging.getLogger(__name__)


# class PlaywrightScriptGenerator:
# 	"""Generates a Playwright script from AgentHistoryList."""

# 	def __init__(
# 		self,
# 		history_list: list[dict[str, Any]],
# 		sensitive_data_keys: list[str] | None = None,
# 		browser_config: BrowserConfig | None = None,
# 		context_config: BrowserContextConfig | None = None,
# 	):
# 		"""
# 		Initializes the script generator.

# 		Args:
# 		    history_list: A list of dictionaries, where each dictionary represents an AgentHistory item.
# 		                 Expected to be raw dictionaries from `AgentHistoryList.model_dump()`.
# 		    sensitive_data_keys: A list of keys used as placeholders for sensitive data.
# 		    browser_config: Configuration from the original Browser instance (deprecated, use BrowserProfile).
# 		    context_config: Configuration from the original BrowserContext instance (deprecated, use BrowserProfile).
# 		"""
# 		self.history = history_list
# 		self.sensitive_data_keys = sensitive_data_keys or []
# 		self.browser_config = browser_config
# 		self.context_config = context_config
# 		self._imports_helpers_added = False
# 		self._page_counter = 0  # Track pages for tab management

# 		# Dictionary mapping action types to handler methods
# 		self._action_handlers = {
# 			'go_to_url': self._map_go_to_url,
# 			'wait': self._map_wait,
# 			'input_text': self._map_input_text,
# 			'click_element': self._map_click_element,
# 			'click_element_by_index': self._map_click_element,  # Map legacy action
# 			'scroll_down': self._map_scroll_down,
# 			'scroll_up': self._map_scroll_up,
# 			'send_keys': self._map_send_keys,
# 			'go_back': self._map_go_back,
# 			'open_tab': self._map_open_tab,
# 			'close_tab': self._map_close_tab,
# 			'switch_tab': self._map_switch_tab,
# 			'search_google': self._map_search_google,
# 			'drag_drop': self._map_drag_drop,
# 			'extract_content': self._map_extract_content,
# 			'click_download_button': self._map_click_download_button,
# 			'done': self._map_done,
# 		}

# 	def _generate_browser_launch_args(self) -> str:
# 		"""Generates the arguments string for browser launch based on BrowserConfig."""
# 		if not self.browser_config:
# 			# Default launch if no config provided
# 			return 'headless=False'

# 		args_dict = {
# 			'headless': self.browser_config.headless,
# 			# Add other relevant launch options here based on self.browser_config
# 			# Example: 'proxy': self.browser_config.proxy.model_dump() if self.browser_config.proxy else None
# 			# Example: 'args': self.browser_config.extra_browser_args # Be careful inheriting args
# 		}
# 		if self.browser_config.proxy:
# 			args_dict['proxy'] = self.browser_config.proxy.model_dump()

# 		# Filter out None values
# 		args_dict = {k: v for k, v in args_dict.items() if v is not None}

# 		# Format as keyword arguments string
# 		args_str = ', '.join(f'{key}={repr(value)}' for key, value in args_dict.items())
# 		return args_str

# 	def _generate_context_options(self) -> str:
# 		"""Generates the options string for context creation based on BrowserContextConfig."""
# 		if not self.context_config:
# 			return ''  # Default context

# 		options_dict = {}

# 		# Map relevant BrowserContextConfig fields to Playwright context options
# 		if self.context_config.user_agent:
# 			options_dict['user_agent'] = self.context_config.user_agent
# 		if self.context_config.locale:
# 			options_dict['locale'] = self.context_config.locale
# 		if self.context_config.permissions:
# 			options_dict['permissions'] = self.context_config.permissions
# 		if self.context_config.geolocation:
# 			options_dict['geolocation'] = self.context_config.geolocation
# 		if self.context_config.timezone_id:
# 			options_dict['timezone_id'] = self.context_config.timezone_id
# 		if self.context_config.http_credentials:
# 			options_dict['http_credentials'] = self.context_config.http_credentials
# 		if self.context_config.is_mobile is not None:
# 			options_dict['is_mobile'] = self.context_config.is_mobile
# 		if self.context_config.has_touch is not None:
# 			options_dict['has_touch'] = self.context_config.has_touch
# 		if self.context_config.save_recording_path:
# 			options_dict['record_video_dir'] = self.context_config.save_recording_path
# 		if self.context_config.save_har_path:
# 			options_dict['record_har_path'] = self.context_config.save_har_path

# 		# Handle viewport/window size
# 		if self.context_config.no_viewport:
# 			options_dict['no_viewport'] = True
# 		elif hasattr(self.context_config, 'window_width') and hasattr(self.context_config, 'window_height'):
# 			options_dict['viewport'] = {
# 				'width': self.context_config.window_width,
# 				'height': self.context_config.window_height,
# 			}

# 		# Note: cookies_file and downloads_dir are handled separately

# 		# Filter out None values
# 		options_dict = {k: v for k, v in options_dict.items() if v is not None}

# 		# Format as keyword arguments string
# 		options_str = ', '.join(f'{key}={repr(value)}' for key, value in options_dict.items())
# 		return options_str

# 	def _get_imports_and_helpers(self) -> list[str]:
# 		"""Generates necessary import statements (excluding helper functions)."""
# 		# Return only the standard imports needed by the main script body
# 		return [
# 			'import asyncio',
# 			'import json',
# 			'import os',
# 			'import sys',
# 			'from pathlib import Path',  # Added Path import
# 			'import urllib.parse',  # Needed for search_google
# 			'from playwright.async_api import async_playwright, Page, BrowserContext',  # Added BrowserContext
# 			'from dotenv import load_dotenv',
# 			'',
# 			'# Load environment variables',
# 			'load_dotenv(override=True)',
# 			'',
# 			# Helper function definitions are no longer here
# 		]

# 	def _get_sensitive_data_definitions(self) -> list[str]:
# 		"""Generates the SENSITIVE_DATA dictionary definition."""
# 		if not self.sensitive_data_keys:
# 			return ['SENSITIVE_DATA = {}', '']

# 		lines = ['# Sensitive data placeholders mapped to environment variables']
# 		lines.append('SENSITIVE_DATA = {')
# 		for key in self.sensitive_data_keys:
# 			env_var_name = key.upper()
# 			default_value_placeholder = f'YOUR_{env_var_name}'
# 			lines.append(f'    "{key}": os.getenv("{env_var_name}", {json.dumps(default_value_placeholder)}),')
# 		lines.append('}')
# 		lines.append('')
# 		return lines

# 	def _get_selector_for_action(self, history_item: dict, action_index_in_step: int) -> str | None:
# 		"""
# 		Gets the selector (preferring XPath) for a given action index within a history step.
# 		Formats the XPath correctly for Playwright.
# 		"""
# 		state = history_item.get('state')
# 		if not isinstance(state, dict):
# 			return None
# 		interacted_elements = state.get('interacted_element')
# 		if not isinstance(interacted_elements, list):
# 			return None
# 		if action_index_in_step >= len(interacted_elements):
# 			return None
# 		element_data = interacted_elements[action_index_in_step]
# 		if not isinstance(element_data, dict):
# 			return None

# 		# Prioritize XPath
# 		xpath = element_data.get('xpath')
# 		if isinstance(xpath, str) and xpath.strip():
# 			if not xpath.startswith('xpath=') and not xpath.startswith('/') and not xpath.startswith('//'):
# 				xpath_selector = f'xpath=//{xpath}'  # Make relative if not already
# 			elif not xpath.startswith('xpath='):
# 				xpath_selector = f'xpath={xpath}'  # Add prefix if missing
# 			else:
# 				xpath_selector = xpath
# 			return xpath_selector

# 		# Fallback to CSS selector if XPath is missing
# 		css_selector = element_data.get('css_selector')
# 		if isinstance(css_selector, str) and css_selector.strip():
# 			return css_selector  # Use CSS selector as is

# 		logger.warning(
# 			f'Could not find a usable XPath or CSS selector for action index {action_index_in_step} (element index {element_data.get("highlight_index", "N/A")}).'
# 		)
# 		return None

# 	def _get_goto_timeout(self) -> int:
# 		"""Gets the page navigation timeout in milliseconds."""
# 		default_timeout = 90000  # Default 90 seconds
# 		if self.context_config and self.context_config.maximum_wait_page_load_time:
# 			# Convert seconds to milliseconds
# 			return int(self.context_config.maximum_wait_page_load_time * 1000)
# 		return default_timeout

# 	# --- Action Mapping Methods ---
# 	def _map_go_to_url(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		url = params.get('url')
# 		goto_timeout = self._get_goto_timeout()
# 		script_lines = []
# 		if url and isinstance(url, str):
# 			escaped_url = json.dumps(url)
# 			script_lines.append(f'            print(f"Navigating to: {url} ({step_info_str})")')
# 			script_lines.append(f'            await page.goto({escaped_url}, timeout={goto_timeout})')
# 			script_lines.append(f"            await page.wait_for_load_state('load', timeout={goto_timeout})")
# 			script_lines.append('            await page.wait_for_timeout(1000)')  # Short pause
# 		else:
# 			script_lines.append(f'            # Skipping go_to_url ({step_info_str}): missing or invalid url')
# 		return script_lines

# 	def _map_wait(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		seconds = params.get('seconds', 3)
# 		try:
# 			wait_seconds = int(seconds)
# 		except (ValueError, TypeError):
# 			wait_seconds = 3
# 		return [
# 			f'            print(f"Waiting for {wait_seconds} seconds... ({step_info_str})")',
# 			f'            await asyncio.sleep({wait_seconds})',
# 		]

# 	def _map_input_text(
# 		self, params: dict, history_item: dict, action_index_in_step: int, step_info_str: str, **kwargs
# 	) -> list[str]:
# 		index = params.get('index')
# 		text = params.get('text', '')
# 		selector = self._get_selector_for_action(history_item, action_index_in_step)
# 		script_lines = []
# 		if selector and index is not None:
# 			clean_text_expression = f'replace_sensitive_data({json.dumps(str(text))}, SENSITIVE_DATA)'
# 			escaped_selector = json.dumps(selector)
# 			escaped_step_info = json.dumps(step_info_str)
# 			script_lines.append(
# 				f'            await _try_locate_and_act(page, {escaped_selector}, "fill", text={clean_text_expression}, step_info={escaped_step_info})'
# 			)
# 		else:
# 			script_lines.append(
# 				f'            # Skipping input_text ({step_info_str}): missing index ({index}) or selector ({selector})'
# 			)
# 		return script_lines

# 	def _map_click_element(
# 		self, params: dict, history_item: dict, action_index_in_step: int, step_info_str: str, action_type: str, **kwargs
# 	) -> list[str]:
# 		if action_type == 'click_element_by_index':
# 			logger.warning(f"Mapping legacy 'click_element_by_index' to 'click_element' ({step_info_str})")
# 		index = params.get('index')
# 		selector = self._get_selector_for_action(history_item, action_index_in_step)
# 		script_lines = []
# 		if selector and index is not None:
# 			escaped_selector = json.dumps(selector)
# 			escaped_step_info = json.dumps(step_info_str)
# 			script_lines.append(
# 				f'            await _try_locate_and_act(page, {escaped_selector}, "click", step_info={escaped_step_info})'
# 			)
# 		else:
# 			script_lines.append(
# 				f'            # Skipping {action_type} ({step_info_str}): missing index ({index}) or selector ({selector})'
# 			)
# 		return script_lines

# 	def _map_scroll_down(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		amount = params.get('amount')
# 		script_lines = []
# 		if amount and isinstance(amount, int):
# 			script_lines.append(f'            print(f"Scrolling down by {amount} pixels ({step_info_str})")')
# 			script_lines.append(f"            await page.evaluate('window.scrollBy(0, {amount})')")
# 		else:
# 			script_lines.append(f'            print(f"Scrolling down by one page height ({step_info_str})")')
# 			script_lines.append("            await page.evaluate('window.scrollBy(0, window.innerHeight)')")
# 		script_lines.append('            await page.wait_for_timeout(500)')
# 		return script_lines

# 	def _map_scroll_up(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		amount = params.get('amount')
# 		script_lines = []
# 		if amount and isinstance(amount, int):
# 			script_lines.append(f'            print(f"Scrolling up by {amount} pixels ({step_info_str})")')
# 			script_lines.append(f"            await page.evaluate('window.scrollBy(0, -{amount})')")
# 		else:
# 			script_lines.append(f'            print(f"Scrolling up by one page height ({step_info_str})")')
# 			script_lines.append("            await page.evaluate('window.scrollBy(0, -window.innerHeight)')")
# 		script_lines.append('            await page.wait_for_timeout(500)')
# 		return script_lines

# 	def _map_send_keys(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		keys = params.get('keys')
# 		script_lines = []
# 		if keys and isinstance(keys, str):
# 			escaped_keys = json.dumps(keys)
# 			script_lines.append(f'            print(f"Sending keys: {keys} ({step_info_str})")')
# 			script_lines.append(f'            await page.keyboard.press({escaped_keys})')
# 			script_lines.append('            await page.wait_for_timeout(500)')
# 		else:
# 			script_lines.append(f'            # Skipping send_keys ({step_info_str}): missing or invalid keys')
# 		return script_lines

# 	def _map_go_back(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		goto_timeout = self._get_goto_timeout()
# 		return [
# 			'            await asyncio.sleep(60)  # Wait 1 minute (important) before going back',
# 			f'            print(f"Navigating back using browser history ({step_info_str})")',
# 			f'            await page.go_back(timeout={goto_timeout})',
# 			f"            await page.wait_for_load_state('load', timeout={goto_timeout})",
# 			'            await page.wait_for_timeout(1000)',
# 		]

# 	def _map_open_tab(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		url = params.get('url')
# 		goto_timeout = self._get_goto_timeout()
# 		script_lines = []
# 		if url and isinstance(url, str):
# 			escaped_url = json.dumps(url)
# 			script_lines.append(f'            print(f"Opening new tab and navigating to: {url} ({step_info_str})")')
# 			script_lines.append('            page = await context.new_page()')
# 			script_lines.append(f'            await page.goto({escaped_url}, timeout={goto_timeout})')
# 			script_lines.append(f"            await page.wait_for_load_state('load', timeout={goto_timeout})")
# 			script_lines.append('            await page.wait_for_timeout(1000)')
# 			self._page_counter += 1  # Increment page counter
# 		else:
# 			script_lines.append(f'            # Skipping open_tab ({step_info_str}): missing or invalid url')
# 		return script_lines

# 	def _map_close_tab(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		page_id = params.get('page_id')
# 		script_lines = []
# 		if page_id is not None:
# 			script_lines.extend(
# 				[
# 					f'            print(f"Attempting to close tab with page_id {page_id} ({step_info_str})")',
# 					f'            if {page_id} < len(context.pages):',
# 					f'                target_page = context.pages[{page_id}]',
# 					'                await target_page.close()',
# 					'                await page.wait_for_timeout(500)',
# 					'                if context.pages: page = context.pages[-1]',  # Switch to last page
# 					'                else:',
# 					"                    print('  Warning: No pages left after closing tab. Cannot switch.', file=sys.stderr)",
# 					'                    # Optionally, create a new page here if needed: page = await context.new_page()',
# 					'                if page: await page.bring_to_front()',  # Bring to front if page exists
# 					'            else:',
# 					f'                print(f"  Warning: Tab with page_id {page_id} not found to close ({step_info_str})", file=sys.stderr)',
# 				]
# 			)
# 		else:
# 			script_lines.append(f'            # Skipping close_tab ({step_info_str}): missing page_id')
# 		return script_lines

# 	def _map_switch_tab(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		page_id = params.get('page_id')
# 		script_lines = []
# 		if page_id is not None:
# 			script_lines.extend(
# 				[
# 					f'            print(f"Switching to tab with page_id {page_id} ({step_info_str})")',
# 					f'            if {page_id} < len(context.pages):',
# 					f'                page = context.pages[{page_id}]',
# 					'                await page.bring_to_front()',
# 					"                await page.wait_for_load_state('load', timeout=15000)",
# 					'                await page.wait_for_timeout(500)',
# 					'            else:',
# 					f'                print(f"  Warning: Tab with page_id {page_id} not found to switch ({step_info_str})", file=sys.stderr)',
# 				]
# 			)
# 		else:
# 			script_lines.append(f'            # Skipping switch_tab ({step_info_str}): missing page_id')
# 		return script_lines

# 	def _map_search_google(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		query = params.get('query')
# 		goto_timeout = self._get_goto_timeout()
# 		script_lines = []
# 		if query and isinstance(query, str):
# 			clean_query = f'replace_sensitive_data({json.dumps(query)}, SENSITIVE_DATA)'
# 			search_url_expression = f'f"https://www.google.com/search?q={{ urllib.parse.quote_plus({clean_query}) }}&udm=14"'
# 			script_lines.extend(
# 				[
# 					f'            search_url = {search_url_expression}',
# 					f'            print(f"Searching Google for query related to: {{ {clean_query} }} ({step_info_str})")',
# 					f'            await page.goto(search_url, timeout={goto_timeout})',
# 					f"            await page.wait_for_load_state('load', timeout={goto_timeout})",
# 					'            await page.wait_for_timeout(1000)',
# 				]
# 			)
# 		else:
# 			script_lines.append(f'            # Skipping search_google ({step_info_str}): missing or invalid query')
# 		return script_lines

# 	def _map_drag_drop(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		source_sel = params.get('element_source')
# 		target_sel = params.get('element_target')
# 		source_coords = (params.get('coord_source_x'), params.get('coord_source_y'))
# 		target_coords = (params.get('coord_target_x'), params.get('coord_target_y'))
# 		script_lines = [f'            print(f"Attempting drag and drop ({step_info_str})")']
# 		if source_sel and target_sel:
# 			escaped_source = json.dumps(source_sel)
# 			escaped_target = json.dumps(target_sel)
# 			script_lines.append(f'            await page.drag_and_drop({escaped_source}, {escaped_target})')
# 			script_lines.append(f"            print(f'  Dragged element {escaped_source} to {escaped_target}')")
# 		elif all(c is not None for c in source_coords) and all(c is not None for c in target_coords):
# 			sx, sy = source_coords
# 			tx, ty = target_coords
# 			script_lines.extend(
# 				[
# 					f'            await page.mouse.move({sx}, {sy})',
# 					'            await page.mouse.down()',
# 					f'            await page.mouse.move({tx}, {ty})',
# 					'            await page.mouse.up()',
# 					f"            print(f'  Dragged from ({sx},{sy}) to ({tx},{ty})')",
# 				]
# 			)
# 		else:
# 			script_lines.append(
# 				f'            # Skipping drag_drop ({step_info_str}): requires either element selectors or full coordinates'
# 			)
# 		script_lines.append('            await page.wait_for_timeout(500)')
# 		return script_lines

# 	def _map_extract_content(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		goal = params.get('goal', 'content')
# 		logger.warning(f"Action 'extract_content' ({step_info_str}) cannot be directly translated to Playwright script.")
# 		return [f'            # Action: extract_content (Goal: {goal}) - Skipped in Playwright script ({step_info_str})']

# 	def _map_click_download_button(
# 		self, params: dict, history_item: dict, action_index_in_step: int, step_info_str: str, **kwargs
# 	) -> list[str]:
# 		index = params.get('index')
# 		selector = self._get_selector_for_action(history_item, action_index_in_step)
# 		download_dir_in_script = "'./files'"  # Default
# 		if self.context_config and self.context_config.downloads_dir:
# 			download_dir_in_script = repr(self.context_config.downloads_dir)

# 		script_lines = []
# 		if selector and index is not None:
# 			script_lines.append(
# 				f'            print(f"Attempting to download file by clicking element ({selector}) ({step_info_str})")'
# 			)
# 			script_lines.append('            try:')
# 			script_lines.append(
# 				'                async with page.expect_download(timeout=120000) as download_info:'
# 			)  # 2 min timeout
# 			step_info_for_download = f'{step_info_str} (triggering download)'
# 			script_lines.append(
# 				f'                    await _try_locate_and_act(page, {json.dumps(selector)}, "click", step_info={json.dumps(step_info_for_download)})'
# 			)
# 			script_lines.append('                download = await download_info.value')
# 			script_lines.append(f'                configured_download_dir = {download_dir_in_script}')
# 			script_lines.append('                download_dir_path = Path(configured_download_dir).resolve()')
# 			script_lines.append('                download_dir_path.mkdir(parents=True, exist_ok=True)')
# 			script_lines.append(
# 				"                base, ext = os.path.splitext(download.suggested_filename or f'download_{{len(list(download_dir_path.iterdir())) + 1}}.tmp')"
# 			)
# 			script_lines.append('                counter = 1')
# 			script_lines.append("                download_path_obj = download_dir_path / f'{base}{ext}'")
# 			script_lines.append('                while download_path_obj.exists():')
# 			script_lines.append("                    download_path_obj = download_dir_path / f'{base}({{counter}}){ext}'")
# 			script_lines.append('                    counter += 1')
# 			script_lines.append('                await download.save_as(str(download_path_obj))')
# 			script_lines.append("                print(f'  File downloaded successfully to: {str(download_path_obj)}')")
# 			script_lines.append('            except PlaywrightActionError as pae:')
# 			script_lines.append('                raise pae')  # Re-raise to stop script
# 			script_lines.append('            except Exception as download_err:')
# 			script_lines.append(
# 				f"                raise PlaywrightActionError(f'Download failed for {step_info_str}: {{download_err}}') from download_err"
# 			)
# 		else:
# 			script_lines.append(
# 				f'            # Skipping click_download_button ({step_info_str}): missing index ({index}) or selector ({selector})'
# 			)
# 		return script_lines

# 	def _map_done(self, params: dict, step_info_str: str, **kwargs) -> list[str]:
# 		script_lines = []
# 		if isinstance(params, dict):
# 			final_text = params.get('text', '')
# 			success_status = params.get('success', False)
# 			escaped_final_text_with_placeholders = json.dumps(str(final_text))
# 			script_lines.append(f'            print("\\n--- Task marked as Done by agent ({step_info_str}) ---")')
# 			script_lines.append(f'            print(f"Agent reported success: {success_status}")')
# 			script_lines.append('            # Final Message from agent (may contain placeholders):')
# 			script_lines.append(
# 				f'            final_message = replace_sensitive_data({escaped_final_text_with_placeholders}, SENSITIVE_DATA)'
# 			)
# 			script_lines.append('            print(final_message)')
# 		else:
# 			script_lines.append(f'            print("\\n--- Task marked as Done by agent ({step_info_str}) ---")')
# 			script_lines.append('            print("Success: N/A (invalid params)")')
# 			script_lines.append('            print("Final Message: N/A (invalid params)")')
# 		return script_lines

# 	def _map_action_to_playwright(
# 		self,
# 		action_dict: dict,
# 		history_item: dict,
# 		previous_history_item: dict | None,
# 		action_index_in_step: int,
# 		step_info_str: str,
# 	) -> list[str]:
# 		"""
# 		Translates a single action dictionary into Playwright script lines using dictionary dispatch.
# 		"""
# 		if not isinstance(action_dict, dict) or not action_dict:
# 			return [f'            # Invalid action format: {action_dict} ({step_info_str})']

# 		action_type = next(iter(action_dict.keys()), None)
# 		params = action_dict.get(action_type)

# 		if not action_type or params is None:
# 			if action_dict == {}:
# 				return [f'            # Empty action dictionary found ({step_info_str})']
# 			return [f'            # Could not determine action type or params: {action_dict} ({step_info_str})']

# 		# Get the handler function from the dictionary
# 		handler = self._action_handlers.get(action_type)

# 		if handler:
# 			# Call the specific handler method
# 			return handler(
# 				params=params,
# 				history_item=history_item,
# 				action_index_in_step=action_index_in_step,
# 				step_info_str=step_info_str,
# 				action_type=action_type,  # Pass action_type for legacy handling etc.
# 				previous_history_item=previous_history_item,
# 			)
# 		else:
# 			# Handle unsupported actions
# 			logger.warning(f'Unsupported action type encountered: {action_type} ({step_info_str})')
# 			return [f'            # Unsupported action type: {action_type} ({step_info_str})']

# 	def generate_script_content(self) -> str:
# 		"""Generates the full Playwright script content as a string."""
# 		script_lines = []
# 		self._page_counter = 0  # Reset page counter for new script generation

# 		if not self._imports_helpers_added:
# 			script_lines.extend(self._get_imports_and_helpers())
# 			self._imports_helpers_added = True

# 		# Read helper script content
# 		helper_script_path = Path(__file__).parent / 'playwright_script_helpers.py'
# 		try:
# 			with open(helper_script_path, encoding='utf-8') as f_helper:
# 				helper_script_content = f_helper.read()
# 		except FileNotFoundError:
# 			logger.error(f'Helper script not found at {helper_script_path}. Cannot generate script.')
# 			return '# Error: Helper script file missing.'
# 		except Exception as e:
# 			logger.error(f'Error reading helper script {helper_script_path}: {e}')
# 			return f'# Error: Could not read helper script: {e}'

# 		script_lines.extend(self._get_sensitive_data_definitions())

# 		# Add the helper script content after imports and sensitive data
# 		script_lines.append('\n# --- Helper Functions (from playwright_script_helpers.py) ---')
# 		script_lines.append(helper_script_content)
# 		script_lines.append('# --- End Helper Functions ---')

# 		# Generate browser launch and context creation code
# 		browser_launch_args = self._generate_browser_launch_args()
# 		context_options = self._generate_context_options()
# 		# Determine browser type (defaulting to chromium)
# 		browser_type = 'chromium'
# 		if self.browser_config and self.browser_config.browser_class in ['firefox', 'webkit']:
# 			browser_type = self.browser_config.browser_class

# 		script_lines.extend(
# 			[
# 				'async def run_generated_script():',
# 				'    global SENSITIVE_DATA',  # Ensure sensitive data is accessible
# 				'    async with async_playwright() as p:',
# 				'        browser = None',
# 				'        context = None',
# 				'        page = None',
# 				'        exit_code = 0 # Default success exit code',
# 				'        try:',
# 				f"            print('Launching {browser_type} browser...')",
# 				# Use generated launch args, remove slow_mo
# 				f'            browser = await p.{browser_type}.launch({browser_launch_args})',
# 				# Use generated context options
# 				f'            context = await browser.new_context({context_options})',
# 				"            print('Browser context created.')",
# 			]
# 		)

# 		# Add cookie loading logic if cookies_file is specified
# 		if self.context_config and self.context_config.cookies_file:
# 			cookies_file_path = repr(self.context_config.cookies_file)
# 			script_lines.extend(
# 				[
# 					'            # Load cookies if specified',
# 					f'            cookies_path = {cookies_file_path}',
# 					'            if cookies_path and os.path.exists(cookies_path):',
# 					'                try:',
# 					"                    with open(cookies_path, 'r', encoding='utf-8') as f_cookies:",
# 					'                        cookies = json.load(f_cookies)',
# 					'                        # Validate sameSite attribute',
# 					"                        valid_same_site = ['Strict', 'Lax', 'None']",
# 					'                        for cookie in cookies:',
# 					"                            if 'sameSite' in cookie and cookie['sameSite'] not in valid_same_site:",
# 					'                                print(f\'  Warning: Fixing invalid sameSite value "{{cookie["sameSite"]}}" to None for cookie {{cookie.get("name")}}\', file=sys.stderr)',
# 					"                                cookie['sameSite'] = 'None'",
# 					'                        await context.add_cookies(cookies)',
# 					"                        print(f'  Successfully loaded {{len(cookies)}} cookies from {{cookies_path}}')",
# 					'                except Exception as cookie_err:',
# 					"                    print(f'  Warning: Failed to load or add cookies from {{cookies_path}}: {{cookie_err}}', file=sys.stderr)",
# 					'            else:',
# 					'                if cookies_path:',  # Only print if a path was specified but not found
# 					"                    print(f'  Cookie file not found at: {cookies_path}')",
# 					'',
# 				]
# 			)

# 		script_lines.extend(
# 			[
# 				'            # Initial page handling',
# 				'            if context.pages:',
# 				'                page = context.pages[0]',
# 				"                print('Using initial page provided by context.')",
# 				'            else:',
# 				'                page = await context.new_page()',
# 				"                print('Created a new page as none existed.')",
# 				"            print('\\n--- Starting Generated Script Execution ---')",
# 			]
# 		)

# 		action_counter = 0
# 		stop_processing_steps = False
# 		previous_item_dict = None

# 		for step_index, item_dict in enumerate(self.history):
# 			if stop_processing_steps:
# 				break

# 			if not isinstance(item_dict, dict):
# 				logger.warning(f'Skipping step {step_index + 1}: Item is not a dictionary ({type(item_dict)})')
# 				script_lines.append(f'\n            # --- Step {step_index + 1}: Skipped (Invalid Format) ---')
# 				previous_item_dict = item_dict
# 				continue

# 			script_lines.append(f'\n            # --- Step {step_index + 1} ---')
# 			model_output = item_dict.get('model_output')

# 			if not isinstance(model_output, dict) or 'action' not in model_output:
# 				script_lines.append('            # No valid model_output or action found for this step')
# 				previous_item_dict = item_dict
# 				continue

# 			actions = model_output.get('action')
# 			if not isinstance(actions, list):
# 				script_lines.append(f'            # Actions format is not a list: {type(actions)}')
# 				previous_item_dict = item_dict
# 				continue

# 			for action_index_in_step, action_detail in enumerate(actions):
# 				action_counter += 1
# 				script_lines.append(f'            # Action {action_counter}')

# 				step_info_str = f'Step {step_index + 1}, Action {action_index_in_step + 1}'
# 				action_lines = self._map_action_to_playwright(
# 					action_dict=action_detail,
# 					history_item=item_dict,
# 					previous_history_item=previous_item_dict,
# 					action_index_in_step=action_index_in_step,
# 					step_info_str=step_info_str,
# 				)
# 				script_lines.extend(action_lines)

# 				action_type = next(iter(action_detail.keys()), None) if isinstance(action_detail, dict) else None
# 				if action_type == 'done':
# 					stop_processing_steps = True
# 					break

# 			previous_item_dict = item_dict

# 		# Updated final block to include sys.exit
# 		script_lines.extend(
# 			[
# 				'        except PlaywrightActionError as pae:',  # Catch specific action errors
# 				"            print(f'\\n--- Playwright Action Error: {pae} ---', file=sys.stderr)",
# 				'            exit_code = 1',  # Set exit code to failure
# 				'        except Exception as e:',
# 				"            print(f'\\n--- An unexpected error occurred: {e} ---', file=sys.stderr)",
# 				'            import traceback',
# 				'            traceback.print_exc()',
# 				'            exit_code = 1',  # Set exit code to failure
# 				'        finally:',
# 				"            print('\\n--- Generated Script Execution Finished ---')",
# 				"            print('Closing browser/context...')",
# 				'            if context:',
# 				'                 try: await context.close()',
# 				"                 except Exception as ctx_close_err: print(f'  Warning: could not close context: {ctx_close_err}', file=sys.stderr)",
# 				'            if browser:',
# 				'                 try: await browser.close()',
# 				"                 except Exception as browser_close_err: print(f'  Warning: could not close browser: {browser_close_err}', file=sys.stderr)",
# 				"            print('Browser/context closed.')",
# 				'            # Exit with the determined exit code',
# 				'            if exit_code != 0:',
# 				"                print(f'Script finished with errors (exit code {exit_code}).', file=sys.stderr)",
# 				'                sys.exit(exit_code)',  # Exit with non-zero code on error
# 				'',
# 				'# --- Script Entry Point ---',
# 				"if __name__ == '__main__':",
# 				"    if os.name == 'nt':",
# 				'        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())',
# 				'    asyncio.run(run_generated_script())',
# 			]
# 		)

# 		return '\n'.join(script_lines)
