import asyncio
import os
import sys

from browser_use.llm.openai.chat import ChatOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()
from lmnr import Laminar

try:
	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except Exception:
	pass

from browser_use import Agent

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4o',
)


task = 'Go to google.com/travel/flights and search for flights to Tokyo next week'
task = """http://www.sadfdsafdssdafd.com/ go here and scroll around"""
task = 'Go to Louis Vuittons website, find every product and save the product details 1 by 1. Extract product details as JSON: productname (Full name as shown on the webpage), brand (Manufacturer or designer name), model (Specific version or edition), gender (Target audience: Men, Women, Unisex), sku (Unique identifier), releasedate (Launch date in YYYY-MM-DD format), retailprice (Price as a number, no currency symbols), colorway (Color description without spaces around slashes, e.g., White/PinkFoam), sizerange (Available sizes as a list, maintain decimals for half sizes, e.g., 7.5), requesturl (URL where product data is scraped), requesttimestamp (ISO 8601 timestamp of the request), primaryimgurl (URL of the main product image); ensure required fields are present, return null if data is missing.'

agent = Agent(task=task, llm=llm)


async def main():
	import time

	start_time = time.time()
	history = await agent.run()
	# token usage
	print(history.usage)
	end_time = time.time()
	print(f'Time taken: {end_time - start_time} seconds')


if __name__ == '__main__':
	asyncio.run(main())
