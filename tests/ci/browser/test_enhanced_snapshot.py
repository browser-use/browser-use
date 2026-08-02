"""Pure-function unit tests for build_snapshot_lookup coordinate scaling (no browser).

build_snapshot_lookup() takes a raw CDP DOMSnapshot dict and returns enhanced
nodes, so a synthetic snapshot lets us assert the device-pixel-ratio coordinate
math directly without launching a browser.
"""

from browser_use.dom.enhanced_snapshot import build_snapshot_lookup


def _single_node_snapshot() -> dict:
	"""One backend node (id=1) with bounds/clientRects/scrollRects in device pixels."""
	return {
		'documents': [
			{
				'nodes': {'backendNodeId': [1]},
				'layout': {
					'nodeIndex': [0],
					'bounds': [[100, 200, 50, 60]],
					'clientRects': [[100, 200, 50, 60]],
					'scrollRects': [[0, 0, 50, 300]],
				},
			}
		],
		'strings': [],
	}


def test_all_rects_scaled_to_css_pixels_at_dpr_2():
	"""bounds, clientRects and scrollRects must all be divided by the DPR uniformly."""
	lookup = build_snapshot_lookup(_single_node_snapshot(), device_pixel_ratio=2.0)
	node = lookup[1]
	assert node.bounds.x == 50.0
	assert node.bounds.height == 30.0
	assert node.clientRects.x == 50.0
	assert node.clientRects.width == 25.0
	assert node.scrollRects.height == 150.0
	assert node.scrollRects.width == 25.0


def test_dpr_1_is_identity():
	"""At DPR=1 (Linux/CI default) all coordinates are unchanged."""
	lookup = build_snapshot_lookup(_single_node_snapshot(), device_pixel_ratio=1.0)
	node = lookup[1]
	assert node.bounds.x == 100.0
	assert node.clientRects.x == 100.0
	assert node.scrollRects.height == 300.0
