import asyncio

from dotenv import load_dotenv

from browser_use import LLM, Agent

load_dotenv()

# Initialize the model
llm = LLM(
    model="openai/gpt-4o",
    temperature=0.0,
)
task = "Find the founders of browser-use and draft them a short personalized message"

agent = Agent(task=task, llm=llm)


async def main():
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
