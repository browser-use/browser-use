#!/usr/bin/env python3
"""
Dynamic Parallel Orchestrator with Beautiful Terminal Interface
A multi-agent system that can handle any natural language task by automatically
splitting it into optimal subtasks and executing them in parallel.
"""

import asyncio
import os
import sys

# Check for rich library
try:
    from rich import box
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.text import Text
except ImportError:
    print("Installing rich library for beautiful terminal interface...")
    os.system("pip install rich")
    from rich import box
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel

from base_agent import BaseAgent
from shared_memory import SharedMemory

# Initialize rich console
console = Console()

def show_banner():
    """Display the beautiful ASCII art banner."""
    console = Console()
    banner = """
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
║                                                                                                       ║
║                             [bold red]PARALLEL AGENTS[/bold red]                                      ║
║                                                                                                       ║
║  Multi-Agent Browser Automation System                                                                ║
║  Powered by Gemini AI & Browser-Use Framework                                                         ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════════════╝
"""
    console.print(banner)

def get_user_task():
    """Get the task from user input with beautiful prompt."""
    console.print("\n[bold cyan]🎯 Enter your task:[/bold cyan]")
    console.print("[dim]Example: 'Find the ages of Elon Musk and Sam Altman'[/dim]")
    console.print("[dim]Example: 'When were Apple and Microsoft founded?'[/dim]\n")
    
    task = input("> ").strip()
    if not task:
        console.print("[red]❌ No task provided. Exiting...[/red]")
        sys.exit(1)
    
    return task

def create_progress_layout():
    """Create the progress layout with spinning animation."""
    layout = Layout()
    
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="progress", size=5),
        Layout(name="status", size=3),
        Layout(name="output", ratio=1)
    )
    
    return layout

def update_progress_layout(layout, task, status, progress_percent, output_text=""):
    """Update the progress layout with current status."""
    # Header
    layout["header"].update(Panel(
        f"[bold blue]🎯 Task:[/bold blue] {task}",
        box=box.ROUNDED,
        border_style="blue"
    ))
    
    # Progress bar
    progress_panel = Panel(
        f"[bold green]🔄 Progress:[/bold green] {progress_percent}%",
        box=box.ROUNDED,
        border_style="green"
    )
    layout["progress"].update(progress_panel)
    
    # Status
    status_panel = Panel(
        f"[bold yellow]📊 Status:[/bold yellow] {status}",
        box=box.ROUNDED,
        border_style="yellow"
    )
    layout["status"].update(status_panel)
    
    # Output
    if output_text:
        output_panel = Panel(
            f"[bold white]📄 Results:[/bold white]\n{output_text}",
            box=box.ROUNDED,
            border_style="white"
        )
        layout["output"].update(output_panel)

def save_shared_memory_to_file(results):
    """Save the shared memory contents to a JSON file for debugging."""
    filename = 'shared_memory_contents.txt'
    
    with open(filename, 'w') as f:
        f.write("SHARED MEMORY CONTENTS\n")
        f.write("=" * 30 + "\n\n")
        
        for person, result in results.items():
            f.write(f"{person}:\n")
            f.write(str(result))
            f.write("\n\n" + "-" * 50 + "\n\n")

def save_clean_results_to_file(results):
    """Save only the clean, final answers to a simple file."""
    filename = "final_answers.txt"
    
    with open(filename, 'w') as f:
        f.write("FINAL ANSWERS\n")
        f.write("=" * 30 + "\n\n")
        
        for person, result in results.items():
            # Extract the final clean answer
            if hasattr(result, 'all_results') and result.all_results:
                # Look for the final "done" result
                final_answer = None
                for action_result in reversed(result.all_results):
                    if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                        content = action_result.extracted_content
                        if isinstance(content, str) and ("years old" in content or "age" in content.lower()):
                            final_answer = content
                            break
                
                if final_answer:
                    f.write(f"{person}: {final_answer}\n\n")
                else:
                    f.write(f"{person}: Task completed but no final answer found\n\n")
            else:
                f.write(f"{person}: {str(result)}\n\n")

async def run_with_interface():
    """Run the parallel orchestrator with beautiful interface."""
    # Show banner
    show_banner()
    
    # Get user task
    task = get_user_task()
    
    # Check API key
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        console.print("[red]❌ Error: GOOGLE_API_KEY environment variable not set.[/red]")
        console.print("[yellow]Please set it with: export GOOGLE_API_KEY='your-key-here'[/yellow]")
        return
    
    console.print(f"[green]✅ Using API key: {api_key[:10]}...[/green]\n")
    
    # Initialize shared memory
    shared_memory = SharedMemory()
    
    # Create progress layout
    layout = create_progress_layout()
    
    # Start the live display
    with Live(layout, refresh_per_second=4, screen=True):
        try:
            # Initialize base agent
            update_progress_layout(layout, task, "Initializing Base Agent...", 10)
            base_agent = BaseAgent(api_key=api_key, model='gemini-1.5-flash', headless=True)
            await base_agent.initialize()
            
            # Start task processing
            update_progress_layout(layout, task, "Analyzing and splitting task...", 20)
            
            # Process the task
            results = await base_agent.process_task(task)
            
            # Update progress
            update_progress_layout(layout, task, "Aggregating results...", 90)
            
            # Display final results
            if results:
                final_output = ""
                for key, result in results.items():
                    if hasattr(result, 'all_results') and result.all_results:
                        # Extract the final clean answer
                        final_answer = None
                        for action_result in reversed(result.all_results):
                            if hasattr(action_result, 'result') and action_result.result:
                                final_answer = str(action_result.result)
                                break
                        
                        if final_answer:
                            final_output += f"[bold green]✅ {key}:[/bold green] {final_answer}\n\n"
                        else:
                            final_output += f"[bold red]❌ {key}:[/bold red] No result found\n\n"
                    else:
                        final_output += f"[bold yellow]⚠️ {key}:[/bold yellow] {result}\n\n"
                
                update_progress_layout(layout, task, "✅ Task completed successfully!", 100, final_output)
                
                # Save to file
                with open('final_answers.txt', 'w') as f:
                    f.write("FINAL ANSWERS\n")
                    f.write("=" * 30 + "\n\n")
                    f.write(final_output)
                
                console.print("\n[bold green]💾 Results saved to: final_answers.txt[/bold green]")
            else:
                update_progress_layout(layout, task, "❌ No results obtained", 100, "Task failed to produce results")
            
        except Exception as e:
            update_progress_layout(layout, task, f"❌ Error: {str(e)}", 100, f"Task failed with error: {str(e)}")
            console.print(f"\n[red]❌ Error: {str(e)}[/red]")
        
        finally:
            # Cleanup
            try:
                await base_agent.cleanup()
            except:
                pass

async def main():
    """Main function to run the parallel orchestrator."""
    # Show the beautiful banner
    show_banner()
    
    # Check for API key
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key or api_key == "YOUR_API_K...":
        # Get API key from environment variable
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            print("❌ Error: GOOGLE_API_KEY environment variable not set.")
            print("Please set it with: export GOOGLE_API_KEY='your-key-here'")
            sys.exit(1)
        print("✅ API key found!")
    else:
        print("✅ API key found!")
    
    # Ensure the API key is set in environment
    os.environ['GOOGLE_API_KEY'] = api_key
    
    # Get task from user input
    task = get_user_task()
    print(f"🔄 Processing: {task}")
    print("🔄 Spinning up worker agents...\n")
    
    # Create shared memory
    shared_memory = SharedMemory()
    
    # Create base agent with the API key
    base_agent = BaseAgent(
        api_key=api_key,
        model='gemini-1.5-flash',
        max_workers=10,
        headless=True
    )
    
    try:
        # Process the task
        results = await base_agent.process_task(task)
        
        # Save the shared memory contents to a JSON file
        save_shared_memory_to_file(results)
        
        # Save clean results to a simple file
        save_clean_results_to_file(results)
        
        # Display final results
        print("\n🎯 FINAL RESULTS")
        print("=" * 50)
        
        for person, result in results.items():
            if hasattr(result, 'all_results') and result.all_results:
                # Extract the final clean answer
                final_answer = None
                for action_result in reversed(result.all_results):
                    if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
                        content = action_result.extracted_content
                        if isinstance(content, str) and ("years old" in content or "age" in content.lower()):
                            final_answer = content
                            break
                
                if final_answer:
                    print(f"✅ {person}: {final_answer}")
                else:
                    print(f"⚠️  {person}: Task completed but no final answer found")
            else:
                print(f"❌ {person}: {str(result)}")
        
        print("=" * 50)
        print("✅ Task completed! Results saved to final_answers.txt")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
