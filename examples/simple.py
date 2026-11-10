"""
Setup:
1. uv init --python 3.12 my-agent && cd my-agent && uv add 'browser-use==1.0.0'
2. export BROWSER_USE_API_KEY=bu_...   (get one at https://cloud.browser-use.com/new-api-key)

Runs on the default model (bu-fast) in a Browser Use Cloud browser. For a local browser and your own model:
    Agent(task, llm=ChatOpenAI('gpt-6-luna'), browser=Browser('chromium'))   # or Browser('chrome'): your open Chrome
"""

from browser_use import Agent

agent = Agent('Find the number of stars of the following repos: browser-use, playwright, stagehand, react, nextjs')
result = agent.run_sync()
print(result.final_result())
