"""Navigator LLM resolution for CLI / Agent construction (no TUI imports)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from browser_use.llm.base import BaseChatModel


def resolve_navigator_llm_for_agent(
	config: dict[str, Any],
	executor_llm: BaseChatModel,
	get_llm: Callable[[dict[str, Any]], BaseChatModel],
) -> BaseChatModel:
	"""Pick navigator LLM from config when continuous_navigation is enabled (defaults to executor model)."""
	agent_cfg = config.get('agent', {})
	if not agent_cfg.get('continuous_navigation'):
		return executor_llm
	nav_model = agent_cfg.get('navigator_model')
	if not nav_model:
		return executor_llm
	cfg = copy.deepcopy(config)
	cfg.setdefault('model', {})['name'] = nav_model
	return get_llm(cfg)
