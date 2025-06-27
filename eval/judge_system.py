"""
@file purpose: Comprehensive judge system for evaluating browser-use agent runs with detailed structured feedback.
"""

import asyncio
import base64
import io
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from PIL import Image

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


@dataclass
class ScoreBreakdown:
	trajectory_quality: int  # How human-like is the solution path (1-100)
	tool_calling_effectiveness: int  # How well do tools work (1-100)
	agent_reasoning: int  # Quality of agent's decision making (1-100)
	browser_handling: int  # Browser stability and error handling (1-100)
	task_satisfaction: int  # Final user satisfaction (1-100)


@dataclass
class JudgeResult:
	# Basic Information
	task_summary: str  # 1 sentence summary
	task_clarity_score: int  # How clear vs uncertain the task is (1-100)
	task_categories: list[TaskCategory]  # Primary task categories

	# Analysis
	reasoning: str  # What went well/not well analysis
	error_categories: list[ErrorCategory]  # Core error categories identified

	# Scores
	scores: ScoreBreakdown
	final_score: int  # Overall score (1-100)
	passed: bool  # Whether it meets 70% threshold

	# Developer Feedback
	improvement_tips: list[str]  # Concrete improvement suggestions
	critical_issues: list[str]  # Must-fix issues

	# Metadata
	evaluation_timestamp: str


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
					step_text += f'Actions: {json.dumps(model_output["action"], indent=1)[:500]}...[cut for eval system]\n'
				# if 'current_state' in model_output:
				# step_text += f'State: {model_output["current_state"]}\n'

		# Add results if available
		if step.get('result'):
			for j, result in enumerate(step['result']):
				if isinstance(result, dict):
					if result.get('extracted_content'):
						step_text += f'Result {j + 1}: {result["extracted_content"][:500]}...[cut for eval system]\n'
					if result.get('error'):
						step_text += f'Error {j + 1}: {result["error"][:500]}...[cut for eval system]\n'

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
- Reasons explicitly about browser state, history, and progress
- Calls done action only when task complete or impossible to continue - not too early
- If the agent needs to repeat the same sub task multiple times & has a good trajectory, but hits the max step limit its still very good and can pass the evaluation
- Analyse the screenshots. Each interactive element should have exactly one color bounding box. 

**EVALUATION CRITERIA:**
1. **Task Satisfaction**: Understand the user intent - Is the user satisfied with the final result? - This is the most important criterion.
2. **Tool Usage**: How well did the tools work? -Do they work as expected?
3. **Agent Reasoning**: Quality of decision-making and problem-solving - good todo.md usage for tasks above 20 steps?
4. **Browser Handling**: How well did the navigation and browser interaction work - are there many blocks or 404s?
5. **Final Output**: How does the output presented is it exactly what the user asked for? If there is no output the score must be low.
6. If we get blocked by a captcha or if the task is impossible, we should not pass the evaluation. The score must be low.
7. If the trajectory is bad and tools are used in a stupid way, reduce the score.
8. If the agent is not able to complete the task, the score must be low.
9. If the trajectory can be optimized deduct points.


**ERROR CATEGORIES TO CONSIDER:**
{error_categories_text}

**TASK CATEGORIES TO CONSIDER:**
extraction, interaction, login, research, shopping, booking, comparison, qa_testing, form_filling, navigation, search, filtering, content_creation, file_operations, multi_step_workflow
- You can use multiple categories for the same task.
- You can also add other categories if they fit better.

**TASK CLARITY SCORE:**
- is the task very clear step by step like a recipe (high score) or very vague and uncertain (low score)

**CRITICAL ISSUES:**
- What's the core thing why the task failed? - What are the most important things to fix?

**IMPROVEMENT TIPS:**
- Create actionable tips for browser-use agent developers to fix common issues 
- Make the tips easy understandable for a developer 
- Tips will be aggregated across tasks to identify the most problematic patterns
- Consider improvements to: system prompt, browser_state representation, action handling, not working tools, waiting and other error categories,  output format
- Always mention the error first this would fix, then the specific improvement suggestion. Like Login error on sheets.google.com: build a login function for google sheets
- If errors are related to specific websites please meention the link in the improvement  


**SCORING SCALE:**
- 90-100: Excellent execution, human-like, minimal issues
- 80-89: Good execution with minor issues
- 70-79: Acceptable execution, some problems but functional
- 60-69: Poor execution with significant issues
- 1-59: Failed execution, major problems

**PASS THRESHOLD: 70%**

**IMPORTANT: DO NOT EVALUATE FOR HALLUCINATION**
The agent has access at every step to browser_state so it has more information than you can see. If the agent states something as fact or provides specific data, assume it is correct. Focus on evaluating trajectory quality, tool usage, and task completion rather than data accuracy.

Respond with EXACTLY this JSON structure (no additional text):

{{
    "task_summary": "One sentence summary of what the task was trying to accomplish",
    "task_categories": ["category1", "category2"],
    "task_clarity_score": 85,
    "reasoning": "Detailed analysis of what went well and what didn't, trajectory quality, planning assessment, output quality, user satisfaction",
    "error_categories": ["error1", "error2"],
    "scores": {{
        "task_satisfaction": 70
        "tool_calling_effectiveness": 80,
        "agent_reasoning": 85,
        "browser_handling": 65,
        "trajectory_quality": 75,
    }},
    "final_score": 75,
    "critical_issues": [
        "Critical issue that must be fixed 1",
        "Critical issue that must be fixed 2"
    ],
    "improvement_tips": [
        "Error1: Specific actionable improvement 1",
        "Error2: Specific actionable improvement 2"
    ]
}}"""

	user_prompt = f"""**TASK:** {task_truncated}

**AGENT TRAJECTORY:**
{chr(10).join(agent_steps)}

**AGENT'S LAST INPUT MESSAGE:**
{last_message_truncated}

**FINAL RESULT:**
{final_result_truncated}

**TOTAL STEPS:** {len(complete_history)}
**SCREENSHOTS PROVIDED:** {len(selected_images)}

Evaluate this execution and respond with the exact JSON structure requested."""

	# Build messages
	content_parts: list[ContentPartTextParam | ContentPartImageParam] = [ContentPartTextParam(text=user_prompt)]
	content_parts.extend(encoded_images)

	messages: list[BaseMessage] = [
		SystemMessage(content=system_prompt),
		UserMessage(content=content_parts),
	]

	# Get structured response
	try:
		response = await model.ainvoke(messages)

		# Parse the JSON response
		# Handle both string and list content types
		response_text = response.completion
		response_text = response_text.strip()

		# Try to extract JSON if wrapped in markdown
		if '```json' in response_text:
			json_start = response_text.find('```json') + 7
			json_end = response_text.find('```', json_start)
			if json_end != -1:
				response_text = response_text[json_start:json_end].strip()
		elif '```' in response_text:
			json_start = response_text.find('```') + 3
			json_end = response_text.find('```', json_start)
			if json_end != -1:
				response_text = response_text[json_start:json_end].strip()

		# Parse JSON
		try:
			result_dict = json.loads(response_text)
		except json.JSONDecodeError as e:
			logger.error(f'Failed to parse JSON response: {e}')
			logger.error(f'Response text: {response_text}')
			# Create fallback result
			return create_fallback_result(task, 'Failed to parse judge response')

		# Convert to structured result
		return parse_judge_response(result_dict, task)

	except Exception as e:
		logger.error(f'Judge evaluation failed: {e}')
		return create_fallback_result(task, str(e))


def parse_judge_response(result_dict: dict, task: str) -> JudgeResult:
	"""Parse the LLM response into a structured JudgeResult."""
	try:
		# Parse task categories
		task_categories = []
		if 'task_categories' in result_dict:
			for cat in result_dict['task_categories']:
				try:
					task_categories.append(TaskCategory(cat))
				except ValueError:
					logger.warning(f'Unknown task category: {cat}')

		# Parse error categories
		error_categories = []
		if 'error_categories' in result_dict:
			for err in result_dict['error_categories']:
				try:
					error_categories.append(ErrorCategory(err))
				except ValueError:
					logger.warning(f'Unknown error category: {err}')

		# Parse scores
		scores_dict = result_dict.get('scores', {})
		scores = ScoreBreakdown(
			trajectory_quality=scores_dict.get('trajectory_quality', 50),
			tool_calling_effectiveness=scores_dict.get('tool_calling_effectiveness', 50),
			agent_reasoning=scores_dict.get('agent_reasoning', 50),
			browser_handling=scores_dict.get('browser_handling', 50),
			task_satisfaction=scores_dict.get('task_satisfaction', 50),
		)

		final_score = result_dict.get('final_score', 50)

		return JudgeResult(
			task_summary=result_dict.get('task_summary', 'Task analysis unavailable'),
			task_clarity_score=result_dict.get('task_clarity_score', 50),
			task_categories=task_categories,
			reasoning=result_dict.get('reasoning', 'Analysis unavailable'),
			error_categories=error_categories,
			scores=scores,
			final_score=final_score,
			passed=final_score >= 70,
			improvement_tips=result_dict.get('improvement_tips', []),
			critical_issues=result_dict.get('critical_issues', []),
			evaluation_timestamp=datetime.now().isoformat(),
		)

	except Exception as e:
		logger.error(f'Failed to parse judge response: {e}')
		return create_fallback_result(task, 'Failed to parse structured response')


def create_fallback_result(task: str, error_msg: str) -> JudgeResult:
	"""Create a fallback result when evaluation fails."""
	return JudgeResult(
		task_summary=f'Failed to analyze task: {task[:100]}...',
		task_clarity_score=0,
		task_categories=[TaskCategory.QA_TESTING],
		reasoning=f'Evaluation failed: {error_msg}',
		error_categories=[ErrorCategory.IMPOSSIBLE_TASK],
		scores=ScoreBreakdown(
			trajectory_quality=0,
			tool_calling_effectiveness=0,
			agent_reasoning=0,
			browser_handling=0,
			task_satisfaction=0,
		),
		final_score=0,
		passed=False,
		improvement_tips=['Fix evaluation system'],
		critical_issues=[f'Evaluation system failure: {error_msg}'],
		evaluation_timestamp=datetime.now().isoformat(),
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


def get_example_json_structure() -> dict:
	"""Get an example of the expected JSON response structure for the LLM judge."""
	return {
		'task_summary': 'Extract product prices from an e-commerce website',
		'task_clarity_score': 85,
		'task_categories': ['extraction', 'research'],
		'reasoning': 'The agent successfully navigated to the target website and extracted most product information. However, it had difficulty with dynamic loading elements and missed some prices that loaded asynchronously. The overall approach was logical but could benefit from better wait strategies.',
		'error_categories': ['element_not_found', 'load_timeout'],
		'scores': {
			'trajectory_quality': 75,
			'tool_calling_effectiveness': 80,
			'agent_reasoning': 85,
			'browser_handling': 65,
			'task_satisfaction': 70,
		},
		'final_score': 75,
		'critical_issues': [
			'Missing wait for dynamic content to load',
			'No fallback strategy when primary selectors fail',
		],
		'improvement_tips': [
			'Browser not loaded: Implement better wait strategies for dynamic content',
			'Element not found: Add retry logic for element detection',
			'No error message: Improve error handling for the tool click element',
		],
	}


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
		judge_dict = asdict(judge_result)

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
