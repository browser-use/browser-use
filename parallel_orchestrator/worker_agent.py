import asyncio
import hashlib
import logging
import os
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from browser_use import Agent, BrowserProfile, BrowserSession, Controller

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WorkerAgent:
	"""Dynamic worker agent that can execute any type of task using browser automation."""

	def __init__(self, worker_id: int, api_key: str, model: str = 'gemini-1.5-flash', headless: bool = False, shared_memory=None):
		self.worker_id = worker_id
		self.api_key = api_key
		self.model = model
		self.headless = headless
		self.browser: BrowserSession | None = None
		self.controller: Controller | None = None
		self.llm = ChatGoogleGenerativeAI(model=self.model, api_key=self.api_key, temperature=0.3)
		self.last_api_call = 0
		self.min_delay_between_calls = 1  # Reduced delay for better parallelism
		self.shared_memory = shared_memory

	async def initialize(self):
		"""Initialize the browser session and controller."""
		logger.info(f'Worker {self.worker_id}: Initializing browser session...')
		try:
			# Assign a unique user_data_dir for each worker
			user_data_dir = os.path.expanduser(f'~/.config/browseruse/profiles/worker_{self.worker_id}')

			# Create a browser profile optimized for automation
			from browser_use.browser.types import ViewportSize
			browser_profile = BrowserProfile(
				headless=self.headless,  # Use the headless setting from constructor
				user_data_dir=user_data_dir,
				window_size=ViewportSize(width=1280, height=800),
				no_viewport=True,
				keep_alive=True,
				chromium_sandbox=False,
			)

			# Create browser session with the profile
			self.browser = BrowserSession(browser_profile=browser_profile)
			await self.browser.start()
			self.controller = Controller()
			logger.info(f'Worker {self.worker_id}: Browser session initialized successfully')
		except Exception as e:
			logger.error(f'Worker {self.worker_id}: Failed to initialize browser session: {str(e)}')
			raise

	async def _wait_for_rate_limit(self):
		"""Wait if necessary to respect API rate limits."""
		current_time = asyncio.get_event_loop().time()
		time_since_last_call = current_time - self.last_api_call
		if time_since_last_call < self.min_delay_between_calls:
			wait_time = self.min_delay_between_calls - time_since_last_call
			await asyncio.sleep(wait_time)
		self.last_api_call = asyncio.get_event_loop().time()

	async def execute_task(self, task: str) -> Any:
		"""Execute any type of task using browser automation with true parallelism."""
		logger.info(f'Worker {self.worker_id}: Starting task: {task}')
		try:
			if not self.browser or not self.controller:
				raise RuntimeError('Browser session or controller not initialized')

			agent = Agent(task=task, llm=self.llm, controller=self.controller, browser_session=self.browser)

			# Execute the task immediately
			result = await agent.run()
			logger.info(f'Worker {self.worker_id}: Task completed successfully')

			# Write result to shared memory if available
			if self.shared_memory:
				task_key = self._generate_task_key(task)
				await self.shared_memory.write(task_key, result)

			return result

		except Exception as e:
			logger.error(f'Worker {self.worker_id}: Task failed: {str(e)}')
			if self.shared_memory:
				task_key = self._generate_task_key(task)
				await self.shared_memory.write(task_key, f'Error: {str(e)}')
			raise

	def _generate_task_key(self, task: str) -> str:
		"""Generate a unique key for any task using hash-based approach."""
		# Simple hash-based key generation - no hardcoded logic
		task_hash = hashlib.md5(task.encode()).hexdigest()[:8]
		return f'Task_{task_hash}'

	async def cleanup(self):
		"""Clean up the browser session."""
		logger.info(f'Worker {self.worker_id}: Cleaning up browser session...')
		if self.browser:
			await self.browser.stop()
		logger.info(f'Worker {self.worker_id}: Browser session cleaned up')
