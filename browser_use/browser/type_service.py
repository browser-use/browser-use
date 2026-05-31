from __future__ import annotations

import asyncio
import json
from typing import Any

from browser_use.browser.click_service import ClickService
from browser_use.browser.service_base import BrowserService
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode


class TypeService(BrowserService):
	"""Text entry operations."""

	async def type_index(
		self,
		index: int,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict[str, Any] | None:
		node = await self.browser_session.get_element_by_index(index)
		if node is None:
			raise ValueError(f'No element found for index {index}')
		return await self.type_node(
			node,
			text,
			clear=clear,
			is_sensitive=is_sensitive,
			sensitive_key_name=sensitive_key_name,
		)

	async def type_node(
		self,
		node: EnhancedDOMTreeNode,
		text: str,
		*,
		clear: bool = True,
		is_sensitive: bool = False,
		sensitive_key_name: str | None = None,
	) -> dict[str, Any] | None:
		"""Type text into an element, falling back to the focused page when needed."""
		index_for_logging = node.backend_node_id or 'unknown'

		if not node.backend_node_id or node.backend_node_id == 0:
			await self._type_to_page(text)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(f'⌨️ Typed <{sensitive_key_name}> to the page (current focus)')
				else:
					self.browser_session.logger.info('⌨️ Typed <sensitive> to the page (current focus)')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" to the page (current focus)')
			return None

		try:
			input_metadata = await self._input_text_element_node_impl(
				node,
				text,
				clear=clear or (not text),
				is_sensitive=is_sensitive,
			)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(
						f'⌨️ Typed <{sensitive_key_name}> into element with index {index_for_logging}'
					)
				else:
					self.browser_session.logger.info(f'⌨️ Typed <sensitive> into element with index {index_for_logging}')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" into element with index {index_for_logging}')
			self.browser_session.logger.debug(f'Element xpath: {node.xpath}')
			return input_metadata
		except Exception as exc:
			self.browser_session.logger.warning(
				f'Failed to type to element {index_for_logging}: {exc}. Falling back to page typing.'
			)
			try:
				await asyncio.wait_for(
					ClickService(browser_session=self.browser_session)._click_element_node_impl(node), timeout=10.0
				)
			except Exception:
				pass
			await self._type_to_page(text)
			if is_sensitive:
				if sensitive_key_name:
					self.browser_session.logger.info(f'⌨️ Typed <{sensitive_key_name}> to the page as fallback')
				else:
					self.browser_session.logger.info('⌨️ Typed <sensitive> to the page as fallback')
			else:
				self.browser_session.logger.info(f'⌨️ Typed "{text}" to the page as fallback')
			return None

	async def _type_to_page(self, text: str):
		"""
		Type text to the page (whatever element currently has focus).
		This is used when index is 0 or when an element can't be found.
		"""
		try:
			# Get CDP client and session
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=True)

			# Type the text character by character to the focused element
			for char in text:
				# Handle newline characters as Enter key
				if char == '\n':
					# Send proper Enter key sequence
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
					# Send char event with carriage return
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': '\r',
						},
						session_id=cdp_session.session_id,
					)
					# Send keyup
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
				else:
					# Handle regular characters
					# Send keydown
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': char,
						},
						session_id=cdp_session.session_id,
					)
					# Send char for actual text input
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
						},
						session_id=cdp_session.session_id,
					)
					# Send keyup
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': char,
						},
						session_id=cdp_session.session_id,
					)
				# Add 10ms delay between keystrokes
				await asyncio.sleep(0.010)
		except Exception as e:
			raise Exception(f'Failed to type to page: {str(e)}')

	def _get_char_modifiers_and_vk(self, char: str) -> tuple[int, int, str]:
		"""Get modifiers, virtual key code, and base key for a character.

		Returns:
			(modifiers, windowsVirtualKeyCode, base_key)
		"""
		# Characters that require Shift modifier
		shift_chars = {
			'!': ('1', 49),
			'@': ('2', 50),
			'#': ('3', 51),
			'$': ('4', 52),
			'%': ('5', 53),
			'^': ('6', 54),
			'&': ('7', 55),
			'*': ('8', 56),
			'(': ('9', 57),
			')': ('0', 48),
			'_': ('-', 189),
			'+': ('=', 187),
			'{': ('[', 219),
			'}': (']', 221),
			'|': ('\\', 220),
			':': (';', 186),
			'"': ("'", 222),
			'<': (',', 188),
			'>': ('.', 190),
			'?': ('/', 191),
			'~': ('`', 192),
		}

		# Check if character requires Shift
		if char in shift_chars:
			base_key, vk_code = shift_chars[char]
			return (8, vk_code, base_key)  # Shift=8

		# Some Unicode characters' upper()/lower() expand to multiple code points
		# (e.g. 'ß'.upper() == 'SS', 'ﬃ'.upper() == 'FFI'). ord() rejects those,
		# so fall back to the original char's code point for the VK code.
		def _vk_from(c: str) -> int:
			up = c.upper()
			return ord(up) if len(up) == 1 else ord(c)

		# Uppercase letters require Shift
		if char.isupper():
			return (8, ord(char), char.lower()[:1] or char)  # Shift=8

		# Lowercase letters
		if char.islower():
			return (0, _vk_from(char), char)

		# Numbers
		if char.isdigit():
			return (0, ord(char), char)

		# Special characters without Shift
		no_shift_chars = {
			' ': 32,
			'-': 189,
			'=': 187,
			'[': 219,
			']': 221,
			'\\': 220,
			';': 186,
			"'": 222,
			',': 188,
			'.': 190,
			'/': 191,
			'`': 192,
		}

		if char in no_shift_chars:
			return (0, no_shift_chars[char], char)

		# Fallback
		return (0, _vk_from(char) if char.isalpha() else ord(char), char)

	def _get_key_code_for_char(self, char: str) -> str:
		"""Get the proper key code for a character (like Playwright does)."""
		# Key code mapping for common characters (using proper base keys + modifiers)
		key_codes = {
			' ': 'Space',
			'.': 'Period',
			',': 'Comma',
			'-': 'Minus',
			'_': 'Minus',  # Underscore uses Minus with Shift
			'@': 'Digit2',  # @ uses Digit2 with Shift
			'!': 'Digit1',  # ! uses Digit1 with Shift (not 'Exclamation')
			'?': 'Slash',  # ? uses Slash with Shift
			':': 'Semicolon',  # : uses Semicolon with Shift
			';': 'Semicolon',
			'(': 'Digit9',  # ( uses Digit9 with Shift
			')': 'Digit0',  # ) uses Digit0 with Shift
			'[': 'BracketLeft',
			']': 'BracketRight',
			'{': 'BracketLeft',  # { uses BracketLeft with Shift
			'}': 'BracketRight',  # } uses BracketRight with Shift
			'/': 'Slash',
			'\\': 'Backslash',
			'=': 'Equal',
			'+': 'Equal',  # + uses Equal with Shift
			'*': 'Digit8',  # * uses Digit8 with Shift
			'&': 'Digit7',  # & uses Digit7 with Shift
			'%': 'Digit5',  # % uses Digit5 with Shift
			'$': 'Digit4',  # $ uses Digit4 with Shift
			'#': 'Digit3',  # # uses Digit3 with Shift
			'^': 'Digit6',  # ^ uses Digit6 with Shift
			'~': 'Backquote',  # ~ uses Backquote with Shift
			'`': 'Backquote',
			"'": 'Quote',
			'"': 'Quote',  # " uses Quote with Shift
		}

		# Numbers
		if char.isdigit():
			return f'Digit{char}'

		# Letters
		if char.isalpha():
			return f'Key{char.upper()}'

		# Special characters
		if char in key_codes:
			return key_codes[char]

		# Fallback for unknown characters
		return f'Key{char.upper()}'

	async def _clear_text_field(self, object_id: str, cdp_session) -> bool:
		"""Clear text field using multiple strategies, starting with the most reliable."""
		try:
			# Strategy 1: Direct JavaScript value/content setting (handles both inputs and contenteditable)
			self.logger.debug('🧹 Clearing text field using JavaScript value setting')

			clear_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': """
						function() {
							// Check if it's a contenteditable element
							const hasContentEditable = this.getAttribute('contenteditable') === 'true' ||
													this.getAttribute('contenteditable') === '' ||
													this.isContentEditable === true;

							if (hasContentEditable) {
								// For contenteditable elements, clear all content
								while (this.firstChild) {
									this.removeChild(this.firstChild);
								}
								this.textContent = "";
								this.innerHTML = "";

								// Focus and position cursor at the beginning
								this.focus();
								const selection = window.getSelection();
								const range = document.createRange();
								range.setStart(this, 0);
								range.setEnd(this, 0);
								selection.removeAllRanges();
								selection.addRange(range);

								// Dispatch events
								this.dispatchEvent(new Event("input", { bubbles: true }));
								this.dispatchEvent(new Event("change", { bubbles: true }));

								return {cleared: true, method: 'contenteditable', finalText: this.textContent};
							} else if (this.value !== undefined) {
								// For regular inputs with value property
								try {
									this.select();
								} catch (e) {
									// ignore
								}
								this.value = "";
								this.dispatchEvent(new Event("input", { bubbles: true }));
								this.dispatchEvent(new Event("change", { bubbles: true }));
								return {cleared: true, method: 'value', finalText: this.value};
							} else {
								return {cleared: false, method: 'none', error: 'Not a supported input type'};
							}
						}
					""",
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			# Check the clear result
			clear_info = clear_result.get('result', {}).get('value', {})
			self.logger.debug(f'Clear result: {clear_info}')

			if clear_info.get('cleared'):
				final_text = clear_info.get('finalText', '')
				if not final_text or not final_text.strip():
					self.logger.debug(f'✅ Text field cleared successfully using {clear_info.get("method")}')
					return True
				else:
					self.logger.debug(f'⚠️ JavaScript clear partially failed, field still contains: "{final_text}"')
			else:
				self.logger.debug(f'❌ JavaScript clear failed: {clear_info.get("error", "Unknown error")}')

		except Exception as e:
			self.logger.debug(f'JavaScript clear failed with exception: {e}')
			return False

		# Strategy 2: Triple-click + Delete (fallback for stubborn fields)
		try:
			self.logger.debug('🧹 Fallback: Clearing using triple-click + Delete')

			# Get element center coordinates for triple-click
			bounds_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.getBoundingClientRect(); }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			if bounds_result.get('result', {}).get('value'):
				bounds = bounds_result['result']['value']
				center_x = bounds['x'] + bounds['width'] / 2
				center_y = bounds['y'] + bounds['height'] / 2

				# Triple-click to select all text
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=cdp_session.session_id,
				)

				# Delete selected text
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=cdp_session.session_id,
				)

				self.logger.debug('✅ Text field cleared using triple-click + Delete')
				return True

		except Exception as e:
			self.logger.debug(f'Triple-click clear failed: {e}')

		# Strategy 3: Keyboard shortcuts (last resort)
		try:
			import platform

			is_macos = platform.system() == 'Darwin'
			select_all_modifier = 4 if is_macos else 2  # Meta=4 (Cmd), Ctrl=2
			modifier_name = 'Cmd' if is_macos else 'Ctrl'

			self.logger.debug(f'🧹 Last resort: Clearing using {modifier_name}+A + Backspace')

			# Select all text (Ctrl/Cmd+A)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyDown',
					'key': 'a',
					'code': 'KeyA',
					'modifiers': select_all_modifier,
				},
				session_id=cdp_session.session_id,
			)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyUp',
					'key': 'a',
					'code': 'KeyA',
					'modifiers': select_all_modifier,
				},
				session_id=cdp_session.session_id,
			)

			# Delete selected text (Backspace)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyDown',
					'key': 'Backspace',
					'code': 'Backspace',
				},
				session_id=cdp_session.session_id,
			)
			await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
				params={
					'type': 'keyUp',
					'key': 'Backspace',
					'code': 'Backspace',
				},
				session_id=cdp_session.session_id,
			)

			self.logger.debug('✅ Text field cleared using keyboard shortcuts')
			return True

		except Exception as e:
			self.logger.debug(f'All clearing strategies failed: {e}')
			return False

	async def _focus_element_simple(
		self, backend_node_id: int, object_id: str, cdp_session, input_coordinates: dict | None = None
	) -> bool:
		"""Simple focus strategy: CDP first, then click if failed."""

		# Strategy 1: Try CDP DOM.focus first
		try:
			result = await cdp_session.cdp_client.send.DOM.focus(
				params={'backendNodeId': backend_node_id},
				session_id=cdp_session.session_id,
			)
			self.logger.debug(f'Element focused using CDP DOM.focus (result: {result})')
			return True

		except Exception as e:
			self.logger.debug(f'❌ CDP DOM.focus threw exception: {type(e).__name__}: {e}')

		# Strategy 2: Try click to focus if CDP failed
		if input_coordinates and 'input_x' in input_coordinates and 'input_y' in input_coordinates:
			try:
				click_x = input_coordinates['input_x']
				click_y = input_coordinates['input_y']

				self.logger.debug(f'🎯 Attempting click-to-focus at ({click_x:.1f}, {click_y:.1f})')

				# Click to focus
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': click_x,
						'y': click_y,
						'button': 'left',
						'clickCount': 1,
					},
					session_id=cdp_session.session_id,
				)
				await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': click_x,
						'y': click_y,
						'button': 'left',
						'clickCount': 1,
					},
					session_id=cdp_session.session_id,
				)

				self.logger.debug('✅ Element focused using click method')
				return True

			except Exception as e:
				self.logger.debug(f'Click focus failed: {e}')

		# Both strategies failed
		self.logger.debug('Focus strategies failed, will attempt typing anyway')
		return False

	def _requires_direct_value_assignment(self, element_node: EnhancedDOMTreeNode) -> bool:
		"""
		Check if an element requires direct value assignment instead of character-by-character typing.

		Certain input types have compound components, custom plugins, or special requirements
		that make character-by-character typing unreliable. These need direct .value assignment:

		Native HTML5:
		- date, time, datetime-local: Have spinbutton components (ISO format required)
		- month, week: Similar compound structure
		- color: Expects hex format #RRGGBB
		- range: Needs numeric value within min/max

		jQuery/Bootstrap Datepickers:
		- Detected by class names or data attributes
		- Often expect specific date formats (MM/DD/YYYY, DD/MM/YYYY, etc.)

		Note: We use direct assignment because:
		1. Typing triggers intermediate validation that might reject partial values
		2. Compound components (like date spinbuttons) don't work with sequential typing
		3. It's much faster and more reliable
		4. We dispatch proper input/change events afterward to trigger listeners
		"""
		if not element_node.tag_name or not element_node.attributes:
			return False

		tag_name = element_node.tag_name.lower()

		# Check for native HTML5 inputs that need direct assignment
		if tag_name == 'input':
			input_type = element_node.attributes.get('type', '').lower()

			# Native HTML5 inputs with compound components or strict formats
			if input_type in {'date', 'time', 'datetime-local', 'month', 'week', 'color', 'range'}:
				return True

			# Detect jQuery/Bootstrap datepickers (text inputs with datepicker plugins)
			if input_type in {'text', ''}:
				# Check for common datepicker indicators
				class_attr = element_node.attributes.get('class', '').lower()
				if any(
					indicator in class_attr
					for indicator in ['datepicker', 'daterangepicker', 'datetimepicker', 'bootstrap-datepicker']
				):
					return True

				# Check for data attributes indicating datepickers
				if any(attr in element_node.attributes for attr in ['data-datepicker', 'data-date-format', 'data-provide']):
					return True

		return False

	async def _set_value_directly(self, element_node: EnhancedDOMTreeNode, text: str, object_id: str, cdp_session) -> None:
		"""
		Set element value directly using JavaScript for inputs that don't support typing.

		This is used for:
		- Date/time inputs where character-by-character typing doesn't work
		- jQuery datepickers that need direct value assignment
		- Color/range inputs that need specific formats
		- Any input with custom plugins that intercept typing

		After setting the value, we dispatch comprehensive events to ensure all frameworks
		and plugins recognize the change (React, Vue, Angular, jQuery, etc.)
		"""
		try:
			# Set the value using JavaScript with comprehensive event dispatching
			# callFunctionOn expects a function body (not a self-invoking function)
			set_value_js = f"""
			function() {{
				// Store old value for comparison
				const oldValue = this.value;

				// REACT-COMPATIBLE VALUE SETTING:
				// React uses Object.getOwnPropertyDescriptor to track input changes
				// We need to use the native setter to bypass React's tracking and then trigger events
				const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
					window.HTMLInputElement.prototype,
					'value'
				).set;

				// Set the value using the native setter (bypasses React's control)
				nativeInputValueSetter.call(this, {json.dumps(text)});

				// Dispatch comprehensive events to ensure all frameworks detect the change
				// Order matters: focus -> input -> change -> blur (mimics user interaction)

				// 1. Focus event (in case element isn't focused)
				this.dispatchEvent(new FocusEvent('focus', {{ bubbles: true }}));

				// 2. Input event (CRITICAL for React onChange)
				// React listens to 'input' events on the document and checks for value changes
				const inputEvent = new Event('input', {{ bubbles: true, cancelable: true }});
				this.dispatchEvent(inputEvent);

				// 3. Change event (for form handling, traditional listeners)
				const changeEvent = new Event('change', {{ bubbles: true, cancelable: true }});
				this.dispatchEvent(changeEvent);

				// 4. Blur event (triggers final validation in some libraries)
				this.dispatchEvent(new FocusEvent('blur', {{ bubbles: true }}));

				// 5. jQuery-specific events (if jQuery is present)
				if (typeof jQuery !== 'undefined' && jQuery.fn) {{
					try {{
						jQuery(this).trigger('change');
						// Trigger datepicker-specific events if it's a datepicker
						if (jQuery(this).data('datepicker')) {{
							jQuery(this).datepicker('update');
						}}
					}} catch (e) {{
						// jQuery not available or error, continue anyway
					}}
				}}

				return this.value;
			}}
			"""

			result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': set_value_js,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			# Verify the value was set correctly
			if 'result' in result and 'value' in result['result']:
				actual_value = result['result']['value']
				self.logger.debug(f'✅ Value set directly to: "{actual_value}"')
			else:
				self.logger.warning('⚠️ Could not verify value was set correctly')

		except Exception as e:
			self.logger.error(f'❌ Failed to set value directly: {e}')
			raise

	async def _input_text_element_node_impl(
		self, element_node: EnhancedDOMTreeNode, text: str, clear: bool = True, is_sensitive: bool = False
	) -> dict | None:
		"""
		Input text into an element using pure CDP with improved focus fallbacks.

		For date/time inputs, uses direct value assignment instead of typing.
		"""

		try:
			# Get CDP client
			cdp_client = self.browser_session.cdp_client

			# Get the correct session ID for the element's iframe
			# session_id = await self._get_session_id_for_element(element_node)

			# cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=element_node.target_id, focus=True)
			cdp_session = await self.browser_session.cdp_client_for_node(element_node)

			# Get element info
			backend_node_id = element_node.backend_node_id

			# Track coordinates for metadata
			input_coordinates = None

			# Scroll element into view
			try:
				await cdp_session.cdp_client.send.DOM.scrollIntoViewIfNeeded(
					params={'backendNodeId': backend_node_id}, session_id=cdp_session.session_id
				)
				await asyncio.sleep(0.01)
			except Exception as e:
				# Node detached errors are common with shadow DOM and dynamic content
				# The element can still be interacted with even if scrolling fails
				error_str = str(e)
				if 'Node is detached from document' in error_str or 'detached from document' in error_str:
					self.logger.debug(
						f'Element node temporarily detached during scroll (common with shadow DOM), continuing: {element_node}'
					)
				else:
					self.logger.debug(f'Failed to scroll element {element_node} into view before typing: {type(e).__name__}: {e}')

			# Get object ID for the element
			result = await cdp_client.send.DOM.resolveNode(
				params={'backendNodeId': backend_node_id},
				session_id=cdp_session.session_id,
			)
			assert 'object' in result and 'objectId' in result['object'], (
				'Failed to find DOM element based on backendNodeId, maybe page content changed?'
			)
			object_id = result['object']['objectId']

			# Get current coordinates using unified method
			coords = await self.browser_session.get_element_coordinates(backend_node_id, cdp_session)
			if coords:
				center_x = coords.x + coords.width / 2
				center_y = coords.y + coords.height / 2

				# Check for occlusion before using coordinates for focus
				is_occluded = await self._check_element_occlusion(backend_node_id, center_x, center_y, cdp_session)

				if is_occluded:
					self.logger.debug('🚫 Input element is occluded, skipping coordinate-based focus')
					input_coordinates = None  # Force fallback to CDP-only focus
				else:
					input_coordinates = {'input_x': center_x, 'input_y': center_y}
					self.logger.debug(f'Using unified coordinates: x={center_x:.1f}, y={center_y:.1f}')
			else:
				input_coordinates = None
				self.logger.debug('No coordinates found for element')

			# Ensure we have a valid object_id before proceeding
			if not object_id:
				raise ValueError('Could not get object_id for element')

			# Step 1: Focus the element using simple strategy
			focused_successfully = await self._focus_element_simple(
				backend_node_id=backend_node_id, object_id=object_id, cdp_session=cdp_session, input_coordinates=input_coordinates
			)

			# Step 2: Check if this element requires direct value assignment (date/time inputs)
			requires_direct_assignment = self._requires_direct_value_assignment(element_node)

			if requires_direct_assignment:
				# Date/time inputs: use direct value assignment instead of typing
				self.logger.debug(
					f'🎯 Element type={element_node.attributes.get("type")} requires direct value assignment, setting value directly'
				)
				await self._set_value_directly(element_node, text, object_id, cdp_session)

				# Return input coordinates for metadata
				return input_coordinates

			# Step 3: Clear existing text if requested (only for regular inputs that support typing)
			if clear:
				cleared_successfully = await self._clear_text_field(object_id=object_id, cdp_session=cdp_session)
				if not cleared_successfully:
					self.logger.warning('⚠️ Text field clearing failed, typing may append to existing text')

			# Step 4: Type the text character by character using proper human-like key events
			# This emulates exactly how a human would type, which modern websites expect
			if is_sensitive:
				# Note: sensitive_key_name is not passed to this low-level method,
				# but we could extend the signature if needed for more granular logging
				self.logger.debug('🎯 Typing <sensitive> character by character')
			else:
				self.logger.debug(f'🎯 Typing text character by character: "{text}"')

			# Detect contenteditable elements (may have leaf-start bug where first char is dropped)
			_attrs = element_node.attributes or {}
			_is_contenteditable = _attrs.get('contenteditable') in ('true', '') or (
				_attrs.get('role') == 'textbox' and element_node.tag_name not in ('input', 'textarea')
			)

			# For contenteditable: after typing first char, check if dropped and retype if needed
			_check_first_char = _is_contenteditable and len(text) > 0 and clear
			_first_char = text[0] if _check_first_char else None

			for i, char in enumerate(text):
				# Handle newline characters as Enter key
				if char == '\n':
					# Send proper Enter key sequence
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.001)

					# Send char event with carriage return
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': '\r',
							'key': 'Enter',
						},
						session_id=cdp_session.session_id,
					)

					# Send keyUp event
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=cdp_session.session_id,
					)
				else:
					# Handle regular characters
					# Get proper modifiers, VK code, and base key for the character
					modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(char)
					key_code = self._get_key_code_for_char(base_key)

					# self.logger.debug(f'🎯 Typing character {i + 1}/{len(text)}: "{char}" (base_key: {base_key}, code: {key_code}, modifiers: {modifiers}, vk: {vk_code})')

					# Step 1: Send keyDown event (NO text parameter)
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=cdp_session.session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.005)

					# Step 2: Send char event (WITH text parameter) - this is crucial for text input
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
							'key': char,
						},
						session_id=cdp_session.session_id,
					)

					# Step 3: Send keyUp event (NO text parameter)
					await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=cdp_session.session_id,
					)

				# After first char on contenteditable: check if dropped and retype if needed
				if i == 0 and _check_first_char and _first_char:
					check_result = await cdp_session.cdp_client.send.Runtime.evaluate(
						params={'expression': 'document.activeElement.textContent'},
						session_id=cdp_session.session_id,
					)
					content = check_result.get('result', {}).get('value', '')
					if _first_char not in content:
						self.logger.debug(f'🎯 First char "{_first_char}" was dropped (leaf-start bug), retyping')
						# Retype the first character - cursor now past leaf-start
						modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(_first_char)
						key_code = self._get_key_code_for_char(base_key)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={
								'type': 'keyDown',
								'key': base_key,
								'code': key_code,
								'modifiers': modifiers,
								'windowsVirtualKeyCode': vk_code,
							},
							session_id=cdp_session.session_id,
						)
						await asyncio.sleep(0.005)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={'type': 'char', 'text': _first_char, 'key': _first_char},
							session_id=cdp_session.session_id,
						)
						await cdp_session.cdp_client.send.Input.dispatchKeyEvent(
							params={
								'type': 'keyUp',
								'key': base_key,
								'code': key_code,
								'modifiers': modifiers,
								'windowsVirtualKeyCode': vk_code,
							},
							session_id=cdp_session.session_id,
						)

				# Small delay between characters to look human (realistic typing speed)
				await asyncio.sleep(0.001)

			# Step 4: Trigger framework-aware DOM events after typing completion
			# Modern JavaScript frameworks (React, Vue, Angular) rely on these events
			# to update their internal state and trigger re-renders
			await self._trigger_framework_events(object_id=object_id, cdp_session=cdp_session)

			# Step 5: Read back actual value for verification (skip for sensitive data)
			if not is_sensitive:
				try:
					await asyncio.sleep(0.05)  # let autocomplete/formatter JS settle
					readback_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'objectId': object_id,
							'functionDeclaration': 'function() { return this.value !== undefined ? this.value : this.textContent; }',
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)
					actual_value = readback_result.get('result', {}).get('value')
					if actual_value is not None:
						if input_coordinates is None:
							input_coordinates = {}
						input_coordinates['actual_value'] = actual_value
				except Exception as e:
					self.logger.debug(f'Value readback failed (non-critical): {e}')

			# Step 6: Auto-retry on concatenation mismatch (only when clear was requested)
			# If we asked to clear but the readback value contains the typed text as a substring
			# yet is longer, the field had pre-existing text that wasn't cleared. Set directly.
			if clear and not is_sensitive and input_coordinates and 'actual_value' in input_coordinates:
				actual_value = input_coordinates['actual_value']
				if (
					isinstance(actual_value, str)
					and actual_value != text
					and len(actual_value) > len(text)
					and (actual_value.endswith(text) or actual_value.startswith(text))
				):
					self.logger.info(f'🔄 Concatenation detected: got "{actual_value}", expected "{text}" — auto-retrying')
					try:
						# Clear + set value via native setter in one JS call (works with React/Vue)
						retry_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
							params={
								'objectId': object_id,
								'functionDeclaration': """
									function(newValue) {
										if (this.value !== undefined) {
											var desc = Object.getOwnPropertyDescriptor(
												HTMLInputElement.prototype, 'value'
											) || Object.getOwnPropertyDescriptor(
												HTMLTextAreaElement.prototype, 'value'
											);
											if (desc && desc.set) {
												desc.set.call(this, newValue);
											} else {
												this.value = newValue;
											}
										} else if (this.isContentEditable) {
											this.textContent = newValue;
										}
										this.dispatchEvent(new Event('input', { bubbles: true }));
										this.dispatchEvent(new Event('change', { bubbles: true }));
										return this.value !== undefined ? this.value : this.textContent;
									}
								""",
								'arguments': [{'value': text}],
								'returnByValue': True,
							},
							session_id=cdp_session.session_id,
						)
						retry_value = retry_result.get('result', {}).get('value')
						if retry_value is not None:
							input_coordinates['actual_value'] = retry_value
							if retry_value == text:
								self.logger.info('✅ Auto-retry fixed concatenation')
							else:
								self.logger.warning(f'⚠️ Auto-retry value still differs: "{retry_value}"')
					except Exception as e:
						self.logger.debug(f'Auto-retry failed (non-critical): {e}')

			# Return coordinates metadata if available
			return input_coordinates

		except Exception as e:
			self.logger.error(f'Failed to input text via CDP: {type(e).__name__}: {e}')
			raise BrowserError(f'Failed to input text into element: {repr(element_node)}')

	async def _trigger_framework_events(self, object_id: str, cdp_session) -> None:
		"""
		Trigger framework-aware DOM events after text input completion.

		This is critical for modern JavaScript frameworks (React, Vue, Angular, etc.)
		that rely on DOM events to update their internal state and trigger re-renders.

		Args:
			object_id: CDP object ID of the input element
			cdp_session: CDP session for the element's context
		"""
		try:
			# Execute JavaScript to trigger comprehensive event sequence
			framework_events_script = """
			function() {
				// Find the target element (available as 'this' when using objectId)
				const element = this;
				if (!element) return false;

				// Ensure element is focused
				element.focus();

				// Comprehensive event sequence for maximum framework compatibility
				const events = [
					// Input event - primary event for React controlled components
					{ type: 'input', bubbles: true, cancelable: true },
					// Change event - important for form validation and Vue v-model
					{ type: 'change', bubbles: true, cancelable: true },
					// Blur event - triggers validation in many frameworks
					{ type: 'blur', bubbles: true, cancelable: true }
				];

				let success = true;

				events.forEach(eventConfig => {
					try {
						const event = new Event(eventConfig.type, {
							bubbles: eventConfig.bubbles,
							cancelable: eventConfig.cancelable
						});

						// Special handling for InputEvent (more specific than Event)
						if (eventConfig.type === 'input') {
							const inputEvent = new InputEvent('input', {
								bubbles: true,
								cancelable: true,
								data: element.value,
								inputType: 'insertText'
							});
							element.dispatchEvent(inputEvent);
						} else {
							element.dispatchEvent(event);
						}
					} catch (e) {
						success = false;
						console.warn('Framework event dispatch failed:', eventConfig.type, e);
					}
				});

				// Special React synthetic event handling
				// React uses internal fiber properties for event system
				if (element._reactInternalFiber || element._reactInternalInstance || element.__reactInternalInstance) {
					try {
						// Trigger React's synthetic event system
						const syntheticInputEvent = new InputEvent('input', {
							bubbles: true,
							cancelable: true,
							data: element.value
						});

						// Force React to process this as a synthetic event
						Object.defineProperty(syntheticInputEvent, 'isTrusted', { value: true });
						element.dispatchEvent(syntheticInputEvent);
					} catch (e) {
						console.warn('React synthetic event failed:', e);
					}
				}

				// Special Vue reactivity trigger
				// Vue uses __vueParentComponent or __vue__ for component access
				if (element.__vue__ || element._vnode || element.__vueParentComponent) {
					try {
						// Vue often needs explicit input event with proper timing
						const vueEvent = new Event('input', { bubbles: true });
						setTimeout(() => element.dispatchEvent(vueEvent), 0);
					} catch (e) {
						console.warn('Vue reactivity trigger failed:', e);
					}
				}

				return success;
			}
			"""

			# Execute the framework events script
			result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': framework_events_script,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			success = result.get('result', {}).get('value', False)
			if success:
				self.logger.debug('✅ Framework events triggered successfully')
			else:
				self.logger.warning('⚠️ Failed to trigger framework events')

		except Exception as e:
			self.logger.warning(f'⚠️ Failed to trigger framework events: {type(e).__name__}: {e}')
			# Don't raise - framework events are a best-effort enhancement
