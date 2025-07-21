import asyncio
import logging
from typing import Any, Optional
from browser_use import Controller, BrowserSession, Agent, BrowserProfile
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.pydantic_v1 import SecretStr
import os
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WorkerAgent:
    """Worker agent that executes tasks using browser automation."""
    
    def __init__(
        self,
        worker_id: int,
        api_key: str,
        model: str = "gemini-2.0-flash",
        headless: bool = False,
        shared_memory=None
    ):
        self.worker_id = worker_id
        self.api_key = api_key
        self.model = model
        self.headless = headless
        self.browser: Optional[BrowserSession] = None
        self.controller: Optional[Controller] = None
        self.llm = ChatGoogleGenerativeAI(
            model=self.model,
            api_key=self.api_key,
            temperature=0.7
        )
        self.last_api_call = 0
        self.min_delay_between_calls = 2  # Minimum delay between API calls in seconds
        self.shared_memory = shared_memory
    
    async def initialize(self):
        """Initialize the browser session and controller."""
        logger.info(f"Worker {self.worker_id}: Initializing browser session...")
        try:
            # Assign a unique user_data_dir for each worker
            user_data_dir = os.path.expanduser(f"~/.config/browseruse/profiles/worker_{self.worker_id}")
            
            # Create a browser profile with visible mode
            browser_profile = BrowserProfile(
                headless=False,  # Force headless to False
                user_data_dir=user_data_dir,
                window_size={'width': 1280, 'height': 800},
                no_viewport=True,  # Disable viewport to use actual window size
                keep_alive=True,  # Keep browser open between tasks
                chromium_sandbox=False,  # Disable sandbox for better compatibility
                launch_options={
                    "args": [
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--window-size=1920,1080"
                    ]
                }
            )
            
            # Create browser session with the profile
            self.browser = BrowserSession(browser_profile=browser_profile)
            await self.browser.start()
            self.controller = Controller()
            logger.info(f"Worker {self.worker_id}: Browser session initialized")
        except Exception as e:
            logger.error(f"Worker {self.worker_id}: Failed to initialize browser session: {str(e)}")
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
        """Execute a task using browser automation with true parallelism."""
        logger.info(f"Worker {self.worker_id}: Starting task: {task}")
        try:
            # Remove rate limiting for true parallelism
            # await self._wait_for_rate_limit()
            
            if not self.browser or not self.controller:
                raise RuntimeError("Browser session or controller not initialized")
            
            agent = Agent(
                task=task,
                llm=self.llm,
                controller=self.controller,
                browser_session=self.browser
            )
            
            # Execute the task immediately
            result = await agent.run()
            logger.info(f"Worker {self.worker_id}: Task completed successfully")
            
            # Write result to shared memory if available
            if self.shared_memory:
                person = self._extract_person_name(task)
                await self.shared_memory.write(person, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Worker {self.worker_id}: Task failed: {str(e)}")
            if self.shared_memory:
                person = self._extract_person_name(task)
                await self.shared_memory.write(person, f"Error: {str(e)}")
            raise
    
    def _extract_person_name(self, task: str) -> str:
        people = ["Mark Zuckerberg", "Elon Musk", "Donald Trump", "Sam Altman"]
        for person in people:
            if person in task:
                return person
        return f"Worker_{self.worker_id}_task"
    
    async def cleanup(self):
        """Clean up the browser session."""
        logger.info(f"Worker {self.worker_id}: Cleaning up browser session...")
        if self.browser:
            await self.browser.stop()
        logger.info(f"Worker {self.worker_id}: Browser session cleaned up") 