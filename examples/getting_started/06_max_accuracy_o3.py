"""
Maximum Accuracy Example with O3 Model

This example demonstrates how to configure browser-use for maximum accuracy
using the O3 model with optimized settings and specific prompting techniques.

@file purpose: Demonstrates maximum accuracy configuration with O3 model,
focusing on precision over speed with longer wait times and careful step execution.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, BrowserProfile, ChatOpenAI

# Accuracy optimization prompting for maximum precision
ACCURACY_OPTIMIZATION_PROMPT = """
Accuracy and precision instructions:
- Take your time to carefully analyze each page state before acting
- Double-check element selectors and ensure you're targeting the correct elements
- Verify that actions were successful before proceeding to the next step
- If an action fails, analyze why and try alternative approaches
- Be thorough in your reasoning and explain your thought process clearly
- When extracting data, cross-reference multiple sources if available
- Always validate that the information you extract is complete and accurate
- If you're uncertain about any element or action, describe what you see and ask for clarification
- Focus on precision over speed - accuracy is the primary goal
"""


async def main():
    # 1. Use O3 model for maximum accuracy and reasoning capability
    llm = ChatOpenAI(
        model="o3",
        temperature=0.0,  # Minimize randomness for consistency
    )

    # 2. Create accuracy-optimized browser profile with longer wait times
    browser_profile = BrowserProfile(
        # Longer page load times for complex pages
        minimum_wait_page_load_time=1.0,  # Wait longer before capturing state
        wait_for_network_idle_page_load_time=2.0,  # Ensure network is idle
        maximum_wait_page_load_time=10.0,  # Allow more time for complex pages
        wait_between_actions=1.5,  # More time between actions for stability
        
        # Visual settings for better element detection
        highlight_elements=True,  # Keep highlighting for better visibility
        viewport_expansion=800,  # Larger viewport for more context
        
        # Browser settings for stability
        headless=False,  # Visual mode for better debugging
        slow_mo=500,  # Slow down browser actions for accuracy (500ms delay)
        timeout=60000,  # 60 second timeout for operations
        default_navigation_timeout=45000,  # 45 seconds for navigation
    )

    # 3. Define a complex, multi-step accuracy task
    task = """
    Perform a comprehensive research task with high accuracy:
    
    1. Go to Wikipedia (https://en.wikipedia.org)
    2. Search for "Artificial Intelligence" 
    3. Navigate to the main AI article
    4. Extract the following information with high precision:
       - The exact definition provided in the first paragraph
       - The year AI was first established as an academic discipline
       - At least 3 key subfields mentioned in the article
       - The names of at least 2 founding figures mentioned
    5. Verify each piece of information by cross-referencing with the article content
    6. Format the extracted information in a clear, structured way
    
    Be extremely thorough and double-check all extracted information for accuracy.
    """

    # 4. Create agent with all accuracy optimizations
    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        
        # Agent settings optimized for accuracy
        max_actions_per_step=3,  # Lower number to be more deliberate
        use_thinking=True,  # Enable thinking for better reasoning
        flash_mode=False,  # Disable flash mode to keep full reasoning
        max_failures=5,  # Allow more retries for complex operations
        retry_delay=15,  # Longer delay between retries
        
        # Timeout settings for complex operations
        llm_timeout=120,  # 2 minutes for LLM responses
        step_timeout=300,  # 5 minutes per step for complex operations
        
        # Vision settings for better analysis
        use_vision=True,
        vision_detail_level='high',  # High detail for better element detection
        
        # Extended system message for accuracy focus
        extend_system_message=ACCURACY_OPTIMIZATION_PROMPT,
        
        # Enable cost calculation to monitor O3 usage
        calculate_cost=True,
    )

    print("🎯 Starting maximum accuracy browser agent with O3 model...")
    print("⚙️ Configuration:")
    print(f"   • Model: {llm.model}")
    print(f"   • Max actions per step: 3")
    print(f"   • Wait between actions: 1.5s")
    print(f"   • Slow motion: 500ms")
    print(f"   • Vision detail: high")
    print(f"   • Thinking enabled: True")
    print(f"   • Step timeout: 5 minutes")
    print("")

    # Run with lower max_steps to ensure thorough execution
    history = await agent.run(max_steps=15)
    
    print("\n" + "="*60)
    print("🎉 Task completed! Results:")
    print("="*60)
    
    # Extract and display the final results
    if history.final_result():
        print("📋 Final Result:")
        print(history.final_result())
    
    # Show any errors for debugging
    if history.errors():
        print("\n❌ Errors encountered:")
        for error in history.errors():
            print(f"   • {error}")
    
    print(f"\n📊 Total steps executed: {len(history)}")
    print("💡 Tip: For even higher accuracy, consider increasing wait times further")
    print("    or reducing max_actions_per_step to 1-2 for the most critical tasks.")


if __name__ == '__main__':
    asyncio.run(main())