from dataclasses import dataclass, field
from os import getenv
from typing import Any, Literal, cast

from openai.types.shared_params.reasoning_effort import ReasoningEffort

from browser_use.llm.openai.chat import ChatOpenAI

MiniMaxRegion = Literal['global', 'cn']
MINIMAX_BASE_URLS: dict[MiniMaxRegion, str] = {
	'global': 'https://api.minimax.io/v1',
	'cn': 'https://api.minimaxi.com/v1',
}


@dataclass(frozen=True)
class MiniMaxModelMetadata:
	input_modalities: tuple[Literal['text', 'image', 'video'], ...]
	thinking_modes: tuple[Literal['adaptive', 'disabled', 'always_on'], ...]


MINIMAX_MODEL_METADATA = {
	'MiniMax-M3.1-Flash': MiniMaxModelMetadata(('text', 'image', 'video'), ('adaptive',)),
	'MiniMax-M3': MiniMaxModelMetadata(('text', 'image', 'video'), ('adaptive', 'disabled')),
	'MiniMax-M2.7': MiniMaxModelMetadata(('text',), ('always_on',)),
}


@dataclass
class ChatMiniMax(ChatOpenAI):
	"""MiniMax's OpenAI-compatible API, using MINIMAX_API_KEY by default.

	M3.1 Flash requires adaptive thinking and uses maximum effort by default.
	M3 also supports thinking='disabled'. Explicit legacy and custom model
	IDs are sent unchanged; reasoning_effort is only sent for M3.1 Flash.
	"""

	model: str = 'MiniMax-M3.1-Flash'
	region: MiniMaxRegion = field(default_factory=lambda: cast(MiniMaxRegion, getenv('MINIMAX_REGION', 'global').lower()))
	frequency_penalty: float | None = None
	max_completion_tokens: int | None = 16384
	# MiniMax extends the OpenAI reasoning-effort enum with 'max'.
	reasoning_effort: ReasoningEffort = cast(ReasoningEffort, 'max')
	reasoning_models: list[str] | None = field(default_factory=list)
	thinking: Literal['adaptive', 'disabled'] | None = None

	@property
	def provider(self) -> str:
		return 'minimax'

	def __post_init__(self) -> None:
		if self.region not in MINIMAX_BASE_URLS:
			raise ValueError(f"Unknown MiniMax region: '{self.region}'. Expected 'global' or 'cn'.")
		if self.api_key is None:
			self.api_key = getenv('MINIMAX_API_KEY')
		if self.base_url is None:
			self.base_url = getenv('MINIMAX_BASE_URL') or MINIMAX_BASE_URLS[self.region]

	@property
	def model_metadata(self) -> MiniMaxModelMetadata | None:
		return MINIMAX_MODEL_METADATA.get(self.model)

	def _get_model_params(self) -> dict[str, Any]:
		params = super()._get_model_params()
		# Do not infer effort support from an arbitrary saved/custom model name.
		params.pop('reasoning_effort', None)
		if self.model == 'MiniMax-M3.1-Flash':
			if self.service_tier is not None:
				raise ValueError('MiniMax-M3.1-Flash does not support service_tier')
			if self.thinking == 'disabled':
				raise ValueError('MiniMax-M3.1-Flash requires adaptive thinking')
			if self.reasoning_effort not in ('low', 'medium', 'high', 'xhigh', 'max'):
				raise ValueError('MiniMax-M3.1-Flash reasoning_effort must be low, medium, high, xhigh, or max')
			params['reasoning_effort'] = self.reasoning_effort
		if self.thinking is not None:
			if self.thinking not in ('adaptive', 'disabled'):
				raise ValueError('MiniMax thinking must be adaptive or disabled')
			params['extra_body'] = {'thinking': {'type': self.thinking}}
		return params
