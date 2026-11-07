"""Usage mapping shared by OpenAI-compatible chat providers."""

from openai.types.chat.chat_completion import ChatCompletion

from browser_use.llm.views import ChatInvokeUsage


def get_chat_usage(response: ChatCompletion) -> ChatInvokeUsage | None:
	"""Map reported token totals and cached prompt tokens, or return None when absent."""
	usage = response.usage
	if usage is None:
		return None
	# DeepSeek exposes cache hits both here and as an additional top-level usage field.
	cached_tokens = usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details is not None else None
	if cached_tokens is None:
		cached_tokens = getattr(usage, 'prompt_cache_hit_tokens', None)
	return ChatInvokeUsage(
		prompt_tokens=usage.prompt_tokens,
		prompt_cached_tokens=cached_tokens,
		prompt_cache_creation_tokens=None,
		prompt_image_tokens=None,
		completion_tokens=usage.completion_tokens,
		total_tokens=usage.total_tokens,
	)
