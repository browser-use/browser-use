import os
import sys
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use.agent.service import Agent

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

load_dotenv()

def build_agent() -> Agent:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set. Please check your .env file.")

    llm = ChatOpenAI(model="gpt-4o", api_key=api_key)

    task = (
        "Go to https://papago.naver.com, translate the Korean sentence '안녕하세요. 오늘 날씨가 좋네요.' "
        "into English, and return only the translated sentence."
    )

    return Agent(llm=llm, task=task)

async def run_translation():
    agent = build_agent()
    await agent.run()

if __name__ == "__main__":
    asyncio.run(run_translation())
