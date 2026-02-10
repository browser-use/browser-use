"""Multi-agent orchestrator that wraps the browser-use Agent step loop.

Design:
- Creates and owns a real browser-use Agent for browser interaction.
- Before each Agent step, consults advisory agents (Planner/Searcher/Critic).
- Injects advisory context into the Agent's message history via on_step_start hook.
- Delegates actual browser action execution entirely to browser-use Agent.
- Returns the same AgentHistoryList as Agent.run().
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList, AgentHistory, ActionResult
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateHistory

from multiagent.agents.planner import PlannerAgent
from multiagent.agents.searcher import SearcherAgent
from multiagent.agents.critic import CriticAgent
from multiagent.config import MultiAgentConfig, load_config
from multiagent.logging import RunLogger

logger = logging.getLogger('multiagent.orchestrator')


class MultiAgentOrchestrator:
	"""Planner-centric orchestrator: one environment step -> one action.

	For each browser-use step:
	1. Get browser state via browser-use Agent internals.
	2. Optionally invoke Searcher (first step, stuck, or loop).
	3. Ask Planner for the action (with Searcher intel if any).
	4. Ask Critic to review (always in v1).
	5. Execute the action via the real browser-use Agent step.
	6. Log everything.
	"""

	def __init__(
		self,
		task: str,
		config: MultiAgentConfig,
		config_path: str | Path | None = None,
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
	) -> None:
		self.task = task
		self.config = config
		self.run_logger = RunLogger(config, config_path)

		# Build advisory agents from config
		self.planner: PlannerAgent | None = None
		self.searcher: SearcherAgent | None = None
		self.critic: CriticAgent | None = None
		self._init_agents()

		# Browser-use agent (the real executor)
		self.browser_profile = browser_profile or BrowserProfile()
		self.browser_session = browser_session

		# State tracking
		self.recent_actions: deque[str] = deque(maxlen=self.config.orchestrator.loop_detection_window)
		self.critic_reject_count: int = 0
		self.step_number: int = 0

	def _init_agents(self) -> None:
		"""Initialize advisory agents from config."""
		for name, agent_cfg in self.config.agents.items():
			if not agent_cfg.enabled:
				continue
			if name == 'planner':
				self.planner = PlannerAgent(agent_cfg)
			elif name == 'searcher':
				self.searcher = SearcherAgent(agent_cfg)
			elif name == 'critic':
				self.critic = CriticAgent(agent_cfg)
			else:
				logger.warning(f'Unknown agent type in config: {name!r}, skipping')

		assert self.planner is not None, 'Planner agent must be enabled'

	def _detect_loop(self) -> bool:
		"""Check if recent actions suggest the agent is stuck in a loop."""
		if len(self.recent_actions) < self.config.orchestrator.loop_detection_threshold:
			return False

		# Check if the last N actions are all identical
		threshold = self.config.orchestrator.loop_detection_threshold
		recent = list(self.recent_actions)[-threshold:]
		return len(set(recent)) == 1

	def _build_history_summary(self, agent: Agent) -> str:
		"""Build a concise summary of recent action history."""
		if not agent.history.history:
			return 'No actions taken yet.'

		lines = []
		for i, item in enumerate(agent.history.history[-5:]):  # Last 5 steps
			if item.model_output and item.model_output.action:
				for action in item.model_output.action:
					action_dict = action.model_dump(exclude_none=True, exclude_unset=True)
					lines.append(f'Step {i}: {json.dumps(action_dict, default=str)[:200]}')
			if item.result:
				for r in item.result:
					if r.error:
						lines.append(f'  -> Error: {r.error[:100]}')
					elif r.extracted_content:
						lines.append(f'  -> Content: {r.extracted_content[:100]}')
					elif r.is_done:
						lines.append(f'  -> Done (success={r.success})')

		return '\n'.join(lines) if lines else 'No action history available.'

	def _build_state_description(self, agent: Agent) -> str:
		"""Build a text description of current browser state for advisory agents."""
		session = agent.browser_session
		if session is None:
			return 'Browser session not available.'

		parts = []
		# Use cached state from the agent if available
		state = agent.state
		if state.last_model_output:
			if state.last_model_output.next_goal:
				parts.append(f'Current goal: {state.last_model_output.next_goal}')
			if state.last_model_output.memory:
				parts.append(f'Agent memory: {state.last_model_output.memory}')

		if state.last_result:
			last = state.last_result[-1]
			if last.error:
				parts.append(f'Last action error: {last.error}')
			elif last.extracted_content:
				parts.append(f'Last extracted: {last.extracted_content[:300]}')

		return '\n'.join(parts) if parts else 'Initial state - no actions taken yet.'

	def _get_action_space(self, agent: Agent) -> str:
		"""Get description of available actions."""
		if agent.tools and agent.tools.registry:
			return agent.tools.registry.get_prompt_description()
		return 'Standard browser-use actions: click, type, scroll, navigate, search, done, etc.'

	def _get_screenshot_b64(self, agent: Agent) -> str | None:
		"""Extract the last screenshot from agent history."""
		if agent.history.history:
			last_state = agent.history.history[-1].state
			if last_state and last_state.screenshot_path:
				try:
					import base64
					path = Path(last_state.screenshot_path)
					if path.exists():
						return base64.b64encode(path.read_bytes()).decode()
				except Exception:
					pass
		return None

	async def run(self) -> AgentHistoryList:
		"""Execute the task through multi-agent orchestration.

		Returns the same AgentHistoryList type as Agent.run().
		"""
		from multiagent.providers.base import create_llm_from_config

		# Create the underlying browser-use Agent with the planner's LLM
		planner_llm = create_llm_from_config(self.config.agents['planner'].provider)

		agent = Agent(
			task=self.task,
			llm=planner_llm,
			browser_profile=self.browser_profile,
			browser_session=self.browser_session,
			max_actions_per_step=1,  # One action per step for multi-agent control
		)

		max_steps = self.config.orchestrator.max_steps

		logger.info(f'Starting multi-agent orchestration for task: {self.task[:100]}')
		logger.info(f'Max steps: {max_steps}, Run dir: {self.run_logger.run_dir}')

		# Advisory context to inject into agent steps
		self._advisory_context: str | None = None

		async def on_step_start(agent_ref: Agent) -> None:
			"""Hook called before each Agent step - consult advisory agents."""
			self.step_number = agent_ref.state.n_steps

			state_desc = self._build_state_description(agent_ref)
			history_summary = self._build_history_summary(agent_ref)
			action_space = self._get_action_space(agent_ref)
			screenshot = self._get_screenshot_b64(agent_ref)
			loop_detected = self._detect_loop()

			# Log step inputs
			step_inputs: dict[str, Any] = {
				'step': self.step_number,
				'state': state_desc[:500],
				'loop_detected': loop_detected,
			}

			searcher_summary: str | None = None
			critic_feedback: str | None = None
			searcher_used = False

			# --- Searcher ---
			should_search = (
				self.searcher is not None
				and self.searcher.config.enabled
				and (
					(self.step_number == 1 and self.config.orchestrator.searcher_on_first_step)
					or loop_detected
				)
			)

			if should_search:
				assert self.searcher is not None
				searcher_used = True
				try:
					searcher_summary = await self.searcher.gather_info(
						task=self.task,
						state_description=state_desc,
						step_number=self.step_number,
						history_summary=history_summary,
					)
					logger.info(f'Step {self.step_number}: Searcher returned {len(searcher_summary)} chars')
				except Exception as e:
					logger.error(f'Step {self.step_number}: Searcher failed: {e}')
					searcher_summary = f'Searcher error: {e}'

			# --- Planner (pre-step advisory) ---
			planner_response: str | None = None
			if self.planner is not None:
				try:
					planner_response = await self.planner.plan(
						task=self.task,
						state_description=state_desc,
						action_space=action_space,
						step_number=self.step_number,
						history_summary=history_summary,
						searcher_summary=searcher_summary,
						screenshot_b64=screenshot,
					)
					logger.info(f'Step {self.step_number}: Planner responded ({len(planner_response)} chars)')
				except Exception as e:
					logger.error(f'Step {self.step_number}: Planner failed: {e}')

			# --- Critic ---
			critic_verdict_str: str | None = None
			if (
				self.critic is not None
				and self.critic.config.enabled
				and self.config.orchestrator.always_use_critic
				and planner_response
			):
				try:
					verdict = await self.critic.critique(
						task=self.task,
						state_description=state_desc,
						planner_response=planner_response,
						step_number=self.step_number,
						history_summary=history_summary,
						loop_detected=loop_detected,
						screenshot_b64=screenshot,
					)
					critic_feedback = verdict.feedback
					critic_verdict_str = verdict.verdict

					if verdict.should_abort:
						self.critic_reject_count += 1
						logger.warning(
							f'Step {self.step_number}: Critic recommends ABORT '
							f'({self.critic_reject_count}/{self.config.orchestrator.abort_on_critic_reject_count}): '
							f'{verdict.abort_reason}'
						)
						if self.critic_reject_count >= self.config.orchestrator.abort_on_critic_reject_count:
							logger.error('Critic abort threshold reached, stopping agent')
							agent_ref.state.stopped = True
					elif verdict.should_revise:
						logger.info(f'Step {self.step_number}: Critic suggests revision: {verdict.revision}')
					else:
						logger.info(f'Step {self.step_number}: Critic approved')

				except Exception as e:
					logger.error(f'Step {self.step_number}: Critic failed: {e}')

			# Build advisory context to inject
			advisory_parts = []
			if searcher_summary:
				advisory_parts.append(f'[Searcher Intel]\n{searcher_summary}')
			if planner_response:
				advisory_parts.append(f'[Planner Guidance]\n{planner_response}')
			if critic_feedback:
				advisory_parts.append(f'[Critic Feedback ({critic_verdict_str})]\n{critic_feedback}')

			self._advisory_context = '\n\n'.join(advisory_parts) if advisory_parts else None

			# Log step data
			self.run_logger.log_step(
				step_number=self.step_number,
				agent_inputs=step_inputs,
				agent_outputs={
					'searcher': searcher_summary[:500] if searcher_summary else None,
					'planner': planner_response[:500] if planner_response else None,
					'critic': critic_feedback[:500] if critic_feedback else None,
				},
				loop_detected=loop_detected,
				critic_verdict=critic_verdict_str,
				searcher_used=searcher_used,
			)

		async def on_step_end(agent_ref: Agent) -> None:
			"""Hook called after each Agent step - record action for loop detection."""
			if agent_ref.history.history:
				last_item = agent_ref.history.history[-1]
				if last_item.model_output and last_item.model_output.action:
					action_repr = json.dumps(
						last_item.model_output.action[0].model_dump(exclude_none=True, exclude_unset=True),
						default=str,
					)[:200]
					self.recent_actions.append(action_repr)

				# Update step log with action outcome
				outcome: dict[str, Any] = {}
				if last_item.result:
					last_result = last_item.result[-1]
					outcome = {
						'is_done': last_result.is_done,
						'success': last_result.success,
						'error': last_result.error,
						'extracted_content': last_result.extracted_content[:200] if last_result.extracted_content else None,
					}

				chosen_action: dict[str, Any] = {}
				if last_item.model_output and last_item.model_output.action:
					chosen_action = last_item.model_output.action[0].model_dump(
						exclude_none=True, exclude_unset=True
					)

				self.run_logger.log_step(
					step_number=self.step_number,
					action_outcome=outcome,
					chosen_action=chosen_action,
				)

				# Save screenshot artifact if configured
				if self.config.logging.save_screenshots and last_item.state and last_item.state.screenshot_path:
					try:
						src = Path(last_item.state.screenshot_path)
						if src.exists():
							self.run_logger.save_artifact(
								f'screenshot_{src.name}',
								src.read_bytes(),
								step=self.step_number,
							)
					except Exception:
						pass

		try:
			result: AgentHistoryList = await agent.run(
				max_steps=max_steps,
				on_step_start=on_step_start,
				on_step_end=on_step_end,
			)

			# Save run summary
			self.run_logger.log_summary({
				'task': self.task,
				'total_steps': len(result.history),
				'is_done': result.is_done(),
				'is_successful': result.is_successful(),
				'final_result': result.final_result(),
				'errors': result.errors(),
				'planner_calls': self.planner.call_count if self.planner else 0,
				'searcher_calls': self.searcher.call_count if self.searcher else 0,
				'critic_calls': self.critic.call_count if self.critic else 0,
				'critic_reject_count': self.critic_reject_count,
			})

			logger.info(
				f'Multi-agent run complete: {len(result.history)} steps, '
				f'done={result.is_done()}, success={result.is_successful()}'
			)
			logger.info(f'Logs saved to: {self.run_logger.run_dir}')

			return result

		except Exception as e:
			logger.error(f'Multi-agent orchestration failed: {e}', exc_info=True)
			self.run_logger.log_summary({
				'task': self.task,
				'error': str(e),
				'total_steps': self.step_number,
			})
			raise


async def run_multiagent(
	task: str,
	config_path: str | Path,
	browser_profile: BrowserProfile | None = None,
	browser_session: BrowserSession | None = None,
) -> AgentHistoryList:
	"""Convenience function to run a multi-agent task.

	Returns the same AgentHistoryList as single-agent Agent.run().
	"""
	config = load_config(config_path)
	orchestrator = MultiAgentOrchestrator(
		task=task,
		config=config,
		config_path=config_path,
		browser_profile=browser_profile,
		browser_session=browser_session,
	)
	return await orchestrator.run()
