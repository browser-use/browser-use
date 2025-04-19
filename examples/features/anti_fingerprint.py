import asyncio
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, BrowserConfig

# Load environment variables
load_dotenv()

# Check if OpenAI API key is set
if not os.getenv('OPENAI_API_KEY'):
    print("Warning: OPENAI_API_KEY is not set. Using a dummy value for testing.")
    os.environ['OPENAI_API_KEY'] = 'dummy-api-key-for-testing'

async def test_anti_fingerprint():
    """
    Example of using the anti-fingerprinting feature to avoid detection by bot detection systems.
    """
    # Method 1: Configure anti-fingerprinting in BrowserConfig
    browser_config = BrowserConfig()
    browser_config.anti_fingerprint = True  # Enable anti-fingerprinting measures

    # Print the anti-fingerprint setting
    print(f"Browser anti_fingerprint: {browser_config.anti_fingerprint}")

    agent = Agent(
        task="Visit https://browserleaks.com/javascript and tell me what information is shown about my browser. "
             "Specifically, check the navigator properties and tell me if webdriver is detected.",
        llm=ChatOpenAI(model="gpt-4o"),
        browser_config=browser_config,
    )

    history = await agent.run(max_steps=5)
    print(f"Result: {history.final_result()}")

    # Method 2: Enable anti-fingerprinting directly in agent settings
    agent2 = Agent(
        task="Visit https://bot.sannysoft.com and tell me if any bot detection tests are failing. "
             "Summarize the results of the tests.",
        llm=ChatOpenAI(model="gpt-4o"),
        settings={
            "anti_fingerprint": True,  # Enable anti-fingerprinting measures
        }
    )

    history2 = await agent2.run(max_steps=5)
    print(f"Result 2: {history2.final_result()}")

if __name__ == "__main__":
    asyncio.run(test_anti_fingerprint())
