from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BrowserSkill(BaseModel):
	"""Small task-specific guidance that can be added to typed context on demand."""

	model_config = ConfigDict(frozen=True)

	name: str
	title: str
	content: str
	task_patterns: list[str] = Field(default_factory=list)
	url_patterns: list[str] = Field(default_factory=list)
	failure_patterns: list[str] = Field(default_factory=list)
	metadata: dict[str, Any] = Field(default_factory=dict)

	def matches(
		self,
		*,
		task: str | None = None,
		url: str | None = None,
		explicit_names: set[str] | None = None,
		recent_failures: list[str] | None = None,
	) -> bool:
		if explicit_names and self.name in explicit_names:
			return True
		if task and _matches_any(self.task_patterns, task):
			return True
		if url and _matches_any(self.url_patterns, url):
			return True
		if recent_failures and any(_matches_any(self.failure_patterns, failure) for failure in recent_failures):
			return True
		return False


class BrowserSkillRegistry(BaseModel):
	"""Selects compact browser interaction skills only when relevant."""

	model_config = ConfigDict(validate_assignment=True)

	skills: dict[str, BrowserSkill] = Field(default_factory=dict)

	@classmethod
	def default(cls) -> BrowserSkillRegistry:
		skills = [
			BrowserSkill(
				name='downloads',
				title='Downloads',
				task_patterns=['download', 'pdf', 'csv', 'xlsx', 'file'],
				failure_patterns=['download', 'pdf viewer'],
				content=(
					'When a task needs a downloaded file, wait for the download to finish, then inspect available file paths. '
					'Use file or workspace tools for the downloaded content instead of relying only on the browser viewer.'
				),
			),
			BrowserSkill(
				name='dialogs',
				title='Dialogs',
				task_patterns=['alert', 'confirm', 'prompt', 'dialog', 'popup'],
				failure_patterns=['dialog', 'popup', 'modal'],
				content=(
					'If a JavaScript dialog or blocking modal appears, resolve it before continuing. '
					'After dismissal, refresh browser state because the page can change without a normal navigation.'
				),
			),
			BrowserSkill(
				name='iframes',
				title='Iframes',
				task_patterns=['iframe', 'embedded', 'frame'],
				url_patterns=['checkout', 'payment', 'auth'],
				failure_patterns=['iframe', 'frame', 'cross-origin'],
				content=(
					'For iframe-heavy pages, prefer fresh browser state and CDP target/session handles. '
					'If a DOM index fails, inspect the element, use accessibility data, or use raw CDP against the relevant target.'
				),
			),
			BrowserSkill(
				name='shadow_dom',
				title='Shadow DOM',
				task_patterns=['shadow dom', 'web component', 'component'],
				failure_patterns=['shadow', 'not clickable', 'element not found'],
				content=(
					'For web components or shadow DOM, compare cleaned DOM, raw HTML, accessibility tree, and screenshot. '
					'Use coordinate click or CDP only after checking the Browser Use element index path.'
				),
			),
			BrowserSkill(
				name='dropdowns',
				title='Dropdowns',
				task_patterns=['dropdown', 'select', 'combobox', 'menu'],
				failure_patterns=['dropdown', 'select option', 'combobox'],
				content=(
					'For native select elements, use dropdown-specific tools when available. '
					'For custom dropdowns, open the menu, refresh state, then choose by visible option text or accessibility name.'
				),
			),
			BrowserSkill(
				name='uploads',
				title='Uploads',
				task_patterns=['upload', 'attach file', 'choose file'],
				failure_patterns=['upload', 'file input', 'available_file_paths'],
				content=(
					'For file uploads, use available file paths or workspace-created files. '
					'Prefer the upload tool for file inputs; only use keyboard or coordinate fallbacks when the input is hidden behind custom UI.'
				),
			),
		]
		return cls(skills={skill.name: skill for skill in skills})

	def select(
		self,
		*,
		task: str | None = None,
		url: str | None = None,
		explicit_names: list[str] | None = None,
		recent_failures: list[str] | None = None,
		max_skills: int = 3,
	) -> list[BrowserSkill]:
		explicit = set(explicit_names or [])
		matches = [
			skill
			for skill in self.skills.values()
			if skill.matches(task=task, url=url, explicit_names=explicit, recent_failures=recent_failures)
		]
		return matches[:max_skills]

	def get(self, name: str) -> BrowserSkill | None:
		return self.skills.get(name)


def _matches_any(patterns: list[str], value: str) -> bool:
	value_lower = value.lower()
	return any(re.search(pattern, value_lower, re.IGNORECASE) for pattern in patterns)
