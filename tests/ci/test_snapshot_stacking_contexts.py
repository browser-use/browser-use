"""Regression test: CDP `stackingContexts` is RareBooleanData, not positional data.

`build_snapshot_lookup` indexed `layout['stackingContexts']['index']` with the layout index, so the set of
indices was read as a per-node value: nodes before the first stacking context reported an unrelated integer
and the real stacking-context nodes reported `None`.
"""

from typing import Any

from browser_use.dom.enhanced_snapshot import build_snapshot_lookup


def _snapshot(*, include_stacking_contexts: bool = True) -> Any:
	bounds = [[0, 0, 100, 100], [0, 0, 100, 100], [0, 0, 100, 100]]
	layout: dict[str, Any] = {
		# Deliberately not [0, 1, 2]: layout index and snapshot/node index have to disagree, otherwise a
		# lookup that reads `nodeIndex` instead of the layout index would still produce the right answer.
		# layout_idx 0 -> node 2, layout_idx 1 -> node 0, layout_idx 2 -> node 1
		'nodeIndex': [2, 0, 1],
		'bounds': bounds,
		'paintOrders': [1, 2, 3],
		'styles': [[0], [0], [0]],
	}
	if include_stacking_contexts:
		# Only layout index 2 creates a stacking context, which is backend node 102 - not 103.
		layout['stackingContexts'] = {'index': [2]}

	return {
		'documents': [
			{
				'nodes': {
					'backendNodeId': [101, 102, 103],
				},
				'layout': layout,
			}
		],
		'strings': ['display', 'block'],
	}


def test_only_listed_layout_indices_are_stacking_contexts() -> None:
	lookup = build_snapshot_lookup(_snapshot(), device_pixel_ratio=1.0)

	assert lookup[101].stacking_contexts is False
	assert lookup[102].stacking_contexts is True
	assert lookup[103].stacking_contexts is False


def test_missing_stacking_contexts_stays_unknown() -> None:
	"""CDP omits `stackingContexts` when no node creates one; that is unknown, not `False`."""
	lookup = build_snapshot_lookup(_snapshot(include_stacking_contexts=False), device_pixel_ratio=1.0)

	assert lookup[101].stacking_contexts is None
	assert lookup[102].stacking_contexts is None
	assert lookup[103].stacking_contexts is None


def test_bounds_are_scaled_by_device_pixel_ratio() -> None:
	lookup = build_snapshot_lookup(_snapshot(), device_pixel_ratio=2.0)

	assert lookup[101].bounds is not None
	assert lookup[101].bounds.width == 50
	assert lookup[101].bounds.height == 50
