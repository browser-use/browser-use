"""
Speed-Focused Example: Headless Mode with Minimal Wait Times

This example demonstrates the fastest possible browser-use configuration using
headless mode with optimized wait times and browser settings. Perfect for
production environments where speed is critical.

@file purpose: Demonstrates headless mode with minimal wait times for maximum speed
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# Fast model configuration
llm = ChatOpenAI(
    model='gpt-4.1-mini',  # Fast model
    temperature=0.0,  # Deterministic for speed
    max_tokens=512,  # Limit response length
    timeout=20,  # Quick timeout
)

# Ultra-fast headless browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        # Core speed settings
        headless=True,  # Headless mode - no GUI overhead
        wait_between_actions=0.0,  # No waiting between actions
        
        # Minimal viewport for faster rendering
        viewport={'width': 800, 'height': 600},
        
        # No persistent profile for faster startup
        user_data_dir=None,
        
        # Performance-optimized Chrome arguments
        args=[
            # Core performance flags
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-software-rasterizer',
            
            # Disable unnecessary features
            '--disable-extensions',
            '--disable-plugins',
            '--disable-images',  # Skip image loading
            '--disable-javascript-harmony-shipping',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI,BlinkGenPropertyTrees',
            
            # Network optimizations
            '--disable-background-networking',
            '--disable-sync',
            '--disable-default-apps',
            '--no-first-run',
            '--disable-component-update',
            '--disable-domain-reliability',
            
            # Memory optimizations
            '--memory-pressure-off',
            '--max_old_space_size=4096',
            '--aggressive-cache-discard',
            
            # Security disabled for speed (use only in controlled environments)
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            '--disable-ipc-flooding-protection',
            
            # Additional speed flags
            '--fast-start',
            '--no-pings',
            '--disable-hang-monitor',
            '--disable-prompt-on-repost',
            '--disable-client-side-phishing-detection',
            '--disable-popup-blocking',
        ],
        
        # Disable unnecessary security for speed (controlled environment only)
        disable_security=False,  # Keep basic security
        
        # Minimal timeouts
        timeout=15000,  # 15 second browser timeout
    )
)

# Speed-optimized task
task = """
EXECUTE WITH MAXIMUM SPEED - NO DELAYS:

1. Go to duckduckgo.com
2. Search for "python automation"
3. Click the first result
4. Get the page title
5. Return immediately

Priority: Speed over perfection. Execute actions immediately.
"""

async def main():
    print("🚀 Launching ultra-fast headless browser automation")
    print("⚡ Configuration: Headless + Zero wait times + Optimized Chrome flags")
    print("🎯 Target: Sub-30 second execution for simple tasks")
    
    # Create speed-demon agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        
        # Speed-first agent configuration
        flash_mode=True,  # Minimal system prompt
        use_vision=True,  # Keep vision for accuracy
        max_actions_per_step=10,  # Batch actions for speed
        max_failures=1,  # Single retry only
        retry_delay=0,  # No retry delay
        step_timeout=20,  # Very short step timeout
        llm_timeout=15,  # Short LLM timeout
        use_thinking=False,  # Skip thinking for speed
        vision_detail_level='low',  # Faster image processing
        
        # Disable non-essential features
        generate_gif=False,  # No GIF generation
        calculate_cost=False,  # No cost calculation overhead
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n⏱️  Starting speed test...")
        result = await agent.run(max_steps=6)
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        print(f"\n🏁 Completed in {execution_time:.2f} seconds")
        
        if execution_time < 30:
            print("🎉 SPEED TARGET ACHIEVED! (< 30 seconds)")
        else:
            print("⚠️  Speed target missed, consider further optimizations")
            
        print(f"📊 Result: {result}")
        
        # Performance metrics
        print(f"\n📈 Performance Metrics:")
        print(f"   ⏱️  Total time: {execution_time:.2f}s")
        print(f"   🚀 Actions/second: ~{6/execution_time:.1f}")
        print(f"   💨 Mode: Headless + Zero wait")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n💥 Failed after {end_time - start_time:.2f} seconds")
        print(f"❌ Error: {e}")
        print("💡 Tip: For production, add error handling and retries")
    
    finally:
        if agent.browser_session:
            await agent.browser_session.close()

if __name__ == '__main__':
    print("🔧 Speed Configuration Summary:")
    print("   • Headless mode: ON")
    print("   • Wait between actions: 0ms")
    print("   • Image loading: DISABLED")
    print("   • Extensions: DISABLED") 
    print("   • Flash mode: ENABLED")
    print("   • Thinking mode: DISABLED")
    print("   • Max actions per step: 10")
    print()
    
    asyncio.run(main())