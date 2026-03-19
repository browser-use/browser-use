# pyright: reportMissingImports=false
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

# Third-party imports
import gradio as gr  # type: ignore

# Local module imports
from browser_use import Agent

PROVIDER_MODELS: dict[str, list[str]] = {
	'openai': ['gpt-4.1-mini', 'gpt-4.1', 'gpt-5-mini', 'gpt-5', 'o3'],
	'anthropic': ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5'],
	'deepseek': ['deepseek-chat', 'deepseek-reasoner'],
	'google': ['gemini-3-flash-preview', 'gemini-3-pro'],
	'groq': ['mixtral-8x7b-32768', 'llama-3.3-70b-versatile'],
	'ollama': ['llama3', 'mistral', 'qwen2.5'],
}

PROVIDER_ENV_KEYS: dict[str, str] = {
	'openai': 'OPENAI_API_KEY',
	'anthropic': 'ANTHROPIC_API_KEY',
	'deepseek': 'DEEPSEEK_API_KEY',
	'google': 'GOOGLE_API_KEY',
	'groq': 'GROQ_API_KEY',
	'ollama': '',
}

# Providers that do not support vision (screenshots in prompts)
NO_VISION_PROVIDERS = {'deepseek', 'groq', 'ollama'}


def get_llm(provider: str, model: str, api_key: str):
	"""Create an LLM instance for the given provider and model."""
	env_key = PROVIDER_ENV_KEYS.get(provider, '')
	if env_key and api_key.strip():
		os.environ[env_key] = api_key

	if provider == 'openai':
		from browser_use import ChatOpenAI

		return ChatOpenAI(model=model, temperature=0.0)
	elif provider == 'anthropic':
		from browser_use.llm import ChatAnthropic

		return ChatAnthropic(model=model, temperature=0.0)
	elif provider == 'deepseek':
		from browser_use.llm import ChatDeepSeek

		return ChatDeepSeek(model=model)
	elif provider == 'google':
		from browser_use.llm import ChatGoogle

		return ChatGoogle(model=model)
	elif provider == 'groq':
		from browser_use.llm import ChatGroq

		return ChatGroq(model=model)
	elif provider == 'ollama':
		from browser_use.llm import ChatOllama

		return ChatOllama(model=model)
	else:
		raise ValueError(f'Unsupported provider: {provider}')


async def run_browser_task(
	task: str,
	provider: str,
	api_key: str,
	model: str,
	headless: bool = True,
) -> str:
	if provider != 'ollama' and not api_key.strip():
		env_key = PROVIDER_ENV_KEYS.get(provider, '')
		if env_key and not os.getenv(env_key):
			return f'Please provide an API key or set {env_key} in your environment'

	try:
		llm = get_llm(provider, model, api_key)
		use_vision = provider not in NO_VISION_PROVIDERS
		agent = Agent(
			task=task,
			llm=llm,
			use_vision=use_vision,
		)
		result = await agent.run()
		return str(result)
	except Exception as e:
		return f'Error: {str(e)}'


def create_ui():
	with gr.Blocks(title='Browser Use GUI') as interface:
		gr.Markdown('# Browser Use Task Automation')

		with gr.Row():
			with gr.Column():
				provider = gr.Dropdown(
					choices=list(PROVIDER_MODELS.keys()),
					label='Provider',
					value='openai',
				)
				model = gr.Dropdown(
					choices=PROVIDER_MODELS['openai'],
					label='Model',
					value='gpt-4.1-mini',
				)
				api_key = gr.Textbox(label='API Key', placeholder='sk-...', type='password')
				task = gr.Textbox(
					label='Task Description',
					placeholder='E.g., Find flights from New York to London for next week',
					lines=3,
				)
				headless = gr.Checkbox(label='Run Headless', value=False)
				submit_btn = gr.Button('Run Task')

			with gr.Column():
				output = gr.Textbox(label='Output', lines=10, interactive=False)

		def update_models(selected_provider: str):
			models = PROVIDER_MODELS.get(selected_provider, [])
			return gr.update(choices=models, value=models[0] if models else '')

		provider.change(fn=update_models, inputs=provider, outputs=model)

		submit_btn.click(
			fn=lambda *args: asyncio.run(run_browser_task(*args)),
			inputs=[task, provider, api_key, model, headless],
			outputs=output,
		)

	return interface


if __name__ == '__main__':
	demo = create_ui()
	demo.launch()
