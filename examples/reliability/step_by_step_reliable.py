"""
Reliability-Focused Example: Step-by-Step Execution with Loading Validation

This example demonstrates how to configure browser-use for maximum reliability using:
- Step-by-step prompts with numbered instructions
- Temperature 0 for deterministic behavior
- OpenAI o3 model for superior reasoning
- Proper loading validation after each action
- Comprehensive error handling and retries

@file purpose: Demonstrates reliability-focused configuration with step-by-step execution
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# Reliability-focused LLM configuration with o3
llm = ChatOpenAI(
    model='o3',  # Most capable model for complex reasoning
    temperature=0.0,  # Zero temperature for deterministic, reliable behavior
    max_tokens=2048,  # Sufficient tokens for detailed responses
    timeout=120,  # Longer timeout for complex reasoning
)

# Reliability-focused browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=False,  # Visible browser for better debugging and validation
        wait_between_actions=2.0,  # Longer wait times for page stability
        viewport={'width': 1920, 'height': 1080},  # Full HD for better element detection
        user_data_dir='~/.config/browseruse/profiles/reliable',  # Persistent profile
        
        # Reliability-focused browser arguments
        args=[
            '--no-sandbox',  # Required for many environments
            '--disable-dev-shm-usage',  # Prevent crashes in limited memory
            '--disable-blink-features=AutomationControlled',  # Better compatibility
            '--start-maximized',  # Ensure full window visibility
            '--disable-infobars',  # Remove automation notifications
            '--disable-extensions',  # Avoid extension interference
            '--disable-popup-blocking',  # Allow necessary popups
            '--disable-default-apps',  # Prevent default app prompts
            '--no-first-run',  # Skip first run setup
            '--disable-background-timer-throttling',  # Ensure timers work properly
            '--disable-backgrounding-occluded-windows',  # Keep background tabs active
            '--disable-renderer-backgrounding',  # Maintain renderer performance
        ],
        
        # Enhanced timeouts for reliability
        timeout=60000,  # 60 second browser timeout
        
        # Deterministic rendering for consistent behavior
        deterministic_rendering=False,  # Keep disabled for better performance
    )
)

# Step-by-step reliable task with explicit validation points
task = """
RELIABILITY PRIORITY: Execute each step carefully and validate completion before proceeding.

IMPORTANT INSTRUCTIONS:
- Wait for each page to fully load before taking any action
- Validate that each action was successful before proceeding
- If an element is not immediately visible, wait 3-5 seconds and try again
- Take screenshots after critical actions for verification
- Report any issues encountered during execution

STEP-BY-STEP EXECUTION PLAN:

1. Navigate to https://github.com
   - Wait for the page to fully load (look for the GitHub logo and navigation)
   - Validate: Confirm the page title contains "GitHub"
   - Validate: Confirm the search box is visible

2. Search for "browser-use"
   - Click on the search input field
   - Wait for the search field to become active
   - Type "browser-use" slowly and clearly
   - Validate: Confirm the text appears in the search field
   - Press Enter to search
   - Wait for search results to load completely

3. Locate and click on the browser-use repository
   - Wait for search results page to fully load
   - Look for "browser-use/browser-use" in the results
   - Validate: Confirm the repository appears in search results
   - Click on the main repository link (not issues, discussions, etc.)
   - Wait for the repository page to load completely

4. Extract repository information
   - Wait for the repository page to fully load
   - Validate: Confirm the repository name "browser-use" is visible
   - Validate: Confirm the star count is visible
   - Validate: Confirm the description is loaded
   - Extract and report:
     * Repository name
     * Star count
     * Fork count
     * Main programming language
     * Description

5. Verify data accuracy
   - Double-check all extracted information is visible on screen
   - Validate: All numbers are properly formatted
   - Validate: All text is complete and not truncated
   - Report final results with confidence level

CRITICAL REQUIREMENTS:
- After each step, explicitly state "Step X completed successfully" or report issues
- If any step fails, wait 5 seconds and retry once before reporting failure
- Always wait for loading indicators to disappear before proceeding
- Take time to ensure accuracy over speed
"""

async def main():
    print("🔒 Initializing reliability-focused browser automation")
    print("🎯 Model: OpenAI o3 (temperature=0.0)")
    print("⏳ Configuration: Maximum reliability with validation")
    print("📋 Execution: Step-by-step with loading validation")
    
    # Create reliability-focused agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        
        # Reliability-first agent configuration
        flash_mode=False,  # Full system prompt for comprehensive instructions
        use_vision=True,  # Enable vision for better validation
        max_actions_per_step=3,  # Fewer actions per step for careful execution
        max_failures=5,  # More retries for reliability
        retry_delay=10,  # Longer retry delay for stability
        step_timeout=180,  # Longer step timeout for complex operations
        llm_timeout=120,  # Longer LLM timeout for o3 reasoning
        use_thinking=True,  # Enable thinking for better reasoning
        vision_detail_level='high',  # High detail for accurate validation
        
        # Enhanced reliability features
        generate_gif=True,  # Generate GIF for debugging
        calculate_cost=True,  # Track costs for monitoring
        validate_output=True,  # Enable output validation
        
        # Custom system message extension for reliability
        extend_system_message="""
RELIABILITY PROTOCOL:
- Always wait for pages to fully load before taking actions
- Validate each action's success before proceeding to the next step
- If an element is not found, wait 3-5 seconds and retry
- Report step completion status explicitly
- Prioritize accuracy and completeness over speed
- Take screenshots after critical actions for verification
- If uncertain about page state, wait longer and re-evaluate
        """,
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n🚀 Starting reliable step-by-step execution...")
        print("⏱️  Note: This may take longer due to reliability measures")
        
        result = await agent.run(max_steps=15)  # More steps allowed for careful execution
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        print(f"\n✅ Reliable execution completed in {execution_time:.2f} seconds")
        print(f"🎯 Result: {result}")
        
        # Reliability metrics
        print(f"\n📊 Reliability Metrics:")
        print(f"   ⏱️  Execution time: {execution_time:.2f}s")
        print(f"   🔄 Model: OpenAI o3 (temperature=0.0)")
        print(f"   🔍 Vision detail: High")
        print(f"   ⚡ Actions per step: 3 (conservative)")
        print(f"   🛡️  Max retries: 5")
        print(f"   ✅ Validation: Enabled")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n❌ Execution failed after {end_time - start_time:.2f} seconds")
        print(f"🚫 Error: {e}")
        print("🔧 Debugging tips:")
        print("   • Check browser logs for detailed error information")
        print("   • Verify network connectivity and GitHub accessibility")
        print("   • Review generated GIF for visual debugging")
        print("   • Consider increasing timeouts for slower networks")
    
    finally:
        if agent.browser_session:
            print("\n🧹 Cleaning up browser session...")
            await agent.browser_session.close()

if __name__ == '__main__':
    # Verify OpenAI API key for o3 model
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY environment variable not set!")
        print("🔑 Required for OpenAI o3 model access")
        sys.exit(1)
    
    print("🔧 Reliability Configuration Summary:")
    print("   • Model: OpenAI o3 (zero temperature)")
    print("   • Wait between actions: 2.0 seconds")
    print("   • Validation: Step-by-step with loading checks")
    print("   • Retries: 5 attempts with 10s delay")
    print("   • Vision: High detail level")
    print("   • Thinking: Enabled for better reasoning")
    print("   • Browser: Visible mode for debugging")
    print("   • Timeouts: Extended for reliability")
    print()
    
    asyncio.run(main())