import asyncio
import os
from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatOpenAI

# Load .env file explicitly
load_dotenv('/Users/spoorthiramireddygari/Documents/GitHub/demo-Browser-use1/browser-use1-demo/.env')

async def main():
    # Create 3 separate browser instances
    browsers = [
        Browser(
            user_data_dir=f'./temp-profile-{i}',
            headless=False,  # Matches BROWSER_USE_HEADLESS=false in .env
        )
        for i in range(3)
    ]

    # Initialize the LLM with OpenRouter and DeepSeek V3 (free tier)
    llm = ChatOpenAI(
        model="deepseek/deepseek-chat-v3-0324:free",
        api_key=os.getenv("OPENROUTER_API_KEY"),  # Changed from openai_api_key
        base_url="https://openrouter.ai/api/v1",  # Changed to base_url
        temperature=0.7,
        #verbose=True,  # Enable for debugging
    )

    # Create 3 agents with different tasks, all using the same LLM
    agents = [
        Agent(
            task='Search for "browser automation" on Google',
            browser=browsers[0],
            llm=llm,
        ),
        Agent(
            task='Search for "AI agents" on DuckDuckGo',
            browser=browsers[1],
            llm=llm,
        ),
        Agent(
            task='Visit Wikipedia and search for "web scraping"',
            browser=browsers[2],
            llm=llm,
        ),
    ]

    # Run all agents in parallel with a slight delay to avoid rate limits
    tasks = []
    for agent in agents:
        tasks.append(agent.run())
        await asyncio.sleep(1)  # 1-second delay to prevent OpenRouter rate limits
    results = await asyncio.gather(*tasks, return_exceptions=True)

    print('🎉 All agents completed!')
    print('Results:', results)

if __name__ == '__main__':
    asyncio.run(main())
