import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()
import asyncio

# get an api key from https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key
api_key = os.getenv('ALIBABA_CLOUD')
base_url = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'

# so far we only had success with qwen-vl-max
# other models, even qwen-max, do not return the right output format. They confuse the action schema.
# E.g. they return actions: [{"navigate": "google.com"}] instead of [{"navigate": {"url": "google.com"}}]
# If you want to use smaller models and you see they mix up the action schema, add concrete examples to your prompt of the right format.
llm = ChatOpenAI(model='qwen-vl-max', api_key=api_key, base_url=base_url)


async def main():
	agent = Agent(task='go find the founders of browser-use', llm=llm, use_vision=True, max_actions_per_step=1)
	await agent.run()


if '__main__' == __name__:
	asyncio.run(main())
