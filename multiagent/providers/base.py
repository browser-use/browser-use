"""Factory for creating LLM instances from agent provider config."""

from __future__ import annotations

from browser_use.llm.base import BaseChatModel
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.azure.chat import ChatAzureOpenAI

from multiagent.config import ProviderConfig


def create_llm_from_config(cfg: ProviderConfig) -> BaseChatModel:
	"""Create the appropriate LLM client from a ProviderConfig."""
	if cfg.type == 'vllm':
		return ChatOpenAI(
			model=cfg.model_name,
			base_url=cfg.base_url,
			api_key=cfg.api_key or 'not-needed',
			temperature=cfg.temperature,
			max_completion_tokens=cfg.max_completion_tokens,
		)
	elif cfg.type == 'azure':
		return ChatAzureOpenAI(
			model=cfg.model_name,
			api_key=cfg.api_key,
			api_version=cfg.api_version,
			azure_endpoint=cfg.api_base,
			temperature=cfg.temperature,
			max_completion_tokens=cfg.max_completion_tokens,
		)
	else:
		raise ValueError(f'Unknown provider type: {cfg.type!r}. Must be "vllm" or "azure".')
