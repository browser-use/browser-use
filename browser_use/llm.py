import re
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrock
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_fireworks import ChatFireworks
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai import ChatVertexAI
from langchain_groq import ChatGroq
from langchain_huggingface import ChatHuggingFace
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_together import ChatTogether


class LLM:
    model_provider: str
    model_name: str
    model: BaseChatModel

    def __init__(self, model: str, **kwargs: Any) -> None:
        # Define the regex pattern for model_id: model_provider/model_name
        pattern = r"^([a-zA-Z0-9\_\-\.]+)/([a-zA-Z0-9\_\-\.]+)$"
        match = re.match(pattern, model)
        if not match:
            raise ValueError(f'Invalid model format: "{model}". Expected format "model_provider/model_name".')

        self.model_provider, self.model_name = match.groups()

        # Initialize the appropriate model based on the provider
        if self.model_provider == "openai":
            self.model = ChatOpenAI(model=self.model_name, **kwargs)
        elif self.model_provider == "azure":
            self.model = AzureChatOpenAI(model=self.model_name, **kwargs)
        elif self.model_provider == "anthropic":
            self.model = ChatAnthropic(model_name=self.model_name, **kwargs)
        elif self.model_provider == "gemini":
            self.model = ChatGoogleGenerativeAI(model=self.model_name, **kwargs)
        elif self.model_provider == "vertex_ai":
            self.model = ChatVertexAI(model=self.model_name, **kwargs)
        elif self.model_provider == "groq":
            self.model = ChatGroq(model=self.model_name, **kwargs)
        elif self.model_provider == "ollama":
            self.model = ChatOllama(model=self.model_name, **kwargs)
        elif self.model_provider == "fireworks_ai":
            self.model = ChatFireworks(model=self.model_name, **kwargs)
        elif self.model_provider == "bedrock":
            self.model = ChatBedrock(model=self.model_name, **kwargs)
        elif self.model_provider == "together_ai":
            self.model = ChatTogether(model=self.model_name, **kwargs)
        elif self.model_provider == "huggingface":
            self.model = ChatHuggingFace(model=self.model_name, **kwargs)
        elif self.model_provider == "deepseek":
            self.model = ChatDeepSeek(model=self.model_name, **kwargs)
        else:
            raise ValueError(f'The model provider "{self.model_provider}" is not supported.')
