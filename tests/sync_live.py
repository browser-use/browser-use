# """
# Live integration test for OAuth2 device flow with real cloud backend.

# This test is skipped by default and only runs when explicitly selected.
# Run with: pytest tests/ci/test_live_oauth2_integration.py::test_live_oauth2_integration -v
# """

# import asyncio
# import json
# import logging
# import os
# import tempfile
# from pathlib import Path

# import pytest

# from browser_use import Agent
# from browser_use.browser.browser import BrowserSession
# from browser_use.sync.service import CloudSync
# from tests.ci.mocks import create_mock_llm

# logger = logging.getLogger(__name__)


# def create_oauth_mock_llm():
# 	"""Create a mock LLM that follows a simple script for OAuth testing."""
# 	actions = [
# 		# First action - navigate to a simple page
# 		json.dumps(
# 			{
# 				'current_state': {
# 					'evaluation_previous_goal': 'Starting OAuth integration test',
# 					'memory': 'Beginning test sequence',
# 					'next_goal': 'Navigate to example page',
# 				},
# 				'action': [
# 					{'goto': {'url': 'https://example.com', 'reasoning': 'Starting the test by navigating to a simple webpage'}}
# 				],
# 			}
# 		),
# 		# Second action - complete the test
# 		json.dumps(
# 			{
# 				'current_state': {
# 					'evaluation_previous_goal': 'Successfully navigated to example page',
# 					'memory': 'OAuth flow test initiated',
# 					'next_goal': 'Complete test',
# 				},
# 				'action': [{'done': {'text': 'OAuth integration test completed - cloud sync initiated', 'success': True}}],
# 			}
# 		),
# 	]
# 	return create_mock_llm(actions)


# @pytest.fixture
# def temp_browser_profile():
# 	"""Create a temporary browser profile directory."""
# 	with tempfile.TemporaryDirectory() as tmpdir:
# 		profile_dir = Path(tmpdir) / 'browser_profile'
# 		profile_dir.mkdir(parents=True, exist_ok=True)
# 		yield str(profile_dir)


# @pytest.mark.skipif(not os.getenv('RUN_LIVE_TESTS'), reason='Live integration tests only run when RUN_LIVE_TESTS=1 is set')
# @pytest.mark.asyncio
# async def test_live_oauth2_integration(temp_browser_profile):
# 	"""
# 	Live integration test for OAuth2 device flow.

# 	This test:
# 	1. Creates a real browser session
# 	2. Sets up cloud sync with real backend
# 	3. Runs an agent with a mocked LLM
# 	4. Verifies the OAuth2 device flow is initiated
# 	5. Sends real events to the cloud backend

# 	Environment variables required:
# 	- RUN_LIVE_TESTS=1 (to enable the test)
# 	- BROWSER_USE_CLOUD_URL (optional, defaults to https://cloud.browser-use.com)
# 	"""

# 	# Configuration
# 	backend_url = os.getenv('BROWSER_USE_CLOUD_URL', 'http://localhost:8000')
# 	logger.info(f'Running live integration test against: {backend_url}')

# 	# Create mock LLM
# 	mock_llm = create_oauth_mock_llm()

# 	# Set environment variables for cloud sync
# 	os.environ['BROWSERUSE_CLOUD_SYNC'] = 'true'
# 	os.environ['BROWSER_USE_CLOUD_URL'] = backend_url

# 	# Create browser session with real profile
# 	browser_session = BrowserSession(
# 		user_data_dir=temp_browser_profile,
# 		headless=False,  # Show browser for visual confirmation
# 	)

# 	# Create agent (cloud sync will be auto-enabled via environment variables)
# 	agent = Agent(
# 		task='Visit the Browser Use login page and demonstrate OAuth integration',
# 		llm=mock_llm,
# 		browser_session=browser_session,
# 	)

# 	# Run the agent for a short time
# 	logger.info('Starting agent with OAuth2 integration...')

# 	# Run with timeout to prevent hanging
# 	try:
# 		await asyncio.wait_for(agent.run(), timeout=60)
# 	except TimeoutError:
# 		logger.info('Agent run timed out (expected for live test)')

# 	# Get cloud sync from agent
# 	cloud_sync = agent.cloud_sync
# 	assert cloud_sync is not None, 'Cloud sync should be enabled'

# 	# Wait for any pending cloud sync operations
# 	if cloud_sync.auth_task and not cloud_sync.auth_task.done():
# 		try:
# 			await asyncio.wait_for(cloud_sync.auth_task, timeout=10)
# 		except TimeoutError:
# 			logger.info('Auth task still running (expected for live test)')

# 	# Verify cloud sync was attempted
# 	assert cloud_sync.auth_client is not None, 'Auth client should be initialized'

# 	logger.info('✅ Live OAuth2 integration test completed successfully')
# 	logger.info(f'🔗 LLM invocations: {mock_llm.invoke.call_count if hasattr(mock_llm.invoke, "call_count") else "mock"}')

# 	# Print session ID for manual verification
# 	if cloud_sync.session_id:
# 		logger.info(f'📊 Agent session ID: {cloud_sync.session_id}')
# 		logger.info(f'🌐 Check session at: {backend_url}/agent/{cloud_sync.session_id}')

# 	await asyncio.sleep(60000)


# @pytest.mark.skipif(not os.getenv('RUN_LIVE_TESTS'), reason='Live integration tests only run when RUN_LIVE_TESTS=1 is set')
# @pytest.mark.asyncio
# async def test_live_cloud_sync_events():
# 	"""
# 	Test that cloud sync can send events to the real backend.

# 	This is a simpler test that just verifies event sending works.
# 	"""

# 	backend_url = os.getenv('BROWSER_USE_CLOUD_URL', 'http://localhost:8000')
# 	logger.info(f'Testing cloud sync against: {backend_url}')

# 	# Create cloud sync service
# 	cloud_sync = CloudSync(base_url=backend_url, enable_auth=True)

# 	# Import event types
# 	from uuid import uuid4

# 	from browser_use.agent.cloud_events import CreateAgentSessionEvent
# 	from browser_use.sync.auth import TEMP_USER_ID

# 	# Create a test session event
# 	session_event = CreateAgentSessionEvent(
# 		user_id=TEMP_USER_ID,
# 		id=str(uuid4()),
# 		browser_session_id=str(uuid4()),
# 		browser_session_live_url='https://example.com',
# 		browser_session_cdp_url='ws://localhost:9222',
# 		browser_state={'test': 'live_integration'},
# 		is_source_api=True,
# 	)

# 	# Send event to cloud
# 	logger.info('Sending test event to cloud...')
# 	try:
# 		await cloud_sync.handle_event(session_event)
# 		logger.info('✅ Event sent successfully')
# 	except Exception as e:
# 		logger.error(f'❌ Failed to send event: {e}')
# 		raise

# 	# Wait a moment for processing
# 	await asyncio.sleep(2)

# 	logger.info('✅ Cloud sync event test completed')

# 	if cloud_sync.session_id:
# 		logger.info(f'📊 Session ID: {cloud_sync.session_id}')

# 	await asyncio.sleep(60000)


# if __name__ == '__main__':
# 	# Allow running the test directly with: python test_live_oauth2_integration.py
# 	import sys

# 	if len(sys.argv) > 1 and sys.argv[1] == '--live':
# 		os.environ['RUN_LIVE_TESTS'] = '1'
# 		pytest.main([__file__, '-v', '-s'])
# 	else:
# 		print('To run live integration tests:')
# 		print('1. Set environment variable: export RUN_LIVE_TESTS=1')
# 		print('2. Run: pytest tests/ci/test_live_oauth2_integration.py -v')
# 		print('3. Or run directly: python test_live_oauth2_integration.py --live')
