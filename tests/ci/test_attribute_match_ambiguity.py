"""Tests for ambiguity handling in ATTRIBUTE-level (Level 5) element matching.

Level 5 of `_update_action_indices` matches historical elements by the
`name`/`id`/`aria-label` attributes for old history files that lack a
stable_hash. When several elements on the current page share the same
attribute value, rewriting the action index to the first hit would silently
target the wrong element. These tests verify that ambiguous attribute matches
are rejected (treated like a miss) and that unique matches still rewrite.

Zero-browser tests: they call `Agent._update_action_indices` directly with
stubbed selector maps and a minimal fake action.
"""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from browser_use.agent.service import Agent
from browser_use.dom.views import DOMInteractedElement, NodeType, SerializedDOMState


def mk_hist(**attr_overrides: Any) -> DOMInteractedElement:
	"""Historical element whose hash/stable_hash/xpath match nothing on the page,
	forcing the cascade down to the ATTRIBUTE level."""
	attrs = {'name': 'qty'}
	attrs.update(attr_overrides)
	return DOMInteractedElement(
		node_id=1,
		backend_node_id=1,
		frame_id=None,
		node_type=NodeType.ELEMENT_NODE,
		node_value='',
		node_name='INPUT',
		attributes=attrs,
		bounds=None,
		x_path='html/body/ghost',  # matches no node below
		element_hash=111111,  # matches no node below
		stable_hash=222222,  # matches no node below
		ax_name=None,  # skip AX_NAME level
	)


def mk_node(
	idx: int,
	node_name: str = 'INPUT',
	**attrs: str,
) -> SimpleNamespace:
	"""Stub selector-map node with per-index unique hash/xpath so only the
	ATTRIBUTE level can match."""
	return SimpleNamespace(
		frame_id=None,
		node_name=node_name,
		attributes=dict(attrs) or None,
		element_hash=900000 + idx,
		xpath=f'html/body/div[{idx}]',
		compute_stable_hash=lambda idx=idx: 800000 + idx,
		ax_node=None,
	)


def mk_state(selector_map: dict[int, SimpleNamespace]) -> SimpleNamespace:
	"""Minimal BrowserStateSummary stand-in: only `.dom_state.selector_map` is read."""
	return SimpleNamespace(dom_state=SerializedDOMState(_root=None, selector_map=selector_map))  # type: ignore[arg-type]


class FakeAction:
	"""Minimal stand-in for ActionModel with the get_index/set_index protocol."""

	def __init__(self, index: int):
		self._index = index
		self.set_index_calls: list[int] = []

	def get_index(self) -> int | None:
		return self._index

	def set_index(self, index: int):
		self.set_index_calls.append(index)
		self._index = index


def run_update(hist: DOMInteractedElement, action: FakeAction, state: Any) -> Any:
	"""Call the unbound async method with a bare `self` that only carries a logger."""
	fake_self = SimpleNamespace(logger=logging.getLogger('test_attribute_match_ambiguity'))
	return asyncio.run(Agent._update_action_indices(fake_self, hist, action, state))  # type: ignore[arg-type]


def test_ambiguous_attribute_match_returns_none_and_keeps_index():
	"""Two INPUTs share name='qty' -> the match is ambiguous, must NOT rewrite.

	Bug (RED before fix): the loop breaks on the first hit and silently
	reindexes 9 -> 5.
	"""
	selector_map = {
		5: mk_node(5, name='qty'),
		9: mk_node(9, name='qty'),
	}
	hist = mk_hist()
	action = FakeAction(index=9)

	result = run_update(hist, action, mk_state(selector_map))

	assert result is None, 'Ambiguous attribute match must be treated as a miss (return None)'
	assert action.get_index() == 9, 'Action index must be left untouched on ambiguity'
	assert action.set_index_calls == [], 'set_index must not be called on ambiguity'


def test_unique_attribute_match_still_rewrites_index():
	"""Exactly one INPUT with name='qty' (plus decoys) -> rewrite is safe."""
	selector_map = {
		3: mk_node(3, name='other'),
		5: mk_node(5, name='qty'),
		7: mk_node(7, name='other2'),
	}
	hist = mk_hist()
	action = FakeAction(index=9)

	result = run_update(hist, action, mk_state(selector_map))

	assert result is action
	assert action.get_index() == 5
	assert action.set_index_calls == [5]


def test_ambiguous_name_falls_through_to_unique_id():
	"""Ambiguous `name` must fall through like a miss; unique `id` still matches."""
	selector_map = {
		5: mk_node(5, name='qty'),
		9: mk_node(9, name='qty', id='qty-main'),
	}
	hist = mk_hist(name='qty', id='qty-main')
	action = FakeAction(index=42)

	result = run_update(hist, action, mk_state(selector_map))

	assert result is action
	assert action.get_index() == 9, 'Must resolve via the unique id, not the first name hit (5)'
	assert action.set_index_calls == [9]


def test_no_attribute_match_returns_none():
	"""No element carries the historical identifier -> whole level misses -> None."""
	selector_map = {
		5: mk_node(5, name='other'),
		9: mk_node(9, name='other2'),
	}
	hist = mk_hist()
	action = FakeAction(index=9)

	result = run_update(hist, action, mk_state(selector_map))

	assert result is None
	assert action.get_index() == 9
	assert action.set_index_calls == []
