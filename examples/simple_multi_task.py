import sys
import asyncio
from browser_use import Agent, ChatGoogle, BrowserProfile
from dotenv import load_dotenv

load_dotenv()

async def run_task_sequence(agent, tasks, max_steps_per_task=15):
    """
    Run a sequence of tasks with the same agent instance.
    """
    for i, task in enumerate(tasks):
        print(f"\n🔄 Running task {i+1}/{len(tasks)}: {task}")
        
        # Reset agent state for new task
        agent.state.consecutive_failures = 0
        
        # Make sure we have a valid eventbus
        try:
            # Dynamically import bubus to handle potential missing modules
            import importlib
            bubus = importlib.import_module('bubus')
            # Create a new eventbus with a unique name for this task
            agent.eventbus = bubus.EventBus(name=f'Agent_{str(agent.id)[-4:]}_task_{i+1}')
        except Exception as e:
            print(f"Warning: Could not reinitialize event bus: {e}")
        
        # Add task to agent
        if i == 0:
            # First task - set it directly
            agent.task = task
            agent._message_manager.add_new_task(task)
        else:
            # Follow-up tasks - use add_new_task
            agent.add_new_task(task)
        
        # Run the task
        try:
            await agent.run(max_steps=max_steps_per_task)
            print(f"\n✅ Task {i+1} completed successfully!")
        except Exception as e:
            print(f"\n❌ Error during task {i+1}: {e}")
            choice = input("Continue to next task? (y/n): ")
            if choice.lower() != 'y':
                return False
    
    return True

async def main():
    try:
        # Configure browser profile
        profile = BrowserProfile(
            user_data_dir=r"E:\VS CODE\Browser use\profile",  # Your profile folder
            profile="Default",
            chrome_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            keep_alive=True,
            enable_default_extensions=True
        )
        
        # Create agent with dummy initial task
        agent = Agent(
            task="Initialize browser",
            llm=ChatGoogle(model="gemini-2.0-flash"),
            browser_profile=profile
        )
        
        # Option 1: Predefined task list
        tasks = [
            "Go to GeeksforGeeks data structures and algorithms",
            "Search for Python on GeeksforGeeks",
            "Go to Stack Overflow and search for 'browser automation'",
            "Go to GitHub and search for 'browser-use'"
        ]
        
        # Option 2: Get tasks from user input
        use_custom_tasks = input("Do you want to enter custom tasks? (y/n): ").lower() == 'y'
        if use_custom_tasks:
            tasks = []
            print("Enter tasks, one per line. Type 'done' when finished:")
            while True:
                task = input("> ")
                if task.lower() == 'done':
                    break
                tasks.append(task)
        
        # Run the tasks
        success = await run_task_sequence(agent, tasks)
        
        # Clean up
        await agent.close()
        print("\nBrowser session closed.")
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"Fatal error: {type(e).__name__}: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
