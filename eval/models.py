import logging
import os

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.openai.chat import ChatOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s: %(message)s')
logger = logging.getLogger(__name__)

SUPPORTED_MODELS = {
	# Anthropic
	'claude-3.5-sonnet': {
		'provider': 'anthropic',
		'model_name': 'claude-3-5-sonnet-20240620',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-3.5-sonnet-exp': {
		'provider': 'anthropic',
		'model_name': 'claude-3-5-sonnet-20241022',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-3.5-haiku-latest': {
		'provider': 'anthropic',
		'model_name': 'claude-3-5-haiku-latest',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-3.7-sonnet-exp': {
		'provider': 'anthropic',
		'model_name': 'claude-3-7-sonnet-20250219',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-sonnet-4': {
		'provider': 'anthropic',
		'model_name': 'claude-sonnet-4-20250514',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	'claude-opus-4': {
		'provider': 'anthropic',
		'model_name': 'claude-opus-4-20250514',
		'api_key_env': 'ANTHROPIC_API_KEY',
	},
	# Deepseek (via OpenAI Compatible API)
	'deepseek-reasoner': {
		'provider': 'openai_compatible',
		'model_name': 'deepseek-reasoner',
		'base_url': 'https://api.deepseek.com/v1',
		'api_key_env': 'DEEPSEEK_API_KEY',
	},
	'deepseek-chat': {
		'provider': 'openai_compatible',
		'model_name': 'deepseek-chat',
		'base_url': 'https://api.deepseek.com/v1',
		'api_key_env': 'DEEPSEEK_API_KEY',
	},
	# Google
	'gemini-1.5-flash': {'provider': 'google', 'model_name': 'gemini-1.5-flash-latest', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.0-flash-lite': {'provider': 'google', 'model_name': 'gemini-2.0-flash-lite', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.0-flash': {
		'provider': 'google',
		'model_name': 'gemini-2.0-flash',
		'api_key_env': 'GEMINI_API_KEY',
		'thinking_budget': 0,
	},
	'gemini-2.5-pro': {'provider': 'google', 'model_name': 'gemini-2.5-pro', 'api_key_env': 'GEMINI_API_KEY'},
	'gemini-2.5-flash': {
		'provider': 'google',
		'model_name': 'gemini-2.5-flash',
		'api_key_env': 'GEMINI_API_KEY',
		'thinking_budget': 0,
	},
	'gemini-2.5-flash-lite-preview': {
		'provider': 'google',
		'model_name': 'gemini-2.5-flash-lite-preview-06-17',
		'api_key_env': 'GEMINI_API_KEY',
		'thinking_budget': 0,
	},
	'gemini-2.5-pro-preview-05-06': {
		'provider': 'google',
		'model_name': 'gemini-2.5-pro-preview-05-06',
		'api_key_env': 'GEMINI_API_KEY',
	},
	'gemini-2.5-flash-preview': {
		'provider': 'google',
		'model_name': 'gemini-2.5-flash-preview-04-17',
		'api_key_env': 'GEMINI_API_KEY',
	},
	# OpenAI
	'gpt-4.1': {'provider': 'openai', 'model_name': 'gpt-4.1-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4.1-mini': {'provider': 'openai', 'model_name': 'gpt-4.1-mini-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-o3': {'provider': 'openai', 'model_name': 'o3-2025-04-16', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4.1-nano': {'provider': 'openai', 'model_name': 'gpt-4.1-nano-2025-04-14', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o': {'provider': 'openai', 'model_name': 'gpt-4o', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-4o-mini': {'provider': 'openai', 'model_name': 'gpt-4o-mini', 'api_key_env': 'OPENAI_API_KEY'},
	'gpt-o4-mini': {'provider': 'openai', 'model_name': 'o4-mini', 'api_key_env': 'OPENAI_API_KEY'},
	# X.ai (via OpenAI Compatible API)
	'grok-2': {
		'provider': 'openai_compatible',
		'model_name': 'grok-2-1212',
		'base_url': 'https://api.x.ai/v1',
		'api_key_env': 'XAI_API_KEY',
	},
	'grok-3': {
		'provider': 'openai_compatible',
		'model_name': 'grok-3-beta',
		'base_url': 'https://api.x.ai/v1',
		'api_key_env': 'XAI_API_KEY',
	},
	# Groq
	'gemma2-9b-it': {
		'provider': 'groq',
		'model_name': 'gemma2-9b-it',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	'llama-3.3-70b-versatile': {
		'provider': 'groq',
		'model_name': 'llama-3.3-70b-versatile',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	'llama-3.1-8b-instant': {
		'provider': 'groq',
		'model_name': 'llama-3.1-8b-instant',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	'llama3-70b-8192': {
		'provider': 'groq',
		'model_name': 'llama3-70b-8192',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	'llama3-8b-8192': {
		'provider': 'groq',
		'model_name': 'llama3-8b-8192',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	# Groq Preview
	'llama-4-maverick': {
		'provider': 'groq',
		'model_name': 'meta-llama/llama-4-maverick-17b-128e-instruct',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	'llama-4-scout': {
		'provider': 'groq',
		'model_name': 'meta-llama/llama-4-scout-17b-16e-instruct',
		'api_key_env': 'GROQ_API_KEY',
		'service_tier': 'auto',
	},
	# SambaNova
	'deepseek-r1-sambanova': {
		'provider': 'openai_compatible',
		'model_name': 'DeepSeek-R1',
		'base_url': 'https://api.sambanova.ai/v1',
		'api_key_env': 'SAMBANOVA_API_KEY',
	},
	'llama-4-maverick-sambanova': {
		'provider': 'openai_compatible',
		'model_name': 'Llama-4-Maverick-17B-128E-Instruct',
		'base_url': 'https://api.sambanova.ai/v1',
		'api_key_env': 'SAMBANOVA_API_KEY',
	},
	'qwen2.5-vl-72b-instruct': {
		'provider': 'openai_compatible',
		'model_name': 'Qwen/Qwen2.5-VL-72B-Instruct',
		'base_url': 'https://api.together.xyz/v1',
		'api_key_env': 'TOGETHER_API_KEY',
	},
}


def get_llm(model_name: str):
	"""Instantiates the correct ChatModel based on the model name."""
	if model_name not in SUPPORTED_MODELS:
		raise ValueError(f'Unsupported model: {model_name}. Supported models are: {list(SUPPORTED_MODELS.keys())}')

	config = SUPPORTED_MODELS[model_name]
	provider = config['provider']
	api_key_env = config.get('api_key_env')
	api_key = os.getenv(api_key_env) if api_key_env else None

	if not api_key and api_key_env:
		logger.warning(
			f'API key environment variable {api_key_env} not found or empty for model {model_name}. Trying without API key if possible.'
		)
		api_key = None

	match provider:
		case 'openai':
			kwargs = {'model': config['model_name'], 'temperature': 0.0}
			# Must set temperatue=1 if model is gpt-o4-mini
			if model_name in ['gpt-o4-mini', 'gpt-o3']:
				kwargs['temperature'] = 1
			if api_key:
				kwargs['api_key'] = api_key
			return ChatOpenAI(**kwargs)
		case 'anthropic':
			kwargs = {
				'model': config['model_name'],
				'temperature': 0.0,
				'timeout': 100,
			}
			if api_key:
				kwargs['api_key'] = api_key
			return ChatAnthropic(**kwargs)
		case 'google':
			kwargs = {'model': config['model_name'], 'temperature': 0.0, 'thinking_budget': config.get('thinking_budget', None)}
			if api_key:
				kwargs['api_key'] = api_key
			return ChatGoogle(**kwargs)
		case 'groq':
			kwargs = {
				'model': config['model_name'],
				'temperature': 0.0,
				'service_tier': config.get('service_tier', 'auto'),
			}
			if api_key:
				kwargs['api_key'] = api_key
			return ChatGroq(**kwargs)
		case 'openai_compatible':
			kwargs = {'model': config['model_name'], 'base_url': config['base_url'], 'temperature': 0.0}
			if api_key:
				kwargs['api_key'] = api_key
			elif config.get('base_url'):
				logger.warning(
					f'API key for {model_name} at {config["base_url"]} is missing, but base_url is specified. Authentication may fail.'
				)
			return ChatOpenAI(**kwargs)
		case _:
			raise ValueError(f'Unknown provider: {provider}')
