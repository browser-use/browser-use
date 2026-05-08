"""Executor LLM for daily-task experiments (browser-use cloud vs OpenAI-compatible APIs).

Code map:
- Presets A/B/C/D pick executor profiles in `experiment_presets.py`.
- `build_executor_llm()` is the single factory used by `runner.run_agent_task`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from browser_use import ChatBrowserUse
from browser_use.llm.base import BaseChatModel
from browser_use.llm.openai.chat import ChatOpenAI

ExecutorBackend = Literal['chat_browser_use', 'openai_compatible']


@dataclass(frozen=True)
class ExecutorConfig:
	"""LLM that drives Browser Use `Agent` actions."""

	backend: ExecutorBackend = 'chat_browser_use'
	model: str = 'bu-latest'
	"""ChatBrowserUse model id, or OpenAI-compatible model name for Qwen/DashScope."""

	api_key_env: str = 'DASHSCOPE_API_KEY'
	# China (Beijing) Model Studio / 百炼; use dashscope-intl for Singapore.
	base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
	temperature: float | None = 0.2
	use_vision: Literal['auto', True, False] = 'auto'


def build_executor_llm(config: ExecutorConfig) -> BaseChatModel:
	if config.backend == 'chat_browser_use':
		return ChatBrowserUse(model=config.model)

	api_key = os.getenv(config.api_key_env)
	if not api_key:
		raise ValueError(
			f'{config.api_key_env} is not set; required for OpenAI-compatible executor ({config.model}).'
		)
	return ChatOpenAI(
		model=config.model,
		api_key=api_key,
		base_url=config.base_url,
		temperature=config.temperature,
	)


def default_use_vision_for_executor(config: ExecutorConfig) -> Literal['auto', True, False]:
	"""Qwen-style OpenAI-compatible executors are text-first in this eval harness."""
	if config.backend == 'chat_browser_use':
		return config.use_vision
	return False if config.use_vision == 'auto' else config.use_vision


def default_max_actions_per_step_for_executor(config: ExecutorConfig) -> int:
	"""Qwen / OpenAI-compatible chat models often emit malformed multi-action JSON
	(closing braces leak into the previous action's URL field, e.g. '...com/}}],').

	Forcing one action per step matches `examples/models/qwen.py` recommendation
	and reliably avoids the URL %7D%7D issue. ChatBrowserUse keeps the upstream
	default (3) since the BU cloud schema is hardened.
	"""
	if config.backend == 'chat_browser_use':
		return 3
	return 1
