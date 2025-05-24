import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import ActionResult
from browser_use.agent.service import Agent
from browser_use.controller.service import Controller
from browser_use.browser import BrowserConfig, BrowserSession
from amazoncaptcha import AmazonCaptcha

browser_profile = BrowserConfig(
	headless=False
)

# Initialize controller first
controller = Controller()


@controller.action('Solve Amazon text based captcha', domains=[
	'amazon.com', 'amazon.co.uk', 'amazon.ca', 'amazon.de', 'amazon.es', 
	'amazon.fr', 'amazon.it', 'amazon.co.jp', 'amazon.in', 'amazon.cn', 
	'amazon.com.sg', 'amazon.com.mx', 'amazon.ae', 'amazon.com.br', 
	'amazon.nl', 'amazon.com.au', 'amazon.com.tr', 'amazon.sa', 
	'amazon.se', 'amazon.pl'
])
async def solve_amazon_captcha(browser_session: BrowserSession):
	page = await browser_session.get_current_page()
	
	# Find the captcha image and extract its src
	captcha_img = page.locator('img[src*="amazon.com/captcha"]')
	link = await captcha_img.get_attribute('src')
	
	if not link:
		raise ValueError("Could not find captcha image on the page")

	captcha = AmazonCaptcha.fromlink(link)
	solution = captcha.solve()
	if solution == 'Not solved':
		raise ValueError("Captcha could not be solved")

	await page.locator('#captchacharacters').fill(solution)
	await page.locator('button[type="submit"]').click()

	return ActionResult(extracted_content=solution)

async def main():
	task = 'Go to https://www.amazon.com/errors/validateCaptcha and solve the captcha using the solve_amazon_captcha tool'

	model = ChatOpenAI(model='gpt-4o')
	browser_session = BrowserSession(browser_profile=browser_profile)
	await browser_session.start()
	agent = Agent(task=task, llm=model, controller=controller, browser_session=browser_session)

	await agent.run()
	await browser_session.stop()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
