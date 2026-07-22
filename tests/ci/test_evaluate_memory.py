from types import SimpleNamespace
from unittest.mock import AsyncMock

from browser_use.tools.service import Tools


def fake_browser_session(evaluate_response):
	evaluate = AsyncMock(return_value=evaluate_response)
	cdp_client = SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=evaluate)))
	cdp_session = SimpleNamespace(cdp_client=cdp_client, session_id='test-session')
	browser_session = SimpleNamespace(
		cdp_client=cdp_client,
		get_current_page_url=AsyncMock(return_value='https://example.com'),
		get_or_create_cdp_session=AsyncMock(return_value=cdp_session),
	)
	return browser_session, evaluate


async def test_evaluate_persists_code_for_empty_result():
	tools = Tools()
	code = 'document.title ?? ""'
	browser_session, evaluate = fake_browser_session({'result': {'value': ''}})

	result = await tools.evaluate(code=code, browser_session=browser_session)

	assert result.error is None
	assert result.extracted_content == ''
	assert result.long_term_memory == f'JavaScript executed:\n{code}\n\nResult:\n[empty string]'
	assert result.include_extracted_content_only_once is False
	evaluate.assert_awaited_once_with(
		params={'expression': code, 'returnByValue': True, 'awaitPromise': True},
		session_id='test-session',
	)


async def test_evaluate_persists_requested_and_rewritten_code():
	tools = Tools()
	code = r'document.querySelector(\"#target\")?.textContent'
	executed_code = 'document.querySelector(`#target`)?.textContent'
	browser_session, evaluate = fake_browser_session({'result': {'value': 'Found it'}})

	result = await tools.evaluate(code=code, browser_session=browser_session)

	assert result.long_term_memory == (
		f'JavaScript requested:\n{code}\n\nJavaScript executed after validation:\n{executed_code}\n\nResult:\nFound it'
	)
	evaluate.assert_awaited_once_with(
		params={'expression': executed_code, 'returnByValue': True, 'awaitPromise': True},
		session_id='test-session',
	)


async def test_evaluate_keeps_large_result_one_shot_but_persists_code():
	tools = Tools()
	code = 'document.body.innerText'
	large_result = 'x' * 10_000
	browser_session, _ = fake_browser_session({'result': {'value': large_result}})

	result = await tools.evaluate(code=code, browser_session=browser_session)

	assert result.extracted_content == large_result
	assert result.long_term_memory == (
		f'JavaScript executed:\n{code}\n\nResult:\nJavaScript returned 10000 characters. '
		'The full result was provided in read state for the next step.'
	)
	assert result.include_extracted_content_only_once is True
	assert result.long_term_memory is not None
	assert large_result not in result.long_term_memory


async def test_evaluate_persists_code_for_javascript_error():
	tools = Tools()
	code = 'missingFunction()'
	browser_session, _ = fake_browser_session({'exceptionDetails': {'text': 'Uncaught ReferenceError'}})

	result = await tools.evaluate(code=code, browser_session=browser_session)

	assert result.error is not None
	assert result.long_term_memory == (
		f'JavaScript executed:\n{code}\n\nResult:\nJavaScript execution error: Uncaught ReferenceError'
	)


async def test_evaluate_persists_code_when_cdp_session_is_unavailable():
	tools = Tools()
	code = 'document.title'
	browser_session = SimpleNamespace(
		cdp_client=SimpleNamespace(),
		get_current_page_url=AsyncMock(return_value='https://example.com'),
		get_or_create_cdp_session=AsyncMock(side_effect=RuntimeError('CDP unavailable')),
	)

	result = await tools.evaluate(code=code, browser_session=browser_session)

	assert result.error == 'Failed to execute JavaScript: RuntimeError: CDP unavailable'
	assert result.long_term_memory == (
		f'JavaScript requested:\n{code}\n\nResult:\nFailed to execute JavaScript: RuntimeError: CDP unavailable'
	)
