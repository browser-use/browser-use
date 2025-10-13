"""
Custom model pricing for models not available in LiteLLM's pricing data.

Prices are per token (not per 1M tokens).
"""

from typing import Any

# Custom model pricing data
# Format matches LiteLLM's model_prices_and_context_window.json structure
CUSTOM_MODEL_PRICING: dict[str, dict[str, Any]] = {
	'browser-use/fast': {
		'input_cost_per_token': 0.50 / 1_000_000,  # $0.50 per 1M tokens
		'output_cost_per_token': 3.00 / 1_000_000,  # $3.00 per 1M tokens
		'cache_read_input_token_cost': 0.10 / 1_000_000,  # $0.10 per 1M tokens
		'cache_creation_input_token_cost': None,  # Not specified
		'max_tokens': None,  # Not specified
		'max_input_tokens': None,  # Not specified
		'max_output_tokens': None,  # Not specified
	},
	'browser-use/smart': {
		'input_cost_per_token': 0.50 / 1_000_000,  # $0.50 per 1M tokens
		'output_cost_per_token': 3.00 / 1_000_000,  # $3.00 per 1M tokens
		'cache_read_input_token_cost': 0.10 / 1_000_000,  # $0.10 per 1M tokens
		'cache_creation_input_token_cost': None,  # Not specified
		'max_tokens': None,  # Not specified
		'max_input_tokens': None,  # Not specified
		'max_output_tokens': None,  # Not specified
	},
}
