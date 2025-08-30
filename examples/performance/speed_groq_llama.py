"""
Speed-Focused Example: Fast LLM with Groq Llama

This example demonstrates using Groq's ultra-fast Llama inference for maximum speed.
Groq provides some of the fastest LLM inference available, making it ideal for
speed-critical browser automation tasks.

@file purpose: Demonstrates Groq Llama configuration for ultra-fast LLM inference
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatGroq
from browser_use.browser import BrowserSession, BrowserProfile

# Ultra-fast Groq Llama configuration
llm = ChatGroq(
    model='meta-llama/llama-4-maverick-17b-128e-instruct',  # Fast Llama model
    temperature=0.0,  # Zero temperature for maximum speed and consistency
    max_tokens=1024,  # Limit tokens for faster generation
    timeout=15,  # Very short timeout - Groq is fast!
)

# Speed-optimized browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=True,  # Headless for speed
        wait_between_actions=0.05,  # Minimal wait time - Groq is fast enough
        viewport={'width': 1024, 'height': 768},
        user_data_dir=None,  # Ephemeral for faster startup
        # Groq-optimized browser args
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-web-security',  # For speed (use only in controlled environments)
            '--disable-features=VizDisplayCompositor',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-sync',
            '--disable-default-apps',
            '--no-first-run',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images',  # Disable image loading for maximum speed
            '--disable-javascript-harmony-shipping',
            '--disable-background-networking',
            '--aggressive-cache-discard',
        ]
    )
)

# Fast-execution task optimized for Groq's speed
task = """
SPEED PRIORITY: Execute as fast as possible.

1. Navigate to amazon.com
2. Search for "wireless headphones"
3. Sort by "Price: Low to High"
4. Get the price and name of the first 3 results
5. Return the results

Execute immediately without waiting. Groq inference is ultra-fast.
"""

async def main():
    print("⚡ Initializing ultra-fast Groq Llama automation...")
    print("🚀 Model: Llama-4 Maverick on Groq infrastructure")
    print("⏱️  Expected inference time: <200ms per call")
    
    # Create speed-optimized agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        # Ultra-speed settings for Groq
        flash_mode=True,  # Flash mode for minimal prompt overhead
        use_vision=True,  # Keep vision but optimize for speed
        max_actions_per_step=8,  # More actions per step due to fast inference
        max_failures=1,  # Single retry only
        retry_delay=1,  # Minimal retry delay
        step_timeout=30,  # Short timeout - Groq is fast
        llm_timeout=15,  # Very short LLM timeout
        use_thinking=False,  # No thinking mode for maximum speed
        vision_detail_level='low',  # Lower detail for faster vision processing
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n🏃‍♂️ Starting ultra-fast execution...")
        result = await agent.run(max_steps=8)
        end_time = asyncio.get_event_loop().time()
        
        print(f"\n🎯 Ultra-fast completion in {end_time - start_time:.2f} seconds")
        print(f"⚡ Average inference speed: ~{(end_time - start_time) / 8:.1f}s per step")
        print(f"📋 Results: {result}")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n💥 Failed after {end_time - start_time:.2f} seconds")
        print(f"❌ Error: {e}")
    
    finally:
        if agent.browser_session:
            await agent.browser_session.close()

if __name__ == '__main__':
    # Verify Groq API key
    if not os.getenv('GROQ_API_KEY'):
        print("❌ GROQ_API_KEY environment variable not set!")
        print("🔑 Get your free API key at: https://console.groq.com/")
        sys.exit(1)
    
    asyncio.run(main())