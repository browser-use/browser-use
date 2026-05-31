import logging

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.tools.dom_scripts import build_find_elements_js, build_search_page_js
from browser_use.tools.views import FindElementsAction, SearchPageAction

logger = logging.getLogger(__name__)


async def search_page_action(params: SearchPageAction, browser_session: BrowserSession) -> ActionResult:
	"""Search visible page text through CDP without spending LLM tokens."""
	js_code = build_search_page_js(
		pattern=params.pattern,
		regex=params.regex,
		case_sensitive=params.case_sensitive,
		context_chars=params.context_chars,
		css_scope=params.css_scope,
		max_results=params.max_results,
	)

	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js_code, 'returnByValue': True, 'awaitPromise': True},
		session_id=cdp_session.session_id,
	)

	if result.get('exceptionDetails'):
		error_text = result['exceptionDetails'].get('text', 'Unknown JS error')
		return ActionResult(error=f'search_page failed: {error_text}')

	data = result.get('result', {}).get('value')
	if data is None:
		return ActionResult(error='search_page returned no result')

	if isinstance(data, dict) and data.get('error'):
		return ActionResult(error=f'search_page: {data["error"]}')

	formatted = format_search_results(data, params.pattern)
	total = data.get('total', 0)
	memory = f'Searched page for "{params.pattern}": {total} match{"es" if total != 1 else ""} found.'
	logger.info(f'🔎 {memory}')
	return ActionResult(extracted_content=formatted, long_term_memory=memory)


async def find_elements_action(params: FindElementsAction, browser_session: BrowserSession) -> ActionResult:
	"""Query page elements by CSS selector through CDP without spending LLM tokens."""
	js_code = build_find_elements_js(
		selector=params.selector,
		attributes=params.attributes,
		max_results=params.max_results,
		include_text=params.include_text,
	)

	cdp_session = await browser_session.get_or_create_cdp_session()
	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js_code, 'returnByValue': True, 'awaitPromise': True},
		session_id=cdp_session.session_id,
	)

	if result.get('exceptionDetails'):
		error_text = result['exceptionDetails'].get('text', 'Unknown JS error')
		return ActionResult(error=f'find_elements failed: {error_text}')

	data = result.get('result', {}).get('value')
	if data is None:
		return ActionResult(error='find_elements returned no result')

	if isinstance(data, dict) and data.get('error'):
		return ActionResult(error=f'find_elements: {data["error"]}')

	formatted = format_find_results(data, params.selector)
	total = data.get('total', 0)
	memory = f'Found {total} element{"s" if total != 1 else ""} matching "{params.selector}".'
	logger.info(f'🔍 {memory}')
	return ActionResult(extracted_content=formatted, long_term_memory=memory)


def format_search_results(data: dict, pattern: str) -> str:
	"""Format search_page CDP result into human-readable text for the agent."""
	if not isinstance(data, dict):
		return f'search_page returned unexpected result: {data}'

	matches = data.get('matches', [])
	total = data.get('total', 0)
	has_more = data.get('has_more', False)

	if total == 0:
		return f'No matches found for "{pattern}" on page.'

	lines = [f'Found {total} match{"es" if total != 1 else ""} for "{pattern}" on page:']
	lines.append('')
	for i, match in enumerate(matches):
		context = match.get('context', '')
		path = match.get('element_path', '')
		loc = f' (in {path})' if path else ''
		lines.append(f'[{i + 1}] {context}{loc}')

	if has_more:
		lines.append(f'\n... showing {len(matches)} of {total} total matches. Increase max_results to see more.')

	return '\n'.join(lines)


def format_find_results(data: dict, selector: str) -> str:
	"""Format find_elements CDP result into human-readable text for the agent."""
	if not isinstance(data, dict):
		return f'find_elements returned unexpected result: {data}'

	elements = data.get('elements', [])
	total = data.get('total', 0)
	showing = data.get('showing', 0)

	if total == 0:
		return f'No elements found matching "{selector}".'

	lines = [f'Found {total} element{"s" if total != 1 else ""} matching "{selector}":']
	lines.append('')
	for element in elements:
		idx = element.get('index', 0)
		tag = element.get('tag', '?')
		text = element.get('text', '')
		attrs = element.get('attrs', {})
		children = element.get('children_count', 0)

		parts = [f'[{idx}] <{tag}>']
		if text:
			display_text = ' '.join(text.split())
			if len(display_text) > 120:
				display_text = display_text[:120] + '...'
			parts.append(f'"{display_text}"')
		if attrs:
			attr_strs = [f'{k}="{v}"' for k, v in attrs.items()]
			parts.append('{' + ', '.join(attr_strs) + '}')
		parts.append(f'({children} children)')
		lines.append(' '.join(parts))

	if showing < total:
		lines.append(f'\nShowing {showing} of {total} total elements. Increase max_results to see more.')

	return '\n'.join(lines)
