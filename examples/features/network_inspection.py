import asyncio
import os
import sys

# Ensure we can import from local source
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from browser_use import Agent, ChatBrowserUse

load_dotenv()


async def main():
	# 1. Define a task that requires network inspection
	task = """
    1. Go to https://hn.algolia.com/
    2. Type "Browser Automation" into the search box.
    3. Use the 'check_network_traffic' tool to find the network request that fetched the search results (filter for type 'XHR' or 'Fetch').
    4. Locate the URL that contains '/1/indexes/Item_dev/query'.
    5. Use the 'get_response_body' tool with that specific URL pattern to get the raw JSON response.
    6. From that raw JSON, extract the 'objectID' and 'title' of the very first result.
    7. Return ONLY the objectID and Title.
    """

	print(f'🚀 Starting Network Inspection Task:\n{task}\n')

	# 3. Create the Agent
	agent = Agent(task=task, llm=ChatBrowserUse())

	# 4. Run
	history = await agent.run()

	# 5. Output result
	print('\n-------------------------------------------------')
	print('Final Result:')
	print(history.final_result())
	print('-------------------------------------------------')


if __name__ == '__main__':
	asyncio.run(main())
