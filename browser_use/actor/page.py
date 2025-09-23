"""Page class for page-level operations."""

from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

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
				self._client.send.Runtime.enable(session_id=self._session_id),
				self._client.send.Network.enable(session_id=self._session_id),
			)

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

		# Debug: print the actual expression being evaluated
		print(f'DEBUG: Evaluating JavaScript: {repr(expression)}')

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

	async def screenshot(self, format: str = 'jpeg', quality: int | None = None) -> str:
		"""Take a screenshot and return base64 encoded image.

		Args:
		    format: Image format ('jpeg', 'png', 'webp')
		    quality: Quality 0-100 for JPEG format

		Returns:
		    Base64-encoded image data
		"""
		session_id = await self._ensure_session()

		params: 'CaptureScreenshotParameters' = {'format': format}

		if quality is not None and format.lower() == 'jpeg':
			params['quality'] = quality

		result = await self._client.send.Page.captureScreenshot(params, session_id=session_id)

		return result['data']

	async def press(self, key: str) -> None:
		"""Press a key on the page (sends keyboard input to the focused element or page)."""
		session_id = await self._ensure_session()

		# Handle key combinations like "Control+A"
		if '+' in key:
			parts = key.split('+')
			modifiers = parts[:-1]
			main_key = parts[-1]

			# Press modifier keys
			for mod in modifiers:
				params: 'DispatchKeyEventParameters' = {'type': 'keyDown', 'key': mod}
				await self._client.send.Input.dispatchKeyEvent(params, session_id=session_id)

			# Press main key
			main_down_params: 'DispatchKeyEventParameters' = {'type': 'keyDown', 'key': main_key}
			await self._client.send.Input.dispatchKeyEvent(main_down_params, session_id=session_id)

			main_up_params: 'DispatchKeyEventParameters' = {'type': 'keyUp', 'key': main_key}
			await self._client.send.Input.dispatchKeyEvent(main_up_params, session_id=session_id)

			# Release modifier keys
			for mod in reversed(modifiers):
				release_params: 'DispatchKeyEventParameters' = {'type': 'keyUp', 'key': mod}
				await self._client.send.Input.dispatchKeyEvent(release_params, session_id=session_id)
		else:
			# Simple key press
			key_down_params: 'DispatchKeyEventParameters' = {'type': 'keyDown', 'key': key}
			await self._client.send.Input.dispatchKeyEvent(key_down_params, session_id=session_id)

			key_up_params: 'DispatchKeyEventParameters' = {'type': 'keyUp', 'key': key}
			await self._client.send.Input.dispatchKeyEvent(key_up_params, session_id=session_id)

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
		await self._client.send.Page.navigate(params, session_id=session_id)

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

		enhanced_dom_tree = await dom_service.get_dom_tree(target_id=self._target_id)

		serialized_dom_state, _ = DOMTreeSerializer(
			enhanced_dom_tree, None, paint_order_filtering=True
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

		return Element_(self._browser_session, element.backend_node_id, self._session_id)

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

		# Extract clean markdown from the page
		session_id = await self._ensure_session()
		try:
			body_id = await self._client.send.DOM.getDocument(session_id=session_id)
			page_html_result = await self._client.send.DOM.getOuterHTML(
				params={'backendNodeId': body_id['root']['backendNodeId']}, session_id=session_id
			)
			page_html = page_html_result['outerHTML']
		except Exception as e:
			raise RuntimeError(f"Couldn't extract page content: {e}")

		# Convert HTML to clean markdown
		import html2text

		h = html2text.HTML2Text()
		h.ignore_links = False
		h.ignore_images = True
		h.ignore_emphasis = False
		h.body_width = 0  # Don't wrap lines
		h.unicode_snob = True
		h.skip_internal_links = True
		markdown_content = h.handle(page_html)

		# Clean up the markdown
		import re

		# Remove URL encoding artifacts
		markdown_content = re.sub(r'%[0-9A-Fa-f]{2}', '', markdown_content)

		# Compress excessive newlines
		markdown_content = re.sub(r'\n{4,}', '\n\n\n', markdown_content)

		# Remove very short lines (likely artifacts)
		lines = markdown_content.split('\n')
		filtered_lines = []
		for line in lines:
			stripped = line.strip()
			if len(stripped) > 2:  # Keep lines with substantial content
				filtered_lines.append(line)

		markdown_content = '\n'.join(filtered_lines).strip()

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
		prompt_content = f'<query>\n{prompt}\n</query>\n\n<webpage_content>\n{markdown_content}\n</webpage_content>'

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
