from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar('T', bound=BaseModel)


class TokenUsageEntry(BaseModel):
	"""Single token usage entry"""

	model: str
	timestamp: datetime
	prompt_tokens: int
	completion_tokens: int
	total_tokens: int
	image_tokens: Optional[int] = None


class ModelPricing(BaseModel):
	"""Pricing information for a model"""

	model: str
	input_cost_per_token: Optional[float] = None
	output_cost_per_token: Optional[float] = None
	max_tokens: Optional[int] = None
	max_input_tokens: Optional[int] = None
	max_output_tokens: Optional[int] = None


class CachedPricingData(BaseModel):
	"""Cached pricing data with timestamp"""

	timestamp: datetime
	data: Dict[str, Any]


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
	models: List[str] = Field(default_factory=list)
	by_model: Dict[str, ModelUsageStats] = Field(default_factory=dict)
