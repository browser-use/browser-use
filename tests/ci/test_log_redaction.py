"""Test log redaction functionality"""

import asyncio
import logging

import pytest

from browser_use import Agent, Browser
from browser_use.logging_config import LogRedactionFilter


class TestLogRedactionFilter:
	"""Test the LogRedactionFilter class"""

	def test_redact_task(self):
		"""Test that task content is redacted"""
		task = 'Go to https://example.com and search for my secret password'
		filter_obj = LogRedactionFilter(task=task)

		text = f'Agent task: {task}'
		redacted = filter_obj._redact_string(text)

		assert '[REDACTED_TASK]' in redacted
		assert task not in redacted

	def test_redact_urls(self):
		"""Test that URLs are redacted"""
		filter_obj = LogRedactionFilter()

		text = 'Testing URL: https://example.com/sensitive-path and http://test.com'
		redacted = filter_obj._redact_string(text)

		assert 'https://example.com' not in redacted
		assert 'http://test.com' not in redacted
		assert '[REDACTED_URL]' in redacted

	def test_redact_cdp_url(self):
		"""Test that CDP URL is redacted"""
		cdp_url = 'http://localhost:9222'
		filter_obj = LogRedactionFilter(cdp_url=cdp_url)

		text = f'Connecting to {cdp_url}/devtools/browser'
		redacted = filter_obj._redact_string(text)

		assert cdp_url not in redacted
		assert '[REDACTED_CDP_URL]' in redacted

	def test_redact_json_text_fields(self):
		"""Test that JSON text fields are redacted"""
		filter_obj = LogRedactionFilter()

		text = '{"text": "sensitive data", "query": "secret query", "content": "private content"}'
		redacted = filter_obj._redact_string(text)

		assert 'sensitive data' not in redacted
		assert 'secret query' not in redacted
		assert 'private content' not in redacted
		assert '[REDACTED]' in redacted

	def test_redact_json_value_fields(self):
		"""Test that JSON value fields are redacted"""
		filter_obj = LogRedactionFilter()

		text = '{"value": "my password"}'
		redacted = filter_obj._redact_string(text)

		assert 'my password' not in redacted
		assert '[REDACTED]' in redacted

	def test_filter_applies_to_log_record(self):
		"""Test that filter applies redaction to log records"""
		task = 'My secret task'
		filter_obj = LogRedactionFilter(task=task)

		# Create a mock log record
		record = logging.LogRecord(
			name='test',
			level=logging.INFO,
			pathname='',
			lineno=0,
			msg=f'Processing task: {task}',
			args=(),
			exc_info=None,
		)

		# Apply filter
		result = filter_obj.filter(record)

		assert result is True  # Filter should return True
		assert '[REDACTED_TASK]' in record.msg
		assert task not in record.msg


class TestAgentLogRedaction:
	"""Test Agent integration with log redaction"""

	async def test_agent_with_redact_logs_enabled(self, mock_llm):
		"""Test that agent applies redaction filter when redact_logs=True"""
		task = 'Go to https://example.com'

		agent = Agent(
			task=task,
			llm=mock_llm,
			browser=Browser(headless=True, keep_alive=False),
			redact_logs=True,
		)

		# Check that redaction filter is stored
		assert agent.redact_logs is True
		assert agent._redaction_filter is not None
		assert isinstance(agent._redaction_filter, LogRedactionFilter)

		# Check that logger has the filter applied
		logger = agent.logger
		assert any(isinstance(f, LogRedactionFilter) for f in logger.filters)

		await agent.close()

	async def test_agent_without_redact_logs(self, mock_llm):
		"""Test that agent doesn't apply redaction filter when redact_logs=False"""
		task = 'Go to https://example.com'

		agent = Agent(
			task=task,
			llm=mock_llm,
			browser=Browser(headless=True, keep_alive=False),
			redact_logs=False,
		)

		# Check that redaction filter is not stored
		assert agent.redact_logs is False
		assert agent._redaction_filter is None

		# Check that logger doesn't have the filter applied
		logger = agent.logger
		assert not any(isinstance(f, LogRedactionFilter) for f in logger.filters)

		await agent.close()

	async def test_agent_default_redact_logs_false(self, mock_llm):
		"""Test that redact_logs defaults to False"""
		agent = Agent(
			task='test task',
			llm=mock_llm,
			browser=Browser(headless=True, keep_alive=False),
		)

		assert agent.redact_logs is False

		await agent.close()
