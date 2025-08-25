import asyncio
import logging

import aiofiles
try:
    from .shared_memory import SharedMemory
    from .worker_agent import WorkerAgent
except ImportError:
    from shared_memory import SharedMemory
    from worker_agent import WorkerAgent
from typing import Optional

from browser_use.llm import ChatGoogle
from browser_use.llm.messages import UserMessage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseAgent:
    """Dynamic base agent that can handle any natural language prompt and automatically determine optimal worker count."""

    def __init__(self, api_key: str, model: str = 'gemini-1.5-flash', max_workers: int = 10, headless: bool = True, shared_memory: Optional[SharedMemory] = None):
        self.api_key = api_key
        self.model = model
        self.max_workers = max_workers
        self.headless = headless
        self.workers = []
        self.shared_memory = shared_memory if shared_memory is not None else SharedMemory()
        self.llm = ChatGoogle(model=model, api_key=api_key, temperature=0.3)

    async def initialize(self):
        """Initialize the base agent."""
        logger.info('Initializing dynamic base agent...')
        self.workers = []
        logger.info('Base agent initialized successfully')

    async def analyze_and_split_task(self, main_task: str) -> list[str]:
        """Use AI to analyze any natural language task and break it into optimal subtasks."""
        logger.info(f'Analyzing and splitting task: {main_task}')

        analysis_prompt = f"""
You are an expert task decomposition system. Your job is to analyze any natural language goal and break it into independent, parallelizable subtasks.

MAIN TASK: "{main_task}"

ANALYSIS INSTRUCTIONS:
1. First, understand what the user wants to accomplish
2. Identify if this task can be broken into independent parts
3. Determine the optimal number of subtasks (1 to {self.max_workers})
4. Create specific, actionable subtasks that can run in parallel

EXAMPLES OF GOOD DECOMPOSITION:

"Find the top 5 most recent Hacker News posts and summarize each"
→ 5 subtasks (one per post)

"Compare the pricing of AWS, Google Cloud, and Azure for compute instances"
→ 3 subtasks (one per cloud provider)

"Find contact information for 10 tech companies"
→ 10 subtasks (one per company)

"Research the latest AI developments from OpenAI, Anthropic, and Google"
→ 3 subtasks (one per company)

"Create a summary of the current weather in New York, London, and Tokyo"
→ 3 subtasks (one per city)

"Find the age of Elon Musk and Sam Altman"
→ 2 subtasks (one per person)

"Find ages of alexandr wang and roy lee (cluely)"
→ 2 subtasks (one per person)

SINGLE TASK EXAMPLES (when decomposition doesn't make sense):
"Write a blog post about AI trends" → 1 subtask
"Analyze this specific website's performance" → 1 subtask
"Create a comprehensive report on climate change" → 1 subtask

RULES:
- Each subtask must be completely independent
- Each subtask should be specific and actionable
- Return ONLY a JSON array of strings
- Maximum {self.max_workers} subtasks
- If the task cannot be logically split, return a single subtask
- Be precise - don't create more subtasks than necessary

Return the subtasks as a JSON array:
"""

        try:
            # Use the LLM to analyze and split the task
            response = await self.llm.ainvoke([UserMessage(content=analysis_prompt)])
            response_text = response.completion

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

            # Validate subtasks
            if not isinstance(subtasks, list):
                subtasks = [main_task]

            # Ensure we don't exceed max workers
            if len(subtasks) > self.max_workers:
                logger.warning(f'AI suggested {len(subtasks)} subtasks, limiting to {self.max_workers}')
                subtasks = subtasks[: self.max_workers]

            logger.info(f'AI analysis complete - created {len(subtasks)} subtasks')
            for i, task in enumerate(subtasks):
                logger.info(f'  Subtask {i + 1}: {task}')

            return subtasks

        except Exception as e:
            logger.error(f'AI task analysis failed: {str(e)}')
            # Retry once
            try:
                logger.info('Retrying AI task analysis...')
                response = await self.llm.ainvoke([UserMessage(content=analysis_prompt)])
                response_text = response.completion

                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    subtasks = json.loads(json_match.group())
                else:
                    subtasks = json.loads(response_text)

                if not isinstance(subtasks, list):
                    subtasks = [main_task]

                if len(subtasks) > self.max_workers:
                    subtasks = subtasks[: self.max_workers]

                logger.info(f'AI retry successful - created {len(subtasks)} subtasks')
                return subtasks

            except Exception as retry_e:
                logger.error(f'AI analysis retry also failed: {str(retry_e)}')
                logger.info('Falling back to single task execution')
                return [main_task]

    async def aggregate_results(self, raw_results: dict) -> dict:
        """Aggregate and clean results from shared memory for any type of task."""
        logger.info('Aggregating and cleaning results...')
        clean_results = {}

        for task_key, result in raw_results.items():
            try:
                # Extract the final answer from the agent history
                if hasattr(result, 'all_results') and result.all_results:
                    # Find the final successful result
                    final_result = None
                    for action_result in reversed(result.all_results):
                        if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                            # Look for any meaningful final result
                            content = action_result.extracted_content
                            if content and len(content.strip()) > 10:  # Meaningful content
                                final_result = content
                                break

                    if final_result:
                        clean_results[task_key] = final_result
                    else:
                        # Fallback: use the last result with content
                        for action_result in reversed(result.all_results):
                            if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                                clean_results[task_key] = action_result.extracted_content
                                break
                        else:
                            clean_results[task_key] = f'No final result found for {task_key}'
                else:
                    clean_results[task_key] = str(result)

                logger.info(f'Extracted clean result for {task_key}')
            except Exception as e:
                logger.error(f'Error extracting result for {task_key}: {str(e)}')
                clean_results[task_key] = f'Error: {str(e)}'

        return clean_results

    async def create_ai_cleaned_final_answer(self, clean_results: dict) -> str:
        """Use AI to create a clean, final answer from the aggregated results and return it (do not write to file)."""
        try:
            # Create a prompt for the AI to extract only the essential information
            clean_prompt = f"""
You are an expert at extracting clean, final answers from raw data.

RAW RESULTS FROM WORKERS:
{clean_results}

TASK: Extract ONLY the essential information and present it in a clean, readable format.

RULES:
- Remove all technical details, browser actions, DOM elements, etc.
- Keep only the actual answers/findings
- Present information clearly and concisely
- If it's about ages, just say "The age of [person] is [age]"
- If it's about net worth, just say "The net worth of [person] is [amount]"
- If it's about weather, just say "Weather in [city] is [description]"
- Format as a simple, clean response

CLEAN FINAL ANSWER:
"""

            # Use the LLM to create clean final answer
            response = await self.llm.ainvoke([UserMessage(content=clean_prompt)])
            clean_answer = response.completion.strip()
            return clean_answer

        except Exception as e:
            logger.error(f'Error creating AI-cleaned final answer: {str(e)}')
            # Fallback: join raw results into a simple string
            try:
                joined = "\n".join(f"{k}: {v}" for k, v in clean_results.items())
                return joined
            except Exception:
                return ""

    async def save_aggregated_results_to_file(self, aggregated_results: dict) -> None:
        """Write the aggregated (per-subtask) results to final_answers.txt."""
        filename = 'final_answers.txt'
        async with aiofiles.open(filename, 'w') as f:
            await f.write('AGGREGATED RESULTS\n')
            await f.write('=' * 30 + '\n\n')
            for key, result in aggregated_results.items():
                await f.write(f'{key}: {result}\n\n')
        logger.info(f'Aggregated results saved to {filename}')

    async def process_task(self, main_task: str) -> dict:
        """Process a main task by splitting it into subtasks and coordinating workers."""
        # Update shared memory with task start
        await self.shared_memory.set("task_start", main_task)
        await self.shared_memory.set("task_status", "Analyzing")

        try:
            logger.info(f"Analyzing and splitting task: {main_task}")
            
            # Update shared memory with splitting status
            await self.shared_memory.set("task_status", "Splitting tasks")
            
            # Analyze and split the task
            subtasks = await self.analyze_and_split_task(main_task)
            workers_needed = len(subtasks)
            
            # Update shared memory with task count
            await self.shared_memory.set("total_tasks", workers_needed)
            await self.shared_memory.set("completed_tasks", 0)
            
            logger.info(f"Creating {workers_needed} worker agents for {len(subtasks)} subtasks...")
            
            # Create worker agents
            for i, subtask in enumerate(subtasks):
                worker = WorkerAgent(
                    worker_id=i,
                    api_key=self.api_key,
                    model=self.model,
                    headless=self.headless,
                    shared_memory=self.shared_memory
                )
                self.workers.append(worker)
                
                # Update shared memory with worker status
                await self.shared_memory.set(f"worker_{i}_status", "Created")  # Use i for consistency
            
            # Update shared memory with total workers
            await self.shared_memory.set("total_workers", len(self.workers))
            
            # Assign tasks to workers
            await self.shared_memory.set("task_status", "Assigning tasks")
            for i, (worker, subtask) in enumerate(zip(self.workers, subtasks)):
                await self.shared_memory.set(f"task_{i+1}", subtask)
                await self.shared_memory.set(f"worker_{i}_task", subtask)  # Use i for worker_id (0-based)
                await self.shared_memory.set(f"worker_{i}_status", "Assigned")  # Use i for consistency
            
            # Update shared memory with running status
            await self.shared_memory.set("task_status", "Running workers")
            
            logger.info(f"Starting {len(self.workers)} workers in parallel...")
            
            # Start all workers in parallel
            tasks = []
            for worker in self.workers:
                task = asyncio.create_task(worker.run_task())
                tasks.append(task)
            
            # Wait for all workers to complete
            results = {}
            completed = 0
            
            for i, task in enumerate(tasks):
                try:
                    result = await task
                    results[f"Worker_{i+1}"] = result
                    completed += 1
                    
                    # Update shared memory with success status
                    await self.shared_memory.set(f"worker_{i}_status", "Done")  # Use i for consistency
                    await self.shared_memory.set(f"task_{i+1}_status", "Done")
                    
                except Exception as e:
                    logger.error(f"Worker {i+1} failed: {str(e)}")
                    completed += 1
                    
                    # Update shared memory with failure status
                    await self.shared_memory.set(f"worker_{i}_status", "Failed")  # Use i for consistency
                    await self.shared_memory.set(f"task_{i+1}_status", "Failed")
            
            # Update shared memory with completion count
            await self.shared_memory.set("completed_tasks", completed)
            
            # Aggregate and clean results
            await self.shared_memory.set("task_status", "Aggregating results")
            logger.info("Aggregating and cleaning results...")
            
            clean_results = await self.aggregate_results(results)
            # Save aggregated results to file (full results)
            await self.save_aggregated_results_to_file(clean_results)
            
            # Create AI-cleaned final answer for terminal display only
            await self.shared_memory.set("task_status", "Creating final answer")
            cleaned_answer = await self.create_ai_cleaned_final_answer(clean_results)
            await self.shared_memory.set("final_cleaned_answer", cleaned_answer)
            
            # Update shared memory with final results
            await self.shared_memory.set("final_results", clean_results)
            await self.shared_memory.set("task_status", "Completed")
            
            # Clean up all worker agents to close browser tabs
            logger.info("Cleaning up worker agents and closing browser tabs...")
            await self.cleanup()
            
            return clean_results
            
        except Exception as e:
            logger.error(f"Task processing failed: {str(e)}")
            await self.shared_memory.set("task_status", f"Failed: {str(e)}")
            raise

    async def cleanup(self):
        """Clean up all worker agents."""
        logger.info('Cleaning up worker agents...')
        cleanup_tasks = [worker.cleanup() for worker in self.workers]
        await asyncio.gather(*cleanup_tasks)
        logger.info('Cleanup completed')
