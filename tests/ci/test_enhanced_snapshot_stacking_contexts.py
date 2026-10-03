"""Regression test for stackingContexts decoding in build_snapshot_lookup().

CDP types `LayoutTreeSnapshot.stackingContexts` as RareBooleanData: `index` holds
the layout indices that begin a stacking context, and membership in that list is
the value. Reading it positionally (`index[layout_idx]`) hands back a different
node's layout index instead of this node's flag, so the first few nodes get a
truthy int they never earned and every real stacking context past the list length
silently reads as None.
"""

from typing import cast

from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns
from cdp_use.cdp.domsnapshot.types import DocumentSnapshot, LayoutTreeSnapshot, NodeTreeSnapshot

from browser_use.dom.enhanced_snapshot import build_snapshot_lookup

BACKEND_NODE_IDS = [100, 101, 102]


def _snapshot(stacking_context_indices: list[int] | None, node_index: list[int] | None = None) -> CaptureSnapshotReturns:
	"""Three laid-out nodes (backend ids 100/101/102 at snapshot indices 0/1/2).

	`node_index` is `LayoutTreeSnapshot.nodeIndex`: entry `i` names the snapshot
	node drawn at layout position `i`. It defaults to identity; pass a permutation
	to drive the two index spaces apart.
	"""
	layout_fields: dict = {
		'nodeIndex': list(node_index) if node_index is not None else [0, 1, 2],
		'styles': [[], [], []],
		'bounds': [[0, 0, 10, 10], [0, 0, 10, 10], [0, 0, 10, 10]],
		'text': [],
	}
	# Chrome always sends stackingContexts, but build_snapshot_lookup reads it
	# defensively, so cover the absent case too.
	if stacking_context_indices is not None:
		layout_fields['stackingContexts'] = {'index': stacking_context_indices}
	layout = cast(LayoutTreeSnapshot, layout_fields)

	document = DocumentSnapshot(
		documentURL=0,
		title=0,
		baseURL=0,
		contentLanguage=0,
		encodingName=0,
		publicId=0,
		systemId=0,
		frameId=0,
		nodes=NodeTreeSnapshot(backendNodeId=list(BACKEND_NODE_IDS)),
		layout=layout,
		textBoxes={'layoutIndex': [], 'bounds': [], 'start': [], 'length': []},
	)
	return CaptureSnapshotReturns(documents=[document], strings=[''])


def _flags(stacking_context_indices: list[int] | None, node_index: list[int] | None = None) -> list[bool | None]:
	lookup = build_snapshot_lookup(_snapshot(stacking_context_indices, node_index))
	return [lookup[backend_node_id].stacking_contexts for backend_node_id in BACKEND_NODE_IDS]


def test_only_listed_layout_indices_are_stacking_contexts():
	"""`index: [2]` means node 2 begins a stacking context and nodes 0/1 do not."""
	assert _flags([2]) == [False, False, True]


def test_empty_index_marks_no_stacking_contexts():
	"""An empty `index` list means no node begins a stacking context."""
	assert _flags([]) == [False, False, False]


def test_every_layout_index_can_be_a_stacking_context():
	"""Nodes past the old positional bound must still be readable."""
	assert _flags([0, 1, 2]) == [True, True, True]


def test_absent_stacking_contexts_stays_none():
	"""Without the field there is no information, which is distinct from False."""
	assert _flags(None) == [None, None, None]


def test_membership_is_read_in_layout_index_space():
	"""`index` holds layout positions, so a non-identity `nodeIndex` must be honoured.

	Layout position 0 draws snapshot node 2 here, so `index: [0]` flags backend id
	102 and nothing else. Every other scenario uses an identity `nodeIndex`, where
	layout position and snapshot index coincide and a decoder reading the wrong one
	still looks correct; this permutation is what separates them. Reading the flag
	as `_parse_rare_boolean_data(stacking_context_set, snapshot_index)` would return
	`[True, False, False]` and fail.
	"""
	assert _flags([0], node_index=[2, 0, 1]) == [False, False, True]

	# The other direction: flag the layout position that draws snapshot node 0.
	assert _flags([1], node_index=[2, 0, 1]) == [True, False, False]
