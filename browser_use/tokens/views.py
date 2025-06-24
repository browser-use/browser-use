from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar('T', bound=BaseModel)


class TokenUsageEntry(BaseModel):
	"""Single token usage entry"""

	model: str
	timestamp: datetime
	prompt_tokens: int
	completion_tokens: int
	total_tokens: int
	image_tokens: int | None = None


class ModelPricing(BaseModel):
	"""Pricing information for a model"""

	model: str
	input_cost_per_token: float | None = None
	output_cost_per_token: float | None = None
	max_tokens: int | None = None
	max_input_tokens: int | None = None
	max_output_tokens: int | None = None


class CachedPricingData(BaseModel):
	"""Cached pricing data with timestamp"""

	timestamp: datetime
	data: dict[str, Any]


class ModelUsageStats(BaseModel):
	"""Usage statistics for a single model"""

	model: str
	prompt_tokens: int = 0
	completion_tokens: int = 0
	total_tokens: int = 0
	cost: float = 0.0
	invocations: int = 0
	average_tokens_per_invocation: float = 0.0


class UsageSummary(BaseModel):
	"""Summary of token usage and costs"""

	total_prompt_tokens: int
	total_prompt_cost: float
	total_completion_tokens: int
	total_completion_cost: float
	total_tokens: int
	total_cost: float
	entry_count: int
	models: list[str] = Field(default_factory=list)
	by_model: dict[str, ModelUsageStats] = Field(default_factory=dict)
