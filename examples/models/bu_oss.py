"""Run the open-weights Browser Use model on your own GPU.

`browser-use/bu-30b-a3b-preview` is published under
https://huggingface.co/browser-use/bu-30b-a3b-preview. It is open weights you host
yourself, not a model Browser Use Cloud serves for you, so it needs no
BROWSER_USE_API_KEY and has no per-token price.

Setup:
1. pip install vllm
2. vllm serve browser-use/bu-30b-a3b-preview --max-model-len 65536 --host 0.0.0.0 --port 8000
3. python examples/models/bu_oss.py

Point BU_OSS_BASE_URL at the server if it is not on localhost.
"""

import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

try:
	from lmnr import Laminar

	Laminar.initialize()
except ImportError:
	pass

# Any OpenAI-compatible server works; vLLM is what the model card recommends.
llm = ChatOpenAI(
	model='browser-use/bu-30b-a3b-preview',
	base_url=os.getenv('BU_OSS_BASE_URL', 'http://localhost:8000/v1'),
	api_key=os.getenv('BU_OSS_API_KEY', 'not-needed'),
)

agent = Agent(
	task='Find the number of stars of browser-use and stagehand. Tell me which one has more stars :)',
	llm=llm,
	flash_mode=True,
)
agent.run_sync()
