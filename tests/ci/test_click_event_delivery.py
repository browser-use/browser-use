"""Regression tests for verification of standard CDP click delivery."""

# Tests use intentionally partial CDP/DOM doubles.
# pyright: reportArgumentType=false, reportOptionalMemberAccess=false

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.tools.utils import get_click_delivery_message


def _watchdog() -> DefaultActionWatchdog:
	browser_session = SimpleNamespace(logger=logging.getLogger('test.click_event_delivery'))
	return DefaultActionWatchdog.model_construct(browser_session=browser_session, event_bus=SimpleNamespace())


def _cdp_session(*, resolve_result=None, runtime_results=None):
	resolve_node = AsyncMock(return_value=resolve_result or {'object': {'objectId': 'object-1'}})
	call_function = AsyncMock(side_effect=runtime_results)
	send = SimpleNamespace(
		DOM=SimpleNamespace(resolveNode=resolve_node),
		Runtime=SimpleNamespace(callFunctionOn=call_function),
	)
	return (
		SimpleNamespace(
			cdp_client=SimpleNamespace(send=send),
			session_id='session-1',
		),
		resolve_node,
		call_function,
	)


@pytest.mark.asyncio
async def test_install_click_event_probe_returns_element_object_id() -> None:
	watchdog = _watchdog()
	cdp_session, resolve_node, call_function = _cdp_session(runtime_results=[{'result': {'value': True}}])

	object_id = await watchdog._install_click_event_probe(cdp_session, backend_node_id=42)

	assert object_id == 'object-1'
	resolve_node.assert_awaited_once_with(params={'backendNodeId': 42}, session_id='session-1')
	assert '__browserUseClickProbe' in call_function.await_args.kwargs['params']['functionDeclaration']


@pytest.mark.asyncio
async def test_native_click_event_does_not_trigger_fallback() -> None:
	watchdog = _watchdog()
	cdp_session, _, call_function = _cdp_session(runtime_results=[{'result': {'value': True}}, {'result': {'value': True}}])

	received = await watchdog._verify_click_event_or_fallback(cdp_session, 'object-1')

	assert received is True
	assert call_function.await_count == 2  # read, cleanup
	assert 'this.click()' not in call_function.await_args_list[0].kwargs['params']['functionDeclaration']


@pytest.mark.asyncio
async def test_missing_native_click_event_uses_javascript_fallback() -> None:
	watchdog = _watchdog()
	cdp_session, _, call_function = _cdp_session(
		runtime_results=[
			{'result': {'value': False}},
			{},
			{'result': {'value': True}},
			{'result': {'value': True}},
		]
	)

	with patch('browser_use.browser.watchdogs.default_action_watchdog.asyncio.sleep', new=AsyncMock()) as sleep_mock:
		received = await watchdog._verify_click_event_or_fallback(cdp_session, 'object-1')

	assert received is True
	assert call_function.await_count == 4  # read, JS click, read, cleanup
	assert 'this.click()' in call_function.await_args_list[1].kwargs['params']['functionDeclaration']
	sleep_mock.assert_awaited_once_with(0.05)


def test_detects_button_nested_in_aria_dialog() -> None:
	dialog = SimpleNamespace(tag_name='div', attributes={'role': 'dialog'}, parent_node=None)
	container = SimpleNamespace(tag_name='div', attributes={}, parent_node=dialog)
	button = SimpleNamespace(tag_name='button', attributes={}, parent_node=container)

	assert DefaultActionWatchdog._has_dialog_ancestor(button) is True


def test_does_not_treat_ordinary_button_as_dialog_button() -> None:
	main = SimpleNamespace(tag_name='main', attributes={}, parent_node=None)
	button = SimpleNamespace(tag_name='button', attributes={}, parent_node=main)

	assert DefaultActionWatchdog._has_dialog_ancestor(button) is False


def test_click_result_does_not_claim_the_intended_outcome() -> None:
	message = get_click_delivery_message('button "Save"')

	assert message.startswith('Clicked button "Save".')
	assert 'delivery is confirmed' in message
	assert 'outcome is unverified' in message
	assert 'verify the resulting browser state' in message
