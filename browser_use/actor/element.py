"""Element class for element operations."""

import asyncio
from typing import TYPE_CHECKING, Literal, Union

from cdp_use.client import logger
from typing_extensions import TypedDict

if TYPE_CHECKING:
	from cdp_use.cdp.dom.commands import (
		DescribeNodeParameters,
		FocusParameters,
		GetAttributesParameters,
		GetBoxModelParameters,
		PushNodesByBackendIdsToFrontendParameters,
		RequestChildNodesParameters,
		ResolveNodeParameters,
	)
	from cdp_use.cdp.input.commands import (
		DispatchMouseEventParameters,
	)
	from cdp_use.cdp.input.types import MouseButton
	from cdp_use.cdp.page.commands import CaptureScreenshotParameters
	from cdp_use.cdp.page.types import Viewport

	from browser_use.browser.session import BrowserSession

# Type definitions for element operations
ModifierType = Literal['Alt', 'Control', 'Meta', 'Shift']


class Position(TypedDict):
	"""2D position coordinates."""

	x: float
	y: float


class BoundingBox(TypedDict):
	"""Element bounding box with position and dimensions."""

	x: float
	y: float
	width: float
	height: float


class ElementInfo(TypedDict):
	"""Basic information about a DOM element."""

	backendNodeId: int
	nodeId: int | None
	nodeName: str
	nodeType: int
	nodeValue: str | None
	attributes: dict[str, str]
	boundingBox: BoundingBox | None
	error: str | None


class Element:
	"""Element operations using BackendNodeId."""

	def __init__(
		self,
		browser_session: 'BrowserSession',
		backend_node_id: int,
		session_id: str | None = None,
	):
		self._browser_session = browser_session
		self._client = browser_session.cdp_client
		self._backend_node_id = backend_node_id
		self._session_id = session_id

	async def _get_node_id(self) -> int:
		"""Get DOM node ID from backend node ID."""
		params: 'PushNodesByBackendIdsToFrontendParameters' = {'backendNodeIds': [self._backend_node_id]}
		result = await self._client.send.DOM.pushNodesByBackendIdsToFrontend(params, session_id=self._session_id)
		return result['nodeIds'][0]

	async def _get_remote_object_id(self) -> str | None:
		"""Get remote object ID for this element."""
		node_id = await self._get_node_id()
		params: 'ResolveNodeParameters' = {'nodeId': node_id}
		result = await self._client.send.DOM.resolveNode(params, session_id=self._session_id)
		object_id = result['object'].get('objectId', None)

		if not object_id:
			return None
		return object_id

	async def click(
		self,
		button: 'MouseButton' = 'left',
		click_count: int = 1,
		modifiers: list[ModifierType] | None = None,
	) -> None:
		"""Click the element using the advanced watchdog implementation."""

		try:
			# Get viewport dimensions for visibility checks
			layout_metrics = await self._client.send.Page.getLayoutMetrics(session_id=self._session_id)
			viewport_width = layout_metrics['layoutViewport']['clientWidth']
			viewport_height = layout_metrics['layoutViewport']['clientHeight']

			# Try multiple methods to get element geometry
			quads = []

			# Method 1: Try DOM.getContentQuads first (best for inline elements and complex layouts)
			try:
				content_quads_result = await self._client.send.DOM.getContentQuads(
					params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
				)
				if 'quads' in content_quads_result and content_quads_result['quads']:
					quads = content_quads_result['quads']
			except Exception:
				pass

			# Method 2: Fall back to DOM.getBoxModel
			if not quads:
				try:
					box_model = await self._client.send.DOM.getBoxModel(
						params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
					)
					if 'model' in box_model and 'content' in box_model['model']:
						content_quad = box_model['model']['content']
						if len(content_quad) >= 8:
							# Convert box model format to quad format
							quads = [
								[
									content_quad[0],
									content_quad[1],  # x1, y1
									content_quad[2],
									content_quad[3],  # x2, y2
									content_quad[4],
									content_quad[5],  # x3, y3
									content_quad[6],
									content_quad[7],  # x4, y4
								]
							]
				except Exception:
					pass

			# Method 3: Fall back to JavaScript getBoundingClientRect
			if not quads:
				try:
					result = await self._client.send.DOM.resolveNode(
						params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
					)
					if 'object' in result and 'objectId' in result['object']:
						object_id = result['object']['objectId']

						# Get bounding rect via JavaScript
						bounds_result = await self._client.send.Runtime.callFunctionOn(
							params={
								'functionDeclaration': """
									function() {
										const rect = this.getBoundingClientRect();
										return {
											x: rect.left,
											y: rect.top,
											width: rect.width,
											height: rect.height
										};
									}
								""",
								'objectId': object_id,
								'returnByValue': True,
							},
							session_id=self._session_id,
						)

						if 'result' in bounds_result and 'value' in bounds_result['result']:
							rect = bounds_result['result']['value']
							# Convert rect to quad format
							x, y, w, h = rect['x'], rect['y'], rect['width'], rect['height']
							quads = [
								[
									x,
									y,  # top-left
									x + w,
									y,  # top-right
									x + w,
									y + h,  # bottom-right
									x,
									y + h,  # bottom-left
								]
							]
				except Exception:
					pass

			# If we still don't have quads, fall back to JS click
			if not quads:
				try:
					result = await self._client.send.DOM.resolveNode(
						params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
					)
					if 'object' not in result or 'objectId' not in result['object']:
						raise Exception('Failed to find DOM element based on backendNodeId, maybe page content changed?')
					object_id = result['object']['objectId']

					await self._client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=self._session_id,
					)
					await asyncio.sleep(0.05)
					return
				except Exception as js_e:
					raise Exception(f'Failed to click element: {js_e}')

			# Find the largest visible quad within the viewport
			best_quad = None
			best_area = 0

			for quad in quads:
				if len(quad) < 8:
					continue

				# Calculate quad bounds
				xs = [quad[i] for i in range(0, 8, 2)]
				ys = [quad[i] for i in range(1, 8, 2)]
				min_x, max_x = min(xs), max(xs)
				min_y, max_y = min(ys), max(ys)

				# Check if quad intersects with viewport
				if max_x < 0 or max_y < 0 or min_x > viewport_width or min_y > viewport_height:
					continue  # Quad is completely outside viewport

				# Calculate visible area (intersection with viewport)
				visible_min_x = max(0, min_x)
				visible_max_x = min(viewport_width, max_x)
				visible_min_y = max(0, min_y)
				visible_max_y = min(viewport_height, max_y)

				visible_width = visible_max_x - visible_min_x
				visible_height = visible_max_y - visible_min_y
				visible_area = visible_width * visible_height

				if visible_area > best_area:
					best_area = visible_area
					best_quad = quad

			if not best_quad:
				# No visible quad found, use the first quad anyway
				best_quad = quads[0]

			# Calculate center point of the best quad
			center_x = sum(best_quad[i] for i in range(0, 8, 2)) / 4
			center_y = sum(best_quad[i] for i in range(1, 8, 2)) / 4

			# Ensure click point is within viewport bounds
			center_x = max(0, min(viewport_width - 1, center_x))
			center_y = max(0, min(viewport_height - 1, center_y))

			# Scroll element into view
			try:
				await self._client.send.DOM.scrollIntoViewIfNeeded(
					params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
				)
				await asyncio.sleep(0.05)  # Wait for scroll to complete
			except Exception:
				pass

			# Calculate modifier bitmask for CDP
			modifier_value = 0
			if modifiers:
				modifier_map = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
				for mod in modifiers:
					modifier_value |= modifier_map.get(mod, 0)

			# Perform the click using CDP
			try:
				# Move mouse to element
				await self._client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseMoved',
						'x': center_x,
						'y': center_y,
					},
					session_id=self._session_id,
				)
				await asyncio.sleep(0.05)

				# Mouse down
				try:
					await asyncio.wait_for(
						self._client.send.Input.dispatchMouseEvent(
							params={
								'type': 'mousePressed',
								'x': center_x,
								'y': center_y,
								'button': button,
								'clickCount': click_count,
								'modifiers': modifier_value,
							},
							session_id=self._session_id,
						),
						timeout=1.0,  # 1 second timeout for mousePressed
					)
					await asyncio.sleep(0.08)
				except TimeoutError:
					pass  # Don't sleep if we timed out

				# Mouse up
				try:
					await asyncio.wait_for(
						self._client.send.Input.dispatchMouseEvent(
							params={
								'type': 'mouseReleased',
								'x': center_x,
								'y': center_y,
								'button': button,
								'clickCount': click_count,
								'modifiers': modifier_value,
							},
							session_id=self._session_id,
						),
						timeout=3.0,  # 3 second timeout for mouseReleased
					)
				except TimeoutError:
					pass

			except Exception as e:
				# Fall back to JavaScript click via CDP
				try:
					result = await self._client.send.DOM.resolveNode(
						params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
					)
					if 'object' not in result or 'objectId' not in result['object']:
						raise Exception('Failed to find DOM element based on backendNodeId, maybe page content changed?')
					object_id = result['object']['objectId']

					await self._client.send.Runtime.callFunctionOn(
						params={
							'functionDeclaration': 'function() { this.click(); }',
							'objectId': object_id,
						},
						session_id=self._session_id,
					)
					await asyncio.sleep(0.1)
					return
				except Exception as js_e:
					raise Exception(f'Failed to click element: {e}')

		except Exception as e:
			# Extract key element info for error message
			raise RuntimeError(f'Failed to click element: {e}')

	async def fill(self, value: str, clear: bool = True) -> None:
		"""Fill the input element using proper CDP methods with improved focus handling."""
		try:
			# Use the existing CDP client and session
			cdp_client = self._client
			session_id = self._session_id
			backend_node_id = self._backend_node_id

			# Track coordinates for metadata
			input_coordinates = None

			# Scroll element into view
			try:
				await cdp_client.send.DOM.scrollIntoViewIfNeeded(params={'backendNodeId': backend_node_id}, session_id=session_id)
				await asyncio.sleep(0.01)
			except Exception as e:
				logger.warning(f'Failed to scroll element into view: {e}')

			# Get object ID for the element
			result = await cdp_client.send.DOM.resolveNode(
				params={'backendNodeId': backend_node_id},
				session_id=session_id,
			)
			if 'object' not in result or 'objectId' not in result['object']:
				raise RuntimeError('Failed to get object ID for element')
			object_id = result['object']['objectId']

			# Get element coordinates for focus
			try:
				bounds_result = await cdp_client.send.Runtime.callFunctionOn(
					params={
						'functionDeclaration': 'function() { return this.getBoundingClientRect(); }',
						'objectId': object_id,
						'returnByValue': True,
					},
					session_id=session_id,
				)
				if bounds_result.get('result', {}).get('value'):
					bounds = bounds_result['result']['value']  # type: ignore
					center_x = bounds['x'] + bounds['width'] / 2
					center_y = bounds['y'] + bounds['height'] / 2
					input_coordinates = {'input_x': center_x, 'input_y': center_y}
					logger.debug(f'Using element coordinates: x={center_x:.1f}, y={center_y:.1f}')
			except Exception as e:
				logger.debug(f'Could not get element coordinates: {e}')

			# Ensure session_id is not None
			if session_id is None:
				raise RuntimeError('Session ID is required for fill operation')

			# Step 1: Focus the element
			focused_successfully = await self._focus_element_simple(
				backend_node_id=backend_node_id,
				object_id=object_id,
				cdp_client=cdp_client,
				session_id=session_id,
				input_coordinates=input_coordinates,
			)

			# Step 2: Clear existing text if requested
			if clear and focused_successfully:
				cleared_successfully = await self._clear_text_field(
					object_id=object_id, cdp_client=cdp_client, session_id=session_id
				)
				if not cleared_successfully:
					logger.warning('Text field clearing failed, typing may append to existing text')

			# Step 3: Type the text character by character using proper human-like key events
			logger.debug(f'Typing text character by character: "{value}"')

			for i, char in enumerate(value):
				# Handle newline characters as Enter key
				if char == '\n':
					# Send proper Enter key sequence
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.001)

					# Send char event with carriage return
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': '\r',
							'key': 'Enter',
						},
						session_id=session_id,
					)

					# Send keyUp event
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': 'Enter',
							'code': 'Enter',
							'windowsVirtualKeyCode': 13,
						},
						session_id=session_id,
					)
				else:
					# Handle regular characters
					# Get proper modifiers, VK code, and base key for the character
					modifiers, vk_code, base_key = self._get_char_modifiers_and_vk(char)
					key_code = self._get_key_code_for_char(base_key)

					# Step 1: Send keyDown event (NO text parameter)
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=session_id,
					)

					# Small delay to emulate human typing speed
					await asyncio.sleep(0.001)

					# Step 2: Send char event (WITH text parameter) - this is crucial for text input
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
							'key': char,
						},
						session_id=session_id,
					)

					# Step 3: Send keyUp event (NO text parameter)
					await cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': base_key,
							'code': key_code,
							'modifiers': modifiers,
							'windowsVirtualKeyCode': vk_code,
						},
						session_id=session_id,
					)

				# Add 18ms delay between keystrokes
				await asyncio.sleep(0.018)

		except Exception as e:
			raise Exception(f'Failed to fill element: {str(e)}')

	async def hover(self) -> None:
		"""Hover over the element."""
		box = await self.get_bounding_box()
		if not box:
			raise RuntimeError('Element is not visible or has no bounding box')

		x = box['x'] + box['width'] / 2
		y = box['y'] + box['height'] / 2

		params: 'DispatchMouseEventParameters' = {'type': 'mouseMoved', 'x': x, 'y': y}
		await self._client.send.Input.dispatchMouseEvent(params, session_id=self._session_id)

	async def focus(self) -> None:
		"""Focus the element."""
		node_id = await self._get_node_id()
		params: 'FocusParameters' = {'nodeId': node_id}
		await self._client.send.DOM.focus(params, session_id=self._session_id)

	async def check(self) -> None:
		"""Check or uncheck a checkbox/radio button."""
		await self.click()

	async def select_option(self, values: str | list[str]) -> None:
		"""Select option(s) in a select element."""
		if isinstance(values, str):
			values = [values]

		# Focus the element first
		try:
			await self.focus()
		except Exception:
			logger.warning('Failed to focus element')

		# For select elements, we need to find option elements and click them
		# This is a simplified approach - in practice, you might need to handle
		# different select types (single vs multi-select) differently
		node_id = await self._get_node_id()

		# Request child nodes to get the options
		params: 'RequestChildNodesParameters' = {'nodeId': node_id, 'depth': 1}
		await self._client.send.DOM.requestChildNodes(params, session_id=self._session_id)

		# Get the updated node description with children
		describe_params: 'DescribeNodeParameters' = {'nodeId': node_id, 'depth': 1}
		describe_result = await self._client.send.DOM.describeNode(describe_params, session_id=self._session_id)

		select_node = describe_result['node']

		# Find and select matching options
		for child in select_node.get('children', []):
			if child.get('nodeName', '').lower() == 'option':
				# Get option attributes
				attrs = child.get('attributes', [])
				option_attrs = {}
				for i in range(0, len(attrs), 2):
					if i + 1 < len(attrs):
						option_attrs[attrs[i]] = attrs[i + 1]

				option_value = option_attrs.get('value', '')
				option_text = child.get('nodeValue', '')

				# Check if this option should be selected
				should_select = option_value in values or option_text in values

				if should_select:
					# Click the option to select it
					option_node_id = child.get('nodeId')
					if option_node_id:
						# Get backend node ID for the option
						option_describe_params: 'DescribeNodeParameters' = {'nodeId': option_node_id}
						option_backend_result = await self._client.send.DOM.describeNode(
							option_describe_params, session_id=self._session_id
						)
						option_backend_id = option_backend_result['node']['backendNodeId']

						# Create an Element for the option and click it
						option_element = Element(self._browser_session, option_backend_id, self._session_id)
						await option_element.click()

	async def drag_to(
		self,
		target: Union['Element', Position],
		source_position: Position | None = None,
		target_position: Position | None = None,
	) -> None:
		"""Drag this element to another element or position."""
		# Get source coordinates
		if source_position:
			source_x = source_position['x']
			source_y = source_position['y']
		else:
			source_box = await self.get_bounding_box()
			if not source_box:
				raise RuntimeError('Source element is not visible')
			source_x = source_box['x'] + source_box['width'] / 2
			source_y = source_box['y'] + source_box['height'] / 2

		# Get target coordinates
		if isinstance(target, dict) and 'x' in target and 'y' in target:
			target_x = target['x']
			target_y = target['y']
		else:
			if target_position:
				target_box = await target.get_bounding_box()
				if not target_box:
					raise RuntimeError('Target element is not visible')
				target_x = target_box['x'] + target_position['x']
				target_y = target_box['y'] + target_position['y']
			else:
				target_box = await target.get_bounding_box()
				if not target_box:
					raise RuntimeError('Target element is not visible')
				target_x = target_box['x'] + target_box['width'] / 2
				target_y = target_box['y'] + target_box['height'] / 2

		# Perform drag operation
		await self._client.send.Input.dispatchMouseEvent(
			{'type': 'mousePressed', 'x': source_x, 'y': source_y, 'button': 'left'},
			session_id=self._session_id,
		)

		await self._client.send.Input.dispatchMouseEvent(
			{'type': 'mouseMoved', 'x': target_x, 'y': target_y},
			session_id=self._session_id,
		)

		await self._client.send.Input.dispatchMouseEvent(
			{'type': 'mouseReleased', 'x': target_x, 'y': target_y, 'button': 'left'},
			session_id=self._session_id,
		)

	# Element properties and queries
	async def get_attribute(self, name: str) -> str | None:
		"""Get an attribute value."""
		node_id = await self._get_node_id()
		params: 'GetAttributesParameters' = {'nodeId': node_id}
		result = await self._client.send.DOM.getAttributes(params, session_id=self._session_id)

		attributes = result['attributes']
		for i in range(0, len(attributes), 2):
			if attributes[i] == name:
				return attributes[i + 1]
		return None

	async def get_bounding_box(self) -> BoundingBox | None:
		"""Get the bounding box of the element."""
		try:
			node_id = await self._get_node_id()
			params: 'GetBoxModelParameters' = {'nodeId': node_id}
			result = await self._client.send.DOM.getBoxModel(params, session_id=self._session_id)

			if 'model' not in result:
				return None

			# Get content box (first 8 values are content quad: x1,y1,x2,y2,x3,y3,x4,y4)
			content = result['model']['content']
			if len(content) < 8:
				return None

			# Calculate bounding box from quad
			x_coords = [content[i] for i in range(0, 8, 2)]
			y_coords = [content[i] for i in range(1, 8, 2)]

			x = min(x_coords)
			y = min(y_coords)
			width = max(x_coords) - x
			height = max(y_coords) - y

			return BoundingBox(x=x, y=y, width=width, height=height)

		except Exception:
			return None

	async def screenshot(self, format: str = 'jpeg', quality: int | None = None) -> str:
		"""Take a screenshot of this element and return base64 encoded image.

		Args:
			format: Image format ('jpeg', 'png', 'webp')
			quality: Quality 0-100 for JPEG format

		Returns:
			Base64-encoded image data
		"""
		# Get element's bounding box
		box = await self.get_bounding_box()
		if not box:
			raise RuntimeError('Element is not visible or has no bounding box')

		# Create viewport clip for the element
		viewport: 'Viewport' = {'x': box['x'], 'y': box['y'], 'width': box['width'], 'height': box['height'], 'scale': 1.0}

		# Prepare screenshot parameters
		params: 'CaptureScreenshotParameters' = {'format': format, 'clip': viewport}

		if quality is not None and format.lower() == 'jpeg':
			params['quality'] = quality

		# Take screenshot
		result = await self._client.send.Page.captureScreenshot(params, session_id=self._session_id)

		return result['data']

	# Helpers for modifiers etc
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

		# Uppercase letters require Shift
		if char.isupper():
			return (8, ord(char), char.lower())  # Shift=8

		# Lowercase letters
		if char.islower():
			return (0, ord(char.upper()), char)

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
		return (0, ord(char.upper()) if char.isalpha() else ord(char), char)

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
			'"': 'Quote',  # " uses Quote with Shift
			"'": 'Quote',
			'<': 'Comma',  # < uses Comma with Shift
			'>': 'Period',  # > uses Period with Shift
			'|': 'Backslash',  # | uses Backslash with Shift
		}

		if char in key_codes:
			return key_codes[char]
		elif char.isalpha():
			return f'Key{char.upper()}'
		elif char.isdigit():
			return f'Digit{char}'
		else:
			# Fallback for unknown characters
			return f'Key{char.upper()}' if char.isascii() and char.isalpha() else 'Unidentified'

	async def _clear_text_field(self, object_id: str, cdp_client, session_id: str) -> bool:
		"""Clear text field using multiple strategies, starting with the most reliable."""
		try:
			# Strategy 1: Direct JavaScript value setting (most reliable for modern web apps)
			logger.debug('Clearing text field using JavaScript value setting')

			await cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': """
						function() {
							this.value = "";
							this.dispatchEvent(new Event("input", { bubbles: true }));
							this.dispatchEvent(new Event("change", { bubbles: true }));
							return this.value;
						}
					""",
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=session_id,
			)

			# Verify clearing worked by checking the value
			verify_result = await cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.value; }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=session_id,
			)

			current_value = verify_result.get('result', {}).get('value', '')
			if not current_value:
				logger.debug('Text field cleared successfully using JavaScript')
				return True
			else:
				logger.debug(f'JavaScript clear partially failed, field still contains: "{current_value}"')

		except Exception as e:
			logger.debug(f'JavaScript clear failed: {e}')

		# Strategy 2: Triple-click + Delete (fallback for stubborn fields)
		try:
			logger.debug('Fallback: Clearing using triple-click + Delete')

			# Get element center coordinates for triple-click
			bounds_result = await cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { return this.getBoundingClientRect(); }',
					'objectId': object_id,
					'returnByValue': True,
				},
				session_id=session_id,
			)

			if bounds_result.get('result', {}).get('value'):
				bounds = bounds_result['result']['value']  # type: ignore  # type: ignore
				center_x = bounds['x'] + bounds['width'] / 2
				center_y = bounds['y'] + bounds['height'] / 2

				# Triple-click to select all text
				await cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=session_id,
				)
				await cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': center_x,
						'y': center_y,
						'button': 'left',
						'clickCount': 3,
					},
					session_id=session_id,
				)

				# Delete selected text
				await cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyDown',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=session_id,
				)
				await cdp_client.send.Input.dispatchKeyEvent(
					params={
						'type': 'keyUp',
						'key': 'Delete',
						'code': 'Delete',
					},
					session_id=session_id,
				)

				logger.debug('Text field cleared using triple-click + Delete')
				return True

		except Exception as e:
			logger.debug(f'Triple-click clear failed: {e}')

		# If all strategies failed
		logger.warning('All text clearing strategies failed')
		return False

	async def _focus_element_simple(
		self, backend_node_id: int, object_id: str, cdp_client, session_id: str, input_coordinates=None
	) -> bool:
		"""Focus element using multiple strategies with robust fallbacks."""
		try:
			# Strategy 1: CDP focus (most reliable)
			logger.debug('Focusing element using CDP focus')
			await cdp_client.send.DOM.focus(params={'backendNodeId': backend_node_id}, session_id=session_id)
			logger.debug('Element focused successfully using CDP focus')
			return True
		except Exception as e:
			logger.debug(f'CDP focus failed: {e}, trying JavaScript focus')

		try:
			# Strategy 2: JavaScript focus (fallback)
			logger.debug('Focusing element using JavaScript focus')
			await cdp_client.send.Runtime.callFunctionOn(
				params={
					'functionDeclaration': 'function() { this.focus(); }',
					'objectId': object_id,
				},
				session_id=session_id,
			)
			logger.debug('Element focused successfully using JavaScript')
			return True
		except Exception as e:
			logger.debug(f'JavaScript focus failed: {e}, trying click focus')

		try:
			# Strategy 3: Click to focus (last resort)
			if input_coordinates:
				logger.debug(f'Focusing element by clicking at coordinates: {input_coordinates}')
				center_x = input_coordinates['input_x']
				center_y = input_coordinates['input_y']

				# Click on the element to focus it
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
				logger.debug('Element focused using click')
				return True
			else:
				logger.debug('No coordinates available for click focus')
		except Exception as e:
			logger.warning(f'All focus strategies failed: {e}')
		return False

	async def get_basic_info(self) -> ElementInfo:
		"""Get basic information about the element including coordinates and properties."""
		try:
			# Get basic node information
			node_id = await self._get_node_id()
			describe_result = await self._client.send.DOM.describeNode({'nodeId': node_id}, session_id=self._session_id)

			node_info = describe_result['node']

			# Get bounding box
			bounding_box = await self.get_bounding_box()

			# Get attributes as a proper dict
			attributes_list = node_info.get('attributes', [])
			attributes_dict: dict[str, str] = {}
			for i in range(0, len(attributes_list), 2):
				if i + 1 < len(attributes_list):
					attributes_dict[attributes_list[i]] = attributes_list[i + 1]

			return ElementInfo(
				backendNodeId=self._backend_node_id,
				nodeId=node_id,
				nodeName=node_info.get('nodeName', ''),
				nodeType=node_info.get('nodeType', 0),
				nodeValue=node_info.get('nodeValue'),
				attributes=attributes_dict,
				boundingBox=bounding_box,
				error=None,
			)
		except Exception as e:
			return ElementInfo(
				backendNodeId=self._backend_node_id,
				nodeId=None,
				nodeName='',
				nodeType=0,
				nodeValue=None,
				attributes={},
				boundingBox=None,
				error=str(e),
			)
