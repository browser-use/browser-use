"""
Speed-Focused Example: Flash Mode Configuration

This example demonstrates how to configure browser-use for maximum speed using flash mode.
Flash mode reduces the system prompt complexity and speeds up LLM processing while
maintaining good performance for simple tasks.

@file purpose: Demonstrates flash mode configuration for speed optimization
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# Speed-optimized LLM configuration
llm = ChatOpenAI(
    model='gpt-4.1-mini',  # Faster, smaller model
    temperature=0.1,  # Lower temperature for more consistent, faster responses
    timeout=30,  # Reduced timeout for faster failures
)

# Speed-optimized browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=True,  # Headless mode for faster rendering
        wait_between_actions=0.1,  # Reduced wait time between actions
        viewport={'width': 1280, 'height': 720},  # Smaller viewport for faster rendering
        user_data_dir=None,  # Ephemeral profile for faster startup
        # Additional speed optimizations
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-default-apps',
            '--no-first-run',
            '--fast-start',
            '--disable-extensions',
        ]
    )
)

# Speed-focused task - simple and direct
task = """
1. Go to google.com
2. Search for "browser-use github"
3. Click on the first GitHub result
4. Find and return the number of stars the repository has

Be fast and direct. Don't wait unnecessarily between actions.
"""

async def main():
    # Create agent with speed optimizations
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        # Speed-focused agent settings
        flash_mode=True,  # Enable flash mode for faster processing
        use_vision=True,  # Keep vision for accuracy but with speed focus
        max_actions_per_step=5,  # Allow more actions per step
        max_failures=2,  # Fewer retries for faster execution
        retry_delay=2,  # Shorter retry delay
        step_timeout=60,  # Shorter step timeout
        llm_timeout=30,  # Shorter LLM timeout
        use_thinking=False,  # Disable thinking for speed
    )
    
    print("🚀 Starting speed-optimized browser automation with flash mode...")
    print("⚡ Configuration: Flash mode ON, Headless mode, Reduced wait times")
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        result = await agent.run(max_steps=10)
        end_time = asyncio.get_event_loop().time()
        
        print(f"\n✅ Task completed in {end_time - start_time:.2f} seconds")
        print(f"📊 Result: {result}")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n❌ Task failed after {end_time - start_time:.2f} seconds")
        print(f"🚫 Error: {e}")
    
    finally:
        # Clean up
        if agent.browser_session:
            await agent.browser_session.close()

if __name__ == '__main__':
    asyncio.run(main())