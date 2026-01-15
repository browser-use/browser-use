from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.dom.service import DomService


@pytest.mark.asyncio
async def test_recursion_limit_for_self_referencing_iframes():
	"""
	Verify that the DOM service correctly handles infinite recursion in iframes
	by respecting the max_iframe_depth limit when pierce=False and manual traversal is used.
	"""
	# Setup mocks
	mock_session = MagicMock()
	mock_session.session_manager.get_target.return_value = MagicMock(
		target_id='child_target', url='http://example.com', title='Child', target_type='iframe'
	)
	mock_session.get_or_create_cdp_session = AsyncMock()
	mock_session.get_or_create_cdp_session.return_value.session_id = 'sess_1'

	service = DomService(MagicMock(), logger=MagicMock())
	service.max_iframe_depth = 2
	service.browser_session = mock_session
	service.cross_origin_iframes = True

	# Mock return values
	mock_trees = MagicMock()
	mock_trees.snapshot = {'dummy': 'snapshot'}

	# Infinite structure simulation
	mock_trees.dom_tree = {
		'root': {
			'nodeId': 1,
			'backendNodeId': 1,
			'nodeName': 'BODY',
			'nodeType': 1,
			'nodeValue': '',
			'attributes': [],
			'childNodeCount': 1,
			'children': [
				{
					'nodeId': 2,
					'backendNodeId': 2,
					'nodeName': 'IFRAME',
					'nodeType': 1,
					'nodeValue': '',
					'attributes': [],
					'frameId': 'frame_1',
					'contentDocument': None,
				}
			],
		}
	}
	mock_trees.ax_tree = {'nodes': []}
	mock_trees.device_pixel_ratio = 1.0
	mock_trees.cdp_timing = {}

	service._get_all_trees = AsyncMock(return_value=mock_trees)
	service._get_viewport_ratio = AsyncMock(return_value=1.0)
	service.browser_session.get_all_frames = AsyncMock(return_value=({'frame_1': {'frameTargetId': 'target_2'}}, {}))

	# Patch internals
	with patch('browser_use.dom.service.build_snapshot_lookup', return_value={}):
		# Test execution
		try:
			result, _ = await service.get_dom_tree(target_id='root', iframe_depth=0)
			assert result is not None
		except RecursionError:
			pytest.fail('RecursionError encountered - infinite loop not prevented!')
