import asyncio

from browser_use import LLM, Agent


async def run_search():
    agent = Agent(
        task=(
            "1. Go to https://www.reddit.com/r/LocalLLaMA"
            "2. Search for 'browser use' in the search bar"
            "3. Click search"
            "4. Call done"
        ),
        llm=LLM(
            # model='qwen2.5:32b-instruct-q4_K_M',
            # model='qwen2.5:14b',
            model="ollama/qwen2.5:latest",
            num_ctx=128000,
        ),
        max_actions_per_step=1,
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(run_search())
