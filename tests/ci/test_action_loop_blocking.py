"""Hard blocking for action loops on a stagnant page.

The existing loop detector only nudges: it appends a context message and lets the agent
repeat anyway. That suits a model that self-corrects. A small model does not — traces of
qwen3.5-9b show up to 38 consecutive identical actions against an unchanged page. Blocking
is opt-in via loop_block_threshold so no existing run changes behaviour.
"""

from browser_use.agent.views import ActionLoopDetector


def _stagnate(detector: ActionLoopDetector, times: int, url: str = 'https://example.com/a') -> None:
	"""Record the same page fingerprint `times` times, as an unchanging page would."""
	for _ in range(times):
		detector.record_page_state(url=url, dom_text='<div>same</div>', element_count=3)


class TestShouldBlock:
	def test_disabled_by_default(self):
		"""threshold=0 must never block, so existing behaviour is untouched."""
		d = ActionLoopDetector()
		for _ in range(20):
			d.record_action('click', {'index': 5})
		_stagnate(d, 20)

		assert d.should_block('click', {'index': 5}, threshold=0) is None

	def test_blocks_repeated_action_on_stagnant_page(self):
		d = ActionLoopDetector()
		for _ in range(4):
			d.record_action('click', {'index': 5})
		_stagnate(d, 4)

		reason = d.should_block('click', {'index': 5}, threshold=3)

		assert reason is not None
		assert 'click' in reason

	def test_allows_when_page_is_changing(self):
		"""Repetition while the page changes is progress, not a loop."""
		d = ActionLoopDetector()
		for i in range(6):
			d.record_action('click', {'index': 5})
			d.record_page_state(url=f'https://example.com/{i}', dom_text=f'<div>{i}</div>', element_count=3 + i)

		assert d.should_block('click', {'index': 5}, threshold=3) is None

	def test_allows_a_different_action(self):
		"""Blocking must not punish the agent for trying something new."""
		d = ActionLoopDetector()
		for _ in range(6):
			d.record_action('click', {'index': 5})
		_stagnate(d, 6)

		assert d.should_block('click', {'index': 99}, threshold=3) is None
		assert d.should_block('scroll', {'down': True, 'index': None}, threshold=3) is None

	def test_never_blocks_done(self):
		"""Blocking done would strand the agent with no way to terminate."""
		d = ActionLoopDetector()
		for _ in range(10):
			d.record_action('done', {'text': 'x', 'success': True})
		_stagnate(d, 10)

		assert d.should_block('done', {'text': 'x', 'success': True}, threshold=3) is None

	def test_below_threshold_is_allowed(self):
		d = ActionLoopDetector()
		for _ in range(2):
			d.record_action('click', {'index': 5})
		_stagnate(d, 2)

		assert d.should_block('click', {'index': 5}, threshold=5) is None

	def test_reason_tells_the_model_what_to_do(self):
		"""The blocked result is the model's only feedback, so it must be actionable."""
		d = ActionLoopDetector()
		for _ in range(5):
			d.record_action('click', {'index': 7})
		_stagnate(d, 5)

		reason = d.should_block('click', {'index': 7}, threshold=3)

		assert reason is not None
		lowered = reason.lower()
		assert 'block' in lowered
		assert any(word in lowered for word in ('different', 'another', 'change'))


class TestAgentSetting:
	def _agent(self, **kwargs):
		from browser_use import Agent
		from tests.ci.conftest import create_mock_llm

		return Agent(task='t', llm=create_mock_llm(), **kwargs)

	def test_default_threshold_is_zero(self):
		"""Off by default: this must not change any existing run."""
		agent = self._agent()
		assert agent.settings.loop_block_threshold == 0

	def test_threshold_is_configurable(self):
		agent = self._agent(loop_block_threshold=3)
		assert agent.settings.loop_block_threshold == 3

	def test_agent_block_reason_respects_threshold(self):
		"""The agent-level gate must honour both the threshold and the master switch."""
		agent = self._agent(loop_block_threshold=3)
		detector = agent.state.loop_detector
		for _ in range(4):
			detector.record_action('click', {'index': 5})
		_stagnate(detector, 4)

		assert agent._loop_block_reason('click', {'index': 5}) is not None
		assert agent._loop_block_reason('click', {'index': 6}) is None

	def test_agent_block_disabled_when_threshold_zero(self):
		agent = self._agent()
		detector = agent.state.loop_detector
		for _ in range(10):
			detector.record_action('click', {'index': 5})
		_stagnate(detector, 10)

		assert agent._loop_block_reason('click', {'index': 5}) is None

	def test_loop_detection_disabled_also_disables_blocking(self):
		"""loop_detection_enabled=False is a master switch over the whole subsystem."""
		agent = self._agent(loop_block_threshold=3, loop_detection_enabled=False)
		detector = agent.state.loop_detector
		for _ in range(10):
			detector.record_action('click', {'index': 5})
		_stagnate(detector, 10)

		assert agent._loop_block_reason('click', {'index': 5}) is None
