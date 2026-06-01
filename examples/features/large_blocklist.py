"""
Example: Using large blocklists (400k+ domains) with automatic optimization

This example demonstrates:
1. Loading a real-world blocklist (HaGeZi's Pro++ with 439k+ domains)
2. Automatic conversion to set for O(1) lookup performance
3. Testing that blocked domains are actually blocked

Performance: ~0.02ms per domain check (50,000+ checks/second!)
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserProfile, BrowserSession

llm = ChatOpenAI(model='gpt-4.1-mini')


def load_blocklist_from_url(url: str) -> list[str]:
	"""Load and parse a blocklist from a URL.

	Args:
		url: URL to the blocklist file

	Returns:
		List of domain strings (comments and empty lines removed)
	"""
	import urllib.request

	print(f'📥 Downloading blocklist from {url}...')

	domains = []
	with urllib.request.urlopen(url) as response:
		for line in response:
			line = line.decode('utf-8').strip()
			# Skip comments and empty lines
			if line and not line.startswith('#'):
				domains.append(line)

	print(f'✅ Loaded {len(domains):,} domains')
	return domains


async def main():
	# Load HaGeZi's Pro++ blocklist (blocks ads, tracking, malware, etc.)
	# Source: https://github.com/hagezi/dns-blocklists
	blocklist_url = 'https://gitlab.com/hagezi/mirror/-/raw/main/dns-blocklists/domains/pro.plus.txt'

	print('=' * 70)
	print('🚀 Large Blocklist Demo - 439k+ Blocked Domains')
	print('=' * 70)
	print()

	# Load the blocklist
	prohibited_domains = load_blocklist_from_url(blocklist_url)

	# Sample some blocked domains to test
	test_blocked = [prohibited_domains[0], prohibited_domains[1000], prohibited_domains[-1]]
	print(f'\n📋 Sample blocked domains: {", ".join(test_blocked[:3])}')

	print(f'\n🔧 Creating browser with {len(prohibited_domains):,} blocked domains...')
	print('   (Auto-optimizing to set for O(1) lookup performance)')

	# Create browser with the blocklist
	# The list will be automatically optimized to a set for fast lookups
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			prohibited_domains=prohibited_domains,
			headless=False,
			user_data_dir='~/.config/browseruse/profiles/blocklist-demo',
		),
	)

	# Task: Try to visit a blocked domain and a safe domain
	blocked_site = test_blocked[0]  # Will be blocked
	safe_site = 'github.com'  # Will be allowed

	task = f"""
	Try to navigate to these websites and report what happens:
	1. First, try to visit https://{blocked_site}
	2. Then, try to visit https://{safe_site}
	
	Tell me which sites you were able to access and which were blocked.
	"""

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=browser_session,
	)

	print(f'\n🤖 Agent task: Try to visit {blocked_site} (blocked) and {safe_site} (allowed)')
	print('\n' + '=' * 70)

	await agent.run(max_steps=5)

	print('\n' + '=' * 70)
	print('✅ Demo complete!')
	print(f'💡 The blocklist with {len(prohibited_domains):,} domains was optimized to a set')
	print('   for instant O(1) domain checking (vs slow O(n) pattern matching)')
	print('=' * 70)

	input('\nPress Enter to close the browser...')
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
