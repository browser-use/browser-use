"""JS-codegen extraction: LLM generates a JS script, CDP executes it, returns structured JSON."""

import json
import logging
from typing import Any

from browser_use.browser import BrowserSession
from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.tools.extraction.views import ExtractionResult

logger = logging.getLogger(__name__)

_JS_CODEGEN_SYSTEM_PROMPT = """You are an expert at writing JavaScript data extraction scripts.
Write a single JavaScript IIFE that extracts the requested data from the current page's DOM.

Rules:
- Use document.querySelectorAll / querySelector with robust CSS selectors
- Return a JSON-serializable value (object or array)
- Handle null/missing elements gracefully with fallback values (empty string, null, etc.)
- Use .textContent.trim() for text, .getAttribute() for attributes, .href for links
- Do NOT use external libraries — vanilla JS only
- The script runs on the full live DOM, not just the HTML shown below
- Wrap everything in (function(){ ... })()
- Return the result directly from the IIFE (no console.log)
- If an output schema is provided, match its structure exactly

Output ONLY the JavaScript code, no markdown fences, no explanation."""

_MAX_HTML_FOR_LLM = 100_000


class JSExtractionService:
	"""Generates and executes JS extraction scripts via a blocking LLM call."""

	async def extract(
		self,
		query: str,
		browser_session: BrowserSession,
		llm: BaseChatModel,
		output_schema: dict[str, Any] | None = None,
		css_selector: str | None = None,
		cached_js_script: str | None = None,
	) -> ExtractionResult:
		"""Run the full JS-codegen extraction pipeline.

		Args:
			query: What to extract.
			browser_session: Active browser session.
			llm: LLM for script generation.
			output_schema: Optional JSON Schema for output validation.
			css_selector: Optional CSS selector to narrow scope.
			cached_js_script: If provided, skip LLM call and execute this script directly.

		Returns:
			ExtractionResult with extracted data and metadata.
		"""
		current_url = await browser_session.get_current_page_url()

		# Step 1 & 2: Get HTML (possibly scoped) and generate or reuse script
		if cached_js_script:
			js_script = cached_js_script
		else:
			html = await self._get_html_for_llm(browser_session, css_selector)
			js_script = await self._generate_script(llm, html, query, output_schema)

		# Step 3: Execute JS via CDP
		raw_result, exec_error = await self._execute_script(browser_session, js_script)

		# Step 4: If execution failed, retry once with error feedback
		if exec_error is not None and not cached_js_script:
			logger.warning(f'JS execution failed, retrying with error feedback: {exec_error}')
			html = await self._get_html_for_llm(browser_session, css_selector)
			js_script = await self._generate_script(llm, html, query, output_schema, previous_error=exec_error)
			raw_result, exec_error = await self._execute_script(browser_session, js_script)

		if exec_error is not None:
			return ExtractionResult(
				data=None,
				schema_used=output_schema is not None,
				is_partial=False,
				source_url=current_url,
				content_stats={'error': exec_error, 'js_script': js_script},
			)

		# Step 5: Validate against schema if provided
		validated_data = raw_result
		schema_valid = True
		if output_schema is not None and raw_result is not None:
			validated_data, schema_valid = self._validate_result(raw_result, output_schema)
			if not schema_valid and not cached_js_script:
				# Retry once with validation error feedback
				logger.warning('Schema validation failed, retrying with feedback')
				html = await self._get_html_for_llm(browser_session, css_selector)
				validation_hint = (
					f'Previous script returned data that does not match the schema. Got: {json.dumps(raw_result)[:500]}'
				)
				js_script = await self._generate_script(llm, html, query, output_schema, previous_error=validation_hint)
				raw_result, exec_error = await self._execute_script(browser_session, js_script)
				if exec_error is None and raw_result is not None:
					validated_data, schema_valid = self._validate_result(raw_result, output_schema)

		return ExtractionResult(
			data=validated_data,
			schema_used=output_schema is not None and schema_valid,
			is_partial=False,
			source_url=current_url,
			content_stats={
				'js_script': js_script,
				'css_selector': css_selector,
				'schema_valid': schema_valid,
			},
		)

	async def _get_html_for_llm(
		self,
		browser_session: BrowserSession,
		css_selector: str | None = None,
	) -> str:
		"""Get page HTML for the LLM to analyze structure.

		When css_selector is provided, scopes to that element's outerHTML.
		Otherwise serializes the full enhanced DOM tree.
		Truncates to _MAX_HTML_FOR_LLM chars — the LLM only needs structure, not all content.
		"""
		if css_selector:
			# Get scoped HTML via CDP
			html = await self._get_scoped_html(browser_session, css_selector)
			if html:
				return html[:_MAX_HTML_FOR_LLM]

		# Full page: use HTMLSerializer on enhanced DOM tree
		try:
			from browser_use.dom.markdown_extractor import _get_enhanced_dom_tree_from_browser_session

			enhanced_dom_tree = await _get_enhanced_dom_tree_from_browser_session(browser_session)
			serializer = HTMLSerializer(extract_links=True)
			html = serializer.serialize(enhanced_dom_tree)
			return html[:_MAX_HTML_FOR_LLM]
		except Exception as e:
			logger.warning(f'Failed to get HTML via serializer, falling back to CDP: {e}')
			return await self._get_full_html_via_cdp(browser_session)

	async def _get_scoped_html(self, browser_session: BrowserSession, css_selector: str) -> str | None:
		"""Get outerHTML of a specific element via CDP."""
		try:
			cdp_session = await browser_session.get_or_create_cdp_session()
			escaped_selector = css_selector.replace('\\', '\\\\').replace("'", "\\'")
			js = f"(function(){{ var el = document.querySelector('{escaped_selector}'); return el ? el.outerHTML : null; }})()"
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': js, 'returnByValue': True, 'awaitPromise': True},
				session_id=cdp_session.session_id,
			)
			value = result.get('result', {}).get('value')
			return value if isinstance(value, str) else None
		except Exception as e:
			logger.warning(f'Failed to get scoped HTML for selector "{css_selector}": {e}')
			return None

	async def _get_full_html_via_cdp(self, browser_session: BrowserSession) -> str:
		"""Fallback: get full page HTML via CDP."""
		try:
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': 'document.documentElement.outerHTML',
					'returnByValue': True,
					'awaitPromise': True,
				},
				session_id=cdp_session.session_id,
			)
			html = result.get('result', {}).get('value', '')
			return html[:_MAX_HTML_FOR_LLM] if isinstance(html, str) else ''
		except Exception as e:
			logger.error(f'Failed to get full HTML via CDP: {e}')
			return ''

	async def _generate_script(
		self,
		llm: BaseChatModel,
		html: str,
		query: str,
		output_schema: dict[str, Any] | None = None,
		previous_error: str | None = None,
	) -> str:
		"""Generate a JS extraction script via a single blocking LLM call."""
		user_parts = [f'<query>{query}</query>']

		if output_schema:
			user_parts.append(f'<output_schema>{json.dumps(output_schema, indent=2)}</output_schema>')

		if previous_error:
			user_parts.append(f'<previous_error>The previous script failed. Fix the issue:\n{previous_error}</previous_error>')

		user_parts.append(f'<html_structure>\n{html}\n</html_structure>')

		messages = [
			SystemMessage(content=_JS_CODEGEN_SYSTEM_PROMPT),
			UserMessage(content='\n\n'.join(user_parts)),
		]

		response = await llm.ainvoke(messages)
		script = response.completion if isinstance(response.completion, str) else str(response.completion)

		# Strip markdown fences if present
		script = script.strip()
		if script.startswith('```'):
			lines = script.split('\n')
			# Remove first and last fence lines
			if lines[0].startswith('```'):
				lines = lines[1:]
			if lines and lines[-1].strip() == '```':
				lines = lines[:-1]
			script = '\n'.join(lines)

		return script.strip()

	async def _execute_script(
		self,
		browser_session: BrowserSession,
		js_script: str,
	) -> tuple[Any, str | None]:
		"""Execute JS via CDP Runtime.evaluate. Returns (result, error_or_none)."""
		try:
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': js_script,
					'returnByValue': True,
					'awaitPromise': True,
				},
				session_id=cdp_session.session_id,
			)

			# Check for JS errors
			if result.get('exceptionDetails'):
				exception = result['exceptionDetails']
				error_text = exception.get('text', 'Unknown JS error')
				# Try to get more details from exception object
				exc_obj = exception.get('exception', {})
				description = exc_obj.get('description', '')
				error_msg = f'{error_text}: {description}' if description else error_text
				return None, error_msg

			result_data = result.get('result', {})
			if result_data.get('type') == 'undefined':
				return None, 'Script returned undefined — ensure the IIFE returns a value'

			value = result_data.get('value')
			return value, None

		except Exception as e:
			return None, f'CDP execution error: {type(e).__name__}: {e}'

	def _validate_result(
		self,
		raw_result: Any,
		output_schema: dict[str, Any],
	) -> tuple[Any, bool]:
		"""Validate raw JS result against the output schema. Returns (data, is_valid)."""
		try:
			from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model

			model = schema_dict_to_pydantic_model(output_schema)
			# raw_result should be a dict if the schema is an object type
			if isinstance(raw_result, dict):
				validated = model.model_validate(raw_result)
				return validated.model_dump(mode='json'), True
			elif isinstance(raw_result, list):
				# If the schema root is object but result is a list, wrap it
				# This is a common pattern: schema expects {items: [...]} but script returns [...]
				return raw_result, False
			else:
				return raw_result, False
		except Exception as e:
			logger.debug(f'Schema validation failed: {e}')
			return raw_result, False
