"""
AgentHistoryList-compatible shims so existing eval harnesses can call
`history.history[i].state.url`, `.result[j].is_done`, `.usage.model_dump()`,
etc. on a Rust-backed run.

These are thin views over the data already in `AgentRunResult` / its
`StepRecord`s and `events`. Fields that need live browser state
(screenshots, DOM, scroll position) return `None` — the Rust core doesn't
forward them today. Eval code typically `getattr`-guards those.

Kept in a separate module so `views.py` stays a clean pydantic surface
and the compat object is allowed to be ad-hoc.
"""

from __future__ import annotations

from typing import Any

from browser_use.rust.events import ModelConfig


class _ActionResultView:
	"""Shape: ActionResult — what the legacy harness reads off result[i]."""

	__slots__ = ('_data', 'extracted_content', 'error', 'is_done', 'success', 'long_term_memory')

	def __init__(self, data: dict[str, Any], *, is_done: bool = False) -> None:
		self._data = data
		# These attribute names match browser_use.agent.views.ActionResult.
		self.extracted_content = (
			data.get('extracted_content') or data.get('text') or data.get('content') or data.get('result')
		)
		self.error = data.get('error') or data.get('failure')
		self.is_done = bool(data.get('is_done', is_done))
		self.success = data.get('success')
		self.long_term_memory = data.get('long_term_memory')

	def model_dump(self) -> dict[str, Any]:
		return {
			'extracted_content': self.extracted_content,
			'error': self.error,
			'is_done': self.is_done,
			'success': self.success,
			'long_term_memory': self.long_term_memory,
		}


class _StateView:
	"""Shape: BrowserStateHistory — what the legacy harness reads off .state."""

	__slots__ = ('url', 'title', '_screenshot_b64')

	def __init__(self, url: str | None = None, title: str | None = None) -> None:
		self.url = url
		self.title = title
		# Rust core doesn't propagate screenshots through events today.
		self._screenshot_b64: str | None = None

	def get_screenshot(self) -> str | None:
		"""Compat: classic API returns base64-encoded PNG or None."""
		return self._screenshot_b64

	def model_dump(self) -> dict[str, Any]:
		return {'url': self.url, 'title': self.title}


class _ModelOutputView:
	"""Shape: AgentOutput — `.action` list of dicts + `.current_state`."""

	__slots__ = ('action', 'current_state', '_data')

	def __init__(self, tool: str | None, tool_input: dict[str, Any] | None, model_text: str) -> None:
		self._data = {
			'action': [{tool: tool_input}] if tool else [],
			'current_state': {'thought': model_text} if model_text else {},
		}
		self.action = self._data['action']
		self.current_state = self._data['current_state']

	def model_dump(self) -> dict[str, Any]:
		return self._data


class _MetadataView:
	"""Shape: StepMetadata."""

	__slots__ = ('input_tokens', 'duration_seconds', 'step_start_time', 'step_end_time')

	def __init__(self) -> None:
		self.input_tokens = 0
		self.duration_seconds = 0.0
		self.step_start_time = 0.0
		self.step_end_time = 0.0

	def model_dump(self) -> dict[str, Any]:
		return {
			'input_tokens': self.input_tokens,
			'duration_seconds': self.duration_seconds,
			'step_start_time': self.step_start_time,
			'step_end_time': self.step_end_time,
		}


class _HistoryItemView:
	"""Shape: AgentHistory."""

	__slots__ = ('state', 'result', 'model_output', 'metadata')

	def __init__(self, step, is_last: bool, final_summary: str | None) -> None:
		self.state = _StateView()
		raw_results = step.tool_output or {}
		results = [_ActionResultView(raw_results, is_done=is_last)]
		if is_last and final_summary and not results[0].extracted_content:
			results[0].extracted_content = final_summary
			results[0].is_done = True
		self.result = results
		self.model_output = _ModelOutputView(step.tool, step.tool_input, step.model_text)
		self.metadata = _MetadataView()

	def model_dump(self) -> dict[str, Any]:
		return {
			'state': self.state.model_dump(),
			'result': [r.model_dump() for r in self.result],
			'model_output': self.model_output.model_dump(),
			'metadata': self.metadata.model_dump(),
		}


class _UsageView:
	"""Shape: tokens/cost. Populated from model.config events when available."""

	__slots__ = ('input_tokens', 'output_tokens', 'cost', 'model')

	def __init__(self) -> None:
		self.input_tokens = 0
		self.output_tokens = 0
		self.cost = 0.0
		self.model: str | None = None

	def model_dump(self) -> dict[str, Any]:
		return {
			'input_tokens': self.input_tokens,
			'output_tokens': self.output_tokens,
			'cost': self.cost,
			'model': self.model,
		}


class _MessageManagerStub:
	"""Compat for `agent.message_manager.last_input_messages` reads in evals."""

	def __init__(self) -> None:
		self.last_input_messages: list[Any] = []


def build_history_items(result) -> list[_HistoryItemView]:
	"""Turn AgentRunResult.steps + final_summary into AgentHistory views."""
	items: list[_HistoryItemView] = []
	steps = result.steps
	if not steps and result.final_summary:
		# No tool steps observed but the agent did produce a final answer.
		# Synthesize a single done-step so eval harnesses see something.
		synthetic = type(
			'SyntheticStep',
			(),
			{
				'seq': 0,
				'tool': 'done',
				'tool_input': None,
				'tool_output': {'extracted_content': result.final_summary, 'is_done': True, 'success': True},
				'model_text': '',
			},
		)()
		items.append(_HistoryItemView(synthetic, is_last=True, final_summary=result.final_summary))
		return items
	for idx, step in enumerate(steps):
		items.append(
			_HistoryItemView(
				step,
				is_last=idx == len(steps) - 1,
				final_summary=result.final_summary,
			)
		)
	return items


def build_usage(result) -> _UsageView:
	usage = _UsageView()
	for event in result.events:
		if isinstance(event, ModelConfig):
			usage.model = event.model or usage.model
	return usage
