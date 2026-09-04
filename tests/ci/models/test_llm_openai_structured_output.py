from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


class StructuredAnswer(BaseModel):
	answer: str


class FakeChatOpenAI(ChatOpenAI):
	def __init__(self, content: str | None) -> None:
		super().__init__(model='gpt-4.1-mini', api_key='test')
		self.content = content

	def get_client(self):
		async def create(**kwargs):
			return SimpleNamespace(
				id='chatcmpl-empty',
				usage=None,
				choices=[
					SimpleNamespace(
						finish_reason='stop',
						message=SimpleNamespace(content=self.content),
					)
				],
			)

		return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize('content', [None, '', '   \n\t'])
async def test_openai_structured_output_empty_content_raises_provider_error(content):
	llm = FakeChatOpenAI(content)

	with pytest.raises(ModelProviderError) as exc_info:
		await llm.ainvoke([UserMessage(content='Return JSON')], output_format=StructuredAnswer)

	error = exc_info.value
	assert error.status_code == 502
	assert error.model == 'gpt-4.1-mini'
	assert 'empty structured output' in error.message
	assert 'response_id=chatcmpl-empty' in error.message
	assert 'finish_reason=stop' in error.message
