import asyncio
from browser_use import Agent, ChatGoogle

async def main():
    # Initialize with a dummy task - we'll replace it with user input
    agent = Agent(
        task='Initialize browser',
        llm=ChatGoogle(model='gemini-2.0-flash'),
    )
    
    # For the first task
    first_task = input("Enter a task (or 'exit' to quit): ")
    if first_task.lower() == 'exit':
        return
        
    # Run the first task
    try:
        await agent.run(max_steps=20)
        print("\n✅ Task completed. Browser session remains active.")
    except Exception as e:
        print(f"\n❌ Error during initial task: {e}")
        print("Attempting to continue anyway...")
    
    # Keep browser session alive for continued interaction
    while True:
        # Get next task from user
        follow_up = input("\nEnter follow-up task (or 'exit' to quit): ")
        
        # Check for exit command
        if follow_up.lower() in ['exit', 'quit', 'q']:
            print("Exiting browser control mode...")
            break
            
        # Reset consecutive failures counter
        agent.state.consecutive_failures = 0
        
        # Add new task to the agent and run it
        agent.add_new_task(follow_up)
        
        # Try to reinitialize the event bus
        try:
            import importlib
            bubus = importlib.import_module('bubus')
            agent.eventbus = bubus.EventBus(name=f'Agent_{str(agent.id)[-4:]}_task_{len(agent.history.history)}')
        except Exception as e:
            print(f"Warning: Could not reinitialize event bus: {e}")
        
        # Run the follow-up task
        print(f"\n🔄 Running: {follow_up}")
        try:
            await agent.run(max_steps=20)
            print("\n✅ Task completed. Browser session remains active.")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Browser session may be in an inconsistent state.")
            choice = input("Continue anyway? (y/n): ")
            if choice.lower() != 'y':
                break
    
    print("Browser control session ended.")
    
    # Final cleanup - needed to avoid dangling browser processes
    await agent.close()

if __name__ == '__main__':
    asyncio.run(main())