from browser_use import Agent, ChatGoogle, ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

agent = Agent(
    task="Find Jeff ZQ Cheng on linkedin and go into his profile",
    llm=ChatOpenAI(model="gpt-5-nano"),
    # browser=Browser(use_cloud=True),  # Uses Browser-Use cloud for the browser
)
agent.run_sync()


#```​:codex-file-citation[codex-file-citation]{line_range_start=54 line_range_end=67 path=README.md git_url="https://github.com/BigDjeff/browser-use/blob/main/README.md#L54-L67"}​

