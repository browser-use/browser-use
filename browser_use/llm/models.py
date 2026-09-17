"""
Convenient access to LLM models.

Usage:
    from browser_use import llm

    # Simple model access
    model = llm.azure_gpt_4_1_mini
    model = llm.openai_gpt_4o
    model = llm.google_gemini_2_5_pro
    model = llm.bu_latest  # or bu_2_0_mini_preview, bu_2_0, bu_1_0
"""

import os
import re
from typing import TYPE_CHECKING

from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.mistral.chat import ChatMistral
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.openrouter.chat import ChatOpenRouter

# Optional OCI import
try:
	from browser_use.llm.oci_raw.chat import ChatOCIRaw

	OCI_AVAILABLE = True
except ImportError:
	ChatOCIRaw = None
	OCI_AVAILABLE = False

# Optional Ollama import
try:
	from browser_use.llm.ollama.chat import ChatOllama

	OLLAMA_AVAILABLE = True
except ImportError:
	OLLAMA_AVAILABLE = False

if TYPE_CHECKING:
	from browser_use.llm.base import BaseChatModel

# Type stubs for IDE autocomplete
openai_gpt_4o: 'BaseChatModel'
openai_gpt_4o_mini: 'BaseChatModel'
openai_gpt_4_1_mini: 'BaseChatModel'
openai_o1: 'BaseChatModel'
openai_o1_mini: 'BaseChatModel'
openai_o1_pro: 'BaseChatModel'
openai_o3: 'BaseChatModel'
openai_o3_mini: 'BaseChatModel'
openai_o3_pro: 'BaseChatModel'
openai_o4_mini: 'BaseChatModel'
openai_gpt_5: 'BaseChatModel'
openai_gpt_5_mini: 'BaseChatModel'
openai_gpt_5_nano: 'BaseChatModel'

azure_gpt_4o: 'BaseChatModel'
azure_gpt_4o_mini: 'BaseChatModel'
azure_gpt_4_1_mini: 'BaseChatModel'
azure_o1: 'BaseChatModel'
azure_o1_mini: 'BaseChatModel'
azure_o1_pro: 'BaseChatModel'
azure_o3: 'BaseChatModel'
azure_o3_mini: 'BaseChatModel'
azure_o3_pro: 'BaseChatModel'
azure_gpt_5: 'BaseChatModel'
azure_gpt_5_mini: 'BaseChatModel'

google_gemini_2_0_flash: 'BaseChatModel'
google_gemini_2_0_pro: 'BaseChatModel'
google_gemini_2_5_pro: 'BaseChatModel'
google_gemini_2_5_flash: 'BaseChatModel'
google_gemini_2_5_flash_lite: 'BaseChatModel'
mistral_large: 'BaseChatModel'
mistral_medium: 'BaseChatModel'
mistral_small: 'BaseChatModel'
codestral: 'BaseChatModel'
pixtral_large: 'BaseChatModel'

anthropic_claude_sonnet_4_0: 'BaseChatModel'
anthropic_claude_fable_5: 'BaseChatModel'
anthropic_claude_3_5_sonnet_latest: 'BaseChatModel'
anthropic_claude_3_5_haiku_latest: 'BaseChatModel'

cerebras_gpt_oss_120b: 'BaseChatModel'
cerebras_zai_glm_4_7: 'BaseChatModel'
cerebras_gemma_4_31b: 'BaseChatModel'

deepseek_chat: 'BaseChatModel'
deepseek_reasoner: 'BaseChatModel'

groq_llama_3_3_70b: 'BaseChatModel'
groq_llama_4_scout: 'BaseChatModel'
groq_llama_4_maverick: 'BaseChatModel'

ollama_llama3: 'BaseChatModel'
ollama_llama3_2: 'BaseChatModel'

openrouter_anthropic_claude_3_5_sonnet: 'BaseChatModel'

bu_latest: 'BaseChatModel'
bu_1_0: 'BaseChatModel'
bu_2_0: 'BaseChatModel'
bu_2_0_mini_preview: 'BaseChatModel'


def get_llm_by_name(model_name: str):
	"""
	Factory function to create LLM instances from string names with API keys from environment.

	Args:
	    model_name: String name like 'azure_gpt_4_1_mini', 'openai_gpt_4o', etc.

	Returns:
	    LLM instance with API keys from environment variables

	Raises:
	    ValueError: If model_name is not recognized
	"""
	if not model_name:
		raise ValueError('Model name cannot be empty')

	# Handle top-level Mistral aliases without provider prefix
	mistral_aliases = {
		'mistral_large': 'mistral-large-latest',
		'mistral_medium': 'mistral-medium-latest',
		'mistral_small': 'mistral-small-latest',
		'codestral': 'codestral-latest',
		# Pixtral Large was retired; Mistral names Mistral Medium 3.5 as the replacement
		'pixtral_large': 'mistral-medium-latest',
	}
	if model_name in mistral_aliases:
		api_key = os.getenv('MISTRAL_API_KEY')
		base_url = os.getenv('MISTRAL_BASE_URL', 'https://api.mistral.ai/v1')
		return ChatMistral(model=mistral_aliases[model_name], api_key=api_key, base_url=base_url)

	# Parse model name
	parts = model_name.split('_', 1)
	if len(parts) < 2:
		raise ValueError(f"Invalid model name format: '{model_name}'. Expected format: 'provider_model_name'")

	provider = parts[0]
	model_part = parts[1]

	# Convert underscores back to dots/dashes for actual model names
	if 'gpt_4_1_mini' in model_part:
		model = model_part.replace('gpt_4_1_mini', 'gpt-4.1-mini')
	elif 'gpt_4o_mini' in model_part:
		model = model_part.replace('gpt_4o_mini', 'gpt-4o-mini')
	elif 'gpt_4o' in model_part:
		model = model_part.replace('gpt_4o', 'gpt-4o')
	elif 'gemini_2_0' in model_part:
		model = model_part.replace('gemini_2_0', 'gemini-2.0').replace('_', '-')
	elif 'gemini_2_5' in model_part:
		model = model_part.replace('gemini_2_5', 'gemini-2.5').replace('_', '-')
	elif 'llama3_1' in model_part or 'llama_3_1' in model_part:
		model = model_part.replace('llama3_1', 'llama3.1').replace('llama_3_1', 'llama3.1').replace('_', '-')
	elif 'llama3_3' in model_part or 'llama_3_3' in model_part:
		model = model_part.replace('llama3_3', 'llama-3.3').replace('llama_3_3', 'llama-3.3').replace('_', '-')
	elif 'llama_4_scout' in model_part:
		model = model_part.replace('llama_4_scout', 'llama-4-scout').replace('_', '-')
	elif 'llama_4_maverick' in model_part:
		model = model_part.replace('llama_4_maverick', 'llama-4-maverick').replace('_', '-')
	elif 'gpt_oss_120b' in model_part:
		model = model_part.replace('gpt_oss_120b', 'gpt-oss-120b')
	elif 'zai_glm_4_7' in model_part:
		model = model_part.replace('zai_glm_4_7', 'zai-glm-4.7')
	elif 'qwen_3_32b' in model_part:
		model = model_part.replace('qwen_3_32b', 'qwen-3-32b')
	elif 'qwen_3_235b_a22b_instruct' in model_part:
		if model_part.endswith('_2507'):
			model = model_part.replace('qwen_3_235b_a22b_instruct_2507', 'qwen-3-235b-a22b-instruct-2507')
		else:
			model = model_part.replace('qwen_3_235b_a22b_instruct', 'qwen-3-235b-a22b-instruct-2507')
	elif 'qwen_3_235b_a22b_thinking' in model_part:
		if model_part.endswith('_2507'):
			model = model_part.replace('qwen_3_235b_a22b_thinking_2507', 'qwen-3-235b-a22b-thinking-2507')
		else:
			model = model_part.replace('qwen_3_235b_a22b_thinking', 'qwen-3-235b-a22b-thinking-2507')
	elif 'qwen_3_coder_480b' in model_part:
		model = model_part.replace('qwen_3_coder_480b', 'qwen-3-coder-480b')
	else:
		model = model_part.replace('_', '-')

	# OpenAI Models
	if provider == 'openai':
		api_key = os.getenv('OPENAI_API_KEY')
		return ChatOpenAI(model=model, api_key=api_key)

	# Azure OpenAI Models
	elif provider == 'azure':
		api_key = os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY')
		azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
		return ChatAzureOpenAI(model=model, api_key=api_key, azure_endpoint=azure_endpoint)

	# Google Models
	elif provider == 'google':
		api_key = os.getenv('GOOGLE_API_KEY')
		return ChatGoogle(model=model, api_key=api_key)

	# Anthropic Models
	elif provider == 'anthropic':
		from browser_use.llm.anthropic.chat import ChatAnthropic

		api_key = os.getenv('ANTHROPIC_API_KEY')
		return ChatAnthropic(model=model, api_key=api_key)

	# Mistral Models
	elif provider == 'mistral':
		api_key = os.getenv('MISTRAL_API_KEY')
		base_url = os.getenv('MISTRAL_BASE_URL', 'https://api.mistral.ai/v1')
		mistral_map = {
			'large': 'mistral-large-latest',
			'medium': 'mistral-medium-latest',
			'small': 'mistral-small-latest',
			'codestral': 'codestral-latest',
			'pixtral-large': 'mistral-medium-latest',
		}
		normalized_model_part = model_part.replace('_', '-')
		resolved_model = mistral_map.get(normalized_model_part, model.replace('_', '-'))
		return ChatMistral(model=resolved_model, api_key=api_key, base_url=base_url)

	# OCI Models
	elif provider == 'oci':
		# OCI requires more complex configuration that can't be easily inferred from env vars
		# Users should use ChatOCIRaw directly with proper configuration
		raise ValueError('OCI models require manual configuration. Use ChatOCIRaw directly with your OCI credentials.')

	# Cerebras Models
	elif provider == 'cerebras':
		api_key = os.getenv('CEREBRAS_API_KEY')
		return ChatCerebras(model=model, api_key=api_key)

	# DeepSeek Models
	elif provider == 'deepseek':
		api_key = os.getenv('DEEPSEEK_API_KEY')
		base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
		deepseek_map = {
			'chat': 'deepseek-chat',
			'reasoner': 'deepseek-reasoner',
		}
		normalized_model_part = model_part.replace('_', '-')
		resolved_model = deepseek_map.get(normalized_model_part, model)
		if not resolved_model.startswith('deepseek-'):
			resolved_model = f'deepseek-{resolved_model}'
		return ChatDeepSeek(model=resolved_model, api_key=api_key, base_url=base_url)

	# Groq Models
	elif provider == 'groq':
		api_key = os.getenv('GROQ_API_KEY')
		base_url = os.getenv('GROQ_BASE_URL')
		groq_map = {
			'llama-3.3-70b': 'llama-3.3-70b-versatile',
			'llama-3.3-70b-versatile': 'llama-3.3-70b-versatile',
			'llama-4-scout': 'meta-llama/llama-4-scout-17b-16e-instruct',
			'llama-4-maverick': 'meta-llama/llama-4-maverick-17b-128e-instruct',
		}
		normalized_model_part = model_part.replace('_', '-')
		resolved_model = groq_map.get(normalized_model_part, groq_map.get(model, model))
		return ChatGroq(model=resolved_model, api_key=api_key, base_url=base_url)

	# Ollama Models
	elif provider == 'ollama':
		if not OLLAMA_AVAILABLE:
			raise ImportError('Ollama integration not available. Install with: pip install ollama')
		ollama_map = {
			'llama3_1': 'llama3.1',
			'llama3-1': 'llama3.1',
			'llama3_2': 'llama3.2',
			'llama3-2': 'llama3.2',
			'llama3_3': 'llama3.3',
			'llama3-3': 'llama3.3',
			'llama_3_1': 'llama3.1',
			'llama_3_2': 'llama3.2',
			'llama_3_3': 'llama3.3',
			'qwen2_5': 'qwen2.5',
			'qwen2-5': 'qwen2.5',
			'deepseek_r1': 'deepseek-r1',
		}
		if model_part in ollama_map:
			resolved_model = ollama_map[model_part]
		elif model in ollama_map:
			resolved_model = ollama_map[model]
		else:
			resolved_model = re.sub(r'(\d+)[_-](\d+)(?![a-zA-Z\d])', r'\1.\2', model_part)
			resolved_model = resolved_model.replace('_', '-')
		host = os.getenv('OLLAMA_HOST')
		return ChatOllama(model=resolved_model, host=host)

	# OpenRouter Models
	elif provider == 'openrouter':
		api_key = os.getenv('OPENROUTER_API_KEY')
		base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
		openrouter_map = {
			'anthropic_claude_3_5_sonnet': 'anthropic/claude-3.5-sonnet',
			'anthropic-claude-3-5-sonnet': 'anthropic/claude-3.5-sonnet',
		}
		resolved_model = openrouter_map.get(model_part, openrouter_map.get(model, model))
		return ChatOpenRouter(model=resolved_model, api_key=api_key, base_url=base_url)

	# Browser Use Models
	elif provider == 'bu':
		# Handle bu_latest -> bu-latest conversion (need to prepend 'bu-' back)
		model = f'bu-{model_part.replace("_", "-")}'
		api_key = os.getenv('BROWSER_USE_API_KEY')
		return ChatBrowserUse(model=model, api_key=api_key)

	else:
		available_providers = [
			'openai',
			'azure',
			'google',
			'anthropic',
			'mistral',
			'oci',
			'cerebras',
			'deepseek',
			'groq',
			'ollama',
			'openrouter',
			'bu',
		]
		raise ValueError(f"Unknown provider: '{provider}'. Available providers: {', '.join(available_providers)}")


# Pre-configured model instances (lazy loaded via __getattr__)
def __getattr__(name: str) -> 'BaseChatModel':
	"""Create model instances on demand with API keys from environment."""
	# Handle chat classes first
	if name == 'ChatOpenAI':
		return ChatOpenAI  # type: ignore
	elif name == 'ChatAzureOpenAI':
		return ChatAzureOpenAI  # type: ignore
	elif name == 'ChatGoogle':
		return ChatGoogle  # type: ignore

	elif name == 'ChatMistral':
		return ChatMistral  # type: ignore

	elif name == 'ChatOCIRaw':
		if not OCI_AVAILABLE:
			raise ImportError('OCI integration not available. Install with: pip install "browser-use[oci]"')
		return ChatOCIRaw  # type: ignore
	elif name == 'ChatCerebras':
		return ChatCerebras  # type: ignore
	elif name == 'ChatDeepSeek':
		return ChatDeepSeek  # type: ignore
	elif name == 'ChatGroq':
		return ChatGroq  # type: ignore
	elif name == 'ChatOllama':
		if not OLLAMA_AVAILABLE:
			raise ImportError('Ollama integration not available. Install with: pip install ollama')
		return ChatOllama  # type: ignore
	elif name == 'ChatOpenRouter':
		return ChatOpenRouter  # type: ignore
	elif name == 'ChatBrowserUse':
		return ChatBrowserUse  # type: ignore

	# Handle model instances - these are the main use case
	try:
		return get_llm_by_name(name)
	except ValueError:
		raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Export all classes and preconfigured instances, conditionally including ChatOCIRaw
__all__ = [
	'ChatOpenAI',
	'ChatAzureOpenAI',
	'ChatGoogle',
	'ChatMistral',
	'ChatCerebras',
	'ChatBrowserUse',
	'ChatDeepSeek',
	'ChatGroq',
	'ChatOpenRouter',
]

if OCI_AVAILABLE:
	__all__.append('ChatOCIRaw')
if OLLAMA_AVAILABLE:
	__all__.append('ChatOllama')

__all__ += [
	'get_llm_by_name',
	# OpenAI instances - created on demand
	'openai_gpt_4o',
	'openai_gpt_4o_mini',
	'openai_gpt_4_1_mini',
	'openai_o1',
	'openai_o1_mini',
	'openai_o1_pro',
	'openai_o3',
	'openai_o3_mini',
	'openai_o3_pro',
	'openai_o4_mini',
	'openai_gpt_5',
	'openai_gpt_5_mini',
	'openai_gpt_5_nano',
	# Azure instances - created on demand
	'azure_gpt_4o',
	'azure_gpt_4o_mini',
	'azure_gpt_4_1_mini',
	'azure_o1',
	'azure_o1_mini',
	'azure_o1_pro',
	'azure_o3',
	'azure_o3_mini',
	'azure_o3_pro',
	'azure_gpt_5',
	'azure_gpt_5_mini',
	# Google instances - created on demand
	'google_gemini_2_0_flash',
	'google_gemini_2_0_pro',
	'google_gemini_2_5_pro',
	'google_gemini_2_5_flash',
	'google_gemini_2_5_flash_lite',
	# Anthropic instances - created on demand
	'anthropic_claude_sonnet_4_0',
	'anthropic_claude_fable_5',
	'anthropic_claude_3_5_sonnet_latest',
	'anthropic_claude_3_5_haiku_latest',
	# Mistral instances - created on demand
	'mistral_large',
	'mistral_medium',
	'mistral_small',
	'codestral',
	'pixtral_large',
	# Cerebras instances - created on demand
	'cerebras_gpt_oss_120b',
	'cerebras_zai_glm_4_7',
	'cerebras_gemma_4_31b',
	# DeepSeek instances - created on demand
	'deepseek_chat',
	'deepseek_reasoner',
	# Groq instances - created on demand
	'groq_llama_3_3_70b',
	'groq_llama_4_scout',
	'groq_llama_4_maverick',
	# Ollama instances - created on demand
	'ollama_llama3',
	'ollama_llama3_2',
	# OpenRouter instances - created on demand
	'openrouter_anthropic_claude_3_5_sonnet',
	# Browser Use instances - created on demand
	'bu_latest',
	'bu_1_0',
	'bu_2_0',
	'bu_2_0_mini_preview',
]

# NOTE: OCI backend is optional. The try/except ImportError and conditional __all__ are required
# so this module can be imported without browser-use[oci] installed.
