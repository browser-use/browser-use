"""Experimental Jev policies. Disabled agents follow the unmodified native path."""

import asyncio
import time
from typing import Any

from browser_use.agent.jev_client import JevClient
from browser_use.agent.views import AgentOutput


class JevPolicy:
	def __init__(self, mode: str, log_path: str | None):
		if mode not in {'actions', 'vision', 'compact', 'model', 'model_static'}:
			raise ValueError('jev_mode must be actions, vision, compact, model, model_static, or None')
		self.mode = mode
		self.client = JevClient(log_path=log_path)
		self.browser_state: Any = None
		self.previous_results: Any = None
		self.previous_output: Any = None
		self.parent_calls = 0
		self.fast_actions = 0
		self.transformed_calls = 0
		self.router = None
		self.model_router = None
		self.use_mini = False
		self.mini_llm = None
		self.mini_calls = 0
		self.mini_unknown_cost_calls = 0
		self.mini_final_verifications = 0
		self.last_mini_step = None
		self.full_calls = 0
		if mode == 'actions':
			from browser_use.agent.jev_actions import JevActionRouter

			self.router = JevActionRouter(self.client)

		if mode in {'model', 'model_static'}:
			from browser_use.agent.jev_model import JevModelRouter

			self.model_router = JevModelRouter(self.client)

	async def prepare(self, agent, messages):
		"""Choose one native action or prepare a temporary parent-model observation."""
		self.use_mini = False
		force_full = any(result.error for result in self.previous_results or [])
		force_full = force_full or bool(
			self.previous_output
			and any('screenshot' in action.model_dump(exclude_none=True) for action in self.previous_output.action)
		)
		# Never suppress observations when the runtime is forcing a final answer.
		force_full = force_full or agent.AgentOutput is agent.DoneAgentOutput
		force_full = force_full or agent.state.loop_detector.consecutive_stagnant_pages >= 2
		force_full = force_full or agent.state.n_steps % 4 == 0
		force_full = force_full or self.last_mini_step == agent.state.n_steps
		try:
			if self.model_router is not None:
				self.use_mini = await self.model_router.choose_mini(
					agent,
					messages,
					previous_results=self.previous_results,
					force_full=force_full,
					static=self.mode == 'model_static',
				)
				return None, messages
			if self.router and not force_full:
				output = await self.router.try_action(agent, self.browser_state, previous_results=self.previous_results)
				if output is not None:
					self.fast_actions += 1
					self.client.record(
						{
							'event': 'fast_action',
							'step': agent.state.n_steps,
							'actions': [a.model_dump(exclude_none=True) for a in output.action],
						}
					)
					return output, messages
			elif self.mode in {'vision', 'compact'}:
				from browser_use.agent.jev_observation import apply_jev_compact, apply_jev_vision

				transform = apply_jev_vision if self.mode == 'vision' else apply_jev_compact
				updated = await transform(messages, self.client, force_full=force_full)
				if updated != messages:
					self.transformed_calls += 1
				self.client.record(
					{
						'event': 'observation',
						'step': agent.state.n_steps,
						'before': observation_size(messages),
						'after': observation_size(updated),
						'changed': updated != messages,
					}
				)
				return None, updated
		except Exception as exc:
			# No browser mutation has happened. Cancellation (BaseException) propagates.
			self.client.record({'event': 'fallback', 'step': agent.state.n_steps, 'error': type(exc).__name__})
		self.client.record(
			{
				'event': 'route',
				'step': agent.state.n_steps,
				'reason': self.router.last_route_reason if self.router else 'full_context',
			}
		)
		return None, messages

	async def invoke(self, agent, messages, kwargs):
		"""Use a bounded mini call, with native BU2 recovery and final verification."""
		from browser_use.llm.browser_use.chat import ChatBrowserUse

		if (
			not self.use_mini
			or self.last_mini_step == agent.state.n_steps
			or not isinstance(agent.llm, ChatBrowserUse)
			or agent.llm.model != 'bu-2-0'
		):
			self.full_calls += 1
			return await agent.llm.ainvoke(messages, **kwargs)
		if self.mini_llm is None:
			self.mini_llm = ChatBrowserUse(
				model='bu-2-0-mini-preview',
				api_key=agent.llm.api_key,
				base_url=agent.llm.base_url,
				timeout=20,
				max_retries=1,
			)
			self.mini_llm.fast = agent.llm.fast
			agent.token_cost_service.register_llm(self.mini_llm)
		self.last_mini_step = agent.state.n_steps
		self.mini_calls += 1
		self.mini_unknown_cost_calls += 1
		started = time.monotonic()
		self.client.record({'event': 'mini_start', 'step': agent.state.n_steps})
		try:
			response = await asyncio.wait_for(self.mini_llm.ainvoke(messages, **kwargs), timeout=20)
			if response.usage is not None:
				self.mini_unknown_cost_calls -= 1
			self.client.record(
				{
					'event': 'mini_finish',
					'step': agent.state.n_steps,
					'duration_seconds': time.monotonic() - started,
					'usage_known': response.usage is not None,
				}
			)
			if not isinstance(response.completion, AgentOutput) or not response.completion.action:
				raise TypeError('Mini returned an unexpected output schema')
			if not any('done' in action.model_dump(exclude_none=True) for action in response.completion.action):
				return response
			self.mini_final_verifications += 1
			self.client.record({'event': 'mini_final_verification', 'step': agent.state.n_steps})
		except Exception as exc:
			self.client.record(
				{
					'event': 'mini_fallback',
					'step': agent.state.n_steps,
					'error': type(exc).__name__,
					'duration_seconds': time.monotonic() - started,
				}
			)
		# Mini output is not executed or inserted as evidence. BU2 sees the original state.
		self.full_calls += 1
		return await agent.llm.ainvoke(messages, **kwargs)

	def remember(self, output) -> None:
		self.parent_calls += 1
		if self.router:
			self.router.remember_main_output(output)

	def summary(self):
		return {
			'mode': self.mode,
			'parent_calls': self.parent_calls,
			'fast_actions': self.fast_actions,
			'transformed_calls': self.transformed_calls,
			'mini_calls': self.mini_calls,
			'full_calls': self.full_calls,
			'mini_unknown_cost_calls': self.mini_unknown_cost_calls,
			'mini_final_verifications': self.mini_final_verifications,
			**self.client.summary(),
		}


def observation_size(messages):
	chars = 0
	images = 0
	for message in messages:
		if isinstance(message.content, str):
			chars += len(message.content)
		else:
			for part in message.content:
				if part.type == 'text':
					chars += len(part.text)
				elif part.type == 'image_url':
					images += 1
	return {'text_chars': chars, 'images': images}
