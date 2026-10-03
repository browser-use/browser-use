"""Lock down the byte-prefix property of agent history serialization.

Provider prompt caches (Gemini implicit, Anthropic ephemeral) only reuse a
byte-identical prefix. For the agent-history portion of the prompt to hit step
over step, rendering steps 1..N at step N+1 must extend - never rewrite - what
was rendered at step N.

Restores the coverage removed in 51598efd and extends it to the
`max_history_items` window, which previously slid one item per step and so
rewrote the transcript on every single call.
"""

import pytest
from pydantic import ValidationError

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.message_manager.views import HistoryItem
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage


def _manager(base_dir, **kwargs) -> MessageManager:
	return MessageManager(
		task='find the cheapest flight',
		system_message=SystemMessage(content='SYSTEM'),
		file_system=FileSystem(base_dir=base_dir),
		**kwargs,
	)


def _item(n: int) -> HistoryItem:
	return HistoryItem(
		step_number=n,
		evaluation_previous_goal=f'Verdict: Success - step {n}',
		memory=f'Visited {n} pages',
		next_goal=f'Click result {n + 1}',
		action_results=f'Action 1/1: clicked element {n}',
	)


def test_history_item_is_frozen():
	"""Once appended, an item must not be able to shift bytes rendered earlier."""
	item = _item(1)
	with pytest.raises(ValidationError):
		item.memory = 'mutated'  # type: ignore[misc]


def test_render_is_append_only_without_a_window(tmp_path):
	"""With no limit the transcript is a strict byte-prefix of the next step's."""
	manager = _manager(tmp_path)
	previous = ''
	for n in range(1, 12):
		manager.state.agent_history_items.append(_item(n))
		current = manager.agent_history_description
		assert current.startswith(previous), f'step {n} rewrote earlier bytes'
		previous = current


def test_window_evicts_in_blocks_not_one_item_per_step(tmp_path):
	"""The window may only shift at eviction boundaries.

	A window that slides one item per step rewrites the transcript on every step,
	which pins the cacheable prefix at a few dozen bytes for the rest of the run.
	The guarantee here is relative: most steps past the limit must extend the
	previous render rather than rewrite it.
	"""
	limit, steps = 25, 80
	manager = _manager(tmp_path, max_history_items=limit)
	previous, bursts = '', 0
	for n in range(1, steps + 1):
		manager.state.agent_history_items.append(_item(n))
		current = manager.agent_history_description
		if n > limit and not current.startswith(previous):
			bursts += 1
		previous = current

	# Sliding per step bursts on every one of these; blockwise must leave most intact.
	slid_every_step = steps - limit
	assert bursts < slid_every_step / 3, f'{bursts} bursts of a possible {slid_every_step} - still sliding per step'


def test_omitted_marker_is_stable_between_evictions(tmp_path):
	"""The count inside the marker must not change on every step."""
	manager = _manager(tmp_path, max_history_items=25)
	markers = []
	for n in range(1, 81):
		manager.state.agent_history_items.append(_item(n))
		for line in manager.agent_history_description.split('\n'):
			if '<sys>' in line:
				markers.append(line)
				break

	assert markers, 'expected an omitted-steps marker once the window filled'
	# A per-step counter makes every marker distinct; blockwise eviction changes it
	# only when the window start actually moves.
	changes = sum(1 for a, b in zip(markers, markers[1:]) if a != b)
	assert changes <= len(markers) // 3, f'omitted count changed {changes}x over {len(markers)} steps'


def test_window_never_exceeds_max_history_items(tmp_path):
	"""Blockwise eviction must not overshoot the configured cap."""
	for limit in (6, 10, 25):
		manager = _manager(tmp_path, max_history_items=limit)
		for n in range(1, 81):
			manager.state.agent_history_items.append(_item(n))
			rendered = manager.agent_history_description
			# Item 0 is the 'Agent initialized' system message, which renders without a
			# <step> tag - count it back in or the cap check is off by one.
			shown = rendered.count('<step>') + 1
			assert shown <= limit, f'limit={limit} step={n} rendered {shown} items, over cap'
			if n > limit:
				assert shown > limit * 0.7, f'limit={limit} step={n} rendered only {shown} items'
			assert rendered.count('Visited 1 pages') <= 1, 'first item rendered twice'
