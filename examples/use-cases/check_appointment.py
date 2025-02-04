import asyncio

import dotenv
from pydantic import BaseModel

from browser_use import LLM, Agent, Controller

dotenv.load_dotenv()


controller = Controller()


class WebpageInfo(BaseModel):
    link: str = "https://appointment.mfa.gr/en/reservations/aero/ireland-grcon-dub/"


@controller.action("Go to the webpage", param_model=WebpageInfo)
def go_to_webpage(webpage_info: WebpageInfo):
    return webpage_info.link


async def main():
    task = (
        "Go to the Greece MFA webpage via the link I provided you."
        "Check the visa appointment dates. If there is no available date in this month, check the next month."
        "If there is no available date in both months, tell me there is no available date."
    )

    llm = LLM(model="openai/gpt-4o-mini")
    agent = Agent(task, llm, controller=controller, use_vision=True)

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
