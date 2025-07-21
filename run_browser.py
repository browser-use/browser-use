import asyncio
from dotenv import load_dotenv
import os
from browser_use import Agent
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

# Set the API key
os.environ["GOOGLE_API_KEY"] = ""

async def main():
    agent = Agent(
        task="Search for the latest news about artificial intelligence",
        llm=ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            api_key=SecretStr(os.environ["GOOGLE_API_KEY"])
        ),
    )
    await agent.run()

if __name__ == "__main__":
    asyncio.run(main()) 