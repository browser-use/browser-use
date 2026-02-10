"""Planner agent - main reasoner and final action decider."""

from __future__ import annotations

import json
import logging
from typing import Any

from multiagent.agents.base import BaseAgent
from multiagent.config import AgentConfig

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
	"""Produces the final single browser-use action each step.

	Takes browser state + optional advice from Searcher/Critic and decides
	the next action in browser-use's action format.
	"""

	def __init__(self, config: AgentConfig) -> None:
		super().__init__('planner', config)

	async def plan(
		self,
		task: str,
		state_description: str,
		action_space: str,
		step_number: int,
		history_summary: str,
		searcher_summary: str | None = None,
		critic_feedback: str | None = None,
		screenshot_b64: str | None = None,
	) -> str:
		"""Generate a planning response with the next action to take.

		Returns raw LLM text that the orchestrator will parse into an action.
		"""
		parts = [
			f'## Task\n{task}',
			f'## Step {step_number}',
			f'## Current Browser State\n{state_description}',
			f'## Action History\n{history_summary}',
			f'## Available Actions\n{action_space}',
		]

		if searcher_summary:
			parts.append(f'## Searcher Intelligence\n{searcher_summary}')

		if critic_feedback:
			parts.append(f'## Critic Feedback\n{critic_feedback}')

		parts.append(
			'## Instructions\n'
			'Analyze the current state and decide on exactly ONE action to take.\n'
			'Respond with a JSON object containing:\n'
			'- "thinking": your reasoning about what to do\n'
			'- "action": the action name (from available actions)\n'
			'- "params": the action parameters as a dict\n'
			'- "is_done": true if the task is complete, false otherwise\n'
			'- "success": true/false (only when is_done is true)\n'
			'- "extracted_content": any content extracted (only when is_done is true)'
		)

		user_msg = '\n\n'.join(parts)

		images = None
		if screenshot_b64:
			images = [{'url': f'data:image/png;base64,{screenshot_b64}'}]

		return await self.invoke(user_msg, images=images)
