"""
@file purpose: Comprehensive judge system for evaluating browser-use agent runs with detailed structured feedback.
"""

import asyncio
import base64
import io
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
	# Access & Authentication
	CAPTCHA_CHALLENGE = 'captcha_challenge'
	LOGIN_REQUIRED = 'login_required'
	RATE_LIMITED = 'rate_limited'

	# Agent Behavior Issues
	INFINITE_LOOP = 'infinite_loop'
	CONTEXT_LOSS = 'missing_user_data'

	# Browser & Technical
	ELEMENT_NOT_FOUND = 'element_not_found'
	CLICK_FAILURE = 'click_failure'
	LOAD_TIMEOUT = 'load_timeout'
	JAVASCRIPT_ERROR = 'javascript_error'
	MAX_STEPS_REACHED = 'max_steps_reached'

	CONTENT_PARSING_ERROR = 'content_parsing_error'

	# Enhanced Detection Categories
	NAVIGATION_CONFUSION = 'navigation_confusion'
	FORM_FILLING_ERROR = 'form_filling_error'
	IFRAME_ISSUES = 'iframe_issues'
	BROWSER_CRASHES = 'browser_crashes'
	IMPOSSIBLE_TASK = 'impossible_task'

	# Browser-Use Specific Categories
	INVALID_ELEMENT_INDEX = 'invalid_element_index'  # Using non-existent [index] values
	FILE_SYSTEM_MISUSE = 'file_system_misuse'  # Not saving results or tracking progress

	EXTRACT_DATA_MISUSE = 'extract_data_misuse'  # Wrong usage of extract_structured_data

	# Output & Task Completion Issues
	PARTIAL_OUTPUT = 'partial_output'
	WRONG_OUTPUT_FORMAT = 'wrong_output_format'


class TaskCategory(Enum):
	EXTRACTION = 'extraction'
	INTERACTION = 'interaction'
	LOGIN = 'login'
	RESEARCH = 'research'
	SHOPPING = 'shopping'
	BOOKING = 'booking'
	COMPARISON = 'comparison'
	QA_TESTING = 'qa_testing'
	FORM_FILLING = 'form_filling'
	NAVIGATION = 'navigation'
	SEARCH = 'search'
	FILTERING = 'filtering'
	CONTENT_CREATION = 'content_creation'
	FILE_OPERATIONS = 'file_operations'
	MULTI_STEP_WORKFLOW = 'multi_step_workflow'


class JudgeResult(BaseModel):
	# Basic Information
	task_summary: str  # 1 sentence summary

	# Analysis
	reasoning: str  # What went well/not well analysis
	error_categories: list[ErrorCategory]  # Core error categories identified

	final_score: int  # Overall score (0-100) - percentage of task completion

	# Developer Feedback
	improvement_tips: list[str]  # Concrete improvement suggestions


def encode_image(image_path: str) -> str:
	"""Convert image file to base64 string."""
	try:
		with Image.open(image_path) as image:
			if image.mode == 'RGBA':
				image = image.convert('RGB')
			buffered = io.BytesIO()
			image.save(buffered, format='JPEG')
			return base64.b64encode(buffered.getvalue()).decode('utf-8')
	except Exception as e:
		logger.error(f'Failed to encode image {image_path}: {e}')
		return ''


def truncate_text(text: str, max_length: int, from_beginning: bool = False) -> str:
	"""Truncate text to maximum length with eval system indicator."""
	if len(text) <= max_length:
		return text
	if from_beginning:
		return '...[cut for eval]' + text[-max_length + 23 :]
	else:
		return text[: max_length - 23] + '...[cut for eval]...'


def prepare_agent_steps(complete_history: list[dict]) -> list[str]:
	"""Extract and format agent steps, limiting each to 2000 characters.

	Excludes the last step if it contains a 'done' action, since that content
	is already included in the final_result.
	"""
	# Check if last step contains a 'done' action
	# history_to_process = complete_history.copy()
	# if complete_history:
	# 	last_step = complete_history[-1]
	# 	if last_step.get('result'):
	# 		for result in last_step['result']:
	# 			if isinstance(result, dict) and result.get('is_done'):
	# 				# Exclude the last step since it's a 'done' action
	# 				history_to_process = complete_history[:-1]
	# 				break
	history_to_process = complete_history

	steps = []
	for i, step in enumerate(history_to_process):
		step_text = f'Step {i + 1}:\n'

		# Add model output if available
		if step.get('model_output'):
			model_output = step['model_output']
			if isinstance(model_output, dict):
				# Format the model output nicely
				if 'action' in model_output:
					action_json = json.dumps(model_output['action'], indent=1)
					if len(action_json) > 500:
						step_text += f'Actions: {action_json[:500]}...[cut for eval system]\n'
					else:
						step_text += f'Actions: {action_json}\n'
				# if 'current_state' in model_output:
				# step_text += f'State: {model_output["current_state"]}\n'

		# Add results if available
		if step.get('result'):
			for j, result in enumerate(step['result']):
				if isinstance(result, dict):
					if result.get('extracted_content'):
						content = str(result['extracted_content'])
						if len(content) > 500:
							step_text += f'Result {j + 1}: {content[:500]}...[cut for eval system]\n'
						else:
							step_text += f'Result {j + 1}: {content}\n'
					if result.get('error'):
						error = str(result['error'])
						if len(error) > 500:
							step_text += f'Error {j + 1}: {error[:500]}...[cut for eval system]\n'
						else:
							step_text += f'Error {j + 1}: {error}\n'

		steps.append(step_text)

	# iterate reversed over steps until you reach 15000 char and return the last part of the steps
	total_length = 0
	last_part: list[str] = []
	for step_text in reversed(steps):
		total_length += len(step_text)
		if total_length > 15000:
			break
		last_part.append(step_text)
	return last_part[::-1]


def are_images_identical(img_path1: str, img_path2: str) -> bool:
	"""Check if two images are identical by comparing their content."""
	try:
		with Image.open(img_path1) as img1, Image.open(img_path2) as img2:
			# Convert to same format for comparison
			if img1.mode != img2.mode:
				img1 = img1.convert('RGB')
				img2 = img2.convert('RGB')

			# Compare sizes first (quick check)
			if img1.size != img2.size:
				return False

			# Compare pixel data
			return list(img1.getdata()) == list(img2.getdata())
	except Exception as e:
		logger.warning(f'Failed to compare images {img_path1} and {img_path2}: {e}')
		return False


def filter_images(screenshot_paths: list[str], max_images: int) -> list[str]:
	"""
	Filter screenshot paths to:
	1. Never include the first image (always white)
	2. Remove consecutive duplicate images
	3. Return up to max_images from the end
	"""
	if not screenshot_paths:
		return []

	# Skip the first image (always white)
	filtered_paths = screenshot_paths[1:] if len(screenshot_paths) > 1 else []

	if not filtered_paths:
		return []

	# Remove consecutive duplicates
	deduplicated_paths = [filtered_paths[0]]  # Always include the first non-skipped image

	for i in range(1, len(filtered_paths)):
		current_path = filtered_paths[i]
		previous_path = filtered_paths[i - 1]

		# Only add if not identical to previous image
		if not are_images_identical(current_path, previous_path):
			deduplicated_paths.append(current_path)

	# Return last max_images images
	return deduplicated_paths[-max_images:] if len(deduplicated_paths) > max_images else deduplicated_paths


async def comprehensive_judge(
	task: str,
	complete_history: list[dict],
	final_result: str,
	last_message: str,
	screenshot_paths: list[str],
	model: BaseChatModel,
	max_images: int = 10,
) -> JudgeResult:
	"""
	Comprehensive judge that evaluates browser-use agent runs with detailed structured feedback.

	Args:
		task: The original task description
		complete_history: Full execution history with steps and results
		final_result: The final result returned to the user
		last_message: The agent's final message/output before completion
		screenshot_paths: List of screenshot file paths from execution
		model: The LLM model to use for evaluation
		max_images: Maximum number of images to include in evaluation
	"""

	# Prepare inputs with length limits
	task_truncated = truncate_text(task, 40000)
	final_result_truncated = truncate_text(final_result or 'No final result', 20000)
	last_message_truncated = truncate_text(last_message or 'No last message', 40000, from_beginning=True)
	agent_steps = prepare_agent_steps(complete_history)

	# Select and filter images
	selected_images = filter_images(screenshot_paths, max_images)

	# Encode images
	encoded_images: list[ContentPartImageParam] = []
	for img_path in selected_images:
		if Path(img_path).exists():
			encoded_img = encode_image(img_path)
			if encoded_img:
				encoded_images.append(ContentPartImageParam(image_url=ImageURL(url=f'data:image/jpeg;base64,{encoded_img}')))

	# Build error categories dynamically from enum
	error_categories_text = ', '.join([category.value for category in ErrorCategory])

	# Construct the evaluation prompt
	system_prompt = f"""You are an expert judge evaluating browser-use agent performance.

Here is context about the agent you have to evaluate:

<browser_use_agent_context>
**AGENT ARCHITECTURE UNDERSTANDING:**
The browser-use agent operates in iterative loops receiving structured input:

**AGENT INPUT (what agent sees each step):**
1. AGENT HISTORY: Chronological event stream with previous actions and results
2. AGENT STATE: User request, file system state, todo.md contents, step info  
3. BROWSER STATE: Current URL, tabs, and interactive elements in indexed format (this represents the css selector of the element), and text of the current viewport
4. BROWSER VISION: Screenshot with bounding boxes around interactive elements
5. READ STATE: Temporary data from extract_structured_data or read_file actions

**CRITICAL: BROWSER STATE CONTAINS READABLE TEXT**
- The DOM is converted to text with indexed interactive elements: [index]<type>text content</type>
- Agent sees the browser_state of the current viewport at every step without needing extract_structured_data
- extract_structured_data gets the markdown of the entire page and not just the visible part
- Instead of extract_structured_data the agent can also scroll to get more information in the browser_state 
- The browser_state is the ground truth, but can be improved if information is missing
- The agent can also read information directly from the input screenshot  

**AGENT OUTPUT FORMAT (always JSON):**
- thinking: Structured reasoning following specific patterns
- evaluation_previous_goal: Assessment of last action success/failure  
- memory: Progress tracking (1-3 sentences)
- next_goal: Clear statement of immediate objectives
- action: List of actions to execute sequentially

**EXPECTED AGENT BEHAVIORS:**
- Follows task output format requirements precisely (direct output vs file writing)
- Uses todo.md for long tasks above 20 steps
- Saves findings to results.md when the task is long multiple things need to be extracted on different pages
- Dont use file system for short tasks except required by the task
- Calls done action only when task complete or impossible to continue - not too early
- If the agent needs to repeat the same sub task multiple times & has a good trajectory, but hits the max step limit the score should be medium
- Analyse the screenshots. Each interactive element should have exactly one color bounding box. If the bounding boxes look off mention that.

</browser_use_agent_context>

**EVALUATION FRAMEWORK:**
**PRIMARY EVALUATION CRITERIA (in order of importance):**
1. **Task Satisfaction (Most Important)**: Did the agent accomplish what the user asked for? Focus on user intent and final outcome.
2. **Output Quality**: Is the final result in the correct format and complete? Does it match exactly what was requested?
3. **Tool Effectiveness**: Did the browser interactions work as expected? Were tools used appropriately? How many % of the tools failed? 
4. **Agent Reasoning**: Quality of decision-making, planning, and problem-solving throughout the trajectory. 
5. **Browser Handling**: Navigation stability, error recovery, and technical execution. If the browser crashes, does not load or a captcha blocks the task, the score must be very low.

**SCORING GUIDELINES (final_score represents % of task completion):**
- 90-100: Excellent - Task completed as requested, human-like execution
- 80-89: Very Good - Task completed with minor issues, but meets user fully requirements  
- 70-79: Good - Task completed with minor issues, core requirements satisfied
- 60-69: Partial - Some parts of task completed, but significant portions incomplete or incorrect
- 40-59: Poor - Major issues, only minor parts of task completed successfully
- 1-39: Failed - Task not completed, significant problems throughout execution
- 0: Complete failure - No meaningful progress toward task completion or completely blocked by a captcha or login

**Examples of task completion scoring:**
- If task asks for 10 items and agent finds 4 items correctly: 40
- If task completed to full user requirements but with some errors to improve in the trajectory: 85
- If task impossible due to captcha/login requirements: 0
- If we get blocked by Cloudflare challenge the final score must be 0
- If the trajectory is ideal and the output is perfect: 100


**FAILURE CONDITIONS (automatically score very low):**
- Task not completed when it should be completable
- Blocked by captcha or authentication when avoidable
- Output format completely wrong or missing
- Infinite loops or severe technical failures
- Critical user requirements ignored
- Page not loaded
- Browser crashed
- Agent could not interact with required UI elements

**ERROR CATEGORIES TO IDENTIFY:**
{error_categories_text}

**Improvement Tips (Actionable Developer Guidance):**
Format: "Error Category: Specific improvement suggestion"
Examples:
- "Login error on sheets.google.com: Build a dedicated Google Sheets login function"
- "Element not found: Improve the DOM extraction layer to correctly include buttons in the navigation bar of the website check24.de"
- "Load timeout: Implement better wait strategies for dynamic content to wait until the page is fully loaded"
- "File system misuse: The agent used the read and write file tools for short tasks even it could have outputted the information directly. Adapt the system prompt to not use the file system for short tasks."

**IMPORTANT EVALUATION NOTES:**
- **DO NOT evaluate for hallucination** - Agent has access to browser_state with the DOM and the screenshot at every step, so trust all factual claims. When ever the agent states clear output information trust it and do not include that in your evaluation. The agent is not hallucinating. It know that information.
- **Penalize poor planning** - The agent should not use the file system for short tasks.
- **Penalize poor tool usage** - Wrong tools, inefficient approaches, ignoring available information

**RESPONSE FORMAT:**
Respond with EXACTLY this JSON structure (no additional text before or after):

{{
    "task_summary": "One sentence summary of what the task was trying to accomplish",
    "reasoning": "Detailed analysis covering: what went well, what didn't work, trajectory quality assessment, tool usage evaluation, output quality review, and overall user satisfaction prediction",
    "error_categories": ["error1", "error2"],
    "final_score": 75,
    "improvement_tips": [
        "Button not clickable: Improve the DOM extraction layer to correctly include buttons in the navigation bar of the website check24.de"
    ]
}}"""

	user_prompt = f"""**TASK:** 
<task>
{task_truncated}
</task>

**AGENT TRAJECTORY:**
<agent_trajectory>
{chr(10).join(agent_steps)}
</agent_trajectory>

**AGENT'S LAST INPUT MESSAGE:**
<agent_last_input_message>
{last_message_truncated}
</agent_last_input_message>

**FINAL RESULT:**
<agent_final_result>
{final_result_truncated}
</agent_final_result>

**TOTAL STEPS:** {len(complete_history)}
**SCREENSHOTS PROVIDED:** {len(selected_images)}

Evaluate this agent execution given the criteria and respond with the exact JSON structure requested."""

	# Build messages
	content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=user_prompt)]
	content_parts.extend(encoded_images)

	messages: list[BaseMessage] = [
		SystemMessage(content=system_prompt),
		UserMessage(content=content_parts),
	]

	# Get structured response
	try:
		response = await model.ainvoke(messages, output_format=JudgeResult)
		logger.info(f'Judge response: {response}')
		return response.completion

	except Exception as e:
		logger.error(f'Judge evaluation failed: {e}')
		return create_fallback_result(task, str(e))


def parse_judge_response(result_dict: dict, task: str) -> JudgeResult:
	"""Parse the LLM response into a structured JudgeResult."""
	try:
		# Parse error categories
		error_categories = []
		if 'error_categories' in result_dict:
			for err in result_dict['error_categories']:
				try:
					error_categories.append(ErrorCategory(err))
				except ValueError:
					logger.warning(f'Unknown error category: {err}')

		final_score = result_dict.get('final_score', 0)

		return JudgeResult(
			task_summary=result_dict.get('task_summary', 'Task analysis unavailable'),
			reasoning=result_dict.get('reasoning', 'Analysis unavailable'),
			error_categories=error_categories,
			final_score=final_score,
			improvement_tips=result_dict.get('improvement_tips', []),
		)

	except Exception as e:
		logger.error(f'Failed to parse judge response: {e}')
		return create_fallback_result(task, 'Failed to parse structured response')


def create_fallback_result(task: str, error_msg: str) -> JudgeResult:
	"""Create a fallback result when evaluation fails."""
	return JudgeResult(
		task_summary=f'Failed to analyze task: {task[:100]}...',
		reasoning=f'Evaluation failed: {error_msg}',
		error_categories=[ErrorCategory.IMPOSSIBLE_TASK],
		final_score=0,
		improvement_tips=['Fix evaluation system'],
	)


async def judge_with_retry(
	task: str,
	complete_history: list[dict],
	final_result: str,
	last_message: str,
	screenshot_paths: list[str],
	model: BaseChatModel,
	max_retries: int = 3,
	max_images: int = 10,
) -> JudgeResult:
	"""
	Judge with retry logic for robustness.

	Args:
		task: The original task description
		complete_history: Full execution history with steps and results
		final_result: The final result returned to the user
		last_message: The agent's final message/output before completion
		screenshot_paths: List of screenshot file paths from execution
		model: The LLM model to use for evaluation
		max_retries: Maximum number of retry attempts
		max_images: Maximum number of images to include in evaluation
	"""
	for attempt in range(max_retries):
		try:
			return await comprehensive_judge(
				task,
				complete_history,
				final_result,
				last_message,
				screenshot_paths,
				model,
				max_images,
			)
		except Exception as e:
			if attempt == max_retries - 1:
				logger.error(f'Judge failed after {max_retries} attempts: {e}')
				return create_fallback_result(task, str(e))
			logger.warning(f'Judge attempt {attempt + 1} failed, retrying: {e}')
			await asyncio.sleep(2**attempt)

	# Fallback return (should never reach here given the logic above, but ensures type safety)
	return create_fallback_result(task, 'Max retries exceeded without proper error handling')


def _read_result_file(result_file: Path) -> dict[str, Any]:
	"""Helper function to read result file synchronously."""
	with open(result_file) as f:
		return json.load(f)


def _write_result_file(result_file: Path, result_data: dict[str, Any]) -> None:
	"""Helper function to write result file synchronously."""
	with open(result_file, 'w') as f:
		f.write(json.dumps(result_data, indent=2, default=str))


# Integration helper function
async def evaluate_task_with_comprehensive_judge(task_folder: Path, model: BaseChatModel, max_images: int = 10) -> dict[str, Any]:
	"""
	Evaluate a task result using the comprehensive judge system.

	Returns a dictionary with both the old format for compatibility
	and the new comprehensive analysis.
	"""
	result_file = task_folder / 'result.json'
	if not result_file.exists():
		return {
			'task_id': task_folder.name,
			'comprehensive_judge': None,
			'error': 'No result.json found',
		}

	try:
		# Load existing result using async wrapper
		result_data = await asyncio.to_thread(_read_result_file, result_file)

		# Check if comprehensive judge result already exists
		if result_data.get('comprehensive_judge_evaluation'):
			return {
				'task_id': task_folder.name,
				'comprehensive_judge': result_data['comprehensive_judge_evaluation'],
				'error': None,
			}

		# Extract data for evaluation
		task = result_data.get('task', 'Unknown task')
		complete_history = result_data.get('complete_history', [])
		final_result = result_data.get('final_result_response', '')
		last_message = result_data.get('last_message', '')
		screenshot_paths = result_data.get('screenshot_paths', [])

		# Run comprehensive evaluation
		judge_result = await judge_with_retry(
			task=task,
			complete_history=complete_history,
			final_result=final_result,
			last_message=last_message,
			screenshot_paths=screenshot_paths,
			model=model,
			max_images=max_images,
		)

		# Convert to dict for storage
		judge_dict = judge_result.model_dump()

		# Save back to result file using async wrapper
		result_data['comprehensive_judge_evaluation'] = judge_dict
		await asyncio.to_thread(_write_result_file, result_file, result_data)

		return {
			'task_id': task_folder.name,
			'comprehensive_judge': judge_dict,
			'error': None,
		}

	except Exception as e:
		logger.error(f'Comprehensive judge evaluation failed for {task_folder.name}: {e}')
		return {
			'task_id': task_folder.name,
			'comprehensive_judge': None,
			'error': str(e),
		}
