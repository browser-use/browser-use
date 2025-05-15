import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))


task_1 = """
Navigate to: https://sortablejs.github.io/Sortable/. 
Then scroll down to the first examplw with title "Simple list example". 
Drag the element with name "item 1" to below the element with name "item 3".
"""


task_2 = """
Navigate to: https://excalidraw.com/.
Click on the pencil icon (with index 40).
Then draw a triangle in the canvas.
Draw the triangle starting from coordinate (400,400).
You can use the drag and drop action to draw the triangle.
"""


async def run_search():
	agent = Agent(
		task=task_1,
		llm=llm,
		max_actions_per_step=1,
		use_vision=True,
	)

	await agent.run(max_steps=25)


if __name__ == '__main__':
	asyncio.run(run_search())
