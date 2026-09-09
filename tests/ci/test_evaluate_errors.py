"""Real Chromium regressions for diagnostics returned by the evaluate action."""

from collections.abc import AsyncIterator

import pytest

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture(scope='module')
async def evaluation_browser() -> AsyncIterator[BrowserSession]:
	"""Run local, model-free JavaScript without extensions or external pages."""
	browser = BrowserSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, use_cloud=False, enable_default_extensions=False)
	)
	await browser.start()
	try:
		yield browser
	finally:
		await browser.kill()
		await browser.event_bus.stop(clear=True, timeout=5)


async def evaluate(browser: BrowserSession, code: str) -> ActionResult:
	"""Exercise the registered action, including its normal ActionResult error path."""
	result = await Tools().registry.execute_action('evaluate', {'code': code}, browser_session=browser)
	assert isinstance(result, ActionResult)
	return result


async def test_syntax_error_does_not_execute_and_reports_the_parser_error(evaluation_browser: BrowserSession) -> None:
	"""A bare return must expose the parser diagnosis so the caller can correct the script."""
	await evaluation_browser.navigate_to('about:blank')
	code = "document.body.dataset.syntaxProbe = 'executed';\nreturn 42;"
	failed = await evaluate(evaluation_browser, code)
	assert failed.error and 'SyntaxError: Illegal return statement' in failed.error
	assert 'Location: line ' in failed.error and ', column ' in failed.error
	unchanged = await evaluate(evaluation_browser, 'document.body.dataset.syntaxProbe')
	assert unchanged.error is None and unchanged.extracted_content == 'undefined'
	corrected = await evaluate(evaluation_browser, '(function(){' + code + '})()')
	assert corrected.error is None and corrected.extracted_content == '42'


@pytest.mark.parametrize(
	('code', 'error'),
	[
		('null.missing', 'TypeError:'),
		('missingEvaluationVariable', 'ReferenceError:'),
		("Promise.reject(new Error('async failure'))", 'Error: async failure'),
		("throw 'plain failure'", 'JavaScript execution error: "plain failure"'),
		("throw ''", 'JavaScript execution error: ""'),
		('throw 0', 'JavaScript execution error: 0'),
		('throw false', 'JavaScript execution error: false'),
		('throw null', 'JavaScript execution error: null'),
	],
)
async def test_runtime_errors_and_primitive_throws_preserve_the_diagnostic(
	evaluation_browser: BrowserSession, code: str, error: str
) -> None:
	"""Runtime errors, rejected promises, and falsy thrown values must retain their details."""
	result = await evaluate(evaluation_browser, code)
	assert result.error and error in result.error


async def test_large_unicode_exception_is_bounded_and_utf8_safe(evaluation_browser: BrowserSession) -> None:
	"""A long exception with an unpaired surrogate must remain usable in logs and model input."""
	result = await evaluate(evaluation_browser, "throw new Error(String.fromCharCode(0xD800) + 'x'.repeat(5000))")
	assert result.error and 'Error:' in result.error
	assert '[Truncated exception]' in result.error
	assert len(result.error) < 5000
	result.error.encode('utf-8')
