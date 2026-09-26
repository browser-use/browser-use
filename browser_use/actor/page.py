"""Page class for page-level operations."""

import asyncio
import math
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from browser_use import logger
from browser_use.actor.utils import get_key_info
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.service import DomService
from browser_use.llm.messages import SystemMessage, UserMessage

T = TypeVar('T', bound=BaseModel)

if TYPE_CHECKING:
	from cdp_use.cdp.dom.commands import (
		DescribeNodeParameters,
		QuerySelectorAllParameters,
	)
	from cdp_use.cdp.emulation.commands import SetDeviceMetricsOverrideParameters
	from cdp_use.cdp.input.commands import (
		DispatchKeyEventParameters,
	)
	from cdp_use.cdp.page.commands import CaptureScreenshotParameters, NavigateParameters, NavigateToHistoryEntryParameters
	from cdp_use.cdp.page.types import Viewport
	from cdp_use.cdp.runtime.commands import EvaluateParameters
	from cdp_use.cdp.target.commands import (
		AttachToTargetParameters,
		GetTargetInfoParameters,
	)
	from cdp_use.cdp.target.types import TargetInfo

	from browser_use.browser.session import BrowserSession
	from browser_use.llm.base import BaseChatModel

	from .element import Element
	from .mouse import Mouse


class Page:
	"""Page operations (tab or iframe)."""

	def __init__(
		self, browser_session: 'BrowserSession', target_id: str, session_id: str | None = None, llm: 'BaseChatModel | None' = None
	):
		self._browser_session = browser_session
		self._client = browser_session.cdp_client
		self._target_id = target_id
		self._session_id: str | None = session_id
		self._mouse: 'Mouse | None' = None

		self._llm = llm

	async def _ensure_session(self) -> str:
		"""Ensure we have a session ID for this target."""
		if not self._session_id:
			params: 'AttachToTargetParameters' = {'targetId': self._target_id, 'flatten': True}
			result = await self._client.send.Target.attachToTarget(params)
			self._session_id = result['sessionId']

			# Enable necessary domains
			import asyncio

			await asyncio.gather(
				self._client.send.Page.enable(session_id=self._session_id),
				self._client.send.DOM.enable(session_id=self._session_id),
				self._client.send.Network.enable(session_id=self._session_id),
			)

			# Runtime.evaluate/callFunctionOn work without the Runtime domain staying
			# "enabled" — enable is only needed to receive Runtime.* events, which we
			# don't consume here. Leaving it enabled makes Chrome emit a
			# Runtime.consoleAPICalled event that page-side JS can detect in a few
			# lines, a signal anti-bot vendors (Cloudflare, DataDome) key off of.
			# Immediately disabling after enable still lets executionContextCreated
			# fire once, closing the leak window.
			await self._client.send.Runtime.enable(session_id=self._session_id)
			await self._client.send.Runtime.disable(session_id=self._session_id)

		return self._session_id

	@property
	async def session_id(self) -> str:
		"""Get the session ID for this target.

		@dev Pass this to an arbitrary CDP call
		"""
		return await self._ensure_session()

	@property
	async def mouse(self) -> 'Mouse':
		"""Get the mouse interface for this target."""
		if not self._mouse:
			session_id = await self._ensure_session()
			from .mouse import Mouse

			self._mouse = Mouse(self._browser_session, session_id, self._target_id)
		return self._mouse

	async def reload(self) -> None:
		"""Reload the target."""
		session_id = await self._ensure_session()
		await self._client.send.Page.reload(session_id=session_id)

	async def get_element(self, backend_node_id: int) -> 'Element':
		"""Get an element by its backend node ID."""
		session_id = await self._ensure_session()

		from .element import Element as Element_

		return Element_(self._browser_session, backend_node_id, session_id)

	async def evaluate(self, page_function: str, *args) -> str:
		"""Execute JavaScript in the target.

		Args:
			page_function: JavaScript code that MUST start with (...args) => format
			*args: Arguments to pass to the function

		Returns:
			String representation of the JavaScript execution result.
			Objects and arrays are JSON-stringified.
		"""
		session_id = await self._ensure_session()

		# Clean and fix common JavaScript string parsing issues
		page_function = self._fix_javascript_string(page_function)

		# Enforce arrow function format
		if not (page_function.startswith('(') and '=>' in page_function):
			raise ValueError(f'JavaScript code must start with (...args) => format. Got: {page_function[:50]}...')

		# Build the expression - call the arrow function with provided args
		if args:
			# Convert args to JSON representation for safe passing
			import json

			arg_strs = [json.dumps(arg) for arg in args]
			expression = f'({page_function})({", ".join(arg_strs)})'
		else:
			expression = f'({page_function})()'

		# Debug: log the actual expression being evaluated
		logger.debug(f'Evaluating JavaScript: {repr(expression)}')

		params: 'EvaluateParameters' = {'expression': expression, 'returnByValue': True, 'awaitPromise': True}
		result = await self._client.send.Runtime.evaluate(
			params,
			session_id=session_id,
		)

		if 'exceptionDetails' in result:
			raise RuntimeError(f'JavaScript evaluation failed: {result["exceptionDetails"]}')

		value = result.get('result', {}).get('value')

		# Always return string representation
		if value is None:
			return ''
		elif isinstance(value, str):
			return value
		else:
			# Convert objects, numbers, booleans to string
			import json

			try:
				return json.dumps(value) if isinstance(value, (dict, list)) else str(value)
			except (TypeError, ValueError):
				return str(value)

	def _fix_javascript_string(self, js_code: str) -> str:
		"""Fix common JavaScript string parsing issues when written as Python string."""

		# Just do minimal, safe cleaning
		js_code = js_code.strip()

		# Only fix the most common and safe issues:

		# 1. Remove obvious Python string wrapper quotes if they exist
		if (js_code.startswith('"') and js_code.endswith('"')) or (js_code.startswith("'") and js_code.endswith("'")):
			# Check if it's a wrapped string (not part of JS syntax)
			inner = js_code[1:-1]
			if inner.count('"') + inner.count("'") == 0 or '() =>' in inner:
				js_code = inner

		# 2. Only fix clearly escaped quotes that shouldn't be
		# But be very conservative - only if we're sure it's a Python string artifact
		if '\\"' in js_code and js_code.count('\\"') > js_code.count('"'):
			js_code = js_code.replace('\\"', '"')
		if "\\'" in js_code and js_code.count("\\'") > js_code.count("'"):
			js_code = js_code.replace("\\'", "'")

		# 3. Basic whitespace normalization only
		js_code = js_code.strip()

		# Final validation - ensure it's not empty
		if not js_code:
			raise ValueError('JavaScript code is empty after cleaning')

		return js_code

	async def screenshot(self, format: str = 'png', quality: int | None = None, *, clip: 'Viewport | None' = None) -> str:
		"""Take a screenshot and return base64 encoded image.

		Args:
		    format: Image format ('jpeg', 'png', 'webp')
		    quality: Quality 0-100 for JPEG format
		    clip: Optional document-pixel region and output scale for a crop/zoom.

		Returns:
		    Base64-encoded image data
		"""
		session_id = await self._ensure_session()

		params: 'CaptureScreenshotParameters' = {'format': format}
		if clip is not None:
			if clip['width'] <= 0 or clip['height'] <= 0 or clip['scale'] <= 0:
				raise ValueError('Screenshot clip width, height and scale must be positive')
			params['clip'] = clip

		if quality is not None and format.lower() == 'jpeg':
			params['quality'] = quality

		result = await self._client.send.Page.captureScreenshot(params, session_id=session_id)

		return result['data']

	async def press(self, key: str) -> None:
		"""Press a key/chord or type literal text using the normal keyboard action."""
		from browser_use.browser.events import SendKeysEvent

		# Preserve named CDP keys that the text-oriented SendKeys action does not recognize.
		code, vk_code = get_key_info(key)
		if len(key) > 1 and vk_code is not None and key not in ('Enter', 'Tab', 'Space'):
			session_id = await self._ensure_session()
			for event_type in ('keyDown', 'keyUp'):
				await self._client.send.Input.dispatchKeyEvent(
					{'type': event_type, 'key': key, 'code': code, 'windowsVirtualKeyCode': vk_code},
					session_id=session_id,
				)
			return

		event = self._browser_session.event_bus.dispatch(SendKeysEvent(keys=key, target_id=self._target_id))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def hold_key(self, key: str, duration: float) -> None:
		"""Hold a key/chord for seconds, releasing every pressed key on exit.

		This emits one key-down per key; it does not synthesize auto-repeat.
		"""
		if not math.isfinite(duration) or duration < 0:
			raise ValueError('duration must be finite and non-negative')
		aliases = {
			'ctrl': 'Control',
			'control': 'Control',
			'alt': 'Alt',
			'cmd': 'Meta',
			'meta': 'Meta',
			'shift': 'Shift',
			'enter': 'Enter',
			'return': 'Enter',
			'tab': 'Tab',
			'escape': 'Escape',
			'space': ' ',
		}
		keys = [aliases.get(part.lower(), part) for part in key.split('+')] if key != '+' else ['+']
		modifier_bits = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
		if not keys or any(not part for part in keys) or any(part not in modifier_bits for part in keys[:-1]):
			raise ValueError('Use one key or a modifier chord, such as Control+a')
		session_id = await self._ensure_session()
		held: list[str] = []
		modifiers = 0
		try:
			for part in keys:
				code, vk_code = get_key_info(part)
				modifiers |= modifier_bits.get(part, 0)
				params: 'DispatchKeyEventParameters' = {'type': 'keyDown', 'key': part, 'code': code, 'modifiers': modifiers}
				if vk_code is not None:
					params['windowsVirtualKeyCode'] = vk_code
				held.append(part)
				await self._client.send.Input.dispatchKeyEvent(params, session_id=session_id)
			await asyncio.sleep(duration)
		finally:
			release_error: Exception | None = None
			for part in reversed(held):
				modifiers &= ~modifier_bits.get(part, 0)
				code, vk_code = get_key_info(part)
				params = {'type': 'keyUp', 'key': part, 'code': code, 'modifiers': modifiers}
				if vk_code is not None:
					params['windowsVirtualKeyCode'] = vk_code
				try:
					await self._client.send.Input.dispatchKeyEvent(params, session_id=session_id)
				except Exception as exc:
					release_error = release_error or exc
			if release_error is not None:
				raise release_error

	async def set_viewport_size(self, width: int, height: int) -> None:
		"""Set the viewport size."""
		session_id = await self._ensure_session()

		params: 'SetDeviceMetricsOverrideParameters' = {
			'width': width,
			'height': height,
			'deviceScaleFactor': 1.0,
			'mobile': False,
		}
		await self._client.send.Emulation.setDeviceMetricsOverride(
			params,
			session_id=session_id,
		)

	# Target properties (from CDP getTargetInfo)
	async def get_target_info(self) -> 'TargetInfo':
		"""Get target information."""
		params: 'GetTargetInfoParameters' = {'targetId': self._target_id}
		result = await self._client.send.Target.getTargetInfo(params)
		return result['targetInfo']

	async def get_url(self) -> str:
		"""Get the current URL."""
		info = await self.get_target_info()
		return info.get('url', '')

	async def get_title(self) -> str:
		"""Get the current title."""
		info = await self.get_target_info()
		return info.get('title', '')

	async def goto(self, url: str) -> None:
		"""Navigate this target to a URL."""
		session_id = await self._ensure_session()

		params: 'NavigateParameters' = {'url': url}
		result = await self._client.send.Page.navigate(params, session_id=session_id)
		if result.get('errorText'):
			raise RuntimeError(f'Navigation failed: {result["errorText"]}')

	async def navigate(self, url: str) -> None:
		"""Alias for goto."""
		await self.goto(url)

	async def go_back(self) -> None:
		"""Navigate back in history."""
		session_id = await self._ensure_session()

		try:
			# Get navigation history
			history = await self._client.send.Page.getNavigationHistory(session_id=session_id)
			current_index = history['currentIndex']
			entries = history['entries']

			# Check if we can go back
			if current_index <= 0:
				raise RuntimeError('Cannot go back - no previous entry in history')

			# Navigate to the previous entry
			previous_entry_id = entries[current_index - 1]['id']
			params: 'NavigateToHistoryEntryParameters' = {'entryId': previous_entry_id}
			await self._client.send.Page.navigateToHistoryEntry(params, session_id=session_id)

		except Exception as e:
			raise RuntimeError(f'Failed to navigate back: {e}')

	async def go_forward(self) -> None:
		"""Navigate forward in history."""
		session_id = await self._ensure_session()

		try:
			# Get navigation history
			history = await self._client.send.Page.getNavigationHistory(session_id=session_id)
			current_index = history['currentIndex']
			entries = history['entries']

			# Check if we can go forward
			if current_index >= len(entries) - 1:
				raise RuntimeError('Cannot go forward - no next entry in history')

			# Navigate to the next entry
			next_entry_id = entries[current_index + 1]['id']
			params: 'NavigateToHistoryEntryParameters' = {'entryId': next_entry_id}
			await self._client.send.Page.navigateToHistoryEntry(params, session_id=session_id)

		except Exception as e:
			raise RuntimeError(f'Failed to navigate forward: {e}')

	# Element finding methods (these would need to be implemented based on DOM queries)
	async def get_elements_by_css_selector(self, selector: str) -> list['Element']:
		"""Get elements by CSS selector."""
		session_id = await self._ensure_session()

		# Get document first
		doc_result = await self._client.send.DOM.getDocument(session_id=session_id)
		document_node_id = doc_result['root']['nodeId']

		# Query selector all
		query_params: 'QuerySelectorAllParameters' = {'nodeId': document_node_id, 'selector': selector}
		result = await self._client.send.DOM.querySelectorAll(query_params, session_id=session_id)

		elements = []
		from .element import Element as Element_

		# Convert node IDs to backend node IDs
		for node_id in result['nodeIds']:
			# Get backend node ID
			describe_params: 'DescribeNodeParameters' = {'nodeId': node_id}
			node_result = await self._client.send.DOM.describeNode(describe_params, session_id=session_id)
			backend_node_id = node_result['node']['backendNodeId']
			elements.append(Element_(self._browser_session, backend_node_id, session_id))

		return elements

	# AI METHODS

	@property
	def dom_service(self) -> 'DomService':
		"""Get the DOM service for this target."""
		return DomService(self._browser_session)

	async def get_element_by_prompt(self, prompt: str, llm: 'BaseChatModel | None' = None) -> 'Element | None':
		"""Get an element by a prompt."""
		await self._ensure_session()
		llm = llm or self._llm

		if not llm:
			raise ValueError('LLM not provided')

		dom_service = self.dom_service

		# Lazy fetch all_frames inside get_dom_tree if needed (for cross-origin iframes)
		enhanced_dom_tree, _ = await dom_service.get_dom_tree(target_id=self._target_id, all_frames=None)

		session_id = self._browser_session.id
		serialized_dom_state, _ = DOMTreeSerializer(
			enhanced_dom_tree, None, paint_order_filtering=True, session_id=session_id
		).serialize_accessible_elements()

		llm_representation = serialized_dom_state.llm_representation()

		system_message = SystemMessage(
			content="""You are an AI created to find an element on a page by a prompt.

<browser_state>
Interactive Elements: All interactive elements will be provided in format as [index]<type>text</type> where
- index: Numeric identifier for interaction
- type: HTML element type (button, input, etc.)
- text: Element description

Examples:
[33]<div>User form</div>
[35]<button aria-label='Submit form'>Submit</button>

Note that:
- Only elements with numeric indexes in [] are interactive
- (stacked) indentation (with \t) is important and means that the element is a (html) child of the element above (with a lower index)
- Pure text elements without [] are not interactive.
</browser_state>

Your task is to find an element index (if any) that matches the prompt (written in <prompt> tag).

If non of the elements matches the, return None.

Before you return the element index, reason about the state and elements for a sentence or two."""
		)

		state_message = UserMessage(
			content=f"""
			<browser_state>
			{llm_representation}
			</browser_state>

			<prompt>
			{prompt}
			</prompt>
			"""
		)

		class ElementResponse(BaseModel):
			# thinking: str
			element_highlight_index: int | None

		llm_response = await llm.ainvoke(
			[
				system_message,
				state_message,
			],
			output_format=ElementResponse,
		)

		element_highlight_index = llm_response.completion.element_highlight_index

		if element_highlight_index is None or element_highlight_index not in serialized_dom_state.selector_map:
			return None

		element = serialized_dom_state.selector_map[element_highlight_index]

		from .element import Element as Element_

		element_session = await self._browser_session.cdp_client_for_node(element)
		return Element_(self._browser_session, element.backend_node_id, element_session.session_id)

	async def must_get_element_by_prompt(self, prompt: str, llm: 'BaseChatModel | None' = None) -> 'Element':
		"""Get an element by a prompt.

		@dev LLM can still return None, this just raises an error if the element is not found.
		"""
		element = await self.get_element_by_prompt(prompt, llm)
		if element is None:
			raise ValueError(f'No element found for prompt: {prompt}')

		return element

	async def extract_content(self, prompt: str, structured_output: type[T], llm: 'BaseChatModel | None' = None) -> T:
		"""Extract structured content from the current page using LLM.

		Extracts clean markdown from the page and sends it to LLM for structured data extraction.

		Args:
			prompt: Description of what content to extract
			structured_output: Pydantic BaseModel class defining the expected output structure
			llm: Language model to use for extraction

		Returns:
			The structured BaseModel instance with extracted content
		"""
		llm = llm or self._llm

		if not llm:
			raise ValueError('LLM not provided')

		# Extract clean markdown using the same method as in tools/service.py
		try:
			content, content_stats = await self._extract_clean_markdown()
		except Exception as e:
			raise RuntimeError(f'Could not extract clean markdown: {type(e).__name__}')

		# System prompt for structured extraction
		system_prompt = """
You are an expert at extracting structured data from the markdown of a webpage.

<input>
You will be given a query and the markdown of a webpage that has been filtered to remove noise and advertising content.
</input>

<instructions>
- You are tasked to extract information from the webpage that is relevant to the query.
- You should ONLY use the information available in the webpage to answer the query. Do not make up information or provide guess from your own knowledge.
- If the information relevant to the query is not available in the page, your response should mention that.
- If the query asks for all items, products, etc., make sure to directly list all of them.
- Return the extracted content in the exact structured format specified.
</instructions>

<output>
- Your output should present ALL the information relevant to the query in the specified structured format.
- Do not answer in conversational format - directly output the relevant information in the structured format.
</output>
""".strip()

		# Build prompt with just query and content
		prompt_content = f'<query>\n{prompt}\n</query>\n\n<webpage_content>\n{content}\n</webpage_content>'

		# Send to LLM with structured output
		import asyncio

		try:
			response = await asyncio.wait_for(
				llm.ainvoke(
					[SystemMessage(content=system_prompt), UserMessage(content=prompt_content)], output_format=structured_output
				),
				timeout=120.0,
			)

			# Return the structured output BaseModel instance
			return response.completion
		except Exception as e:
			raise RuntimeError(str(e))

	async def _extract_clean_markdown(self, extract_links: bool = False) -> tuple[str, dict]:
		"""Extract clean markdown from the current page using enhanced DOM tree.

		Uses the shared markdown extractor for consistency with tools/service.py.
		"""
		from browser_use.dom.markdown_extractor import extract_clean_markdown

		dom_service = self.dom_service
		return await extract_clean_markdown(dom_service=dom_service, target_id=self._target_id, extract_links=extract_links)
