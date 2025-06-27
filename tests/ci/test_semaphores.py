"""
Test semaphore functionality, especially multiprocess semaphores.
"""

import asyncio
import multiprocessing
import os
import sys
import time
from pathlib import Path

import pytest

# Add the browser-use directory to the path so we can import from it
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from browser_use.utils import retry


def worker_acquire_semaphore(
	worker_id: int,
	start_time: float,
	results_queue: multiprocessing.Queue,
	hold_time: float = 0.5,
	timeout: float = 5.0,
	should_release: bool = True,
):
	"""Worker process that tries to acquire a semaphore."""
	try:
		print(f'Worker {worker_id} starting...')

		# Define a function decorated with multiprocess semaphore
		@retry(
			retries=0,
			timeout=10,
			semaphore_limit=3,  # Only 3 concurrent processes allowed
			semaphore_name='test_multiprocess_sem',
			semaphore_scope='multiprocess',
			semaphore_timeout=timeout,
			semaphore_lax=False,  # Strict mode - must acquire semaphore
		)
		async def semaphore_protected_function():
			acquire_time = time.time() - start_time
			results_queue.put(('acquired', worker_id, acquire_time))

			# Hold the semaphore for a bit
			await asyncio.sleep(hold_time)

			release_time = time.time() - start_time
			results_queue.put(('released', worker_id, release_time))
			return f'Worker {worker_id} completed'

		# Run the async function
		print(f'Worker {worker_id} running async function...')
		result = asyncio.run(semaphore_protected_function())
		print(f'Worker {worker_id} completed with result: {result}')
		results_queue.put(('completed', worker_id, result))

	except TimeoutError as e:
		timeout_time = time.time() - start_time
		print(f'Worker {worker_id} timed out: {e}')
		results_queue.put(('timeout', worker_id, timeout_time, str(e)))
	except Exception as e:
		error_time = time.time() - start_time
		print(f'Worker {worker_id} error: {type(e).__name__}: {e}')
		import traceback

		traceback.print_exc()
		results_queue.put(('error', worker_id, error_time, str(e)))


def worker_that_dies(
	worker_id: int,
	start_time: float,
	results_queue: multiprocessing.Queue,
	die_after: float = 0.2,
):
	"""Worker process that acquires semaphore then dies without releasing."""
	try:

		@retry(
			retries=0,
			timeout=10,
			semaphore_limit=2,  # Only 2 concurrent processes
			semaphore_name='test_death_sem',
			semaphore_scope='multiprocess',
			semaphore_timeout=5.0,
			semaphore_lax=False,
		)
		async def semaphore_protected_function():
			acquire_time = time.time() - start_time
			results_queue.put(('acquired', worker_id, acquire_time))

			# Hold for a bit then simulate crash
			await asyncio.sleep(die_after)

			# Simulate unexpected death
			os._exit(1)  # Hard exit without cleanup

		asyncio.run(semaphore_protected_function())

	except Exception as e:
		error_time = time.time() - start_time
		results_queue.put(('error', worker_id, error_time, str(e)))


def worker_death_test_normal(
	worker_id: int,
	start_time: float,
	results_queue: multiprocessing.Queue,
):
	"""Worker for death test that uses the same semaphore."""

	@retry(
		retries=0,
		timeout=10,
		semaphore_limit=2,
		semaphore_name='test_death_sem',
		semaphore_scope='multiprocess',
		semaphore_timeout=5.0,
		semaphore_lax=False,
	)
	async def semaphore_protected_function():
		acquire_time = time.time() - start_time
		results_queue.put(('acquired', worker_id, acquire_time))
		await asyncio.sleep(0.2)
		release_time = time.time() - start_time
		results_queue.put(('released', worker_id, release_time))
		return f'Worker {worker_id} completed'

	try:
		result = asyncio.run(semaphore_protected_function())
		results_queue.put(('completed', worker_id, result))
	except Exception as e:
		error_time = time.time() - start_time
		results_queue.put(('error', worker_id, error_time, str(e)))


class TestMultiprocessSemaphore:
	"""Test multiprocess semaphore functionality."""

	@pytest.mark.skip(reason='Flaky test - FIFO ordering is not guaranteed due to process scheduling')
	def test_basic_multiprocess_semaphore(self):
		"""Test that semaphore limits work across processes."""
		results_queue = multiprocessing.Queue()
		start_time = time.time()
		processes = []

		# Start 6 worker processes (semaphore limit is 3)
		for i in range(6):
			p = multiprocessing.Process(target=worker_acquire_semaphore, args=(i, start_time, results_queue, 0.5, 5.0))
			p.start()
			processes.append(p)
			time.sleep(0.05)  # Small delay to ensure processes start in order

		# Wait for all processes to complete
		for p in processes:
			p.join(timeout=10)

		# Collect results
		results = []
		while not results_queue.empty():
			results.append(results_queue.get())

		# Analyze results
		acquired_events = [r for r in results if r[0] == 'acquired']
		released_events = [r for r in results if r[0] == 'released']
		completed_events = [r for r in results if r[0] == 'completed']

		# All 6 workers should complete successfully
		assert len(completed_events) == 6, f'Expected 6 completions, got {len(completed_events)}'

		# Sort by acquisition time
		acquired_events.sort(key=lambda x: x[2])

		# Extract worker IDs in order of acquisition
		acquisition_order = [event[1] for event in acquired_events]

		# Verify FIFO order - workers should generally acquire in start order
		# Allow some flexibility for first batch due to process startup variations
		first_batch = acquisition_order[:3]
		second_batch = acquisition_order[3:]

		# All first batch workers should have lower IDs than second batch
		max_first_batch = max(first_batch)
		min_second_batch = min(second_batch)
		assert max_first_batch < min_second_batch, (
			f'First batch (workers {first_batch}) should have lower IDs than second batch (workers {second_batch})'
		)

		# Verify semaphore is actually limiting concurrency
		# Check that no more than 3 workers held the semaphore simultaneously
		active_workers = []
		# Filter out events that don't have timing information
		timed_events = [e for e in results if len(e) >= 3 and isinstance(e[2], (int, float))]
		for event in sorted(timed_events, key=lambda x: x[2]):  # Sort all events by time
			if event[0] == 'acquired':
				active_workers.append(event[1])
				assert len(active_workers) <= 3, f'Too many workers active: {active_workers}'
			elif event[0] == 'released':
				if event[1] in active_workers:
					active_workers.remove(event[1])

	def test_semaphore_timeout(self):
		"""Test that semaphore timeout works correctly."""
		results_queue = multiprocessing.Queue()
		start_time = time.time()
		processes = []

		# Start 4 workers with short timeout (semaphore limit is 3)
		for i in range(4):
			p = multiprocessing.Process(
				target=worker_acquire_semaphore,
				args=(i, start_time, results_queue, 2.0, 0.5),  # 2s hold, 0.5s timeout
			)
			p.start()
			processes.append(p)

		# Wait for processes
		for p in processes:
			p.join(timeout=5)

		# Collect results
		results = []
		while not results_queue.empty():
			results.append(results_queue.get())

		# Check that we have timeout events
		timeout_events = [r for r in results if r[0] == 'timeout']
		completed_events = [r for r in results if r[0] == 'completed']

		# 3 should complete, 1 should timeout
		assert len(completed_events) == 3, f'Expected 3 completions, got {len(completed_events)}'
		assert len(timeout_events) == 1, f'Expected 1 timeout, got {len(timeout_events)}'

		# Verify that timeout occurred before any releases
		released_events = [r for r in results if r[0] == 'released']
		if released_events and timeout_events:
			min_release_time = min(r[2] for r in released_events)
			timeout_time = timeout_events[0][2]
			assert timeout_time < min_release_time, (
				f'Timeout should occur before releases. Timeout: {timeout_time:.2f}s, First release: {min_release_time:.2f}s'
			)

	def test_process_death_releases_semaphore(self):
		"""Test that killing a process releases its semaphore slot."""
		results_queue = multiprocessing.Queue()
		start_time = time.time()

		# Start 2 processes that will die (limit is 2)
		death_processes = []
		for i in range(2):
			p = multiprocessing.Process(target=worker_that_dies, args=(i, start_time, results_queue, 0.3))
			p.start()
			death_processes.append(p)

		# Wait a bit for them to acquire
		time.sleep(0.5)

		# Now start 2 more processes that should be able to acquire after the first 2 die
		normal_processes = []
		for i in range(2, 4):
			p = multiprocessing.Process(target=worker_death_test_normal, args=(i, start_time, results_queue))
			p.start()
			normal_processes.append(p)

		# Wait for death processes to exit
		for p in death_processes:
			p.join(timeout=2)
			assert p.exitcode == 1, f'Process should have exited with code 1, got {p.exitcode}'

		# Wait for normal processes
		for p in normal_processes:
			p.join(timeout=10)
			assert p.exitcode == 0, 'Process should complete successfully'

		# Collect results
		results = []
		while not results_queue.empty():
			results.append(results_queue.get())

		# Check that processes 2 and 3 were able to acquire
		acquired_events = [r for r in results if r[0] == 'acquired']
		completed_events = [r for r in results if r[0] == 'completed' and r[1] >= 2]

		# Should have 4 acquisitions total (2 that died + 2 that completed)
		assert len(acquired_events) >= 4, f'Expected at least 4 acquisitions, got {len(acquired_events)}'

		# Processes 2 and 3 should complete
		assert len(completed_events) == 2, f'Expected 2 completions from workers 2-3, got {len(completed_events)}'

	@pytest.mark.skip(reason='Flaky test - FIFO ordering is not guaranteed due to process scheduling')
	def test_concurrent_acquisition_order(self):
		"""Test that processes acquire semaphore with fairness."""
		results_queue = multiprocessing.Queue()
		start_time = time.time()
		processes = []

		# Start 5 processes with delays to establish clear order (limit is 2)
		for i in range(5):
			p = multiprocessing.Process(
				target=worker_acquire_semaphore,
				args=(i, start_time, results_queue, 0.3, 5.0),  # 0.3s hold time
			)
			p.start()
			processes.append(p)
			time.sleep(0.1)  # 100ms delay between starts to establish clear order

		# Wait for all to complete
		for p in processes:
			p.join(timeout=10)

		# Collect and analyze results
		results = []
		while not results_queue.empty():
			results.append(results_queue.get())

		acquired_events = [r for r in results if r[0] == 'acquired']
		acquired_events.sort(key=lambda x: x[2])  # Sort by acquisition time

		# Extract worker IDs in order of acquisition
		acquisition_order = [event[1] for event in acquired_events]

		# Verify all workers acquired
		assert len(acquisition_order) == 5, f'All 5 workers should acquire, got {len(acquisition_order)}'
		assert set(acquisition_order) == {0, 1, 2, 3, 4}, f'All workers should acquire: {acquisition_order}'

		# Verify FIFO order is generally maintained
		# Workers started earlier should generally acquire earlier
		# We check that the average position of early workers is lower than late workers
		early_workers = [0, 1, 2]  # Started first
		late_workers = [3, 4]  # Started later

		early_positions = [acquisition_order.index(w) for w in early_workers]
		late_positions = [acquisition_order.index(w) for w in late_workers]

		avg_early = sum(early_positions) / len(early_positions)
		avg_late = sum(late_positions) / len(late_positions)

		assert avg_early < avg_late, (
			f'Early workers should acquire before late workers on average. '
			f'Early avg position: {avg_early:.1f}, Late avg position: {avg_late:.1f}. '
			f'Order: {acquisition_order}'
		)

	def test_semaphore_persistence_across_runs(self):
		"""Test that semaphore state persists correctly across process runs."""
		results_queue = multiprocessing.Queue()
		start_time = time.time()

		# First run: Start 3 processes that hold semaphore (limit is 3)
		first_batch = []
		for i in range(3):
			p = multiprocessing.Process(
				target=worker_acquire_semaphore,
				args=(i, start_time, results_queue, 1.0, 5.0),  # Hold for 1 second
			)
			p.start()
			first_batch.append(p)

		# Wait for them to acquire and ensure all slots are taken
		time.sleep(0.5)

		# Try to start one more - should timeout quickly
		timeout_worker = multiprocessing.Process(
			target=worker_acquire_semaphore,
			args=(99, start_time, results_queue, 0.5, 0.3),  # Very short timeout
		)
		timeout_worker.start()
		timeout_worker.join(timeout=2)

		# Wait for first batch to complete
		for p in first_batch:
			p.join(timeout=5)

		# Now start a new batch - should work immediately
		second_batch = []
		for i in range(3, 6):
			p = multiprocessing.Process(target=worker_acquire_semaphore, args=(i, start_time, results_queue, 0.2, 5.0))
			p.start()
			second_batch.append(p)

		for p in second_batch:
			p.join(timeout=5)

		# Analyze results
		results = []
		while not results_queue.empty():
			results.append(results_queue.get())

		timeout_events = [r for r in results if r[0] == 'timeout' and r[1] == 99]
		second_batch_acquired = [r for r in results if r[0] == 'acquired' and r[1] >= 3]

		# Worker 99 should timeout
		assert len(timeout_events) == 1, 'Worker 99 should timeout'

		# Second batch should all acquire successfully
		assert len(second_batch_acquired) == 3, 'All second batch workers should acquire'

		# Verify the second batch acquired after the first batch started releasing
		# Get the minimum release time from first batch
		first_batch_released = [r for r in results if r[0] == 'released' and r[1] < 3]
		if first_batch_released:
			min_release_time = min(r[2] for r in first_batch_released)
			# At least one second batch worker should have acquired after first release
			second_batch_times = [event[2] for event in second_batch_acquired]
			assert any(t >= min_release_time - 0.1 for t in second_batch_times), (
				f'Second batch should acquire after first batch releases. '
				f'Min release: {min_release_time:.2f}, Second batch times: {second_batch_times}'
			)


class TestRegularSemaphoreScopes:
	"""Test non-multiprocess semaphore scopes still work correctly."""

	async def test_global_scope(self):
		"""Test global scope semaphore."""
		results = []

		@retry(
			retries=0,
			timeout=1,
			semaphore_limit=2,
			semaphore_scope='global',
			semaphore_name='test_global',
		)
		async def test_func(worker_id: int):
			results.append(('start', worker_id, time.time()))
			await asyncio.sleep(0.1)
			results.append(('end', worker_id, time.time()))
			return worker_id

		# Run 4 tasks concurrently (limit is 2)
		tasks = [test_func(i) for i in range(4)]
		await asyncio.gather(*tasks)

		# Check that only 2 ran concurrently
		starts = [r for r in results if r[0] == 'start']
		starts.sort(key=lambda x: x[2])

		# First 2 should start immediately
		assert starts[1][2] - starts[0][2] < 0.05

		# 3rd should wait for first to finish
		assert starts[2][2] - starts[0][2] > 0.08

	async def test_class_scope(self):
		"""Test class scope semaphore."""

		class TestClass:
			def __init__(self):
				self.results = []

			@retry(
				retries=0,
				timeout=1,
				semaphore_limit=1,
				semaphore_scope='class',
				semaphore_name='test_method',
			)
			async def test_method(self, worker_id: int):
				self.results.append(('start', worker_id, time.time()))
				await asyncio.sleep(0.1)
				self.results.append(('end', worker_id, time.time()))
				return worker_id

		# Create two instances
		obj1 = TestClass()
		obj2 = TestClass()

		# Run method on both instances concurrently
		# They should share the semaphore (class scope)
		start_time = time.time()
		await asyncio.gather(
			obj1.test_method(1),
			obj2.test_method(2),
		)
		end_time = time.time()

		# Should take ~0.2s (sequential) not ~0.1s (parallel)
		assert end_time - start_time > 0.18

	async def test_self_scope(self):
		"""Test self scope semaphore."""

		class TestClass:
			def __init__(self):
				self.results = []

			@retry(
				retries=0,
				timeout=1,
				semaphore_limit=1,
				semaphore_scope='self',
				semaphore_name='test_method',
			)
			async def test_method(self, worker_id: int):
				self.results.append(('start', worker_id, time.time()))
				await asyncio.sleep(0.1)
				self.results.append(('end', worker_id, time.time()))
				return worker_id

		# Create two instances
		obj1 = TestClass()
		obj2 = TestClass()

		# Run method on both instances concurrently
		# They should NOT share the semaphore (self scope)
		start_time = time.time()
		await asyncio.gather(
			obj1.test_method(1),
			obj2.test_method(2),
		)
		end_time = time.time()

		# Should take ~0.1s (parallel) not ~0.2s (sequential)
		assert end_time - start_time < 0.15


if __name__ == '__main__':
	# Run the tests
	pytest.main([__file__, '-v'])
