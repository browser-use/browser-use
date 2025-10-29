# @file purpose: Single agent for Amazon shopping with strict rules
"""
This file implements a single-agent approach for browser automation.
Uses one LLM with vision to autonomously complete shopping tasks.
"""

import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

# Unset GEMINI_API_KEY to avoid conflicts with GOOGLE_API_KEY
if "GEMINI_API_KEY" in os.environ:
    os.environ["GEMINI_API_KEY"] = ""

from browser_use import Agent, BrowserProfile
from browser_use.llm import ChatGoogle

# Check available API keys and configure LLM
gemini_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')

if gemini_key:
    llm = ChatGoogle(model='gemini-flash-latest', api_key=gemini_key)
    print("🤖 Using Gemini Flash Latest")
else:
    raise ValueError("No API key found! Please set GEMINI_API_KEY or GOOGLE_API_KEY")

# Setup browser profile
browser_profile = BrowserProfile(
    headless=False,
    user_data_dir='~/.config/browseruse/profiles/default',
)

logging.basicConfig(level=logging.INFO)

async def main():
    """
    Single agent approach - Let the Agent handle planning and execution autonomously.
    """
    
    # Simple natural language task
    task = "Go to Amazon and buy: Fitbit Charge 6, large red t-shirt, Dell XPS 13, 20 pound dumbbell, Harry Potter book 1 paperback. Use zip 21703."

    # Extended system message to enforce rules
    extend_system_message = """
CRITICAL EXECUTION RULES:
1. MINIMIZE SCROLLING: Only scroll once per page maximum. E-commerce sites show "Add to Cart" buttons at the top.
2. ADD TO CART MANDATORY: Every product page visit MUST include clicking "Add to Cart" or "See all buying options" before moving to next item.
3. USE SEARCH BAR IN-PLACE: Always use the search bar on the current page. Don't navigate back unless no search bar exists.
4. ONE QUANTITY ONLY: Default quantity is always 1. Never change quantity unless explicitly requested.
5. VERIFY VARIANTS: Always check the selected variant (size/color/format) matches the request before adding to cart.
6. NO DUPLICATE ITEMS: Never add the same item twice. If duplicate detected in cart, remove it immediately.
7. CHANGE ZIPCODE FIRST: Before shopping, update the delivery zipcode if specified in the task.
8. FINAL VERIFICATION: After adding all items, go to cart and verify all items are present with correct variants.

If you cannot find an element after 1 scroll, move on - don't waste time scrolling repeatedly.
"""

    agent = Agent(
        task=task, 
        llm=llm,
        browser_profile=browser_profile,
        use_vision=True,  # Enable vision for better page understanding
        max_actions_per_step=1,  # One action per step for better control
        extend_system_message=extend_system_message,
        llm_timeout=90,  # Generous timeout for LLM calls
        max_failures=5,  # Allow some retries for transient errors
    )

    print("\n--- Running Single Agent ---")
    print(f"📋 Task: {task}\n")
    
    try:
        result = await agent.run(max_steps=100)
        print("\n✅ --- EXECUTION COMPLETE ---")
        print(f"Result: {result}")
    except Exception as e:
        print(f"\n❌ ERROR during execution: {e}")

if __name__ == '__main__':
    print("[DEBUG] Starting single agent approach...")
    asyncio.run(main())