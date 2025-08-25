import asyncio
import hashlib
import logging
import os
from typing import Any

from browser_use import Agent, BrowserProfile, BrowserSession, Controller
from browser_use.llm import ChatGoogle
from browser_use.llm.messages import UserMessage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WorkerAgent:
    """Dynamic worker agent that can execute any type of task using browser automation."""

    def __init__(
            self,
            worker_id: int,
            api_key: str,
            model: str = 'gemini-1.5-flash',
            headless: bool = False,
            shared_memory=None):
        self.worker_id = worker_id
        self.api_key = api_key
        self.model = model
        self.headless = headless
        self.browser: BrowserSession | None = None
        self.controller: Controller | None = None
        self.llm = ChatGoogle(
            model=self.model,
            api_key=self.api_key,
            temperature=0.3)
        self.last_api_call = 0
        self.min_delay_between_calls = 1  # Reduced delay for better parallelism
        self.shared_memory = shared_memory

    async def initialize(self):
        """Initialize the browser session and controller."""
        logger.info(
            f'Worker {self.worker_id}: Initializing browser session...')
        try:
            # Assign a unique user_data_dir for each worker
            user_data_dir = os.path.expanduser(
                f'~/.config/browseruse/profiles/worker_{self.worker_id}')

            # Create a browser profile optimized for automation
            from browser_use.browser.profile import ViewportSize

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
            logger.info(
                f'Worker {self.worker_id}: Browser session initialized successfully')
        except Exception as e:
            logger.error(
                f'Worker {self.worker_id}: Failed to initialize browser session: {str(e)}')
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
                raise RuntimeError(
                    'Browser session or controller not initialized')

            agent = Agent(
                task=task,
                llm=self.llm,
                controller=self.controller,
                browser_session=self.browser)

            # Execute the task immediately
            result = await agent.run()
            logger.info(
                f'Worker {self.worker_id}: Task completed successfully')

            return result

        except Exception as e:
            logger.error(f'Worker {self.worker_id}: Task failed: {str(e)}')
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
            try:
                await self.browser.stop()
                self.browser = None
                logger.info(f'Worker {self.worker_id}: Browser session cleaned up')
            except Exception as e:
                logger.error(f'Worker {self.worker_id}: Error during cleanup: {str(e)}')

    async def _generate_result_key(self, task: str) -> str:
        """Generate a meaningful result key from the task using AI logic."""
        # Use AI to extract a meaningful key from the task
        try:
            if self.shared_memory and hasattr(self, 'llm'):
                prompt = f"""
                Given this task: "{task}"
                
                Generate a short, meaningful key (2-4 words) that represents what this task is looking for.
                Examples:
                - "Find the age of Elon Musk" → "Elon_Musk_age"
                - "When was Tesla founded" → "Tesla_founding_date"
                - "Compare Apple and Microsoft" → "Apple_Microsoft_comparison"
                - "Find weather in New York" → "New_York_weather"
                
                Return only the key, no explanation.
                """
                
                # Use the LLM to generate a meaningful key
                response = await self.llm.ainvoke([UserMessage(content=prompt)])
                key = response.completion.strip().replace(" ", "_")
                return key if key else f"Task_{hashlib.md5(task.encode()).hexdigest()[:8]}"
            else:
                # Fallback: use task hash
                task_hash = hashlib.md5(task.encode()).hexdigest()[:8]
                return f"Task_{task_hash}"
        except Exception as e:
            logger.debug(f"Error generating AI key: {str(e)}")
            # Fallback: use task hash
            task_hash = hashlib.md5(task.encode()).hexdigest()[:8]
            return f"Task_{task_hash}"

    async def run_task(self):
        """Run the assigned task and return results."""
        try:
            # Try multiple possible task keys to be more robust
            task = None
            possible_keys = [
                f"worker_{self.worker_id}_task",
                f"task_{self.worker_id + 1}",
                f"worker_{self.worker_id + 1}_task"
            ]
            
            for key in possible_keys:
                try:
                    if self.shared_memory:
                        task = await self.shared_memory.get(key)
                        if task:
                            logger.info(f'Worker {self.worker_id}: Found task with key "{key}": {task}')
                            break
                except Exception as e:
                    logger.debug(f'Worker {self.worker_id}: Key "{key}" not found: {str(e)}')
                    continue
            
            if not task:
                # Fallback: try to get any task from shared memory
                logger.warning(f'Worker {self.worker_id}: No specific task found, checking for any available task...')
                # This is a fallback - in practice, the base agent should assign tasks properly
                raise ValueError(f"No task assigned to worker {self.worker_id}")

            # Update status to running
            if self.shared_memory:
                await self.shared_memory.set(f"worker_{self.worker_id}_status", "Running")
                await self.shared_memory.set(f"worker_{self.worker_id}_progress", "25%")

            logger.info(f'Worker {self.worker_id}: Starting task: {task}')

            # Initialize the agent
            await self.initialize()
            if self.shared_memory:
                await self.shared_memory.set(f"worker_{self.worker_id}_progress", "50%")

            # Execute the task
            result = await self.execute_task(task)
            if self.shared_memory:
                await self.shared_memory.set(f"worker_{self.worker_id}_progress", "75%")

            # Extract meaningful name for result key
            result_key = await self._generate_result_key(task)

            # Store result in shared memory
            if self.shared_memory:
                await self.shared_memory.set(result_key, result)
                await self.shared_memory.set(f"worker_{self.worker_id}_progress", "100%")

            logger.info(f'Worker {self.worker_id}: Task completed successfully')
            return result

        except Exception as e:
            logger.error(f'Worker {self.worker_id}: Task failed: {str(e)}')
            if self.shared_memory:
                await self.shared_memory.set(f"worker_{self.worker_id}_status", "Failed")
                await self.shared_memory.set(f"worker_{self.worker_id}_error", str(e))
            raise
        finally:
            # Always cleanup the browser session
            await self.cleanup()
