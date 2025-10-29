# import asyncio
# import os
# from browser_use.llm import ChatDeepSeek
# from browser_use.llm.messages import SystemMessage, UserMessage

# async def test_llm():
#     llm = ChatDeepSeek(
#         model="deepseek/deepseek-chat-v3.1:free",
#         base_url='https://openrouter.ai/api/v1',
#         api_key=os.getenv('OPENROUTER_API_KEY')
#     )
#     messages = [
#         SystemMessage(content="You are a helpful assistant."),
#         UserMessage(content="Test: Can you respond with 'Hello'?")
#     ]
#     response = await llm.ainvoke(messages)
#     print(response.completion)

# asyncio.run(test_llm())

import asyncio
from browser_use.llm.openai.chat import ChatOpenAI  # Use ChatOpenAI instead
from browser_use.llm.messages import SystemMessage, UserMessage
import os
from dotenv import load_dotenv

load_dotenv()

async def test_llm():
    llm = ChatOpenAI(
        model="openai/gpt-oss-20b:free",
        base_url='https://openrouter.ai/api/v1',
        api_key=os.getenv('OPENROUTER_API_KEY')
    )
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        UserMessage(content="Test: Can you respond with 'Hello'?")
    ]
    response = await llm.ainvoke(messages)
    print(response.completion)

asyncio.run(test_llm())