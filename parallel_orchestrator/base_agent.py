import asyncio
from typing import List, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
import logging
from worker_agent import WorkerAgent
from shared_memory import SharedMemory

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseAgent:
    """Base agent that orchestrates parallel execution of worker agents."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        max_workers: int = 5,
        headless: bool = False
    ):
        self.api_key = api_key
        self.model = model
        self.max_workers = max_workers
        self.headless = headless
        self.workers = []
        self.shared_memory = SharedMemory()
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            api_key=api_key,
            temperature=0.7
        )
    
    async def initialize(self):
        """Initialize the base agent and prepare for dynamic worker creation."""
        logger.info("Initializing base agent...")
        # Workers will be created dynamically based on task requirements
        self.workers = []
        logger.info("Base agent initialized successfully")
    
    async def split_task(self, main_task: str) -> list:
        """Use AI to intelligently split the main task into independent subtasks."""
        logger.info(f"Using AI to split main task: {main_task}")
        
        # Create a prompt for the AI to split the task
        split_prompt = f"""
You are a task decomposition expert. Given a main task, break it down into independent subtasks that can be executed in parallel.

Main task: "{main_task}"

Rules:
1. Each subtask should be completely independent and can run in parallel
2. Each subtask should be specific and actionable
3. Return ONLY a JSON array of strings, no other text
4. Each subtask should be a complete, self-contained task description
5. If the task involves multiple people/companies/items, create one subtask per item

Examples:
- "Find ages of Elon Musk and Donald Trump" → ["Find the age of Elon Musk by searching online for their birth date and calculating their current age", "Find the age of Donald Trump by searching online for their birth date and calculating their current age"]
- "Find contact emails for Perplexity AI and Anthropic" → ["Find the contact email for Perplexity AI by visiting their website and looking for contact information", "Find the contact email for Anthropic by visiting their website and looking for contact information"]

Return the subtasks as a JSON array:
"""
        
        try:
            # Use the LLM to split the task
            response = await self.llm.ainvoke(split_prompt)
            response_text = response.content
            
            # Extract JSON array from response
            import json
            import re
            
            # Find JSON array in the response
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                subtasks = json.loads(json_match.group())
            else:
                # Fallback: try to parse the entire response as JSON
                subtasks = json.loads(response_text)
            
            logger.info(f"AI split into {len(subtasks)} subtasks: {subtasks}")
            return subtasks
            
        except Exception as e:
            logger.error(f"AI task splitting failed: {str(e)}")
            # Retry the Base Agent splitting once more
            logger.info("Retrying Base Agent task splitting...")
            try:
                response = await self.llm.ainvoke(split_prompt)
                response_text = response.content
                
                # Extract JSON array from response
                import json
                import re
                
                # Find JSON array in the response
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    subtasks = json.loads(json_match.group())
                else:
                    # Fallback: try to parse the entire response as JSON
                    subtasks = json.loads(response_text)
                
                logger.info(f"Base Agent retry successful - split into {len(subtasks)} subtasks: {subtasks}")
                return subtasks
                
            except Exception as retry_e:
                logger.error(f"Base Agent retry also failed: {str(retry_e)}")
                # Only as last resort, return the main task as a single task
                logger.info("Base Agent completely failed - returning main task as single task")
                return [main_task]
    
    async def aggregate_results(self, raw_results: dict) -> dict:
        """Aggregate and clean the results from shared memory."""
        logger.info("Aggregating and cleaning results...")
        clean_results = {}
        
        for person, result in raw_results.items():
            try:
                # Extract the final answer from the agent history
                if hasattr(result, 'all_results') and result.all_results:
                    # Find the final successful result
                    final_result = None
                    for action_result in reversed(result.all_results):
                        if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                            # Look for the final "done" result that contains the age calculation
                            if "was born on" in action_result.extracted_content and "years old" in action_result.extracted_content:
                                final_result = action_result.extracted_content
                                break
                    
                    if final_result:
                        clean_results[person] = final_result
                    else:
                        # Fallback: use the last result with content
                        for action_result in reversed(result.all_results):
                            if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                                clean_results[person] = action_result.extracted_content
                                break
                        else:
                            clean_results[person] = f"No final result found for {person}"
                else:
                    clean_results[person] = str(result)
                    
                logger.info(f"Extracted clean result for {person}")
            except Exception as e:
                logger.error(f"Error extracting result for {person}: {str(e)}")
                clean_results[person] = f"Error: {str(e)}"
        
        return clean_results
    
    async def process_task(self, main_task: str) -> dict:
        """Process the main task with true parallelism."""
        logger.info(f"Starting to process main task: {main_task}")
        
        # Use AI to split the task into subtasks
        subtasks = await self.split_task(main_task)
        
        # Initialize workers based on the number of subtasks
        workers_needed = len(subtasks)
        logger.info(f"Initializing {workers_needed} worker agents for {len(subtasks)} subtasks...")
        
        # Create workers if we don't have enough
        while len(self.workers) < workers_needed:
            worker = WorkerAgent(
                worker_id=len(self.workers),
                api_key=self.api_key,
                model=self.model,
                headless=self.headless,
                shared_memory=self.shared_memory
            )
            self.workers.append(worker)
            await worker.initialize()
        
        # Start ALL tasks simultaneously for true parallelism
        logger.info("Starting ALL tasks in parallel...")
        tasks = []
        for worker, task in zip(self.workers[:workers_needed], subtasks):
            task_coro = worker.execute_task(task)
            tasks.append(task_coro)
        
        # Execute all tasks simultaneously
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Task execution timed out after 5 minutes")
        
        logger.info("All tasks completed")
        # Get raw results from shared memory
        raw_results = await self.shared_memory.get_all()
        
        # Aggregate and clean the results
        clean_results = await self.aggregate_results(raw_results)
        
        return clean_results
    
    def _extract_person_name(self, task: str) -> str:
        """Extract person name from task description."""
        people = ["Mark Zuckerberg", "Elon Musk", "Donald Trump", "Sam Altman", "Geoffrey Hinton"]
        for person in people:
            if person in task:
                return person
        return "Unknown Person"
    
    async def cleanup(self):
        """Clean up all worker agents."""
        logger.info("Cleaning up worker agents...")
        cleanup_tasks = [worker.cleanup() for worker in self.workers]
        await asyncio.gather(*cleanup_tasks)
        logger.info("Cleanup completed") 