"""Regression test: an explicit empty ``include_attributes`` list must disable
attribute serialization.

``DOMTreeSerializer`` only prints attributes whose name appears in
``include_attributes``, and ``Agent(include_attributes=[])`` is the natural way to
ask for a lean DOM (no attributes at all). ``SerializedDOMState.llm_representation``
substituted the ~55-entry ``DEFAULT_INCLUDE_ATTRIBUTES`` list whenever the argument
was falsy, so an explicit ``[]`` was indistinguishable from "unset" and the option
was silently ignored.

``None`` ("unset" -> defaults) and ``[]`` ("no attributes") therefore have to stay
distinguishable, which also means ``MessageManager`` must not coerce ``None`` into
``[]`` before handing the value to ``AgentMessagePrompt``.
"""

from pathlib import Path

from browser_use.agent.message_manager.service import MessageManager
from browser_use.dom.views import (
	DOMRect,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
	SerializedDOMState,
	SimplifiedNode,
)
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import SystemMessage


def _anchor_state() -> SerializedDOMState:
	"""Minimal serialized state holding one interactive <a> with id/title attributes."""
	node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='A',
		node_value='',
		attributes={'id': 'submit-btn', 'title': 'Checkout', 'href': '/checkout'},
		is_scrollable=False,
		is_visible=True,
		absolute_position=DOMRect(x=0, y=0, width=100, height=30),
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=EnhancedSnapshotNode(
			is_clickable=None,
			cursor_style='pointer',
			bounds=DOMRect(x=0, y=0, width=100, height=30),
			clientRects=None,
			scrollRects=None,
			computed_styles={'display': 'block', 'visibility': 'visible', 'opacity': '1'},
			paint_order=None,
			stacking_contexts=None,
		),
	)
	simplified = SimplifiedNode(original_node=node, children=[], is_interactive=True, selector_index=1)
	return SerializedDOMState(_root=simplified, selector_map={1: node})


class TestLlvmRepresentationIncludeAttributes:
	def test_empty_list_emits_no_attributes(self):
		"""include_attributes=[] means "no attributes", not "use the defaults"."""
		output = _anchor_state().llm_representation([])

		assert '[1]<a' in output, output
		assert 'id=' not in output, f'id attribute leaked despite include_attributes=[]: {output}'
		assert 'title=' not in output, f'title attribute leaked despite include_attributes=[]: {output}'

	def test_none_still_uses_defaults(self):
		"""Unset (None) keeps showing the default attribute list."""
		output = _anchor_state().llm_representation(None)

		assert 'id=submit-btn' in output, output

	def test_explicit_subset_is_honored(self):
		output = _anchor_state().llm_representation(['id'])

		assert 'id=submit-btn' in output, output
		assert 'title=' not in output, output


class TestMessageManagerKeepsNoneAndEmptyListDistinct:
	def test_none_stays_none_and_empty_list_stays_empty(self, tmp_path: Path):
		"""MessageManager must forward None unchanged so the serializer can default it."""
		file_system = FileSystem(tmp_path)
		system_message = SystemMessage(content='system')

		unset = MessageManager(task='t', system_message=system_message, file_system=file_system, include_attributes=None)
		assert unset.include_attributes is None

		disabled = MessageManager(task='t', system_message=system_message, file_system=file_system, include_attributes=[])
		assert disabled.include_attributes == []
