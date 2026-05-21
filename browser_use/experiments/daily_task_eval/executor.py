"""Executor LLM for daily-task experiments (browser-use cloud vs OpenAI-compatible APIs).

Code map:
- Presets A/B/C/D pick executor profiles in `experiment_presets.py`.
- `build_executor_llm()` is the single factory used by `runner.run_agent_task`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from browser_use import ChatBrowserUse, ChatGoogle
from browser_use.llm.base import BaseChatModel
from browser_use.llm.openai.chat import ChatOpenAI

ExecutorBackend = Literal['chat_browser_use', 'openai_compatible', 'google']

DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

# Volcengine Ark (豆包) OpenAI-compatible Chat Completions — same as official `OpenAI(base_url=...)`.
# https://www.volcengine.com/docs/82379/1399008
VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
VOLCES_ARK_API_KEY_ENV = 'ARK_API_KEY'

# Default DashScope (Qwen) compatible endpoint; must match `experiment_presets.DASHSCOPE_CN_BASE_URL`.
DEFAULT_DASHSCOPE_COMPAT_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'


def infer_volcengine_ark_executor_model(model: str) -> bool:
	"""True when `model` looks like a 豆包 / Ark endpoint id (OpenAI-compatible path on Volcengine)."""
	m = model.strip().lower()
	return m.startswith('doubao-') or m.startswith('ep-')


def resolve_openai_compatible_credentials(
	model: str,
	raw_api_key_env: str | None,
	raw_base_url: str | None,
) -> tuple[str, str]:
	"""Pick DashScope vs Volcengine Ark from model id when CLI omits URL / key env (None).

	Explicit ``raw_*`` values always win.
	"""
	if infer_volcengine_ark_executor_model(model):
		return (
			raw_api_key_env if raw_api_key_env is not None else VOLCES_ARK_API_KEY_ENV,
			raw_base_url if raw_base_url is not None else VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
		)
	return (
		raw_api_key_env if raw_api_key_env is not None else 'DASHSCOPE_API_KEY',
		raw_base_url if raw_base_url is not None else DEFAULT_DASHSCOPE_COMPAT_BASE_URL,
	)


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

	if config.backend == 'google':
		api_key = os.getenv(config.api_key_env)
		if not api_key:
			raise ValueError(
				f'{config.api_key_env} is not set; required for Google Gemini executor ({config.model}).'
			)
		return ChatGoogle(
			model=config.model,
			api_key=api_key,
			temperature=config.temperature,
		)

	api_key = os.getenv(config.api_key_env)
	if not api_key:
		raise ValueError(
			f'{config.api_key_env} is not set; required for OpenAI-compatible executor ({config.model}).'
		)
	# Volcengine Ark (豆包) rejects OpenAI `response_format.type=json_schema`; use prompt-stuffed schema only.
	ark_compat = infer_volcengine_ark_executor_model(config.model) or (
		'volces.com' in (config.base_url or '').lower()
	)
	if ark_compat:
		return ChatOpenAI(
			model=config.model,
			api_key=api_key,
			base_url=config.base_url,
			temperature=0.0,
			dont_force_structured_output=True,
			add_schema_to_system_prompt=True,
		)
	return ChatOpenAI(
		model=config.model,
		api_key=api_key,
		base_url=config.base_url,
		temperature=config.temperature,
	)


def default_use_vision_for_executor(config: ExecutorConfig) -> Literal['auto', True, False]:
	"""OpenAI-compatible Qwen executors are text-first; Gemini follows config."""
	if config.backend == 'chat_browser_use':
		return config.use_vision
	if config.backend == 'google':
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
	if config.backend == 'google':
		return 3
	return 1
