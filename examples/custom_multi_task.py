import sys
import asyncio
from browser_use import Agent, ChatGoogle, BrowserProfile
from dotenv import load_dotenv
# Import the QueueShutDown exception to handle it specifically
from bubus.service import QueueShutDown

load_dotenv()

async def run_multi_task_sequence(tasks, max_steps_per_task=15):
    """
    Run a sequence of tasks one after another using the same browser session.
    
    Args:
        tasks: List of tasks to run in sequence
        max_steps_per_task: Maximum steps to take for each task
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Configure browser profile with your settings
        profile = BrowserProfile(
            # Update these paths to your own settings
            user_data_dir=r"E:\VS CODE\Browser use\profile",  # your clean profile folder
            profile="Default",
            chrome_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            keep_alive=True,
            enable_default_extensions=True
        )
        
        # Initialize agent with first task
        first_task = tasks[0] if tasks else "Initialize browser"
        
        agent = Agent(
            task=first_task,
            llm=ChatGoogle(model="gemini-2.0-flash"),
            browser_profile=profile
        )
        
        # Run the first task
        try:
            result = await agent.run(max_steps=max_steps_per_task)
            print("\n✅ Task completed. Browser session remains active.")
        except Exception as e:
            print(f"\n❌ Error during initial task: {e}")
            print("Attempting to continue anyway...")
            
            # Reinitialize eventbus if it was shut down
            try:
                from bubus import EventBus
                agent.eventbus = EventBus(name=f'Agent_{str(agent.id)[-4:]}_restarted')
            except Exception as inner_e:
                print(f"Failed to reinitialize event bus: {inner_e}")
                return 1
        
        # Process remaining tasks in sequence
        for i, task in enumerate(tasks[1:], start=2):
            try:
                print(f"\n🔄 Task {i}/{len(tasks)}: {task}")
                
                # Reset consecutive failures counter
                agent.state.consecutive_failures = 0
                
                # Try to reinitialize eventbus with unique name for this task
                try:
                    from bubus import EventBus
                    agent.eventbus = EventBus(name=f'Agent_{str(agent.id)[-4:]}_task_{i}')
                except Exception as e:
                    print(f"Warning: Could not reinitialize event bus: {e}")
                
                # Add new task to the agent
                agent.add_new_task(task)
                
                # Run the task
                result = await agent.run(max_steps=max_steps_per_task)
                print("\n✅ Task completed. Browser session remains active.")
                
            except QueueShutDown:
                print("\n⚠️ Event queue was shut down. Attempting to continue...")
                # Try to reinitialize eventbus again with a different name
                try:
                    from bubus import EventBus
                    agent.eventbus = EventBus(name=f'Agent_{str(agent.id)[-4:]}_retry_{i}')
                    # Continue to next task
                except Exception as retry_e:
                    print(f"Failed to reinitialize event bus after shutdown: {retry_e}")
                    # Break out of the loop if we can't recover
                    break
                    
            except Exception as e:
                print(f"\n❌ Error during task {i}: {e}")
                choice = input("Continue to next task? (y/n): ")
                if choice.lower() != 'y':
                    break
        
        # Final cleanup
        try:
            await agent.close()
            print("Browser resources cleaned up.")
        except Exception as cleanup_error:
            print(f"Warning during cleanup: {cleanup_error}")
            
        return 0
        
    except Exception as e:
        print(f"Fatal error: {type(e).__name__}: {e}")
        return 1

async def main():
    # Define your list of tasks to run in sequence
    tasks = [
        "Go to GeeksforGeeks data structures and algorithms",
        "Search for Python on GeeksforGeeks",
        "Go to Stack Overflow and search for 'browser automation'",
        "Go to GitHub and search for 'browser-use'"
    ]
    
    # Alternatively, you could get tasks from user input
    # tasks = []
    # while True:
    #     task = input("Enter a task (or 'done' when finished): ")
    #     if task.lower() == 'done':
    #         break
    #     tasks.append(task)
    
    exit_code = await run_multi_task_sequence(tasks)
    return exit_code

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
