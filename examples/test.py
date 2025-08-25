import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from browser_use import Agent, ChatOpenAI


async def check_esc(agent: Agent):
    """Simple ESC checker without threading"""
    if os.name == 'nt':  # Windows
        import msvcrt
        while True:
            await asyncio.sleep(0.1)  # Small delay
            if msvcrt.kbhit() and msvcrt.getch() == b'\x1b':  # ESC
                agent.stop()
                break


async def main():
    # Choose your model
    llm = ChatOpenAI(model='gpt-4.1-mini')
    task = 'Go and find the founders of browser-use'
    agent = Agent(task=task, llm=llm)

    print("Press ESC to stop agent")

    esc_task = asyncio.create_task(check_esc(agent))

    agent_history_list = await agent.run(max_steps=10)
    
    esc_task.cancel()
    
    print("was stopped", agent_history_list.stopped)


if __name__ == '__main__':
    asyncio.run(main())