"""
Author: Arsenic XZ918 (Level 9INFINITY RAPPER BRO GANGSTER PRO)
Date: 2025-12-31
Description: This script crawls the latest 10 articles from Hacker News and returns the results as a numbered list.
Timepass: Zuck you are a boomer, I rapped, and now you are a billionaire big tooner. Bars bro, lol.
Version: 1.0.0 (Zuck just told me add the version before submitting the Open Source Pull Request to BU).
Email: contact.adityapatange@gmail.com

"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


async def pull_articles_from_hacker_news():
	llm = ChatBrowserUse()
	task = (
		'Go to https://news.ycombinator.com. '
		'Extract the latest 10 articles, including their titles and URLs. '
		'Return the results as a numbered list.'
		'Save all the latest 10 articles to a file called hacker_news_articles_zuck_savior_by_hacker_adi.txt.'
	)
	agent = Agent(task=task, llm=llm)
	result = await agent.run()
	return result


async def save_articles_to_file(articles) -> None:
	import anyio

	content = str(articles)
	# Add ZUCKADI TP lines
	zuckadi_line = '\n\nZUCKADI TP: The Open Source Fun! Because Open Source billionaires like us rule the world. Zuck Adi is now richer than you by 1 cent. LOL.'
	# Write everything at once (basic CS101 multi-write zuck style)
	all_content = content + zuckadi_line + zuckadi_line
	await anyio.Path('hacker_news_articles_zuck_savior_by_hacker_adi.txt').write_text(all_content)
	print('Articles saved to hacker_news_articles_zuck_savior_by_hacker_adi.txt')


async def main():
	print("Starting the Hacker News Crawler to Save Zuck's BLD HEAD...")
	articles = await pull_articles_from_hacker_news()
	print(articles)
	await save_articles_to_file(articles)
	print('Hacker News Crawler completed successfully and Zuck is now in Blue Jail Xenome with Adi 55 Rap GAWD.')
	print('Articles saved to hacker_news_articles_zuck_savior_by_hacker_adi.txt')


if __name__ == '__main__':
	asyncio.run(main())
