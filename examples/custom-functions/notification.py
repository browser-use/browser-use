import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from dotenv import load_dotenv

from browser_use import LLM, ActionResult, Agent, Controller

load_dotenv()

controller = Controller()


@controller.registry.action("Done with task ")
async def done(text: str):
    import yagmail

    # To send emails use
    # STEP 1: go to https://support.google.com/accounts/answer/185833
    # STEP 2: Create an app password (you cant use here your normal gmail password)
    # STEP 3: Use the app password in the code below for the password
    yag = yagmail.SMTP("your_email@gmail.com", "your_app_password")
    yag.send(
        to="recipient@example.com",
        subject="Test Email",
        contents=f"result\n: {text}",
    )

    return ActionResult(is_done=True, extracted_content="Email sent!")


async def main():
    task = "go to brower-use.com and then done"
    llm = LLM(model="openai/gpt-4o")
    agent = Agent(task=task, llm=llm, controller=controller)

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
