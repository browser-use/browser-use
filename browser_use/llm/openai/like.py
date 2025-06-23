from dataclasses import dataclass

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatOpenAILike(ChatOpenAI):
	"""
	A class for to interact with any provider using the OpenAI API schema.

	Args:
	    model (str): The name of the OpenAI model to use. Defaults to "not-provided".
	    api_key (Optional[str]): The API key to use. Defaults to "not-provided".
	"""

	model: str
