import asyncio
from dotenv import load_dotenv
load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatOpenAI

async def main():
      agent = Agent(
          task=(
              "go to this exact site - http://192.168.90.204:3000/transaction/indent-rise "
            #   "from there enter this 9025371033 mobile number and click on enter, "
            #   "next enter this password 123456@a and click on login. "
            #   "open the side menu and click Dept/Ward Store then click Indent then close the side menu to make space"
              "in the indent form create a new indent, here steps to create a new indent"
              "search and select Institution: PSG HOSPITALS"
              "search and select Units: PSG SUPER SPECIALITY HOSPITAL"
              "search and select Department: INFORMATION TECHNOLOGY"
              "type Purpose: test"
              "search and select Indent Type: IT Recurring"
              "type Remarks: test"
              "add 1 item in the item table row:"
              "Item: 'W' HOOK"
              "UOM: NOS"
              "EX Qty: 0"
              "Required Qty: 10"
              "Reference: test"
              "and Submit the form, it generates a new indent number, note that number"
              "click on View tab at top and search for the indent number and click on report button"
             
          ),
          llm=ChatOpenAI(model="gpt-4.1", temperature=1.0),
      )
      await agent.run()

asyncio.run(main())