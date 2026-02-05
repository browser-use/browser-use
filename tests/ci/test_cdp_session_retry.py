"""Unit tests for CDP session retry logic.

Tests the _send_cdp_with_retry method that handles CDP session detachment
during tab switches and other operations.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.browser.session import BrowserSession, CDPSession


class TestCDPSessionRetry:
	"""Test CDP session retry logic for handling session detachment."""

	@pytest.mark.asyncio
	async def test_successful_command_first_attempt(self):
		"""Test that successful commands work on first attempt without retry."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Bind the method to the mock instance
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Mock successful command
		async def successful_command(s):
			return {'success': True}
		
		# Execute
		result = await retry_method(cdp_session, successful_command)
		
		# Verify
		assert result == {'success': True}
		assert session.logger.debug.call_count == 0  # No retry logs

	@pytest.mark.asyncio
	async def test_retry_on_session_detachment(self):
		"""Test retry logic when CDP session is detached."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Mock get_or_create_cdp_session for refresh
		new_cdp_session = MagicMock(spec=CDPSession)
		new_cdp_session.target_id = 'test-target-id-12345678'
		
		async def mock_get_session(target_id, focus):
			return new_cdp_session
		
		session.get_or_create_cdp_session = mock_get_session
		
		# Bind the method
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Mock command that fails first time, succeeds second time
		call_count = 0
		
		async def flaky_command(s):
			nonlocal call_count
			call_count += 1
			if call_count == 1:
				raise Exception("{'code': -32001, 'message': 'Session with given id not found.'}")
			return {'success': True}
		
		# Execute
		result = await retry_method(cdp_session, flaky_command, max_retries=3)
		
		# Verify
		assert result == {'success': True}
		assert call_count == 2  # Failed once, succeeded on retry
		assert session.logger.debug.call_count >= 2  # Retry log + refresh log

	@pytest.mark.asyncio
	async def test_all_retries_exhausted(self):
		"""Test that RuntimeError is raised when all retries fail."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Mock get_or_create_cdp_session for refresh
		new_cdp_session = MagicMock(spec=CDPSession)
		new_cdp_session.target_id = 'test-target-id-12345678'
		
		async def mock_get_session(target_id, focus):
			return new_cdp_session
		
		session.get_or_create_cdp_session = mock_get_session
		
		# Bind the method
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Mock command that always fails
		async def always_fails(s):
			raise Exception("{'code': -32001, 'message': 'Session with given id not found.'}")
		
		# Execute and verify exception
		with pytest.raises(RuntimeError, match='all 3 retries failed'):
			await retry_method(cdp_session, always_fails, max_retries=3)

	@pytest.mark.asyncio
	async def test_non_session_error_propagates_immediately(self):
		"""Test that non-session errors propagate without retry."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Bind the method
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Mock command that fails with different error
		async def different_error(s):
			raise ValueError('Some other error')
		
		# Execute and verify exception propagates immediately
		with pytest.raises(ValueError, match='Some other error'):
			await retry_method(cdp_session, different_error)
		
		# Verify no retry logs
		assert session.logger.debug.call_count == 0

	@pytest.mark.asyncio
	async def test_exponential_backoff_timing(self):
		"""Test that exponential backoff timing is correct."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Mock get_or_create_cdp_session for refresh
		new_cdp_session = MagicMock(spec=CDPSession)
		new_cdp_session.target_id = 'test-target-id-12345678'
		
		async def mock_get_session(target_id, focus):
			return new_cdp_session
		
		session.get_or_create_cdp_session = mock_get_session
		
		# Bind the method
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Track sleep times
		sleep_times = []
		original_sleep = asyncio.sleep
		
		async def mock_sleep(duration):
			sleep_times.append(duration)
			await original_sleep(0)  # Don't actually sleep in test
		
		# Patch asyncio.sleep
		# Note: We use the global asyncio module which is already imported
		asyncio.sleep = mock_sleep
		
		try:
			# Mock command that fails 3 times, succeeds 4th time
			call_count = 0
			
			async def flaky_command(s):
				nonlocal call_count
				call_count += 1
				if call_count < 4:
					raise Exception("{'code': -32001, 'message': 'Session with given id not found.'}")
				return {'success': True}
			
			# Execute
			await retry_method(cdp_session, flaky_command, max_retries=4)
			
			# Verify exponential backoff: 0.1, 0.2, 0.4
			assert len(sleep_times) == 3
			assert sleep_times[0] == 0.1  # 0.1 * 2^0
			assert sleep_times[1] == 0.2  # 0.1 * 2^1
			assert sleep_times[2] == 0.4  # 0.1 * 2^2
		
		finally:
			# Restore original sleep
			asyncio.sleep = original_sleep

	@pytest.mark.asyncio
	async def test_target_no_longer_exists_after_detachment(self):
		"""Test error handling when target is removed after detachment."""
		# Create minimal browser session mock
		session = MagicMock(spec=BrowserSession)
		session.logger = MagicMock()
		
		# Mock get_or_create_cdp_session that raises ValueError (target gone)
		async def mock_get_session(target_id, focus):
			raise ValueError('Target test-target-id-12345678 not found - may have detached or never existed')
		
		session.get_or_create_cdp_session = mock_get_session
		
		# Bind the method
		retry_method = BrowserSession._send_cdp_with_retry.__get__(session, BrowserSession)
		
		# Create mock CDP session
		cdp_session = MagicMock(spec=CDPSession)
		cdp_session.target_id = 'test-target-id-12345678'
		
		# Mock command that fails with session error
		async def fails_command(s):
			raise Exception("{'code': -32001, 'message': 'Session with given id not found.'}")
		
		# Execute and verify error message
		with pytest.raises(RuntimeError, match='target no longer exists'):
			await retry_method(cdp_session, fails_command)
