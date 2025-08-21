#!/usr/bin/env python3
"""
Interactive Terminal Interface for Parallel Orchestrator
A beautiful terminal interface with live dashboard and progress tracking.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

# Check for rich library
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
    from rich.live import Live
    from rich.layout import Layout
    from rich.text import Text
    from rich.table import Table
    from rich import box
    from rich.tree import Tree
    from rich.columns import Columns
except ImportError:
    print("Installing rich library for beautiful terminal interface...")
    os.system("pip install rich")
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
    from rich.live import Live
    from rich.layout import Layout
    from rich.text import Text
    from rich.table import Table
    from rich import box
    from rich.tree import Tree
    from rich.columns import Columns

from base_agent import BaseAgent
from shared_memory import SharedMemory

def show_banner():
    """Display the beautiful ASCII art banner."""
    console = Console(force_terminal=True, color_system="truecolor")
    banner = """
[bold red]
╔═══════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                                       ║
║  ██████╗  ██████╗   ██████╗  ██╗    ██╗ ███████╗  ███████╗ ██████╗      ██╗   ██╗  ███████╗  ███████╗ ║
║  ██╔══██╗ ██╔══██╗ ██╔═══██╗ ██║    ██║ ██╔════╝  ██╔════╝ ██╔══██╗     ██║   ██║  ██╔════╝  ██╔════╝ ║
║  ██████╔╝ ██████╔╝ ██║   ██║ ██║ █╗ ██║ ███████╗  █████╗   ██████╔╝     ██║   ██║  ███████╗  █████╗   ║
║  ██╔══██╗ ██╔══██╗ ██║   ██║ ██║███╗██║ ╚════██║  ██╔══╝   ██╔══██╗     ██║   ██║  ╚════██║  ██╔══╝   ║
║  ██████╔╝ ██║  ██║ ╚██████╔╝ ╚███╔███╔╝ ███████║  ███████╗ ██║  ██║     ╚██████╔╝  ███████║  ███████╗ ║
║  ╚═════╝  ╚═╝  ╚═╝  ╚═════╝   ╚══╝╚══╝  ╚══════╝  ╚══════╝ ╚═╝  ╚═╝      ╚═════╝   ╚══════╝  ╚══════╝ ║
║                                                                                                       ║
║                                                                                                       ║                                                                                                     
║                                           [bold blue]PARALLEL AGENTS[/bold blue]                                             ║                                                     
║                                                                                                       ║
║  Multi-Agent Browser Automation System                                                                ║
║  Powered by Gemini AI & Browser-Use Framework                                                         ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════╝
[/bold red]
"""
    console.print(banner)

def get_user_task():
    """Get the task from user input with beautiful prompt."""
    console = Console(force_terminal=True, color_system="truecolor")
    console.print("\n[bold cyan]Enter your task:[/bold cyan]")
    console.print("[dim]Example: 'Find the ages of Elon Musk and Sam Altman'[/dim]")
    console.print("[dim]Example: 'When were Apple, Microsoft and Google founded?'[/dim]\n")
    
    task = input("> ").strip()
    if not task:
        console.print("[red]No task provided. Exiting...[/red]")
        sys.exit(1)
    
    return task

def _status_to_renderable(name: str, status: str):
    status_lower = (status or "").lower()
    if "running" in status_lower:
        return Text(f"{name} [yellow](running)[/yellow]")
    if "done" in status_lower or "completed" in status_lower:
        return Text(f"{name} [green](done)[/green]")
    if "failed" in status_lower or "error" in status_lower:
        return Text(f"{name} [red](failed)[/red]")
    if "assigned" in status_lower or "created" in status_lower:
        return Text(f"{name} [cyan]({status})[/cyan]")
    return Text(f"{name} [dim]({status or 'pending'})[/dim]")

async def build_subtask_tree(shared_memory: SharedMemory) -> Tree:
    main_task = await shared_memory.get("task_start")
    task_status = await shared_memory.get("task_status")
    total_tasks = await shared_memory.get("total_tasks") or 0
    completed_tasks = await shared_memory.get("completed_tasks") or 0

    header = Text.assemble(
        ("Main Task: ", "bold"),
        (str(main_task or "(none)"), "bold blue"),
        (f"  [{completed_tasks}/{total_tasks}] ", "dim"),
        (f"{task_status or ''}", "yellow")
    )
    tree = Tree(header)

    for i in range(1, int(total_tasks) + 1):
        subtask_name = await shared_memory.get(f"task_{i}") or f"Subtask {i}"
        subtask_status = await shared_memory.get(f"task_{i}_status") or await shared_memory.get(f"worker_{i}_status") or "Pending"
        node_label = _status_to_renderable(str(subtask_name), str(subtask_status))
        tree.add(node_label)

    return tree

class TerminalInterface:
    def __init__(self):
        # Set the API key directly
        api_key = "AIzaSyA5_5u1A7ynST0rOn5QWrO1EH4sHqnyJVw"
        os.environ['GOOGLE_API_KEY'] = api_key
        print("API key set successfully!")
        
        self.console = Console(force_terminal=True, color_system="truecolor")
        self.shared_memory = SharedMemory()
        
        # Create base agent (share memory instance)
        self.base_agent = BaseAgent(
            api_key=api_key,
            model='gemini-1.5-flash',
            max_workers=10,
            headless=False,
            shared_memory=self.shared_memory
        )
    
    def show_banner(self):
        """Display the beautiful ASCII art banner."""
        show_banner()
    
    async def display_final_results(self):
        """Display only the final cleaned answer in a simple format."""
        final_answer = await self.shared_memory.get("final_cleaned_answer")
        if not final_answer:
            final_answer = "No final answer available."
        self.console.print(Panel(str(final_answer), title="Final Answer", border_style="green"))
    
    async def run_task(self, task):
        """Run a single task with a static subtask tree snapshot (no live updates)."""
        try:
            # Seed shared memory header and suppress log noise
            await self.shared_memory.set("task_start", task)
            await self.shared_memory.set("task_status", "Starting")
            logging.disable(logging.CRITICAL)

            # Begin processing in background
            process = asyncio.create_task(self.base_agent.process_task(task))

            # Wait until subtasks are available to render a single snapshot
            for _ in range(300):  # up to ~30s
                total_tasks = await self.shared_memory.get("total_tasks")
                if total_tasks and int(total_tasks) > 0:
                    break
                await asyncio.sleep(0.1)

            # One-time snapshot of the task tree (initial)
            initial_tree = await build_subtask_tree(self.shared_memory)
            self.console.print(Panel(initial_tree, title="Task Progress", border_style="cyan"))

            # Wait for processing to complete silently
            await process
            logging.disable(logging.NOTSET)

            # Update snapshot to show Done/Failed statuses before final answer
            final_tree = await build_subtask_tree(self.shared_memory)
            self.console.print(Panel(final_tree, title="Task Progress", border_style="cyan"))

            # Final answer
            await self.display_final_results()
            return await self.shared_memory.get("final_results")

        except Exception as e:
            logging.disable(logging.NOTSET)
            self.console.print(f"[red]Error running task: {e}[/red]")
            return None
    
    async def main_loop(self):
        """Main interactive loop."""
        self.show_banner()
        
        while True:
            try:
                # Get task from user
                task = get_user_task()
                
                # Run the task
                results = await self.run_task(task)
                
                # Do not show completion banners; only tree + final answer
                
                # Ask if user wants to continue
                self.console.print("\n[bold cyan]Would you like to run another task? (y/n):[/bold cyan]")
                continue_choice = input("> ").strip().lower()
                
                if continue_choice not in ['y', 'yes']:
                    self.console.print("[bold blue]👋 Goodbye![/bold blue]")
                    break
                    
            except KeyboardInterrupt:
                self.console.print("\n[bold blue]Goodbye![/bold blue]")
                break
            except Exception as e:
                self.console.print(f"[red]Unexpected error: {e}[/red]")

async def main():
    """Main entry point."""
    interface = TerminalInterface()
    await interface.main_loop()

if __name__ == "__main__":
    asyncio.run(main()) 