import asyncio
import os
from dataclasses import dataclass
from typing import List, Optional
import logging
# Third-party imports
import gradio as gr
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Local module imports
from browser_use import Agent

load_dotenv()

logger = logging.getLogger(__name__)

@dataclass
class ActionResult:
	is_done: bool
	extracted_content: Optional[str]
	error: Optional[str]
	include_in_memory: bool


@dataclass
class AgentHistoryList:
	all_results: List[ActionResult]
	all_model_outputs: List[dict]

	def __str__(self) -> str:
			# Customize the string representation
			results = "\n".join(
				f"Step {i + 1}: {result.extracted_content or 'No content'}"
				for i, result in enumerate(self.all_results)
			)
			return f"Agent History:\n{results}"

def parse_agent_history(history_str: str) -> None:
	console = Console()

	# Split the content into sections based on ActionResult entries
	sections = history_str.split('ActionResult(')

	for i, section in enumerate(sections[1:], 1):  # Skip first empty section
		# Extract relevant information
		content = ''
		if 'extracted_content=' in section:
			content = section.split('extracted_content=')[1].split(',')[0].strip("'")

		if content:
			header = Text(f'Step {i}', style='bold blue')
			panel = Panel(content, title=header, border_style='blue')
			console.print(panel)
			console.print()


async def run_browser_task(
	task: str,
	api_key: str,
	model: str = 'gpt-4',
	headless: bool = True,
) -> str:
	if not api_key.strip():
		return 'Please provide an API key'

	os.environ['OPENAI_API_KEY'] = api_key

	try:
		# Initialize the LLM
		llm = ChatOpenAI(model=model)
		planner_llm = ChatOpenAI(model=model)  # Use same model for planner
		logger.info(f"LLM initialized: {llm}")
		if llm is None:
			raise ValueError("Failed to initialize LLM. Check your API key and model configuration.")
		agent = Agent(
			task=task,
			llm=llm,
			planner_llm=planner_llm,  # Enable planner
			planner_interval=1,  # Run planner every step
			use_vision=False,  # Disable vision capabilities
		)
		result = await agent.run()

		# Ensure we always return a string
		if isinstance(result, AgentHistoryList):
			return str(result)
		return str(result)  # Convert any other type to string
	except Exception as e:
		return f'Error: {str(e)}'


def create_ui():
    with gr.Blocks(title='Browser Use GUI') as interface:
        gr.Markdown('# Browser Use Task Automation')

        with gr.Row():
            with gr.Column():
                api_key = gr.Textbox(label='OpenAI API Key', placeholder='sk-...', type='password')
                task = gr.Textbox(
                    label='Task Description',
                    placeholder='E.g., Find flights from New York to London for next week',
                    lines=3,
                )
                model = gr.Dropdown(choices=['gpt-4', 'gpt-3.5-turbo'], label='Model', value='gpt-4')
                headless = gr.Checkbox(label='Run Headless', value=True)
                submit_btn = gr.Button('Run Task')

            with gr.Column():
                output = gr.Textbox(label='Output', lines=10, interactive=False)

        # Pass all inputs, including the model, to run_browser_task
        submit_btn.click(
            fn=lambda *args: asyncio.run(run_browser_task(*args)),
            inputs=[task, api_key, model, headless],  # Ensure model is included here
            outputs=output,
        )

    return interface


if __name__ == '__main__':
	demo = create_ui()
	demo.launch()
