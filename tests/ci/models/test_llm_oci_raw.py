"""ChatOCIRaw structured output must not rewrite the caller's messages."""

from types import SimpleNamespace

from pydantic import BaseModel

from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.oci_raw.chat import ChatOCIRaw


class Answer(BaseModel):
	answer: str


async def test_structured_output_leaves_system_message_untouched():
	llm = ChatOCIRaw(
		model_id='ocid1.model.oc1.test', service_endpoint='https://example.test', compartment_id='ocid1.compartment.test'
	)
	sent: list[list] = []

	async def fake_request(messages):
		sent.append(messages)
		return SimpleNamespace(data=SimpleNamespace(chat_response=SimpleNamespace(text='{"answer": "ok"}')))

	llm._make_request = fake_request  # type: ignore[method-assign]

	system = SystemMessage(content='You are a browser agent.')
	messages = [system, UserMessage(content='go')]

	for _ in range(3):
		result = await llm.ainvoke(messages, Answer)
		assert result.completion == Answer(answer='ok')

	assert system.content == 'You are a browser agent.'
	assert len(messages) == 2
	# Every request carried the schema instruction exactly once
	for request in sent:
		assert isinstance(request[0].content, str)
		assert request[0].content.count('You must respond with ONLY a valid JSON object') == 1
