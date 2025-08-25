"""
Getting Started Example 5: Speed-Optimized Browser Automation

This example demonstrates how to configure browser-use for maximum speed:
1. Flash mode enabled (disables thinking and evaluation steps)
2. Fast LLM (Llama 4 on Groq for ultra-fast inference)
3. Reduced wait times between actions
4. Headless mode option (faster rendering, default off for visibility)
5. Extended system prompt to encourage concise responses
6. Optimized agent settings for speed

Perfect for production environments where speed is critical.
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatGroq
from browser_use.browser.profile import BrowserProfile

# Speed optimization instructions for the model
SPEED_OPTIMIZATION_PROMPT = """
SPEED OPTIMIZATION INSTRUCTIONS:
- Be extremely concise and direct in your responses
- Skip unnecessary explanations and focus on actions
- Use multi-action sequences whenever possible to reduce steps
- Prioritize efficiency over detailed reasoning
- Get to the goal as quickly as possible
"""


async def main():
    # 1. Use fast LLM - Llama 4 on Groq for ultra-fast inference
    llm = ChatGroq(
        model='meta-llama/llama-4-maverick-17b-128e-instruct',
        temperature=0.0,  # Deterministic for speed
    )
    
    # 2. Create speed-optimized browser profile
    browser_profile = BrowserProfile(
        # 3. Reduce wait times for faster execution
        wait_between_actions=0.1,  # Reduced from default 0.5s
        minimum_wait_page_load_time=0.1,  # Reduced from default 0.25s
        wait_for_network_idle_page_load_time=0.25,  # Reduced from default 0.5s
        maximum_wait_page_load_time=3.0,  # Reduced from default 5.0s
        
        # 4. Headless mode for faster rendering (set to True for maximum speed)
        headless=False,  # Default off for visibility, set to True for production speed
        
        # Additional speed optimizations
        disable_security=True,  # Skip security checks for speed
        ignore_https_errors=True,  # Skip certificate validation
    )
    
    # Define a speed-focused task
    task = "Go to example.com and quickly extract the main heading text"
    
    # 5. Create agent with all speed optimizations
    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        
        # Agent speed settings
        flash_mode=True,  # Disables thinking and evaluation for maximum speed
        use_thinking=False,  # Explicitly disable thinking (redundant with flash_mode)
        max_actions_per_step=10,  # Allow multiple actions per step
        
        # 6. Extend system prompt with speed instructions
        extend_system_message=SPEED_OPTIMIZATION_PROMPT,
        
        # Additional speed optimizations
        use_vision=True,  # Keep vision for accuracy but with low detail
        vision_detail_level='low',  # Faster image processing
        max_failures=2,  # Reduce retry attempts
        retry_delay=5,  # Faster retry cycles
    )
    
    print("🚀 Running speed-optimized browser automation...")
    print("⚡ Optimizations enabled:")
    print("  - Flash mode (no thinking/evaluation)")
    print("  - Llama 4 on Groq (ultra-fast inference)")
    print("  - Reduced wait times (0.1s between actions)")
    print("  - Low vision detail level")
    print("  - Concise system prompt")
    print("  - Multi-action sequences")
    if browser_profile.headless:
        print("  - Headless mode (fastest rendering)")
    else:
        print("  - Windowed mode (set headless=True for max speed)")
    print()
    
    await agent.run()


if __name__ == '__main__':
    asyncio.run(main())