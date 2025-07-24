import asyncio
import logging

import aiofiles
from shared_memory import SharedMemory
from worker_agent import WorkerAgent

from browser_use.llm import ChatGoogle
from browser_use.llm.messages import UserMessage

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseAgent:
	"""Dynamic base agent that can handle any natural language prompt and automatically determine optimal worker count."""

	def __init__(self, api_key: str, model: str = 'gemini-1.5-flash', max_workers: int = 10, headless: bool = False):
		self.api_key = api_key
		self.model = model
		self.max_workers = max_workers
		self.headless = headless
		self.workers = []
		self.shared_memory = SharedMemory()
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

		# Use AI to create a clean final answer
		await self.create_ai_cleaned_final_answer(clean_results)

		return clean_results

	async def create_ai_cleaned_final_answer(self, clean_results: dict):
		"""Use AI to create a clean, final answer from the aggregated results."""
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

			# Save to final_answers.txt
			filename = 'parallel_orchestrator/final_answers.txt'
			async with aiofiles.open(filename, 'w') as f:
				await f.write('AI-CLEANED FINAL ANSWER\n')
				await f.write('=' * 30 + '\n\n')
				await f.write(clean_answer)
				await f.write('\n\n')

			logger.info(f'AI-cleaned final answer saved to {filename}')

		except Exception as e:
			logger.error(f'Error creating AI-cleaned final answer: {str(e)}')
			# Fallback to original clean results
			filename = 'parallel_orchestrator/final_answers.txt'
			async with aiofiles.open(filename, 'w') as f:
				await f.write('FINAL ANSWERS (Fallback)\n')
				await f.write('=' * 25 + '\n\n')
				for key, result in clean_results.items():
					await f.write(f'{key}: {result}\n\n')

	async def process_task(self, main_task: str) -> dict:
		"""Process any natural language task with dynamic worker allocation."""
		logger.info(f'Starting to process task: {main_task}')

		# Use AI to analyze and split the task
		subtasks = await self.analyze_and_split_task(main_task)

		# Determine optimal number of workers
		workers_needed = len(subtasks)
		logger.info(f'Creating {workers_needed} worker agents for {len(subtasks)} subtasks...')

		# Create workers dynamically
		while len(self.workers) < workers_needed:
			worker = WorkerAgent(
				worker_id=len(self.workers),
				api_key=self.api_key,
				model=self.model,
				headless=self.headless,
				shared_memory=self.shared_memory,
			)
			self.workers.append(worker)
			await worker.initialize()

		# Start ALL tasks simultaneously for true parallelism
		logger.info('Starting ALL tasks in parallel...')
		tasks = []
		for worker, task in zip(self.workers[:workers_needed], subtasks):
			task_coro = worker.execute_task(task)
			tasks.append(task_coro)

		# Execute all tasks simultaneously
		try:
			await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=600)  # 10 minute timeout
		except TimeoutError:
			logger.error('Task execution timed out after 10 minutes')

		logger.info('All tasks completed')

		# Get raw results from shared memory
		raw_results = await self.shared_memory.get_all()

		# Aggregate and clean the results
		clean_results = await self.aggregate_results(raw_results)

		return clean_results

	async def cleanup(self):
		"""Clean up all worker agents."""
		logger.info('Cleaning up worker agents...')
		cleanup_tasks = [worker.cleanup() for worker in self.workers]
		await asyncio.gather(*cleanup_tasks)
		logger.info('Cleanup completed')
