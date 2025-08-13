#Tests for the gpt-oss:20b
import pytest
import json
from pydantic import BaseModel
from browser_use import Agent
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.messages import UserMessage
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.llm.exceptions import ModelProviderError


class ExampleOutput(BaseModel):
    name: str


@pytest.mark.asyncio
async def test_gptoss_plain_text(monkeypatch):
    """GPT-OSS without output_format returns plain string."""
    async def mock_chat(*args, **kwargs):
        class MockResp:
            message = type("m", (), {"content": "Hello GPT-OSS"})
        return MockResp()

    monkeypatch.setattr(ChatOllama, "get_client", lambda self: type("c", (), {"chat": mock_chat})())

    llm = ChatOllama(model="qwen3:8b", host="http://...") #replace wth actual host and change the model name to gpt-oss:20b
    result = await llm.ainvoke([UserMessage(content="Hello")])
    assert isinstance(result, ChatInvokeCompletion)
    assert result.completion == "Hello GPT-OSS"


@pytest.mark.asyncio
async def test_gptoss_with_valid_json(monkeypatch):
    """GPT-OSS with output_format and valid JSON parses correctly."""
    async def mock_chat(*args, **kwargs):
        class MockResp:
            message = type("m", (), {"content": '{"name": "Browser Use"}'})
        return MockResp()

    monkeypatch.setattr(ChatOllama, "get_client", lambda self: type("c", (), {"chat": mock_chat})())

    llm = ChatOllama(model="qwen3:8b", host="http://...") #replace with actual host and change the model name to gpt-oss:20b
    result = await llm.ainvoke([UserMessage(content="Hello")], output_format=ExampleOutput)
    assert result.completion.name == "Browser Use"


@pytest.mark.asyncio
async def test_gptoss_with_invalid_json(monkeypatch):
    """GPT-OSS with output_format but invalid JSON returns raw string."""
    async def mock_chat(*args, **kwargs):
        class MockResp:
            message = type("m", (), {"content": "Not JSON output"})
        return MockResp()

    monkeypatch.setattr(ChatOllama, "get_client", lambda self: type("c", (), {"chat": mock_chat})())

    llm = ChatOllama(model="qwen3:8b", host="http://...") # replace with actual host and change the model name to gpt-oss:20b
    result = await llm.ainvoke([UserMessage(content="Hello")], output_format=ExampleOutput)
    assert result.completion == "Not JSON output"


@pytest.mark.asyncio
async def test_non_gptoss_with_output_format(monkeypatch):
    """Non-GPT-OSS with output_format should use Pydantic JSON parsing."""
    data = ExampleOutput(name="Normal Ollama").model_dump_json()

    async def mock_chat(*args, **kwargs):
        class MockResp:
            message = type("m", (), {"content": data})
        return MockResp()

    monkeypatch.setattr(ChatOllama, "get_client", lambda self: type("c", (), {"chat": mock_chat})())

    llm = ChatOllama(model="llama2:7b", host="http://...") # replace with actual host and no change in model name
    result = await llm.ainvoke([UserMessage(content="Hello")], output_format=ExampleOutput)
    assert result.completion.name == "Normal Ollama"


@pytest.mark.asyncio
async def test_model_provider_error(monkeypatch):
    """If chat() raises exception, ModelProviderError should be raised."""
    async def mock_chat(*args, **kwargs):
        raise RuntimeError("Connection failed")

    monkeypatch.setattr(ChatOllama, "get_client", lambda self: type("c", (), {"chat": mock_chat})())

    llm = ChatOllama(model="qwen3:8b", host="http://...") #replace with actual host and change the model name to gpt-oss:20b
    with pytest.raises(ModelProviderError) as excinfo:
        await llm.ainvoke([UserMessage(content="Hello")])
    assert "Connection failed" in str(excinfo.value)


def test_provider_and_name_and_client_params():
    """Test provider, name, and _get_client_params output."""
    llm = ChatOllama(model="qwen3:8b", host="http://...", timeout=5, client_params={"a": 1}) #replace with actual host and change the model name to gpt-oss:20b
    assert llm.provider == "ollama"
    assert llm.name == "gpt-oss:20b"
    params = llm._get_client_params()
    assert params["host"] == "http://10.20.20.100:11434"
    assert params["timeout"] == 5
    assert params["client_params"] == {"a": 1}
