from browser_use.llm import ChatGoogle
from browser_use import Agent, Controller
from dotenv import load_dotenv
load_dotenv()

import asyncio

from pydantic import BaseModel, Field
from typing import List, Dict, Any

class Response(BaseModel):
    items: List[str] = Field(description="A list of strings of response")

llm = ChatGoogle(model="gemini-2.5-flash", temperature=0.3)
controller = Controller(output_model=Response)

async def main():
    agent = Agent(
        task="starts by navigating to the ecommerce in this shopping portal, adds a tshirt to the cart and checks out and after that go to fill the form in fill in the expected details and submit the form",
        llm=llm,
        controller=controller,
        logging=True
    )
    result = await agent.run()
    print(result.final_result())

asyncio.run(main())
