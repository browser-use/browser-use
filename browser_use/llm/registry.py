"""Model registry for creating chat models from string specifications.

Handles provider detection, API key resolution, and model instantiation.
Supports both explicit provider syntax ('provider/model') and auto-detection from model prefixes.
"""

import os
from typing import Any

from browser_use.llm.base import BaseChatModel


def parse_model_string(model_string: str) -> tuple[str | None, str]:
	"""Parse model string with optional provider prefix.

	Formats:
		- "model" → (None, "model")
		- "provider/model" → ("provider", "model")

	Examples:
		- "gpt-4.1-mini" → (None, "gpt-4.1-mini")
		- "azure/gpt-4.1-mini" → ("azure", "gpt-4.1-mini")
		- "groq/meta-llama/llama-4-maverick" → ("groq", "meta-llama/llama-4-maverick")
	"""
	if '/' not in model_string:
		return (None, model_string)

	# Split on first slash only to handle models with slashes in their names
	parts = model_string.split('/', 1)
	return (parts[0], parts[1])


def _get_provider_info(provider: str) -> tuple[type[BaseChatModel], str | list[str] | None, dict[str, str]]:
	"""Get provider class, required credentials, and extra params.

	Uses lazy imports via browser_use.llm.__getattr__ to avoid loading unused providers.

	Returns:
		(chat_class, required_keys, extra_params)
	"""
	# Provider metadata: class_name → (required_env_keys, extra_params_map)
	# - required_env_keys: env var name(s) for API keys (str for single, list for multiple, None for optional)
	# - extra_params_map: {constructor_param: env_var_name} for provider-specific config
	provider_metadata: dict[str, tuple[str, str | list[str] | None, dict[str, str]]] = {
		'openai': ('ChatOpenAI', 'OPENAI_API_KEY', {}),
		'azure': ('ChatAzureOpenAI', 'AZURE_OPENAI_KEY', {'azure_endpoint': 'AZURE_OPENAI_ENDPOINT'}),
		'anthropic': ('ChatAnthropic', 'ANTHROPIC_API_KEY', {}),
		'aws_bedrock': ('ChatAWSBedrock', ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'], {'aws_region': 'AWS_DEFAULT_REGION'}),
		'aws_bedrock_anthropic': (
			'ChatAnthropicBedrock',
			['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
			{'aws_region': 'AWS_DEFAULT_REGION'},
		),
		'google': ('ChatGoogle', 'GOOGLE_API_KEY', {}),
		'groq': ('ChatGroq', 'GROQ_API_KEY', {}),
		'ollama': ('ChatOllama', None, {'host': 'OLLAMA_BASE_URL'}),
		'deepseek': ('ChatOpenAI', 'DEEPSEEK_API_KEY', {'base_url': 'https://api.deepseek.com'}),
		'openrouter': ('ChatOpenAI', 'OPENROUTER_API_KEY', {'base_url': 'https://openrouter.ai/api/v1'}),
	}

	if provider not in provider_metadata:
		available = ', '.join(sorted(provider_metadata.keys()))
		raise ValueError(
			f"Unknown provider: '{provider}'\n"
			f'Available providers: {available}\n'
			f"Use format: 'provider/model' or set BROWSER_USE_LLM_PROVIDER"
		)

	class_name, required_keys, extra_params = provider_metadata[provider]

	# Lazy import via browser_use.llm.__getattr__
	import browser_use.llm

	chat_class = getattr(browser_use.llm, class_name)

	return chat_class, required_keys, extra_params


def _auto_detect_provider(model_name: str) -> str | None:
	"""Auto-detect provider from model name prefix.

	Only matches highly distinctive prefixes to avoid ambiguity.
	"""
	prefix_hints = {
		'claude-': 'anthropic',
		'gemini-': 'google',
		'llama': 'ollama',  # Ollama-specific naming (e.g., llama3.1:8b)
		'gemma': 'ollama',  # Ollama-specific naming (e.g., gemma3:4b)
		'deepseek-': 'deepseek',
	}

	for prefix, provider in prefix_hints.items():
		if model_name.startswith(prefix):
			return provider

	return None


def _resolve_credentials(
	required_keys: str | list[str] | None, config: dict[str, Any], extra_params: dict[str, str]
) -> dict[str, Any]:
	"""Resolve API keys and extra params from config or environment.

	Args:
		required_keys: Single key name, list of key names, or None
		config: Config dict that may contain keys
		extra_params: Map of param_name → env_var_name for provider-specific params

	Returns:
		Dict of resolved kwargs for model constructor

	Raises:
		ValueError: If required credentials are missing
	"""
	kwargs = {}

	# Resolve main API key(s)
	if required_keys is not None:
		if isinstance(required_keys, str):
			# Single API key (most providers)
			key_value = config.get('api_key') or os.getenv(required_keys)
			if not key_value:
				raise ValueError(f'Missing required credential: {required_keys}\nSet it via config or environment variable')
			kwargs['api_key'] = key_value
		else:
			# Multiple credentials (AWS Bedrock)
			for key_name in required_keys:
				# AWS credentials are set via environment, not constructor params
				# Just validate they exist
				key_value = os.getenv(key_name)
				if not key_value:
					raise ValueError(f'Missing required credential: {key_name}\nSet it via environment variable')

	# Resolve extra params (azure_endpoint, base_url, aws_region, etc.)
	for param_name, env_var_name in extra_params.items():
		value = config.get(param_name) or os.getenv(env_var_name)
		if value:
			kwargs[param_name] = value
		elif param_name == 'azure_endpoint':
			# Azure endpoint is required
			raise ValueError(f'Missing required parameter: {param_name}\nSet via config or {env_var_name} environment variable')

	return kwargs


def create_chat_model_from_string(
	model: str, config: dict[str, Any] | None = None, provider: str | None = None, temperature: float = 0.7, **kwargs: Any
) -> BaseChatModel:
	"""Create chat model from string with smart provider resolution.

	Resolution order (highest to lowest priority):
		1. Explicit provider parameter
		2. Provider prefix in model string ("provider/model")
		3. Provider hint in config dict
		4. Auto-detect from model prefix
		5. Fallback to OpenAI (backward compatible default)

	Args:
		model: Model name (bare or with "provider/model" prefix)
		config: Config dict with optional provider, api_key, azure_endpoint, etc.
		provider: Explicit provider override
		temperature: Model temperature
		**kwargs: Additional kwargs passed to model constructor

	Returns:
		Instantiated chat model

	Raises:
		ValueError: If provider is unknown or credentials are missing

	Examples:
		create_chat_model_from_string("groq/meta-llama/llama-4")
		create_chat_model_from_string("gpt-4.1-mini", {"provider": "azure"})
		create_chat_model_from_string("claude-sonnet-4-0")  # Auto-detects anthropic
		create_chat_model_from_string("gpt-4.1-mini")  # Defaults to openai
	"""
	config = config or {}

	# Parse provider prefix from model string if present
	provider_from_string, model_name = parse_model_string(model)

	# Resolve provider: explicit param > string prefix > config > auto-detect > default
	resolved_provider = (
		provider or provider_from_string or config.get('provider') or _auto_detect_provider(model_name) or 'openai'
	)

	# Get provider-specific class and credential requirements
	chat_class, required_keys, extra_params = _get_provider_info(resolved_provider)

	# Build constructor kwargs
	init_kwargs: dict[str, Any] = {
		'model': model_name,
		'temperature': temperature,
	}
	init_kwargs.update(_resolve_credentials(required_keys, config, extra_params))
	init_kwargs.update(kwargs)

	# Instantiate model
	try:
		return chat_class(**init_kwargs)
	except Exception as e:
		raise ValueError(
			f"Failed to create {chat_class.__name__} with model '{model_name}': {e}\n"
			f'Check that required credentials are set and model name is correct.'
		) from e
