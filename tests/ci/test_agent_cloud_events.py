from types import SimpleNamespace

from browser_use.agent.cloud_events import CreateAgentTaskEvent


class CustomAdapter:
	model = 'custom-model'

	@property
	def provider(self) -> str:
		return 'custom'

	@property
	def name(self) -> str:
		return self.model

	async def ainvoke(self, messages, output_format=None, **kwargs):
		raise AssertionError('not used by this test')


def test_create_agent_task_event_uses_canonical_llm_model_property():
	llm = CustomAdapter()
	assert not hasattr(llm, 'model_name')
	agent = SimpleNamespace(
		task_id='task-id',
		session_id='session-id',
		task='test task',
		llm=llm,
		state=SimpleNamespace(model_dump=lambda: {}),
		_task_start_time=0,
		cloud_sync=None,
	)

	event = CreateAgentTaskEvent.from_agent(agent)

	assert event.llm_model == 'custom-model'
