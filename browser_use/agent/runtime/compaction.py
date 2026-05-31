from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from browser_use.agent.runtime.context import (
	BrowserContext,
	CompactionItem,
	ContextItem,
	DownloadItem,
	FileArtifactItem,
	SkillItem,
	TaskItem,
	UserSteerItem,
	WarningItem,
)

CompactionReason = Literal['item_count', 'context_pressure']


class ContextCompactionPolicy(BaseModel):
	"""Deterministic rules for compacting typed browser-agent context."""

	model_config = ConfigDict(frozen=True)

	max_items_before_compaction: int = Field(default=30, ge=3)
	max_rendered_chars_before_compaction: int | None = Field(default=24_000, ge=1000)
	keep_recent_items: int = Field(default=8, ge=1)
	max_summary_chars: int = Field(default=4000, ge=200)


class ContextCompactionResult(BaseModel):
	"""Result of compacting typed context."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	context: BrowserContext
	compacted: bool
	source_item_ids: list[str] = Field(default_factory=list)
	summary: str | None = None
	reasons: list[CompactionReason] = Field(default_factory=list)
	before_item_count: int | None = None
	after_item_count: int | None = None
	before_rendered_chars: int | None = None
	after_rendered_chars: int | None = None

	def event_payload(self) -> dict[str, object]:
		"""Return a compact event payload suitable for runtime event streams."""

		return {
			'compacted': self.compacted,
			'reasons': self.reasons,
			'source_item_count': len(self.source_item_ids),
			'source_item_ids': self.source_item_ids,
			'before_item_count': self.before_item_count,
			'after_item_count': self.after_item_count,
			'before_rendered_chars': self.before_rendered_chars,
			'after_rendered_chars': self.after_rendered_chars,
		}


class BrowserContextCompactor(BaseModel):
	"""Compacts old typed context without touching the active browser state."""

	model_config = ConfigDict(validate_assignment=True)

	policy: ContextCompactionPolicy = Field(default_factory=ContextCompactionPolicy)

	def should_compact(self, context: BrowserContext) -> bool:
		return bool(self.compaction_reasons(context))

	def compaction_reasons(self, context: BrowserContext, *, rendered_chars: int | None = None) -> list[CompactionReason]:
		reasons: list[CompactionReason] = []
		if len(context.items) > self.policy.max_items_before_compaction:
			reasons.append('item_count')

		max_rendered_chars = self.policy.max_rendered_chars_before_compaction
		if max_rendered_chars is not None:
			rendered_chars = rendered_chars if rendered_chars is not None else len(context.render())
			if rendered_chars > max_rendered_chars:
				reasons.append('context_pressure')

		return reasons

	def compact(self, context: BrowserContext) -> ContextCompactionResult:
		before_rendered_chars = len(context.render())
		reasons = self.compaction_reasons(context, rendered_chars=before_rendered_chars)
		if not reasons:
			return ContextCompactionResult(
				context=context,
				compacted=False,
				before_item_count=len(context.items),
				after_item_count=len(context.items),
				before_rendered_chars=before_rendered_chars,
				after_rendered_chars=before_rendered_chars,
			)

		latest_browser_state = context.latest_browser_state()
		preserved: list[ContextItem] = []
		recent = context.items[-self.policy.keep_recent_items :]
		recent_ids = {item.item_id for item in recent}

		for item in context.items:
			if _always_preserve(item):
				preserved.append(item)
			elif latest_browser_state is not None and item.item_id == latest_browser_state.item_id:
				preserved.append(item)
			elif item.item_id in recent_ids:
				preserved.append(item)

		seen = set()
		deduped_preserved: list[ContextItem] = []
		for item in preserved:
			if item.item_id in seen:
				continue
			seen.add(item.item_id)
			deduped_preserved.append(item)

		compacted_items = [item for item in context.items if item.item_id not in seen]
		if not compacted_items:
			return ContextCompactionResult(
				context=context,
				compacted=False,
				reasons=reasons,
				before_item_count=len(context.items),
				after_item_count=len(context.items),
				before_rendered_chars=before_rendered_chars,
				after_rendered_chars=before_rendered_chars,
			)

		summary = _summarize_items(compacted_items, max_chars=self.policy.max_summary_chars)
		source_ids = [item.item_id for item in compacted_items]

		insert_at = _compaction_insert_index(deduped_preserved)
		new_items: list[ContextItem] = list(deduped_preserved)
		if summary:
			new_items.insert(insert_at, CompactionItem(summary=summary, source_item_ids=source_ids))
		compacted_context = BrowserContext(items=new_items)

		return ContextCompactionResult(
			context=compacted_context,
			compacted=True,
			source_item_ids=source_ids,
			summary=summary,
			reasons=reasons,
			before_item_count=len(context.items),
			after_item_count=len(compacted_context.items),
			before_rendered_chars=before_rendered_chars,
			after_rendered_chars=len(compacted_context.render()),
		)


def _always_preserve(item: ContextItem) -> bool:
	return isinstance(item, TaskItem | UserSteerItem | DownloadItem | FileArtifactItem | WarningItem | SkillItem)


def _compaction_insert_index(items: list[ContextItem]) -> int:
	for index, item in enumerate(items):
		if not isinstance(item, TaskItem | UserSteerItem | SkillItem):
			return index
	return len(items)


def _summarize_items(items: list[ContextItem], *, max_chars: int) -> str:
	lines = []
	for item in items:
		rendered = item.render().strip().replace('\n', ' ')
		if len(rendered) > 280:
			rendered = f'{rendered[:277]}...'
		lines.append(f'- {item.kind}: {rendered}')

	summary = '\n'.join(lines)
	if len(summary) > max_chars:
		summary = f'{summary[: max_chars - 3]}...'
	return summary
