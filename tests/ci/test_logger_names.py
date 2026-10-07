import logging
import logging.handlers
import os
import queue
import subprocess
import sys

from browser_use import Agent
from browser_use.browser import BrowserSession
from tests.ci.conftest import create_mock_llm


def test_sessions_and_agents_do_not_create_a_logger_per_instance():
	for i in range(20):
		session = BrowserSession(cdp_url=f'ws://127.0.0.1:{31000 + i}/devtools/browser/x')
		agent = Agent(
			task='Inspect logger name.',
			llm=create_mock_llm(),
			browser_session=session,
			task_id=f'task-{i:04d}',
			directly_open_url=False,
		)
		assert session.logger.name == 'browser_use.BrowserSession'
		assert agent.logger.name == 'browser_use.Agent'

	assert [name for name in logging.Logger.manager.loggerDict if '🅑' in name or '🅰' in name] == []


def test_session_and_agent_records_carry_the_instance(caplog):
	session = BrowserSession(cdp_url='ws://127.0.0.1:31500/devtools/browser/x')
	agent = Agent(
		task='Inspect logger name.',
		llm=create_mock_llm(),
		browser_session=session,
		task_id='task-1234',
		directly_open_url=False,
	)

	# capture copies on the component loggers: their handlers run before the browser_use console handler,
	# whose formatter rewrites record.name in place
	caplog.set_level(logging.DEBUG, logger='browser_use.BrowserSession')
	caplog.set_level(logging.DEBUG, logger='browser_use.Agent')
	captured: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
	handler = logging.handlers.QueueHandler(captured)
	component_loggers = [logging.getLogger('browser_use.BrowserSession'), logging.getLogger('browser_use.Agent')]
	for component_logger in component_loggers:
		component_logger.addHandler(handler)
	try:
		session.logger.warning('session message')
		agent.logger.warning('agent message')
	finally:
		for component_logger in component_loggers:
			component_logger.removeHandler(handler)

	records = [captured.get_nowait() for _ in range(captured.qsize())]
	assert [(record.name, record.getMessage()) for record in records] == [
		('browser_use.BrowserSession', 'session message'),
		('browser_use.Agent', 'agent message'),
	]
	session_record, agent_record = records
	assert session_record.__dict__['browser_use_instance'] == str(session).removeprefix('BrowserSession')
	assert agent_record.__dict__['browser_use_instance'] == f'🅰 1234 ⇢ 🅑 {session.id[-4:]} 🅣 --'
	assert agent_record.funcName == 'test_session_and_agent_records_carry_the_instance'


def test_debug_console_output_still_shows_the_instance():
	child = (
		'import logging.handlers\n'
		'from browser_use.browser import BrowserSession\n'
		'later_handler = logging.handlers.BufferingHandler(capacity=100)\n'
		"logging.getLogger('browser_use').addHandler(later_handler)\n"
		"session = BrowserSession(cdp_url='ws://127.0.0.1:31600/devtools/browser/x')\n"
		"session.logger.debug('session message')\n"
		'print(session)\n'
		'print(later_handler.buffer[-1].name)\n'
	)
	env = {
		**os.environ,
		'BROWSER_USE_SETUP_LOGGING': 'true',
		'BROWSER_USE_LOGGING_LEVEL': 'debug',
		'ANONYMIZED_TELEMETRY': 'false',
	}
	result = subprocess.run([sys.executable, '-c', child], env=env, capture_output=True, text=True, timeout=120, check=True)

	session_str, later_record_name = result.stdout.splitlines()
	assert f'[browser_use.{session_str}] session message' in result.stderr
	assert later_record_name == 'browser_use.BrowserSession'
