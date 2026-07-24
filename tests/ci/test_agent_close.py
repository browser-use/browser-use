from typing import Any, cast

from browser_use.agent.service import Agent


class FakeEventBus:
	def __init__(self):
		self.stop_calls = []
		self.event_queue = object()
		self._on_idle = object()

	async def stop(self, **kwargs):
		self.stop_calls.append(kwargs)


class FakeBrowserProfile:
	def __init__(self, keep_alive: bool):
		self.keep_alive = keep_alive


class FakeBrowserSession:
	def __init__(self, keep_alive: bool):
		self.id = 'fake-browser-session'
		self.agent_focus_target_id = None
		self.browser_profile = FakeBrowserProfile(keep_alive=keep_alive)
		self.event_bus = FakeEventBus()
		self.kill_calls = 0

	async def kill(self):
		self.kill_calls += 1


class FakeSkillService:
	def __init__(self):
		self.close_calls = 0

	async def close(self):
		self.close_calls += 1


def make_agent(browser_session: FakeBrowserSession, skill_service: FakeSkillService | None = None) -> Agent:
	agent = cast(Any, object.__new__(Agent))
	agent.browser_session = browser_session
	agent.skill_service = skill_service
	return cast(Agent, agent)


async def test_agent_close_kills_non_keep_alive_browser_session():
	session = FakeBrowserSession(keep_alive=False)
	skill_service = FakeSkillService()
	agent = make_agent(session, skill_service)

	await agent.close()

	assert session.kill_calls == 1
	assert session.event_bus.stop_calls == []
	assert session.event_bus.event_queue is not None
	assert session.event_bus._on_idle is not None
	assert skill_service.close_calls == 1


async def test_agent_close_preserves_keep_alive_event_bus():
	session = FakeBrowserSession(keep_alive=True)
	event_queue = session.event_bus.event_queue
	on_idle = session.event_bus._on_idle
	skill_service = FakeSkillService()
	agent = make_agent(session, skill_service)

	await agent.close()

	assert session.kill_calls == 0
	assert session.event_bus.stop_calls == []
	assert session.event_bus.event_queue is event_queue
	assert session.event_bus._on_idle is on_idle
	assert skill_service.close_calls == 1
