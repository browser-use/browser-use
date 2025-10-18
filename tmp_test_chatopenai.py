import asyncio
import logging
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.messages import BaseMessage

# Setup minimal logging
logging.basicConfig(level=logging.DEBUG)

class DummyChoice:
    def __init__(self, content):
        class Msg:
            def __init__(self, content):
                self.content = content
        self.message = Msg(content)

import asyncio
import logging
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.messages import UserMessage

# Setup minimal logging
logging.basicConfig(level=logging.DEBUG)


class DummyChoice:
    def __init__(self, content):
        class Msg:
            def __init__(self, content):
                self.content = content
        self.message = Msg(content)


class DummyResponse:
    def __init__(self, text):
        self.choices = [DummyChoice(text)]
        class Usage:
            def __init__(self):
                self.prompt_tokens = 5
                self.completion_tokens = 10
                self.total_tokens = 15
                self.prompt_tokens_details = None
                self.completion_tokens_details = None
        self.usage = Usage()


class DummyCompletions:
    class Create:
        async def create(self, **kwargs):
            return DummyResponse('hello from dummy')


class DummyClient:
    def __init__(self):
        self.chat = type('c', (), {'completions': DummyCompletions.Create()})()


async def main():
    model = ChatOpenAI(model='gpt-test')
    # monkeypatch get_client
    model.get_client = lambda: DummyClient()
    # create a UserMessage instance
    msg = UserMessage(content='say hi')
    res = await model.ainvoke([msg])
    print('completion:', res.completion)


asyncio.run(main())
