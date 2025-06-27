import asyncio
import os
import pathlib
import shutil

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm import ChatOpenAI

load_dotenv()

''
SCRIPT_DIR = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
agent_dir = SCRIPT_DIR / 'test_no_thinking'
agent_dir.mkdir(exist_ok=True)
conversation_dir = agent_dir / 'conversations' / 'conversation'
print(f'Agent logs directory: {agent_dir}')

try:
	from lmnr import Laminar

	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except Exception as e:
	print(f'Error initializing Laminar: {e}')

task = """
Go to https://mertunsall.github.io/posts/post1.html
Save the title of the article in "data.md"
Then, use append_file to add the first sentence of the article to "data.md"
Then, read the file to see its content and make sure it's correct.
Finally, share the file with me.

NOTE: DO NOT USE extract_structured_data action - everything is visible in browser state.
""".strip('\n')

llm = ChatOpenAI(
	model='gpt-4.1-mini',
)


agent = Agent(
	task=task,
	llm=llm,
	save_conversation_path=str(conversation_dir),
	file_system_path=str(agent_dir / 'fs'),
)


async def main():
	agent_history = await agent.run()
	print(f'Final result: {agent_history.final_result()}', flush=True)

	input('Press Enter to clean the file system...')
	# clean the file system
	shutil.rmtree(str(agent_dir / 'fs'))


if __name__ == '__main__':
	asyncio.run(main())
