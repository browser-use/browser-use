from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from cdp_use import CDPClient
from cdp_use.cdp.target import AttachedToTargetEvent, DetachedFromTargetEvent

import browser_use.browser.session_manager as session_manager_module
from browser_use.browser import BrowserSession
from browser_use.browser.session_manager import SessionManager


def _attached_event() -> AttachedToTargetEvent:
	return cast(
		AttachedToTargetEvent,
		{
			'sessionId': 'session-id',
			'targetInfo': {
				'targetId': 'iframe-target-id',
				'type': 'iframe',
				'url': 'https://iframe.example',
				'title': 'Iframe',
			},
			'waitingForDebugger': False,
		},
	)


def _detached_event() -> DetachedFromTargetEvent:
	return cast(DetachedFromTargetEvent, {'sessionId': 'session-id'})


async def test_detach_during_auto_attach_does_not_leave_stale_session() -> None:
	set_auto_attach_started = asyncio.Event()
	release_set_auto_attach = asyncio.Event()

	async def block_set_auto_attach(*args: Any, **kwargs: Any) -> None:
		del args, kwargs
		set_auto_attach_started.set()
		await release_set_auto_attach.wait()

	root_client = CDPClient('ws://unused')
	root_client.send.Target.setAutoAttach = AsyncMock(side_effect=block_set_auto_attach)
	browser_session = BrowserSession()
	browser_session._cdp_client_root = root_client
	manager = SessionManager(browser_session)

	attach_task = asyncio.create_task(manager._handle_target_attached(_attached_event()))
	await set_auto_attach_started.wait()

	await manager._handle_target_detached(_detached_event())
	release_set_auto_attach.set()
	await attach_task

	assert manager.get_session('session-id') is None
	assert manager.get_target('iframe-target-id') is None
	assert manager.get_target_id_from_session_id('session-id') is None
	assert manager.get_target_sessions_mapping() == {}


async def test_detach_event_cancels_attach_before_attach_task_runs(monkeypatch: pytest.MonkeyPatch) -> None:
	scheduled_tasks: list[asyncio.Task[Any]] = []

	def capture_task(
		coro: Coroutine[Any, Any, Any],
		*,
		name: str | None = None,
		logger_instance: logging.Logger | None = None,
		suppress_exceptions: bool = False,
	) -> asyncio.Task[Any]:
		del logger_instance, suppress_exceptions
		task = asyncio.create_task(coro, name=name)
		scheduled_tasks.append(task)
		return task

	monkeypatch.setattr(session_manager_module, 'create_task_with_error_handling', capture_task)

	root_client = CDPClient('ws://unused')
	root_client.send.Target.setDiscoverTargets = AsyncMock()
	root_client.send.Target.setAutoAttach = AsyncMock()
	browser_session = BrowserSession()
	browser_session._cdp_client_root = root_client
	manager = SessionManager(browser_session)
	monkeypatch.setattr(manager, '_initialize_existing_targets', AsyncMock())
	await manager.start_monitoring()

	await root_client.emit_event('Target.attachedToTarget', _attached_event())
	await root_client.emit_event('Target.detachedFromTarget', _detached_event())
	await asyncio.gather(*scheduled_tasks)

	assert manager.get_session('session-id') is None
	assert manager.get_target('iframe-target-id') is None
	assert manager.get_target_id_from_session_id('session-id') is None
	assert manager.get_target_sessions_mapping() == {}
	root_client.send.Target.setAutoAttach.assert_not_awaited()
