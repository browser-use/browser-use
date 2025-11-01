import asyncio
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent, ChatOpenAI

extend_system_message = (
	'REMEMBER the most important RULE: ALWAYS open first a new tab and go first to url wikipedia.com no matter the task!!!'
)

# or use override_system_message to completely override the system prompt


async def main():
	task = 'do google search to find images of Elon Musk'
	model = ChatOpenAI(model='gpt-4.1-mini')
	agent = Agent(task=task, llm=model, extend_system_message=extend_system_message)

	print(
		json.dumps(
			agent.message_manager.system_prompt.model_dump(exclude_unset=True),
			indent=4,
		)
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
