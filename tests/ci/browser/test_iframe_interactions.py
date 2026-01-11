"""Unit tests for iframe interaction fixes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.dom.service import DomService
from browser_use.dom.views import EnhancedDOMTreeNode


@pytest.mark.asyncio
async def test_get_ax_tree_for_all_frames_handles_timeout():
	# Mock BrowserSession and CDPClient
	mock_browser_session = AsyncMock()
	mock_cdp_session = AsyncMock()
	mock_browser_session.get_or_create_cdp_session.return_value = mock_cdp_session
	mock_cdp_session.session_id = 'session-123'

	# Mock frame tree
	mock_cdp_session.cdp_client.send.Page.getFrameTree.return_value = {
		'frameTree': {'frame': {'id': 'frame-1'}, 'childFrames': [{'frame': {'id': 'frame-2'}}]}
	}

	# Mock getFullAXTree to hang for frame-2
	async def side_effect_ax_tree(params, session_id):
		if params['frameId'] == 'frame-2':
			# Simulate hang (wait longer than timeout)
			import asyncio

			await asyncio.sleep(2.0)
			return {'nodes': []}
		return {'nodes': [{'nodeId': '1'}]}

	mock_cdp_session.cdp_client.send.Accessibility.getFullAXTree.side_effect = side_effect_ax_tree

	service = DomService(mock_browser_session)

	# Run the method - it should not hang indefinitely
	# The timeout in code is 1.0s, so it should finish quickly
	result = await service._get_ax_tree_for_all_frames('target-1')

	assert result is not None
	# process only frame-1, frame-2 should fail/timeout
	# We expect nodes from frame-1 only
	assert len(result['nodes']) == 1
	assert result['nodes'][0]['nodeId'] == '1'


@pytest.mark.asyncio
async def test_scroll_parent_iframes_into_view():
	mock_browser_session = AsyncMock()

	# Use model_construct to bypass Pydantic validation for mocks
	# Supply event_bus as it is a required field
	watchdog = DefaultActionWatchdog.model_construct(browser_session=mock_browser_session, event_bus=MagicMock())
	# logger is a property, do not try to set it.

	# Element inside Iframe2
	element_node = MagicMock(spec=EnhancedDOMTreeNode)
	element_node.parent = MagicMock(spec=EnhancedDOMTreeNode)

	# Iframe2 element (in Iframe1 doc)
	iframe2_node = element_node.parent
	iframe2_node.tag_name = 'IFRAME'
	iframe2_node.backend_node_id = 102
	iframe2_node.parent = MagicMock(spec=EnhancedDOMTreeNode)

	# Iframe1 element (in Main doc)
	iframe1_node = iframe2_node.parent
	iframe1_node.tag_name = 'IFRAME'
	iframe1_node.backend_node_id = 101
	iframe1_node.parent = MagicMock(spec=EnhancedDOMTreeNode)

	# Main document root (not iframe)
	root_node = iframe1_node.parent
	root_node.tag_name = 'HTML'
	root_node.parent = None

	# Mock cdp_client_for_node to return different sessions
	session1 = AsyncMock()
	session1.session_id = 'session-1'
	session2 = AsyncMock()
	session2.session_id = 'session-2'

	async def side_effect_cdp_client(node):
		if node == iframe1_node:
			return session1  # Main session
		if node == iframe2_node:
			return session2  # Iframe1 session
		return session1

	mock_browser_session.cdp_client_for_node.side_effect = side_effect_cdp_client

	# Execute
	await watchdog._scroll_parent_iframes_into_view(element_node)

	# Verify calls
	# Should scroll Iframe2 first (closest parent iframe)
	# Then Iframe1

	# Check Iframe2 scroll (using session2 - Iframe1 session)
	# Wait, loop order:
	# current = element.parent (iframe2_node) -> IS IFRAME -> scroll it
	# current = iframe2_node.parent (iframe1_node) -> IS IFRAME -> scroll it

	# Verify scrollIntoViewIfNeeded called for iframe2_node
	# args: params={'backendNodeId': 102}, session_id='session-2'
	# Actually my mock logic for session might be simplified, but let's check call args

	assert session2.cdp_client.send.DOM.scrollIntoViewIfNeeded.called
	call_args2 = session2.cdp_client.send.DOM.scrollIntoViewIfNeeded.call_args.kwargs
	assert call_args2['params']['backendNodeId'] == 102

	# Verify scrollIntoViewIfNeeded called for iframe1_node
	# args: params={'backendNodeId': 101}, session_id='session-1'
	assert session1.cdp_client.send.DOM.scrollIntoViewIfNeeded.called
	call_args1 = session1.cdp_client.send.DOM.scrollIntoViewIfNeeded.call_args.kwargs
	assert call_args1['params']['backendNodeId'] == 101
