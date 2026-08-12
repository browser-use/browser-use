import os
from dataclasses import dataclass, field
from typing import Literal, cast

from browser_use.llm.openai.chat import ChatOpenAI

MiniMaxRegion = Literal['global', 'cn']
MiniMaxThinkingMode = Literal['adaptive', 'disabled', 'always_on']
MiniMaxModality = Literal['text', 'image', 'video']

MINIMAX_BASE_URLS: dict[MiniMaxRegion, str] = {
	'global': 'https://api.minimax.io/v1',
	'cn': 'https://api.minimaxi.com/v1',
}


@dataclass(frozen=True)
class MiniMaxModelMetadata:
	context_window: int
	input_cost_per_million_tokens: float
	output_cost_per_million_tokens: float
	cache_read_cost_per_million_tokens: float
	cache_write_cost_per_million_tokens: float | None
	input_modalities: tuple[MiniMaxModality, ...]
	thinking_modes: tuple[MiniMaxThinkingMode, ...]


MINIMAX_MODEL_METADATA = {
	'MiniMax-M3': MiniMaxModelMetadata(
		context_window=1_000_000,
		input_cost_per_million_tokens=0.6,
		output_cost_per_million_tokens=2.4,
		cache_read_cost_per_million_tokens=0.12,
		cache_write_cost_per_million_tokens=None,
		input_modalities=('text', 'image', 'video'),
		thinking_modes=('adaptive', 'disabled'),
	),
	'MiniMax-M2.7': MiniMaxModelMetadata(
		context_window=204_800,
		input_cost_per_million_tokens=0.3,
		output_cost_per_million_tokens=1.2,
		cache_read_cost_per_million_tokens=0.06,
		cache_write_cost_per_million_tokens=0.375,
		input_modalities=('text',),
		thinking_modes=('always_on',),
	),
}


def _region_from_env() -> MiniMaxRegion:
	return cast(MiniMaxRegion, os.getenv('MINIMAX_REGION', 'global').lower())


@dataclass
class ChatMiniMax(ChatOpenAI):
	"""Chat client for MiniMax models with global and China endpoints."""

	model: str = 'MiniMax-M3'
	region: MiniMaxRegion = field(default_factory=_region_from_env)

	def __post_init__(self) -> None:
		if self.region not in MINIMAX_BASE_URLS:
			raise ValueError(f"Unknown MiniMax region: '{self.region}'. Expected 'global' or 'cn'.")
		if self.api_key is None:
			self.api_key = os.getenv('MINIMAX_API_KEY')
		if self.base_url is None:
			self.base_url = os.getenv('MINIMAX_BASE_URL') or MINIMAX_BASE_URLS[self.region]

	@property
	def provider(self) -> str:
		return 'minimax'

	@property
	def model_metadata(self) -> MiniMaxModelMetadata | None:
		return MINIMAX_MODEL_METADATA.get(self.model)
