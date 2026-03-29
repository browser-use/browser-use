"""
AgentSIM + Browser Use: Automated Signup with Real Phone Verification

Demonstrates a Browser Use agent that navigates to a signup page, provisions
a real carrier-grade mobile number via AgentSIM, fills the form, captures
the OTP, and completes registration.

Unlike VoIP numbers, AgentSIM numbers pass carrier lookup checks (line_type:
mobile) so they work with Google, Stripe, WhatsApp, and other services that
block virtual numbers.

Requirements:
    pip install browser-use agentsim-sdk
    playwright install chromium

Environment:
    OPENAI_API_KEY=sk-...
    AGENTSIM_API_KEY=asm_live_...  (get one at https://agentsim.dev/dashboard)
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.chat import ChatBrowserUse
from examples.integrations.agentsim.phone_tools import PhoneTools

TASK = """\
Go to https://example.com/signup and complete the registration:
1. Fill in the form with test details (make up a name and email).
2. When the form asks for a phone number, call provision_phone_number to get a real US mobile number.
3. Enter the provisioned number in the phone field and submit.
4. Call wait_for_otp to get the verification code.
5. Enter the OTP code and complete registration.
6. Call release_phone_number to clean up.
7. Report whether registration succeeded.
"""


async def main():
	tools = PhoneTools(api_key=os.environ["AGENTSIM_API_KEY"])
	llm = ChatBrowserUse(model="bu-2-0")

	agent = Agent(task=TASK, tools=tools, llm=llm)
	await agent.run()


if __name__ == "__main__":
	asyncio.run(main())
