"""Base agent class for multi-agent orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage, BaseMessage
from browser_use.llm.views import ChatInvokeCompletion

from multiagent.config import AgentConfig
from multiagent.providers.base import create_llm_from_config
from multiagent.providers.proxy_scope import proxy_scope

logger = logging.getLogger(__name__)


class BaseAgent:
	"""Base class for advisory agents (Planner/Searcher/Critic).

	These are lightweight LLM wrappers that take context and return text advice.
	They do NOT directly execute browser actions - only the orchestrator does that
	via the real browser-use Agent.
	"""

	def __init__(self, name: str, config: AgentConfig) -> None:
		self.name = name
		self.config = config
		self.llm: BaseChatModel = create_llm_from_config(config.provider)
		self.system_prompt: str = self._load_prompt(config.prompt_path)
		self.call_count: int = 0

	@staticmethod
	def _load_prompt(path: str) -> str:
		p = Path(path)
		assert p.exists(), f'Prompt file not found: {p}'
		return p.read_text(encoding='utf-8')

	async def invoke(self, user_message: str, images: list[dict[str, Any]] | None = None) -> str:
		"""Send a message to the agent's LLM and return the text response.

		Applies proxy scoping for Azure providers.
		"""
		assert self.call_count < self.config.budget_max_calls, (
			f'Agent {self.name} exceeded budget of {self.config.budget_max_calls} calls'
		)

		messages: list[BaseMessage] = [SystemMessage(content=self.system_prompt)]

		if images:
			from browser_use.llm.messages import ContentPartTextParam, ContentPartImageParam, ImageURL

			parts: list[ContentPartTextParam | ContentPartImageParam] = [
				ContentPartTextParam(text=user_message)
			]
			for img in images:
				parts.append(ContentPartImageParam(
					image_url=ImageURL(
						url=img.get('url', img.get('data', '')),
						detail='low',
					)
				))
			messages.append(UserMessage(content=parts))
		else:
			messages.append(UserMessage(content=user_message))

		proxy_url = self.config.provider.proxy_url if self.config.provider.type == 'azure' else None

		with proxy_scope(proxy_url):
			result: ChatInvokeCompletion[str] = await self.llm.ainvoke(messages)

		self.call_count += 1
		return result.completion
