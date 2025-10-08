import asyncio
import os
import sys
import aiohttp
from contextlib import asynccontextmanager
from typing import cast, Any

# Add parent directory to sys.path for module imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from browser_use import Agent, Browser
from browser_use.llm.google.chat import ChatGoogle

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Retrieve Google API key from .env
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("GOOGLE_API_KEY is not set")

# Initialize the Gemini model with ChatGoogle
llm = ChatGoogle(
    model="gemini-2.5-pro",  # Use gemini-2.5-pro for structured output support
    api_key=api_key,
    temperature=0.7,
    config={"tools": []}  # Disable tools to avoid JSON mime type issue
)

@asynccontextmanager
async def managed_session():
    session = aiohttp.ClientSession()
    try:
        yield session
    finally:
        await session.close()

async def run_captcha():
    async with managed_session():
        browser = Browser(use_cloud=False)  # Removed include_screenshot
        agent = Agent(
            task="Navigate to https://www.google.com/recaptcha/api2/demo, click the reCAPTCHA checkbox, and solve any image-based CAPTCHA by selecting the correct images",
            llm=llm,  # type: ignore  # Suppress Pylance type warning for llm
            browser=browser,
            verbose=True  # Enable logging for debugging
        )
        # Type assertion to inform Pylance that agent.browser is a Browser instance
        agent = cast("Agent[Any, Browser]", agent)

        try:
            result = await agent.run()
            print("CAPTCHA Result:", result)
        except Exception as e:
            print(f"Error solving CAPTCHA: {e}")
        finally:
            # Safe browser cleanup
            if hasattr(agent, 'browser') and hasattr(agent.browser, 'close'):
                await agent.browser.close()
            elif browser is not None and hasattr(browser, 'close'):
                await browser.close()

if __name__ == "__main__":
    asyncio.run(run_captcha())