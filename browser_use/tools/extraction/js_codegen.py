"""JS-codegen extraction: LLM generates a JS IIFE, executed via CDP, returns structured JSON."""

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML truncation
# ---------------------------------------------------------------------------

_DEFAULT_MAX_HTML_CHARS = 100_000


def _truncate_html(html: str, max_chars: int = _DEFAULT_MAX_HTML_CHARS) -> tuple[str, bool]:
	"""Truncate HTML at a tag boundary so we don't feed half a tag to the LLM.

	Returns (truncated_html, was_truncated).
	"""
	if len(html) <= max_chars:
		return html, False

	# Find last '>' at or before the limit
	cut = html.rfind('>', 0, max_chars)
	if cut == -1:
		# No tag boundary found — hard cut (unlikely for real HTML)
		cut = max_chars
	else:
		cut += 1  # include the '>'

	return html[:cut], True


# ---------------------------------------------------------------------------
# JS extraction from LLM response
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r'```(?:js|javascript)?\s*\n?(.*?)```', re.DOTALL)
_IIFE_LIKE_RE = re.compile(r'^\s*(\(?\s*(?:function\s*\(|(?:\(\s*)?\(\s*\))\s*)', re.DOTALL)


def _extract_js_from_response(text: str) -> str:
	"""Strip markdown fences from LLM response and return raw JS.

	Accepts both ``(function(){…})()`` and ``(() => {…})()`` styles.
	Raises ValueError if the result doesn't look like an IIFE or arrow IIFE.
	"""
	# Try fenced block first
	m = _FENCE_RE.search(text)
	js = m.group(1).strip() if m else text.strip()

	# Lenient check — does it start with something IIFE-ish?
	if not (js.startswith('(') or js.startswith('async')):
		raise ValueError(f'LLM response does not look like a JS IIFE: {js[:120]}…')

	return js


# ---------------------------------------------------------------------------
# Page HTML helpers
# ---------------------------------------------------------------------------


async def _get_page_html(
	browser_session: 'BrowserSession',
	css_selector: str | None = None,
) -> tuple[str, str]:
	"""Return (html, url) for the current page.

	If *css_selector* is given, we evaluate ``querySelector(sel).outerHTML`` via CDP.
	Otherwise we serialise the full enhanced DOM tree to HTML.
	"""
	current_url = await browser_session.get_current_page_url()

	if css_selector is not None:
		# Scoped path — CDP outerHTML
		js = f'(function(){{ var el = document.querySelector({json.dumps(css_selector)}); return el ? el.outerHTML : null; }})()'
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': js, 'returnByValue': True, 'awaitPromise': True},
			session_id=cdp_session.session_id,
		)
		value = result.get('result', {}).get('value')
		if value is None:
			raise RuntimeError(f'CSS selector {css_selector!r} matched no element on {current_url}')
		return str(value), current_url

	# Full-page path — enhanced DOM → HTML serialiser
	from browser_use.dom.markdown_extractor import _get_enhanced_dom_tree_from_browser_session
	from browser_use.dom.serializer.html_serializer import HTMLSerializer

	enhanced_dom_tree = await _get_enhanced_dom_tree_from_browser_session(browser_session)
	serializer = HTMLSerializer(extract_links=False)
	html = serializer.serialize(enhanced_dom_tree)
	return html, current_url


# ---------------------------------------------------------------------------
# CDP JS execution
# ---------------------------------------------------------------------------


async def _execute_js_on_page(browser_session: 'BrowserSession', js_code: str) -> Any:
	"""Execute *js_code* via CDP Runtime.evaluate and return the value.

	Mirrors error handling from code_use/namespace.py.
	"""
	from browser_use.code_use.namespace import _strip_js_comments

	js_code = _strip_js_comments(js_code)

	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js_code, 'returnByValue': True, 'awaitPromise': True},
		session_id=cdp_session.session_id,
	)

	# CDP-level exception
	if result.get('exceptionDetails'):
		exception = result['exceptionDetails']
		error_text = exception.get('text', 'Unknown error')
		details: list[str] = []
		if 'exception' in exception:
			exc_obj = exception['exception']
			if 'description' in exc_obj:
				details.append(exc_obj['description'])
			elif 'value' in exc_obj:
				details.append(str(exc_obj['value']))
		msg = f'JavaScript execution error: {error_text}'
		if details:
			msg += f'\nDetails: {" | ".join(details)}'
		raise RuntimeError(msg)

	value = result.get('result', {}).get('value')

	# Detect script-level try/catch errors returned as {error: ...}
	if isinstance(value, dict) and 'error' in value and len(value) == 1:
		raise RuntimeError(f'Script returned error: {value["error"]}')

	return value


# ---------------------------------------------------------------------------
# LLM script generation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a JavaScript code generator for browser automation data extraction.

Your task: write a single vanilla JavaScript IIFE that extracts data from the current page's DOM and returns a JSON-serializable value.

Rules:
- Return a single IIFE: (function(){ ... })() or (() => { ... })()
- Use document.querySelector / document.querySelectorAll to locate elements
- Return JSON-serializable values only (objects, arrays, strings, numbers, booleans, null)
- Wrap the entire body in try/catch — on error return {error: e.message}
- Do NOT include comments
- Do NOT use Node.js APIs (require, fs, process, etc.)
- Do NOT use fetch or XMLHttpRequest
- Do NOT navigate or modify the page
- Keep the code concise
""".strip()


async def _generate_js_script(
	llm: BaseChatModel,
	query: str,
	html: str,
	output_schema: dict | None = None,
	css_selector: str | None = None,
	error_feedback: str | None = None,
) -> str:
	"""Single blocking LLM call that returns JS code."""
	user_parts: list[str] = []
	user_parts.append(f'<query>\n{query}\n</query>')

	if css_selector:
		user_parts.append(f'<css_selector>\n{css_selector}\n</css_selector>')

	if output_schema:
		user_parts.append(f'<output_schema>\n{json.dumps(output_schema, indent=2)}\n</output_schema>')

	user_parts.append(f'<page_html>\n{html}\n</page_html>')

	if error_feedback:
		user_parts.append(f'<previous_attempt_error>\n{error_feedback}\n</previous_attempt_error>')

	user_msg = '\n\n'.join(user_parts)

	response = await llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), UserMessage(content=user_msg)])
	js_code = _extract_js_from_response(str(response.completion))
	return js_code


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def js_codegen_extract(
	query: str,
	browser_session: 'BrowserSession',
	llm: BaseChatModel,
	output_schema: dict | None = None,
	css_selector: str | None = None,
	max_retries: int = 1,
) -> tuple[Any, dict[str, Any]]:
	"""Full JS-codegen extraction pipeline.

	Returns (extracted_data, metadata_dict).
	"""
	html, url = await _get_page_html(browser_session, css_selector)
	html, was_truncated = _truncate_html(html)

	metadata: dict[str, Any] = {
		'js_codegen_extraction': True,
		'source_url': url,
		'html_truncated': was_truncated,
	}

	last_error: str | None = None
	js_script: str | None = None

	for attempt in range(1 + max_retries):
		try:
			js_script = await _generate_js_script(
				llm=llm,
				query=query,
				html=html,
				output_schema=output_schema,
				css_selector=css_selector,
				error_feedback=last_error,
			)
			metadata['js_script'] = js_script

			data = await _execute_js_on_page(browser_session, js_script)

			# Schema validation if requested
			if output_schema is not None:
				from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model

				try:
					model = schema_dict_to_pydantic_model(output_schema)
					validated = model.model_validate(data)
					data = validated.model_dump(mode='json')
					from browser_use.tools.extraction.views import ExtractionResult

					extraction_meta = ExtractionResult(
						data=data,
						schema_used=output_schema,
						is_partial=was_truncated,
						source_url=url,
					)
					metadata['extraction_result'] = extraction_meta.model_dump(mode='json')
				except Exception as validation_err:
					# Validation failed — treat as retryable error
					raise RuntimeError(f'Schema validation failed: {validation_err}') from validation_err

			metadata['retries_used'] = attempt
			return data, metadata

		except Exception as exc:
			last_error = str(exc)
			logger.debug(f'js_codegen_extract attempt {attempt + 1} failed: {last_error}')
			if attempt >= max_retries:
				metadata['retries_used'] = attempt
				metadata['js_script'] = js_script
				raise RuntimeError(f'js_codegen_extract failed after {attempt + 1} attempt(s): {last_error}') from exc

	# Should never reach here, but satisfy type checker
	raise RuntimeError('js_codegen_extract: unexpected control flow')  # pragma: no cover
