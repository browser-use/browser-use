from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList, AgentOutput


class RecordingWatchdogShouldNotBeCalled:
	is_recording = True

	async def stop_recording(self) -> Path:
		raise AssertionError('stop_recording should not be called')


def test_agent_history_list_serializes_video_recording_path():
	history = AgentHistoryList(history=[], video_recording_path='/tmp/session.mp4')

	data = history.model_dump()

	assert data['video_recording_path'] == '/tmp/session.mp4'
	assert AgentHistoryList.load_from_dict(data, AgentOutput).video_recording_path == '/tmp/session.mp4'


def test_agent_history_list_omits_empty_video_recording_path():
	assert AgentHistoryList(history=[]).model_dump() == {'history': []}


@pytest.mark.asyncio
async def test_finalize_video_recording_path_skips_missing_browser_session():
	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = None

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path is None


@pytest.mark.asyncio
async def test_finalize_video_recording_path_updates_history():
	class FakeWatchdog:
		is_recording = True

		async def stop_recording(self) -> Path:
			return Path('/tmp/session.mp4')

	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = SimpleNamespace(
		id='browser-session',
		browser_profile=SimpleNamespace(keep_alive=False),
		_recording_watchdog=FakeWatchdog(),
	)

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path == '/tmp/session.mp4'


@pytest.mark.asyncio
async def test_finalize_video_recording_path_skips_keep_alive_sessions():
	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = SimpleNamespace(
		id='browser-session',
		agent_focus_target_id=None,
		browser_profile=SimpleNamespace(keep_alive=True),
		_recording_watchdog=RecordingWatchdogShouldNotBeCalled(),
	)

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path is None


@pytest.mark.asyncio
async def test_finalize_video_recording_path_skips_missing_watchdog():
	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = SimpleNamespace(
		id='browser-session',
		agent_focus_target_id=None,
		browser_profile=SimpleNamespace(keep_alive=False),
	)

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path is None


@pytest.mark.asyncio
async def test_finalize_video_recording_path_skips_inactive_watchdog():
	class InactiveWatchdog:
		is_recording = False

		async def stop_recording(self) -> Path:
			raise AssertionError('stop_recording should not be called')

	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = SimpleNamespace(
		id='browser-session',
		agent_focus_target_id=None,
		browser_profile=SimpleNamespace(keep_alive=False),
		_recording_watchdog=InactiveWatchdog(),
	)

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path is None


@pytest.mark.asyncio
async def test_finalize_video_recording_path_swallows_stop_errors():
	class FailingWatchdog:
		is_recording = True

		async def stop_recording(self) -> Path:
			raise RuntimeError('no encoder')

	agent = cast(Any, object.__new__(Agent))
	agent.history = AgentHistoryList(history=[])
	agent.browser_session = SimpleNamespace(
		id='browser-session',
		agent_focus_target_id=None,
		browser_profile=SimpleNamespace(keep_alive=False),
		_recording_watchdog=FailingWatchdog(),
	)

	await Agent._finalize_video_recording_path(agent)

	assert agent.history.video_recording_path is None
