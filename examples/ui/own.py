import os
import asyncio
from dataclasses import dataclass
from typing import List, Optional

# Third-party imports
import gradio as gr
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Local module import (assumes browser_use is installed)
from browser_use import Agent

# Load environment variables (including any defaults from a .env file)
load_dotenv()

# Global variable to store the currently running interactive agent
active_agent = None

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
    sections = history_str.split('ActionResult(')
    for i, section in enumerate(sections[1:], 1):
        content = ''
        if 'extracted_content=' in section:
            content = section.split('extracted_content=')[1].split(',')[0].strip("'")
        if content:
            header = Text(f'Step {i}', style='bold blue')
            panel = Panel(content, title=header, border_style='blue')
            console.print(panel)
            console.print()

# Create an InteractiveAgent subclass that simulates a multi-step process
class InteractiveAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A queue for receiving new commands during processing.
        self.interrupt_queue = asyncio.Queue()
        # A string to accumulate output that will be streamed.
        self.output = ""

    async def run_interactive(self):
        """
        Simulate a task divided into 5 steps.
        Before each step, process any interrupts (new commands).
        Yield the current output after each step.
        """
        for i in range(5):
            # Process any commands that have been sent
            await self.process_interrupts()
            # Simulate work for the step (replace with real agent logic)
            self.output += f"Step {i+1}: processing...\n"
            # Yield current output to update the UI
            yield self.output
            # Simulate a delay between steps
            await asyncio.sleep(2)
        yield self.output  # Final output

    async def process_interrupts(self):
        """Check and process all commands in the interrupt queue."""
        while not self.interrupt_queue.empty():
            cmd = await self.interrupt_queue.get()
            self.output += f"--> Received command: {cmd}\n"

async def run_interactive_task(
    task: str,
    api_key: str,
    model: str = 'gpt-4',
    headless: bool = True,
) -> str:
    """
    Set up the OpenAI API key (using the same method as your working code),
    then create and run an InteractiveAgent that streams its output.
    """
    global active_agent
    if not api_key.strip():
        yield "Please provide an API key."
        return

    # Use the same method for the OpenAI API key as before:
    os.environ['OPENAI_API_KEY'] = api_key

    try:
        # Create an instance of our InteractiveAgent.
        # (Here we pass the model selected from the UI to ChatOpenAI.)
        active_agent = InteractiveAgent(task=task, llm=ChatOpenAI(model=model))
        # Run the agent interactively and stream the output.
        async for output in active_agent.run_interactive():
            yield output
        active_agent = None  # Clear active_agent when done
    except Exception as e:
        yield f"Error: {str(e)}"

def send_command(new_command: str) -> str:
    """
    When the "Send Command" button is clicked, add the new command to the
    active agent's interrupt queue.
    """
    global active_agent
    if active_agent is None:
        return "No active agent to receive commands."
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(active_agent.interrupt_queue.put(new_command))
        return f"Command '{new_command}' sent."
    except Exception as e:
        return f"Error sending command: {e}"

def create_ui():
    with gr.Blocks(title="Browser Use Interactive GUI") as interface:
        gr.Markdown("# Browser Use Task Automation with Real-Time Commands")

        with gr.Row():
            with gr.Column():
                # These inputs match your original method for setting the API key.
                api_key = gr.Textbox(label="OpenAI API Key", placeholder="sk-...", type="password")
                task = gr.Textbox(
                    label="Task Description",
                    placeholder="E.g., Find flights from New York to London for next week",
                    lines=3,
                )
                model = gr.Dropdown(choices=["gpt-4", "gpt-3.5-turbo"], label="Model", value="gpt-4")
                headless = gr.Checkbox(label="Run Headless", value=True)
                run_btn = gr.Button("Run Task")
                command_box = gr.Textbox(label="New Command", placeholder="Enter additional instructions")
                send_btn = gr.Button("Send Command")
            with gr.Column():
                output = gr.Textbox(label="Output", lines=15, interactive=False)

        # Use Gradio's streaming support: run_btn.click will stream output from run_interactive_task.
        run_btn.click(
            fn=run_interactive_task,
            inputs=[task, api_key, model, headless],
            outputs=output,
        )
        # The "Send Command" button simply calls send_command.
        send_btn.click(
            fn=send_command,
            inputs=command_box,
            outputs=output,
        )

    return interface

if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
