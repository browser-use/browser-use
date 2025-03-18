import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser, BrowserConfig

from examples.custom_captcha_solver.captcha_solver import ReCaptchaSolver

load_dotenv()

browser = Browser(
    config=BrowserConfig(
        disable_security=True,
        headless=False,
    )
)

async def main():
    task = (
        "Open this website https://www.google.com/recaptcha/api2/demo"
        " check is recaptcha solved"
        " click 'Submit' button if solved"
        " finish the task"
    )

    solver_instance = ReCaptchaSolver()

    agent = Agent(
        task=task,
        llm=ChatOpenAI(model="gpt-4o"),
        browser=browser,
        captcha_solver=solver_instance,
    )

    result = await agent.run()
    print(result)

asyncio.run(main())
