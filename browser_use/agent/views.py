"""The result of Agent.run(): keeps the common 0.x AgentHistoryList methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelMessage

from browser_use.exceptions import removed
from browser_use.tools import ActionResult  # 0.x imported it from here

if TYPE_CHECKING:
	from browser_use.agent.judge import Judgement

__all__ = ['ActionResult', 'AgentHistoryList']


class Usage(dict):
	"""result.usage: {'input', 'output', 'cache_read', 'cache_write', 'requests'}. 0.x's UsageSummary attributes raise the
	removed error with their 1.0 key."""

	ALTERNATIVES = {
		'total_cost': 'result.cost_usd.',
		'total_prompt_tokens': "result.usage['input'].",
		'total_prompt_cached_tokens': "result.usage['cache_read'].",
		'total_completion_tokens': "result.usage['output'].",
		'total_tokens': "result.usage['input'] + result.usage['output'].",
		'entry_count': "result.usage['requests'].",
		'by_model': 'one model runs the whole task: result.usage.',
	}

	def __getattr__(self, name: str):
		if name in self.ALTERNATIVES:
			raise AttributeError(removed(f'result.usage.{name}', self.ALTERNATIVES[name]))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')


# 0.x methods built on per-step browser state. 1.0 runs Python cells, so these have no faithful equivalent.
REMOVED = {
	'history',
	'urls',
	'screenshots',
	'screenshot_paths',
	'action_names',
	'action_history',
	'action_results',
	'model_thoughts',
	'model_outputs',
	'model_actions',
	'model_actions_filtered',
	'extracted_content',
	'agent_steps',
	'last_action',
	'save_to_file',
	'load_from_file',
	'get_structured_output',
	'add_item',
	'is_judged',
	'is_validated',
	'model_dump',
	'model_dump_json',
	'total_input_tokens',
	'input_token_usage',
	'load_from_dict',
	'save_as_playwright_script',
}
ALTERNATIVES = {  # removed names with a direct 1.0 equivalent
	'model_dump': 'dataclasses.asdict(result), or result.final_result() / result.structured_output.',
	'model_dump_json': 'result.final_result() (structured output as JSON).',
	'total_input_tokens': "result.usage['input'].",
	'input_token_usage': "result.usage['input'].",
	'history': 'result.messages (the full transcript) and result.number_of_steps().',
	**dict.fromkeys(('is_judged', 'is_validated'), 'result.judgement (None when the run was not judged).'),
}
HISTORY_ALTERNATIVE = (
	'the agent runs Python cells, not step actions: use final_result(), structured_output, errors(), .messages (the '
	'full transcript) or the files the agent saved in agent.workspace.'
)


@dataclass
class AgentHistoryList:
	# completed | timeout | max_steps | error. A run that reaches max_steps or the timeout gets one forced delivery turn
	# and still returns 'completed' (success=False when the agent reports it unfinished); 'max_steps' and 'timeout'
	# mean nothing was delivered: read partial.
	status: str
	text: str
	output: Any
	steps: int
	duration_s: float
	usage: dict[str, int]
	# model + web search charges only (None when a model's price is unknown); a cloud browser and its proxy are billed
	# apart: GET /api/v4/browsers/{browser.id} has browserCost and proxyCost
	cost_usd: float | None
	partial: Any  # last checkpoint(..., partial=True) when unfinished
	error: str | None
	messages: list[ModelMessage]
	success: bool | None = None  # the agent's optional verdict from finish(..., success=...); None when it gave none
	output_schema: Any = None  # Agent(output_model_schema=...) (str when none); None: unknown, judged by the output
	downloads: list[Path] = field(default_factory=list)  # files this run downloaded, in agent.workspace/downloads
	# the judge's verdict, labels and gotchas (Agent(judge=True), the default); None when off, not run or failed
	judgement: Judgement | None = None

	def __post_init__(self) -> None:
		if self.status != 'completed':
			self.success = None
		if not isinstance(self.usage, Usage):
			self.usage = Usage(self.usage)

	def __len__(self) -> int:
		"""0.x: one history item per step; there are none here."""
		raise TypeError(removed('len(AgentHistoryList)', 'result.number_of_steps() (model requests).'))

	def __bool__(self) -> bool:  # without it, truth testing would call __len__
		return True

	def __repr__(self) -> str:
		"""Without .messages: the transcript (screenshots included) made print(result) about 565 KB."""
		text = self.text if len(self.text) <= 500 else f'{self.text[:500]}... ({len(self.text)} chars)'
		return (
			f'AgentHistoryList(status={self.status!r}, success={self.success!r}, text={text!r}, steps={self.steps}, '
			f'duration_s={self.duration_s:.1f}, cost_usd={self.cost_usd!r}, usage={dict(self.usage)!r}, '
			f'error={self.error!r}, messages=<{len(self.messages)} messages>)'
		)

	def final_result(self) -> str | None:
		"""The answer text, or None when the run did not complete."""
		return self.text if self.status == 'completed' else None

	@property
	def structured_output(self) -> Any:
		"""The output_model_schema instance, or None. A Literal or StrEnum schema delivers a str: still structured."""
		if self.status != 'completed':
			return None
		structured = self.output_schema is not str if self.output_schema is not None else not isinstance(self.output, str)
		return self.output if structured else None

	def is_done(self) -> bool:
		return self.status == 'completed'

	def is_successful(self) -> bool | None:
		"""The agent's verdict: True / False from finish(..., success); None when there is no verdict: the run did not
		finish, or the agent answered in plain text or gave no success (0.x done defaulted it to True). For the 0.x
		default use `is_done() and success is not False`. is_done() only says the run completed."""
		return self.success if self.status == 'completed' else None

	def errors(self) -> list[str]:
		"""The error that ended the run, if any. Unlike 0.x (one entry per step), cell errors the agent recovered from
		are not listed: they are in .messages (the python tool results)."""
		return [self.error] if self.error else []

	def has_errors(self) -> bool:
		"""True when an error ended the run (see errors())."""
		return self.error is not None

	def number_of_steps(self) -> int:
		return self.steps

	def total_duration_seconds(self) -> float:
		return self.duration_s

	@classmethod
	def load_from_file(cls, *args: Any, **kwargs: Any) -> Any:
		"""A 0.x classmethod: called on the class, __getattr__ never runs."""
		raise AttributeError(removed('AgentHistoryList.load_from_file', HISTORY_ALTERNATIVE))

	def __getattr__(self, name: str) -> Any:
		if name in REMOVED:
			raise AttributeError(removed(f'AgentHistoryList.{name}', ALTERNATIVES.get(name, HISTORY_ALTERNATIVE)))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
