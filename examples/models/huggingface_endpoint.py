import asyncio
import os

from dotenv import load_dotenv
from pydantic import SecretStr
from langchain_huggingface import ChatHuggingFace
from browser_use import Agent

# Required environment variables:
# Add the following lines to your `.env` file:
# HUGGINGFACE_ENDPOINT_URL=https://api-inference.huggingface.co/models/<your-model-name>
# HUGGINGFACE_API_TOKEN=hf_XXXXXXXXXXXXXXXXXXXXXXXXXXXX
#  Get your API token from: https://huggingface.co/settings/tokens
#  Create an inference endpoint at: https://huggingface.co/inference-endpoints

load_dotenv()
hf_endpoint = os.getenv("HUGGINGFACE_ENDPOINT_URL", "")
hf_token = os.getenv("HUGGINGFACE_API_TOKEN", "")

# 🚨 Improved error message for clarity
missing_vars = []
if not hf_endpoint:
    missing_vars.append("HUGGINGFACE_ENDPOINT_URL")
if not hf_token:
    missing_vars.append("HUGGINGFACE_API_TOKEN")

if missing_vars:
    raise ValueError(f"Missing required environment variable(s): {', '.join(missing_vars)}")

async def run_hf_agent():
    # Instantiate the HF-backed LLM
    llm = ChatHuggingFace(
        endpoint_url=hf_endpoint,
        huggingfacehub_api_token=SecretStr(hf_token),
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
