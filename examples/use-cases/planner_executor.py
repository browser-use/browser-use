# @file purpose: Defines a two-step agent system with a planner and an executor.
"""
This file implements a multi-agent system where a "planner" agent, using a more powerful model,
breaks down a complex task into a series of smaller, concrete steps. An "executor" agent then
carries out these steps using a faster, more lightweight model.

This separation of concerns allows for more effective and efficient task completion. The planner
focuses on high-level strategy, while the executor handles the low-level interactions.
"""

import asyncio
import os
import sys
from typing import Dict, Union
import re
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv


load_dotenv()

# Unset GEMINI_API_KEY to avoid conflicts with GOOGLE_API_KEY
if "GEMINI_API_KEY" in os.environ:
    os.environ["GEMINI_API_KEY"] = ""

from browser_use import Agent, BrowserProfile, BrowserSession
from browser_use.llm import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.messages import UserMessage

# 1. Initialize the LLMs
# The planner uses a more capable model for strategic thinking,
# while the executor uses a faster model for action-oriented tasks.

# Planner LLM
planner_llm = ChatOpenAI(
    model="openai/gpt-oss-20b:free",
    base_url='https://openrouter.ai/api/v1',
    api_key=os.getenv('OPENROUTER_API_KEY')
)
# Executor LLM
executor_llm = ChatGoogle(model='gemini-2.5-flash')

# 2. Setup the browser profile the planner agent i supposed to give a high level task based on planner agent and executor agent to follow the excution based on the plan.
# Setup browser profile
browser_profile = BrowserProfile(
    headless=False,
    viewport_expansion=0,
    user_data_dir='/Users/spoorthiramireddygari/.config/browseruse/profiles/default',
    record_video_dir='/Users/spoorthiramireddygari/Documents/GitHub/demo-Browser-use1/videos',
    record_video_size={"width": 1280, "height": 720},
    allowed_domains=["www.amazon.com", "amazon.com", "google.com"],
)


logging.basicConfig(level=logging.DEBUG)

async def main():
    # The main execution logic will go here.
    # I will first implement the planner, then the executor.
    high_level_task = "Go to Amazon.com, change zipcode to 21703 and add the following items to the cart: Fitbit Charge 6 Fitness, Red T-shirt 'large', Dell XPS 13 Laptop 'regular prize', 20 lb dumbell, Harry Potter Book 1(paperback), the total item shoould be 5"

    # 1. Create and run the planner agent
    print("--- Running Planner Agent ---")

    # Use the LLM directly for planning instead of the Agent class
    from browser_use.llm.messages import SystemMessage

    planning_prompt = f"""You are a senior software engineer. Create a detailed, step-by-step plan of browser actions to accomplish the following task: {high_level_task}.

The plan should be like how a human would do it, but faster. It should only include browser actions. Do not include any file system operations.

When the task involves multiple items, ensure the plan includes steps to search for and add *each item* to the cart individually. After adding an item, the plan should navigate back to the search page to look for the next item.

Crucially, the plan must account for variations in the "add to cart" process on Amazon. Sometimes, the "Add to Cart" button is not immediately visible. The plan must include steps to handle these alternative scenarios:
- If an "Add to Cart" button is not visible, look for a "See all buying options" or similar button and click it.
- If any item or the requested size/variant is not available, skip it and proceed to the next item.
- If there are different purchasing options (e.g., "Join Prime" deals vs. regular price), the plan should explicitly choose the regular price option.
- The plan should be flexible enough to handle pop-ups or intermediate pages that might appear. Look for a "No, thanks" or "close" button to dismiss them.
- All the items should be added to the cart, do not skip any item. Skip the item if it is not available.
- Always check the number of items in the cart after adding each item, based on the number of items requested in the task.

After adding all items, the plan must include a step to go to the cart, take a screenshot, and visually verify that all items are present before proceeding to checkout. If any items are missing, the plan should include steps to go back and add them.

Respond with just the plan, nothing else. So that the executor can follow the plan and execute it. The plan should be conversational and not robotic.

Example format for a multi-item task:
1. Go to https://www.amazon.com.
2. Wait for the homepage to load fully.
3. Change ZIP code to 21703.
   - If a pop-up appears, input ZIP code there.
   - If not, click the delivery location near the top-left and update it manually.
   - If the zipcode is already set, move to the next step
4. Wait for page reload and confirm the ZIP has been updated.
5. In the search bar, enter "Item 1" and press Enter.
6. Wait for search results to load.
7. Click on the most relevant result based on title match.
8. Always go to the product page and avoid clicking add to cart on lists page. 
9. Once the product page is visible do the following: 
   - If “Add to Cart” is visible, click it.
   - If not visible, click “See All Buying Options”.
     - Wait for the buying options page to load.
     - Choose a valid option (prioritize ones that can be added to cart).
     - Click “Add to Cart” on the selected offer.
9. If any pop-ups (e.g., upsells or warranties) appear, close or skip them.
10. Return to the search bar (without returning to the homepage).
11. Clear the existing text, then search for "Item 2".
12. Repeat steps 6–9 for "Item 2", "Item 3", "Item 4", and "Item 5".
13. After adding all items, click the cart icon to go to the cart page.
14. Wait for the cart to load.
15. Take a screenshot of the cart.
16. Visually verify that all 5 items are present. If an item is missing, go back to the search page and add it.
17. Once all items are confirmed, proceed to checkout. 

Your plan:"""

    messages = [
        SystemMessage(content="You are a helpful planning assistant that creates step-by-step browser action plans."),
        UserMessage(content=planning_prompt)
    ]
    
    response = await planner_llm.ainvoke(messages)
    plan = response.completion

    if not plan or not isinstance(plan, str):
        print("Planner failed to generate a plan or the plan is not a string.")
        if plan:
            print(f"Received plan of type: {type(plan)}")
            print(f"Plan content: {plan}")
        return

    # Create a single browser session that will persist across all steps
    browser_session = BrowserSession(browser_profile=browser_profile)

    print("--- Running Executor Agent ---")
    # Create a single agent to execute the entire plan
    executor_agent = Agent(
        task=plan,  # Give the entire plan to the agent
        llm=executor_llm,
        browser_session=browser_session,
        max_actions_per_step=100,  # Allow more actions for the multi-step task
        afc_enabled=False,
    )
    
    # Run the agent to complete the whole plan
    await executor_agent.run(max_steps=100)

    # Close the browser session only after the entire plan is executed
    await browser_session.close()
    print("Browser session closed.")

if __name__ == '__main__':
	asyncio.run(main())