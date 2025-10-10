import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.messages import UserMessage


@dataclass
class DummyMessage:
    content: Any


@dataclass
class DummyChoice:
    message: DummyMessage


@dataclass
class DummyResponse:
    choices: list
    usage: Any = None


class DummyClient:
    class chat:
        class completions:
            @staticmethod
            async def create(*args, **kwargs):
                # return a simple echo in the same structure expected
                return DummyResponse(choices=[DummyChoice(message=DummyMessage(content='echo'))])


def test_chatopenai_ainvoke_echo(monkeypatch):
    # Create ChatOpenAI with a dummy client to avoid real network calls
    chat = ChatOpenAI(model='gpt-4.1-mini', api_key='test')

    def fake_get_client():
        return DummyClient()

    monkeypatch.setattr(chat, 'get_client', fake_get_client)

    async def run_once():
        resp = await chat.ainvoke([UserMessage(content='hello')])
        return resp

    result = asyncio.run(run_once())

    # Assert that we received the expected echo completion
    assert result.completion == 'echo'
