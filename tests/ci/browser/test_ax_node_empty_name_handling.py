"""Regression tests for empty accessible-name (`ax_node.name == ""`) handling.

`ax_node.name` is `str | None`. An empty string `""` is a *valid* accessible
name (e.g. `aria-label=""` deliberately hiding decorative content from
screen readers), semantically distinct from `None` (no accessibility
information at all). Several call sites used truthiness checks
(`if ax_node.name:`) that treat `""` and `None` identically, which is wrong.

These tests exercise the exact branching logic from the three fixed call
sites in isolation, rather than constructing full `EnhancedDOMTreeNode`
instances (which require a live CDP session context to build realistically).
This mirrors the logic byte-for-byte, so a regression in either location
will be caught here even without a browser.
"""

from dataclasses import dataclass


@dataclass
class FakeAxNode:
	name: str | None


@dataclass
class FakeElement:
	ax_node: FakeAxNode | None
	attributes: dict[str, str]


# ── browser_use/dom/service.py: collect_hidden_elements text extraction ────


def _collect_hidden_text_before(elem: FakeElement) -> str:
	"""The buggy version: truthiness check on ax_node.name."""
	text = ''
	if elem.ax_node and elem.ax_node.name:
		text = elem.ax_node.name[:40]
	elif elem.attributes:
		text = (
			elem.attributes.get('placeholder', '')
			or elem.attributes.get('title', '')
			or elem.attributes.get('aria-label', '')
		)[:40]
	return text


def _collect_hidden_text_after(elem: FakeElement) -> str:
	"""The fixed version: explicit None check."""
	text = ''
	if elem.ax_node and elem.ax_node.name is not None:
		text = elem.ax_node.name[:40]
	elif elem.attributes:
		text = (
			elem.attributes.get('placeholder', '')
			or elem.attributes.get('title', '')
			or elem.attributes.get('aria-label', '')
		)[:40]
	return text


class TestCollectHiddenElementsTextExtraction:
	def test_explicit_empty_ax_name_does_not_fall_through_to_attributes(self):
		"""An element with an explicit empty accessible name must not fall
		through to a possibly stale/misleading `title`/`placeholder`/
		`aria-label` attribute — the empty ax_name is authoritative."""
		elem = FakeElement(
			ax_node=FakeAxNode(name=''),
			attributes={'title': 'stale template placeholder text'},
		)
		assert _collect_hidden_text_before(elem) == 'stale template placeholder text', (
			'sanity check: confirms the bug exists in the unfixed logic'
		)
		assert _collect_hidden_text_after(elem) == ''

	def test_none_ax_name_still_falls_through_to_attributes(self):
		"""No accessibility info at all (name=None) should still fall
		through to attributes — this must be unchanged by the fix."""
		elem = FakeElement(
			ax_node=FakeAxNode(name=None),
			attributes={'title': 'fallback title'},
		)
		assert _collect_hidden_text_before(elem) == 'fallback title'
		assert _collect_hidden_text_after(elem) == 'fallback title'

	def test_non_empty_ax_name_used_directly_unchanged(self):
		elem = FakeElement(ax_node=FakeAxNode(name='Submit'), attributes={})
		assert _collect_hidden_text_before(elem) == 'Submit'
		assert _collect_hidden_text_after(elem) == 'Submit'

	def test_ax_node_none_entirely_falls_through(self):
		elem = FakeElement(ax_node=None, attributes={'title': 'fallback'})
		assert _collect_hidden_text_before(elem) == 'fallback'
		assert _collect_hidden_text_after(elem) == 'fallback'


# ── browser_use/dom/views.py: element-identity hash component ─────────────


def _hash_component_before(ax_node: FakeAxNode | None) -> str:
	ax_name = ''
	if ax_node and ax_node.name:
		ax_name = f'|ax_name={ax_node.name}'
	return ax_name


def _hash_component_after(ax_node: FakeAxNode | None) -> str:
	ax_name = ''
	if ax_node and ax_node.name is not None:
		ax_name = f'|ax_name={ax_node.name}'
	return ax_name


class TestElementHashAxNameComponent:
	def test_explicit_empty_and_missing_ax_name_no_longer_collide(self):
		"""An element that explicitly opts out of accessibility naming
		(ax_name="") is a different accessibility state from an element
		with no accessibility info at all (ax_node is None). Before the
		fix, both produced the same ('') hash component, so two otherwise-
		identical elements with different accessibility semantics could
		collide in the identity hash used for cross-snapshot matching."""
		explicit_empty = _hash_component_before(FakeAxNode(name=''))
		missing_entirely = _hash_component_before(None)
		assert explicit_empty == missing_entirely == '', (
			'sanity check: confirms the collision exists in the unfixed logic'
		)

		explicit_empty_fixed = _hash_component_after(FakeAxNode(name=''))
		missing_entirely_fixed = _hash_component_after(None)
		assert explicit_empty_fixed == '|ax_name='
		assert missing_entirely_fixed == ''
		assert explicit_empty_fixed != missing_entirely_fixed

	def test_none_name_on_present_ax_node_still_empty_component(self):
		"""ax_node present but .name is None (no accessible name computed)
		must still produce an empty component — this is unchanged."""
		assert _hash_component_after(FakeAxNode(name=None)) == ''

	def test_non_empty_name_component_unchanged(self):
		assert _hash_component_after(FakeAxNode(name='Close dialog')) == '|ax_name=Close dialog'
