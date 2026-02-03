"""JS-codegen extraction: LLM generates a JS IIFE, executed via CDP, returns structured JSON."""

import hashlib
import json
import logging
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML cleaning for codegen LLM
# ---------------------------------------------------------------------------

# Attributes the JS codegen LLM actually needs to write correct selectors/extraction code.
_KEEP_ATTRS = frozenset({
	# Identification & selectors
	'id', 'name', 'class', 'for',
	# Semantic / structural
	'type', 'role', 'href', 'src', 'alt', 'title', 'placeholder',
	# State
	'disabled', 'readonly', 'checked', 'selected', 'required', 'open',
	# Accessibility (useful for selector hints)
	'aria-label', 'aria-hidden', 'aria-expanded', 'aria-checked',
	# Form validation
	'pattern', 'min', 'max', 'minlength', 'maxlength', 'step', 'value', 'action', 'method',
	# Testing selectors the LLM may reference
	'data-testid', 'data-cy', 'data-test', 'data-qa', 'data-id',
})

# Tags to strip entirely (including children) — noise for data extraction.
_STRIP_TAGS = frozenset({
	# Media / embeds
	'svg', 'canvas', 'video', 'audio', 'picture', 'source', 'map',
	# Non-rendered / frames
	'noscript', 'iframe',
	# Structural chrome — navigation, headers, footers, sidebars contain
	# zero extraction-relevant data but often 40-60% of the HTML.
	'nav', 'header', 'footer', 'aside',
	# Interactive / scripting noise
	'script', 'style', 'dialog',
})

# Max number of CSS classes to keep per element.
_MAX_CLASSES = 5


class _HTMLCleaner(HTMLParser):
	"""Single-pass HTML cleaner that strips bloat for the codegen LLM."""

	def __init__(self) -> None:
		super().__init__(convert_charrefs=True)
		self.parts: list[str] = []
		self._skip_depth = 0  # > 0 means we're inside a stripped tag

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag in _STRIP_TAGS:
			self._skip_depth += 1
			return
		if self._skip_depth:
			return

		# Filter attributes to whitelist
		clean_attrs: list[str] = []
		for key, val in attrs:
			if key not in _KEEP_ATTRS:
				continue
			if val is None:
				clean_attrs.append(f' {key}')
				continue
			# Compact class lists
			if key == 'class' and val:
				classes = val.split()
				if len(classes) > _MAX_CLASSES:
					val = ' '.join(classes[:_MAX_CLASSES])
			clean_attrs.append(f' {key}="{val}"')

		self.parts.append(f'<{tag}{"".join(clean_attrs)}>')

	def handle_endtag(self, tag: str) -> None:
		if tag in _STRIP_TAGS:
			self._skip_depth = max(0, self._skip_depth - 1)
			return
		if self._skip_depth:
			return
		self.parts.append(f'</{tag}>')

	def handle_data(self, data: str) -> None:
		if self._skip_depth:
			return
		self.parts.append(data)

	def get_clean_html(self) -> str:
		return ''.join(self.parts)


def _clean_html_for_codegen(html: str) -> str:
	"""Strip attributes and tags the codegen LLM doesn't need.

	Single-pass parser that:
	- Keeps only whitelisted attributes (id, class, type, role, href, etc.)
	- Strips SVG, noscript, iframe, canvas, video, audio entirely
	- Caps class lists at 5 classes per element
	- Preserves all text content and tag structure
	"""
	cleaner = _HTMLCleaner()
	cleaner.feed(html)
	return cleaner.get_clean_html()


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
# Empty result detection
# ---------------------------------------------------------------------------


def _is_empty_result(data: Any) -> bool:
	"""Return True if *data* is empty/null and should trigger a retry."""
	if data is None:
		return True
	if isinstance(data, list) and len(data) == 0:
		return True
	if isinstance(data, dict) and len(data) == 0:
		return True
	if isinstance(data, str) and data.strip() == '':
		return True
	return False


# ---------------------------------------------------------------------------
# URL normalization for script caching
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r'^\d+$')


def _normalize_url_for_cache(url: str) -> str:
	"""Normalize a URL so that paginated variants share the same cache key.

	Replaces purely-numeric path segments and query-param values with ``_N_``
	so that ``/products?page=1`` and ``/products?page=2`` map to the same key.
	"""
	parsed = urlparse(url)
	# Path: replace purely numeric segments
	parts = parsed.path.split('/')
	norm_parts = [('_N_' if _NUMERIC_RE.match(p) else p) for p in parts]
	norm_path = '/'.join(norm_parts)
	# Query: replace purely numeric values
	params = parse_qs(parsed.query, keep_blank_values=True)
	norm_params: dict[str, list[str]] = {}
	for key in sorted(params):
		norm_params[key] = [('_N_' if _NUMERIC_RE.match(v) else v) for v in params[key]]
	norm_query = urlencode(norm_params, doseq=True)
	return urlunparse((parsed.scheme, parsed.netloc, norm_path, '', norm_query, ''))


def _make_script_id(js_code: str) -> str:
	"""Deterministic short ID for a JS script (first 8 hex chars of SHA-256)."""
	return hashlib.sha256(js_code.encode()).hexdigest()[:8]


class ScriptCache:
	"""Stores JS extraction scripts for reuse across pages.

	Supports two lookup modes:
	- **Explicit** (by ``script_id``): the agent passes back a script_id from a
	  previous extraction result.
	- **Implicit** (by URL pattern + query): paginated pages that share the same
	  URL template and extraction query automatically reuse a cached script.
	"""

	def __init__(self) -> None:
		self._by_id: dict[str, str] = {}  # script_id -> js_code
		self._by_url_query: dict[str, str] = {}  # url+query key -> script_id

	def get_by_id(self, script_id: str) -> str | None:
		"""Look up a script by its explicit ID."""
		return self._by_id.get(script_id)

	def get_by_url_query(self, url: str, query: str) -> tuple[str | None, str | None]:
		"""Look up a script by normalized URL + query. Returns (script_id, js_code) or (None, None)."""
		key = f'{_normalize_url_for_cache(url)}|{query}'
		sid = self._by_url_query.get(key)
		if sid is None:
			return None, None
		return sid, self._by_id.get(sid)

	def store(self, js_code: str, url: str, query: str) -> str:
		"""Store a successful script. Returns the generated script_id."""
		sid = _make_script_id(js_code)
		self._by_id[sid] = js_code
		key = f'{_normalize_url_for_cache(url)}|{query}'
		self._by_url_query[key] = sid
		return sid


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


# Semantic landmarks to try for auto-scoping, in priority order.
# These are standard HTML5 content markers that reliably identify the main content area.
_AUTO_SCOPE_SELECTORS = ['main', '[role="main"]', 'article', '#content', '#main']

# Only auto-scope if the scoped HTML is at least this much smaller than the full page.
_AUTO_SCOPE_MIN_REDUCTION = 0.5


async def _get_scoped_html_via_cdp(
	browser_session: 'BrowserSession',
	css_selector: str,
) -> str | None:
	"""Try to get outerHTML for a CSS selector via CDP. Returns None if no match."""
	js = f'(function(){{ var el = document.querySelector({json.dumps(css_selector)}); return el ? el.outerHTML : null; }})()'
	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js, 'returnByValue': True, 'awaitPromise': True},
		session_id=cdp_session.session_id,
	)
	value = result.get('result', {}).get('value')
	return str(value) if value is not None else None


async def _get_page_html(
	browser_session: 'BrowserSession',
	css_selector: str | None = None,
) -> tuple[str, str]:
	"""Return (html, url) for the current page.

	If *css_selector* is given, we evaluate ``querySelector(sel).outerHTML`` via CDP.
	Otherwise we get the full page HTML and attempt to auto-scope to the main content
	area using semantic landmarks (main, article, [role="main"], etc.).
	"""
	current_url = await browser_session.get_current_page_url()

	if css_selector is not None:
		# Explicit selector from programmatic caller
		value = await _get_scoped_html_via_cdp(browser_session, css_selector)
		if value is None:
			raise RuntimeError(f'CSS selector {css_selector!r} matched no element on {current_url}')
		return value, current_url

	# Full-page path — enhanced DOM → HTML serialiser
	from browser_use.dom.markdown_extractor import _get_enhanced_dom_tree_from_browser_session
	from browser_use.dom.serializer.html_serializer import HTMLSerializer

	enhanced_dom_tree = await _get_enhanced_dom_tree_from_browser_session(browser_session)
	serializer = HTMLSerializer(extract_links=False)
	full_html = serializer.serialize(enhanced_dom_tree)

	# Auto-scope: try semantic landmarks to reduce HTML size
	for selector in _AUTO_SCOPE_SELECTORS:
		scoped = await _get_scoped_html_via_cdp(browser_session, selector)
		if scoped is not None and len(scoped) < len(full_html) * _AUTO_SCOPE_MIN_REDUCTION:
			logger.debug(f'Auto-scoped to {selector!r} ({len(scoped)} chars vs {len(full_html)} full page)')
			return scoped, current_url

	return full_html, current_url


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
- Prefer structural selectors (tag, nth-child, attribute) over class names which break across sites
- Always use .textContent.trim() to get clean text
- For missing/optional fields, return null instead of throwing

<examples>
Example 1 — extract rows from a table:
```js
(function(){try{var rows=document.querySelectorAll('table tbody tr');var out=[];for(var i=0;i<rows.length;i++){var c=rows[i].querySelectorAll('td');out.push({col1:c[0]?c[0].textContent.trim():null,col2:c[1]?c[1].textContent.trim():null});}return out;}catch(e){return{error:e.message};}})()
```

Example 2 — extract repeated cards/items from a grid:
```js
(function(){try{var items=document.querySelectorAll('[class*="card"],[class*="item"],[class*="product"]');var out=[];items.forEach(function(el){var t=el.querySelector('h2,h3,h4,[class*="title"],[class*="name"]');var p=el.querySelector('[class*="price"]');var a=el.querySelector('a[href]');out.push({title:t?t.textContent.trim():null,price:p?p.textContent.trim():null,link:a?a.href:null});});return out;}catch(e){return{error:e.message};}})()
```

Example 3 — extract all links with text from a page:
```js
(function(){try{var links=document.querySelectorAll('a[href]');var out=[];links.forEach(function(a){var t=a.textContent.trim();if(t&&a.href)out.push({text:t,href:a.href});});return out;}catch(e){return{error:e.message};}})()
```
</examples>
""".strip()


async def _generate_js_script(
	llm: BaseChatModel,
	query: str,
	html: str,
	output_schema: dict | None = None,
	css_selector: str | None = None,
	error_feedback: str | None = None,
	failed_script: str | None = None,
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
		# Include the failed script so the LLM can fix it rather than regenerate blind
		if failed_script:
			user_parts.append(f'<previous_script>\n{failed_script}\n</previous_script>')

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
	script_cache: ScriptCache | None = None,
	script_id: str | None = None,
) -> tuple[Any, dict[str, Any]]:
	"""Full JS-codegen extraction pipeline.

	Returns (extracted_data, metadata_dict).

	If *script_id* is provided and found in *script_cache*, the cached script
	is executed directly — no LLM call, no HTML fetching for the prompt.

	If *script_cache* is provided without an explicit *script_id*, the cache is
	checked by URL-pattern + query (implicit pagination reuse).

	On success, ``metadata['script_id']`` contains an ID the caller can pass
	back on subsequent calls to reuse the same script.
	"""
	current_url = await browser_session.get_current_page_url()

	metadata: dict[str, Any] = {
		'js_codegen_extraction': True,
		'source_url': current_url,
	}

	# --- Explicit script_id reuse ---
	if script_id is not None and script_cache is not None:
		cached_js = script_cache.get_by_id(script_id)
		if cached_js is not None:
			logger.debug(f'Explicit script reuse: script_id={script_id}')
			try:
				data = await _execute_js_on_page(browser_session, cached_js)
				if _is_empty_result(data):
					logger.debug('Cached script returned empty result, falling through to LLM generation')
				else:
					metadata['js_script'] = cached_js
					metadata['script_id'] = script_id
					metadata['cache_hit'] = True
					metadata['retries_used'] = 0
					metadata['html_truncated'] = False
					if output_schema is not None:
						data = _validate_schema(data, output_schema, False, current_url, metadata)
					return data, metadata
			except Exception:
				logger.debug(f'Script {script_id} failed on this page, falling through to LLM generation')

	# --- Get page HTML (needed for LLM prompt and implicit cache) ---
	raw_html, url = await _get_page_html(browser_session, css_selector)
	html = _clean_html_for_codegen(raw_html)
	html, was_truncated = _truncate_html(html)
	metadata['source_url'] = url
	metadata['html_truncated'] = was_truncated

	# --- Implicit cache lookup (URL pattern + query) ---
	if script_cache is not None and script_id is None:
		cached_sid, cached_js = script_cache.get_by_url_query(url, query)
		if cached_js is not None:
			logger.debug(f'Implicit cache hit: script_id={cached_sid}')
			try:
				data = await _execute_js_on_page(browser_session, cached_js)
				if _is_empty_result(data):
					logger.debug('Cached script returned empty result, falling through to LLM generation')
				else:
					metadata['js_script'] = cached_js
					metadata['script_id'] = cached_sid
					metadata['cache_hit'] = True
					metadata['retries_used'] = 0
					if output_schema is not None:
						data = _validate_schema(data, output_schema, was_truncated, url, metadata)
					return data, metadata
			except Exception:
				logger.debug('Implicitly cached script failed, falling through to LLM generation')

	# --- LLM generation loop ---
	last_error: str | None = None
	last_script: str | None = None
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
				failed_script=last_script,
			)
			metadata['js_script'] = js_script

			data = await _execute_js_on_page(browser_session, js_script)

			# Empty result detection — treat as retryable
			if _is_empty_result(data):
				raise RuntimeError(
					'Script executed successfully but returned empty result '
					'(null, [], {}, or blank string). The selectors likely did not match any elements.'
				)

			# Schema validation if requested
			if output_schema is not None:
				data = _validate_schema(data, output_schema, was_truncated, url, metadata)

			metadata['retries_used'] = attempt
			metadata['cache_hit'] = False

			# Store successful script in cache and return script_id
			if script_cache is not None and js_script is not None:
				sid = script_cache.store(js_script, url, query)
				metadata['script_id'] = sid

			return data, metadata

		except Exception as exc:
			last_error = str(exc)
			last_script = js_script
			logger.debug(f'js_codegen_extract attempt {attempt + 1} failed: {last_error}')
			if attempt >= max_retries:
				metadata['retries_used'] = attempt
				metadata['js_script'] = js_script
				raise RuntimeError(f'js_codegen_extract failed after {attempt + 1} attempt(s): {last_error}') from exc

	# Should never reach here, but satisfy type checker
	raise RuntimeError('js_codegen_extract: unexpected control flow')  # pragma: no cover


def _validate_schema(
	data: Any,
	output_schema: dict,
	was_truncated: bool,
	url: str,
	metadata: dict[str, Any],
) -> Any:
	"""Validate *data* against *output_schema* and update *metadata* in place."""
	from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model
	from browser_use.tools.extraction.views import ExtractionResult

	try:
		model = schema_dict_to_pydantic_model(output_schema)
		validated = model.model_validate(data)
		data = validated.model_dump(mode='json')
		extraction_meta = ExtractionResult(
			data=data,
			schema_used=output_schema,
			is_partial=was_truncated,
			source_url=url,
		)
		metadata['extraction_result'] = extraction_meta.model_dump(mode='json')
	except Exception as validation_err:
		raise RuntimeError(f'Schema validation failed: {validation_err}') from validation_err
	return data
