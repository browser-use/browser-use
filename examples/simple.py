"""
Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse

load_dotenv()

# agent = Agent(
# 	task='Find the number of stars of the browser-use repo',
# 	llm=ChatGoogle(model='gemini-flash-latest'),
# 	# browser=Browser(use_cloud=True),  # Uses Browser-Use cloud for the browser
# )
# agent.run_sync()


# from browser_use.llm import ChatGoogle
# llm = ChatGoogle(model='gemini-flash-latest', api_key='YOUR_KEY')
# print(dir(llm))

import asyncio
import os
from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("❌ GOOGLE_API_KEY is not set in your .env file")

async def run_search():
    print("🔍 Testing Gemini (via ChatGoogle)...")

    llm = ChatGoogle(model="gemini-flash-latest", api_key=api_key)
    agent = Agent(
        llm=llm,
        task="How many stars does the browser-use GitHub repository have?",
    )

    try:
        result = await agent.run()
        print("\n✅ Gemini model is working!")
        print("Result:\n", result)
    except Exception as e:
        print("\n❌ Gemini test failed:")
        print(e)

if __name__ == "__main__":
    asyncio.run(run_search())




agent = Agent(
	task='Find the number of stars of the following repos: browser-use, playwright, stagehand, react, nextjs',
	llm=ChatBrowserUse(),
)
agent.run_sync()
