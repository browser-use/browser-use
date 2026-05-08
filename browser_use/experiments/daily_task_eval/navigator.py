from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from .models import TaskCard
from .prompts import build_navigator_prompt

NavigatorBackend = Literal['openai_compatible', 'deepseek']


@dataclass(frozen=True)
class NavigatorConfig:
	"""Planner LLM (navigator). Execution still uses `ExecutorConfig` in `runner.py`."""

	enabled: bool = False
	backend: NavigatorBackend = 'openai_compatible'
	model: str = 'qwen3-max'
	api_key_env: str = 'DASHSCOPE_API_KEY'
	# China (Beijing) 百炼; Singapore: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
	base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
	temperature: float = 0.1


class NavigatorPlanProvider:
	"""Pluggable navigator interface.

	Implementations can use an LLM, a rules engine, or a fixed template. Runner code
	only depends on this interface and can be toggled via config.
	"""

	def __init__(self, config: NavigatorConfig) -> None:
		self.config = config

	async def create_plan(self, task: TaskCard, scenario_id: str) -> str:  # pragma: no cover - interface
		raise NotImplementedError


class NoopNavigator(NavigatorPlanProvider):
	async def create_plan(self, task: TaskCard, scenario_id: str) -> str:
		_ = (task, scenario_id)
		return ''


class LLMNavigator(NavigatorPlanProvider):
	async def create_plan(self, task: TaskCard, scenario_id: str) -> str:
		from browser_use import ChatOpenAI
		from browser_use.llm import ChatDeepSeek
		from browser_use.llm.messages import SystemMessage, UserMessage

		api_key = os.getenv(self.config.api_key_env)
		if not api_key:
			raise ValueError(f'{self.config.api_key_env} is not set; required for navigator model {self.config.model}.')

		if self.config.backend == 'deepseek':
			llm = ChatDeepSeek(
				model=self.config.model,
				api_key=api_key,
				base_url=self.config.base_url,
				temperature=self.config.temperature,
			)
		else:
			llm = ChatOpenAI(
				model=self.config.model,
				api_key=api_key,
				base_url=self.config.base_url,
				temperature=self.config.temperature,
			)
		completion = await llm.ainvoke(
			[
				SystemMessage(
					content=(
						'You are a cautious workflow navigator for browser automation. '
						'Your job is to plan, identify risks, and define recovery behavior. '
						'Never output browser-use action JSON; output human-readable plan text only.'
					)
				),
				UserMessage(content=build_navigator_prompt(task, scenario_id=scenario_id)),
			]
		)
		return completion.completion.strip()


def build_navigator(config: NavigatorConfig) -> NavigatorPlanProvider | None:
	if not config.enabled:
		return None
	return LLMNavigator(config)

