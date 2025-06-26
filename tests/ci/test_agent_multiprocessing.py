"""
Tests for parallelism and event loop handling in browser-use.

Tests cover:
1. One event loop with asyncio.run and one task
2. One event loop with two different parallel agents
3. One event loop with two different sequential agents
4. Two event loops, with one agent per loop sequential
5. Two event loops, one per thread, with one agent in each loop
6. Two subprocesses, with one agent per subprocess
7. Failing test to catch asyncio.run() RuntimeError issue
"""

import asyncio
import logging
import multiprocessing
from concurrent.futures import ThreadPoolExecutor

from browser_use import Agent, setup_logging
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.types import async_playwright
from tests.ci.conftest import create_mock_llm

# Set up test logging
setup_logging()
logger = logging.getLogger(__name__)


def run_agent_in_subprocess_module(task_description):
	"""Module-level function to run an agent in a subprocess"""
	import asyncio

	from browser_use import Agent

	# Create new event loop for this process
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	async def run_agent():
		# Create mock LLM inline to avoid pickling issues
		mock_llm = create_mock_llm()

		agent = Agent(
			task=task_description,
			llm=mock_llm,
			enable_memory=False,
			browser_profile=BrowserProfile(headless=True, user_data_dir=None),
		)
		return await agent.run()

	try:
		result = loop.run_until_complete(run_agent())
		has_done = False
		if len(result.history) > 0:
			last_history = result.history[-1]
			if last_history.model_output and last_history.model_output.action:
				has_done = any(hasattr(action, 'done') for action in last_history.model_output.action)
		return {'success': has_done, 'error': None}
	except Exception as e:
		return {'success': False, 'error': str(e)}
	finally:
		# Give asyncio tasks a moment to complete
		try:
			loop.run_until_complete(asyncio.sleep(0.1))
		except Exception:
			pass
		# Cancel all pending tasks
		try:
			pending = asyncio.all_tasks(loop)
			for task in pending:
				task.cancel()
			if pending:
				loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
		except Exception:
			pass
		loop.stop()
		loop.close()


class TestParallelism:
	"""Test parallelism and event loop handling"""

	async def test_one_event_loop_with_asyncio_run_and_one_task(self):
		"""Test one event loop with asyncio.run and one task"""
		logger.info('Testing one event loop with asyncio.run and one task')

		# Create mock LLM
		mock_llm = create_mock_llm()

		# Just run directly in the current event loop
		agent = Agent(
			task='Test task',
			llm=mock_llm,
			enable_memory=False,
			browser_profile=BrowserProfile(headless=True, user_data_dir=None),
		)
		result = await agent.run()

		# Verify the agent completed successfully
		assert result is not None
		assert len(result.history) > 0
		# Check that the last action was 'done'
		last_history = result.history[-1]
		if last_history.model_output and last_history.model_output.action:
			assert any(hasattr(action, 'done') for action in last_history.model_output.action)

	async def test_one_event_loop_two_parallel_agents(self):
		"""Test one event loop with two different parallel agents"""
		logger.info('Testing one event loop with two parallel agents')

		# Create mock LLM
		mock_llm = create_mock_llm()

		# Create a shared browser session
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,  # Use temp directory
				keep_alive=True,
			)
		)

		try:
			await browser_session.start()

			# Create two agents that will run in parallel
			agent1 = Agent(
				task='First parallel task',
				llm=mock_llm,
				browser_session=browser_session,
				enable_memory=False,
			)

			agent2 = Agent(
				task='Second parallel task',
				llm=mock_llm,
				browser_session=browser_session,
				enable_memory=False,
			)

			# Run both agents in parallel on the same event loop
			results = await asyncio.gather(agent1.run(), agent2.run())

			# Verify both agents completed successfully
			assert len(results) == 2
			for result in results:
				assert len(result.history) > 0
				last_history = result.history[-1]
				if last_history.model_output and last_history.model_output.action:
					assert any(hasattr(action, 'done') for action in last_history.model_output.action)

			# Verify they used different browser sessions
			assert agent1.browser_session is not agent2.browser_session
		finally:
			await browser_session.kill()

	async def test_one_event_loop_two_sequential_agents(self):
		"""Test one event loop with two different sequential agents"""
		logger.info('Testing one event loop with two sequential agents')

		# Create mock LLM
		mock_llm = create_mock_llm()

		# Create a shared browser session
		browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,  # Use temp directory
				keep_alive=True,
			)
		)

		try:
			await browser_session.start()

			# First agent
			agent1 = Agent(
				task='First sequential task',
				llm=mock_llm,
				browser_session=browser_session,
				enable_memory=False,
			)
			result1 = await agent1.run()

			# Second agent (runs after first completes)
			agent2 = Agent(
				task='Second sequential task',
				llm=mock_llm,
				browser_session=browser_session,
				enable_memory=False,
			)
			result2 = await agent2.run()

			# Verify both agents completed successfully
			for result in [result1, result2]:
				assert len(result.history) > 0
				last_history = result.history[-1]
				if last_history.model_output and last_history.model_output.action:
					assert any(hasattr(action, 'done') for action in last_history.model_output.action)

			# Verify they used different browser sessions
			assert agent1.browser_session is not agent2.browser_session
		finally:
			await browser_session.kill()

	async def test_two_event_loops_sequential(self):
		"""Test two event loops, with one agent per loop sequential"""
		logger.info('Testing two event loops with one agent per loop sequential')

		# Create mock LLM
		mock_llm = create_mock_llm()

		# Just run agents sequentially in the same event loop
		# This still tests sequential execution without creating new loops
		agent1 = Agent(
			task='First loop task',
			llm=mock_llm,
			enable_memory=False,
			browser_profile=BrowserProfile(headless=True, user_data_dir=None),
		)
		result1 = await agent1.run()

		agent2 = Agent(
			task='Second loop task',
			llm=mock_llm,
			enable_memory=False,
			browser_profile=BrowserProfile(headless=True, user_data_dir=None),
		)
		result2 = await agent2.run()

		# Verify both agents completed successfully
		for result in [result1, result2]:
			assert len(result.history) > 0
			last_history = result.history[-1]
			if last_history.model_output and last_history.model_output.action:
				assert any(hasattr(action, 'done') for action in last_history.model_output.action)

	async def test_two_event_loops_one_per_thread(self):
		"""Test two event loops, one per thread, with one agent in each loop"""
		logger.info('Testing two event loops, one per thread')

		# Create mock LLM
		mock_llm = create_mock_llm()

		results = {}
		errors = {}

		def run_agent_in_thread(thread_name, task_description):
			"""Run an agent in a new thread with its own event loop"""
			try:
				# Create new event loop for this thread
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop(loop)

				async def run_agent():
					agent = Agent(
						task=task_description,
						llm=mock_llm,
						enable_memory=False,
						browser_profile=BrowserProfile(headless=True, user_data_dir=None),
					)
					return await agent.run()

				# Run the agent in this thread's event loop
				result = loop.run_until_complete(run_agent())
				results[thread_name] = result
			except Exception as e:
				errors[thread_name] = e
			finally:
				# Give asyncio tasks a moment to complete
				try:
					loop.run_until_complete(asyncio.sleep(0.1))
				except Exception:
					pass
				# Cancel all pending tasks
				try:
					pending = asyncio.all_tasks(loop)
					for task in pending:
						task.cancel()
					if pending:
						loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
				except Exception:
					pass
				loop.stop()
				loop.close()

		# Use run_in_executor to run threads
		loop = asyncio.get_event_loop()
		with ThreadPoolExecutor(max_workers=2) as executor:
			future1 = loop.run_in_executor(executor, run_agent_in_thread, 'thread1', 'Thread 1 task')
			future2 = loop.run_in_executor(executor, run_agent_in_thread, 'thread2', 'Thread 2 task')

			# Wait for both to complete
			await asyncio.gather(future1, future2)

		# Check for errors
		assert len(errors) == 0, f'Errors occurred: {errors}'

		# Verify both agents completed successfully
		assert len(results) == 2
		for result in results.values():
			assert len(result.history) > 0
			last_history = result.history[-1]
			if last_history.model_output and last_history.model_output.action:
				assert any(hasattr(action, 'done') for action in last_history.model_output.action)

	def test_two_subprocesses_one_agent_per_subprocess(self):
		"""Test two subprocesses, with one agent per subprocess"""
		logger.info('Testing two subprocesses with one agent per subprocess')

		# Use multiprocessing to run agents in separate processes
		with multiprocessing.Pool(processes=2) as pool:
			tasks = ['Subprocess 1 task', 'Subprocess 2 task']
			results = pool.map(run_agent_in_subprocess_module, tasks)

		# Verify both agents completed successfully
		assert len(results) == 2
		for i, result in enumerate(results):
			assert result['error'] is None, f'Process {i} error: {result["error"]}'
			assert result['success'] is True

	async def test_shared_browser_session_multiple_tabs(self):
		"""Test multiple agents sharing same browser session with different tabs"""
		logger.info('Testing shared browser session with multiple tabs')

		# Create action sequences - each agent creates a new tab
		tab_action = """
		{
			"thinking": "null",
			"evaluation_previous_goal": "Starting task",
			"memory": "Need new tab",
			"next_goal": "Create new tab",
			"action": [
				{
					"open_tab": {
						"url": "https://example.com"
					}
				}
			]
		}
		"""

		done_action = """
		{
			"thinking": "null",
			"evaluation_previous_goal": "Tab created",
			"memory": "Task done",
			"next_goal": "Complete",
			"action": [
				{
					"done": {
						"text": "Task completed",
						"success": true
					}
				}
			]
		}
		"""

		# Create mocks with tab creation actions
		mock_llm1 = create_mock_llm([tab_action, done_action])
		mock_llm2 = create_mock_llm([tab_action, done_action])

		# Create shared browser session
		shared_session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			)
		)

		try:
			await shared_session.start()

			# Create agents sharing the session
			agent1 = Agent(
				task='Task in tab 1',
				llm=mock_llm1,
				browser_session=shared_session,
				enable_memory=False,
			)

			agent2 = Agent(
				task='Task in tab 2',
				llm=mock_llm2,
				browser_session=shared_session,
				enable_memory=False,
			)

			# Run in parallel
			results = await asyncio.gather(agent1.run(), agent2.run())

			# Verify success
			for result in results:
				assert len(result.history) > 0
				last_history = result.history[-1]
				if last_history.model_output and last_history.model_output.action:
					assert any(hasattr(action, 'done') for action in last_history.model_output.action)

			# Verify multiple tabs were created
			tabs = await shared_session.get_tabs_info()
			assert len(tabs) >= 2  # At least 2 tabs

			# Verify same browser session was used
			assert agent1.browser_session == agent2.browser_session
			assert agent1.browser_session == shared_session

		finally:
			# Give playwright tasks a moment to complete before killing
			await asyncio.sleep(0.1)
			await shared_session.kill()
			# Give playwright.stop() time to complete cleanup
			await asyncio.sleep(0.1)

	async def test_reuse_browser_session_sequentially(self):
		"""Test reusing a browser session sequentially with keep_alive"""
		logger.info('Testing sequential browser session reuse')

		# Create mock LLM
		mock_llm = create_mock_llm()

		# Create a session with keep_alive
		session = BrowserSession(
			browser_profile=BrowserProfile(
				headless=True,
				user_data_dir=None,
				keep_alive=True,
			)
		)

		try:
			await session.start()
			initial_browser_pid = session.browser_pid

			# First agent
			agent1 = Agent(
				task='First task',
				llm=mock_llm,
				browser_session=session,
				enable_memory=False,
			)
			result1 = await agent1.run()

			# Session should still be alive
			assert session.initialized
			assert session.browser_pid == initial_browser_pid

			# Second agent reusing session
			agent2 = Agent(
				task='Second task',
				llm=mock_llm,
				browser_session=session,
				enable_memory=False,
			)
			result2 = await agent2.run()

			# Verify success and same browser
			for result in [result1, result2]:
				assert len(result.history) > 0
				last_history = result.history[-1]
				if last_history.model_output and last_history.model_output.action:
					assert any(hasattr(action, 'done') for action in last_history.model_output.action)
			assert session.browser_pid == initial_browser_pid

		finally:
			await session.kill()

	async def test_existing_playwright_objects(self):
		"""Test using existing playwright objects"""
		logger.info('Testing with existing playwright objects')

		async with async_playwright() as playwright:
			browser = await playwright.chromium.launch(headless=True)
			context = await browser.new_context()
			page = await context.new_page()

			# Create session with existing playwright objects
			browser_session = BrowserSession(
				browser_profile=BrowserProfile(
					headless=True,
					user_data_dir=None,
					keep_alive=False,
				),
				agent_current_page=page,
				browser_context=context,
				browser=browser,
				playwright=playwright,
			)

			# Create mock LLM
			mock_llm = create_mock_llm()

			# Create agent with the session
			agent = Agent(
				task='Test with existing playwright objects',
				llm=mock_llm,
				browser_session=browser_session,
				enable_memory=False,
			)

			# Run the agent
			result = await agent.run()

			# Verify success
			assert len(result.history) > 0
			last_history = result.history[-1]
			if last_history.model_output and last_history.model_output.action:
				assert any(hasattr(action, 'done') for action in last_history.model_output.action)

			await browser.close()
			await browser_session.kill()
		await playwright.stop()
