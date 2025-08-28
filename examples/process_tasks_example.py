import sys
import os
import json
import asyncio
from browser_use import Agent, ChatGoogle, BrowserProfile
from dotenv import load_dotenv

load_dotenv()

# Global variable to track the agent for cleanup
agent_instance = None

async def cleanup_agent():
    """Clean up agent resources safely"""
    global agent_instance
    
    if agent_instance:
        try:
            print("\nCleaning up browser resources...")
            await agent_instance.close()
            print("Browser session closed.")
        except Exception as e:
            print(f"Error during cleanup: {e}")

async def main():
    """
    Example of using process_single_task in your own loop.
    This is like manually implementing a 'for' loop to print stars,
    instead of using a function with a 'while' loop inside it.
    """
    global agent_instance
    
    try:
        # Configure browser profile
        profile = BrowserProfile(
            user_data_dir=r"E:\VS CODE\Browser use\profile",  # Update this path
            profile="Default",
            chrome_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",  # Update if needed
            keep_alive=True,
            enable_default_extensions=True
        )
        
        # Create agent with dummy initial task
        agent = Agent(
            task="Initialize browser",  # This will be replaced by the first task
            llm=ChatGoogle(model="gemini-2.0-flash"),
            browser_profile=profile
        )
        
        # Store agent in global variable for cleanup
        agent_instance = agent
        
        # Ask for max_steps configuration
        try:
            max_steps_input = input("\nMaximum steps per task (default: 15): ")
            max_steps = int(max_steps_input) if max_steps_input.strip() else 15
        except ValueError:
            print("Invalid input, using default of 15 steps.")
            max_steps = 15
            
        # Initialize completed tasks list for record-keeping
        completed_tasks = []
        task_count = 0
        
        print("\n===== INTERACTIVE TASK MODE =====")
        print("Enter tasks one by one and see them completed before entering the next task.")
        print("Type 'exit' at any time to quit.")
        
        while True:
            # Get the next task from user
            task_input = input("\n✏️ Enter your task: ")
            
            # Check for exit command
            if task_input.lower() in ['exit', 'quit', 'q']:
                print("Exiting task sequence...")
                break
                
            # Skip empty tasks
            if not task_input.strip():
                print("Task cannot be empty. Try again.")
                continue
                
            task_count += 1
            print(f"\n===== TASK #{task_count} =====")
            print(f"Processing: {task_input}")
            
            # Call process_single_task for this specific task
            success = await agent.process_single_task(task_input, max_steps=max_steps)
            
            # Record task and result
            completed_tasks.append({
                "task": task_input,
                "success": success,
                "timestamp": asyncio.get_event_loop().time()
            })
            
            # Task completion message
            if success:
                print(f"\n✅ Task #{task_count} completed successfully!")
            else:
                print(f"\n❌ Task #{task_count} failed.")
                retry = input("Do you want to try again? (y/n): ")
                if retry.lower() == 'y':
                    task_count -= 1  # Don't count this as a separate task
                    continue
                    
            # Ask if user wants to save task history
            if len(completed_tasks) % 5 == 0:  # Ask every 5 tasks
                save_history = input("\nDo you want to save your task history? (y/n): ")
                if save_history.lower() == 'y':
                    try:
                        with open("task_history.json", 'w') as f:
                            json.dump(completed_tasks, f, indent=2, default=str)
                        print("Task history saved to task_history.json")
                    except Exception as e:
                        print(f"Error saving task history: {e}")
                        
            # Wait a moment before asking for next task to avoid accidental inputs
            print("\nWaiting 2 seconds before next task...")
            await asyncio.sleep(2)
        
        print("\nAll tasks completed!")
        return 0
        
    except KeyboardInterrupt:
        print("\nUser interrupted execution. Cleaning up...")
        return 1
    except Exception as e:
        print(f"\nFatal error: {type(e).__name__}: {e}")
        return 1
    finally:
        # Always try to clean up
        await cleanup_agent()

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nExiting due to keyboard interrupt.")
        # No need to clean up here, the finally block in main() will handle it
    except Exception as e:
        print(f"\nUnhandled exception: {type(e).__name__}: {e}")
        sys.exit(1)
