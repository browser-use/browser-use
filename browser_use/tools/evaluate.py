import json
import logging
import re

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.tools.views import EvaluateAction

logger = logging.getLogger(__name__)


def validate_and_fix_javascript(code: str) -> str:
	"""Validate and fix common JavaScript issues before execution."""
	# Pattern 1: Fix double-escaped quotes (\\\" -> ")
	fixed_code = re.sub(r'\\"', '"', code)

	# Pattern 2: Fix over-escaped regex patterns (\\\\d -> \\d)
	# Common issue: regex gets double-escaped during parsing.
	fixed_code = re.sub(r'\\\\([dDsSwWbBnrtfv])', r'\\\1', fixed_code)
	fixed_code = re.sub(r'\\\\([.*+?^${}()|[\]])', r'\\\1', fixed_code)

	# Pattern 3: Fix XPath expressions with mixed quotes.
	xpath_pattern = r'document\.evaluate\s*\(\s*"([^"]*)"\s*,'

	def fix_xpath_quotes(match: re.Match[str]) -> str:
		xpath_with_quotes = match.group(1)
		return f'document.evaluate(`{xpath_with_quotes}`,'

	fixed_code = re.sub(xpath_pattern, fix_xpath_quotes, fixed_code)

	# Pattern 4: Fix querySelector/querySelectorAll with mixed quotes.
	selector_pattern = r'(querySelector(?:All)?)\s*\(\s*"([^"]*)"\s*\)'

	def fix_selector_quotes(match: re.Match[str]) -> str:
		method_name = match.group(1)
		selector_with_quotes = match.group(2)
		return f'{method_name}(`{selector_with_quotes}`)'

	fixed_code = re.sub(selector_pattern, fix_selector_quotes, fixed_code)

	# Pattern 5: Fix closest() calls with mixed quotes.
	closest_pattern = r'\.closest\s*\(\s*"([^"]*)"\s*\)'

	def fix_closest_quotes(match: re.Match[str]) -> str:
		selector_with_quotes = match.group(1)
		return f'.closest(`{selector_with_quotes}`)'

	fixed_code = re.sub(closest_pattern, fix_closest_quotes, fixed_code)

	# Pattern 6: Fix .matches() calls with mixed quotes.
	matches_pattern = r'\.matches\s*\(\s*"([^"]*)"\s*\)'

	def fix_matches_quotes(match: re.Match[str]) -> str:
		selector_with_quotes = match.group(1)
		return f'.matches(`{selector_with_quotes}`)'

	fixed_code = re.sub(matches_pattern, fix_matches_quotes, fixed_code)

	changes_made = []
	if r'\"' in code and r'\"' not in fixed_code:
		changes_made.append('fixed escaped quotes')
	if '`' in fixed_code and '`' not in code:
		changes_made.append('converted mixed quotes to template literals')

	if changes_made:
		logger.debug(f'JavaScript fixes applied: {", ".join(changes_made)}')

	return fixed_code


async def execute_evaluate_action(params: EvaluateAction, browser_session: BrowserSession) -> ActionResult:
	"""Execute browser JavaScript and normalize CDP results for the agent."""
	code = params.code
	cdp_session = await browser_session.get_or_create_cdp_session()

	try:
		validated_code = validate_and_fix_javascript(code)

		# Always use awaitPromise=True; CDP ignores it for non-promise values.
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': validated_code, 'returnByValue': True, 'awaitPromise': True},
			session_id=cdp_session.session_id,
		)

		if result.get('exceptionDetails'):
			exception = result['exceptionDetails']
			error_msg = f'JavaScript execution error: {exception.get("text", "Unknown error")}'
			enhanced_msg = f"""JavaScript Execution Failed:
{error_msg}

Validated Code (after quote fixing):
{validated_code[:500]}{'...' if len(validated_code) > 500 else ''}
"""
			logger.debug(enhanced_msg)
			return ActionResult(error=enhanced_msg)

		result_data = result.get('result', {})
		if result_data.get('wasThrown'):
			msg = f'JavaScript code: {code} execution failed (wasThrown=true)'
			logger.debug(msg)
			return ActionResult(error=msg)

		value = result_data.get('value')
		if value is None:
			result_text = str(value) if 'value' in result_data else 'undefined'
		elif isinstance(value, (dict, list)):
			try:
				result_text = json.dumps(value, ensure_ascii=False)
			except (TypeError, ValueError):
				result_text = str(value)
		else:
			result_text = str(value)

		image_pattern = r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)'
		found_images = re.findall(image_pattern, result_text)

		metadata = None
		if found_images:
			metadata = {'images': found_images}
			for img_data in found_images:
				result_text = result_text.replace(img_data, '[Image]')

		if len(result_text) > 20000:
			result_text = result_text[:19950] + '\n... [Truncated after 20000 characters]'

		logger.debug(f'JavaScript executed successfully, result length: {len(result_text)}')

		max_memory_length = 10000
		if len(result_text) < max_memory_length:
			memory = result_text
			include_extracted_content_only_once = False
		else:
			memory = f'JavaScript executed successfully, result length: {len(result_text)} characters.'
			include_extracted_content_only_once = True

		return ActionResult(
			extracted_content=result_text,
			long_term_memory=memory,
			include_extracted_content_only_once=include_extracted_content_only_once,
			metadata=metadata,
		)
	except Exception as e:
		error_msg = f'Failed to execute JavaScript: {type(e).__name__}: {e}'
		logger.debug(f'JavaScript code that failed: {code[:200]}...')
		return ActionResult(error=error_msg)
