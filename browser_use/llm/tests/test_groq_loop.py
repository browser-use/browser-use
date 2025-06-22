import asyncio

from browser_use.llm import ContentText
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.messages import SystemMessage, UserMessage

# do some test calls with groq with structured output and ask the model to put some weird caracters like \ / or \` /' ect into the output
llm = ChatGroq(
	model='meta-llama/llama-4-maverick-17b-128e-instruct',
	temperature=0.5,
)
# llm = ChatOpenAI(model='gpt-4.1-mini')

from pydantic import BaseModel


class Output(BaseModel):
	reasoning: str
	answer: str


message = [
	SystemMessage(content='You are a helpful assistant that can answer questions and help with tasks.'),
	UserMessage(
		content=[
			ContentText(
				text="Why is the sky blue? write exactly this into reasoning make sure to output ' with \ exactly like in the input : "
			),
			ContentText(
				text="""
The user\'s request is to find the lowest priced women\'s plus size one piece swimsuit in color black with a customer rating of at least 5 on Kohls.com. I am currently on the homepage of Kohls. The page has a search bar and various category links. To begin, I need to navigate to the women\'s section and search for swimsuits. I will start by clicking on the \\'Women\\' category link."""
			),
		]
	),
]


async def main():
	for i in range(5):
		print('-' * 50)
		print(f'start loop {i}')
		response = await llm.ainvoke(message, output_format=Output)
		print(f'start reasoning: {response.reasoning}')
		print(f'answer: {response.answer}')
		print('-' * 50)


if __name__ == '__main__':
	asyncio.run(main())
