import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserProfile, BrowserSession

llm = ChatOpenAI(model='gpt-4o-mini')

# Example task: Try to navigate to various sites including blocked ones
task = 'Navigate to example.com, then try to go to x.com, then facebook.com, and finally visit google.com. Tell me which sites you were able to access.'

prohibited_domains = [
	'x.com',  # Block X (formerly Twitter) - "locked the f in"
	'twitter.com',  # Block Twitter (redirects to x.com anyway)
	'facebook.com',  # Lock the F in Facebook too
	'*.meta.com',  # Block all Meta properties (wildcard pattern)
	'*.adult-site.com',  # Block all subdomains of adult sites
	'https://explicit-content.org',  # Block specific protocol/domain
	'gambling-site.net',  # Block gambling sites
]

# Note: For lists with 100+ domains, automatic optimization kicks in:
# - Converts list to set for O(1) lookup (blazingly fast!)
# - Pattern matching (*.domain) is disabled for large lists
# - Both www.example.com and example.com variants are checked automatically
# Perfect for ad blockers or large malware domain lists (e.g., 400k+ domains)

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		prohibited_domains=prohibited_domains,
		headless=False,  # Set to True to run without visible browser
		user_data_dir='~/.config/browseruse/profiles/blocked-demo',
	),
)

agent = Agent(
	task=task,
	llm=llm,
	browser_session=browser_session,
)


async def main():
	print('Demo: Blocked Domains Feature - "Lock the F in" Edition')
	print("We're literally locking the F in Facebook and X!")
	print(f'Prohibited domains: {prohibited_domains}')
	print('The agent will try to visit various sites, but blocked domains will be prevented.')
	print()

	await agent.run(max_steps=10)

	input('Press Enter to close the browser...')
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
