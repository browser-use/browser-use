"""Initial tab selection must observe focus without changing the user's tabs."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import BrowserStartEvent
from browser_use.browser.session import Target


@pytest.mark.parametrize('focused_index', [0, 1, 2])
async def test_selects_focused_page_independently_of_discovery_order(monkeypatch, focused_index):
	session = BrowserSession(browser_profile=BrowserProfile(initial_tab='active'))
	targets = [Target(target_id=f'page-{i}', target_type='page') for i in range(3)]
	probes = []

	async def get_session(self, target_id, *, focus):
		assert focus is False
		probe = AsyncMock(return_value={'result': {'value': {'focused': target_id == f'page-{focused_index}', 'visible': True}}})
		probes.append(probe)
		return SimpleNamespace(
			cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=probe))), session_id=target_id
		)

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', get_session)
	assert await session._get_active_page_target(targets) == f'page-{focused_index}'
	assert session.agent_focus_target_id is None
	assert len(probes) == 3
	for probe in probes:
		assert probe.call_args.kwargs['params']['returnByValue'] is True


@pytest.mark.parametrize(
	'values', [[], [(False, False)], [(False, True), (False, True)], [(True, True), (True, True)], [None], ['true']]
)
async def test_ambiguous_or_unreadable_focus_never_falls_back(monkeypatch, values):
	session = BrowserSession()
	targets = [Target(target_id=str(i), target_type='page') for i in range(len(values))]

	async def get_session(self, target_id, *, focus):
		value = values[int(target_id)]
		if isinstance(value, tuple):
			value = {'focused': value[0], 'visible': value[1]}
		probe = AsyncMock(return_value={'result': {'value': value}})
		return SimpleNamespace(
			cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=probe))), session_id=target_id
		)

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', get_session)
	with pytest.raises(RuntimeError, match='Cannot determine'):
		await session._get_active_page_target(targets)
	assert session.agent_focus_target_id is None


@pytest.mark.parametrize('error', [ValueError('target detached'), TimeoutError('page unresponsive')])
async def test_probe_failure_is_not_mistaken_for_background_page(monkeypatch, error):
	session = BrowserSession()
	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', AsyncMock(side_effect=error))
	with pytest.raises(RuntimeError, match='could not be inspected'):
		await session._get_active_page_target([Target(target_id='gone', target_type='page')])


async def test_sole_visible_page_is_selected_without_document_focus(monkeypatch):
	session = BrowserSession()
	targets = [Target(target_id='background', target_type='page'), Target(target_id='visible', target_type='page')]
	# Iframes and workers must not compete with top-level pages for initial focus.
	targets.append(Target(target_id='iframe', target_type='iframe'))

	async def get_session(self, target_id, *, focus):
		assert target_id != 'iframe'
		assert focus is False
		probe = AsyncMock(return_value={'result': {'value': {'focused': False, 'visible': target_id == 'visible'}}})
		return SimpleNamespace(
			cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=SimpleNamespace(evaluate=probe))), session_id=target_id
		)

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', get_session)
	assert await session._get_active_page_target(targets) == 'visible'


async def test_cancellation_propagates(monkeypatch):
	session = BrowserSession()
	started = asyncio.Event()

	async def wait_for_session(*args, **kwargs):
		started.set()
		await asyncio.Event().wait()

	monkeypatch.setattr(BrowserSession, 'get_or_create_cdp_session', wait_for_session)
	task = asyncio.create_task(session._get_active_page_target([Target(target_id='page', target_type='page')]))
	await started.wait()
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task


async def test_active_selection_requires_endpoint_without_launching(monkeypatch):
	session = BrowserSession(browser_profile=BrowserProfile(initial_tab='active'))
	monkeypatch.setattr(BrowserSession, 'attach_all_watchdogs', AsyncMock())
	try:
		with pytest.raises(ValueError, match='requires an existing browser cdp_url'):
			await session.on_BrowserStartEvent(BrowserStartEvent())
	finally:
		await session.event_bus.stop(clear=True, timeout=1)
	assert session.cdp_url is None
	assert session.agent_focus_target_id is None
