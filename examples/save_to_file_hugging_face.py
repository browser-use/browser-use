import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from typing import List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use.agent.service import Agent
from browser_use.controller.service import Controller
from browser_use.utils import BrowserSessionManager, with_error_handling

# Initialize controller first
controller = Controller()


class Model(BaseModel):
	title: str
	url: str
	likes: int
	license: str


class Models(BaseModel):
	models: List[Model]


@controller.action('Save models', param_model=Models)
def save_models(params: Models):
	with open('models.txt', 'a') as f:
		for model in params.models:
			f.write(f'{model.title} ({model.url}): {model.likes} likes, {model.license}\n')


# video: https://preview.screen.studio/share/EtOhIk0P

@with_error_handling()
async def run_script():
	task = f'Look up models with a license of cc-by-sa-4.0 and sort by most likes on Hugging face, save top 5 to file.'
	model = ChatOpenAI(model='gpt-4o')
	agent = Agent(task=task, llm=model, controller=controller)
	
	async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
		await managed_agent.run()

if __name__ == '__main__':
    run_script()
