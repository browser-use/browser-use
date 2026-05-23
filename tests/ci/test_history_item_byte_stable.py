"""Lock down the byte-prefix property of agent history serialization.

For Gemini's implicit cache (and similar provider caches) to hit step over step,
the rendered string for steps 1..N at step N+1 must be byte-identical to the
rendered string for steps 1..N at step N. This file asserts:

1. HistoryItem is frozen — once appended, no mutation can later shift its bytes.
2. Rendering items[:N] is a strict byte-prefix of rendering items[:N+1] under
   the join used by agent_history_description (newline-separated to_string()).
3. to_string() is itself deterministic — same fields in, same bytes out.
"""

import pytest
from pydantic import ValidationError

from browser_use.agent.message_manager.views import HistoryItem


def _render(items: list[HistoryItem]) -> str:
	return '\n'.join(item.to_string() for item in items)


def test_history_item_is_frozen():
	item = HistoryItem(step_number=1, memory='m', next_goal='g', action_results='r')
	with pytest.raises(ValidationError):
		item.memory = 'mutated'  # type: ignore[misc]


def test_to_string_is_deterministic():
	a = HistoryItem(
		step_number=3,
		evaluation_previous_goal='Verdict: Success',
		memory='visited 2 pages',
		next_goal='click Submit',
		action_results='Action 1/1: clicked element 5',
	)
	b = HistoryItem(
		step_number=3,
		evaluation_previous_goal='Verdict: Success',
		memory='visited 2 pages',
		next_goal='click Submit',
		action_results='Action 1/1: clicked element 5',
	)
	assert a.to_string() == b.to_string()


def test_render_grows_by_strict_byte_prefix():
	"""The cache property: appending a new history item must extend the rendered string,
	never rewrite earlier bytes."""
	items: list[HistoryItem] = []
	prev = ''
	for n in range(1, 8):
		items.append(
			HistoryItem(
				step_number=n,
				evaluation_previous_goal=f'eval {n}',
				memory=f'mem {n}',
				next_goal=f'goal {n}',
				action_results=f'Action 1/1: did thing {n}',
			)
		)
		current = _render(items)
		assert current.startswith(prev), (
			f'Step {n} broke byte-prefix property.\nPrev tail: {prev[-200:]!r}\nCurrent at prev len: {current[: len(prev)][-200:]!r}'
		)
		prev = current


def test_prefix_property_holds_with_mixed_entry_shapes():
	"""Errors, system messages, and full step entries should all preserve byte-prefix growth."""
	items: list[HistoryItem] = [
		HistoryItem(step_number=0, system_message='Agent initialized'),
		HistoryItem(step_number=1, memory='m1', next_goal='g1', action_results='r1'),
		HistoryItem(step_number=2, error='Agent failed to output in the right format.'),
		HistoryItem(step_number=3, evaluation_previous_goal='eval', memory='m3', next_goal='g3', action_results='r3'),
		HistoryItem(system_message='<follow_up_user_request> new task </follow_up_user_request>'),
		HistoryItem(step_number=4, memory='m4', next_goal='g4', action_results='r4'),
	]
	prev = ''
	for n in range(1, len(items) + 1):
		current = _render(items[:n])
		assert current.startswith(prev), f'Mixed-shape prefix broke at n={n}'
		prev = current


def test_optional_fields_dont_silently_collapse():
	"""Conditional field inclusion in to_string() must not produce ambiguous output —
	a None field today shouldn't render identically to a populated field tomorrow."""
	with_memory = HistoryItem(step_number=1, memory='something', action_results='r').to_string()
	without_memory = HistoryItem(step_number=1, action_results='r').to_string()
	assert with_memory != without_memory, 'memory contribution to output collapsed to identity'
