import asyncio
import logging
from unittest.mock import Mock

import pytest

from browser_use.utils import create_task_with_error_handling


class ExpectedTaskError(RuntimeError):
	"""Exception used to verify task propagation."""


@pytest.mark.parametrize('suppress_exceptions', [False, True])
async def test_task_exception_is_not_reported_as_callback_failure(suppress_exceptions: bool) -> None:
	loop = asyncio.get_running_loop()
	previous_exception_handler = loop.get_exception_handler()
	exception_contexts: list[dict] = []
	test_logger = Mock(spec=logging.Logger)

	def capture_loop_exception(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
		exception_contexts.append(context)

	async def fail() -> None:
		raise ExpectedTaskError('expected failure')

	loop.set_exception_handler(capture_loop_exception)
	try:
		task = create_task_with_error_handling(
			fail(),
			name='expected-failure',
			logger_instance=test_logger,
			suppress_exceptions=suppress_exceptions,
		)

		with pytest.raises(ExpectedTaskError, match='expected failure'):
			await task

		# Let all callbacks queued by task completion run.
		await asyncio.sleep(0)
	finally:
		loop.set_exception_handler(previous_exception_handler)

	assert exception_contexts == []
	if suppress_exceptions:
		test_logger.error.assert_called_once()
		test_logger.warning.assert_not_called()
	else:
		test_logger.warning.assert_called_once()
		test_logger.error.assert_not_called()
