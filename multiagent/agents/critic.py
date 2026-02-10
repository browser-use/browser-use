"""Critic/Verifier agent - reviews state and planner decisions."""

from __future__ import annotations

import logging
from typing import Any

from multiagent.agents.base import BaseAgent
from multiagent.config import AgentConfig

logger = logging.getLogger(__name__)

VERDICT_APPROVE = 'approve'
VERDICT_REVISE = 'revise'
VERDICT_ABORT = 'abort'


class CriticAgent(BaseAgent):
	"""Reviews state + planner draft; detects loops/failures; proposes fixes or abort."""

	def __init__(self, config: AgentConfig) -> None:
		super().__init__('critic', config)

	async def critique(
		self,
		task: str,
		state_description: str,
		planner_response: str,
		step_number: int,
		history_summary: str,
		loop_detected: bool = False,
		screenshot_b64: str | None = None,
	) -> CriticVerdict:
		"""Review the planner's proposed action and provide feedback.

		Returns a CriticVerdict with verdict, feedback, and optional revision.
		"""
		parts = [
			f'## Task\n{task}',
			f'## Step {step_number}',
			f'## Current Browser State\n{state_description}',
			f'## Recent History\n{history_summary}',
			f'## Planner Proposed Action\n{planner_response}',
		]

		if loop_detected:
			parts.append(
				'## WARNING: Loop Detected\n'
				'The agent appears to be repeating the same actions. '
				'Consider recommending a different approach or aborting.'
			)

		parts.append(
			'## Instructions\n'
			'Review the planner\'s proposed action and respond with a JSON object:\n'
			'- "verdict": one of "approve", "revise", or "abort"\n'
			'- "feedback": your analysis and reasoning\n'
			'- "revision": if verdict is "revise", suggest what action to take instead\n'
			'- "abort_reason": if verdict is "abort", explain why the task should stop'
		)

		user_msg = '\n\n'.join(parts)

		images = None
		if screenshot_b64:
			images = [{'url': f'data:image/png;base64,{screenshot_b64}'}]

		response = await self.invoke(user_msg, images=images)
		return CriticVerdict.parse_response(response)


class CriticVerdict:
	"""Parsed verdict from the Critic agent."""

	def __init__(
		self,
		verdict: str,
		feedback: str,
		revision: str | None = None,
		abort_reason: str | None = None,
		raw_response: str = '',
	) -> None:
		self.verdict = verdict
		self.feedback = feedback
		self.revision = revision
		self.abort_reason = abort_reason
		self.raw_response = raw_response

	@staticmethod
	def parse_response(response: str) -> 'CriticVerdict':
		"""Parse the critic's response, tolerant of non-JSON responses."""
		import json

		try:
			# Try to extract JSON from the response
			start = response.find('{')
			end = response.rfind('}') + 1
			if start >= 0 and end > start:
				data = json.loads(response[start:end])
				return CriticVerdict(
					verdict=data.get('verdict', VERDICT_APPROVE),
					feedback=data.get('feedback', response),
					revision=data.get('revision'),
					abort_reason=data.get('abort_reason'),
					raw_response=response,
				)
		except (json.JSONDecodeError, KeyError):
			pass

		# Fallback: treat entire response as feedback, default approve
		verdict = VERDICT_APPROVE
		lower = response.lower()
		if 'abort' in lower:
			verdict = VERDICT_ABORT
		elif 'revise' in lower or 'revision' in lower or 'instead' in lower:
			verdict = VERDICT_REVISE

		return CriticVerdict(
			verdict=verdict,
			feedback=response,
			raw_response=response,
		)

	@property
	def should_abort(self) -> bool:
		return self.verdict == VERDICT_ABORT

	@property
	def should_revise(self) -> bool:
		return self.verdict == VERDICT_REVISE

	@property
	def approved(self) -> bool:
		return self.verdict == VERDICT_APPROVE
