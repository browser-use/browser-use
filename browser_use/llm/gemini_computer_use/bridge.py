"""Bridge between Gemini Computer Use function calls and Browser Use Agent.

This module allows Browser Use Agent to:
1. Keep enable_computer_use=True for Gemini's native capabilities
2. Intercept Computer Use function calls
3. Execute them via Actor API
4. Continue the agent loop
"""

import logging
from typing import TYPE_CHECKING, Any

from browser_use.agent.views import ActionResult
from browser_use.llm.gemini_computer_use.executor import ComputerUseActionExecutor

if TYPE_CHECKING:
	from browser_use.actor import Page


class ComputerUseBridge:
	"""Bridges Computer Use function calls to Browser Use Agent actions.

	When enable_computer_use=True, Gemini returns function calls like:
	- click_at(x=500, y=300)
	- navigate(url="...")
	- type_text_at(x=500, y=400, text="query")

	This bridge:
	1. Detects these function calls in LLM responses
	2. Executes them via Actor API using ComputerUseActionExecutor
	3. Returns ActionResult for Browser Use Agent to continue
	"""

	def __init__(self, screen_width: int = 1440, screen_height: int = 900):
		"""Initialize the bridge.

		Args:
			screen_width: Browser viewport width
			screen_height: Browser viewport height

		"""
		self.executor = ComputerUseActionExecutor(screen_width, screen_height)
		self.logger = logging.getLogger('browser_use.computer_use_bridge')

	async def execute_function_calls(self, function_calls: list[Any], page: 'Page') -> list[ActionResult]:
		"""Execute Computer Use function calls via Actor API.

		Args:
			function_calls: List of function call objects from Gemini response
			page: Actor Page instance

		Returns:
			List of ActionResult objects for Browser Use Agent

		"""
		results = []

		for fc in function_calls:
			self.logger.info(f'🖱️  Executing Computer Use action: {fc.name}')

			# Execute via Actor API
			execution_result = await self.executor.execute_function_call(fc, page)

			# Convert to ActionResult
			if 'error' in execution_result:
				result = ActionResult(error=execution_result['error'], extracted_content=None, include_in_memory=True)
			elif execution_result.get('status') == 'done':
				# Done action - mark as completed
				message = execution_result.get('message', 'Task completed')
				result = ActionResult(
					error=None,
					extracted_content=f'Done: {message}',
					include_in_memory=True,
					is_done=True,  # Signal completion
				)
			elif execution_result.get('status') == 'success' and execution_result.get('message'):
				# Actions with detailed message (like get_browser_state)
				result = ActionResult(error=None, extracted_content=execution_result['message'], include_in_memory=True)
			else:
				# Generic success
				url = await page.get_url()

				result = ActionResult(
					error=None, extracted_content=f'Executed {fc.name} successfully. Current URL: {url}', include_in_memory=True
				)

			results.append(result)

		return results

	@staticmethod
	def has_computer_use_function_calls(response: Any) -> bool:
		"""Check if LLM response contains Computer Use function calls.

		Args:
			response: Response from ChatGeminiComputerUse.ainvoke()

		Returns:
			True if response contains function calls

		"""
		# This is a placeholder - actual implementation depends on response structure
		# You'd check if the response has function_calls attribute or similar
		return hasattr(response, 'function_calls') and bool(response.function_calls)

	@staticmethod
	def extract_function_calls(response: Any) -> list[Any]:
		"""Extract function calls from LLM response.

		Args:
			response: Response from ChatGeminiComputerUse.ainvoke()

		Returns:
			List of function call objects

		"""
		# This is a placeholder - actual implementation depends on response structure
		if hasattr(response, 'function_calls'):
			return response.function_calls
		return []


def create_computer_use_action_handler(screen_width: int = 1440, screen_height: int = 900) -> ComputerUseBridge:
	"""Factory function to create a Computer Use bridge for Browser Use Agent.

	Usage in Browser Use Agent:
	```python
	from browser_use.llm.gemini_computer_use.browser_use_bridge import create_computer_use_action_handler

	# In agent initialization
	computer_use_handler = create_computer_use_action_handler()

	# In agent loop, after getting LLM response
	if computer_use_handler.has_computer_use_function_calls(response):
	    # Execute Computer Use actions via Actor API
	    results = await computer_use_handler.execute_function_calls(computer_use_handler.extract_function_calls(response), page)
	    # Continue with results
	```

	Args:
		screen_width: Browser viewport width
		screen_height: Browser viewport height

	Returns:
		ComputerUseBridge instance

	"""
	return ComputerUseBridge(screen_width, screen_height)
