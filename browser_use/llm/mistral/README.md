# Mistral AI Integration

This directory contains the Mistral AI LLM integration for browser-use.

## Files

- `chat.py` - Main ChatMistral class implementing the BaseChatModel interface
- `serializer.py` - Message serialization between browser-use and Mistral formats
- `__init__.py` - Package initialization

## Usage

### Basic Usage

```python
from browser_use import Agent
from browser_use.llm import ChatMistral
import os

agent = Agent(
    task="Your task here",
    llm=ChatMistral(
        model="mistral-large-latest",
        api_key=os.getenv('MISTRAL_API_KEY')
    )
)
result = await agent.run()
```

### Using Convenience Models

```python
from browser_use import Agent, llm

agent = Agent(
    task="Your task here",
    llm=llm.mistral_large_latest
)
result = await agent.run()
```

### Available Models

- `mistral-large-latest` - Most capable Mistral model
- `mistral-small-latest` - Faster, more cost-effective model
- `codestral-latest` - Optimized for coding tasks

### Configuration Parameters

- `model` (str) - Model name (default: "mistral-large-latest")
- `api_key` (str) - Mistral API key
- `max_tokens` (int) - Maximum tokens in response
- `temperature` (float) - Sampling temperature (0.0-1.0)
- `top_p` (float) - Nucleus sampling parameter
- `random_seed` (int) - Random seed for reproducibility
- `endpoint` (str) - Custom API endpoint (optional)
- `timeout` (int) - Request timeout in seconds (default: 120)

## Features

- ✓ Text generation
- ✓ Function calling / Tool use
- ✓ Structured output (via function calling)
- ✓ Multi-turn conversations
- ✓ Image support (via image URLs)
- ✓ Proper error handling and rate limiting

## Environment Setup

Add your Mistral API key to `.env`:

```bash
MISTRAL_API_KEY=your_api_key_here
```

Get your API key from: https://console.mistral.ai/

## Example

```python
from browser_use import Agent
from browser_use.llm import ChatMistral
from dotenv import load_dotenv

load_dotenv()

async def main():
    agent = Agent(
        task="Go to google.com and search for 'browser-use github'",
        llm=ChatMistral(
            model="mistral-large-latest",
            temperature=0.7
        )
    )
    result = await agent.run()
    print(result)

import asyncio
asyncio.run(main())
```
