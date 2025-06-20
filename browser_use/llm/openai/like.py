from dataclasses import dataclass
from typing import Optional

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatOpenAILike(ChatOpenAI):
	"""
	A class for to interact with any provider using the OpenAI API schema.

	Args:
	    model_name (str): The name of the OpenAI model to use. Defaults to "not-provided".
	    api_key (Optional[str]): The API key to use. Defaults to "not-provided".
	"""

	model_name: str
	provider: str = 'OpenAILike'
	name: str = 'OpenAILike'

	api_key: Optional[str] = 'not-provided'
