"""YAML config schema with strict validation and defaults for multi-agent orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderConfig(BaseModel):
	"""Configuration for a single LLM provider instance."""

	model_config = ConfigDict(extra='forbid')

	type: str = 'vllm'  # 'vllm' or 'azure'
	model_name: str = 'Qwen3VL_32b'
	base_url: str | None = None
	api_key: str | None = None
	api_version: str | None = None
	api_base: str | None = None
	proxy_url: str | None = None
	temperature: float | None = 0.2
	max_completion_tokens: int | None = 4096

	@model_validator(mode='after')
	def apply_env_defaults(self) -> 'ProviderConfig':
		if self.type == 'vllm':
			if self.base_url is None:
				self.base_url = os.getenv('VLLM_BASE_URL', 'http://127.0.0.1:3333/v1')
			if self.model_name == 'Qwen3VL_32b':
				self.model_name = os.getenv('VLLM_MODEL_NAME', 'Qwen3VL_32b')
		elif self.type == 'azure':
			if self.api_key is None:
				self.api_key = os.getenv('AZURE_OPENAI_API_KEY') or os.getenv('AZURE_OPENAI_KEY')
			if self.api_base is None:
				self.api_base = os.getenv('AZURE_OPENAI_ENDPOINT')
			if self.api_version is None:
				self.api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')
			if self.proxy_url is None:
				self.proxy_url = os.getenv('AZURE_PROXY_URL', 'http://127.0.0.1:9090')
		return self


class AgentConfig(BaseModel):
	"""Configuration for a single agent in the multi-agent system."""

	model_config = ConfigDict(extra='forbid')

	enabled: bool = True
	prompt_path: str  # path to prompt .md file
	provider: ProviderConfig = Field(default_factory=ProviderConfig)
	max_tokens_per_call: int = 4096
	budget_max_calls: int = 50  # max LLM calls per run for this agent


class OrchestratorConfig(BaseModel):
	"""Orchestration policy settings."""

	model_config = ConfigDict(extra='forbid')

	max_steps: int = 50
	loop_detection_window: int = 5  # number of recent actions to check for loops
	loop_detection_threshold: int = 3  # how many repeats trigger loop detection
	searcher_on_first_step: bool = True
	always_use_critic: bool = True
	force_replan_on_loop: bool = True
	abort_on_critic_reject_count: int = 3


class LoggingConfig(BaseModel):
	"""Logging configuration."""

	model_config = ConfigDict(extra='forbid')

	run_dir_base: str = 'runs/multiagent'
	experiment_name: str = 'default'
	save_screenshots: bool = True
	save_dom_snapshots: bool = True
	log_level: str = 'INFO'


class MultiAgentConfig(BaseModel):
	"""Top-level YAML config for multi-agent orchestration."""

	model_config = ConfigDict(extra='forbid')

	agents: dict[str, AgentConfig]
	orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
	logging: LoggingConfig = Field(default_factory=LoggingConfig)

	@model_validator(mode='after')
	def validate_required_agents(self) -> 'MultiAgentConfig':
		if 'planner' not in self.agents:
			raise ValueError("Config must include a 'planner' agent")
		return self


def load_config(path: str | Path) -> MultiAgentConfig:
	"""Load and validate a YAML config file."""
	path = Path(path)
	assert path.exists(), f'Config file not found: {path}'
	assert path.suffix in ('.yaml', '.yml'), f'Config must be .yaml/.yml, got: {path.suffix}'

	with open(path) as f:
		raw: dict[str, Any] = yaml.safe_load(f)

	assert isinstance(raw, dict), f'Config root must be a mapping, got {type(raw).__name__}'
	return MultiAgentConfig.model_validate(raw)
