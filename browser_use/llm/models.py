"""
Convenient access to LLM models.

Usage:
    from browser_use import llm

    # Simple model access
    model = llm.azure_gpt_4_1_mini
    model = llm.openai_gpt_4o
    model = llm.google_gemini_2_5_pro
"""

import os
from typing import TYPE_CHECKING

from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI

# Optional OCI import
try:
	from browser_use.llm.oci_raw.chat import ChatOCIRaw

	OCI_AVAILABLE = True
except ImportError:
	ChatOCIRaw = None
	OCI_AVAILABLE = False

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

cerebras_llama3_1_8b: 'BaseChatModel'
cerebras_llama3_3_70b: 'BaseChatModel'
cerebras_gpt_oss_120b: 'BaseChatModel'
cerebras_llama_4_scout_17b_16e_instruct: 'BaseChatModel'
cerebras_llama_4_maverick_17b_128e_instruct: 'BaseChatModel'
cerebras_qwen_3_32b: 'BaseChatModel'
cerebras_qwen_3_235b_a22b_instruct_2507: 'BaseChatModel'
cerebras_qwen_3_235b_a22b_thinking_2507: 'BaseChatModel'
cerebras_qwen_3_coder_480b: 'BaseChatModel'


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
	elif 'llama3_1' in model_part:
		model = model_part.replace('llama3_1', 'llama3.1').replace('_', '-')
	elif 'llama3_3' in model_part:
		model = model_part.replace('llama3_3', 'llama-3.3').replace('_', '-')
	elif 'llama_4_scout' in model_part:
		model = model_part.replace('llama_4_scout', 'llama-4-scout').replace('_', '-')
	elif 'llama_4_maverick' in model_part:
		model = model_part.replace('llama_4_maverick', 'llama-4-maverick').replace('_', '-')
	elif 'gpt_oss_120b' in model_part:
		model = model_part.replace('gpt_oss_120b', 'gpt-oss-120b')
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

	# OCI Models
	elif provider == 'oci':
		# OCI requires more complex configuration that can't be easily inferred from env vars
		# Users should use ChatOCIRaw directly with proper configuration
		raise ValueError('OCI models require manual configuration. Use ChatOCIRaw directly with your OCI credentials.')

	# Cerebras Models
	elif provider == 'cerebras':
		api_key = os.getenv('CEREBRAS_API_KEY')
		return ChatCerebras(model=model, api_key=api_key)

	else:
		available_providers = ['openai', 'azure', 'google', 'oci', 'cerebras']
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
	elif name == 'ChatOCIRaw':
		if not OCI_AVAILABLE:
			raise ImportError('OCI integration not available. Install with: pip install "browser-use[oci]"')
		return ChatOCIRaw  # type: ignore
	elif name == 'ChatCerebras':
		return ChatCerebras  # type: ignore

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
	'ChatCerebras',
]

if OCI_AVAILABLE:
	__all__.append('ChatOCIRaw')

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
	# Cerebras instances - created on demand
	'cerebras_llama3_1_8b',
	'cerebras_llama3_3_70b',
	'cerebras_gpt_oss_120b',
	'cerebras_llama_4_scout_17b_16e_instruct',
	'cerebras_llama_4_maverick_17b_128e_instruct',
	'cerebras_qwen_3_32b',
	'cerebras_qwen_3_235b_a22b_instruct_2507',
	'cerebras_qwen_3_235b_a22b_thinking_2507',
	'cerebras_qwen_3_coder_480b',
]

# NOTE: OCI backend is optional. The try/except ImportError and conditional __all__ are required
# so this module can be imported without browser-use[oci] installed.
