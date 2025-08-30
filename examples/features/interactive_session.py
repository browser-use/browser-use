"""
Example: Interactive session with follow-up tasks

This example shows how to build your own interactive loop where:
1. Browser session stays alive between tasks
2. User can input multiple tasks sequentially
3. Each task builds on the previous browser state

This pattern is useful for:
- Building custom chat interfaces
- Scripted automation with multiple steps
- Testing scenarios where you need session persistence
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI


async def interactive_browser_session():
    """
    Create an interactive browser session that accepts multiple tasks.
    """
    
    # Set up LLM
    llm = ChatOpenAI(model='gpt-4o-mini', temperature=0.0)
    
    # Create persistent browser session
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,  # Set to True for headless mode
            keep_alive=True,  # Critical: keeps browser alive between tasks
            user_data_dir='~/.config/browseruse/profiles/interactive',
        )
    )
    
    print("🚀 Starting browser session...")
    await browser_session.start()
    
    agent = None
    task_count = 0
    
    print("""
🌟 Interactive Browser Session Started!
Type your tasks one by one. The browser will stay open between tasks.
Type 'exit' or 'quit' to end the session.

Example tasks:
- "go to reddit.com"
- "what's the first post about?"
- "go to github.com and search for browser-use"
- "click on the first result"
""")
    
    try:
        while True:
            # Get task from user
            task = input(f"\n📝 Task #{task_count + 1}: ").strip()
            
            if task.lower() in ['exit', 'quit', '']:
                print("👋 Ending session...")
                break
                
            task_count += 1
            print(f"🏃 Running task: {task}")
            
            if agent is None:
                # First task: create new agent
                agent = Agent(
                    task=task,
                    llm=llm,
                    browser_session=browser_session,
                )
            else:
                # Subsequent tasks: add to existing agent
                agent.add_new_task(task)
            
            # Run the task
            try:
                history = await agent.run()
                
                if history.is_successful():
                    print(f"✅ Task completed successfully!")
                    if history.final_result():
                        print(f"📄 Result: {history.final_result()}")
                else:
                    print(f"❌ Task failed or was incomplete")
                    
            except Exception as e:
                print(f"💥 Error running task: {e}")
                
    except KeyboardInterrupt:
        print("\n🛑 Session interrupted by user")
        
    finally:
        # Clean up
        print("🧹 Cleaning up browser session...")
        await browser_session.kill()
        print("✅ Session ended")


async def automated_follow_up_demo():
    """
    Demonstration with predefined follow-up tasks.
    """
    
    llm = ChatOpenAI(model='gpt-4o-mini', temperature=0.0)
    
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            keep_alive=True,
            user_data_dir='~/.config/browseruse/profiles/demo',
        )
    )
    
    await browser_session.start()
    
    # Define a sequence of related tasks
    tasks = [
        "Navigate to reddit.com",
        "What is the title of the first post on the homepage?",
        "Scroll down to see more posts",
        "How many posts are visible on the page now?",
    ]
    
    agent = None
    
    try:
        for i, task in enumerate(tasks, 1):
            print(f"\n📝 Task {i}/{len(tasks)}: {task}")
            
            if agent is None:
                agent = Agent(
                    task=task,
                    llm=llm,
                    browser_session=browser_session,
                )
            else:
                agent.add_new_task(task)
            
            history = await agent.run()
            
            print(f"✅ Task {i} completed: {history.is_successful()}")
            if history.final_result():
                print(f"📄 Result: {history.final_result()}")
                
            # Brief pause between tasks
            await asyncio.sleep(1)
            
    finally:
        await browser_session.kill()


if __name__ == '__main__':
    print("🌟 Interactive Session Examples")
    print("="*50)
    
    mode = input("""
Choose mode:
1. Interactive (you type tasks)
2. Automated demo (predefined tasks)

Enter 1 or 2: """).strip()
    
    if mode == "1":
        asyncio.run(interactive_browser_session())
    elif mode == "2":
        print("\n🤖 Running automated demo...")
        asyncio.run(automated_follow_up_demo())
    else:
        print("Invalid choice. Please run again and choose 1 or 2.")