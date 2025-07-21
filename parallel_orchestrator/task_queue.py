import asyncio
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Task:
    """Represents a single task to be executed by a worker agent."""
    id: str
    description: str
    created_at: datetime
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Any] = None
    error: Optional[str] = None

class TaskQueue:
    """Manages a queue of tasks for parallel execution."""
    
    def __init__(self):
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._tasks: Dict[str, Task] = {}
        self._results: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
    
    async def add_task(self, description: str) -> str:
        """Add a new task to the queue."""
        task = Task(
            id=f"task_{len(self._tasks)}",
            description=description,
            created_at=datetime.now()
        )
        self._tasks[task.id] = task
        await self._queue.put(task)
        return task.id
    
    async def get_task(self) -> Optional[Task]:
        """Get the next task from the queue."""
        try:
            return await self._queue.get()
        except asyncio.QueueEmpty:
            return None
    
    async def mark_task_completed(self, task_id: str, result: Any) -> None:
        """Mark a task as completed with its result."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "completed"
                self._tasks[task_id].result = result
                self._results[task_id] = result
    
    async def mark_task_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed with an error message."""
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "failed"
                self._tasks[task_id].error = error
    
    async def get_task_status(self, task_id: str) -> Optional[str]:
        """Get the status of a specific task."""
        return self._tasks.get(task_id, None).status if task_id in self._tasks else None
    
    async def get_all_results(self) -> Dict[str, Any]:
        """Get all completed task results."""
        return self._results.copy()
    
    async def is_queue_empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()
    
    async def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        return [task for task in self._tasks.values() if task.status == "pending"]
    
    async def get_completed_tasks(self) -> List[Task]:
        """Get all completed tasks."""
        return [task for task in self._tasks.values() if task.status == "completed"] 