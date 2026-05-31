"""Regression tests for provider serializers handling tool result messages."""

from typing import Any, cast

from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.aws.serializer import AWSBedrockMessageSerializer
from browser_use.llm.cerebras.serializer import CerebrasMessageSerializer
from browser_use.llm.deepseek.serializer import DeepSeekMessageSerializer
from browser_use.llm.groq.serializer import GroqMessageSerializer
from browser_use.llm.messages import ToolMessage
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.openai.responses_serializer import ResponsesAPIMessageSerializer


def test_tool_message_serializes_for_provider_formats():
	message = ToolMessage(tool_call_id='call_123', name='browser.done', content='{"success": true}')

	anthropic = AnthropicMessageSerializer.serialize(message)
	assert anthropic['role'] == 'user'
	anthropic_content = anthropic['content']
	assert isinstance(anthropic_content, list)
	anthropic_block = cast(dict[str, Any], anthropic_content[0])
	assert anthropic_block['type'] == 'tool_result'
	assert anthropic_block['tool_use_id'] == 'call_123'

	aws = AWSBedrockMessageSerializer.serialize(message)
	assert aws['role'] == 'user'
	assert aws['content'][0]['toolResult']['toolUseId'] == 'call_123'
	assert aws['content'][0]['toolResult']['content'][0]['text'] == '{"success": true}'

	cerebras = CerebrasMessageSerializer.serialize(message)
	assert cerebras == {
		'role': 'tool',
		'content': '{"success": true}',
		'tool_call_id': 'call_123',
		'name': 'browser.done',
	}

	deepseek = DeepSeekMessageSerializer.serialize(message)
	assert deepseek == cerebras

	groq = GroqMessageSerializer.serialize(message)
	assert groq['role'] == 'tool'
	assert groq['content'] == '{"success": true}'
	assert groq['tool_call_id'] == 'call_123'

	ollama = OllamaMessageSerializer.serialize(message)
	assert ollama.role == 'tool'
	assert ollama.content == '{"success": true}'
	assert ollama.tool_name == 'browser.done'

	responses = ResponsesAPIMessageSerializer.serialize(message)
	assert responses['role'] == 'user'
	assert 'call_123' in responses['content']
	assert '{"success": true}' in responses['content']
