from __future__ import annotations

import logging
from dataclasses import dataclass

from browser_use.agent.message_manager.views import MessageManagerState
from browser_use.agent.views import AgentStepInfo, MessageCompactionSettings
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.utils import collect_sensitive_data_values, redact_sensitive_string

logger = logging.getLogger(__name__)

SensitiveData = dict[str, str | dict[str, str]]


@dataclass
class MessageCompactionService:
	"""Summarizes old legacy message-manager history into compact memory."""

	state: MessageManagerState
	sensitive_data: SensitiveData | None = None

	async def maybe_compact(
		self,
		llm: BaseChatModel | None,
		settings: MessageCompactionSettings | None,
		step_info: AgentStepInfo | None = None,
	) -> bool:
		"""Summarize older history into a compact memory block.

		Step interval is the primary trigger; char count is a minimum floor.
		"""
		if not settings or not settings.enabled:
			return False
		if llm is None:
			return False
		if step_info is None:
			return False

		steps_since = step_info.step_number - (self.state.last_compaction_step or 0)
		if steps_since < settings.compact_every_n_steps:
			return False

		history_items = self.state.agent_history_items
		full_history_text = '\n'.join(item.to_string() for item in history_items).strip()
		trigger_char_count = settings.trigger_char_count or 40000
		if len(full_history_text) < trigger_char_count:
			return False

		logger.debug(f'Compacting message history (items={len(history_items)}, chars={len(full_history_text)})')

		compaction_input = self._build_compaction_input(settings, full_history_text)
		compaction_input = self._redact_sensitive_text(compaction_input)
		system_prompt = self._system_prompt(settings)

		messages = [SystemMessage(content=system_prompt), UserMessage(content=compaction_input)]
		try:
			response = await llm.ainvoke(messages)
			summary = (response.completion or '').strip()
		except Exception as e:
			logger.warning(f'Failed to compact messages: {e}')
			return False

		if not summary:
			return False

		if settings.summary_max_chars and len(summary) > settings.summary_max_chars:
			summary = summary[: settings.summary_max_chars].rstrip() + '…'

		self._store_summary(summary, step_info, settings)
		logger.debug(f'Compaction complete (summary_chars={len(summary)}, history_items={len(self.state.agent_history_items)})')

		return True

	def _build_compaction_input(self, settings: MessageCompactionSettings, full_history_text: str) -> str:
		compaction_sections = []
		if self.state.compacted_memory:
			compaction_sections.append(
				f'<previous_compacted_memory>\n{self.state.compacted_memory}\n</previous_compacted_memory>'
			)
		compaction_sections.append(f'<agent_history>\n{full_history_text}\n</agent_history>')
		if settings.include_read_state and self.state.read_state_description:
			compaction_sections.append(f'<read_state>\n{self.state.read_state_description}\n</read_state>')
		return '\n\n'.join(compaction_sections)

	def _system_prompt(self, settings: MessageCompactionSettings) -> str:
		system_prompt = (
			'You are summarizing an agent run for prompt compaction.\n'
			'Capture task requirements, key facts, decisions, partial progress, errors, and next steps.\n'
			'Preserve important entities, values, URLs, and file paths.\n'
			'CRITICAL: Only mark a step as completed if you see explicit success confirmation in the history. '
			'If a step was started but not explicitly confirmed complete, mark it as "IN-PROGRESS". '
			'Never infer completion from context — only report what was confirmed.\n'
			'Return plain text only. Do not include tool calls or JSON.'
		)
		if settings.summary_max_chars:
			system_prompt += f' Keep under {settings.summary_max_chars} characters if possible.'
		return system_prompt

	def _store_summary(self, summary: str, step_info: AgentStepInfo, settings: MessageCompactionSettings) -> None:
		self.state.compacted_memory = summary
		self.state.compaction_count += 1
		self.state.last_compaction_step = step_info.step_number

		history_items = self.state.agent_history_items
		keep_last = max(0, settings.keep_last_items)
		if len(history_items) > keep_last + 1:
			if keep_last == 0:
				self.state.agent_history_items = [history_items[0]]
			else:
				self.state.agent_history_items = [history_items[0]] + history_items[-keep_last:]

	def _redact_sensitive_text(self, text: str) -> str:
		if not self.sensitive_data:
			return text

		sensitive_values = collect_sensitive_data_values(self.sensitive_data)
		if not sensitive_values:
			logger.warning('No valid entries found in sensitive_data dictionary')
			return text

		return redact_sensitive_string(text, sensitive_values)
