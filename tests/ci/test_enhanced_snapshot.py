from browser_use.dom.enhanced_snapshot import build_snapshot_lookup


def test_build_snapshot_lookup_dpi_scaling_and_stacking_contexts():
	"""Verify that clientRects and scrollRects are properly scaled by device_pixel_ratio,
	and that stackingContexts rare boolean data uses set membership instead of positional indexing."""
	device_pixel_ratio = 2.0

	snapshot = {
		'documents': [
			{
				'nodes': {
					'backendNodeId': [101, 102],
				},
				'layout': {
					'nodeIndex': [0, 1],  # layout_idx 0 -> snapshot node 0; layout_idx 1 -> snapshot node 1
					'bounds': [
						[200.0, 400.0, 600.0, 800.0],
						[100.0, 120.0, 140.0, 160.0],
					],
					'clientRects': [
						[200.0, 400.0, 600.0, 800.0],
						[100.0, 120.0, 140.0, 160.0],
					],
					'scrollRects': [
						[10.0, 20.0, 1000.0, 2000.0],
						[30.0, 40.0, 500.0, 600.0],
					],
					# In CDP, stackingContexts.index lists layout indices that have stacking contexts.
					# Here only layout_idx 1 has a stacking context.
					'stackingContexts': {
						'index': [1],
					},
					'styles': [],
				},
			}
		],
		'strings': [],
	}

	from typing import cast

	from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns

	lookup = build_snapshot_lookup(cast(CaptureSnapshotReturns, snapshot), device_pixel_ratio=device_pixel_ratio)

	# Node 101 (layout_idx 0)
	node_101 = lookup[101]
	assert node_101.bounds is not None
	assert node_101.bounds.x == 100.0
	assert node_101.bounds.y == 200.0
	assert node_101.bounds.width == 300.0
	assert node_101.bounds.height == 400.0

	# clientRects and scrollRects must be scaled by device_pixel_ratio
	assert node_101.clientRects is not None
	assert node_101.clientRects.x == 100.0
	assert node_101.clientRects.y == 200.0
	assert node_101.clientRects.width == 300.0
	assert node_101.clientRects.height == 400.0

	assert node_101.scrollRects is not None
	assert node_101.scrollRects.x == 5.0
	assert node_101.scrollRects.y == 10.0
	assert node_101.scrollRects.width == 500.0
	assert node_101.scrollRects.height == 1000.0

	# Stacking context: layout_idx 0 is NOT in stackingContexts.index
	assert node_101.stacking_contexts is False

	# Node 102 (layout_idx 1)
	node_102 = lookup[102]
	assert node_102.bounds is not None
	assert node_102.bounds.x == 50.0
	assert node_102.bounds.y == 60.0
	assert node_102.bounds.width == 70.0
	assert node_102.bounds.height == 80.0

	assert node_102.clientRects is not None
	assert node_102.clientRects.x == 50.0
	assert node_102.clientRects.y == 60.0
	assert node_102.clientRects.width == 70.0
	assert node_102.clientRects.height == 80.0

	assert node_102.scrollRects is not None
	assert node_102.scrollRects.x == 15.0
	assert node_102.scrollRects.y == 20.0
	assert node_102.scrollRects.width == 250.0
	assert node_102.scrollRects.height == 300.0

	# Stacking context: layout_idx 1 IS in stackingContexts.index
	assert node_102.stacking_contexts is True
