import os
import asyncio
from browser_use.llm.huggingface.chat import ChatHuggingFace
from browser_use.llm import SystemMessage, UserMessage

# Optional: override if you use a custom Inference Endpoint provider
# os.environ["HF_OPENAI_API_BASE"] = "https://<your-endpoint-host>/v1"


async def main():
	llm = ChatHuggingFace(
		model='openai/gpt-oss-20b:hyperbolic',
		api_key=os.getenv('HUGGINGFACE_API_KEY') or os.getenv('HF_API_KEY'),
		base_url=os.getenv('HF_OPENAI_API_BASE') or 'https://router.huggingface.co/v1',
	)

	messages = [
		SystemMessage(content='You are a helpful assistant.'),
		UserMessage(content='Say hi in one short sentence.'),
	]

	resp = await llm.ainvoke(messages)
	print('Model:', llm.model)
	print('Provider:', llm.provider)
	print('Reply:', resp.completion)


asyncio.run(main())
