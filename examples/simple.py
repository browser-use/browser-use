from browser_use.llm import ChatGoogle
from browser_use import Agent
from dotenv import load_dotenv
load_dotenv()

import asyncio

llm = ChatGoogle(model="gemini-2.5-pro")

async def main():
    agent = Agent(
        task="starts by navigating to the ecommerce in this shopping portal, adds a product to the cart multiple times, and then adjusts the quantity in the cart and buy a tshirt",
        llm=llm,
        logging=True
    )
    result = await agent.run()
    print(result)

asyncio.run(main())
