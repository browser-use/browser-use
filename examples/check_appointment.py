import asyncio
import os

import dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from browser_use.agent.service import Agent
from browser_use.controller.service import Controller
from browser_use.utils import BrowserSessionManager, with_error_handling

dotenv.load_dotenv()


controller = Controller()


class WebpageInfo(BaseModel):
	link: str = 'https://appointment.mfa.gr/en/reservations/aero/ireland-grcon-dub/'


@controller.action('Go to the webpage', param_model=WebpageInfo)
def go_to_webpage(webpage_info: WebpageInfo):
	return webpage_info.link


task = (
	'Go to the Greece MFA webpage via the link I provided you.'
	'Check the visa appointment dates. If there is no available date in this month, check the next month.'
	'If there is no available date in both months, tell me there is no available date.'
)

model = ChatOpenAI(model='gpt-4o-mini', api_key=SecretStr(os.getenv('OPENAI_API_KEY', '')))
agent = Agent(task, model, controller=controller, use_vision=True)


async def main():
	result = await agent.run()


@with_error_handling()
async def run_script():
    async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
        await managed_agent.run()

if __name__ == '__main__':
    run_script()
