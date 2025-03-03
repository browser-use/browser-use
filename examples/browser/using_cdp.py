"""
Simple demonstration of the CDP feature.

To test this locally, follow these steps:
1. Create a shortcut for the executable Chrome file.
2. Add the following argument to the shortcut:
   - On Windows: `--remote-debugging-port=9222`
3. Open a web browser and navigate to `http://localhost:9222/json/version` to verify that the Remote Debugging Protocol (CDP) is running.
4. Launch this example.

@dev You need to set the `GEMINI_API_KEY` environment variable before proceeding.
"""

import os
import sys
import requests
from dotenv import load_dotenv
from pydantic import SecretStr

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_google_genai import ChatGoogleGenerativeAI

from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig

load_dotenv()
api_key = 'AIzaSyCkgWIHP5Fsjf8PXpVm3SKbaKZVsta7Ddw'
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

payload = {
    "headless": True,
    "timeout": 2,
    "idle_timeout": 2
}
headers = {
    "anchor-api-key": "sk-6aab7609751e26167b4de4d217f280f9",
    "Content-Type": "application/json"
}

response = requests.request("POST", "https://api.anchorbrowser.io/api/sessions", headers=headers, json=payload)
response = response.json()
session_id = response["id"]
print(response['livew_view_url'])
cdp_url = f"wss://connect.anchorbrowser.io?sessionId={session_id}"

browser = Browser(
	config=BrowserConfig(
		headless=False,
		cdp_url=cdp_url,
	)
)
controller = Controller()


async def main():
	task = 'Go to https://coned.com/ ,insert the username test@example.com and password "1234" and login, return what was the webiste reaction to the login attempt'
	model = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(str(api_key)))
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser=browser,
	)

	await agent.run()
	await browser.close()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
