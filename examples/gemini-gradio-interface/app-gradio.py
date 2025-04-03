import asyncio
import os
from dataclasses import dataclass
from typing import List, Optional
from pydantic import SecretStr
import gradio as gr
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from browser_use import Agent
load_dotenv()
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
	model: str = 'gemini-1.5-flash-latest',
	headless: bool = True,
) -> str:
	if not api_key.strip():
		return 'Please provide an API key'

	os.environ['GEMINI_API_KEY'] = api_key

	try:
		agent = Agent(
			task=task,
			llm= ChatGoogleGenerativeAI(model=model, api_key=SecretStr(api_key)),
		 
		)
		result = await agent.run()
		
		return result
	except Exception as e:
		return f'Error: {str(e)}'


def create_ui():
	with gr.Blocks(title='Browser Use GUI', css="footer {visibility: hidden} #header {text-align: center; padding: 20px; background: linear-gradient(to right, #2193b0, #6dd5ed); color: white; margin-bottom: 20px;} #welcome {text-align: center; margin: 20px 0; font-size: 1.2em;} #custom-footer {text-align: center; padding: 15px; background: linear-gradient(to right, #141e30, #243b55); color: white; margin-top: 20px; font-family: 'Arial', sans-serif;}") as interface:
		# Header
		gr.HTML("""
			<div id="header">
				<h1 style="margin: 0; font-size: 2.5em;">🤖 Browser Task Automation</h1>
				<p style="margin: 10px 0 0 0;">Your AI-Powered Browser Assistant</p>
			</div>
		""")
		
		# Welcome Message
		gr.HTML("""
			<div id="welcome">
				<p>Welcome to our intelligent browser automation platform. Let AI handle your web tasks efficiently and securely.</p>
			</div>
		""")

		with gr.Row():
			# Left Column - Examples Panel
			with gr.Column(scale=1):
				gr.HTML("""
					<div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
						<h3 style="color: #1a73e8; margin-top: 0;">📋 Example Tasks</h3>
						<div style="margin: 10px 0;">
							<p style="font-weight: bold; color: #202124;">Web Research:</p>
							<ul style="list-style-type: none; padding-left: 10px; color: #5f6368;">
								<li>• Find latest AI news on TechCrunch</li>
								<li>• Compare prices for iPhone 15 Pro</li>
								<li>• Research climate change statistics</li>
							</ul>
						</div>
						<div style="margin: 10px 0;">
							<p style="font-weight: bold; color: #202124;">Data Collection:</p>
							<ul style="list-style-type: none; padding-left: 10px; color: #5f6368;">
								<li>• Extract product reviews from Amazon</li>
								<li>• Gather contact info from company websites</li>
								<li>• Collect real estate listings data</li>
							</ul>
						</div>
						<div style="margin: 10px 0;">
							<p style="font-weight: bold; color: #202124;">Automation:</p>
							<ul style="list-style-type: none; padding-left: 10px; color: #5f6368;">
								<li>• Fill out contact forms</li>
								<li>• Schedule appointments</li>
								<li>• Monitor price changes</li>
							</ul>
						</div>
					</div>
				""")

			# Middle Column - Input Controls
			with gr.Column(scale=2):
				api_key = gr.Textbox(label='Gemini API Key', placeholder='AI...', type='password')
				task = gr.Textbox(
					label='Task Description',
					placeholder='E.g., Find flights from New York to London for next week',
					lines=3,
				)
				model = gr.Dropdown(
					choices=[
						'gemini-1.5-flash-latest',
						'gemini-2.0-flash-exp',
						'gemini-1.5-flash-002',
						'gemini-1.5-flash-8b',
						'gemini-1.5-pro-latest',
						'gemini-1.5-pro-002',
						'gemini-exp-1206'
					],
					label='Model',
					value='gemini-1.5-flash-latest'
				)
				headless = gr.Checkbox(label='Run Headless', value=True)
				submit_btn = gr.Button('Run Task')

			# Right Column - Output
			with gr.Column(scale=2):
				output = gr.Textbox(label='Output', lines=10, interactive=False)

		submit_btn.click(
			fn=lambda api_key, task, model, headless: asyncio.run(run_browser_task(task, api_key, model, headless)),
			inputs=[api_key, task, model, headless],
			outputs=output,
		)

		# Custom Footer
		gr.HTML("""
			<div id="custom-footer">
				<p style="margin: 0;">
					<span style="font-size: 1.1em; font-weight: bold;color:white">Falah.G.Salieh</span>
					<span style="margin: 0 10px;">|</span>
					<span style="color: #4fc3f7;">Powered by Browser Use AI Agent</span>
					<span style="margin: 0 10px;">|</span>
					<span style="margin: 0 10px;">|</span>
					<span style="font-size: 0.9em;">© 2025</span>
				</p>
			</div>
		""")

	return interface


if __name__ == '__main__':
	demo = create_ui()
	demo.launch()
