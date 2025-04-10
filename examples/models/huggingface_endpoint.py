import asyncio
import os

from dotenv import load_dotenv
from pydantic import SecretStr
from langchain_huggingface import ChatHuggingFace
from browser_use import Agent

# please add following var to your .env file

load_dotenv()
hf_endpoint = os.getenv("HUGGINGFACE_ENDPOINT_URL", "")
hf_token = os.getenv("HUGGINGFACE_API_TOKEN", "")
if not hf_endpoint or not hf_token:
    raise ValueError("HUGGINGFACE_ENDPOINT_URL or HUGGINGFACE_API_TOKEN not set")

async def run_hf_agent():
    # Instantiate the HF-backed LLM
    llm = ChatHuggingFace(
        endpoint_url=hf_endpoint,
        huggingfacehub_api_token=SecretStr(hf_token),
        # You can pass any additional params your endpoint supports, e.g. model_kwargs:
        model_kwargs={"temperature": 0.2, "max_new_tokens": 256},
    )

    # Define your browsing task
    task = (
        "Go to wikipedia.org, search for 'Mistral AI', "
        "open the first result, and give me the first paragraph of the article."
    )

    agent = Agent(
        task=task,
        llm=llm,
        use_vision=False,
        max_failures=3,
        max_actions_per_step=2,
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(run_hf_agent())
