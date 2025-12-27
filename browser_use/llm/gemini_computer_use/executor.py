"""Executor for Gemini Computer Use actions within Browser Use using Actor API."""

import asyncio
import logging
import platform
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.actor import Page


class ComputerUseActionExecutor:
	"""Executes Gemini Computer Use function calls within Browser Use using Actor API.

	Computer Use actions are coordinate-based (click_at x=500, y=300) while Browser Use
	actions are element-based (click index=123). This executor bridges the gap by:
	1. Executing Computer Use function calls via Actor API
	2. Converting results back to Browser Use format
	"""

	def __init__(self, screen_width: int = 1440, screen_height: int = 900):
		"""Initialize the executor.

		Args:
			screen_width: Browser viewport width (default 1440, matching Computer Use docs)
			screen_height: Browser viewport height (default 900, matching Computer Use docs)

		"""
		self.screen_width = screen_width
		self.screen_height = screen_height
		self.logger = logging.getLogger('browser_use.llm.gemini_computer_use.executor')
		self._browser_opened = False  # Track if we've already handled open_web_browser

	def denormalize_x(self, x: int) -> int:
		"""Convert normalized x coordinate (0-999) to actual pixel coordinate."""
		return int(x / 1000 * self.screen_width)

	def denormalize_y(self, y: int) -> int:
		"""Convert normalized y coordinate (0-999) to actual pixel coordinate."""
		return int(y / 1000 * self.screen_height)

	async def execute_function_call(self, function_call: Any, page: 'Page') -> dict[str, Any]:
		"""Execute a single Computer Use function call using Actor API.

		Args:
			function_call: The function call object from Gemini response
			page: Actor Page instance (browser_use.actor.Page)

		Returns:
			Result dictionary with status and any error info

		"""
		fname = function_call.name
		args = function_call.args

		self.logger.debug(f'🖱️  Executing Computer Use action: {fname}')

		try:
			if fname == 'open_web_browser':
				# Browser already open in Browser Use
				# Only navigate to about:blank on FIRST call to match expected behavior
				if not self._browser_opened:
					self.logger.info('  First open_web_browser call - navigating to about:blank')
					await page.goto('about:blank')
					self._browser_opened = True
				else:
					self.logger.info('  Browser already opened - skipping duplicate open_web_browser call')
				return {'status': 'success', 'message': 'Browser opened', 'url': 'about:blank'}

			elif fname == 'done':
				# Gemini wants to finish - return success with message
				message = args.get('message', 'Task completed')
				self.logger.info(f'  ✅ Done: {message}')
				return {'status': 'done', 'message': message}

			elif fname == 'wait_5_seconds':
				await asyncio.sleep(5)

			elif fname == 'go_back':
				await page.go_back()

			elif fname == 'go_forward':
				await page.go_forward()

			elif fname == 'search':
				await page.goto('https://www.google.com')

			elif fname == 'navigate':
				url = args['url']
				await page.goto(url)

			elif fname == 'click_at':
				actual_x = self.denormalize_x(args['x'])
				actual_y = self.denormalize_y(args['y'])
				self.logger.debug(f'  Clicking at ({actual_x}, {actual_y})')
				mouse = await page.mouse
				await mouse.click(actual_x, actual_y)

			elif fname == 'hover_at':
				actual_x = self.denormalize_x(args['x'])
				actual_y = self.denormalize_y(args['y'])
				mouse = await page.mouse
				await mouse.move(actual_x, actual_y)

			elif fname == 'type_text_at':
				actual_x = self.denormalize_x(args['x'])
				actual_y = self.denormalize_y(args['y'])
				text = args['text']
				press_enter = args.get('press_enter', True)  # Default True per spec
				clear_before = args.get('clear_before_typing', True)  # Default True per spec

				# Click to focus using Actor Mouse
				mouse = await page.mouse
				await mouse.click(actual_x, actual_y)
				await asyncio.sleep(0.1)  # Wait for click to register

				# Clear existing text if requested
				if clear_before:
					# Select all and delete (works cross-platform)
					is_mac = platform.system() == 'Darwin'
					select_all_key = 'Meta+A' if is_mac else 'Control+A'
					await page.press(select_all_key)
					await asyncio.sleep(0.05)
					await page.press('Backspace')
					await asyncio.sleep(0.05)

				# Type text using JavaScript
				# This properly handles all special characters
				escaped_text = text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
				await page.evaluate(f"""() => {{
					const el = document.activeElement;
					if (el) {{
						if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {{
							el.value = '{escaped_text}';
							el.dispatchEvent(new Event('input', {{ bubbles: true }}));
							el.dispatchEvent(new Event('change', {{ bubbles: true }}));
						}} else if (el.isContentEditable) {{
							el.textContent = '{escaped_text}';
							el.dispatchEvent(new Event('input', {{ bubbles: true }}));
						}}
					}}
				}}""")

				# Press enter if requested
				if press_enter:
					await asyncio.sleep(0.1)
					await page.press('Enter')

			elif fname == 'key_combination':
				keys = args['keys']
				await page.press(keys)

			elif fname == 'scroll_document':
				direction = args.get('direction', 'down')
				mouse = await page.mouse

				if direction == 'down':
					await mouse.scroll(delta_y=500)
				elif direction == 'up':
					await mouse.scroll(delta_y=-500)
				elif direction == 'left':
					await mouse.scroll(delta_x=-500)
				elif direction == 'right':
					await mouse.scroll(delta_x=500)

			elif fname == 'scroll_at':
				actual_x = self.denormalize_x(args['x'])
				actual_y = self.denormalize_y(args['y'])
				direction = args.get('direction', 'down')
				magnitude = args.get('magnitude', 800)
				actual_magnitude = int(magnitude / 1000 * self.screen_height)

				mouse = await page.mouse

				# Move mouse to position first
				await mouse.move(actual_x, actual_y)

				if direction == 'down':
					await mouse.scroll(x=actual_x, y=actual_y, delta_y=actual_magnitude)
				elif direction == 'up':
					await mouse.scroll(x=actual_x, y=actual_y, delta_y=-actual_magnitude)
				elif direction == 'left':
					await mouse.scroll(x=actual_x, y=actual_y, delta_x=-actual_magnitude)
				elif direction == 'right':
					await mouse.scroll(x=actual_x, y=actual_y, delta_x=actual_magnitude)

			elif fname == 'drag_and_drop':
				start_x = self.denormalize_x(args['x'])
				start_y = self.denormalize_y(args['y'])
				dest_x = self.denormalize_x(args['destination_x'])
				dest_y = self.denormalize_y(args['destination_y'])

				mouse = await page.mouse
				await mouse.move(start_x, start_y)
				await mouse.down()
				await mouse.move(dest_x, dest_y)
				await mouse.up()

			elif fname == 'get_browser_state':
				# Return page URL and text content for content extraction
				url = await page.get_url()
				text_content = await page.evaluate('document.body.innerText || document.body.textContent || ""')
				if len(text_content) > 5000:
					text_content = text_content[:5000] + '...(truncated)'
				self.logger.info(f'  📄 get_browser_state: URL={url}, text_len={len(text_content)}')
				return {
					'status': 'success',
					'url': url,
					'text_content': text_content,
					'message': f'URL: {url}\n\nPage text:\n{text_content}',
				}

			else:
				self.logger.warning(f'⚠️  Unimplemented Computer Use action: {fname}')
				return {'error': f'Unimplemented action: {fname}'}

			# Wait for page to settle - using Actor Page API
			# Actor Page doesn't have wait_for_load_state, so we'll just sleep
			await asyncio.sleep(0.5)  # Brief pause for animations and page updates

			return {'status': 'success'}

		except Exception as e:
			self.logger.error(f'❌ Error executing {fname}: {e}')
			return {'error': str(e)}
