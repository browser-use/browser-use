"""Experimental Jev policies. Disabled agents follow the unmodified native path."""

from typing import Any

from browser_use.agent.jev_client import JevClient


class JevPolicy:
	def __init__(self, mode: str, log_path: str | None):
		if mode not in {'actions', 'vision', 'compact'}:
			raise ValueError('jev_mode must be actions, vision, compact, or None')
		self.mode = mode
		self.client = JevClient(log_path=log_path)
		self.browser_state: Any = None
		self.previous_results: Any = None
		self.previous_output: Any = None
		self.parent_calls = 0
		self.fast_actions = 0
		self.transformed_calls = 0
		self.router = None
		if mode == 'actions':
			from browser_use.agent.jev_actions import JevActionRouter

			self.router = JevActionRouter(self.client)

	async def prepare(self, agent, messages):
		"""Choose one native action or prepare a temporary parent-model observation."""
		force_full = any(result.error for result in self.previous_results or [])
		force_full = force_full or bool(
			self.previous_output
			and any('screenshot' in action.model_dump(exclude_none=True) for action in self.previous_output.action)
		)
		# Never suppress observations when the runtime is forcing a final answer.
		force_full = force_full or agent.AgentOutput is agent.DoneAgentOutput
		force_full = force_full or agent.state.loop_detector.consecutive_stagnant_pages >= 2
		force_full = force_full or agent.state.n_steps % 4 == 0
		try:
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
