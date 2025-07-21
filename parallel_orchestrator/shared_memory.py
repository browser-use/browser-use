"""
Shared Memory System for Multi-Agent Browser Use Framework

This module provides a thread-safe in-memory storage system for sharing task results
between the Base Agent and Worker Agents in the parallel orchestrator.

@file purpose: Provides thread-safe shared memory storage for multi-agent communication
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SharedMemory:
	"""
	Thread-safe shared memory system for storing and retrieving task results.

	This class provides a centralized storage mechanism that can be safely accessed
	by multiple worker agents running in parallel, as well as the base agent that
	coordinates them.

	Features:
	- Thread-safe operations using asyncio.Lock for async compatibility
	- Simple key-value storage with task IDs as keys
	- Methods for writing, reading, and managing task results
	- Clean interface for multi-agent communication
	"""

	def __init__(self):
		"""Initialize the shared memory with an empty storage and lock."""
		self._storage: dict[str, Any] = {}
		self._lock = asyncio.Lock()
		logger.debug('SharedMemory initialized')

	async def write(self, task_id: str, result: Any) -> None:
		"""
		Store a result for a specific task ID.

		Args:
		    task_id: Unique identifier for the task
		    result: The result data to store (can be any type)

		Example:
		    await shared_memory.write("task_001", {"email": "contact@company.com"})
		"""
		async with self._lock:
			self._storage[task_id] = result
			logger.debug(f'Stored result for task_id: {task_id}')

	async def read(self, task_id: str) -> Any | None:
		"""
		Retrieve a result for a specific task ID.

		Args:
		    task_id: Unique identifier for the task

		Returns:
		    The stored result for the task, or None if not found

		Example:
		    result = await shared_memory.read("task_001")
		"""
		async with self._lock:
			result = self._storage.get(task_id)
			if result is not None:
				logger.debug(f'Retrieved result for task_id: {task_id}')
			else:
				logger.debug(f'No result found for task_id: {task_id}')
			return result

	async def get_all(self) -> dict[str, Any]:
		"""
		Retrieve all stored task results.

		Returns:
		    A copy of the complete storage dictionary

		Example:
		    all_results = await shared_memory.get_all()
		"""
		async with self._lock:
			# Return a copy to prevent external modification
			result = self._storage.copy()
			logger.debug(f'Retrieved all results: {len(result)} tasks')
			return result

	async def clear(self) -> None:
		"""
		Clear all stored task results.

		Example:
		    await shared_memory.clear()
		"""
		async with self._lock:
			self._storage.clear()
			logger.debug('Cleared all stored results')

	async def has_task(self, task_id: str) -> bool:
		"""
		Check if a task result exists in storage.

		Args:
		    task_id: Unique identifier for the task

		Returns:
		    True if the task exists, False otherwise

		Example:
		    exists = await shared_memory.has_task("task_001")
		"""
		async with self._lock:
			return task_id in self._storage

	async def remove_task(self, task_id: str) -> bool:
		"""
		Remove a specific task result from storage.

		Args:
		    task_id: Unique identifier for the task

		Returns:
		    True if the task was removed, False if it didn't exist

		Example:
		    removed = await shared_memory.remove_task("task_001")
		"""
		async with self._lock:
			if task_id in self._storage:
				del self._storage[task_id]
				logger.debug(f'Removed task_id: {task_id}')
				return True
			else:
				logger.debug(f'Task_id not found for removal: {task_id}')
				return False

	async def get_task_count(self) -> int:
		"""
		Get the total number of stored tasks.

		Returns:
		    Number of tasks currently in storage

		Example:
		    count = await shared_memory.get_task_count()
		"""
		async with self._lock:
			return len(self._storage)

	def __str__(self) -> str:
		"""String representation of the shared memory state."""
		return f'SharedMemory(stored_tasks={len(self._storage)})'

	def __repr__(self) -> str:
		"""Detailed string representation for debugging."""
		return f'SharedMemory(storage={self._storage}, lock={self._lock})'


# Convenience function to create a shared memory instance
def create_shared_memory() -> SharedMemory:
	"""
	Create and return a new SharedMemory instance.

	Returns:
	    A new SharedMemory instance ready for use

	Example:
	    shared_memory = create_shared_memory()
	"""
	return SharedMemory()
