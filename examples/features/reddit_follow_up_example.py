"""
Example: Follow-up tasks without killing the session

This example demonstrates how to:
1. Go to Reddit (agent completes and calls done())
2. Browser stays open (keep_alive=True)
3. Add a follow-up task: "What's the first post?"
4. Agent continues with the same session

This is the exact pattern you'd get with CLI interactive mode.
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


async def main():
    """
    Demonstrate follow-up tasks with persistent browser session.
    """
    
    # Set up LLM
    llm = ChatOpenAI(model='gpt-4o-mini', temperature=0.0)
    
    # Create a browser session with keep_alive=True
    # This prevents the browser from closing when the first task completes
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,  # Set to True if you don't want to see the browser
            keep_alive=True,  # This is the key setting for follow-up tasks
            user_data_dir='~/.config/browseruse/profiles/reddit_demo',  # Reuse profile
        )
    )
    
    print("🚀 Starting browser session...")
    await browser_session.start()
    
    # Initial task: Go to Reddit
    initial_task = "Navigate to reddit.com and wait for the page to load"
    
    agent = Agent(
        task=initial_task,
        llm=llm,
        browser_session=browser_session,  # Pass the existing session
    )
    
    print(f"📝 Running initial task: {initial_task}")
    history1 = await agent.run()
    
    print(f"✅ Initial task completed! Success: {history1.is_successful()}")
    print(f"📍 Current URL: {history1.final_result()}")
    print("\n" + "="*50)
    print("🔄 Browser session is still alive! Adding follow-up task...")
    print("="*50 + "\n")
    
    # Follow-up task: Analyze the first post
    # The browser stays open and we can continue working
    follow_up_task = "Look at the first post on the Reddit homepage and tell me what it's about"
    
    print(f"📝 Adding follow-up task: {follow_up_task}")
    agent.add_new_task(follow_up_task)
    
    # Run the follow-up task
    history2 = await agent.run()
    
    print(f"✅ Follow-up task completed! Success: {history2.is_successful()}")
    print(f"📄 Result: {history2.final_result()}")
    
    # You could add more follow-up tasks here...
    # agent.add_new_task("Click on the first post and read the comments")
    # await agent.run()
    
    print("\n" + "="*50)
    print("🧹 Cleaning up...")
    print("="*50)
    
    # Clean up: manually kill the browser session
    # Note: This is necessary because we set keep_alive=True
    await browser_session.kill()
    print("✅ Browser session closed")


def simulate_cli_interaction():
    """
    This simulates what happens in the CLI interactive mode:
    
    1. User types: "go to reddit"
    2. Agent runs and completes task (calls done())
    3. Browser stays open because CLI uses keep_alive=True by default
    4. User types: "what's the first post"
    5. CLI calls agent.add_new_task() and agent.run() again
    6. Agent continues with the same browser session
    """
    print("""
    🖥️  CLI Simulation:
    
    $ browser-use
    > go to reddit
    [Agent works and completes task...]
    ✅ Task completed! Browser stays open.
    
    > what's the first post
    [Agent continues with same browser session...]
    ✅ Task completed!
    
    > exit
    [Browser closes]
    """)


if __name__ == '__main__':
    print("🌟 Reddit Follow-up Tasks Example")
    print("="*50)
    print("This demonstrates the same pattern as CLI interactive mode:")
    print("1. Complete initial task (browser stays open)")
    print("2. Add follow-up task without restarting browser")
    print("3. Continue working in the same session")
    print("="*50 + "\n")
    
    # Show what CLI does
    simulate_cli_interaction()
    
    print("🏃 Running actual example...")
    print("-" * 30 + "\n")
    
    # Run the actual example
    asyncio.run(main())