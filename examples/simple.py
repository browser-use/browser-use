"""
Setup:
1. uv add 'browser-use>=1.0.0.dev0'   (1.0 is a pre-release)
2. browser-use login   (opens your browser; or export BROWSER_USE_API_KEY=...)

Runs on the default model (bu-ultrafast) in a Browser Use Cloud browser. For your own Chrome and model:
    Agent(task, llm=ChatOpenAI('gpt-6-luna'), browser=Browser(local=True))
"""

from browser_use import Agent

agent = Agent('Find the number of stars of the following repos: browser-use, playwright, stagehand, react, nextjs')
result = agent.run_sync()
print(result.final_result())
