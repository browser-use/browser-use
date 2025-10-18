import asyncio

from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use.llm.messages import UserMessage


class DummyCompletions:
    def __init__(self):
        self.called_with = None

    class Create:
        async def create(self, **kwargs):
            # Return a minimal fake response matching expected shape
            class Choice:
                class Msg:
                    content = 'ok'

                message = Msg()

            class Resp:
                choices = [Choice()]
                usage = None

            # capture passed kwargs for assertion
            DummyCompletions.last_kwargs = kwargs
            return Resp()


class DummyClient:
    def __init__(self):
        self.chat = type('c', (), {'completions': DummyCompletions.Create()})()


def test_extra_body_forwarded():
    async def run():
        model = ChatOpenRouter(model='test-model', extra_body={'foo': 'bar'})
        # set get_client to return a dummy client
        model.get_client = lambda: DummyClient()
        res = await model.ainvoke([UserMessage(content='hi')])
        assert res.completion == 'ok'
        # confirm extra_body was forwarded to create
        assert DummyCompletions.last_kwargs.get('extra_body') == {'foo': 'bar'}

    asyncio.get_event_loop().run_until_complete(run())
