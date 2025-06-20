import os
from dataclasses import dataclass
from typing import Optional

from browser_use.llm.openai.like import ChatOpenAILike


@dataclass
class ChatGroq(ChatOpenAILike):
	"""
	A class for interacting with Groq models.

	Attributes:
	    id (str): The id of the Groq model to use. Default is "groq/llama-3.3-70b-instruct".
	    name (str): The name of this chat model instance. Default is "Groq"
	    provider (str): The provider of the model. Default is "Groq".
	    api_key (str): The api key to authorize request to Groq.
	    base_url (str): The base url to which the requests are sent.
	"""

	model: str = 'meta-llama/llama-4-maverick-17b-128e-instruct'
	provider: str = 'Groq'
	name: str = 'Groq'

	api_key: Optional[str] = os.getenv('GROQ_API_KEY')
	base_url: str = 'https://api.groq.com/openai/v1'
