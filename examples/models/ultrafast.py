"""
Self-hosted OpenAI-compatible endpoint driven with the `ultrafast` agent preset.

`ultrafast=True` is tuned for small self-hosted models: reasoning is capped inside a JSON
field, screenshots are sent only on request (`use_vision='auto'`), and the extra LLM round
trips (planning, judging, compaction) are switched off.

Setup:
	export ULTRAFAST_BASE_URL="https://your-endpoint/v1"
	export ULTRAFAST_API_KEY="your-key"

Browser paths below are macOS. Point them at your own Chrome to reuse a logged-in profile
(close Chrome first - a running instance holds a lock on the user data dir).
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatOpenAI

load_dotenv()

# Qwen3 needs top_k/top_p exactly like this, and `enable_thinking: False` is not optional:
# thinking defaults on, and leaving it enabled costs ~30s per step instead of ~1.5s.
llm = ChatOpenAI(
	model=os.getenv('ULTRAFAST_MODEL', 'ultrafast'),
	base_url=os.environ['ULTRAFAST_BASE_URL'],
	api_key=os.environ['ULTRAFAST_API_KEY'],
	temperature=0.7,
	top_p=0.8,
	presence_penalty=0.0,
	frequency_penalty=0.0,
	extra_body={
		'top_k': 20,
		'chat_template_kwargs': {'enable_thinking': False, 'preserve_thinking': False},
	},
)

browser = Browser(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	user_data_dir='~/Library/Application Support/Google/Chrome',
	profile_directory='Default',
)

task = """
Go to target.com and add these to the cart, set for delivery (not pickup):
- Hues and Cues board game
- Pack of big claw hair clips
- Starbursts
- Birthday wrapping paper for a young girl
Add them one at a time, confirming each is in the cart before starting the next.
Then go to checkout and stop as soon as it asks for a credit card or address.
"""

asyncio.run(Agent(task=task, llm=llm, browser=browser, ultrafast=True).run(max_steps=120))
