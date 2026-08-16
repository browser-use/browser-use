"""Lock per-step varying metadata (step counter, wall-clock date) at the tail of the user message.

The agent's user message looks roughly:
  <user_request>...</user_request>
  <agent_history>...</agent_history>
  <agent_state>...</agent_state>
  <browser_state>...</browser_state>
  [<read_state>...</read_state>]
  [<page_specific_actions>...</page_specific_actions>]
  [unavailable skills info]
  <step_info>...</step_info>   <-- new home

`<step_info>` carries a step counter and `datetime.now()`, both of which change between
calls. Keeping it at the very end means everything above it can in principle be cached;
moving it back into `<agent_state>` would silently shrink the cacheable prefix.
"""

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import AgentStepInfo
from browser_use.browser.views import BrowserStateSummary, PageInfo, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem


def _make_prompt(tmp_path, step_number: int = 3) -> AgentMessagePrompt:
	dom_state = SerializedDOMState(_root=None, selector_map={})
	bs = BrowserStateSummary(
		url='https://example.test/foo',
		title='Test',
		tabs=[TabInfo(target_id='abcd1234', url='https://example.test/foo', title='Test')],
		page_info=PageInfo(
			viewport_width=1280,
			viewport_height=720,
			page_width=1280,
			page_height=1440,
			scroll_x=0,
			scroll_y=0,
			pixels_above=0,
			pixels_below=720,
			pixels_left=0,
			pixels_right=0,
		),
		dom_state=dom_state,
		is_pdf_viewer=False,
		recent_events=None,
		closed_popup_messages=[],
		screenshot=None,
	)
	fs = FileSystem(base_dir=str(tmp_path), create_default_files=False)
	return AgentMessagePrompt(
		browser_state_summary=bs,
		file_system=fs,
		agent_history_description='<step>existing history</step>',
		task='Do the test thing',
		step_info=AgentStepInfo(step_number=step_number, max_steps=50),
	)


def test_step_info_lives_at_suffix(tmp_path):
	content = _make_prompt(tmp_path).get_user_message(use_vision=False).content
	assert isinstance(content, str)

	assert '<step_info>' in content
	assert content.index('<user_request>') < content.index('<agent_history>')
	assert content.index('</agent_history>') < content.index('<agent_state>')
	# Suffix: step_info must come after agent_state and browser_state.
	assert content.index('<agent_state>') < content.index('<step_info>')
	assert content.index('<browser_state>') < content.index('<step_info>')

	# And it must NOT live inside <agent_state> any more.
	state_start = content.index('<agent_state>')
	state_end = content.index('</agent_state>')
	assert '<step_info>' not in content[state_start:state_end], 'per-step metadata leaked into <agent_state> prefix region'
	assert '<user_request>' not in content[state_start:state_end], 'user request leaked back into <agent_state>'


def test_agent_history_end_marker_is_present_once(tmp_path):
	content = _make_prompt(tmp_path).get_user_message(use_vision=False).content
	assert isinstance(content, str)

	assert content.count('</agent_history>') == 1, (
		'super important: LLM gateway cache splitting expects exactly one </agent_history> marker'
	)


def test_prefix_up_to_step_info_is_stable_across_steps(tmp_path):
	"""Step number and date can change; the bytes before <step_info> must not."""
	a = _make_prompt(tmp_path, step_number=3).get_user_message(use_vision=False).content
	b = _make_prompt(tmp_path, step_number=4).get_user_message(use_vision=False).content
	assert isinstance(a, str) and isinstance(b, str)
	prefix_end = a.index('<step_info>')
	assert a[:prefix_end] == b[:prefix_end], 'message bytes diverged before <step_info> — step counter is leaking into the prefix'
	# Sanity: the tails do differ (step counter advanced).
	assert a[prefix_end:] != b[prefix_end:]


def test_agent_state_block_unaffected_by_step_change(tmp_path):
	"""<agent_state> should not include per-step-varying metadata."""
	a = _make_prompt(tmp_path, step_number=3).get_user_message(use_vision=False).content
	b = _make_prompt(tmp_path, step_number=4).get_user_message(use_vision=False).content
	assert isinstance(a, str) and isinstance(b, str)

	def agent_state_block(s: str) -> str:
		return s[s.index('<agent_state>') : s.index('</agent_state>')]

	assert agent_state_block(a) == agent_state_block(b)
